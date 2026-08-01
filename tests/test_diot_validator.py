# -*- coding: utf-8 -*-
"""
tests/test_diot_validator.py — Comprehensive tests for the DIOT XML validator.

Covers:
  • Individual field validators (RFC, TipoOperacion, numeric fields)
  • XML operation-level validation
  • Full document validation (valid and invalid cases)
  • Edge cases: empty XML, missing nodes, malformed data
  • IVA cross-check with declared totals
"""
from __future__ import annotations

import pytest
import xml.etree.ElementTree as ET
from pathlib import Path

from b2b_ai.services.diot_validator import (
    DIOTValidationResult,
    ValidationError,
    parse_diot_xml,
    validate_diot_xml,
    validate_non_negative_float,
    validate_operation_xml,
    validate_positive_float,
    validate_razon_social,
    validate_rfc_format,
    validate_tipo_operacion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_operation_xml(
    rfc: str = "ABC123456789",
    razon_social: str = "Proveedor SA",
    tipo_operacion: str = "01",
    monto: str = "10000.00",
    iva_trasladado: str = "1600.00",
    iva_acreditable: str = "1600.00",
    fecha_operacion: str = "2024-01-15",
) -> ET.Element:
    """Build a single <Operacion> XML node with defaults."""
    node = ET.Element("Operacion")
    for tag, val in [
        ("RFC", rfc),
        ("RazonSocial", razon_social),
        ("TipoOperacion", tipo_operacion),
        ("Monto", monto),
        ("IVATrasladado", iva_trasladado),
        ("IVAAcreditable", iva_acreditable),
        ("FechaOperacion", fecha_operacion),
    ]:
        child = ET.SubElement(node, tag)
        child.text = val
    return node


def _make_diot_xml(
    operations: list | None = None,
    declared_iva_trasladado: str | None = None,
    root_tag: str = "DIOT",
) -> str:
    """Build a complete DIOT XML string."""
    root = ET.Element(root_tag)
    if declared_iva_trasladado is not None:
        total_el = ET.SubElement(root, "TotalIVATrasladado")
        total_el.text = declared_iva_trasladado
    if operations is None:
        operations = [_make_operation_xml()]
    for op in operations:
        root.append(op)
    return ET.tostring(root, encoding="unicode")


# ===========================================================================
# validate_rfc_format
# ===========================================================================

class TestValidateRfcFormat:
    """Tests for RFC format validation."""

    def test_valid_persona_moral_12_chars(self):
        assert validate_rfc_format("ABC123456789") is None

    def test_valid_persona_fisica_13_chars(self):
        assert validate_rfc_format("GARC850101ABC") is None

    def test_valid_rfc_with_ampersand(self):
        assert validate_rfc_format("X&X010101AAA") is None

    def test_empty_string(self):
        err = validate_rfc_format("")
        assert err is not None
        assert "vacío" in err

    def test_none(self):
        err = validate_rfc_format(None)
        assert err is not None

    def test_whitespace_only(self):
        err = validate_rfc_format("   ")
        assert err is not None
        assert "vacío" in err

    def test_too_short(self):
        err = validate_rfc_format("ABC123")
        assert err is not None
        assert "patrón" in err

    def test_too_long(self):
        err = validate_rfc_format("ABC123456789012")
        assert err is not None

    def test_invalid_start_with_numbers(self):
        err = validate_rfc_format("1234567890123")
        assert err is not None
        assert "patrón" in err

    def test_lowercase_converted_to_uppercase(self):
        # Should be accepted after uppercase conversion
        err = validate_rfc_format("garc850101abc")
        assert err is None

    def test_invalid_format_no_digits_middle(self):
        err = validate_rfc_format("ABCDABCDEFAB")
        assert err is not None

    def test_invalid_format_letters_at_end(self):
        err = validate_rfc_format("ABC12345678AB")
        assert err is not None

    def test_valid_14_chars_rejected(self):
        err = validate_rfc_format("ABCD1234567890")
        assert err is not None


# ===========================================================================
# validate_tipo_operacion
# ===========================================================================

class TestValidateTipoOperacion:
    """Tests for TipoOperacion validation."""

    def test_valid_01_iva(self):
        assert validate_tipo_operacion("01") is None

    def test_valid_02_ieps(self):
        assert validate_tipo_operacion("02") is None

    def test_valid_03_exento(self):
        assert validate_tipo_operacion("03") is None

    def test_invalid_04(self):
        err = validate_tipo_operacion("04")
        assert err is not None
        assert "inválido" in err

    def test_empty_string(self):
        err = validate_tipo_operacion("")
        assert err is not None

    def test_none(self):
        err = validate_tipo_operacion(None)
        assert err is not None

    def test_text_value(self):
        err = validate_tipo_operacion("IVA")
        assert err is not None


# ===========================================================================
# validate_non_negative_float / validate_positive_float
# ===========================================================================

class TestValidateNonNegativeFloat:

    def test_valid_positive(self):
        assert validate_non_negative_float("100.50", "Monto") is None

    def test_valid_zero(self):
        assert validate_non_negative_float("0", "Monto") is None

    def test_negative_value(self):
        err = validate_non_negative_float("-50", "Monto")
        assert err is not None
        assert "negativo" in err

    def test_non_numeric(self):
        err = validate_non_negative_float("abc", "Monto")
        assert err is not None
        assert "numérico" in err

    def test_none_value(self):
        err = validate_non_negative_float(None, "Monto")
        assert err is not None
        assert "obligatorio" in err

    def test_empty_string(self):
        err = validate_non_negative_float("", "Monto")
        assert err is not None


class TestValidatePositiveFloat:

    def test_valid_positive(self):
        assert validate_positive_float("100.00", "Monto") is None

    def test_zero_rejected(self):
        err = validate_positive_float("0", "Monto")
        assert err is not None
        assert "mayor a cero" in err

    def test_negative_rejected(self):
        err = validate_positive_float("-10", "Monto")
        assert err is not None

    def test_none_rejected(self):
        err = validate_positive_float(None, "Monto")
        assert err is not None


# ===========================================================================
# validate_razon_social
# ===========================================================================

class TestValidateRazonSocial:

    def test_valid(self):
        assert validate_razon_social("Mi Empresa SA de CV") is None

    def test_empty(self):
        err = validate_razon_social("")
        assert err is not None

    def test_none(self):
        err = validate_razon_social(None)
        assert err is not None

    def test_whitespace_only(self):
        err = validate_razon_social("   ")
        assert err is not None


# ===========================================================================
# validate_operation_xml
# ===========================================================================

class TestValidateOperationXml:
    """Tests for single <Operacion> XML node validation."""

    def test_valid_operation(self):
        node = _make_operation_xml()
        errors = validate_operation_xml(node, 1)
        assert errors == []

    def test_missing_rfc(self):
        node = _make_operation_xml(rfc="")
        # Remove RFC element entirely
        rfc_el = node.find("RFC")
        node.remove(rfc_el)
        errors = validate_operation_xml(node, 1)
        assert any("RFC" in e.field for e in errors)

    def test_invalid_rfc_format(self):
        node = _make_operation_xml(rfc="INVALID")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "RFC" for e in errors)

    def test_missing_razon_social(self):
        node = ET.Element("Operacion")
        for tag, val in [("RFC", "ABC123456789"), ("TipoOperacion", "01"),
                         ("Monto", "100"), ("IVATrasladado", "16"),
                         ("IVAAcreditable", "16")]:
            child = ET.SubElement(node, tag)
            child.text = val
        errors = validate_operation_xml(node, 1)
        assert any("RazonSocial" in e.field for e in errors)

    def test_invalid_tipo_operacion(self):
        node = _make_operation_xml(tipo_operacion="99")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "TipoOperacion" for e in errors)

    def test_negative_monto(self):
        node = _make_operation_xml(monto="-100")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "Monto" for e in errors)

    def test_zero_monto(self):
        node = _make_operation_xml(monto="0")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "Monto" for e in errors)

    def test_negative_iva_trasladado(self):
        node = _make_operation_xml(iva_trasladado="-100")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "IVATrasladado" for e in errors)

    def test_negative_iva_acreditable(self):
        node = _make_operation_xml(iva_acreditable="-50")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "IVAAcreditable" for e in errors)

    def test_zero_iva_trasladado_allowed(self):
        node = _make_operation_xml(iva_trasladado="0", monto="5000")
        errors = validate_operation_xml(node, 1)
        assert not any(e.field == "IVATrasladado" and e.severity == "error" for e in errors)

    def test_non_standard_iva_rate_warning(self):
        # 10% IVA rate → non-standard
        node = _make_operation_xml(monto="1000", iva_trasladado="100")
        errors = validate_operation_xml(node, 1)
        assert any(e.severity == "warning" for e in errors)

    def test_standard_iva_16_percent_no_warning(self):
        node = _make_operation_xml(monto="10000", iva_trasladado="1600")
        errors = validate_operation_xml(node, 1)
        assert not any(e.severity == "warning" for e in errors)

    def test_operation_index_in_error(self):
        node = _make_operation_xml(rfc="")
        rfc_el = node.find("RFC")
        node.remove(rfc_el)
        errors = validate_operation_xml(node, 5)
        assert any(e.operacion_index == 5 for e in errors)

    def test_non_numeric_monto(self):
        node = _make_operation_xml(monto="abc")
        errors = validate_operation_xml(node, 1)
        assert any(e.field == "Monto" for e in errors)


