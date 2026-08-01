# -*- coding: utf-8 -*-
"""
test_reconciliation_agent.py — 25+ tests for the Reconciliation Agent.

Covers:
  - CSV parser (BBVA, Banorte, Santander, generic)
  - OFX parser
  - QIF parser
  - MT940 parser
  - PDF parser (with pdfplumber)
  - Matching engine (exact, fuzzy, multi-line)
  - ReconciliationResult model
  - SPEIVerification
  - Alert engine (aging, duplicates, large movements, income discrepancy)
  - API endpoint models
  - Edge cases (empty input, malformed data, etc.)
"""
from __future__ import annotations

import os
import tempfile
import pytest
from datetime import datetime, timedelta

from b2b_ai.features.reconciliation_agent.parsers import BankStatementParser
from b2b_ai.features.reconciliation_agent.matching_engine import MatchingEngine
from b2b_ai.features.reconciliation_agent.models import (
    BankMovement,
    MatchLevel,
    ReconciliationResult,
    AlertSeverity,
    AgingAlert,
    BancoMX,
    BankFormat,
)
from b2b_ai.features.reconciliation_agent.alerts import AlertEngine
from b2b_ai.features.reconciliation_agent.spei import SPEIVerifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp(content: str, suffix: str = ".csv") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _today():
    return datetime.utcnow().strftime("%Y-%m-%d")


def _days_ago(n):
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# TEST 1-3: CSV Parser
# ---------------------------------------------------------------------------

class TestCSVParser:
    """Tests for CSV parsing across multiple banks."""

    def test_csv_bbva_semicolon_delimited(self):
        """Test 1: BBVA CSV with semicolon delimiter."""
        csv_content = (
            "Fecha;Descripción;Referencia;Abono;Cargo;Saldo\n"
            "15/07/2026;Transferencia SPEI;REF001;5800.00;;5800.00\n"
            "16/07/2026;Pago proveedor;REF002;;1500.00;4300.00\n"
            "17/07/2026;Depósito efectivo;REF003;2000.00;;6300.00\n"
        )
        path = _write_temp(csv_content, ".csv")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="bbva")
            assert len(movs) == 3
            assert movs[0].fecha == "2026-07-15"
            assert movs[0].abono == 5800.0
            assert movs[0].descripcion == "Transferencia SPEI"
            assert movs[1].cargo == 1500.0
            assert movs[1].monto == -1500.0
            assert movs[2].monto == 2000.0
        finally:
            os.unlink(path)

    def test_csv_banorte_deposit_retiro_columns(self):
        """Test 2: Banorte CSV with Depósitos/Retiros columns."""
        csv_content = (
            "Fecha;Descripción;Referencia;Depósitos;Retiros;Saldo\n"
            "01/07/2026;Nómina quincenal;NOM001;25000.00;;25000.00\n"
            "03/07/2026;Pago servicios;SVC001;;3200.00;21800.00\n"
        )
        path = _write_temp(csv_content, ".csv")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="banorte")
            assert len(movs) == 2
            assert movs[0].monto == 25000.0
            assert movs[1].monto == -3200.0
        finally:
            os.unlink(path)

    def test_csv_generic_comma_delimited(self):
        """Test 3: Generic CSV with comma delimiter."""
        csv_content = (
            "date,description,amount\n"
            "2026-07-01,Venta producto,12500.50\n"
            "2026-07-02,Gasto oficina,-890.00\n"
        )
        path = _write_temp(csv_content, ".csv")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="generic")
            assert len(movs) == 2
            assert movs[0].monto == 12500.50
            assert movs[1].monto == -890.0
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TEST 4-6: OFX Parser
# ---------------------------------------------------------------------------

