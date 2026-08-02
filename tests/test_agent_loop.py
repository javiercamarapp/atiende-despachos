# -*- coding: utf-8 -*-
"""test_agent_loop.py — Tests for the AgentLoop main flow.

Covers:
  - classify_invoice with valid data → auto_processed
  - LLM timeout → fail-closed (escalate, no auto-register)
  - Low confidence → hold (no ERP registration)
  - Anomaly detection → alerta → needs_review
"""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

os.environ.setdefault("B2B_ENV", "test")
os.environ.setdefault("B2B_RATE_LIMIT", "off")


# ---------------------------------------------------------------------------
# Helpers: build a minimal AgentLoop with mocked dependencies
# ---------------------------------------------------------------------------

def _make_loop(
    classify_result=None,
    anomaly_result=None,
    classify_timeout=False,
    anomaly_timeout=False,
    policy="hold",
    confidence_threshold=0.7,
    validate_ok=True,
):
    """Build an AgentLoop with all external deps mocked."""
    from b2b_ai.agent.loop import AgentLoop

    # Database mock
    db = MagicMock()
    db.insert_invoice.return_value = (42, True)  # inv_id, inserted
    db.create_review.return_value = 99
    db.list_tenants.return_value = [{"id": 1, "name": "Test"}]
    db.create_tenant.return_value = 1

    # TenantManager mock
    tenants = MagicMock()
    tenants.get_tenant.return_value = {"id": 1, "name": "Test"}
    tenants.get_config.return_value = {
        "policy_human_review": policy,
        "notif_channel": "email",
        "notif_recipient": "test@test.com",
        "confidence_threshold": confidence_threshold,
    }
    tenants.erp_factory.return_value = MagicMock()

    # LLM mock
    llm = MagicMock()
    if classify_timeout:
        from b2b_ai.services.timeouts import ServiceTimeoutError
        llm.classify_invoice.side_effect = ServiceTimeoutError("LLM timeout")
    elif classify_result is not None:
        llm.classify_invoice.return_value = classify_result
    else:
        llm.classify_invoice.return_value = {
            "categoria": "papeleria",
            "confianza": 0.92,
            "razon": "Oficina",
            "source": "rules",
            "requires_human_review": False,
        }

    if anomaly_timeout:
        from b2b_ai.services.timeouts import ServiceTimeoutError
        llm.detect_anomaly.side_effect = ServiceTimeoutError("LLM timeout")
    elif anomaly_result is not None:
        llm.detect_anomaly.return_value = anomaly_result
    else:
        llm.detect_anomaly.return_value = {
            "nivel": "normal",
            "anomalias": [],
            "source": "rules",
        }

    # Tool mocks — patch call_tool to control parse/validate/register
    # parse_cfdi returns a valid CFDI dict
    parsed = {
        "folio_fiscal": "TEST-UUID-001",
        "emisor_rfc": "XAXX010101000",
        "emisor_nombre": "Demo SA",
        "receptor_rfc": "TEST220101CD2",
        "total": 15000.0,
        "subtotal": 12931.03,
        "iva": 2068.97,
        "tipo": "I",
        "fecha": "2026-01-15",
        "conceptos": [{"descripcion": "Papeleria"}],
    }
    validation = {"ok": True, "requires_human_review": False, "issues": []}

    if not validate_ok:
        validation = {"ok": False, "requires_human_review": True,
                      "issues": [{"mensaje": "CFDI inválido"}]}

    def fake_call_tool(name, **kwargs):
        if name == "parse_cfdi":
            return parsed
        elif name == "validate_cfdi":
            return validation
        elif name == "register_erp":
            return {"ok": True, "erp_reference": "ERP-001"}
        elif name == "send_notification":
            return {"status": "sent"}
        raise ValueError(f"Unexpected tool: {name}")

    # Email mock
    email = MagicMock()

    loop = AgentLoop.__new__(AgentLoop)
    loop.db = db
    loop.logger = MagicMock()
    loop.tenants = tenants
    loop.llm = llm
    loop.erp = None
    loop.email = email
    loop.notify = False  # disable notifications in tests
    loop._cu_driver = None

    return loop, parsed, validation, fake_call_tool


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentLoopClassifyInvoice:
    """Test agent loop with valid classification → auto_processed."""

    def test_auto_processed_with_valid_data(self):
        """Happy path: high confidence, no anomaly → auto_processed + ERP registered."""
        loop, parsed, validation, fake_call_tool = _make_loop()

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "auto_processed"
        assert result["invoice_id"] == 42
        assert result["insertado"] is True
        assert result["erp"] is not None
        assert result["erp"]["ok"] is True
        assert result["review_id"] is None
        # Verify steps passed
        pasos = {p["paso"]: p["ok"] for p in result["pasos"]}
        assert pasos["recibir"] is True
        assert pasos["validar"] is True
        assert pasos["clasificar"] is True
        assert pasos["anomalia"] is True
        assert pasos["decidir"] is True

    def test_classification_data_in_result(self):
        """Verify classification and anomaly data are in the result."""
        loop, parsed, validation, fake_call_tool = _make_loop()

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["clasificacion"]["categoria"] == "papeleria"
        assert result["clasificacion"]["confianza"] == 0.92
        assert result["anomalia"]["nivel"] == "normal"


