# -*- coding: utf-8 -*-
"""
test_webhook_receiver.py — Tests for the Conekta webhook receiver.

Coverage:
    - Signature verification (valid, invalid, missing, malformed)
    - Event parsing (all 4 supported + unsupported)
    - DB updates for invoice and subscription events
    - Logging in audit_log
    - Full HTTP endpoint via TestClient
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.billing.webhook_receiver import (
    ConektaEventType,
    ConektaWebhookReceiver,
    SUPPORTED_EVENTS,
    build_webhook_receiver_router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "test_secret_key_12345"


class FakeDB:
    """Fake DB para tests sin SQLite real."""

    def __init__(self):
        self.conn = MagicMock()
        # Make conn.execute() return a mock cursor with rowcount=1
        self._mock_cursor = MagicMock()
        self._mock_cursor.rowcount = 1
        self.conn.execute.return_value = self._mock_cursor
        self._audit_log: List[Dict[str, Any]] = []
        self._invoice_updates: List[Dict[str, Any]] = []
        self._sub_updates: List[Dict[str, Any]] = []

    def log_call(
        self, tool_name, action, entity="", entity_id="",
        payload=None, status="ok", tenant_id=None,
    ):
        self._audit_log.append({
            "tool_name": tool_name,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "payload": payload,
            "status": status,
            "tenant_id": tenant_id,
        })
        return len(self._audit_log)

    def mark_billing_invoice_paid_by_ref(
        self, provider_invoice_id, provider, paid_at=None,
    ):
        self._invoice_updates.append({
            "provider_invoice_id": provider_invoice_id,
            "provider": provider,
            "paid_at": paid_at,
            "action": "mark_paid",
        })
        return True


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def receiver(db):
    return ConektaWebhookReceiver(db, webhook_secret=WEBHOOK_SECRET)


@pytest.fixture
def app(db):
    """App FastAPI de prueba con el webhook endpoint."""
    app = FastAPI()
    app.include_router(
        build_webhook_receiver_router(db, webhook_secret=WEBHOOK_SECRET)
    )
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(payload_body: str, secret: str = WEBHOOK_SECRET) -> str:
    """Genera una firma HMAC válida para un body dado."""
    timestamp = str(int(datetime.now().timestamp()))
    signed_content = f"{timestamp}{payload_body}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac_sha256={signature},t={timestamp}"


def _make_payment_paid_payload(
    invoice_id: str = "inv_123",
    customer_id: str = "cus_456",
    amount: int = 100000,
) -> Dict[str, Any]:
    return {
        "type": "payment.paid",
        "data": {
            "object": {
                "id": invoice_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "amount": amount,
                "status": "paid",
            }
        },
    }


def _make_payment_failed_payload(
    invoice_id: str = "inv_789",
    customer_id: str = "cus_456",
    amount: int = 50000,
) -> Dict[str, Any]:
    return {
        "type": "payment.failed",
        "data": {
            "object": {
                "id": invoice_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "amount": amount,
                "status": "failed",
            }
        },
    }


def _make_subscription_created_payload(
    subscription_id: str = "sub_001",
    customer_id: str = "cus_456",
) -> Dict[str, Any]:
    return {
        "type": "subscription.created",
        "data": {
            "object": {
                "id": subscription_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "status": "active",
            }
        },
    }


def _make_subscription_canceled_payload(
    subscription_id: str = "sub_002",
    customer_id: str = "cus_456",
) -> Dict[str, Any]:
    return {
        "type": "subscription.canceled",
        "data": {
            "object": {
                "id": subscription_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "status": "canceled",
            }
        },
    }


# ===================================================================
# Test: Signature verification
# ===================================================================

class TestSignatureVerification:
    """Tests para la verificación HMAC-SHA256 de Conekta."""

    def test_valid_signature(self, receiver):
        payload_body = json.dumps({"type": "test"}, separators=(",", ":"))
        sig = _make_signature(payload_body)
        assert receiver.verify_signature(payload_body, sig) is True

    def test_invalid_signature(self, receiver):
        payload_body = json.dumps({"type": "test"}, separators=(",", ":"))
        assert receiver.verify_signature(payload_body, "hmac_sha256=badhash,t=123") is False

    def test_missing_secret_returns_false(self, db):
        receiver = ConektaWebhookReceiver(db, webhook_secret="")
        assert receiver.verify_signature("body", "sig") is False

    def test_empty_signature_header_returns_false(self, receiver):
        assert receiver.verify_signature("body", "") is False

    def test_malformed_signature_no_equals(self, receiver):
        assert receiver.verify_signature("body", "justgarbage") is False

    def test_malformed_signature_missing_timestamp(self, receiver):
        assert receiver.verify_signature("body", "hmac_sha256=abc") is False

    def test_malformed_signature_missing_hash(self, receiver):
        assert receiver.verify_signature("body", "t=12345") is False

    def test_signature_with_extra_parts(self, receiver):
        """Signature with extra comma-separated parts should still work."""
        payload_body = json.dumps({"ok": True}, separators=(",", ":"))
        timestamp = "1700000000"
        signed_content = f"{timestamp}{payload_body}"
        sig_hash = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        header = f"hmac_sha256={sig_hash},t={timestamp},extra=ignored"
        assert receiver.verify_signature(payload_body, header) is True

    def test_signature_timing_safe(self, receiver):
        """Even a slightly different payload should fail."""
        body1 = json.dumps({"type": "a"}, separators=(",", ":"))
        body2 = json.dumps({"type": "b"}, separators=(",", ":"))
        sig = _make_signature(body1)
        assert receiver.verify_signature(body2, sig) is False


# ===================================================================
# Test: Event parsing
# ===================================================================

class TestEventParsing:
    """Tests para la normalización de eventos de Conekta."""

    def test_parse_payment_paid(self, receiver):
        payload = _make_payment_paid_payload()
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "payment.paid"
        assert parsed["is_supported"] is True
        assert parsed["invoice_id"] == "inv_123"
        assert parsed["customer_id"] == "cus_456"
        assert parsed["amount"] == 100000

    def test_parse_payment_failed(self, receiver):
        payload = _make_payment_failed_payload()
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "payment.failed"
        assert parsed["is_supported"] is True

    def test_parse_subscription_created(self, receiver):
        payload = _make_subscription_created_payload()
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "subscription.created"
        assert parsed["is_supported"] is True
        assert parsed["subscription_id"] == "sub_001"

    def test_parse_subscription_canceled(self, receiver):
        payload = _make_subscription_canceled_payload()
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "subscription.canceled"
        assert parsed["is_supported"] is True
        assert parsed["subscription_id"] == "sub_002"

    def test_parse_unsupported_event(self, receiver):
        payload = {"type": "order.created", "data": {"object": {}}}
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "order.created"
        assert parsed["is_supported"] is False

    def test_parse_missing_type_raises(self, receiver):
        with pytest.raises(ValueError, match="Missing 'type'"):
            ConektaWebhookReceiver.parse_event({})

    def test_parse_empty_data_object(self, receiver):
        payload = {"type": "payment.paid", "data": {}}
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "payment.paid"
        assert parsed["invoice_id"] == ""

    def test_parse_none_data(self, receiver):
        payload = {"type": "payment.paid", "data": None}
        parsed = ConektaWebhookReceiver.parse_event(payload)
        assert parsed["event_type"] == "payment.paid"


# ===================================================================
# Test: Supported events constant
# ===================================================================

class TestSupportedEvents:
    """Tests para la lista de eventos soportados."""

    def test_all_four_events_present(self):
        assert len(SUPPORTED_EVENTS) == 4
        assert "payment.paid" in SUPPORTED_EVENTS
        assert "payment.failed" in SUPPORTED_EVENTS
        assert "subscription.created" in SUPPORTED_EVENTS
        assert "subscription.canceled" in SUPPORTED_EVENTS

    def test_event_type_enum(self):
        assert ConektaEventType.PAYMENT_PAID.value == "payment.paid"
        assert ConektaEventType.PAYMENT_FAILED.value == "payment.failed"
        assert ConektaEventType.SUBSCRIPTION_CREATED.value == "subscription.created"
        assert ConektaEventType.SUBSCRIPTION_CANCELED.value == "subscription.canceled"


# ===================================================================
# Test: Full process_webhook flow
# ===================================================================

class TestProcessWebhook:
    """Tests del flujo completo: firma → parse → DB → log."""

    def test_payment_paid_updates_invoice(self, receiver, db):
        payload = _make_payment_paid_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)

        assert result["received"] is True
        assert result["processed"] is True
        assert result["event_type"] == "payment.paid"
        assert result["invoice_updated"] is True
        assert len(db._invoice_updates) == 1
        assert db._invoice_updates[0]["provider_invoice_id"] == "inv_123"
        assert len(db._audit_log) == 1
        assert db._audit_log[0]["entity"] == "conekta_event"

    def test_payment_failed_updates_invoice(self, receiver, db):
        payload = _make_payment_failed_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)

        assert result["processed"] is True
        assert result["event_type"] == "payment.failed"
        # mark_billing_invoice_paid_by_ref no se llama para failed
        assert len(db._invoice_updates) == 0
        # Pero sí se llama a conn.execute para el update directo
        assert db.conn.execute.called

    def test_subscription_created_updates_sub(self, receiver, db):
        payload = _make_subscription_created_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)

        assert result["processed"] is True
        assert result["event_type"] == "subscription.created"
        assert result["subscription_updated"] is True
        # Verify the SQL was called with correct status
        call_args = db.conn.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "billing_subscriptions" in sql
        assert params[0] == "active"

    def test_subscription_canceled_updates_sub(self, receiver, db):
        payload = _make_subscription_canceled_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)

        assert result["processed"] is True
        assert result["event_type"] == "subscription.canceled"
        assert result["subscription_updated"] is True
        call_args = db.conn.execute.call_args
        params = call_args[0][1]
        assert params[0] == "canceled"

    def test_unsupported_event_returns_not_processed(self, receiver, db):
        payload = {"type": "order.created", "data": {"object": {}}}
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)

        assert result["received"] is True
        assert result["processed"] is False
        assert result["reason"] == "evento no soportado"
        # Still logged
        assert len(db._audit_log) == 1
        assert db._audit_log[0]["status"] == "unsupported"

    def test_invalid_signature_raises_401(self, receiver, db):
        payload = _make_payment_paid_payload()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            receiver.process_webhook(payload, "hmac_sha256=bad,t=123")
        assert exc_info.value.status_code == 401

    def test_missing_type_raises_400(self, receiver, db):
        payload = {"data": {"object": {}}}
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            receiver.process_webhook(payload, sig)
        assert exc_info.value.status_code == 400

    def test_audit_log_contains_all_fields(self, receiver, db):
        payload = _make_payment_paid_payload(
            invoice_id="inv_ABC", customer_id="cus_XYZ", amount=99999
        )
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        receiver.process_webhook(payload, sig)

        log = db._audit_log[0]
        assert log["tool_name"] == "billing"
        assert log["action"] == "webhook"
        assert log["entity"] == "conekta_event"
        assert log["entity_id"] == "payment.paid"
        assert log["payload"]["provider"] == "conekta"
        assert log["payload"]["invoice_id"] == "inv_ABC"
        assert log["payload"]["customer_id"] == "cus_XYZ"
        assert log["payload"]["amount"] == 99999


# ===================================================================
# Test: HTTP endpoint (TestClient)
# ===================================================================

class TestWebhookEndpoint:
    """Tests del endpoint HTTP POST /api/v1/billing/webhook."""

    def test_valid_webhook_returns_200(self, client):
        payload = _make_payment_paid_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["received"] is True
        assert data["processed"] is True
        assert data["event_type"] == "payment.paid"

    def test_empty_body_returns_400(self, client):
        response = client.post(
            "/api/v1/billing/webhook",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "vacío" in response.json()["detail"]

    def test_invalid_json_returns_400(self, client):
        response = client.post(
            "/api/v1/billing/webhook",
            content=b"not json",
            headers={
                "Content-Type": "application/json",
                "conekta-signature": "something",
            },
        )
        assert response.status_code == 400
        assert "inválido" in response.json()["detail"]

    def test_bad_signature_returns_401(self, client):
        payload = _make_payment_paid_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": "hmac_sha256=bad,t=123",
            },
        )
        assert response.status_code == 401
        assert "firma" in response.json()["detail"].lower()

    def test_missing_signature_header_returns_401(self, client):
        payload = _make_payment_paid_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={"Content-Type": "application/json"},
        )
        # Without signature, verify_signature returns False → 401
        assert response.status_code == 401

    def test_subscription_created_endpoint(self, client):
        payload = _make_subscription_created_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "subscription.created"
        assert data["subscription_updated"] is True

    def test_subscription_canceled_endpoint(self, client):
        payload = _make_subscription_canceled_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "subscription.canceled"
        assert data["subscription_updated"] is True

    def test_payment_failed_endpoint(self, client):
        payload = _make_payment_failed_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "payment.failed"
        assert data["processed"] is True

    def test_unsupported_event_endpoint(self, client):
        payload = {"type": "order.created", "data": {"object": {}}}
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        response = client.post(
            "/api/v1/billing/webhook",
            content=payload_body,
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["processed"] is False


# ===================================================================
# Test: Edge cases
# ===================================================================

class TestEdgeCases:
    """Tests de edge cases y robustez."""

    def test_webhook_secret_from_env(self, db):
        """When no secret passed, reads from env var."""
        with patch.dict(os.environ, {"B2B_CONEKTA_WEBHOOK_SECRET": "env_secret"}):
            receiver = ConektaWebhookReceiver(db)
            assert receiver.webhook_secret == "env_secret"

    def test_webhook_secret_none_when_no_env(self, db):
        """When no secret and no env var, secret is empty string."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("B2B_CONEKTA_WEBHOOK_SECRET", None)
            receiver = ConektaWebhookReceiver(db)
            assert receiver.webhook_secret == ""

    def test_conekta_signature_header_name(self):
        """Verify we look for the correct header name."""
        # This is tested implicitly by all endpoint tests using
        # headers={"conekta-signature": sig}
        pass  # Covered by TestWebhookEndpoint

    def test_idempotent_payment_paid(self, receiver, db):
        """Processing the same payment.paid twice should work."""
        payload = _make_payment_paid_payload()
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result1 = receiver.process_webhook(payload, sig)
        result2 = receiver.process_webhook(payload, sig)

        assert result1["processed"] is True
        assert result2["processed"] is True
        assert len(db._audit_log) == 2

    def test_large_payload(self, receiver, db):
        """Large but valid payload should be processed."""
        payload = _make_payment_paid_payload()
        payload["data"]["object"]["description"] = "x" * 10000
        payload_body = json.dumps(payload, separators=(",", ":"))
        sig = _make_signature(payload_body)

        result = receiver.process_webhook(payload, sig)
        assert result["processed"] is True
