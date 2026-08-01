# -*- coding: utf-8 -*-
"""Tests for the DIOT module — matches the module-level function API."""
import pytest
from b2b_ai.features.diot.models import (
    CFDIInvoiceInput,
    DiotEntry,
    DiotReport,
    DiotSummary,
    EstatusDIOT,
    Inconsistencia,
    OperacionType,
    TipoIva,
)
from b2b_ai.features.diot.service import (
    generate_diot,
    validate_diot_data,
    detect_inconsistencies,
    export_diot_xml,
    get_report,
    list_reports,
)
from b2b_ai.features.diot.validators import (
    ValidationResult,
    validate_diot_entries,
    validate_iva_rate,
    validate_rfc,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invoice(**overrides) -> CFDIInvoiceInput:
    """Return a minimal valid CFDIInvoiceInput."""
    base = {
        "uuid": "00000000-0000-0000-0000-000000000001",
        "rfc_emisor": "ABC123456789",
        "nombre_emisor": "Proveedor SA",
        "subtotal": 10000.0,
        "iva_trasladado": 1600.0,
        "iva_acreditable": 1600.0,
        "total": 11600.0,
    }
    base.update(overrides)
    return CFDIInvoiceInput(**base)


# ---------------------------------------------------------------------------
# Validators — validate_rfc
# ---------------------------------------------------------------------------

class TestValidateRfc:
    def test_valid_persona_moral(self):
        assert validate_rfc("ABC123456789") is None

    def test_valid_persona_fisica(self):
        assert validate_rfc("GARC850101ABC") is None

    def test_empty_rfc(self):
        err = validate_rfc("")
        assert err is not None
        assert "vacío" in err

    def test_too_short(self):
        err = validate_rfc("ABC123")
        assert err is not None
        assert "longitud" in err

    def test_invalid_format(self):
        err = validate_rfc("123456789012")
        assert err is not None


# ---------------------------------------------------------------------------
# Validators — validate_iva_rate
# ---------------------------------------------------------------------------

class TestValidateIvaRate:
    def test_valid_16_percent(self):
        ok, err = validate_iva_rate(0.16)
        assert ok is True
        assert err == ""

    def test_valid_8_percent(self):
        ok, _ = validate_iva_rate(0.08)
        assert ok is True

    def test_valid_0_percent(self):
        ok, _ = validate_iva_rate(0.0)
        assert ok is True

    def test_invalid_rate(self):
        ok, err = validate_iva_rate(0.10)
        assert ok is False
        assert "inválida" in err


# ---------------------------------------------------------------------------
# Validators — validate_diot_entries
# ---------------------------------------------------------------------------

class TestValidateDiotEntries:
    def test_returns_validation_result(self):
        result = validate_diot_entries([])
        assert isinstance(result, ValidationResult)

    def test_empty_entries(self):
        result = validate_diot_entries([])
        assert result.valid is False  # Empty list is an error
        assert result.total_entries == 0

    def test_valid_entries(self):
        entries = [
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=10000.0,
                iva_trasladado=1600.0,
                iva_acreditable=1600.0,
            )
        ]
        result = validate_diot_entries(entries)
        assert result.valid is True


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestDiotEntry:
    def test_create_entry(self):
        entry = DiotEntry(
            rfc_tercero="ABC123456789",
            tipo_operacion=OperacionType.COMPRA,
            tipo_iva=TipoIva.GENERAL_16,
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
            tipo_iva=TipoIva.GENERAL_16,
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
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=-100.0,
                iva_trasladado=1600.0,
                iva_acreditable=1600.0,
            )


# ---------------------------------------------------------------------------
# Service — generate_diot
# ---------------------------------------------------------------------------

class TestGenerateDiot:
    def test_generate_with_invoices(self):
        invoices = [_make_invoice(), _make_invoice(
            uuid="00000000-0000-0000-0000-000000000002",
            rfc_emisor="DEF987654321",
            nombre_emisor="Servicios SC",
            subtotal=5000.0,
            iva_trasladado=800.0,
            iva_acreditable=800.0,
            total=5800.0,
        )]
        report = generate_diot(month=1, year=2024, tenant_id="t1", invoices=invoices)
        assert report.month == 1
        assert report.year == 2024
        assert report.tenant_id == "t1"
        assert report.estatus == EstatusDIOT.GENERADA

    def test_generate_no_invoices(self):
        report = generate_diot(month=1, year=2024, tenant_id="t1")
        assert report.estatus == EstatusDIOT.ERROR
        assert len(report.inconsistencies) == 1

    def test_report_is_stored(self):
        report = generate_diot(month=3, year=2024, tenant_id="t2")
        retrieved = get_report(report.id)
        assert retrieved is not None
        assert retrieved.id == report.id

    def test_list_reports(self):
        generate_diot(month=1, year=2024, tenant_id="t1")
        generate_diot(month=2, year=2024, tenant_id="t2")
        reports = list_reports()
        assert len(reports) >= 2


# ---------------------------------------------------------------------------
# Service — validate_diot_data
# ---------------------------------------------------------------------------

class TestValidateDiotData:
    def test_validate_returns_result(self):
        invoices = [_make_invoice()]
        result = validate_diot_data(invoices)
        assert isinstance(result, ValidationResult)
        assert result.valid is True

    def test_validate_empty(self):
        result = validate_diot_data([])
        assert isinstance(result, ValidationResult)
        assert result.valid is False  # Empty list is an error


# ---------------------------------------------------------------------------
# Service — detect_inconsistencies
# ---------------------------------------------------------------------------

class TestDetectInconsistencies:
    def test_no_entries(self):
        result = detect_inconsistencies([])
        assert isinstance(result, list)

    def test_with_entries(self):
        entries = [
            DiotEntry(
                rfc_tercero="ABC123456789",
                tipo_operacion=OperacionType.COMPRA,
                tipo_iva=TipoIva.GENERAL_16,
                monto_neto=10000.0,
                iva_trasladado=1600.0,
                iva_acreditable=1600.0,
            )
        ]
        result = detect_inconsistencies(entries)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Service — export_diot_xml
# ---------------------------------------------------------------------------

class TestExportDiotXml:
    def test_export_creates_file(self, tmp_path):
        report = generate_diot(month=1, year=2024, tenant_id="t1")
        filepath = export_diot_xml(report, output_dir=str(tmp_path))
        assert filepath is not None
        assert len(filepath) > 0
        # File should exist
        from pathlib import Path
        assert Path(filepath).exists()

    def test_export_xml_content(self, tmp_path):
        report = generate_diot(month=1, year=2024, tenant_id="t1")
        filepath = export_diot_xml(report, output_dir=str(tmp_path))
        from pathlib import Path
        content = Path(filepath).read_text(encoding="utf-8")
        assert "DIOT" in content or "PlacasDiarioDiario" in content