class TestAgentLoopLLMTimeout:
    """Test fail-closed behavior when LLM times out."""

    def test_classify_timeout_fails_closed(self):
        """LLM classify timeout → desconocido, 0.0 confidence → hold."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            classify_timeout=True,
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        # Should be held for review due to 0.0 confidence < floor (0.50)
        assert result["decision"] == "needs_review"
        # Should NOT have registered in ERP
        assert result["erp"] is None
        # Should have escalated
        assert result["review_id"] is not None

    def test_anomaly_timeout_fails_closed(self):
        """LLM anomaly timeout → fail-closed: 'alerta' → needs_review."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            anomaly_timeout=True,
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "needs_review"
        assert result["anomalia"]["nivel"] == "alerta"
        assert result["erp"] is None
        assert result["review_id"] is not None

    def test_both_timeouts_fail_closed(self):
        """Both LLM calls timeout → still fails closed, no crash."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            classify_timeout=True,
            anomaly_timeout=True,
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "needs_review"
        assert result["erp"] is None


class TestAgentLoopLowConfidence:
    """Test that low confidence triggers hold (no ERP registration)."""

    def test_low_confidence_below_threshold(self):
        """Confidence 0.4 < threshold 0.7 → hold."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            classify_result={
                "categoria": "otros",
                "confianza": 0.4,
                "razon": "Uncertain",
                "source": "rules",
                "requires_human_review": True,
            },
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "needs_review"
        assert result["erp"] is None
        assert result["review_id"] is not None

    def test_low_confidence_below_floor(self):
        """Confidence 0.3 < floor 0.50 → ALWAYS hold, regardless of policy."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            classify_result={
                "categoria": "otros",
                "confianza": 0.3,
                "razon": "Low",
                "source": "rules",
                "requires_human_review": True,
            },
            policy="auto_register",  # even with auto_register, floor holds
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "needs_review"
        assert result["erp"] is None

    def test_auto_register_policy_registers_when_not_low_confidence(self):
        """With policy=auto_register and high anomaly (not low confidence),
        it should register in ERP even though there's a review needed."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            classify_result={
                "categoria": "papeleria",
                "confianza": 0.85,
                "razon": "High",
                "source": "rules",
                "requires_human_review": False,
            },
            anomaly_result={
                "nivel": "alerta",
                "anomalias": ["Monto inusual"],
                "source": "rules",
            },
            policy="auto_register",
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        # auto_register + anomaly alert → register with review
        assert result["decision"] == "needs_review"
        assert result["erp"] is not None  # ERP registered despite review


class TestAgentLoopAnomalyDetection:
    """Test anomaly detection behavior in the agent loop."""

    def test_anomaly_alerta_triggers_review(self):
        """Anomaly alerta → needs_review."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            anomaly_result={
                "nivel": "alerta",
                "anomalias": ["Duplicado detectado"],
                "source": "llm",
            },
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "needs_review"
        assert result["review_id"] is not None
        assert result["anomalia"]["nivel"] == "alerta"

    def test_anomaly_normal_allows_auto_process(self):
        """No anomaly → auto_processed with high confidence."""
        loop, parsed, validation, fake_call_tool = _make_loop(
            anomaly_result={
                "nivel": "normal",
                "anomalias": [],
                "source": "rules",
            },
        )

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "auto_processed"

    def test_parse_failure_escalates(self):
        """parse_cfdi raises → parse_failed, no ERP, escalation."""
        loop, _, _, _ = _make_loop()

        def fail_parse(name, **kwargs):
            if name == "parse_cfdi":
                raise ValueError("XML malformed")
            return MagicMock()

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fail_parse):
            result = loop.process("/tmp/bad.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "parse_failed"
        assert result["erp"] is None
        assert result["review_id"] is not None

    def test_validation_failure_escalates(self):
        """Validation failure → invalid, no ERP, escalation."""
        loop, parsed, validation, fake_call_tool = _make_loop(validate_ok=False)

        with patch("b2b_ai.agent.loop.call_tool", side_effect=fake_call_tool):
            result = loop.process("/tmp/fake.xml", tenant_id=1, send_notifications=False)

        assert result["decision"] == "invalid"
        assert result["erp"] is None
        assert result["review_id"] is not None