# ===========================================================================
# parse_diot_xml
# ===========================================================================

class TestParseDiotXml:

    def test_parse_valid_string(self):
        xml_str = _make_diot_xml()
        root = parse_diot_xml(xml_str)
        assert root.tag == "DIOT"

    def test_parse_malformed_xml(self):
        with pytest.raises(ET.ParseError):
            parse_diot_xml("<DIOT><unclosed>")

    def test_parse_file(self, tmp_path: Path):
        xml_str = _make_diot_xml()
        filepath = tmp_path / "test.xml"
        filepath.write_text(xml_str, encoding="utf-8")
        root = parse_diot_xml(filepath)
        assert root is not None


# ===========================================================================
# validate_diot_xml — full document
# ===========================================================================

class TestValidateDiotXmlFull:
    """Full document validation tests."""

    def test_valid_single_operation(self):
        xml_str = _make_diot_xml()
        result = validate_diot_xml(xml_str)
        assert result.valid is True
        assert result.total_operations == 1

    def test_valid_multiple_operations(self):
        ops = [
            _make_operation_xml(rfc="ABC123456789", monto="5000", iva_trasladado="800", iva_acreditable="800"),
            _make_operation_xml(rfc="DEF987654321", monto="3000", iva_trasladado="480", iva_acreditable="480"),
        ]
        xml_str = _make_diot_xml(operations=ops)
        result = validate_diot_xml(xml_str)
        assert result.valid is True
        assert result.total_operations == 2
        assert result.total_monto == pytest.approx(8000, abs=0.01)
        assert result.total_iva_trasladado == pytest.approx(1280, abs=0.01)

    def test_empty_xml_no_operations(self):
        xml_str = "<DIOT></DIOT>"
        result = validate_diot_xml(xml_str)
        assert result.valid is False
        assert result.total_operations == 0

    def test_malformed_xml(self):
        result = validate_diot_xml("<DIOT><unclosed>")
        assert result.valid is False
        assert any("parseo" in e.message for e in result.errors)

    def test_missing_rfc_in_operation(self):
        node = _make_operation_xml()
        rfc_el = node.find("RFC")
        node.remove(rfc_el)
        xml_str = _make_diot_xml(operations=[node])
        result = validate_diot_xml(xml_str)
        assert result.valid is False
        assert any(e.field == "RFC" for e in result.errors)

    def test_invalid_rfc_format(self):
        node = _make_operation_xml(rfc="INVALIDRFC")
        xml_str = _make_diot_xml(operations=[node])
        result = validate_diot_xml(xml_str)
        assert result.valid is False

    def test_negative_monto_detected(self):
        node = _make_operation_xml(monto="-500")
        xml_str = _make_diot_xml(operations=[node])
        result = validate_diot_xml(xml_str)
        assert result.valid is False

    def test_totals_calculated(self):
        ops = [
            _make_operation_xml(monto="1000", iva_trasladado="160", iva_acreditable="160"),
            _make_operation_xml(monto="2000", iva_trasladado="320", iva_acreditable="320"),
        ]
        xml_str = _make_diot_xml(operations=ops)
        result = validate_diot_xml(xml_str)
        assert result.total_monto == pytest.approx(3000, abs=0.01)
        assert result.total_iva_trasladado == pytest.approx(480, abs=0.01)
        assert result.total_iva_acreditable == pytest.approx(480, abs=0.01)

    def test_rfc_set_populated(self):
        ops = [
            _make_operation_xml(rfc="ABC123456789"),
            _make_operation_xml(rfc="DEF987654321"),
        ]
        xml_str = _make_diot_xml(operations=ops)
        result = validate_diot_xml(xml_str)
        assert "ABC123456789" in result.rfc_set
        assert "DEF987654321" in result.rfc_set

    def test_declared_total_matches(self):
        xml_str = _make_diot_xml(declared_iva_trasladado="1600.00")
        result = validate_diot_xml(xml_str)
        assert result.declared_total_iva_trasladado == 1600.00
        assert result.valid is True

    def test_declared_total_mismatch(self):
        xml_str = _make_diot_xml(declared_iva_trasladado="9999.00")
        result = validate_diot_xml(xml_str)
        assert result.valid is False
        assert any("TotalIVATrasladado" in e.field for e in result.errors)

    def test_iva_zero_rate_operation(self):
        node = _make_operation_xml(tipo_operacion="03", monto="5000", iva_trasladado="0", iva_acreditable="0")
        xml_str = _make_diot_xml(operations=[node])
        result = validate_diot_xml(xml_str)
        assert result.valid is True

    def test_warnings_separated_from_errors(self):
        # Non-standard IVA rate produces a warning, not an error
        node = _make_operation_xml(monto="10000", iva_trasladado="1000")  # 10% rate
        xml_str = _make_diot_xml(operations=[node])
        result = validate_diot_xml(xml_str)
        assert result.warning_count >= 1
        # It should still be valid (warnings don't fail validation)
        assert result.valid is True


# ===========================================================================
# DIOTValidationResult
# ===========================================================================

class TestDIOTValidationResult:

    def test_initial_state(self):
        r = DIOTValidationResult()
        assert r.valid is True
        assert r.total_operations == 0
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_has_critical_errors(self):
        r = DIOTValidationResult()
        r.errors.append(ValidationError(operacion_index=1, field="RFC", message="bad"))
        assert r.has_critical_errors() is True

    def test_no_critical_errors(self):
        r = DIOTValidationResult()
        r.warnings.append(ValidationError(operacion_index=1, field="RFC", message="bad", severity="warning"))
        assert r.has_critical_errors() is False

    def test_to_dict(self):
        r = DIOTValidationResult(total_operations=5, total_monto=10000)
        d = r.to_dict()
        assert d["total_operations"] == 5
        assert d["total_monto"] == 10000
        assert "valid" in d
        assert "rfc_set" in d


# ===========================================================================
# ValidationError
# ===========================================================================

class TestValidationError:

    def test_repr(self):
        e = ValidationError(operacion_index=3, field="RFC", message="invalid", severity="error")
        r = repr(e)
        assert "op#3" in r
        assert "RFC" in r
        assert "error" in r
