# -*- coding: utf-8 -*-
"""
Comprehensive tests for b2b_ai/services/reconcile.py
Covers: _dec, _norm_fecha, _parse_date, _fecha_dist, _header_index,
        _sniff_delimiter, _is_header_row, parse_bank_statement_csv,
        _extract_pdf_text, _parse_statement_text, _clean_part,
        reconcile, _build_match, build_reconciliation_report
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from decimal import Decimal

import pytest

from b2b_ai.services.reconcile import (
    _dec, _norm_fecha, _parse_date, _fecha_dist,
    _header_index, _sniff_delimiter, _is_header_row,
    parse_bank_statement_csv, _extract_pdf_text, _parse_statement_text,
    _clean_part, reconcile, _build_match, build_reconciliation_report,
    _COL_FECHA, _COL_DESCR, _COL_REF, _COL_CARGO, _COL_ABONO, _COL_MONTO,
)


# ---------------------------------------------------------------------------
# Helpers: _dec
# ---------------------------------------------------------------------------

class TestDec:
    def test_none(self):
        assert _dec(None) is None

    def test_empty(self):
        assert _dec("") is None

    def test_dash(self):
        assert _dec("-") is None
        assert _dec("--") is None

    def test_na(self):
        assert _dec("N/A") is None
        assert _dec("n/a") is None

    def test_valid(self):
        assert _dec("1234.56") == Decimal("1234.56")

    def test_commas(self):
        assert _dec("1,234.56") == Decimal("1234.56")

    def test_dollar(self):
        assert _dec("$500.00") == Decimal("500.00")

    def test_negative(self):
        assert _dec("-100.00") == Decimal("-100.00")

    def test_integer(self):
        assert _dec("42") == Decimal("42")

    def test_invalid(self):
        assert _dec("abc") is None

    def test_spaces(self):
        assert _dec(" 100.00 ") == Decimal("100.00")


# ---------------------------------------------------------------------------
# Helpers: _norm_fecha
# ---------------------------------------------------------------------------

class TestNormFecha:
    def test_none(self):
        assert _norm_fecha(None) == ""

    def test_empty(self):
        assert _norm_fecha("") == ""

    def test_full(self):
        assert _norm_fecha("2026-07-15") == "2026-07-15"

    def test_datetime(self):
        assert _norm_fecha("2026-07-15T10:30:00") == "2026-07-15"

    def test_truncate(self):
        assert _norm_fecha("2026-07-15 extra") == "2026-07-15"


# ---------------------------------------------------------------------------
# Helpers: _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso(self):
        assert _parse_date("2026-07-15") == date(2026, 7, 15)

    def test_european(self):
        assert _parse_date("15/07/2026") == date(2026, 7, 15)

    def test_dash_european(self):
        assert _parse_date("15-07-2026") == date(2026, 7, 15)

    def test_short_year(self):
        assert _parse_date("15/07/26") == date(2026, 7, 15)

    def test_yyyy_slash(self):
        assert _parse_date("2026/07/15") == date(2026, 7, 15)

    def test_us_format(self):
        assert _parse_date("07/15/2026") == date(2026, 7, 15)

    def test_dmy_month_name(self):
        assert _parse_date("15 Jul 2026") == date(2026, 7, 15)

    def test_month_name_comma(self):
        assert _parse_date("Jul 15, 2026") == date(2026, 7, 15)

    def test_none(self):
        assert _parse_date(None) is None

    def test_empty(self):
        assert _parse_date("") is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Helpers: _fecha_dist
# ---------------------------------------------------------------------------

class TestFechaDist:
    def test_same(self):
        assert _fecha_dist("2026-07-15", "2026-07-15") == 0

    def test_one_day(self):
        assert _fecha_dist("2026-07-15", "2026-07-16") == 1

    def test_30_days(self):
        assert _fecha_dist("2026-01-01", "2026-01-31") == 30

    def test_invalid(self):
        assert _fecha_dist("bad", "2026-07-15") is None

    def test_both_invalid(self):
        assert _fecha_dist("bad1", "bad2") is None

    def test_symmetric(self):
        assert _fecha_dist("2026-07-01", "2026-07-05") == _fecha_dist("2026-07-05", "2026-07-01")


# ---------------------------------------------------------------------------
# Helpers: _header_index
# ---------------------------------------------------------------------------

class TestHeaderIndex:
    def test_found(self):
        headers = ["fecha", "monto", "descripcion"]
        assert _header_index(headers, _COL_FECHA) == 0

    def test_not_found(self):
        headers = ["x", "y", "z"]
        assert _header_index(headers, _COL_FECHA) is None

    def test_case_insensitive(self):
        headers = ["FECHA", "MONTO"]
        assert _header_index(headers, _COL_FECHA) == 0

    def test_ref_column(self):
        headers = ["descripcion", "ref", "monto"]
        assert _header_index(headers, _COL_REF) == 1


# ---------------------------------------------------------------------------
# Helpers: _sniff_delimiter
# ---------------------------------------------------------------------------

class TestSniffDelimiter:
    def test_comma(self):
        lines = ["a,b,c", "1,2,3"]
        assert _sniff_delimiter(lines) == ","

    def test_semicolon(self):
        lines = ["a;b;c", "1;2;3"]
        assert _sniff_delimiter(lines) == ";"

    def test_tab(self):
        lines = ["a\tb\tc", "1\t2\t3"]
        assert _sniff_delimiter(lines) == "\t"

    def test_empty(self):
        assert _sniff_delimiter([]) == ","

    def test_mixed_wins_comma(self):
        lines = ["a,b,c", "1,2,3", "4;5"]
        assert _sniff_delimiter(lines) == ","


# ---------------------------------------------------------------------------
# Helpers: _is_header_row
# ---------------------------------------------------------------------------

class TestIsHeaderRow:
    def test_all_text(self):
        assert _is_header_row(["fecha", "monto", "desc"], set()) is True

    def test_mostly_text(self):
        assert _is_header_row(["fecha", "monto", "123"], set()) is True

    def test_mostly_numeric(self):
        assert _is_header_row(["100", "200", "300"], set()) is False

    def test_empty(self):
        assert _is_header_row([], set()) is False


# ---------------------------------------------------------------------------
# parse_bank_statement_csv
# ---------------------------------------------------------------------------

class TestParseBankStatementCSV:
    def _write_csv(self, content, suffix=".csv"):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_basic_csv(self):
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago proveedor,REF-1\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 1
            assert result[0]["fecha"] == "2026-07-15"
            assert result[0]["monto"] == Decimal("500.00")
            assert result[0]["descripcion"] == "Pago proveedor"
            assert result[0]["ref"] == "REF-1"
        finally:
            os.unlink(path)

    def test_cargo_abono_columns(self):
        csv_content = "fecha,cargo,abono,descripcion\n2026-07-15,500.00,,Pago\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 1
            assert result[0]["monto"] < 0  # cargo = negative
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = self._write_csv("")
        try:
            result = parse_bank_statement_csv(path)
            assert result == []
        finally:
            os.unlink(path)

    def test_no_matching_headers(self):
        csv_content = "x,y,z\n1,2,3\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            # Without matching headers, no rows are parsed
            assert len(result) == 0
        finally:
            os.unlink(path)

    def test_multiple_rows(self):
        csv_content = "fecha,monto,descripcion,ref\n"
        for i in range(5):
            csv_content += f"2026-07-{15+i},100.00,Pago{i},REF-{i}\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 5
        finally:
            os.unlink(path)

    def test_semicolon_delimiter(self):
        csv_content = "fecha;monto;descripcion;ref\n2026-07-15;500.00;Pago;REF-1\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 1
        finally:
            os.unlink(path)

    def test_skip_empty_rows(self):
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n\n\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 1
        finally:
            os.unlink(path)

    def test_missing_date_skips_row(self):
        csv_content = "fecha,monto,descripcion,ref\n,500.00,Pago,REF-1\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            # Row without date is skipped
            assert len(result) == 0
        finally:
            os.unlink(path)

    def test_missing_monto_skips_row(self):
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,,Pago,REF-1\n"
        path = self._write_csv(csv_content)
        try:
            result = parse_bank_statement_csv(path)
            assert len(result) == 0
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _extract_pdf_text / _clean_part
# ---------------------------------------------------------------------------

class TestExtractPdfText:
    def test_simple_tj(self):
        raw = "(Hello World) Tj"
        text = _extract_pdf_text(raw)
        assert "Hello World" in text

    def test_tj_array(self):
        raw = "[(Hello) (World)] TJ"
        text = _extract_pdf_text(raw)
        assert "Hello" in text
        assert "World" in text

    def test_escaped_parens(self):
        raw = r"(Hello \(World\)) Tj"
        text = _extract_pdf_text(raw)
        assert "Hello" in text

    def test_empty(self):
        assert _extract_pdf_text("") == ""


class TestCleanPart:
    def test_escaped_parens(self):
        assert _clean_part(r"Hello \(World\)") == "Hello (World)"

    def test_newline(self):
        assert _clean_part(r"Hello\nWorld") == "Hello World"

    def test_carriage_return(self):
        assert _clean_part(r"Hello\rWorld") == "Hello World"

    def test_normal(self):
        assert _clean_part("Hello World") == "Hello World"


# ---------------------------------------------------------------------------
# _parse_statement_text
# ---------------------------------------------------------------------------

class TestParseStatementText:
    def test_basic_line(self):
        text = "03/07/2026 5800.00 -5800.00 TRANSFERENCIA REF-1234"
        result = _parse_statement_text(text)
        assert len(result) >= 1
        assert result[0]["fecha"] is not None

    def test_two_monto_line(self):
        text = "03/07/2026 1000.00 -1000.00 Pago ref-5"
        result = _parse_statement_text(text)
        assert len(result) >= 1

    def test_single_monto_line(self):
        text = "03/07/2026 5800.00 TRANSFERENCIA REF-1"
        result = _parse_statement_text(text)
        assert len(result) >= 1

    def test_no_date_line_skipped(self):
        text = "some random text without a date\nanother line"
        result = _parse_statement_text(text)
        assert result == []

    def test_iso_date(self):
        text = "2026-07-03 5800.00 TRANSFERENCIA"
        result = _parse_statement_text(text)
        assert len(result) >= 1
        assert result[0]["fecha"] == "2026-07-03"

    def test_empty(self):
        assert _parse_statement_text("") == []


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_exact_match(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "Prov"}]
        bank = [{"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "Pago", "ref": "REF-1"}]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 1
        assert result["matched"][0]["via"] == "monto+fecha"

    def test_no_match(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "9999.00", "emisor": "Prov"}]
        bank = [{"fecha": "2026-07-15", "monto": "1.00", "descripcion": "X", "ref": "OTHER"}]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 0
        assert len(result["unmatched_bank"]) == 1
        assert len(result["unmatched_invoices"]) == 1

    def test_reference_match(self):
        invoices = [{"folio_fiscal": "UUID-ABC", "fecha": "2026-07-15", "total": "500.00", "emisor": "Prov"}]
        bank = [{"fecha": "2026-07-20", "monto": "999.00", "descripcion": "Pago UUID-ABC", "ref": "UUID-ABC"}]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 1
        assert result["matched"][0]["via"] == "referencia"

    def test_date_outside_tolerance(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-01", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-20", "monto": "1000.00", "descripcion": "X", "ref": "R"}]
        result = reconcile(invoices, bank, date_tolerance_days=3)
        assert len(result["matched"]) == 0

    def test_date_within_tolerance(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-17", "monto": "1000.00", "descripcion": "X", "ref": "R"}]
        result = reconcile(invoices, bank, date_tolerance_days=3)
        assert len(result["matched"]) == 1

    def test_empty_invoices(self):
        bank = [{"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "X", "ref": "R"}]
        result = reconcile([], bank)
        assert len(result["matched"]) == 0
        assert len(result["unmatched_bank"]) == 1

    def test_empty_bank(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        result = reconcile(invoices, [])
        assert len(result["matched"]) == 0
        assert len(result["unmatched_invoices"]) == 1

    def test_both_empty(self):
        result = reconcile([], [])
        assert len(result["matched"]) == 0

    def test_multiple_matches(self):
        invoices = [
            {"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "A"},
            {"folio_fiscal": "F2", "fecha": "2026-07-16", "total": "2000.00", "emisor": "B"},
        ]
        bank = [
            {"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "A", "ref": "R1"},
            {"fecha": "2026-07-16", "monto": "2000.00", "descripcion": "B", "ref": "R2"},
        ]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 2

    def test_no_folio_skips_reference_match(self):
        invoices = [{"folio_fiscal": "", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "X", "ref": "R"}]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 1  # monto+fecha still works

    def test_no_ref_on_bank_skips_reference_match(self):
        invoices = [{"folio_fiscal": "UUID", "fecha": "2026-07-15", "total": "500.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-20", "monto": "500.00", "descripcion": "Pago", "ref": ""}]
        result = reconcile(invoices, bank, date_tolerance_days=0)
        assert len(result["matched"]) == 0

    def test_negative_monto_matches(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "-1000.00", "descripcion": "Cargo", "ref": "R"}]
        result = reconcile(invoices, bank)
        assert len(result["matched"]) == 1

    def test_match_preserves_folio(self):
        invoices = [{"folio_fiscal": "UUID-123", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "X", "ref": "R"}]
        result = reconcile(invoices, bank)
        assert result["matched"][0]["folio_fiscal"] == "UUID-123"


# ---------------------------------------------------------------------------
# _build_match
# ---------------------------------------------------------------------------

class TestBuildMatch:
    def test_basic(self):
        inv = {"folio_fiscal": "F1", "emisor": "Prov", "total": "1000.00", "fecha": "2026-07-15"}
        bt = {"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "Pago", "ref": "REF-1"}
        m = _build_match(inv, bt, 0, "monto+fecha")
        assert m["folio_fiscal"] == "F1"
        assert m["emisor"] == "Prov"
        assert m["monto"] == "1000.00"
        assert m["dias_diferencia"] == 0
        assert m["via"] == "monto+fecha"

    def test_no_ref_falls_back_to_descripcion(self):
        inv = {"folio_fiscal": "F1", "emisor": "P", "total": "100", "fecha": "2026-07-15"}
        bt = {"fecha": "2026-07-15", "monto": "100", "descripcion": "Desc", "ref": ""}
        m = _build_match(inv, bt, 0, "via")
        assert m["ref_banco"] == "Desc"

    def test_dist_none(self):
        inv = {"folio_fiscal": "F1", "emisor": "P", "total": "100", "fecha": "2026-07-15"}
        bt = {"fecha": "2026-07-15", "monto": "100", "descripcion": "X", "ref": "R"}
        m = _build_match(inv, bt, None, "via")
        assert m["dias_diferencia"] is None


# ---------------------------------------------------------------------------
# build_reconciliation_report
# ---------------------------------------------------------------------------

class TestBuildReconciliationReport:
    def test_full_report(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "Pago", "ref": "R"}]
        report = build_reconciliation_report(invoices, bank, period="2026-07")
        assert report["periodo"] == "2026-07"
        assert report["facturas"] == 1
        assert report["movimientos_banco"] == 1
        assert report["conciliados"] == 1
        assert report["pendientes_banco"] == 0
        assert report["pendientes_facturas"] == 0
        assert float(report["tasa_conciliacion"]) == 100.0

    def test_no_matches(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "9999.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "1.00", "descripcion": "X", "ref": "R"}]
        report = build_reconciliation_report(invoices, bank)
        assert report["conciliados"] == 0
        assert report["pendientes_banco"] == 1
        assert report["pendientes_facturas"] == 1

    def test_empty_data(self):
        report = build_reconciliation_report([], [])
        assert report["facturas"] == 0
        assert report["movimientos_banco"] == 0
        assert report["conciliados"] == 0
        assert report["tasa_conciliacion"] == 0.0

    def test_por_periodo(self):
        invoices = [
            {"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "P"},
            {"folio_fiscal": "F2", "fecha": "2026-07-20", "total": "2000.00", "emisor": "Q"},
        ]
        bank = [
            {"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "A", "ref": "R1"},
            {"fecha": "2026-07-20", "monto": "2000.00", "descripcion": "B", "ref": "R2"},
        ]
        report = build_reconciliation_report(invoices, bank)
        assert report["conciliados"] == 2
        # por_periodo should have entries
        assert isinstance(report["por_periodo"], dict)

    def test_report_keys(self):
        report = build_reconciliation_report([], [])
        expected = {"periodo", "facturas", "movimientos_banco", "conciliados",
                    "pendientes_banco", "pendientes_facturas", "monto_conciliado",
                    "monto_banco_total", "monto_pendiente_banco", "monto_pendiente_facturas",
                    "tasa_conciliacion", "por_periodo", "matched",
                    "unmatched_bank", "unmatched_invoices"}
        assert expected == set(report.keys())

    def test_monto_conciliado(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "500.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "500.00", "descripcion": "X", "ref": "R"}]
        report = build_reconciliation_report(invoices, bank)
        assert report["monto_conciliado"] == "500.00"
        assert report["monto_banco_total"] == "500.00"
        assert report["monto_pendiente_banco"] == "0.00"

    def test_monto_pendiente(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "9999.00", "emisor": "P"}]
        bank = [{"fecha": "2026-07-15", "monto": "100.00", "descripcion": "X", "ref": "R"}]
        report = build_reconciliation_report(invoices, bank)
        assert float(report["monto_pendiente_banco"]) == 100.0


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

class TestColumnConstants:
    def test_fecha_columns(self):
        assert "fecha" in _COL_FECHA
        assert "date" in _COL_FECHA

    def test_descr_columns(self):
        assert "descripcion" in _COL_DESCR
        assert "concepto" in _COL_DESCR

    def test_ref_columns(self):
        assert "referencia" in _COL_REF
        assert "ref" in _COL_REF

    def test_cargo_columns(self):
        assert "cargo" in _COL_CARGO
        assert "retiro" in _COL_CARGO

    def test_abono_columns(self):
        assert "abono" in _COL_ABONO
        assert "deposito" in _COL_ABONO

    def test_monto_columns(self):
        assert "monto" in _COL_MONTO
        assert "importe" in _COL_MONTO
