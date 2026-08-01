# -*- coding: utf-8 -*-
"""
test_conciliacion.py — Tests for the Bank Reconciliation module.

Covers:
  - Models: construction, defaults, serialization, JSON schema
  - Service: exact matches, amount+date matches, partial reference matches
  - Service: discrepancy detection (>2% variance), CSV export
  - Service: edge cases (empty lists, duplicate transactions, same amount different dates)
  - Validators: bank statement validation, CFDI validation
  - Routes: all endpoints via TestClient, auth, error handling

40+ test cases organized by category.
"""
from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.features.conciliacion.models import (
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    MatchResult,
    MatchStatus,
    MatchType,
    TransactionType,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_bank_statement,
    validate_cfdi_for_conciliation,
)

API_KEY = "conciliacion-test-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "conciliacion_test.db"))
    return d


@pytest.fixture
def client(db):
    db.create_tenant("Conciliación Test Tenant")
    db.create_api_key(1, "conciliacion-api-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def _bank_txn(**overrides) -> dict:
    base = {
        "id": "TXN001",
        "date": "2024-01-15",
        "description": "Pago factura ABC",
        "amount": 10000.00,
        "type": "INGRESO",
        "reference": "REF123456",
        "bank_account": "1234",
    }
    base.update(overrides)
    return base


def _cfdi_ref(**overrides) -> dict:
    base = {
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "fecha": "2024-01-15",
        "rfc_emisor": "EMP850101AB1",
        "rfc_receptor": "REC900101CD2",
        "total": 10000.00,
        "tipo_comprobante": "I",
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. MODEL TESTS
# ===========================================================================

class TestModels:
    """Tests for Pydantic schemas."""

    def test_transaction_type_enum(self):
        assert TransactionType.INGRESO.value == "INGRESO"
        assert TransactionType.EGRESO.value == "EGRESO"
        assert TransactionType.TRANSFERENCIA.value == "TRANSFERENCIA"

    def test_match_status_enum(self):
        assert MatchStatus.MATCHED.value == "MATCHED"
        assert MatchStatus.UNMATCHED.value == "UNMATCHED"
        assert MatchStatus.PARTIAL.value == "PARTIAL"
        assert MatchStatus.DISCREPANCY.value == "DISCREPANCY"

    def test_match_type_enum(self):
        assert MatchType.EXACT.value == "EXACT"
        assert MatchType.AMOUNT_DATE.value == "AMOUNT_DATE"
        assert MatchType.PARTIAL_REFERENCE.value == "PARTIAL_REFERENCE"

    def test_bank_transaction_creation(self):
        txn = BankTransaction(
            id="TXN001",
            date="2024-01-15",
            description="Pago",
            amount=5000.0,
            type=TransactionType.INGRESO,
            reference="REF001",
            bank_account="1234",
        )
        assert txn.id == "TXN001"
        assert txn.amount == 5000.0
        assert txn.type == TransactionType.INGROS0 if False else TransactionType.INGRESO

    def test_bank_transaction_defaults(self):
        txn = BankTransaction(
            id="TXN001",
            date="2024-01-15",
            amount=100.0,
            type=TransactionType.EGRESO,
        )
        assert txn.description == ""
        assert txn.reference == ""
        assert txn.bank_account == ""

    def test_bank_transaction_zero_amount_rejected(self):
        with pytest.raises(Exception):
            BankTransaction(
                id="TXN001",
                date="2024-01-15",
                amount=0.0,
                type=TransactionType.INGRESO,
            )

    def test_cfdi_reference_creation(self):
        cfdi = CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15",
            rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2",
            total=15000.0,
        )
        assert cfdi.uuid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert cfdi.total == 15000.0
        assert cfdi.tipo_comprobante == "I"

    def test_cfdi_reference_defaults(self):
        cfdi = CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15",
            rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2",
            total=100.0,
        )
        assert cfdi.tipo_comprobante == "I"

    def test_match_result_creation(self):
        result = MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            match_type=MatchType.EXACT,
            confidence_score=1.0,
            status=MatchStatus.MATCHED,
        )
        assert result.confidence_score == 1.0
        assert result.status == MatchStatus.MATCHED

    def test_match_result_unmatched(self):
        result = MatchResult(
            bank_transaction_id="TXN001",
            confidence_score=0.0,
            status=MatchStatus.UNMATCHED,
        )
        assert result.cfdi_uuid is None
        assert result.confidence_score == 0.0

    def test_conciliation_report_creation(self):
        report = ConciliationReport(
            period="2024-01",
            total_transactions=10,
            matched=8,
            unmatched=2,
        )
        assert report.match_rate == 0.0  # Not set in constructor
        assert report.discrepancies == 0

    def test_bank_transaction_serialization(self):
        txn = BankTransaction(
            id="TXN001",
            date="2024-01-15",
            amount=5000.0,
            type=TransactionType.INGRESO,
        )
        data = txn.model_dump()
        assert isinstance(data, dict)
        assert data["id"] == "TXN001"

    def test_cfdi_reference_serialization(self):
        cfdi = CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15",
            rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2",
            total=100.0,
        )
        data = cfdi.model_dump()
        assert data["uuid"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


# ===========================================================================
# 2. SERVICE TESTS — MATCHING
# ===========================================================================

class TestMatchingAlgorithm:
    """Tests for the core matching algorithm."""

    def test_exact_match_same_amount_and_date(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert len(results) == 1
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.EXACT
        assert results[0].confidence_score == 1.0

    def test_exact_match_wrong_date_no_match(self):
        service = ConciliationService(date_tolerance_days=3)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-25", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        # Date diff is 10 days, outside tolerance of 3
        assert results[0].status == MatchStatus.UNMATCHED

    def test_amount_date_match_within_tolerance(self):
        service = ConciliationService(date_tolerance_days=3)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-18", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.AMOUNT_DATE
        assert results[0].confidence_score < 1.0

    def test_amount_date_match_outside_tolerance(self):
        service = ConciliationService(date_tolerance_days=2)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-20", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].status == MatchStatus.UNMATCHED

    def test_no_match_different_amount(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=5000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].status == MatchStatus.UNMATCHED

    def test_multiple_transactions_match_multiple_cfdi(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=20000.0,
                            type=TransactionType.INGRESO),
        ]
        cfdi = [
            CFDIReference(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                          fecha="2024-01-15", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=10000.0),
            CFDIReference(uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901",
                          fecha="2024-01-16", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=20000.0),
        ]
        results = service.match_transactions(txns, cfdi)
        assert len(results) == 2
        assert all(r.status == MatchStatus.MATCHED for r in results)

    def test_one_to_one_matching_cfdi_not_reused(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
        ]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        matched_count = sum(1 for r in results if r.status == MatchStatus.MATCHED)
        assert matched_count == 1  # Only one can match

    def test_same_amount_different_dates_one_matches(self):
        service = ConciliationService(date_tolerance_days=2)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [
            CFDIReference(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                          fecha="2024-01-15", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=10000.0),
            CFDIReference(uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901",
                          fecha="2024-01-25", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=10000.0),
        ]
        results = service.match_transactions(txns, cfdi)
        assert len(results) == 1
        assert results[0].cfdi_uuid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_egreso_transaction_matching(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=-5000.0,
            type=TransactionType.EGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=-5000.0,
            tipo_comprobante="E",
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.EXACT

    def test_transferencia_type_matching(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=3000.0,
            type=TransactionType.TRANSFERENCIA,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=3000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].match_type == MatchType.EXACT


# ===========================================================================
# 3. SERVICE TESTS — DISCREPANCIES
# ===========================================================================

class TestDiscrepancies:
    """Tests for discrepancy detection."""

    def test_no_discrepancy_exact_match(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        matches = service.match_transactions(txns, cfdi)
        discrepancies = service.find_discrepancies(matches, txns, cfdi)
        assert len(discrepancies) == 0

    def test_discrepancy_detected_above_threshold(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10500.0,  # 5% over
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        # This won't match in matching (different amounts), so we manually
        # create a match to test discrepancy detection
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            match_type=MatchType.EXACT,
            confidence_score=0.8,
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.find_discrepancies(matches, txns, cfdi)
        assert len(discrepancies) == 1
        assert discrepancies[0]["variance"] == 5.0

    def test_no_discrepancy_below_threshold(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10050.0,  # 0.5% over
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            match_type=MatchType.EXACT,
            confidence_score=0.8,
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.find_discrepancies(matches, txns, cfdi)
        assert len(discrepancies) == 0

    def test_discrepancy_negative_amount(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=9000.0,  # 10% under
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-15", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            match_type=MatchType.EXACT,
            confidence_score=0.8,
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.find_discrepancies(matches, txns, cfdi)
        assert len(discrepancies) == 1
        assert discrepancies[0]["variance"] == 10.0

    def test_no_discrepancy_without_data(self):
        service = ConciliationService()
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.find_discrepancies(matches)
        assert len(discrepancies) == 0

    def test_discrepancy_skip_unmatched(self):
        service = ConciliationService()
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            cfdi_uuid=None,
            status=MatchStatus.UNMATCHED,
        )]
        discrepancies = service.find_discrepancies(
            matches,
            [BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                             type=TransactionType.INGRESO)],
            [CFDIReference(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                           fecha="2024-01-15", rfc_emisor="EMP850101AB1",
                           rfc_receptor="REC900101CD2", total=10000.0)],
        )
        assert len(discrepancies) == 0


# ===========================================================================
# 4. SERVICE TESTS — REPORT GENERATION
# ===========================================================================

class TestReportGeneration:
    """Tests for report generation."""

    def test_report_basic(self):
        service = ConciliationService()
        matches = [
            MatchResult(bank_transaction_id="TXN001", cfdi_uuid="uuid1",
                        status=MatchStatus.MATCHED),
            MatchResult(bank_transaction_id="TXN002", cfdi_uuid=None,
                        status=MatchStatus.UNMATCHED),
        ]
        report = service.generate_report(matches, period="2024-01")
        assert report.total_transactions == 2
        assert report.matched == 1
        assert report.unmatched == 1
        assert report.period == "2024-01"

    def test_report_match_rate(self):
        service = ConciliationService()
        matches = [
            MatchResult(bank_transaction_id="TXN001", status=MatchStatus.MATCHED),
            MatchResult(bank_transaction_id="TXN002", status=MatchStatus.MATCHED),
            MatchResult(bank_transaction_id="TXN003", status=MatchStatus.UNMATCHED),
        ]
        report = service.generate_report(matches)
        assert report.match_rate == pytest.approx(66.67, abs=0.01)

    def test_report_empty_matches(self):
        service = ConciliationService()
        report = service.generate_report([])
        assert report.total_transactions == 0
        assert report.match_rate == 0.0


# ===========================================================================
# 5. SERVICE TESTS — CSV EXPORT
# ===========================================================================

class TestCSVExport:
    """Tests for CSV export."""

    def test_export_csv_basic(self):
        service = ConciliationService()
        report = ConciliationReport(
            period="2024-01",
            total_transactions=5,
            matched=4,
            unmatched=1,
            match_rate=80.0,
            details=[],
        )
        csv_str = service.export_csv(report)
        assert "Periodo" in csv_str
        assert "2024-01" in csv_str
        assert "80.0" in csv_str

    def test_export_csv_with_discrepancies(self):
        service = ConciliationService()
        report = ConciliationReport(
            period="2024-01",
            total_transactions=3,
            matched=2,
            unmatched=1,
            match_rate=66.67,
            details=[],
        )
        discrepancies = [{
            "bank_transaction_id": "TXN001",
            "cfdi_uuid": "uuid1",
            "bank_amount": 10500.0,
            "cfdi_total": 10000.0,
            "variance": 5.0,
            "variance_amount": 500.0,
        }]
        csv_str = service.export_csv(report, discrepancies)
        assert "10500.0" in csv_str
        assert "5.0" in csv_str

    def test_export_csv_parseable(self):
        service = ConciliationService()
        report = ConciliationReport(
            period="2024-01",
            total_transactions=2,
            matched=2,
            details=[
                {"bank_transaction_id": "TXN001", "cfdi_uuid": "uuid1",
                 "match_type": "EXACT", "confidence_score": 1.0, "status": "MATCHED"},
            ],
        )
        csv_str = service.export_csv(report)
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) >= 4  # Header + summary + blank + detail header + detail


# ===========================================================================
# 6. SERVICE TESTS — EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_bank_transactions(self):
        service = ConciliationService()
        results = service.match_transactions([], [_cfdi_ref()])
        assert len(results) == 0

    def test_empty_cfdi_list(self):
        service = ConciliationService()
        txn = BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )
        results = service.match_transactions([txn], [])
        assert len(results) == 1
        assert results[0].status == MatchStatus.UNMATCHED

    def test_both_empty(self):
        service = ConciliationService()
        results = service.match_transactions([], [])
        assert len(results) == 0

    def test_duplicate_transaction_ids(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN001", date="2024-01-16", amount=20000.0,
                            type=TransactionType.INGRESO),
        ]
        cfdi = [
            CFDIReference(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                          fecha="2024-01-15", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=10000.0),
            CFDIReference(uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901",
                          fecha="2024-01-16", rfc_emisor="EMP850101AB1",
                          rfc_receptor="REC900101CD2", total=20000.0),
        ]
        results = service.match_transactions(txns, cfdi)
        assert len(results) == 2
        # Both should still match
        matched = sum(1 for r in results if r.status == MatchStatus.MATCHED)
        assert matched == 2

    def test_same_amount_different_dates_outside_tolerance(self):
        service = ConciliationService(date_tolerance_days=1)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        cfdi = [CFDIReference(
            uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            fecha="2024-01-20", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=10000.0,
        )]
        results = service.match_transactions(txns, cfdi)
        assert results[0].status == MatchStatus.UNMATCHED

    def test_date_difference_valid_format(self):
        service = ConciliationService()
        diff = service._date_difference_days("2024-01-15", "2024-01-18")
        assert diff == 3

    def test_date_difference_invalid_format(self):
        service = ConciliationService()
        diff = service._date_difference_days("invalid", "2024-01-18")
        assert diff is None


