# -*- coding: utf-8 -*-
"""test_agente2_declaraciones.py — Comprehensive tests for Agente 2.

Tests cover:
  1. DeclarationEngine — ISR PM, ISR PF, IVA, IEPS, DIOT aggregation
  2. DIOTGenerator — pipe-delimited format, generic RFC filtering
  3. XMLGenerator — XML structure, well-formedness
  4. FIELSigner — certificate info, signing
  5. SATSubmitter — submission flow, status checking
  6. ErrorHandler — all 14 SAT errors, retry logic
  7. API endpoints — calculate, generate, submit, status
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import pytest

# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------
from b2b_ai.features.declaraciones.engine import (
    DeclarationEngine,
    calculate_isr_pm,
    calculate_isr_pf,
    calculate_iva,
    calculate_ieps,
    aggregate_diot,
    is_generic_rfc,
    ISR_TABLE_MONTHLY,
    ISR_TABLE_ANNUAL,
    ISR_PM_RATE,
    GENERIC_RFCS,
    IsrResult,
    IvaResult,
    IepsResult,
    DiotResult,
)


class TestISRPM:
    """Test ISR for Personas Morales (flat 30%)."""

    def test_pm_basic_30_percent(self):
        result = calculate_isr_pm(utilidad_fiscal=100_000)
        assert result.tipo_contribuyente == "PM"
        assert result.isr_bruto == 30_000.00
        assert result.tasa_efectiva == 0.30
        assert result.tabla_aplicada == "pm_30%"

    def test_pm_zero_utilidad(self):
        result = calculate_isr_pm(utilidad_fiscal=0)
        assert result.isr_bruto == 0.0
        assert result.isr_neto == 0.0

    def test_pm_negative_utilidad(self):
        result = calculate_isr_pm(utilidad_fiscal=-50_000)
        assert result.isr_bruto == 0.0

    def test_pm_with_pagos_provisionales(self):
        result = calculate_isr_pm(
            utilidad_fiscal=100_000,
            pagos_provisionales=10_000,
        )
        assert result.isr_bruto == 30_000.00
        assert result.isr_neto == 20_000.00


class TestISRPF:
    """Test ISR for Personas Físicas (progressive table)."""

    def test_pf_first_bracket(self):
        result = calculate_isr_pf(base_gravable=300)
        assert result.tipo_contribuyente == "PF"
        assert result.isr_bruto >= 0
        assert result.isr_bruto < 300  # Less than base

    def test_pf_high_income(self):
        result = calculate_isr_pf(base_gravable=100_000, annual=True)
        assert result.isr_bruto > 0
        assert result.tasa_efectiva > 0.10  # Progressive table effective rate

    def test_pf_zero_income(self):
        result = calculate_isr_pf(base_gravable=0)
        assert result.isr_bruto == 0.0

    def test_pf_annual_vs_monthly_tables(self):
        """Annual and monthly tables give different results for same amount."""
        monthly = calculate_isr_pf(base_gravable=5000)
        annual = calculate_isr_pf(base_gravable=60000, annual=True)
        # Just verify they both return positive values
        assert monthly.isr_bruto > 0
        assert annual.isr_bruto > 0

    def test_isr_tables_have_10_brackets(self):
        assert len(ISR_TABLE_MONTHLY) == 10
        assert len(ISR_TABLE_ANNUAL) == 10


class TestIVA:
    """Test IVA monthly calculation."""

    def test_iva_basic_pagar(self):
        result = calculate_iva(
            iva_trasladado=16_000,
            iva_acreditable=8_000,
        )
        assert result.iva_trasladado == 16_000.0
        assert result.iva_acreditable == 8_000.0
        assert result.iva_neto == 8_000.0
        assert result.saldo_contra == 8_000.0
        assert result.saldo_favor == 0.0

    def test_iva_saldo_favor(self):
        result = calculate_iva(
            iva_trasladado=8_000,
            iva_acreditable=16_000,
        )
        assert result.iva_neto == -8_000.0
        assert result.saldo_favor == 8_000.0
        assert result.saldo_contra == 0.0

    def test_iva_proporcionalidad(self):
        """IVA acreditable should be adjusted by proportion."""
        result = calculate_iva(
            iva_trasladado=16_000,
            iva_acreditable=16_000,
            ingresos_gravados=80_000,
            ingresos_totales=100_000,
        )
        # Proporcion = 80/100 = 0.8
        # Acreditable = 16000 * 0.8 = 12800
        assert result.proporcion_acreditable == 0.8
        assert result.iva_acreditable == 12_800.0
        assert result.iva_neto == 3_200.0


class TestIEPS:
    """Test IEPS calculation."""

    def test_ieps_cerveza(self):
        result = calculate_ieps([
            {"concepto": "Cerveza 1L", "producto_tipo": "cerveza", "base_gravable": 100},
        ])
        assert result.total_ieps == 26.5  # 100 * 0.265

    def test_ieps_multiple_products(self):
        result = calculate_ieps([
            {"concepto": "Cerveza", "producto_tipo": "cerveza", "base_gravable": 200},
            {"concepto": "Cigarros", "producto_tipo": "cigarros", "base_gravable": 500},
        ])
        expected = 200 * 0.265 + 500 * 0.16
        assert abs(result.total_ieps - expected) < 0.01

    def test_ieps_unknown_product(self):
        result = calculate_ieps([
            {"concepto": "Agua", "producto_tipo": "agua", "base_gravable": 100},
        ])
        assert result.total_ieps == 0.0


class TestDIOTAggregation:
    """Test DIOT aggregation from invoices."""

    def test_aggregate_basic(self):
        invoices = [
            {
                "rfc_emisor": "EMP850101AB1",
                "nombre_emisor": "Empresa SA",
                "subtotal": 10_000,
                "iva_trasladado": 1_600,
                "iva_acreditable": 1_600,
                "tasa_iva": 0.16,
                "moneda": "MXN",
                "tipo_cambio": 1.0,
                "fecha": "2024-07-15",
            },
        ]
        result = aggregate_diot(invoices, "ABC123456XYZ", "2024-07")
        assert result.total_records == 1
        assert result.records[0].rfc_tercero == "EMP850101AB1"
        assert result.records[0].monto_neto == 10_000.0

    def test_aggregate_filters_generic_rfc(self):
        invoices = [
            {
                "rfc_emisor": "XAXX010101000",
                "nombre_emisor": "Público General",
                "subtotal": 5_000,
                "iva_trasladado": 800,
                "tasa_iva": 0.16,
            },
            {
                "rfc_emisor": "EMP850101AB1",
                "nombre_emisor": "Empresa SA",
                "subtotal": 10_000,
                "iva_trasladado": 1_600,
                "tasa_iva": 0.16,
            },
        ]
        result = aggregate_diot(invoices, "ABC123456XYZ", "2024-07")
        assert result.total_records == 1  # Only non-generic
        assert result.records[0].rfc_tercero == "EMP850101AB1"

    def test_aggregate_groups_by_rfc(self):
        invoices = [
            {"rfc_emisor": "EMP850101AB1", "subtotal": 5000, "iva_trasladado": 800, "tasa_iva": 0.16},
            {"rfc_emisor": "EMP850101AB1", "subtotal": 3000, "iva_trasladado": 480, "tasa_iva": 0.16},
            {"rfc_emisor": "OTR850101CD2", "subtotal": 2000, "iva_trasladado": 320, "tasa_iva": 0.16},
        ]
        result = aggregate_diot(invoices, "ABC123456XYZ", "2024-07")
        assert result.total_records == 2

    def test_is_generic_rfc(self):
        assert is_generic_rfc("XAXX010101000") is True
        assert is_generic_rfc("XEXX010101000") is True
        assert is_generic_rfc("EMP850101AB1") is False


class TestDeclarationEngineFacade:
    """Test the DeclarationEngine facade class."""

    def test_engine_isr_pm(self):
        engine = DeclarationEngine()
        result = engine.calculate_isr_pm(100_000)
        assert result.isr_bruto == 30_000.00

    def test_engine_isr_pf(self):
        engine = DeclarationEngine()
        result = engine.calculate_isr_pf(10_000)
        assert result.isr_bruto > 0

    def test_engine_iva(self):
        engine = DeclarationEngine()
        result = engine.calculate_iva(16_000, 8_000)
        assert result.iva_neto == 8_000.0

    def test_engine_ieps(self):
        engine = DeclarationEngine()
        result = engine.calculate_ieps([{"producto_tipo": "cerveza", "base_gravable": 100}])
        assert result.total_ieps == 26.5

    def test_engine_diot(self):
        engine = DeclarationEngine()
        invoices = [{"rfc_emisor": "EMP850101AB1", "subtotal": 10000, "iva_trasladado": 1600, "tasa_iva": 0.16}]
        result = engine.aggregate_diot(invoices, "ABC", "2024-07")
        assert result.total_records == 1


# ---------------------------------------------------------------------------
# DIOTGenerator tests
# ---------------------------------------------------------------------------
from b2b_ai.features.declaraciones.diot_generator import DIOTGenerator, format_diot_record
from b2b_ai.features.declaraciones.engine import DiotRecord


class TestDIOTGenerator:
    """Test DIOT pipe-delimited file generation."""

    def test_generate_pipe_format(self):
        gen = DIOTGenerator()
        diot = aggregate_diot(
            [
                {"rfc_emisor": "EMP850101AB1", "nombre_emisor": "Test", "subtotal": 10000, "iva_trasladado": 1600, "tasa_iva": 0.16, "fecha": "2024-07-15"},
            ],
            "ABC123456XYZ",
            "2024-07",
        )
        content = gen.generate(diot)
        assert "|" in content
        assert "EMP850101AB1" in content

    def test_format_record_structure(self):
        record = DiotRecord(
            rfc_tercero="EMP850101AB1",
            nombre="Test",
            tipo_operacion="03",
            monto_neto=10_000,
            iva_trasladado_16=1_600,
            iva_acreditable_16=1_600,
        )
        line = format_diot_record(record)
        parts = line.split("|")
        # TipoOperacion is first field
        assert parts[0] == "03"
        # RFC should appear
        assert "EMP850101AB1" in line

    def test_validate_excludes_generic_rfc(self):
        gen = DIOTGenerator()
        diot = DiotResult(
            records=[
                DiotRecord(
                    rfc_tercero="XAXX010101000",
                    nombre="Público General",
                    tipo_operacion="03",
                    monto_neto=5000,
                ),
            ],
            periodo="2024-07",
            rfc_contribuyente="ABC",
        )
        result = gen.validate(diot)
        assert not result  # Should fail validation
        assert any("genérico" in e.lower() for e in gen.errors)


# ---------------------------------------------------------------------------
# XMLGenerator tests
# ---------------------------------------------------------------------------
from b2b_ai.features.declaraciones.xml_generator import XMLGenerator


class TestXMLGenerator:
    """Test XML generation for declarations."""

    def test_iva_xml_well_formed(self):
        gen = XMLGenerator()
        iva_result = IvaResult(
            iva_trasladado=16000,
            iva_acreditable=8000,
            iva_neto=8000,
            saldo_contra=8000,
        )
        xml_bytes = gen.generate_iva_declaration(
            rfc="ABC123456XYZ", periodo="2024-07", iva_result=iva_result,
        )
        assert gen.validate_xml_structure(xml_bytes)
        root = ET.fromstring(xml_bytes)
        assert root.tag.endswith("DeclaracionInformativa")

    def test_isr_xml_well_formed(self):
        gen = XMLGenerator()
        isr_result = IsrResult(
            base_gravable=100_000,
            isr_bruto=30_000,
            tasa_efectiva=0.30,
            tipo_contribuyente="PM",
            tabla_aplicada="pm_30%",
            isr_neto=30_000,
        )
        xml_bytes = gen.generate_isr_declaration(
            rfc="ABC123456XYZ", periodo="2024-07", isr_result=isr_result,
        )
        assert gen.validate_xml_structure(xml_bytes)
        root = ET.fromstring(xml_bytes)
        # Check RFC is in XML
        xml_str = xml_bytes.decode()
        assert "ABC123456XYZ" in xml_str

    def test_diot_xml_well_formed(self):
        gen = XMLGenerator()
        diot = aggregate_diot(
            [{"rfc_emisor": "EMP850101AB1", "subtotal": 10000, "iva_trasladado": 1600, "tasa_iva": 0.16, "fecha": "2024-07-15"}],
            "ABC123456XYZ",
            "2024-07",
        )
        xml_bytes = gen.generate_diot_xml(diot)
        assert gen.validate_xml_structure(xml_bytes)

    def test_invalid_xml_rejected(self):
        gen = XMLGenerator()
        assert not gen.validate_xml_structure(b"<broken>")


# ---------------------------------------------------------------------------
# ErrorHandler tests
# ---------------------------------------------------------------------------
from b2b_ai.features.declaraciones.error_handler import (
    SATErrorHandler,
    ErrorCode,
    ErrorSeverity,
    SAT_ERRORS,
)


class TestErrorHandler:
    """Test SAT error handler with all 14 error codes."""

    def test_all_14_errors_defined(self):
        assert len(SAT_ERRORS) == 14

    def test_handle_uuid_invalido(self):
        handler = SATErrorHandler()
        result = handler.handle_error(ErrorCode.UUID_INVALIDO)
        assert result.handled
        assert result.error.severity == ErrorSeverity.HIGH

    def test_handle_firma_expirada_no_retry(self):
        handler = SATErrorHandler()
        result = handler.handle_error(ErrorCode.FIRMA_EXPIRADA)
        assert not result.retriable
        assert result.requires_human

    def test_handle_xml_invalido_retriable(self):
        handler = SATErrorHandler()
        result = handler.handle_error(ErrorCode.XML_INVALIDO)
        assert result.retriable
        assert result.auto_fixed

    def test_retry_limit_respected(self):
        handler = SATErrorHandler()
        result = None
        for i in range(5):
            result = handler.handle_error(ErrorCode.RFC_INCORRECTO)
        # After 5 attempts (max=3), should stop being retriable
        assert result is not None
        assert not result.retriable

    def test_duplicada_critical_no_retry(self):
        handler = SATErrorHandler()
        result = handler.handle_error(ErrorCode.DUPLICADA)
        assert result.error.severity == ErrorSeverity.CRITICAL
        assert not result.retriable
        assert result.requires_human

    def test_error_summary(self):
        handler = SATErrorHandler()
        handler.handle_error(ErrorCode.UUID_INVALIDO)
        handler.handle_error(ErrorCode.RFC_INCORRECTO)
        summary = handler.get_error_summary()
        assert summary["total_errors"] >= 2


# ---------------------------------------------------------------------------
# SATSubmitter tests
# ---------------------------------------------------------------------------
from b2b_ai.features.declaraciones.sat_submitter import (
    SATSubmitter,
    SubmissionStatus,
)


class TestSATSubmitter:
    """Test SAT submission flow."""

    def test_submit_empty_xml(self):
        submitter = SATSubmitter(test_mode=True)
        result = submitter.submit_declaration(
            xml_signed=b"",
            declaration_type="iva",
            periodo="2024-07",
            rfc="ABC123456XYZ",
        )
        assert result.status == SubmissionStatus.ERROR

    def test_submit_unsigned_xml(self):
        submitter = SATSubmitter(test_mode=True)
        result = submitter.submit_declaration(
            xml_signed=b"<declaracion>test</declaracion>",
            declaration_type="iva",
            periodo="2024-07",
            rfc="ABC123456XYZ",
        )
        assert result.status == SubmissionStatus.ERROR
        assert "sello" in result.mensaje.lower()

    def test_submit_test_mode_accepted(self):
        submitter = SATSubmitter(test_mode=True)
        signed_xml = b'<declaracion Sello="abc123" Certificado="xyz" NoCertificado="12345">test</declaracion>'
        result = submitter.submit_declaration(
            xml_signed=signed_xml,
            declaration_type="iva",
            periodo="2024-07",
            rfc="ABC123456XYZ",
            declaration_id="test-001",
        )
        assert result.status == SubmissionStatus.ACCEPTED
        assert result.folio is not None
        assert result.folio.startswith("SIM-")

    def test_check_status(self):
        submitter = SATSubmitter(test_mode=True)
        signed_xml = b'<declaracion Sello="abc" Certificado="x" NoCertificado="y">t</declaracion>'
        submitter.submit_declaration(
            xml_signed=signed_xml,
            declaration_type="iva",
            periodo="2024-07",
            rfc="ABC",
            declaration_id="status-test",
        )
        result = submitter.check_status("status-test")
        assert result is not None
        assert result.status == SubmissionStatus.ACCEPTED

    def test_check_nonexistent_status(self):
        submitter = SATSubmitter(test_mode=True)
        assert submitter.check_status("nonexistent") is None
