# -*- coding: utf-8 -*-
"""
test_reportes_coverage.py — Additional tests to close coverage gaps in reportes module.

Targets specific uncovered lines:
  generator.py: 36-37 (_fmt_money exception handler)
  serializers.py: 90-95 (_fmt_importe inside serialize_html — both paths)
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
        # Multiple dots should trigger the exception
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
# _fmt_importe inside serialize_html() — serializers.py lines 90-95
# ---------------------------------------------------------------------------

def _make_report_with_importes(values):
    """Helper: build a ReportData whose section lines use arbitrary importe values."""
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
        totales={"Total": sum(float(v) for v in values if v is not None)},
    )


class TestFmtImporteInHtml:
    """Tests for _fmt_importe inside serialize_html (lines 90-95)."""

    def test_html_normal_decimal_value(self):
        """Lines 90-93: _fmt_importe with a valid numeric value formats as currency."""
        report = _make_report_with_importes(["1234.56"])
        html = serialize_html(report)
        assert "$1,234.56" in html

    def test_html_integer_value(self):
        """Lines 90-93: _fmt_importe with an integer value."""
        report = _make_report_with_importes([5000])
        html = serialize_html(report)
        assert "$5,000.00" in html

    def test_html_string_value_formats(self):
        """Lines 90-93: _fmt_importe with a numeric string like '999.99'."""
        report = _make_report_with_importes(["999.99"])
        html = serialize_html(report)
        assert "$999.99" in html

    def test_html_none_value_falls_through(self):
        """Lines 90-95: _fmt_importe with None triggers exception path → '$None'."""
        report = _make_report_with_importes([None])
        html = serialize_html(report)
        assert "$None" in html

    def test_html_non_numeric_string_triggers_except(self):
        """Lines 94-95: _fmt_importe with 'abc' triggers exception → '$abc'."""
        report = _make_report_with_importes(["abc"])
        html = serialize_html(report)
        assert "$abc" in html

    def test_html_empty_list_no_crash(self):
        """Edge case: report with no sections still renders valid HTML."""
        report = ReportData(
            titulo="Vacío",
            subtitulo="",
            secciones=[],
            totales={},
        )
        html = serialize_html(report)
        assert "<!DOCTYPE html>" in html
        assert "Vacío" in html


# ---------------------------------------------------------------------------
# verify JSON serializer still works with edge cases
# ---------------------------------------------------------------------------

class TestJsonSerializerEdgeCases:
    """Quick sanity checks for JSON serializer."""

    def test_json_with_none_values(self):
        """serialize_json handles sections with None importe."""
        report = _make_report_with_importes([None, 100])
        result = serialize_json(report)
        assert isinstance(result, str)
        data = __import__("json").loads(result)
        assert data["titulo"] == "Test Report"
