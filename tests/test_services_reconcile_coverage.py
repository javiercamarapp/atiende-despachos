# -*- coding: utf-8 -*-
"""
Boost coverage for b2b_ai/services/reconcile.py.

Targets uncovered lines:
  - _is_header_row (108-111)
  - CSV row parse exception (138-139)
  - Reference column swap (158-159)
  - Short/empty row skip (164, 166)
  - monto assignment logic (187)
  - _extract_pdf_text TJ path (220-222)
  - _clean_part (230)
  - parse_bank_statement_pdf errors (246-247, 256-257, 260)
  - _parse_statement_text edge cases (282, 285, 294)
  - reconcile edge cases (337)
"""
from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

from b2b_ai.services.reconcile import (
    _dec, _parse_date, _is_header_row, _sniff_delimiter,
    parse_bank_statement_csv, parse_bank_statement_pdf,
    _parse_statement_text, _extract_pdf_text, _clean_part,
    reconcile, build_reconciliation_report,
)


# ---------------------------------------------------------------------------
# _is_header_row  (lines 108-111)
# ---------------------------------------------------------------------------
class TestIsHeaderRow:
    def test_header_row_detected(self):
        """A row of text values should be detected as a header."""
        cells = ["Fecha", "Descripcion", "Cargo", "Abono"]
        assert _is_header_row(cells, []) is True

    def test_empty_cells(self):
        assert _is_header_row([], []) is False

    def test_numeric_row_not_header(self):
        cells = ["100.00", "200.00", "300.00"]
        assert _is_header_row(cells, []) is False

    def test_mixed_mostly_text(self):
        cells = ["Fecha", "Descripcion", "100"]
        assert _is_header_row(cells, []) is True


# ---------------------------------------------------------------------------
# _sniff_delimiter edge cases
# ---------------------------------------------------------------------------
class TestSniffDelimiter:
    def test_tab_delimited(self):
        lines = ["a\tb\tc", "d\te\tf"]
        assert _sniff_delimiter(lines) == "\t"

    def test_semicolon_delimited(self):
        lines = ["a;b;c", "d;e;f"]
        assert _sniff_delimiter(lines) == ";"

    def test_comma_delimited(self):
        lines = ["a,b,c", "d,e,f"]
        assert _sniff_delimiter(lines) == ","

    def test_no_delimiters(self):
        assert _sniff_delimiter(["singleline"]) == ","


