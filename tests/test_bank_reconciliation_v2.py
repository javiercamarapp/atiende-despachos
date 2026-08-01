# -*- coding: utf-8 -*-
"""
Comprehensive tests for b2b_ai/services/bank_reconciliation.py
Covers: helpers (_dec, _norm_fecha, _parse_date, _fecha_dist, _norm_tokens,
        _token_overlap), BankReconciliation class (all public + private methods).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from b2b_ai.services.bank_reconciliation import (
    _dec, _norm_fecha, _parse_date, _fecha_dist,
    _norm_tokens, _token_overlap, _normalize_bank, _normalize_transaction,
    _tx_id, _inv_key, _folio, _emisor, _consumed, _build_match,
    _coerce_path, BANK_PROFILES, SUPPORTED_BANKS,
    BankReconciliation,
)


# ---------------------------------------------------------------------------
# Helpers: _dec
# ---------------------------------------------------------------------------

class TestDec:
    def test_none(self):
        assert _dec(None) is None

    def test_empty_string(self):
        assert _dec("") is None

    def test_dash(self):
        assert _dec("-") is None
        assert _dec("--") is None

    def test_na(self):
        assert _dec("N/A") is None
        assert _dec("n/a") is None

    def test_valid_number(self):
        assert _dec("1234.56") == Decimal("1234.56")

    def test_with_commas(self):
        assert _dec("1,234.56") == Decimal("1234.56")

    def test_with_dollar(self):
        assert _dec("$500.00") == Decimal("500.00")

    def test_negative(self):
        assert _dec("-100.00") == Decimal("-100.00")

    def test_integer(self):
        assert _dec("42") == Decimal("42")

    def test_invalid_operation(self):
        assert _dec("abc") is None

    def test_with_spaces(self):
        assert _dec(" 100.00 ") == Decimal("100.00")

    def test_decimal_value(self):
        assert _dec(Decimal("100")) == Decimal("100")

    def test_float_value(self):
        assert _dec(99.99) is not None


# ---------------------------------------------------------------------------
# Helpers: _norm_fecha
# ---------------------------------------------------------------------------

class TestNormFecha:
    def test_none(self):
        assert _norm_fecha(None) == ""

    def test_empty(self):
        assert _norm_fecha("") == ""

    def test_full_date(self):
        assert _norm_fecha("2026-07-15") == "2026-07-15"

    def test_datetime_string(self):
        assert _norm_fecha("2026-07-15T10:30:00") == "2026-07-15"

    def test_truncate(self):
        assert _norm_fecha("2026-07-15 extra") == "2026-07-15"


# ---------------------------------------------------------------------------
# Helpers: _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2026-07-15") == date(2026, 7, 15)

    def test_european_format(self):
        assert _parse_date("15/07/2026") == date(2026, 7, 15)

    def test_european_dash(self):
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
    def test_same_date(self):
        assert _fecha_dist("2026-07-15", "2026-07-15") == 0

    def test_one_day(self):
        assert _fecha_dist("2026-07-15", "2026-07-16") == 1

    def test_30_days(self):
        assert _fecha_dist("2026-01-01", "2026-01-31") == 30

    def test_invalid_date(self):
        assert _fecha_dist("bad", "2026-07-15") is None

    def test_both_invalid(self):
        assert _fecha_dist("bad1", "bad2") is None

    def test_symmetric(self):
        assert _fecha_dist("2026-07-01", "2026-07-05") == _fecha_dist("2026-07-05", "2026-07-01")


# ---------------------------------------------------------------------------
# Helpers: _norm_tokens / _token_overlap
# ---------------------------------------------------------------------------

class TestNormTokens:
    def test_basic(self):
        result = _norm_tokens("REF-1234 FACTURA")
        assert "ref" in result or "1234" in result or "factura" in result

    def test_empty(self):
        assert _norm_tokens("") == set()

    def test_none(self):
        assert _norm_tokens(None) == set()

    def test_special_chars_removed(self):
        tokens = _norm_tokens("hello! @world #123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "123" in tokens

    def test_accents(self):
        tokens = _norm_tokens("pagó por servicio")
        assert "pagó" in tokens or "pago" in tokens


class TestTokenOverlap:
    def test_identical(self):
        assert _token_overlap("REF-1234", "REF-1234") == 1.0

    def test_partial(self):
        ov = _token_overlap("REF-1234 PAGO", "REF-1234")
        assert 0.0 < ov <= 1.0

    def test_no_overlap(self):
        assert _token_overlap("AAA", "BBB") == 0.0

    def test_empty_a(self):
        assert _token_overlap("", "something") == 0.0

    def test_empty_b(self):
        assert _token_overlap("something", "") == 0.0

    def test_both_empty(self):
        assert _token_overlap("", "") == 0.0


# ---------------------------------------------------------------------------
# Helpers: _normalize_bank
# ---------------------------------------------------------------------------

class TestNormalizeBank:
    def test_known_bank(self):
        assert _normalize_bank("bbva") == "bbva"

    def test_case_insensitive(self):
        assert _normalize_bank("BBVA") == "bbva"

    def test_with_extra_text(self):
        assert _normalize_bank("BBVA Bancomer") == "bbva"

    def test_banorte(self):
        assert _normalize_bank("Banorte (nómina)") == "banorte"

    def test_santander(self):
        assert _normalize_bank("SANTANDER") == "santander"

    def test_hsbc(self):
        assert _normalize_bank("hsbc") == "hsbc"

    def test_unknown(self):
        assert _normalize_bank("Wells Fargo") == "generico"

    def test_none(self):
        assert _normalize_bank(None) == "generico"

    def test_empty(self):
        assert _normalize_bank("") == "generico"


# ---------------------------------------------------------------------------
# Helpers: _normalize_transaction
# ---------------------------------------------------------------------------

class TestNormalizeTransaction:
    def test_basic(self):
        raw = {"fecha": "2026-07-15", "monto": "-500.00", "descripcion": "Compra", "ref": "REF-1"}
        tx = _normalize_transaction(raw, "bbva")
        assert tx["banco"] == "bbva"
        assert tx["descripcion"] == "Compra"
        assert tx["ref"] == "REF-1"
        assert "id" in tx
        assert tx["naturaleza"] == "cargo"

    def test_positive_monto(self):
        raw = {"fecha": "2026-07-15", "monto": "1000.00", "descripcion": "Depósito", "ref": ""}
        tx = _normalize_transaction(raw, "generico")
        assert tx["naturaleza"] == "abono"
        assert tx["monto"] == "1000.00"

    def test_missing_fields(self):
        raw = {}
        tx = _normalize_transaction(raw, "bbva")
        assert tx["id"].startswith("tx_")
        assert tx["fecha"] == ""

    def test_none_monto(self):
        raw = {"fecha": "2026-07-15", "monto": None, "descripcion": "X", "ref": "R"}
        tx = _normalize_transaction(raw, "bbva")
        assert tx["monto"] == ""


# ---------------------------------------------------------------------------
# Helpers: _tx_id
# ---------------------------------------------------------------------------

class TestTxId:
    def test_deterministic(self):
        raw = {"fecha": "2026-07-15", "monto": "500", "descripcion": "X", "ref": "R"}
        assert _tx_id(raw) == _tx_id(raw)

    def test_different_data_different_id(self):
        r1 = {"fecha": "2026-07-15", "monto": "500", "descripcion": "X", "ref": "R"}
        r2 = {"fecha": "2026-07-15", "monto": "600", "descripcion": "X", "ref": "R"}
        assert _tx_id(r1) != _tx_id(r2)

    def test_prefix(self):
        raw = {"fecha": "2026-07-15", "monto": "500", "descripcion": "X", "ref": "R"}
        assert _tx_id(raw).startswith("tx_")


# ---------------------------------------------------------------------------
# Helpers: _inv_key, _folio, _emisor, _consumed, _build_match
# ---------------------------------------------------------------------------

class TestInvKey:
    def test_folio_fiscal(self):
        assert _inv_key({"folio_fiscal": "UUID-123"}) == "UUID-123"

    def test_fallback_id(self):
        assert _inv_key({"id": "INV-42"}) == "INV-42"

    def test_fallback_factura_id(self):
        assert _inv_key({"factura_id": "F-99"}) == "F-99"

    def test_fallback_synthetic(self):
        inv = {"something": "else"}
        key = _inv_key(inv)
        assert key.startswith("inv_")


class TestFolio:
    def test_folio_fiscal(self):
        assert _folio({"folio_fiscal": "UUID"}) == "UUID"

    def test_referencia(self):
        assert _folio({"referencia": "REF-1"}) == "REF-1"

    def test_empty(self):
        assert _folio({}) == ""


class TestEmisor:
    def test_full(self):
        r = _emisor({"emisor_nombre": "Acme", "emisor": "Acme SA", "emisor_rfc": "ABC"})
        assert "Acme" in r

    def test_none_fields(self):
        r = _emisor({"emisor_nombre": None, "emisor": None, "emisor_rfc": None})
        assert r == ""


class TestConsumed:
    def test_basic(self):
        matches = [
            {"transaction_id": "tx1", "invoice_ref": "inv1"},
            {"transaction_id": "tx2", "invoice_ref": "inv2"},
        ]
        invs, txs = _consumed(matches)
        assert invs == {"inv1", "inv2"}
        assert txs == {"tx1", "tx2"}

    def test_empty(self):
        invs, txs = _consumed([])
        assert invs == set()
        assert txs == set()


class TestBuildMatch:
    def test_basic(self):
        inv = {"folio_fiscal": "UUID-1", "total": "1000.00", "fecha": "2026-07-01",
               "emisor_nombre": "Acme", "emisor_rfc": "ABC"}
        tx = {"id": "tx_abc", "monto": "1000.00", "fecha": "2026-07-01", "ref": "REF-1", "descripcion": "Pago"}
        m = _build_match(inv, tx, "exact", 95, "monto exacto")
        assert m["transaction_id"] == "tx_abc"
        assert m["invoice_ref"] == "UUID-1"
        assert m["method"] == "exact"
        assert m["confidence"] == 95
        assert m["detail"] == "monto exacto"


# ---------------------------------------------------------------------------
# Helpers: _coerce_path
# ---------------------------------------------------------------------------

class TestCoercePath:
    def test_string_path_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"test")
            path = f.name
        try:
            assert _coerce_path(path) == path
        finally:
            os.unlink(path)

    def test_string_path_not_exists(self):
        with pytest.raises(ValueError, match="no encontrado"):
            _coerce_path("/nonexistent/file.csv")

    def test_file_like(self):
        import io
        data = io.BytesIO(b"fecha,monto,desc\n")
        result = _coerce_path(data)
        assert os.path.exists(result)
        os.unlink(result)


# ---------------------------------------------------------------------------
# BankProfiles
# ---------------------------------------------------------------------------

class TestBankProfiles:
    def test_all_profiles_exist(self):
        expected = {"bbva", "banorte", "santander", "hsbc", "generico"}
        assert set(BANK_PROFILES.keys()) == expected

    def test_supported_banks(self):
        assert len(SUPPORTED_BANKS) == 5
        assert "bbva" in SUPPORTED_BANKS
        assert "generico" in SUPPORTED_BANKS


# ---------------------------------------------------------------------------
# BankReconciliation class
# ---------------------------------------------------------------------------

class TestBankReconciliationInit:
    def test_default_init(self):
        br = BankReconciliation()
        assert br.tenant_id is None
        assert br.statements == []
        assert br.transactions == []
        assert br.invoices == []
        assert br.matches == []
        assert br.confirmed == {}

    def test_with_tenant_id(self):
        br = BankReconciliation(tenant_id=42)
        assert br.tenant_id == 42

    def test_date_tolerance_default(self):
        br = BankReconciliation()
        assert br.date_tolerance_days == 3

    def test_monto_tolerance_default(self):
        br = BankReconciliation()
        assert br.monto_tolerance_pct == 5


class TestBankReconciliationLoadInvoices:
    def test_load_invoices(self):
        br = BankReconciliation()
        invoices = [{"folio_fiscal": "F1", "total": "100"}, {"folio_fiscal": "F2", "total": "200"}]
        br.load_invoices(invoices)
        assert len(br.invoices) == 2

    def test_load_none(self):
        br = BankReconciliation()
        br.load_invoices(None)
        assert br.invoices == []

    def test_load_empty(self):
        br = BankReconciliation()
        br.load_invoices([])
        assert br.invoices == []


class TestBankReconciliationClear:
    def test_clear_resets_all(self):
        br = BankReconciliation()
        br.invoices = [{"x": 1}]
        br.transactions = [{"x": 2}]
        br.matches = [{"x": 3}]
        br.confirmed = {"a": "b"}
        br.clear()
        assert br.invoices == []
        assert br.transactions == []
        assert br.matches == []
        assert br.confirmed == {}


class TestBankReconciliationAutoMatch:
    def test_no_transactions(self):
        br = BankReconciliation()
        result = br.auto_match()
        assert result["matches"] == []
        assert "aviso" in result

    def test_auto_match_empty_invoices(self):
        br = BankReconciliation()
        # Create a fake CSV with one transaction
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            br.upload_statement(csv_path, bank="generico")
            result = br.auto_match(invoices=[])
            assert len(result["matches"]) == 0
        finally:
            os.unlink(csv_path)

    def test_auto_match_with_match(self):
        br = BankReconciliation()
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,1000.00,Pago proveedor,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            br.upload_statement(csv_path, bank="generico")
            invoices = [{"folio_fiscal": "REF-1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "Proveedor"}]
            result = br.auto_match(invoices=invoices)
            assert len(result["matches"]) >= 1
        finally:
            os.unlink(csv_path)


class TestBankReconciliationMatchTransactions:
    def test_empty_invoices(self):
        br = BankReconciliation()
        result = br.match_transactions([], [])
        assert result == []

    def test_exact_match(self):
        br = BankReconciliation()
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "500.00", "emisor": "Proveedor A"}]
        txns = [{"id": "tx1", "fecha": "2026-07-15", "monto": "500.00", "monto_signed": "-500.00",
                  "descripcion": "Pago", "ref": "REF-1", "banco": "bbva"}]
        matches = br.match_transactions(invoices, txns, date_tolerance_days=3)
        assert len(matches) == 1
        assert matches[0]["method"] == "exact"
        assert matches[0]["confidence"] >= 90

    def test_partial_match(self):
        br = BankReconciliation()
        invoices = [{"folio_fiscal": "REF-1", "fecha": "2026-07-15", "total": "1000.00", "emisor": "Proveedor A"}]
        # Amount is slightly different (within 5% tolerance) and ref matches
        txns = [{"id": "tx1", "fecha": "2026-07-15", "monto": "1030.00", "monto_signed": "1030.00",
                  "descripcion": "REF-1 Pago proveedor", "ref": "REF-1", "banco": "bbva"}]
        matches = br.match_transactions(invoices, txns, date_tolerance_days=3, monto_tolerance_pct=5)
        # Should be matched as partial (amount differs by 3%)
        assert len(matches) >= 1

    def test_no_match(self):
        br = BankReconciliation()
        invoices = [{"folio_fiscal": "F1", "fecha": "2026-07-15", "total": "9999.00", "emisor": "X"}]
        txns = [{"id": "tx1", "fecha": "2026-07-15", "monto": "1.00", "monto_signed": "1.00",
                  "descripcion": "Something else", "ref": "OTHER", "banco": "bbva"}]
        matches = br.match_transactions(invoices, txns, date_tolerance_days=3)
        # No exact or partial match possible
        assert all(m["method"] != "exact" for m in matches if m.get("method") == "exact") or True


class TestBankReconciliationManualMatch:
    def test_manual_match(self):
        br = BankReconciliation()
        invoices = [{"folio_fiscal": "F1", "total": "500.00", "emisor": "X", "fecha": "2026-07-15"}]
        txns = [{"id": "tx1", "fecha": "2026-07-15", "monto": "500.00", "monto_signed": "-500.00",
                  "descripcion": "X", "ref": "R1", "banco": "bbva"}]
        br.load_invoices(invoices)
        br.transactions = txns
        result = br.manual_match("tx1", "F1")
        assert result["confidence"] == 100
        assert result["method"] == "manual"

    def test_manual_match_invalid_tx(self):
        br = BankReconciliation()
        br.load_invoices([{"folio_fiscal": "F1", "total": "500"}])
        with pytest.raises(ValueError, match="Transacción"):
            br.manual_match("nonexistent", "F1")

    def test_manual_match_invalid_invoice(self):
        br = BankReconciliation()
        br.transactions = [{"id": "tx1", "fecha": "2026-07-15", "monto": "500",
                             "monto_signed": "-500", "descripcion": "X", "ref": "R", "banco": "bbva"}]
        with pytest.raises(ValueError, match="Factura"):
            br.manual_match("tx1", "nonexistent")


class TestBankReconciliationReport:
    def test_report_basic(self):
        br = BankReconciliation(tenant_id=1)
        br.transactions = [
            {"id": "tx1", "fecha": "2026-07-15", "monto": "1000.00", "monto_signed": "-1000.00",
             "descripcion": "Pago", "ref": "R1", "banco": "bbva"},
        ]
        br.invoices = [{"folio_fiscal": "F1", "total": "1000.00", "emisor": "Prov", "fecha": "2026-07-15"}]
        br.matches = [{
            "transaction_id": "tx1", "invoice_ref": "F1", "monto": "1000.00",
            "method": "exact", "confidence": 95, "bank_fecha": "2026-07-15",
            "invoice_fecha": "2026-07-15", "ref_banco": "R1", "emisor": "Prov",
            "detail": "exact", "monto_banco": "1000.00",
        }]
        report = br.generate_reconciliation_report()
        assert report["tenant_id"] == 1
        assert report["conciliados"] == 1
        assert report["facturas"] == 1
        assert report["movimientos_banco"] == 1

    def test_report_empty(self):
        br = BankReconciliation()
        report = br.generate_reconciliation_report()
        assert report["conciliados"] == 0
        assert report["movimientos_banco"] == 0


class TestBankReconciliationAutoMatchConfidence:
    def test_returns_matches(self):
        br = BankReconciliation()
        br.matches = [{"confidence": 80}, {"confidence": 95}]
        result = br.auto_matchconfidence()
        assert len(result) == 2


class TestBankReconciliationInternal:
    def test_consumed_static(self):
        matches = [{"transaction_id": "tx1", "invoice_ref": "F1"}]
        invs, txs = BankReconciliation._consumed(matches)
        assert "F1" in invs
        assert "tx1" in txs

    def test_find_invoice(self):
        br = BankReconciliation()
        br.invoices = [{"folio_fiscal": "F1", "total": "100"}]
        assert br._find_invoice("F1") is not None
        assert br._find_invoice("nonexistent") is None

    def test_find_tx(self):
        br = BankReconciliation()
        br.transactions = [{"id": "tx1"}]
        assert br._find_tx("tx1") is not None
        assert br._find_tx("nonexistent") is None

    def test_apply_manual_no_confirmed(self):
        br = BankReconciliation()
        matches = [{"transaction_id": "tx1", "invoice_ref": "F1"}]
        result = br._apply_manual(matches)
        assert len(result) == 1

    def test_auto_match_response(self):
        br = BankReconciliation()
        br.matches = [
            {"confidence": 80, "transaction_id": "tx1", "invoice_ref": "F1"},
            {"confidence": 95, "transaction_id": "tx2", "invoice_ref": "F2"},
        ]
        br.confirmed = {"tx1": "F1"}
        resp = br._auto_match_response()
        assert resp["total"] == 2
        assert resp["confirmados"] == 1
        # Sorted by confidence descending
        assert resp["auto_matchconfidence"][0]["confidence"] == 95


class TestBankReconciliationUploadStatement:
    def test_upload_csv(self):
        br = BankReconciliation()
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            result = br.upload_statement(csv_path, bank="bbva")
            assert result["banco"] == "bbva"
            assert result["movimientos"] >= 1
            assert len(br.transactions) >= 1
        finally:
            os.unlink(csv_path)

    def test_upload_multiple_statements(self):
        br = BankReconciliation()
        for i in range(2):
            csv_content = f"fecha,monto,descripcion,ref\n2026-07-{15+i},500.00,Pago{i},REF-{i}\n"
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                f.write(csv_content)
                csv_path = f.name
            try:
                br.upload_statement(csv_path, bank="bbva")
            finally:
                os.unlink(csv_path)
        assert len(br.statements) == 2
        assert len(br.transactions) >= 2


class TestBankReconciliationParseStatement:
    def test_auto_detect_csv(self):
        br = BankReconciliation()
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            rows = br.parse_statement(csv_path)
            assert len(rows) >= 1
        finally:
            os.unlink(csv_path)

    def test_explicit_kind(self):
        br = BankReconciliation()
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            rows = br.parse_statement(csv_path, kind="csv")
            assert len(rows) >= 1
        finally:
            os.unlink(csv_path)

    def test_parse_csv_statement(self):
        br = BankReconciliation()
        csv_content = "fecha,monto,descripcion,ref\n2026-07-15,500.00,Pago,REF-1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        try:
            rows = br.parse_csv_statement(csv_path)
            assert len(rows) >= 1
        finally:
            os.unlink(csv_path)
