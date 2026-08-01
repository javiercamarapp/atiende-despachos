# -*- coding: utf-8 -*-
"""
test_conciliacion.py — Comprehensive tests for the Bank Reconciliation module.

Covers:
  - Models: construction, defaults, serialization, JSON schema
  - Service: exact matches, amount+date matches, partial reference matches
  - Service: poliza matching (4-pass algorithm), amount-only matching
  - Service: discrepancy detection (monto, fecha, faltante, sobrante, duplicado)
  - Service: adjustment proposals (corrections, manual entries, voids, reviews)
  - Service: reconciliation report generation (comprehensive)
  - Service: CSV export
  - Service: edge cases (empty lists, duplicate transactions, same amount different dates)
  - Validators: bank statement validation, CFDI validation, poliza validation
  - Validators: amount matching, date range validation
  - Routes: all endpoints via TestClient, auth, error handling
  - Routes: upload, match, reconcile, apply, discrepancies, adjustments, export

80+ test cases organized by category.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.features.conciliacion.models import (
    Adjustment,
    AdjustmentStatus,
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    Discrepancy,
    DiscrepancyType,
    MatchResult,
    MatchStatus,
    MatchType,
    PolizaContable,
    TransactionType,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_amount_match,
    validate_bank_statement,
    validate_cfdi_for_conciliation,
    validate_date_range,
    validate_polizas_contables,
    validate_reconciliation_data,
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


def _poliza(**overrides) -> dict:
    base = {
        "id": "POL001",
        "fecha": "2024-01-15",
        "monto": 10000.00,
        "descripcion": "Pago factura cliente ABC",
        "cuenta": "101.01",
        "concepto": "Ingreso por venta",
        "referencia": "REF123456",
        "rfc": "EMP850101AB1",
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
        assert MatchType.AMOUNT_ONLY.value == "AMOUNT_ONLY"

    def test_discrepancy_type_enum(self):
        assert DiscrepancyType.MONTO.value == "monto"
        assert DiscrepancyType.FECHA.value == "fecha"
        assert DiscrepancyType.FALTANTE.value == "faltante"
        assert DiscrepancyType.SOBRANTE.value == "sobrante"
        assert DiscrepancyType.DUPLICADO.value == "duplicado"

    def test_adjustment_status_enum(self):
        assert AdjustmentStatus.PROPOSED.value == "PROPOSED"
        assert AdjustmentStatus.APPROVED.value == "APPROVED"
        assert AdjustmentStatus.REJECTED.value == "REJECTED"
        assert AdjustmentStatus.APPLIED.value == "APPLIED"

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
        assert txn.type == TransactionType.INGRESO

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

    def test_match_result_with_poliza(self):
        result = MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            match_type=MatchType.EXACT,
            confidence_score=1.0,
            status=MatchStatus.MATCHED,
        )
        assert result.poliza_id == "POL001"
        assert result.cfdi_uuid is None

    def test_conciliation_report_creation(self):
        report = ConciliationReport(
            period="2024-01",
            total_transactions=10,
            matched=8,
            unmatched=2,
        )
        assert report.match_rate == 0.0
        assert report.discrepancies == 0

    def test_conciliation_report_with_polizas(self):
        report = ConciliationReport(
            period="2024-01",
            total_transactions=10,
            matched=8,
            unmatched=2,
            total_polizas=12,
            polizas_matched=8,
        )
        assert report.total_polizas == 12
        assert report.polizas_matched == 8

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

    def test_poliza_contable_creation(self):
        pol = PolizaContable(
            id="POL001",
            fecha="2024-01-15",
            monto=10000.0,
            descripcion="Pago factura",
            cuenta="101.01",
            concepto="Ingreso",
            referencia="REF001",
            rfc="EMP850101AB1",
        )
        assert pol.id == "POL001"
        assert pol.monto == 10000.0
        assert pol.cuenta == "101.01"

    def test_poliza_contable_defaults(self):
        pol = PolizaContable(
            id="POL001",
            fecha="2024-01-15",
            monto=5000.0,
        )
        assert pol.descripcion == ""
        assert pol.cuenta == ""
        assert pol.concepto == ""
        assert pol.referencia == ""
        assert pol.rfc == ""

    def test_poliza_contable_zero_monto_rejected(self):
        with pytest.raises(Exception):
            PolizaContable(
                id="POL001",
                fecha="2024-01-15",
                monto=0.0,
            )

    def test_discrepancy_creation(self):
        disc = Discrepancy(
            id="DISC001",
            type=DiscrepancyType.MONTO,
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            bank_amount=10500.0,
            poliza_amount=10000.0,
            variance=5.0,
            variance_amount=500.0,
            details="Diferencia de monto detectada",
        )
        assert disc.type == DiscrepancyType.MONTO
        assert disc.variance == 5.0

    def test_adjustment_creation(self):
        adj = Adjustment(
            id="ADJ001",
            discrepancy_id="DISC001",
            proposal="Corregir póliza POL001",
            adjustment_type="correction",
            journal_entry={
                "tipo": "correccion",
                "cuenta_debito": "101.01",
                "cuenta_credito": "501.01",
                "monto": 500.0,
            },
            reason="Diferencia de monto",
            status=AdjustmentStatus.PROPOSED,
        )
        assert adj.status == AdjustmentStatus.PROPOSED
        assert adj.journal_entry is not None
        assert adj.journal_entry["monto"] == 500.0

    def test_adjustment_defaults(self):
        adj = Adjustment(
            id="ADJ001",
            discrepancy_id="DISC001",
            proposal="Test",
        )
        assert adj.adjustment_type == "correction"
        assert adj.status == AdjustmentStatus.PROPOSED
        assert adj.applied_by is None
        assert adj.applied_at is None


# ===========================================================================
# 2. SERVICE TESTS — MATCHING (Bank vs CFDI)
# ===========================================================================

class TestMatchingAlgorithm:
    """Tests for the core matching algorithm (CFDI)."""

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
# 3. SERVICE TESTS — MATCHING (Bank vs Polizas)
# ===========================================================================

class TestPolizaMatching:
    """Tests for matching bank transactions against polizas contables."""

    def test_exact_match_poliza(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
            descripcion="Pago factura",
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert len(results) == 1
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.EXACT
        assert results[0].poliza_id == "POL001"

    def test_amount_date_match_poliza(self):
        service = ConciliationService(date_tolerance_days=3)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-17", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.AMOUNT_DATE

    def test_reference_match_poliza(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO, reference="REF123456",
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
            referencia="REF123456",
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].match_type == MatchType.EXACT

    def test_amount_only_match_poliza(self):
        service = ConciliationService(amount_tolerance=0.01)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-02-15", monto=10000.0,  # Different month
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert results[0].status == MatchStatus.PARTIAL
        assert results[0].match_type == MatchType.AMOUNT_ONLY

    def test_no_match_different_amount_poliza(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=5000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert results[0].status == MatchStatus.UNMATCHED

    def test_multiple_polizas_match(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=20000.0,
                            type=TransactionType.EGRESO),
        ]
        polizas = [
            PolizaContable(id="POL001", fecha="2024-01-15", monto=10000.0),
            PolizaContable(id="POL002", fecha="2024-01-16", monto=20000.0),
        ]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert len(results) == 2
        assert all(r.status == MatchStatus.MATCHED for r in results)

    def test_poliza_not_reused(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
        ]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.match_transactions_to_polizas(txns, polizas)
        matched = sum(1 for r in results if r.status == MatchStatus.MATCHED)
        assert matched == 1

    def test_empty_polizas(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        results = service.match_transactions_to_polizas(txns, [])
        assert len(results) == 1
        assert results[0].status == MatchStatus.UNMATCHED

    def test_empty_transactions_polizas(self):
        service = ConciliationService()
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.match_transactions_to_polizas([], polizas)
        assert len(results) == 0


# ===========================================================================
# 4. SERVICE TESTS — RECONCILIATION PIPELINE
# ===========================================================================

class TestReconciliationPipeline:
    """Tests for the full reconcile_bank_statement method."""

    def test_full_reconciliation_with_polizas(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=5000.0,
                            type=TransactionType.EGRESO),
        ]
        polizas = [
            PolizaContable(id="POL001", fecha="2024-01-15", monto=10000.0),
            PolizaContable(id="POL002", fecha="2024-01-16", monto=5000.0),
        ]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        assert len(results["poliza_matches"]) == 2
        assert all(m.status == MatchStatus.MATCHED for m in results["poliza_matches"])
        assert len(results["unmatched_bank"]) == 0
        assert len(results["unmatched_polizas"]) == 0

    def test_reconciliation_with_discrepancy(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10500.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        assert len(results["discrepancies"]) > 0
        assert len(results["adjustments"]) > 0

    def test_reconciliation_finds_unmatched_bank(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=5000.0,
                            type=TransactionType.EGRESO),
        ]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        assert len(results["unmatched_bank"]) == 1
        assert results["unmatched_bank"][0].id == "TXN002"

    def test_reconciliation_finds_unmatched_polizas(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [
            PolizaContable(id="POL001", fecha="2024-01-15", monto=10000.0),
            PolizaContable(id="POL002", fecha="2024-01-16", monto=5000.0),
        ]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        assert len(results["unmatched_polizas"]) == 1
        assert results["unmatched_polizas"][0].id == "POL002"

    def test_reconciliation_with_cfdi(self):
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
        results = service.reconcile_bank_statement(txns, cfdi_list=cfdi)
        assert len(results["matches"]) == 1
        assert results["matches"][0].status == MatchStatus.MATCHED


# ===========================================================================
# 5. SERVICE TESTS — DISCREPANCY DETECTION
# ===========================================================================

class TestDiscrepancies:
    """Tests for discrepancy detection."""

    def test_no_discrepancy_exact_match(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        matches = service.match_transactions_to_polizas(txns, polizas)
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        # No discrepancy for exact match with same amounts
        monto_discs = [d for d in discrepancies if d.type == DiscrepancyType.MONTO]
        assert len(monto_discs) == 0

    def test_discrepancy_detected_above_threshold(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10500.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        # Manually create a match to test discrepancy detection
        # (amounts differ by 5% which exceeds amount_tolerance, so auto-match won't happen)
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            match_type=MatchType.EXACT,
            confidence_score=0.8,
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        # When bank_amount > poliza_amount, type is SOBRANTE
        sobrante_discs = [d for d in discrepancies if d.type == DiscrepancyType.SOBRANTE]
        assert len(sobrante_discs) == 1
        assert sobrante_discs[0].variance == 5.0

    def test_no_discrepancy_below_threshold(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10050.0,  # 0.5% over
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        matches = service.match_transactions_to_polizas(txns, polizas)
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        monto_discs = [d for d in discrepancies if d.type == DiscrepancyType.MONTO]
        assert len(monto_discs) == 0

    def test_discrepancy_sobrante(self):
        """Bank has more than poliza — sobrante."""
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10500.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        matches = service.match_transactions_to_polizas(txns, polizas)
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        sobrante = [d for d in discrepancies if d.type == DiscrepancyType.SOBRANTE]
        assert len(sobrante) == 1

    def test_discrepancy_faltante(self):
        """Bank has less than poliza — faltante."""
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=9500.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        # Manually create a match (5% difference exceeds amount_tolerance)
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            match_type=MatchType.EXACT,
            confidence_score=0.8,
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        faltante = [d for d in discrepancies if d.type == DiscrepancyType.FALTANTE]
        assert len(faltante) == 1

    def test_duplicate_transactions_detected(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
        ]
        discrepancies = service.identify_discrepancies([], txns, [])
        duplicados = [d for d in discrepancies if d.type == DiscrepancyType.DUPLICADO]
        assert len(duplicados) == 1
        assert "TXN001" in duplicados[0].details

    def test_unmatched_bank_transactions_detected(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=5000.0,
                            type=TransactionType.EGRESO),
        ]
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches, txns, [])
        faltantes = [d for d in discrepancies if d.type == DiscrepancyType.FALTANTE]
        assert len(faltantes) == 1
        assert faltantes[0].bank_transaction_id == "TXN002"

    def test_unmatched_polizas_detected(self):
        service = ConciliationService()
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [
            PolizaContable(id="POL001", fecha="2024-01-15", monto=10000.0),
            PolizaContable(id="POL002", fecha="2024-01-16", monto=5000.0),
        ]
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        sobrantes = [d for d in discrepancies if d.type == DiscrepancyType.SOBRANTE]
        assert len(sobrantes) == 1
        assert sobrantes[0].poliza_id == "POL002"

    def test_date_discrepancy_detected(self):
        service = ConciliationService(date_tolerance_days=2)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10000.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-25", monto=10000.0,
        )]
        matches = service.match_transactions_to_polizas(txns, polizas)
        discrepancies = service.identify_discrepancies(matches, txns, polizas)
        fecha_discs = [d for d in discrepancies if d.type == DiscrepancyType.FECHA]
        assert len(fecha_discs) == 1
        assert fecha_discs[0].date_diff_days == 10

    def test_no_discrepancy_without_data(self):
        service = ConciliationService()
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            status=MatchStatus.MATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches)
        assert len(discrepancies) == 0

    def test_discrepancy_skip_unmatched(self):
        service = ConciliationService()
        matches = [MatchResult(
            bank_transaction_id="TXN001",
            poliza_id=None,
            status=MatchStatus.UNMATCHED,
        )]
        discrepancies = service.identify_discrepancies(matches)
        monto_discs = [d for d in discrepancies if d.type == DiscrepancyType.MONTO]
        assert len(monto_discs) == 0


# ===========================================================================
# 6. SERVICE TESTS — ADJUSTMENT PROPOSALS
# ===========================================================================

class TestAdjustments:
    """Tests for adjustment proposal generation."""

    def test_propose_correction_for_monto_discrepancy(self):
        disc = Discrepancy(
            id="DISC001",
            type=DiscrepancyType.MONTO,
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            bank_amount=10500.0,
            poliza_amount=10000.0,
            variance=5.0,
            variance_amount=500.0,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "correction"
        assert adjustments[0].journal_entry is not None
        assert adjustments[0].journal_entry["monto"] == 500.0

    def test_propose_manual_entry_for_sobrante_without_poliza(self):
        disc = Discrepancy(
            id="DISC002",
            type=DiscrepancyType.SOBRANTE,
            bank_transaction_id="TXN001",
            bank_amount=5000.0,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "manual_entry"
        assert adjustments[0].journal_entry is not None

    def test_propose_investigation_for_faltante(self):
        disc = Discrepancy(
            id="DISC003",
            type=DiscrepancyType.FALTANTE,
            bank_transaction_id="TXN001",
            bank_amount=3000.0,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "investigation"

    def test_propose_void_for_duplicate(self):
        disc = Discrepancy(
            id="DISC004",
            type=DiscrepancyType.DUPLICADO,
            bank_transaction_id="TXN001",
            bank_amount=10000.0,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "void"
        assert adjustments[0].journal_entry is not None

    def test_propose_review_for_fecha_discrepancy(self):
        disc = Discrepancy(
            id="DISC005",
            type=DiscrepancyType.FECHA,
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            date_diff_days=10,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "review"

    def test_propose_reclassify_for_sobrante_with_poliza(self):
        disc = Discrepancy(
            id="DISC006",
            type=DiscrepancyType.SOBRANTE,
            bank_transaction_id="TXN001",
            poliza_id="POL001",
            bank_amount=10500.0,
            poliza_amount=10000.0,
            variance=5.0,
            variance_amount=500.0,
        )
        service = ConciliationService()
        adjustments = service.propose_adjustments([disc])
        assert len(adjustments) == 1
        assert adjustments[0].adjustment_type == "reclassify"

    def test_multiple_adjustments(self):
        discs = [
            Discrepancy(id="DISC001", type=DiscrepancyType.MONTO,
                        bank_transaction_id="TXN001", poliza_id="POL001",
                        bank_amount=10500.0, poliza_amount=10000.0),
            Discrepancy(id="DISC002", type=DiscrepancyType.FALTANTE,
                        bank_transaction_id="TXN002", bank_amount=5000.0),
        ]
        service = ConciliationService()
        adjustments = service.propose_adjustments(discs)
        assert len(adjustments) == 2

    def test_adjustment_all_proposed_status(self):
        discs = [
            Discrepancy(id="DISC001", type=DiscrepancyType.MONTO,
                        bank_transaction_id="TXN001", poliza_id="POL001",
                        bank_amount=10500.0, poliza_amount=10000.0),
        ]
        service = ConciliationService()
        adjustments = service.propose_adjustments(discs)
        assert all(a.status == AdjustmentStatus.PROPOSED for a in adjustments)


# ===========================================================================
# 7. SERVICE TESTS — REPORT GENERATION
# ===========================================================================

class TestReportGeneration:
    """Tests for reconciliation report generation."""

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

    def test_reconciliation_report_comprehensive(self):
        service = ConciliationService()
        txns = [
            BankTransaction(id="TXN001", date="2024-01-15", amount=10000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="TXN002", date="2024-01-16", amount=5000.0,
                            type=TransactionType.EGRESO),
        ]
        polizas = [
            PolizaContable(id="POL001", fecha="2024-01-15", monto=10000.0),
            PolizaContable(id="POL002", fecha="2024-01-17", monto=5000.0),
        ]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        report = service.generate_reconciliation_report(results, period="2024-01")
        assert report.period == "2024-01"
        assert report.total_transactions > 0
        assert report.total_polizas > 0

    def test_report_with_adjustments(self):
        service = ConciliationService(discrepancy_threshold=0.02)
        txns = [BankTransaction(
            id="TXN001", date="2024-01-15", amount=10500.0,
            type=TransactionType.INGRESO,
        )]
        polizas = [PolizaContable(
            id="POL001", fecha="2024-01-15", monto=10000.0,
        )]
        results = service.reconcile_bank_statement(txns, polizas=polizas)
        report = service.generate_reconciliation_report(results, period="2024-01")
        assert report.adjustments_proposed > 0


# ===========================================================================
# 8. SERVICE TESTS — CSV EXPORT
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
        assert len(rows) >= 4


# ===========================================================================
# 9. SERVICE TESTS — EDGE CASES
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

    def test_large_dataset_performance(self):
        """Test with a larger dataset to ensure performance is acceptable."""
        service = ConciliationService()
        txns = [
            BankTransaction(
                id=f"TXN{i:04d}", date="2024-01-15", amount=float(i * 1000),
                type=TransactionType.INGRESO,
            )
            for i in range(1, 51)
        ]
        polizas = [
            PolizaContable(
                id=f"POL{i:04d}", fecha="2024-01-15", monto=float(i * 1000),
            )
            for i in range(1, 51)
        ]
        results = service.match_transactions_to_polizas(txns, polizas)
        assert len(results) == 50
        matched = sum(1 for r in results if r.status == MatchStatus.MATCHED)
        assert matched == 50


# ===========================================================================
# 10. VALIDATOR TESTS
# ===========================================================================

class TestValidators:
    """Tests for bank statement, CFDI, and poliza validators."""

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

    def test_valid_poliza(self):
        polizas = [_poliza(), _poliza(id="POL002", monto=5000.0)]
        is_valid, errors = validate_polizas_contables(polizas)
        assert is_valid is True
        assert len(errors) == 0

    def test_empty_polizas(self):
        is_valid, errors = validate_polizas_contables([])
        assert is_valid is False
        assert "vacía" in errors[0]

    def test_poliza_missing_fields(self):
        polizas = [{"id": "POL001"}]  # Missing fecha, monto
        is_valid, errors = validate_polizas_contables(polizas)
        assert is_valid is False

    def test_poliza_duplicate_ids(self):
        polizas = [_poliza(id="POL001"), _poliza(id="POL001")]
        is_valid, errors = validate_polizas_contables(polizas)
        assert is_valid is False
        assert any("duplicado" in e for e in errors)

    def test_poliza_zero_monto(self):
        polizas = [_poliza(monto=0)]
        is_valid, errors = validate_polizas_contables(polizas)
        assert is_valid is False
        assert any("cero" in e for e in errors)


class TestAmountValidation:
    """Tests for amount matching validation."""

    def test_exact_amount_match(self):
        matches, variance = validate_amount_match(10000.0, 10000.0)
        assert matches is True
        assert variance == 0.0

    def test_amount_within_tolerance(self):
        matches, variance = validate_amount_match(10050.0, 10000.0, tolerance=0.01)
        assert matches is True
        assert variance < 0.01

    def test_amount_outside_tolerance(self):
        matches, variance = validate_amount_match(10500.0, 10000.0, tolerance=0.01)
        assert matches is False
        assert variance > 0.01

    def test_zero_reference_amount(self):
        matches, variance = validate_amount_match(100.0, 0.0)
        assert matches is False
        assert variance == 1.0

    def test_both_zero(self):
        matches, variance = validate_amount_match(0.0, 0.0)
        assert matches is True
        assert variance == 0.0


class TestDateRangeValidation:
    """Tests for date range validation."""

    def test_valid_range(self):
        is_valid, errors = validate_date_range("2024-01-01", "2024-01-31")
        assert is_valid is True
        assert len(errors) == 0

    def test_start_after_end(self):
        is_valid, errors = validate_date_range("2024-01-31", "2024-01-01")
        assert is_valid is False
        assert any("posterior" in e for e in errors)

    def test_invalid_format(self):
        is_valid, errors = validate_date_range("15-01-2024", "2024-01-31")
        assert is_valid is False

    def test_same_date(self):
        is_valid, errors = validate_date_range("2024-01-15", "2024-01-15")
        assert is_valid is True


class TestReconciliationDataValidation:
    """Tests for batch reconciliation data validation."""

    def test_valid_data(self):
        bank = [_bank_txn(id="TXN001")]
        polizas = [_poliza(id="POL001")]
        is_valid, errors = validate_reconciliation_data(bank, polizas=polizas)
        assert is_valid is True

    def test_invalid_bank_data(self):
        bank = [{"id": "X"}]
        polizas = [_poliza()]
        is_valid, errors = validate_reconciliation_data(bank, polizas=polizas)
        assert is_valid is False
        assert any("[Bancario]" in e for e in errors)

    def test_date_range_no_overlap(self):
        bank = [_bank_txn(date="2024-01-15")]
        polizas = [_poliza(fecha="2024-06-15")]
        is_valid, errors = validate_reconciliation_data(bank, polizas=polizas)
        # Should have a warning about non-overlapping date ranges
        assert any("[Rango]" in e for e in errors)


# ===========================================================================
# 11. ROUTE TESTS
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
        # CFDI matches are in "cfdi_matches" field
        assert len(data["cfdi_matches"]) == 1

    def test_match_endpoint_with_polizas(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10000.0)],
            "polizas": [_poliza(id="POL001", monto=10000.0)],
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
        assert len(data["matches"]) == 1  # poliza matches

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

    def test_reconcile_endpoint_success(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10000.0)],
            "polizas": [_poliza(id="POL001", monto=10000.0)],
            "tolerance_days": 3,
        }
        resp = tc.post(
            "/api/v1/conciliacion/reconcile",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "report" in data
        assert "summary" in data

    def test_reconcile_endpoint_with_discrepancy(self, client):
        tc, db = client
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10500.0)],
            "polizas": [_poliza(id="POL001", monto=10000.0)],
            "tolerance_days": 3,
        }
        resp = tc.post(
            "/api/v1/conciliacion/reconcile",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["summary"]["discrepancies"] > 0
        assert data["summary"]["adjustments_proposed"] > 0

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

    def test_discrepancies_endpoint_with_filter(self, client):
        tc, db = client
        resp = tc.get(
            "/api/v1/conciliacion/discrepancies?discrepancy_type=monto",
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert "discrepancies" in resp.json()

    def test_adjustments_endpoint(self, client):
        tc, db = client
        resp = tc.get("/api/v1/conciliacion/adjustments", headers=_auth())
        assert resp.status_code == 200
        assert "adjustments" in resp.json()

    def test_upload_endpoint(self, client):
        tc, db = client
        csv_content = "id,date,description,amount,type,reference,bank_account\n"
        csv_content += "TXN001,2024-01-15,Pago factura,10000.00,INGRESO,REF001,1234\n"
        resp = tc.post(
            "/api/v1/conciliacion/upload",
            files={"file": ("statement.csv", csv_content.encode(), "text/csv")},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["transaction_count"] == 1

    def test_upload_endpoint_empty_file(self, client):
        tc, db = client
        resp = tc.post(
            "/api/v1/conciliacion/upload",
            files={"file": ("empty.csv", b"", "text/csv")},
            headers=_auth(),
        )
        assert resp.status_code == 400

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
        # CFDI matches are in "cfdi_matches" field
        matched = sum(1 for m in data["cfdi_matches"] if m["status"] == "MATCHED")
        assert matched == 2

    def test_apply_adjustments_endpoint(self, client):
        """Test the apply adjustments endpoint."""
        tc, db = client
        # First run a reconcile to create adjustments
        payload = {
            "bank_transactions": [_bank_txn(id="TXN001", amount=10500.0)],
            "polizas": [_poliza(id="POL001", monto=10000.0)],
        }
        resp = tc.post(
            "/api/v1/conciliacion/reconcile",
            json=payload,
            headers=_auth(),
        )
        assert resp.status_code == 200

        # Now get adjustments
        resp = tc.get("/api/v1/conciliacion/adjustments", headers=_auth())
        assert resp.status_code == 200
        adjustments = resp.json()["adjustments"]
        if adjustments:
            # Apply the first adjustment
            adj_id = adjustments[0]["id"]
            apply_resp = tc.post(
                "/api/v1/conciliacion/apply",
                json={"adjustment_ids": [adj_id], "applied_by": "test_user"},
                headers=_auth(),
            )
            assert apply_resp.status_code == 200
            assert apply_resp.json()["total_applied"] == 1

    def test_apply_adjustments_not_found(self, client):
        """Test applying non-existent adjustments."""
        tc, db = client
        resp = tc.post(
            "/api/v1/conciliacion/apply",
            json={"adjustment_ids": ["NONEXISTENT"], "applied_by": "test"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["not_found"]) == 1