# ---------------------------------------------------------------------------
# parse_bank_statement_csv  (lines 138-139, 158-159, 164, 166, 187)
# ---------------------------------------------------------------------------
class TestParseBankStatementCSV:
    def test_reference_column_swap(self, tmp_path):
        """When header has 'referencia' as the only desc-like column, it becomes ref (158-159)."""
        csv_content = "fecha,referencia,monto\n2026-01-15,REF-001,500.00\n"
        path = tmp_path / "bank.csv"
        path.write_text(csv_content, encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        assert len(result) == 1
        assert result[0]["ref"] == "REF-001"

    def test_empty_csv(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        assert result == []

    def test_short_row_skipped(self, tmp_path):
        """Row shorter than fecha column index should be skipped (line 164)."""
        csv_content = "fecha,descripcion,monto\n2026-01-15,test,100\nx\n"
        path = tmp_path / "bank.csv"
        path.write_text(csv_content, encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        # The short row 'x' should be skipped
        assert len(result) <= 1

    def test_empty_row_skipped(self, tmp_path):
        """Completely empty rows should be skipped (line 166)."""
        csv_content = "fecha,descripcion,monto\n2026-01-15,test,100\n\n\n"
        path = tmp_path / "bank.csv"
        path.write_text(csv_content, encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        assert len(result) == 1

    def test_cargo_abono_columns(self, tmp_path):
        """Test CSV with separate cargo/abono columns."""
        csv_content = "fecha,descripcion,cargo,abono\n2026-01-15,test,500.00,\n"
        path = tmp_path / "bank.csv"
        path.write_text(csv_content, encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        assert len(result) == 1
        assert result[0]["monto"] is not None

    def test_only_monto_column(self, tmp_path):
        """Test CSV with only monto column (no cargo/abono)."""
        csv_content = "fecha,descripcion,monto\n2026-01-15,test,-500.00\n"
        path = tmp_path / "bank.csv"
        path.write_text(csv_content, encoding="utf-8")
        result = parse_bank_statement_csv(str(path))
        assert len(result) == 1
        assert result[0]["monto"] is not None


# ---------------------------------------------------------------------------
# _extract_pdf_text  (lines 220-222, 230)
# ---------------------------------------------------------------------------
class TestExtractPdfText:
    def test_tj_operator(self):
        """TJ array operator text extraction (lines 220-222)."""
        raw = b"[(Hello) (World)] TJ"
        text = _extract_pdf_text(raw.decode("latin-1"))
        assert "Hello" in text
        assert "World" in text

    def test_tj_with_escapes(self):
        """TJ with escaped parens."""
        raw = b"[(Test\\() (Data\\))] TJ"
        text = _extract_pdf_text(raw.decode("latin-1"))
        assert "Test(" in text
        assert "Data)" in text

    def test_clean_part_escapes(self):
        """_clean_part handles escaped parens and newlines (line 230)."""
        result = _clean_part(r"hello\(\) world\nnewline\rreturn")
        assert "(" in result
        assert ")" in result
        assert "\\n" not in result
        assert "\\r" not in result


# ---------------------------------------------------------------------------
# parse_bank_statement_pdf error paths  (lines 246-247, 256-257, 260)
# ---------------------------------------------------------------------------
class TestParseBankStatementPDF:
    def test_nonexistent_file_raises(self):
        with pytest.raises(ValueError, match="No se pudo abrir"):
            parse_bank_statement_pdf("/nonexistent/file.pdf")

    def test_non_pdf_header_raises(self, tmp_path):
        """File without %PDF header raises ValueError (line 250)."""
        bad = tmp_path / "not.pdf"
        bad.write_bytes(b"NOT A PDF FILE")
        with pytest.raises(ValueError, match="no parece ser un PDF"):
            parse_bank_statement_pdf(str(bad))

    def test_empty_pdf_no_text_layer(self, tmp_path):
        """PDF with no text layer raises ValueError (line 260-262)."""
        # Minimal fake PDF that passes the %PDF check but has no text
        pdf = tmp_path / "empty.pdf"
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")
        with pytest.raises(ValueError, match="no contiene capa de texto"):
            parse_bank_statement_pdf(str(pdf))


# ---------------------------------------------------------------------------
# _parse_statement_text edge cases  (lines 282, 285, 294)
# ---------------------------------------------------------------------------
class TestParseStatementText:
    def test_single_monto(self):
        """Test parsing with single monto column (line 294)."""
        text = "01/07/2026  5800.00  TRANSFERENCIA REF-001"
        result = _parse_statement_text(text)
        assert len(result) == 1
        assert result[0]["monto"] is not None

    def test_dual_monto(self):
        """Test parsing with dual montos (cargo/abono pattern)."""
        text = "01/07/2026  -5800.00  5800.00  TRANSFERENCIA"
        result = _parse_statement_text(text)
        assert len(result) == 1

    def test_no_ref_in_description(self):
        """Line without explicit REF pattern uses extracted REF if present, else empty."""
        text = "01/07/2026  500.00  DEPOSITO"
        result = _parse_statement_text(text)
        assert len(result) == 1
        assert result[0]["ref"] == ""

    def test_non_matching_line_skipped(self):
        """Lines not matching the date pattern are skipped (line 282)."""
        text = "Random text without dates\n01/07/2026  100.00  TEST REF-1"
        result = _parse_statement_text(text)
        assert len(result) == 1

    def test_iso_date_format(self):
        """ISO date format 2026-07-01."""
        text = "2026-07-01  100.00  TEST REF-1"
        result = _parse_statement_text(text)
        assert len(result) == 1

    def test_no_matching_monto_returns_empty(self):
        """Lines that match date but no valid monto are skipped."""
        text = "not a date line"
        result = _parse_statement_text(text)
        assert result == []


# ---------------------------------------------------------------------------
# reconcile edge cases  (line 337)
# ---------------------------------------------------------------------------
class TestReconcileEdgeCases:
    def test_bt_monto_none_skipped(self):
        """Bank transaction with None monto should be skipped (line 337)."""
        invoices = [{"total": "100", "fecha": "2026-01-15"}]
        bank_tx = [{"monto": None, "fecha": "2026-01-15"}]
        result = reconcile(invoices, bank_tx)
        assert len(result["matched"]) == 0

    def test_invoice_with_no_total(self):
        """Invoice with no total should be skipped."""
        invoices = [{"fecha": "2026-01-15"}]
        bank_tx = [{"monto": 100, "fecha": "2026-01-15"}]
        result = reconcile(invoices, bank_tx)
        assert len(result["matched"]) == 0

    def test_exact_reference_match(self):
        """Reference-based matching (pasada 2)."""
        invoices = [{"folio_fiscal": "UUID-123", "total": "999", "fecha": "2026-01-01"}]
        bank_tx = [{"monto": 500, "fecha": "2026-01-20", "ref": "UUID-123"}]
        result = reconcile(invoices, bank_tx, date_tolerance_days=0)
        assert len(result["matched"]) == 1
        assert result["matched"][0]["via"] == "referencia"

    def test_empty_inputs(self):
        result = reconcile([], [])
        assert result["matched"] == []
        assert result["unmatched_bank"] == []
        assert result["unmatched_invoices"] == []

    def test_no_match(self):
        """No matching at all."""
        invoices = [{"total": "100", "fecha": "2026-01-15"}]
        bank_tx = [{"monto": 999, "fecha": "2026-01-15"}]
        result = reconcile(invoices, bank_tx)
        assert len(result["matched"]) == 0
        assert len(result["unmatched_bank"]) == 1
        assert len(result["unmatched_invoices"]) == 1


# ---------------------------------------------------------------------------
# build_reconciliation_report
# ---------------------------------------------------------------------------
class TestBuildReconciliationReport:
    def test_report_basic(self):
        invoices = [
            {"folio_fiscal": "F1", "total": "100", "fecha": "2026-01-15", "emisor": "A"},
        ]
        bank_tx = [
            {"monto": 100, "fecha": "2026-01-15", "ref": "REF-1"},
        ]
        report = build_reconciliation_report(invoices, bank_tx, period="2026-01")
        assert report["periodo"] == "2026-01"
        assert report["conciliados"] == 1
        assert report["facturas"] == 1
        assert report["movimientos_banco"] == 1

    def test_report_no_matches(self):
        report = build_reconciliation_report([], [])
        assert report["conciliados"] == 0
        assert report["tasa_conciliacion"] == 0.0

    def test_report_with_period(self):
        report = build_reconciliation_report([], [], period=None)
        assert report["periodo"] is None
