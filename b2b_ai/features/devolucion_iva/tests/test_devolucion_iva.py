# -*- coding: utf-8 -*-
"""
test_devolucion_iva.py — Comprehensive tests for Devolución de IVA module.

Minimum 30 tests covering:
  - Invoice collection and classification
  - DIOT generation and validation
  - CFDI vs DIOT conciliation
  - DIOT vs Declaration conciliation
  - Balance and refund calculation
  - Working paper generation
  - Request preparation and tracking
  - Edge cases and validation
"""
from __future__ import annotations

import pytest
from typing import List

from b2b_ai.features.devolucion_iva.models import (
    ClasificacionIVA,
    DeclaracionMensual,
    DIOTEntry,
    EstatusConciliacion,
    EstatusDevolucion,
    FacturaCFDI,
    SolicitudDevolucion,
    TipoFactura,
)
from b2b_ai.features.devolucion_iva.service import (
    recopilar_facturas,
    clasificar_iva,
    generar_diot,
    validar_diot,
    conciliar_facturas_diot,
    conciliar_diot_declaracion,
    conciliar_declaracion_saldo,
    calcular_saldo_favor,
    calcular_monto_devolucion,
    preparar_solicitud,
    registrar_solicitud,
    consultar_status,
    generar_reporte_seguimiento,
    actualizar_status,
    listar_solicitudes,
    DevolucionIVAService,
)
from b2b_ai.features.devolucion_iva.validators import (
    validate_rfc,
    validate_iva_rate,
    validate_amount,
    validate_date_format,
    validate_clabe,
    validate_periodo,
    validate_diot_consistency,
    validate_declaration_consistency,
)
from b2b_ai.features.devolucion_iva.workpaper import WorkpaperGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_factura(**overrides) -> FacturaCFDI:
    defaults = {
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "rfc_emisor": "EMP850101AB1",
        "rfc_receptor": "REC850101CD2",
        "fecha": "2025-01-15",
        "subtotal": 10000.0,
        "iva": 1600.0,
        "total": 11600.0,
        "tipo": TipoFactura.INGRESO,
        "categoria": ClasificacionIVA.CREDITABLE_100,
    }
    defaults.update(overrides)
    return FacturaCFDI(**defaults)


def _make_diot_entry(**overrides) -> DIOTEntry:
    defaults = {
        "rfc_tercero": "EMP850101AB1",
        "nombre": "Empresa Test SA de CV",
        "tipo_operacion": "01",
        "monto_neto": 10000.0,
        "iva_trasladado": 1600.0,
        "iva_acreditable": 1600.0,
        "folios_fiscales": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    }
    defaults.update(overrides)
    return DIOTEntry(**defaults)


def _make_declaracion(**overrides) -> DeclaracionMensual:
    defaults = {
        "mes": 1,
        "año": 2025,
        "iva_cobrado": 5000.0,
        "iva_pagado": 8000.0,
        "saldo_favor": 3000.0,
        "saldo_contra": 0.0,
    }
    defaults.update(overrides)
    return DeclaracionMensual(**defaults)


# ---------------------------------------------------------------------------
# Test class: Invoice Collection and Classification
# ---------------------------------------------------------------------------

class TestInvoiceCollection:
    """Tests for Step 1: Invoice collection and classification."""

    def test_recopilar_facturas_filters_by_periodo(self):
        facturas = [
            _make_factura(uuid="f1", fecha="2025-01-10"),
            _make_factura(uuid="f2", fecha="2025-02-15"),
            _make_factura(uuid="f3", fecha="2025-01-20"),
        ]
        result = recopilar_facturas(facturas, periodo="2025-01")
        assert len(result) == 2
        assert all(f.fecha.startswith("2025-01") for f in result)

    def test_recopilar_facturas_empty_input(self):
        result = recopilar_facturas([])
        assert result == []

    def test_recopilar_facturas_no_filter(self):
        facturas = [
            _make_factura(uuid="f1"),
            _make_factura(uuid="f2"),
        ]
        result = recopilar_facturas(facturas)
        assert len(result) == 2

    def test_clasificar_iva_all_acreditable(self):
        facturas = [
            _make_factura(uuid="f1", categoria=ClasificacionIVA.CREDITABLE_100),
            _make_factura(uuid="f2", categoria=ClasificacionIVA.CREDITABLE_100),
        ]
        result = clasificar_iva(facturas)
        assert len(result["acreditable_100"]) == 2
        assert len(result["acreditable_proporcional"]) == 0
        assert len(result["no_acreditable"]) == 0

    def test_clasificar_iva_mixed(self):
        facturas = [
            _make_factura(uuid="f1", categoria=ClasificacionIVA.CREDITABLE_100),
            _make_factura(uuid="f2", categoria=ClasificacionIVA.CREDITABLE_PROPORCIONAL),
            _make_factura(uuid="f3", categoria=ClasificacionIVA.NO_CREDITABLE),
        ]
        result = clasificar_iva(facturas)
        assert len(result["acreditable_100"]) == 1
        assert len(result["acreditable_proporcional"]) == 1
        assert len(result["no_acreditable"]) == 1

    def test_clasificar_iva_empty(self):
        result = clasificar_iva([])
        assert all(len(v) == 0 for v in result.values())


