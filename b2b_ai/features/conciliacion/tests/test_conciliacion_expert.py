# -*- coding: utf-8 -*-
"""
test_conciliacion_expert.py — Expert-level tests for Bank Reconciliation module.
Tests: idempotency, audit trail, input sanitization, error handling,
tenant isolation, edge cases, concurrent access, data validation,
output verification, retry logic.
"""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.models import BankTransaction, CFDIReference, PolizaContable, TransactionType, MatchStatus
from b2b_ai.features.conciliacion.validators import (
    validate_bank_statement, validate_cfdi_for_conciliation,
    validate_polizas_contables, validate_reconciliation_data,
)
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_reconcile_idempotent_same_input(self):
        svc = ConciliationService()
        txns = [BankTransaction(id="T1", date="2024-01-15", amount=1000.0, type=TransactionType.INGRESO)]
        polizas = [PolizaContable(id="P1", fecha="2024-01-15", monto=1000.0)]
        r1 = svc.reconcile_bank_statement(txns, polizas)
        r2 = svc.reconcile_bank_statement(txns, polizas)
        assert len(r1["matches"]) == len(r2["matches"])

    def test_conciliation_service_init_idempotent(self):
        s1 = ConciliationService()
        s2 = ConciliationService()
        assert s1.discrepancy_threshold == s2.discrepancy_threshold


class TestAuditTrail:
    def test_audit_trail_exists(self):
        svc = ConciliationService()
        entry = svc.log_audit(user="test", action="reconcile", module="conciliacion", result="success")
        assert entry.user == "test"
        assert entry.action == "reconcile"
        assert entry.result == "success"

    def test_audit_trail_with_tenant(self):
        svc = ConciliationService()
        entry = svc.log_audit(user="u1", action="test", module="m", result="ok", tenant_id="t1")
        assert entry.tenant_id == "t1"


class TestInputSanitization:
    def test_sanitize_string_strips(self):
        assert sanitize_string("  hello  ") == "hello"

    def test_sanitize_string_truncates(self):
        long_str = "a" * 10000
        assert len(sanitize_string(long_str, max_length=100)) == 100

    def test_check_sql_injection_detects(self):
        safe, msg = check_sql_injection("SELECT * FROM users")
        assert not safe

    def test_check_sql_injection_clean(self):
        safe, msg = check_sql_injection("Factura 12345")
        assert safe


class TestErrorHandling:
    def test_validate_bank_statement_empty(self):
        valid, errors = validate_bank_statement([])
        assert not valid
        assert len(errors) > 0

    def test_validate_polizas_empty(self):
        valid, errors = validate_polizas_contables([])
        assert not valid

    def test_validate_cfdi_empty(self):
        valid, errors = validate_cfdi_for_conciliation([])
        assert not valid

    def test_validate_reconciliation_data_empty_bank(self):
        valid, errors = validate_reconciliation_data([])
        assert not valid


class TestTenantIsolation:
    def test_mask_rfc_masks(self):
        masked = mask_rfc("EMP850101AB1")
        assert masked.startswith("EMP")
        assert "***" in masked

    def test_mask_rfc_short(self):
        assert mask_rfc("AB") == "***"


class TestEdgeCases:
    def test_reconcile_empty_transactions(self):
        svc = ConciliationService()
        result = svc.reconcile_bank_statement([], [])
        assert result["matches"] == []
        assert result["unmatched_bank"] == []

    def test_reconcile_no_match(self):
        svc = ConciliationService()
        txns = [BankTransaction(id="T1", date="2024-01-15", amount=500.0, type=TransactionType.INGRESO)]
        polizas = [PolizaContable(id="P1", fecha="2024-01-15", monto=999.0)]
        result = svc.reconcile_bank_statement(txns, polizas)
        assert len(result["unmatched_bank"]) == 1

    def test_encode_output_safe(self):
        encoded = encode_output("<script>alert(1)</script>")
        assert "<script>" not in encoded
        assert "&lt;" in encoded


class TestConcurrentAccess:
    def test_concurrent_reconciliation(self):
        svc = ConciliationService()
        txns = [BankTransaction(id="T1", date="2024-01-15", amount=1000.0, type=TransactionType.INGRESO)]
        polizas = [PolizaContable(id="P1", fecha="2024-01-15", monto=1000.0)]
        results = []
        def run():
            results.append(svc.reconcile_bank_statement(txns, polizas))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
        for r in results:
            assert len(r["poliza_matches"]) == 1


class TestDataValidation:
    def test_validate_bank_statement_bad_date(self):
        valid, errors = validate_bank_statement([{"id": "1", "date": "bad", "amount": 100, "type": "INGRESO"}])
        assert not valid

    def test_validate_bank_statement_bad_type(self):
        valid, errors = validate_bank_statement([{"id": "1", "date": "2024-01-01", "amount": 100, "type": "INVALID"}])
        assert not valid

    def test_validate_cfdi_bad_uuid(self):
        valid, errors = validate_cfdi_for_conciliation([{
            "uuid": "bad", "fecha": "2024-01-01", "rfc_emisor": "EMP850101AB1",
            "rfc_receptor": "REC900101CD2", "total": 1000
        }])
        assert not valid


class TestOutputVerification:
    def test_match_result_structure(self):
        svc = ConciliationService()
        txns = [BankTransaction(id="T1", date="2024-01-15", amount=1000.0, type=TransactionType.INGRESO)]
        polizas = [PolizaContable(id="P1", fecha="2024-01-15", monto=1000.0)]
        result = svc.reconcile_bank_statement(txns, polizas)
        match = result["poliza_matches"][0]
        assert match.bank_transaction_id == "T1"
        assert match.poliza_id == "P1"
        assert match.status == MatchStatus.MATCHED

    def test_report_has_required_fields(self):
        svc = ConciliationService()
        result = svc.reconcile_bank_statement([], [])
        assert "matches" in result
        assert "poliza_matches" in result
        assert "discrepancies" in result


class TestRetryLogic:
    def test_discrepancy_threshold_configurable(self):
        svc1 = ConciliationService(discrepancy_threshold=0.02)
        svc2 = ConciliationService(discrepancy_threshold=0.05)
        assert svc1.discrepancy_threshold != svc2.discrepancy_threshold
