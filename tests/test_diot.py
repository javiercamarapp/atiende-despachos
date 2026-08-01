# -*- coding: utf-8 -*-
"""Tests for the DIOT module."""
import pytest
from b2b_ai.features.diot.models import DiotEntry, DiotReport, DiotSummary, EstatusDIOT, OperacionType
from b2b_ai.features.diot.service import DiotService
from b2b_ai.features.diot.validators import validate_diot_entries, validate_iva_rate, validate_rfc


# ---------------------------------------------------------------------------
# Validators tests
# ---------------------------------------------------------------------------

class TestValidateRfc:
    def test_valid_persona_moral(self):
        ok, err = validate_rfc("ABC123456789")
        assert ok is True
        assert err == ""

    def test_valid_persona_fisica(self):
        ok, err = validate_rfc("GARC850101ABC")
        assert ok is True
        assert err == ""

    def test_empty_rfc(self):
        ok, err = validate_rfc("")
        assert ok is False
        assert "vacío" in err

    def test_too_short(self):
        ok, err = validate_rfc("ABC123")
        assert ok is False
        assert "longitud" in err

    def test_invalid_format(self):
        ok, err = validate_rfc("123456789012")
        assert ok is False


class TestValidateIvaRate:
    def test_valid_16_percent(self):
        ok, err = validate_iva_rate(0.16)
        assert ok is True

    def test_valid_8_percent(self):
        ok, err = validate_iva_rate(0.08)
        assert ok is True

    def test_valid_0_percent(self):
        ok, err = validate_iva_rate(0.0)
        assert ok is True

    def test_invalid_rate(self):
        ok, err = validate_iva_rate(0.10)
        assert ok is False
        assert "inválida" in err


class TestValidateDiotEntries:
    def test_valid_entries(self):
        entries = [
            {
                "rfc_tercero": "ABC123456789",
                "tipo_operacion": "01",
                "monto_neto": 10000.0,
                "iva_trasladado": 1600.0,
                "iva_acreditable": 1600.0,
            }
        ]
        ok, errors = validate_diot_entries(entries)
        assert ok is True
        assert len(errors) == 0

    def test_empty_list(self):
        ok, errors = validate_diot_entries([])
        assert ok is False
        assert "vacía" in errors[0]

    def test_missing_field(self):
        entries = [
            {
                "rfc_tercero": "ABC123456789",
                # missing tipo_operacion
                "monto_neto": 10000.0,
                "iva_trasladado": 1600.0,
                "iva_acreditable": 1600.0,
            }
        ]
        ok, errors = validate_diot_entries(entries)
        assert ok is False
        assert any("tipo_operacion" in e for e in errors)

    def test_negative_amount(self):
        entries = [
            {
                "rfc_tercero": "ABC123456789",
                "tipo_operacion": "01",
                "monto_neto": -100.0,
                "iva_trasladado": 1600.0,
                "iva_acreditable": 1600.0,
            }
        ]
        ok, errors = validate_diot_entries(entries)
        assert ok is False


# ---------------------------------------------------------------------------
# Models tests
# ---------------------------------------------------------------------------

class TestDiotEntry:
    def test_create_entry(self):
        entry = DiotEntry(
            rfc_tercero="ABC123456789",
            tipo_operacion=OperacionType.COMPRA,
            monto_neto=10000.0,
            iva_trasladado=1600.0,
            iva_acreditable=1600.0,
        )
        assert entry.rfc_tercero == "ABC123456789"
        assert entry.tipo_operacion == OperacionType.COMPRA
        assert entry.monto_neto == 10000.0

    def test_rfc_uppercase(self):
        entry = DiotEntry(
            rfc_tercero="abc123456789",
            tipo_operacion=OperacionType.COMPRA,
            monto_neto=10000.0,
            iva_trasladado=1600.0,
            iva_acreditable=1600.0,
        )
        assert entry.rfc_tercero == "ABC123456789"

    def test_negative_monto_raises(self):
        with pytest.raises(Exception):
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                monto_neto=-100.0,
                iva_trasladado=1600.0,
                iva_acreditable=1600.0,
            )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestDiotService:
    def test_generate_diot(self):
        service = DiotService()
        invoices = [
            {
                "rfc_tercero": "ABC123456789",
                "nombre": "Proveedor SA",
                "tipo_operacion": "01",
                "monto_neto": 10000.0,
                "iva_trasladado": 1600.0,
                "iva_acreditable": 1600.0,
            },
            {
                "rfc_tercero": "DEF987654321",
                "nombre": "Servicios SC",
                "tipo_operacion": "01",
                "monto_neto": 5000.0,
                "iva_trasladado": 800.0,
                "iva_acreditable": 800.0,
            },
        ]
        report = service.generate_diot(month=1, year=2024, invoices=invoices)
        assert report.month == 1
        assert report.year == 2024
        assert len(report.entries) == 2
        assert report.summary.total_operaciones == 2
        assert report.summary.total_iva_trasladado == 2400.0
        assert report.summary.total_iva_acreditable == 2400.0
        assert report.summary.diferencias == 0.0

    def test_detect_inconsistencies_iva_mismatch(self):
        service = DiotService()
        entries = [
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                monto_neto=10000.0,
                iva_trasladado=500.0,  # Wrong: should be 1600
                iva_acreditable=500.0,
            )
        ]
        inconsistencies = service.detect_inconsistencies(entries)
        assert len(inconsistencies) > 0
        assert any(i["type"] == "IVA_MISMATCH" for i in inconsistencies)

    def test_detect_inconsistencies_duplicate(self):
        service = DiotService()
        entries = [
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                monto_neto=10000.0,
                iva_trasladado=1600.0,
                iva_acreditable=1600.0,
            ),
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                monto_neto=5000.0,
                iva_trasladado=800.0,
                iva_acreditable=800.0,
            ),
        ]
        inconsistencies = service.detect_inconsistencies(entries)
        assert any(i["type"] == "DUPLICADO" for i in inconsistencies)

    def test_validate_diot_data(self):
        service = DiotService()
        invoices = [
            {
                "rfc_tercero": "ABC123456789",
                "tipo_operacion": "01",
                "monto_neto": 10000.0,
                "iva_trasladado": 1600.0,
                "iva_acreditable": 1600.0,
            }
        ]
        result = service.validate_diot_data(invoices)
        assert result["is_valid"] is True
        assert result["total_entries"] == 1

    def test_export_diot_xml(self):
        service = DiotService()
        report = service.generate_diot(
            month=1,
            year=2024,
            invoices=[
                {
                    "rfc_tercero": "ABC123456789",
                    "tipo_operacion": "01",
                    "monto_neto": 10000.0,
                    "iva_trasladado": 1600.0,
                    "iva_acreditable": 1600.0,
                }
            ],
        )
        xml = service.export_diot_xml(report)
        assert '<?xml version="1.0"' in xml
        assert "DIOT" in xml
        assert "ABC123456789" in xml
        assert "10000.00" in xml

    def test_get_history(self):
        service = DiotService()
        service.generate_diot(month=1, year=2024, tenant_id="t1")
        service.generate_diot(month=2, year=2024, tenant_id="t1")
        service.generate_diot(month=1, year=2024, tenant_id="t2")

        all_reports = service.get_history()
        assert len(all_reports) == 3

        t1_reports = service.get_history(tenant_id="t1")
        assert len(t1_reports) == 2

    def test_generate_diot_no_invoices(self):
        service = DiotService()
        report = service.generate_diot(month=1, year=2024)
        assert report.entries == []
        assert report.summary.total_operaciones == 0
