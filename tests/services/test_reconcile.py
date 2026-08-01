# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/reconcile.py — bank reconciliation logic."""
import pytest
from decimal import Decimal
from b2b_ai.services.reconcile import (
    reconcile, _dec, _norm_fecha, _parse_date, _sniff_delimiter,
    build_reconciliation_report, _fecha_dist,
)


class TestDecHelpers:
    def test_dec_normal(self):
        assert _dec("1,234.56") == Decimal("1234.56")

    def test_dec_with_dollar(self):
        assert _dec("$500.00") == Decimal("500.00")

    def test_dec_none(self):
        assert _dec(None) is None

    def test_dec_empty(self):
        assert _dec("") is None

    def test_dec_n_a(self):
        assert _dec("N/A") is None

    def test_dec_garbage(self):
        assert _dec("abc") is None

    def test_dec_negative(self):
        assert _dec("-100.50") == Decimal("-100.50")

    def test_dec_integer(self):
        assert _dec(100) == Decimal("100")


class TestParseDate:
    def test_iso_date(self):
        assert _parse_date("2026-07-03") is not None

    def test_dd_mm_yyyy(self):
        d = _parse_date("03/07/2026")
        assert d is not None

    def test_empty(self):
        assert _parse_date("") is None

    def test_none(self):
        assert _parse_date(None) is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


class TestNormFecha:
    def test_shortens_long(self):
        assert _norm_fecha("2026-07-03T10:00:00") == "2026-07-03"

    def test_none(self):
        assert _norm_fecha(None) == ""

    def test_empty(self):
        assert _norm_fecha("") == ""


class TestSniffDelimiter:
    def test_comma(self):
        assert _sniff_delimiter(["a,b,c"]) == ","

    def test_semicolon(self):
        assert _sniff_delimiter(["a;b;c"]) == ";"

    def test_tab(self):
        assert _sniff_delimiter(["a\tb\tc"]) == "\t"

    def test_empty(self):
        assert _sniff_delimiter([]) == ","


class TestFechaDist:
    def test_same_date(self):
        assert _fecha_dist("2026-07-03", "2026-07-03") == 0

    def test_one_day(self):
        assert _fecha_dist("2026-07-03", "2026-07-04") == 1

    def test_invalid(self):
        assert _fecha_dist("bad", "bad") is None


class TestReconcile:
    def test_exact_match_monto_fecha(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-03",
                     "total": "1000.00", "emisor": "RFC1"}]
        bank = [{"fecha": "2026-07-03", "monto": 1000.0,
                 "descripcion": "Pago", "ref": "X"}]
        r = reconcile(invoices, bank)
        assert len(r["matched"]) == 1
        assert r["matched"][0]["via"] == "monto+fecha"
        assert len(r["unmatched_bank"]) == 0
        assert len(r["unmatched_invoices"]) == 0

    def test_date_tolerance(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-03",
                     "total": "500.00", "emisor": "RFC1"}]
        bank = [{"fecha": "2026-07-05", "monto": 500.0,
                 "descripcion": "Pago", "ref": "X"}]
        r = reconcile(invoices, bank, date_tolerance_days=3)
        assert len(r["matched"]) == 1

    def test_no_match_outside_tolerance(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-01",
                     "total": "500.00", "emisor": "RFC1"}]
        bank = [{"fecha": "2026-07-10", "monto": 500.0,
                 "descripcion": "Pago", "ref": "X"}]
        r = reconcile(invoices, bank, date_tolerance_days=3)
        assert len(r["matched"]) == 0

    def test_reference_match(self):
        invoices = [{"folio_fiscal": "UUID-ABC-123", "fecha": "2026-07-01",
                     "total": "2000.00", "emisor": "RFC1"}]
        bank = [{"fecha": "2026-07-15", "monto": 2000.0,
                 "descripcion": "Pago", "ref": "UUID-ABC-123"}]
        r = reconcile(invoices, bank, date_tolerance_days=0)
        assert len(r["matched"]) == 1
        assert r["matched"][0]["via"] == "referencia"

    def test_empty_inputs(self):
        r = reconcile([], [])
        assert r["matched"] == []
        assert r["unmatched_bank"] == []
        assert r["unmatched_invoices"] == []

    def test_unmatched_bank(self):
        invoices = []
        bank = [{"fecha": "2026-07-03", "monto": 1000.0,
                 "descripcion": "Pago", "ref": ""}]
        r = reconcile(invoices, bank)
        assert len(r["unmatched_bank"]) == 1

    def test_unmatched_invoices(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-03",
                     "total": "1000.00", "emisor": "RFC1"}]
        bank = []
        r = reconcile(invoices, bank)
        assert len(r["unmatched_invoices"]) == 1

    def test_missing_fields_no_crash(self):
        invoices = [{"total": None}]
        bank = [{}]
        r = reconcile(invoices, bank)
        assert r["matched"] == []


class TestReconciliationReport:
    def test_basic_report(self):
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-03",
                     "total": "1000.00", "emisor": "RFC1"}]
        bank = [{"fecha": "2026-07-03", "monto": 1000.0,
                 "descripcion": "Pago", "ref": ""}]
        rep = build_reconciliation_report(invoices, bank)
        assert rep["conciliados"] == 1
        assert rep["pendientes_banco"] == 0
        assert rep["pendientes_facturas"] == 0
        assert float(rep["tasa_conciliacion"]) == 100.0

    def test_empty_report(self):
        rep = build_reconciliation_report([], [])
        assert rep["conciliados"] == 0
        assert rep["tasa_conciliacion"] == 0.0

    def test_report_with_period(self):
        rep = build_reconciliation_report([], [], period="2026-07")
        assert rep["periodo"] == "2026-07"