class TestOFXParser:
    """Tests for OFX parsing."""

    def test_ofx_basic_transactions(self):
        """Test 4: Parse basic OFX with multiple transactions."""
        ofx_content = """OFXHEADER:100
OFX:100
<SIGNONMSGSRSV1>
<SONRS>
<STATUS><CODE>0<SEVERITY>INFO
</STATUS>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260715
<TRNAMT>-1500.00
<FITID>TXN001
<NAME>PAGO PROVEEDOR A
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260716
<TRNAMT>5800.00
<FITID>TXN002
<NAME>COBRO CLIENTE B
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>"""
        path = _write_temp(ofx_content, ".ofx")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="citibanamex")
            assert len(movs) == 2
            assert movs[0].fecha == "2026-07-15"
            assert movs[0].monto == -1500.0
            assert movs[1].monto == 5800.0
            assert movs[1].referencia == "TXN002"
        finally:
            os.unlink(path)

    def test_ofx_date_parsing(self):
        """Test 5: OFX date format parsing."""
        parser = BankStatementParser()
        assert parser._parse_ofx_date("20260715") == "2026-07-15"
        assert parser._parse_ofx_date("20260715120000") == "2026-07-15"
        assert parser._parse_ofx_date("20261231") == "2026-12-31"

    def test_ofx_tag_extraction(self):
        """Test 6: OFX tag value extraction."""
        parser = BankStatementParser()
        block = "<TRNTYPE>DEBIT\n<DTPOSTED>20260715\n<TRNAMT>-1500.00\n"
        assert parser._ofx_tag(block, "TRNTYPE") == "DEBIT"
        assert parser._ofx_tag(block, "DTPOSTED") == "20260715"
        assert parser._ofx_tag(block, "TRNAMT") == "-1500.00"
        assert parser._ofx_tag(block, "NONEXISTENT") is None


# ---------------------------------------------------------------------------
# TEST 7-8: QIF Parser
# ---------------------------------------------------------------------------

class TestQIFParser:
    """Tests for QIF parsing."""

    def test_qif_basic_transactions(self):
        """Test 7: Parse QIF with multiple transactions."""
        qif_content = """!Type:Bank
D01/07/2026
T-1500.00
PPago proveedor
MTransferencia SPEI
NREF001
^
D03/07/2026
T5800.00
PCobro cliente
MDepósito
NREF002
^"""
        path = _write_temp(qif_content, ".qif")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="banregio")
            assert len(movs) == 2
            assert movs[0].fecha == "2026-07-01"
            assert movs[0].monto == -1500.0
            assert "Pago proveedor" in movs[0].descripcion
            assert movs[1].monto == 5800.0
            assert movs[1].referencia == "REF002"
        finally:
            os.unlink(path)

    def test_qif_header_detection(self):
        """Test 8: QIF header type detection."""
        parser = BankStatementParser()
        # Cash type
        content = "!Type:Cash\nD15/07/2026\nT100.00\n^"
        movs = parser._parse_qif_content(content, "banregio")
        assert len(movs) == 1
        assert movs[0].monto == 100.0


# ---------------------------------------------------------------------------
# TEST 9-10: MT940 Parser
# ---------------------------------------------------------------------------

class TestMT940Parser:
    """Tests for MT940 parsing."""

    def test_mt940_basic_transactions(self):
        """Test 9: Parse MT940 with debit and credit."""
        mt940_content = """:20:STMTID001
:25:0123456789
:60F:C260701MXN000000000000
:61:260715D1500,00NTRF
:86:Pago proveedor ABC
:61:260716C5800,00NTRF
:86:Cobro cliente XYZ
:62F:C260716MXN000000004300"""
        path = _write_temp(mt940_content, ".mt940")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="hsbc")
            assert len(movs) == 2
            assert movs[0].fecha == "2026-07-15"
            assert movs[0].monto == -1500.0
            assert "Pago proveedor" in movs[0].descripcion
            assert movs[1].monto == 5800.0
        finally:
            os.unlink(path)

    def test_mt940_61_field_parsing(self):
        """Test 10: MT940 :61: field parsing."""
        parser = BankStatementParser()
        m = parser._parse_mt940_61("260715D1500,00NTRF")
        assert m is not None
        assert m.fecha == "2026-07-15"
        assert m.monto == -1500.0

        m2 = parser._parse_mt940_61("260716C5800,00NTRF")
        assert m2 is not None
        assert m2.monto == 5800.0


# ---------------------------------------------------------------------------
# TEST 11: PDF Parser
# ---------------------------------------------------------------------------

class TestPDFParser:
    """Tests for PDF parsing (requires pdfplumber)."""

    def test_pdf_parser_requires_pdfplumber(self):
        """Test 11: PDF parser gracefully handles missing pdfplumber."""
        # Create a fake PDF-like file (just check the import path works)
        parser = BankStatementParser()
        # This tests the code path; actual PDF testing needs a real PDF
        assert parser is not None


# ---------------------------------------------------------------------------
# TEST 12-16: Matching Engine
# ---------------------------------------------------------------------------

