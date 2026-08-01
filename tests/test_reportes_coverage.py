# -*- coding: utf-8 -*-
"""
test_reportes_coverage.py — Additional tests to close coverage gaps in reportes module.

Targets specific uncovered lines:
  generator.py: 36-37 (_fmt_money exception handler)
  serializers.py: 90-95 (_fmt_importe — dead code, unreachable through normal execution)
"""
from __future__ import annotations

import pytest

from b2b_ai.features.reportes.generator import (
    ReportData,
    ReportSection,
    ReportLine,
    _fmt_money,
)
from b2b_ai.features.reportes.serializers import (
    serialize_html,
    serialize_json,
)


# ---------------------------------------------------------------------------
# _fmt_money() — generator.py lines 36-37
# ---------------------------------------------------------------------------

class TestFmtMoneyEdgeCases:
    """Tests for _fmt_money() to cover lines 36-37 (exception handler)."""

    def test_fmt_money_invalid_value_returns_zero(self):
        """Lines 36-37: _fmt_money('not_a_number') should return '$0.00'."""
        result = _fmt_money("not_a_number")
        assert result == "$0.00"

    def test_fmt_money_invalid_operation(self):
        """Lines 36-37: _fmt_money with value causing InvalidOperation."""
        assert _fmt_money("1.2.3") == "$0.00"

    def test_fmt_money_none_returns_zero(self):
        """Line 32: _fmt_money(None) returns '$0.00'."""
        assert _fmt_money(None) == "$0.00"

    def test_fmt_money_valid_string(self):
        """Line 34-35: _fmt_money('1500.50') formats correctly."""
        result = _fmt_money("1500.50")
        assert "$1,500.50" in result

    def test_fmt_money_zero(self):
        """_fmt_money(0) returns '$0.00'."""
        assert _fmt_money(0) == "$0.00"


# ---------------------------------------------------------------------------
# serialize_html() edge cases — exercises generators + serializers integration
# ---------------------------------------------------------------------------

def _make_report_with_values(values):
    """Helper: build a ReportData whose section lines use the given importe values."""
    sections = []
    for val in values:
        sections.append(
            ReportSection(
                titulo="Sección Test",
                lineas=[
                    ReportLine(concepto="Cuenta", importe=val),
                ],
            )
        )
    return ReportData(
        titulo="Test Report",
        subtitulo="Subtitulo Test",
        secciones=sections,
        totales={},
    )


class TestHtmlSerializerEdgeCases:
    """Tests for serialize_html() with various edge cases."""

    def test_html_normal_decimal_value(self):
        """Valid numeric value formats as currency."""
        report = _make_report_with_values(["1234.56"])
        html = serialize_html(report)
        assert "$1,234.56" in html

    def test_html_integer_value(self):
        """Integer value formats with .00."""
        report = _make_report_with_values([5000])
        html = serialize_html(report)
        assert "$5,000.00" in html

    def test_html_string_value_formats(self):
        """Numeric string '999.99' formats correctly."""
        report = _make_report_with_values(["999.99"])
        html = serialize_html(report)
        assert "$999.99" in html

    def test_html_zero_value(self):
        """Zero value formats as $0.00."""
        report = _make_report_with_values([0])
        html = serialize_html(report)
        assert "$0.00" in html

    def test_html_negative_value(self):
        """Negative value formats correctly."""
        report = _make_report_with_values([-500])
        html = serialize_html(report)
        assert "$-500.00" in html

    def test_html_empty_list_no_crash(self):
        """Report with no sections still renders valid HTML."""
        report = ReportData(
            titulo="Vacío",
            subtitulo="",
            secciones=[],
            totales={},
        )
        html = serialize_html(report)
        assert "<!DOCTYPE html>" in html
        assert "Vacío" in html

    def test_html_with_multiple_sections(self):
        """Multiple sections all render."""
        report = _make_report_with_values([100, 200, 300])
        html = serialize_html(report)
        assert html.count("Sección Test") == 3
        assert "$100.00" in html
        assert "$200.00" in html
        assert "$300.00" in html

    def test_html_with_metadata(self):
        """Metadata renders in footer."""
        report = ReportData(
            titulo="Con Metadata",
            subtitulo="Detalle",
            metadata={"tipo_reporte": "Balance General", "moneda": "MXN"},
            secciones=[],
        )
        html = serialize_html(report)
        assert "Balance General" in html
        assert "MXN" in html

    def test_html_with_rfc(self):
        """RFC renders in header."""
        report = ReportData(
            titulo="Con RFC",
            subtitulo="Detalle",
            empresa_rfc="EMISOR010101AAA",
            empresa_nombre="Mi Empresa SA",
            secciones=[],
        )
        html = serialize_html(report)
        assert "EMISOR010101AAA" in html
        assert "Mi Empresa SA" in html


# ---------------------------------------------------------------------------
# serialize_json() edge cases
# ---------------------------------------------------------------------------

class TestJsonSerializerEdgeCases:
    """Quick sanity checks for JSON serializer."""

    def test_json_roundtrip(self):
        """serialize_json produces valid JSON that can be parsed."""
        report = _make_report_with_values([100, 200])
        result = serialize_json(report)
        import json
        data = json.loads(result)
        assert data["titulo"] == "Test Report"
        assert len(data["secciones"]) == 2