# ---------------------------------------------------------------------------
# Test class: DIOT Generation and Validation
# ---------------------------------------------------------------------------

class TestDIOTGeneration:
    """Tests for Step 2: DIOT generation and validation."""

    def test_generar_diot_groups_by_rfc(self):
        facturas = [
            _make_factura(uuid="f1", rfc_emisor="EMP850101AB1", subtotal=1000, iva=160),
            _make_factura(uuid="f2", rfc_emisor="EMP850101AB1", subtotal=2000, iva=320),
            _make_factura(uuid="f3", rfc_emisor="PRO900202XY3", subtotal=500, iva=80),
        ]
        entries = generar_diot(facturas)
        assert len(entries) == 2
        # Find EMP entry
        emp_entry = next(e for e in entries if e.rfc_tercero == "EMP850101AB1")
        assert emp_entry.monto_neto == 3000.0
        assert emp_entry.iva_trasladado == 480.0
        assert len(emp_entry.folios_fiscales) == 2

    def test_generar_diot_empty(self):
        entries = generar_diot([])
        assert entries == []

    def test_generar_diot_applies_proporcionalidad(self):
        facturas = [
            _make_factura(uuid="f1", iva=160, proporcionalidad=0.5),
        ]
        entries = generar_diot(facturas)
        assert len(entries) == 1
        assert entries[0].iva_acreditable == 80.0

    def test_validar_diot_valid_entries(self):
        entries = [
            _make_diot_entry(rfc_tercero="EMP850101AB1", monto_neto=10000, iva_trasladado=1600),
        ]
        errors = validar_diot(entries)
        assert len(errors) == 0

    def test_validar_diot_bad_rfc(self):
        entries = [
            _make_diot_entry(rfc_tercero="BAD", monto_neto=1000, iva_trasladado=160),
        ]
        errors = validar_diot(entries)
        assert len(errors) > 0

    def test_validar_diot_empty(self):
        errors = validar_diot([])
        assert len(errors) > 0

    def test_validar_diot_invalid_iva_rate(self):
        entries = [
            _make_diot_entry(
                rfc_tercero="EMP850101AB1",
                monto_neto=1000,
                iva_trasladado=150,  # 15% - not valid
            ),
        ]
        errors = validar_diot(entries)
        assert any("tasa" in e.lower() or "iva" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Test class: Conciliation
# ---------------------------------------------------------------------------

class TestConciliation:
    """Tests for Step 3: CFDI↔DIOT and DIOT↔Declaration conciliation."""

    def test_conciliar_match(self):
        facturas = [_make_factura(uuid="f1", iva=160)]
        diot = [_make_diot_entry(folios_fiscales=["f1"], iva_acreditable=160)]
        results = conciliar_facturas_diot(facturas, diot)
        assert len(results) == 1
        assert results[0].status == EstatusConciliacion.MATCH

    def test_conciliar_mismatch_missing_in_diot(self):
        facturas = [_make_factura(uuid="f1", iva=160)]
        diot = [_make_diot_entry(folios_fiscales=["other-uuid"], iva_acreditable=160)]
        results = conciliar_facturas_diot(facturas, diot)
        assert results[0].status == EstatusConciliacion.MISMATCH

    def test_conciliar_iva_amount_mismatch(self):
        facturas = [_make_factura(uuid="f1", iva=160)]
        diot = [_make_diot_entry(folios_fiscales=["f1"], iva_acreditable=100)]
        results = conciliar_facturas_diot(facturas, diot)
        assert results[0].status == EstatusConciliacion.MISMATCH

    def test_conciliar_diot_declaracion_match(self):
        diot = [_make_diot_entry(iva_acreditable=8000)]
        decl = [_make_declaracion(iva_pagado=8000)]
        results = conciliar_diot_declaracion(diot, decl)
        assert len(results) == 1
        assert results[0].status == EstatusConciliacion.MATCH

    def test_conciliar_diot_declaracion_mismatch(self):
        diot = [_make_diot_entry(iva_acreditable=8000)]
        decl = [_make_declaracion(iva_pagado=5000)]  # >5% diff
        results = conciliar_diot_declaracion(diot, decl)
        assert results[0].status == EstatusConciliacion.MISMATCH

    def test_conciliar_declaracion_saldo_consistent(self):
        decl = [_make_declaracion(saldo_favor=3000)]
        result = conciliar_declaracion_saldo(decl, saldo_a_favor=3000.0)
        assert result["consistente"] is True

    def test_conciliar_declaracion_saldo_inconsistent(self):
        decl = [_make_declaracion(saldo_favor=3000)]
        result = conciliar_declaracion_saldo(decl, saldo_a_favor=5000.0)
        assert result["consistente"] is False


# ---------------------------------------------------------------------------
# Test class: Balance and Refund Calculation
# ---------------------------------------------------------------------------

class TestBalanceCalculation:
    """Tests for Step 4: Balance and refund amount calculation."""

    def test_calcular_saldo_favor_single(self):
        decl = [_make_declaracion(saldo_favor=5000)]
        assert calcular_saldo_favor(decl) == 5000.0

    def test_calcular_saldo_favor_multiple(self):
        decl = [
            _make_declaracion(mes=1, saldo_favor=3000),
            _make_declaracion(mes=2, saldo_favor=2000),
        ]
        assert calcular_saldo_favor(decl) == 5000.0

    def test_calcular_saldo_favor_empty(self):
        assert calcular_saldo_favor([]) == 0.0

    def test_calcular_monto_devolucion(self):
        decl = [_make_declaracion(saldo_favor=10000)]
        result = calcular_monto_devolucion(10000.0, decl)
        assert result["monto_devolucion_sugerido"] == 10000.0
        assert result["prescripcion_verificada"] is True


# ---------------------------------------------------------------------------
# Test class: Working Paper Generation
# ---------------------------------------------------------------------------

class TestWorkingPaper:
    """Tests for working paper generation."""

    def test_workpaper_structure(self):
        gen = WorkpaperGenerator()
        wp = gen.generate(
            periodo="2025-01",
            facturas=[_make_factura()],
            diot_entries=[_make_diot_entry()],
            declaraciones=[_make_declaracion()],
        )
        assert "secciones" in wp
        assert "1_resumen_periodo" in wp["secciones"]
        assert "2_diot_por_proveedor" in wp["secciones"]
        assert "3_conciliacion_cfdi_diot" in wp["secciones"]
        assert "4_conciliacion_diot_declaracion" in wp["secciones"]
        assert "5_calculo_saldo" in wp["secciones"]
        assert "6_documentos_soporte" in wp["secciones"]

    def test_workpaper_summary_counts(self):
        gen = WorkpaperGenerator()
        facturas = [
            _make_factura(uuid="f1"),
            _make_factura(uuid="f2"),
        ]
        wp = gen.generate(
            periodo="2025-01",
            facturas=facturas,
            diot_entries=[],
            declaraciones=[],
        )
        assert wp["secciones"]["1_resumen_periodo"]["resumen_facturas"]["total_facturas"] == 2

    def test_workpaper_diot_by_supplier(self):
        gen = WorkpaperGenerator()
        entries = [
            _make_diot_entry(rfc_tercero="EMP850101AB1"),
            _make_diot_entry(rfc_tercero="PRO900202XY3"),
        ]
        wp = gen.generate(
            periodo="2025-01",
            facturas=[],
            diot_entries=entries,
            declaraciones=[],
        )
        assert wp["secciones"]["2_diot_por_proveedor"]["total_proveedores"] == 2


# ---------------------------------------------------------------------------
# Test class: Request Preparation and Tracking
# ---------------------------------------------------------------------------

class TestRequestTracking:
    """Tests for Step 5-6: Request preparation and status tracking."""

    def test_preparar_solicitud(self):
        saldo = {"monto_devolucion_sugerido": 50000.0}
        sol = preparar_solicitud("2025-01", saldo, "Banorte", "072180001234567890")
        assert sol.periodo == "2025-01"
        assert sol.monto_solicitado == 50000.0
        assert sol.status == EstatusDevolucion.PENDIENTE

    def test_preparar_solicitud_monto_cero_fails(self):
        saldo = {"monto_devolucion_sugerido": 0.0}
        with pytest.raises(ValueError, match="debe ser mayor a cero"):
            preparar_solicitud("2025-01", saldo)

    def test_preparar_solicitud_clabe_invalid_fails(self):
        saldo = {"monto_devolucion_sugerido": 10000.0}
        with pytest.raises(ValueError, match="CLABE"):
            preparar_solicitud("2025-01", saldo, clabe="123")

    def test_registrar_y_consultar_status(self):
        sol = preparar_solicitud(
            "2025-01",
            {"monto_devolucion_sugerido": 25000.0},
            "Banorte",
            "072180001234567890",
        )
        registrar_solicitud(sol)
        status = consultar_status(sol.solicitud_id)
        assert status is not None
        assert status.status == EstatusDevolucion.PENDIENTE

    def test_actualizar_status(self):
        sol = preparar_solicitud(
            "2025-01",
            {"monto_devolucion_sugerido": 25000.0},
            "Banorte",
            "072180001234567890",
        )
        registrar_solicitud(sol)
        updated = actualizar_status(
            sol.solicitud_id,
            EstatusDevolucion.APROBADA,
            fecha_respuesta="2025-03-01",
            monto_aprobado=25000.0,
        )
        assert updated is not None
        assert updated.status == EstatusDevolucion.APROBADA
        assert updated.monto_aprobado == 25000.0

    def test_generar_reporte_seguimiento(self):
        sol = preparar_solicitud(
            "2025-01",
            {"monto_devolucion_sugerido": 30000.0},
        )
        registrar_solicitud(sol)
        report = generar_reporte_seguimiento(sol.solicitud_id)
        assert report is not None
        assert report["solicitud_id"] == sol.solicitud_id
        assert report["periodo"] == "2025-01"

    def test_generar_reporte_not_found(self):
        report = generar_reporte_seguimiento("nonexistent-id")
        assert report is None

    def test_listar_solicitudes(self):
        sol = preparar_solicitud(
            "2025-01",
            {"monto_devolucion_sugerido": 10000.0},
        )
        registrar_solicitud(sol)
        items = listar_solicitudes()
        assert len(items) >= 1


# ---------------------------------------------------------------------------
# Test class: Validator Functions
# ---------------------------------------------------------------------------

class TestValidators:
    """Tests for validation functions."""

    def test_validate_rfc_valid_moral(self):
        assert validate_rfc("EMP850101AB1") is None

    def test_validate_rfc_valid_fisica(self):
        assert validate_rfc("CACJ850101AB1") is None

    def test_validate_rfc_empty(self):
        assert validate_rfc("") is not None

    def test_validate_rfc_too_short(self):
        assert validate_rfc("AB") is not None

    def test_validate_iva_rate_valid_16(self):
        ok, _ = validate_iva_rate(0.16)
        assert ok

    def test_validate_iva_rate_valid_8(self):
        ok, _ = validate_iva_rate(0.08)
        assert ok

    def test_validate_iva_rate_valid_0(self):
        ok, _ = validate_iva_rate(0.0)
        assert ok

    def test_validate_iva_rate_invalid(self):
        ok, _ = validate_iva_rate(0.12)
        assert not ok

    def test_validate_amount_positive(self):
        assert validate_amount(1000.0) is None

    def test_validate_amount_zero_not_allowed(self):
        assert validate_amount(0, allow_zero=False) is not None

    def test_validate_amount_negative(self):
        assert validate_amount(-100.0) is not None

    def test_validate_date_format_valid(self):
        assert validate_date_format("2025-01-15") is None

    def test_validate_date_format_invalid(self):
        assert validate_date_format("15-01-2025") is not None

    def test_validate_date_format_future(self):
        assert validate_date_format("2099-01-01") is not None

    def test_validate_clabe_valid(self):
        assert validate_clabe("072180001234567890") is None

    def test_validate_clabe_invalid_length(self):
        assert validate_clabe("123456") is not None

    def test_validate_clabe_not_digits(self):
        assert validate_clabe("07218000123456789A") is not None

    def test_validate_periodo_valid(self):
        assert validate_periodo("2025-01") is None

    def test_validate_periodo_invalid(self):
        assert validate_periodo("invalid") is not None

    def test_validate_diot_consistency_empty(self):
        errors = validate_diot_consistency([], [])
        assert len(errors) > 0

    def test_validate_declaration_consistency_empty(self):
        errors = validate_declaration_consistency([], [])
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Test class: Service Class (Router integration)
# ---------------------------------------------------------------------------

class TestDevolucionIVAService:
    """Tests for the DevolucionIVAService class."""

    def test_service_coerce_facturas(self):
        svc = DevolucionIVAService()
        result = svc._coerce_facturas([
            {"uuid": "f1", "rfc_emisor": "EMP850101AB1", "rfc_receptor": "REC850101CD2",
             "fecha": "2025-01-15", "subtotal": 1000, "iva": 160, "total": 1160}
        ])
        assert len(result) == 1
        assert isinstance(result[0], FacturaCFDI)

    def test_service_full_flow(self):
        svc = DevolucionIVAService()
        facturas = [
            {"uuid": "f1", "rfc_emisor": "EMP850101AB1", "rfc_receptor": "REC850101CD2",
             "fecha": "2025-01-15", "subtotal": 10000, "iva": 1600, "total": 11600,
             "categoria": "acreditable_100"},
        ]
        diot_entries = [
            {"rfc_tercero": "EMP850101AB1", "tipo_operacion": "01",
             "monto_neto": 10000, "iva_trasladado": 1600, "iva_acreditable": 1600,
             "folios_fiscales": ["f1"]},
        ]
        declaraciones = [
            {"mes": 1, "año": 2025, "iva_cobrado": 5000, "iva_pagado": 1600,
             "saldo_favor": 1600, "saldo_contra": 0},
        ]

        # Recopilar
        fact = svc.recopilar_facturas(facturas, periodo="2025-01")
        assert len(fact) == 1

        # DIOT
        diot = svc.generar_diot(facturas)
        assert len(diot) == 1

        # Validar DIOT
        errors = svc.validar_diot(diot)
        assert len(errors) == 0

        # Conciliar
        result = svc.conciliar(facturas, diot_entries, declaraciones)
        assert "facturas_vs_diot" in result
        assert "diot_vs_declaracion" in result

        # Calcular
        calc = svc.calcular(declaraciones)
        assert calc["monto_devolucion_sugerido"] == 1600.0

        # Solicitud
        sol = svc.preparar_solicitud(
            "2025-01", calc, "Banorte", "072180001234567890",
        )
        assert sol.monto_solicitado == 1600.0

        # Registrar y consultar
        svc.registrar(sol)
        status = svc.consultar_status(sol.solicitud_id)
        assert status is not None

        # Reporte
        report = svc.generar_reporte(sol.solicitud_id)
        assert report is not None

        # Listar
        items = svc.listar()
        assert len(items) >= 1


# ---------------------------------------------------------------------------
# Test class: Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case tests."""

    def test_multiple_rfc_diot_grouping(self):
        facturas = [
            _make_factura(uuid="f1", rfc_emisor="AAA850101AB1", iva=160),
            _make_factura(uuid="f2", rfc_emisor="BBB850101CD2", iva=320),
            _make_factura(uuid="f3", rfc_emisor="AAA850101AB1", iva=80),
        ]
        entries = generar_diot(facturas)
        assert len(entries) == 2

    def test_proporcionalidad_partial(self):
        facturas = [
            _make_factura(uuid="f1", iva=1600, proporcionalidad=0.6),
            _make_factura(uuid="f2", iva=800, proporcionalidad=0.3),
        ]
        entries = generar_diot(facturas)
        total_acreditable = sum(e.iva_acreditable for e in entries)
        assert total_acreditable == round(1600 * 0.6 + 800 * 0.3, 2)

    def test_conciliar_empty_facturas(self):
        results = conciliar_facturas_diot([], [_make_diot_entry()])
        assert results == []

    def test_conciliar_empty_diot(self):
        results = conciliar_facturas_diot([_make_factura()], [])
        assert results[0].status == EstatusConciliacion.MISMATCH

    def test_calcular_monto_prescription_check(self):
        decl = [_make_declaracion(mes=1, año=2020, saldo_favor=5000)]
        result = calcular_monto_devolucion(5000.0, decl)
        assert result["periodo_mas_antiguo"] == "2020-01"
        assert result["prescripcion_verificada"] is True