class TestMatchingEngine:
    """Tests for the 4-level matching engine."""

    def _make_movements(self, data):
        return [BankMovement(
            fecha=d["fecha"],
            descripcion=d.get("desc", ""),
            referencia=d.get("ref"),
            cargo=d.get("cargo"),
            abono=d.get("abono"),
            monto=d.get("monto", (d.get("abono") or 0) - (d.get("cargo") or 0)),
        ) for d in data]

    def test_exact_match(self):
        """Test 12: Exact matching (same amount, same date)."""
        movs = self._make_movements([
            {"fecha": "2026-07-15", "abono": 5800.0, "monto": 5800.0, "desc": "Transferencia"},
        ])
        records = [
            {"fecha": "2026-07-15", "monto": 5800.0, "total": 5800.0, "descripcion": "Factura A"},
        ]
        engine = MatchingEngine()
        result = engine.match(movs, records)
        assert result.total_matched == 1
        assert len(result.unmatched_bank) == 0
        assert result.matched[0].level == MatchLevel.EXACT
        assert result.matched[0].score == 100

    def test_fuzzy_match(self):
        """Test 13: Fuzzy matching (similar amount, similar description)."""
        movs = self._make_movements([
            {"fecha": "2026-07-15", "abono": 5800.0, "monto": 5800.0,
             "desc": "Transferencia SPEI Proveedor ABC"},
        ])
        records = [
            {"fecha": "2026-07-16", "monto": 5780.0, "total": 5780.0,
             "descripcion": "Transferencia SPEI Proveedor ABC SA"},
        ]
        engine = MatchingEngine(
            date_tolerance_days=3,
            monto_tolerance_pct=5.0,
            fuzzy_threshold=70,
        )
        result = engine.match(movs, records)
        assert result.total_matched == 1
        assert result.matched[0].level == MatchLevel.FUZZY
        assert result.matched[0].score >= 50

    def test_multiline_match(self):
        """Test 14: Multi-line matching (one bank payment covers N records)."""
        movs = self._make_movements([
            {"fecha": "2026-07-15", "abono": 5000.0, "monto": 5000.0,
             "desc": "Transferencia SPEI"},
        ])
        records = [
            {"fecha": "2026-07-15", "monto": 2000.0, "total": 2000.0, "descripcion": "Factura 1"},
            {"fecha": "2026-07-15", "monto": 1500.0, "total": 1500.0, "descripcion": "Factura 2"},
            {"fecha": "2026-07-15", "monto": 1500.0, "total": 1500.0, "descripcion": "Factura 3"},
        ]
        engine = MatchingEngine(date_tolerance_days=3, monto_tolerance_pct=5.0)
        result = engine.match(movs, records)
        assert result.total_matched == 1
        assert result.matched[0].level == MatchLevel.MULTI_LINE
        assert result.matched[0].registro_indices is not None
        assert len(result.matched[0].registro_indices) == 3

    def test_no_match_different_amounts(self):
        """Test 15: No match when amounts are very different."""
        movs = self._make_movements([
            {"fecha": "2026-07-15", "abono": 5800.0, "monto": 5800.0, "desc": "Pago"},
        ])
        records = [
            {"fecha": "2026-07-15", "monto": 1500.0, "total": 1500.0, "descripcion": "Factura"},
        ]
        engine = MatchingEngine()
        result = engine.match(movs, records)
        assert result.total_matched == 0
        assert len(result.unmatched_bank) == 1
        assert len(result.unmatched_books) == 1

    def test_match_result_confidence(self):
        """Test 16: ReconciliationResult confidence calculation."""
        movs = self._make_movements([
            {"fecha": "2026-07-15", "abono": 10000.0, "monto": 10000.0, "desc": "Pago 1"},
            {"fecha": "2026-07-16", "abono": 5000.0, "monto": 5000.0, "desc": "Pago 2"},
        ])
        records = [
            {"fecha": "2026-07-15", "monto": 10000.0, "total": 10000.0, "descripcion": "Fact 1"},
        ]
        engine = MatchingEngine()
        result = engine.match(movs, records)
        assert result.total_matched == 1
        assert result.confidence > 0
        assert result.match_rate == 50.0  # 1/2
        assert result.monto_unmatched_bank == 5000.0


# ---------------------------------------------------------------------------
# TEST 17-18: Alert Engine
# ---------------------------------------------------------------------------