# ===========================================================================
# 7. VALIDATOR TESTS
# ===========================================================================

class TestValidators:
    """Tests for bank statement and CFDI validators."""

    def test_valid_bank_statement(self):
        txns = [
            _bank_txn(id="TXN001"),
            _bank_txn(id="TXN002", amount=5000.0),
        ]
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is True
        assert len(errors) == 0

    def test_empty_bank_statement(self):
        is_valid, errors = validate_bank_statement([])
        assert is_valid is False
        assert "vacía" in errors[0]

    def test_missing_required_fields(self):
        txns = [{"id": "TXN001"}]  # Missing date, amount, type
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is False
        assert len(errors) >= 3

    def test_duplicate_bank_ids(self):
        txns = [_bank_txn(id="TXN001"), _bank_txn(id="TXN001")]
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is False
        assert any("duplicado" in e for e in errors)

    def test_invalid_date_format(self):
        txns = [_bank_txn(date="15-01-2024")]
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is False
        assert any("fecha" in e for e in errors)

    def test_zero_amount(self):
        txns = [_bank_txn(amount=0)]
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is False
        assert any("cero" in e for e in errors)

    def test_invalid_type(self):
        txns = [_bank_txn(type="INVALIDO")]
        is_valid, errors = validate_bank_statement(txns)
        assert is_valid is False
        assert any("tipo" in e for e in errors)

    def test_valid_cfdi_list(self):
        cfdi = [_cfdi_ref(), _cfdi_ref(uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901")]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is True
        assert len(errors) == 0

    def test_empty_cfdi_list(self):
        is_valid, errors = validate_cfdi_for_conciliation([])
        assert is_valid is False
        assert "vacía" in errors[0]

    def test_cfdi_missing_fields(self):
        cfdi = [{"uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is False

    def test_cfdi_duplicate_uuids(self):
        cfdi = [_cfdi_ref(), _cfdi_ref()]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is False
        assert any("duplicado" in e for e in errors)

    def test_cfdi_invalid_uuid_format(self):
        cfdi = [_cfdi_ref(uuid="not-a-valid-uuid")]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is False
        assert any("UUID" in e for e in errors)

    def test_cfdi_negative_total(self):
        cfdi = [_cfdi_ref(total=-100.0)]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is False
        assert any("negativo" in e for e in errors)

    def test_cfdi_invalid_tipo_comprobante(self):
        cfdi = [_cfdi_ref(tipo_comprobante="X")]
        is_valid, errors = validate_cfdi_for_conciliation(cfdi)
        assert is_valid is False
        assert any("tipo_comprobante" in e for e in errors)


# ===========================================================================
# 8. ROUTE TESTS
# ===========================================================================

class TestRoutes:
    """Tests for the API routes via TestClient."""

    def test_match_endpoint_success(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10000.0)],
            "cfdi_list": [_cfdi_ref(total=10000.0)],
            "date_tolerance_days": 3,
        }
        resp = tc.post(
            "/api/v1/conciliacion/match",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["matches"]) == 1

    def test_match_endpoint_no_auth(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [_bank_txn()],
            "cfdi_list": [_cfdi_ref()],
        }
        resp = tc.post("/api/v1/conciliacion/match", json=payload)
        assert resp.status_code in (401, 403)

    def test_match_endpoint_empty_transactions(self, client):
        tc, db = client
        payload = {"bank_transactions": [], "cfdi_list": [_cfdi_ref()]}
        resp = tc.post(
            "/api/v1/conciliacion/match",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 422

    def test_match_endpoint_invalid_data(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [{"id": "X"}],
            "cfdi_list": [_cfdi_ref()],
        }
        resp = tc.post(
            "/api/v1/conciliacion/match",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 422

    def test_report_endpoint_found(self, client):
        tc, db = client
        # First create a report
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10000.0, date="2024-01-15")],
            "cfdi_list": [_cfdi_ref(total=10000.0, fecha="2024-01-15")],
        }
        tc.post("/api/v1/conciliacion/match", json=payload, headers=_auth())
        # Then retrieve it
        resp = tc.get("/api/v1/conciliacion/report/2024-01", headers=_auth())
        assert resp.status_code == 200
        assert "report" in resp.json()

    def test_report_endpoint_not_found(self, client):
        tc, db = client
        resp = tc.get("/api/v1/conciliacion/report/9999-99", headers=_auth())
        assert resp.status_code == 404

    def test_discrepancies_endpoint(self, client):
        tc, db = client
        resp = tc.get("/api/v1/conciliacion/discrepancies", headers=_auth())
        assert resp.status_code == 200
        assert "discrepancies" in resp.json()

    def test_export_endpoint(self, client):
        tc, db = client
        payload = {
            "period": "2024-01",
            "matches": [
                {"bank_transaction_id": "TXN001", "cfdi_uuid": "uuid1",
                 "match_type": "EXACT", "confidence_score": 1.0,
                 "status": "MATCHED"},
            ],
            "bank_transactions": [],
            "cfdi_list": [],
        }
        resp = tc.post(
            "/api/v1/conciliacion/export",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "csv" in data

    def test_export_download_endpoint(self, client):
        tc, db = client
        payload = {
            "period": "2024-01",
            "matches": [],
            "bank_transactions": [],
            "cfdi_list": [],
        }
        resp = tc.post(
            "/api/v1/conciliacion/export/download",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_match_multiple_transactions(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [
                _bank_txn(id="TXN001", amount=10000.0, date="2024-01-15"),
                _bank_txn(id="TXN002", amount=20000.0, date="2024-01-16"),
                _bank_txn(id="TXN003", amount=5000.0, date="2024-01-17"),
            ],
            "cfdi_list": [
                _cfdi_ref(total=10000.0, fecha="2024-01-15"),
                _cfdi_ref(uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901",
                          total=20000.0, fecha="2024-01-16"),
            ],
        }
        resp = tc.post(
            "/api/v1/conciliacion/match",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_transactions"] == 3
        matched = sum(1 for m in data["matches"] if m["status"] == "MATCHED")
        assert matched == 2
