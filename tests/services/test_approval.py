# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/approval.py — approval gate."""
import pytest
from b2b_ai.services.approval import ApprovalManager, _is_payment, DEFAULT_AUTO_THRESHOLD


class TestIsPayment:
    def test_tipo_p(self):
        assert _is_payment({"tipo": "P"}) is True

    def test_tipo_pago(self):
        assert _is_payment({"tipo": "PAGO"}) is True

    def test_complemento_in_concepto(self):
        inv = {"conceptos": [{"descripcion": "Complemento de pago"}]}
        assert _is_payment(inv) is True

    def test_pago_parcialidad(self):
        inv = {"conceptos": [{"descripcion": "Pago parcialidad"}]}
        assert _is_payment(inv) is True

    def test_normal_invoice(self):
        assert _is_payment({"tipo": "I"}) is False

    def test_none_tipo(self):
        assert _is_payment({}) is False


class TestApprovalManager:
    def setup_method(self):
        self.mgr = ApprovalManager()

    def test_auto_approve_below_threshold(self):
        inv = {"total": "10000.00", "folio_fiscal": "F1"}
        r = self.mgr.evaluate(inv)
        assert r["decision"] == "auto_approved"
        assert r["requires_approval"] is False

    def test_requires_approval_above_threshold(self):
        inv = {"total": "100000.00", "folio_fiscal": "F1"}
        r = self.mgr.evaluate(inv)
        assert r["decision"] == "requires_approval"
        assert r["requires_approval"] is True
        assert r["requires_efirma"] is True

    def test_payment_always_requires_approval(self):
        inv = {"total": "100.00", "tipo": "P", "folio_fiscal": "F1"}
        r = self.mgr.evaluate(inv)
        assert r["decision"] == "requires_approval"
        assert r["requires_efirma"] is True

    def test_custom_threshold(self):
        mgr = ApprovalManager(auto_threshold=10000)
        inv = {"total": "15000.00"}
        r = mgr.evaluate(inv)
        assert r["decision"] == "requires_approval"
        assert r["threshold"] == 10000.0

    def test_efirma_notice(self):
        inv = {"total": "100000.00"}
        r = self.mgr.evaluate(inv)
        assert "e.firma" in r["efirma_notice"]


class TestApprove:
    def test_approve_with_efirma(self):
        mgr = ApprovalManager()
        inv = {"total": "100000.00", "folio_fiscal": "F1"}
        r = mgr.approve(inv, "Juan", efirma_ok=True)
        assert r["ok"] is True
        assert r["status"] == "approved"

    def test_approve_without_efirma_blocked(self):
        mgr = ApprovalManager()
        inv = {"total": "100000.00", "folio_fiscal": "F1"}
        r = mgr.approve(inv, "Juan", efirma_ok=False)
        assert r["ok"] is False
        assert r["status"] == "blocked_efirma"

    def test_approve_auto_approved不需要_efirma(self):
        mgr = ApprovalManager()
        inv = {"total": "10000.00", "folio_fiscal": "F1"}
        r = mgr.approve(inv, "Juan", efirma_ok=False)
        assert r["ok"] is True


class TestReject:
    def test_reject(self):
        mgr = ApprovalManager()
        inv = {"total": "100000.00", "folio_fiscal": "F1"}
        r = mgr.reject(inv, "Juan", notes="Monto excesivo")
        assert r["ok"] is True
        assert r["status"] == "rejected"


class TestRecordDecision:
    def test_record(self):
        mgr = ApprovalManager()
        inv = {"total": "10000.00", "folio_fiscal": "F1"}
        rid = mgr.record_decision(inv, "approved", "Juan")
        assert rid == 1
        assert len(mgr.decisions) == 1

    def test_multiple_records(self):
        mgr = ApprovalManager()
        inv = {"total": "10000.00"}
        mgr.record_decision(inv, "approved", "Juan")
        mgr.record_decision(inv, "rejected", "Pedro")
        assert len(mgr.decisions) == 2
        assert mgr.decisions[1]["id"] == 2


class TestCanRegister:
    def test_auto_approved(self):
        assert ApprovalManager().can_register({}, "auto_approved") is True

    def test_approved(self):
        assert ApprovalManager().can_register({}, "approved") is True

    def test_requires_approval(self):
        assert ApprovalManager().can_register({}, "requires_approval") is False

    def test_rejected(self):
        assert ApprovalManager().can_register({}, "rejected") is False

    def test_blocked_efirma(self):
        assert ApprovalManager().can_register({}, "blocked_efirma") is False