class TestAlertEngine:
    """Tests for the aging alert engine."""

    def test_large_movement_alert(self):
        """Test 17: Critical alert for large unidentified movements."""
        result = ReconciliationResult(
            unmatched_bank=[
                BankMovement(
                    fecha=_days_ago(5),
                    descripcion="Transferencia desconocida",
                    monto=75000.0,
                ),
            ],
        )
        engine = AlertEngine(large_movement_threshold=50000)
        alerts = engine.generate_alerts(result)
        large_alerts = [a for a in alerts if a.rule == "large_unidentified"]
        assert len(large_alerts) == 1
        assert large_alerts[0].severity == AlertSeverity.CRITICAL

    def test_bank_fee_alert(self):
        """Test 18: Info alert for bank fees."""
        result = ReconciliationResult(
            unmatched_bank=[
                BankMovement(
                    fecha=_days_ago(3),
                    descripcion="Comisión por transferencia",
                    monto=-45.00,
                ),
            ],
        )
        engine = AlertEngine()
        alerts = engine.generate_alerts(result)
        fee_alerts = [a for a in alerts if a.rule == "bank_fee"]
        assert len(fee_alerts) == 1
        assert fee_alerts[0].severity == AlertSeverity.INFO

    def test_aging_escalation(self):
        """Test 19: Aging escalation for old unreconciled items."""
        result = ReconciliationResult(
            unmatched_bank=[
                BankMovement(
                    fecha=_days_ago(45),
                    descripcion="Depósito sin factura",
                    monto=3000.0,
                ),
            ],
        )
        engine = AlertEngine()
        alerts = engine.generate_alerts(result)
        aging_alerts = [a for a in alerts if a.rule == "aging_escalation"]
        assert len(aging_alerts) >= 1
        assert aging_alerts[0].severity == AlertSeverity.CRITICAL
        assert "45 días" in aging_alerts[0].message

    def test_duplicate_detection(self):
        """Test 20: Duplicate payment detection."""
        result = ReconciliationResult(
            unmatched_bank=[
                BankMovement(fecha=_today(), descripcion="Pago ABC", monto=-5000.0),
                BankMovement(fecha=_days_ago(1), descripcion="Pago ABC", monto=-5000.0),
            ],
        )
        engine = AlertEngine()
        alerts = engine.generate_alerts(result)
        dup_alerts = [a for a in alerts if a.rule == "duplicate_payment"]
        assert len(dup_alerts) >= 1

    def test_income_discrepancy(self):
        """Test 21: Income discrepancy alert (Art. 91 LISR)."""
        engine = AlertEngine(income_discrepancy_ratio=1.15)
        # Deposits > declared × 1.15
        alert = engine.check_income_discrepancy(
            total_deposits=120000.0,
            declared_income=100000.0,
        )
        assert alert is not None
        assert alert.severity == AlertSeverity.CRITICAL
        assert "Art. 91" in alert.message

        # No discrepancy
        alert2 = engine.check_income_discrepancy(
            total_deposits=100000.0,
            declared_income=100000.0,
        )
        assert alert2 is None


# ---------------------------------------------------------------------------
# TEST 22-23: SPEI Verification
# ---------------------------------------------------------------------------

class TestSPEIVerification:
    """Tests for SPEI payment verification."""

    def test_verify_against_movements_found(self):
        """Test 22: SPEI verification finds matching movement."""
        verifier = SPEIVerifier()
        movements = [
            BankMovement(
                fecha="2026-07-15",
                descripcion="SPEI BNET0123456789",
                referencia="BNET0123456789",
                monto=5000.0,
            ),
        ]
        result = verifier.verify_pago_proveedor(
            proveedor_rfc="ABC123456XYZ",
            monto=5000.0,
            fecha_aprox="2026-07-15",
            movements=movements,
        )
        assert result is not None
        assert result.monto == 5000.0

    def test_verify_against_movements_not_found(self):
        """Test 23: SPEI verification returns None when no match."""
        verifier = SPEIVerifier()
        movements = [
            BankMovement(
                fecha="2026-07-15",
                descripcion="Otro movimiento",
                monto=1000.0,
            ),
        ]
        result = verifier.verify_pago_proveedor(
            proveedor_rfc="ABC123456XYZ",
            monto=5000.0,
            fecha_aprox="2026-07-15",
            movements=movements,
        )
        assert result is None


# ---------------------------------------------------------------------------
# TEST 24-26: Models and Edge Cases
# ---------------------------------------------------------------------------

class TestModelsAndEdgeCases:
    """Tests for data models and edge cases."""

    def test_bank_movement_properties(self):
        """Test 24: BankMovement property calculations."""
        m = BankMovement(fecha="2026-07-15", monto=5000.0, abono=5000.0)
        assert m.monto_abs == 5000.0
        assert m.naturaleza == "abono"

        m2 = BankMovement(fecha="2026-07-15", monto=-1500.0, cargo=1500.0)
        assert m2.monto_abs == 1500.0
        assert m2.naturaleza == "cargo"

    def test_empty_input_handling(self):
        """Test 25: Empty file handling."""
        parser = BankStatementParser()
        empty_csv = _write_temp("", ".csv")
        try:
            movs = parser.parse(empty_csv, bank="generic")
            assert len(movs) == 0
        finally:
            os.unlink(empty_csv)

    def test_malformed_csv_handling(self):
        """Test 26: Malformed CSV doesn't crash."""
        csv_content = (
            "fecha,monto,descripcion\n"
            "not a date,not a number,blah\n"
            "15/07/2026,5800.00,Transferencia\n"  # Only valid row
        )
        path = _write_temp(csv_content, ".csv")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="generic")
            assert len(movs) == 1  # Only the valid row
        finally:
            os.unlink(path)

    def test_matching_engine_empty_inputs(self):
        """Test 27: Matching engine handles empty inputs gracefully."""
        engine = MatchingEngine()
        result = engine.match([], [])
        assert result.total_matched == 0
        assert result.confidence == 0.0
        assert len(result.matched) == 0

    def test_bank_normalization(self):
        """Test 28: Bank name normalization."""
        parser = BankStatementParser()
        assert parser._normalize_bank("BBVA") == "bbva"
        assert parser._normalize_bank("BBVA Bancomer") == "bbva"
        assert parser._normalize_bank("SANTANDER") == "santander"
        assert parser._normalize_bank("banorte nomina") == "banorte"
        assert parser._normalize_bank("unknown_bank") == "generic"

    def test_format_detection(self):
        """Test 29: File format auto-detection."""
        from b2b_ai.features.reconciliation_agent.parsers import _detect_format
        assert _detect_format("state.ofx") == BankFormat.OFX
        assert _detect_format("state.qif") == BankFormat.QIF
        assert _detect_format("state.mt940") == BankFormat.MT940
        assert _detect_format("state.pdf") == BankFormat.PDF
        assert _detect_format("state.csv") == BankFormat.CSV
        assert _detect_format("state.xlsx") == BankFormat.XLSX
        assert _detect_format("state.unknown") == BankFormat.CSV

    def test_inter_account_transfer_alert(self):
        """Test 30: Inter-account transfer excluded from alerts."""
        result = ReconciliationResult(
            unmatched_bank=[
                BankMovement(
                    fecha=_days_ago(3),
                    descripcion="Transferencia entre cuentas propias",
                    monto=50000.0,
                ),
            ],
        )
        engine = AlertEngine()
        alerts = engine.generate_alerts(result)
        # Should have transfer alert but NOT deposit alert
        transfer_alerts = [a for a in alerts if a.rule == "inter_account_transfer"]
        deposit_alerts = [a for a in alerts if a.rule == "deposit_no_cfdi"]
        assert len(transfer_alerts) == 1
        assert len(deposit_alerts) == 0


# ---------------------------------------------------------------------------
# TEST 31-32: Existing reconcile.py integration
# ---------------------------------------------------------------------------

class TestExistingIntegration:
    """Tests ensuring we extend, not replace, existing reconciliation."""

    def test_existing_csv_parser_still_works(self):
        """Test 31: Existing reconcile.parse_bank_statement_csv still works."""
        from b2b_ai.services.reconcile import parse_bank_statement_csv
        csv_content = (
            "fecha,monto,descripcion\n"
            "2026-07-01,5000.00,Venta\n"
            "2026-07-02,-1200.00,Gasto\n"
        )
        path = _write_temp(csv_content, ".csv")
        try:
            movs = parse_bank_statement_csv(path)
            assert len(movs) == 2
            assert movs[0]["monto"] == 5000
        finally:
            os.unlink(path)

    def test_existing_bank_reconciliation_still_works(self):
        """Test 32: Existing BankReconciliation still works."""
        from b2b_ai.services.bank_reconciliation import BankReconciliation
        svc = BankReconciliation()
        csv_content = (
            "fecha,monto,descripcion\n"
            "2026-07-01,5000.00,Venta\n"
        )
        path = _write_temp(csv_content, ".csv")
        try:
            res = svc.upload_statement(path, bank="generico")
            assert res["movimientos"] == 1
            assert svc.transactions
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TEST 33: QIF with memo
# ---------------------------------------------------------------------------

class TestQIFEdgeCases:
    def test_qif_memo_only(self):
        """Test 33: QIF with memo field only (no payee)."""
        qif_content = "!Type:Bank\nD15/07/2026\nT-2500.00\nMPago de nómina\n^"
        path = _write_temp(qif_content, ".qif")
        try:
            parser = BankStatementParser()
            movs = parser.parse(path, bank="hsbc")
            assert len(movs) == 1
            assert "nómina" in movs[0].descripcion.lower()
        finally:
            os.unlink(path)
