# -*- coding: utf-8 -*-
"""
test_webhooks.py — Tests del módulo de Webhooks.

Cubre:
  - Modelos: tipos de evento, suscripción, validación url/secret/event_types
  - Firma HMAC-SHA256 y verificación
  - Retry con exponential backoff (3 intentos)
  - Rate limiting
  - Service: alta/baja/listado de suscripciones + publicación de eventos
  - API: endpoints de suscripciones y publicación con autenticación
"""
from __future__ import annotations

import pytest

from b2b_ai.features.webhooks.models import (
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEvent,
    WebhookEventType,
    WebhookSubscription,
)
from b2b_ai.features.webhooks.processor import (
    WebhookProcessor,
    _backoff_delay,
    sign_payload,
    verify_signature,
)
from b2b_ai.features.webhooks.service import WebhookService, reset_state


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _sub(**kw):
    base = {"url": "https://hooks.example.com/cb", "secret": "super-secreto-1"}
    base.update(kw)
    return base


def _dummy_post(*, ok=True, status_code=200, error=None):
    def _post(url, body, headers):
        return {"ok": ok, "status_code": status_code, "error": error}
    return _post


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestEventTypes:
    def test_eventos_requeridos_existen(self):
        """Los 4 eventos clave deben estar definidos."""
        expected = {
            "cfdi.processed",
            "declaration.ready",
            "alert.expiring",
            "reconciliation.completed",
        }
        actual = {e.value for e in WebhookEventType}
        assert expected.issubset(actual)

    def test_values_are_strings(self):
        assert WebhookEventType.CFDI_PROCESSED.value == "cfdi.processed"
        assert WebhookEventType.DECLARATION_READY.value == "declaration.ready"


class TestWebhookSubscription:
    def test_valid_subscription(self):
        s = WebhookSubscription(**_sub())
        assert s.active is True
        assert len(s.secret) >= 8

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError):
            WebhookSubscription(**_sub(url=""))

    def test_non_http_url_rejected(self):
        with pytest.raises(ValueError):
            WebhookSubscription(**_sub(url="ftp://x.com/cb"))

    def test_short_secret_rejected(self):
        with pytest.raises(ValueError):
            WebhookSubscription(**_sub(secret="short"))

    def test_event_types_coerced_from_strings(self):
        s = WebhookSubscription(**_sub(event_types=["cfdi.processed", "alert.expiring"]))
        assert s.event_types == [
            WebhookEventType.CFDI_PROCESSED,
            WebhookEventType.ALERT_EXPIRING,
        ]

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError):
            WebhookSubscription(**_sub(event_types=["nope.event"]))

    def test_accepts_empty_means_all(self):
        s = WebhookSubscription(**_sub())  # event_types vacío
        assert s.accepts(WebhookEventType.CFDI_PROCESSED) is True
        assert s.accepts(WebhookEventType.RECONCILIATION_COMPLETED) is True

    def test_accepts_respects_whitelist(self):
        s = WebhookSubscription(**_sub(event_types=["cfdi.processed"]))
        assert s.accepts(WebhookEventType.CFDI_PROCESSED) is True
        assert s.accepts(WebhookEventType.DECLARATION_READY) is False

    def test_inactive_subscription_does_not_accept(self):
        s = WebhookSubscription(**_sub(active=False))
        assert s.accepts(WebhookEventType.CFDI_PROCESSED) is False

    def test_to_dict(self):
        s = WebhookSubscription(**_sub(event_types=["cfdi.processed"]))
        d = s.to_dict()
        assert d["url"] == "https://hooks.example.com/cb"
        assert "secret" not in d  # el secret nunca debe exponerse
        assert d["event_types"] == ["cfdi.processed"]


# ---------------------------------------------------------------------------
# Firma HMAC-SHA256
# ---------------------------------------------------------------------------

class TestSignature:
    def test_signature_is_hex_sha256(self):
        sig = sign_payload({"event": "cfdi.processed", "payload": {"rfc": "ABC"}}, "secret")
        assert len(sig) == 64
        int(sig, 16)  # debe ser hex válido

    def test_signature_changes_with_payload(self):
        s1 = sign_payload({"a": 1}, "secret")
        s2 = sign_payload({"a": 2}, "secret")
        assert s1 != s2

    def test_signature_changes_with_secret(self):
        s1 = sign_payload({"a": 1}, "secret-1")
        s2 = sign_payload({"a": 1}, "secret-2")
        assert s1 != s2

    def test_verify_matches(self):
        payload = {"event": "declaration.ready", "payload": {"id": "x"}}
        sig = sign_payload(payload, "secret")
        assert verify_signature(payload, "secret", sig) is True

    def test_verify_wrong_secret(self):
        payload = {"event": "declaration.ready", "payload": {"id": "x"}}
        sig = sign_payload(payload, "secret-a")
        assert verify_signature(payload, "secret-b", sig) is False

    def test_verify_tampered(self):
        payload = {"event": "declaration.ready", "payload": {"id": "x"}}
        sig = sign_payload(payload, "secret")
        assert verify_signature({"event": "other", "payload": {}}, "secret", sig) is False


# ---------------------------------------------------------------------------
# Retry exponential backoff
# ---------------------------------------------------------------------------

class TestBackoff:
    def test_backoff_delay_sequence(self):
        # intento 1 → 2s, intento 2 → 4s, intento 3 → 8s
        assert _backoff_delay(1) == 2.0
        assert _backoff_delay(2) == 4.0
        assert _backoff_delay(3) == 8.0

    def test_backoff_is_exponential(self):
        d1, d2, d3 = _backoff_delay(1), _backoff_delay(2), _backoff_delay(3)
        assert d2 == d1 * 2 and d3 == d2 * 2


class TestRetry:
    def test_success_first_attempt_no_retries(self):
        posts = []
        proc = WebhookProcessor(http_post=_dummy_post(ok=True), sleep=lambda s: posts.append(s))
        sub = WebhookSubscription(**_sub())
        event = WebhookEvent(event_type=WebhookEventType.CFDI_PROCESSED, payload={"id": 1})
        d = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=event.id,
                                         event_type=event.event_type), sub, event)
        assert d.status == WebhookDeliveryStatus.DELIVERED
        assert d.attempts == 1
        assert posts == []  # sin reintentos, sin sleep

    def test_retries_until_success(self):
        """Falla 2 veces, funciona en el 3er intento."""
        calls = {"n": 0}
        sleeps = []

        def _flaky(url, body, headers):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"ok": False, "status_code": 500, "error": "boom"}
            return {"ok": True, "status_code": 200}

        proc = WebhookProcessor(http_post=_flaky, sleep=sleeps.append)
        sub = WebhookSubscription(**_sub())
        event = WebhookEvent(event_type=WebhookEventType.DECLARATION_READY, payload={})
        d = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=event.id,
                                         event_type=event.event_type), sub, event)
        assert d.status == WebhookDeliveryStatus.DELIVERED
        assert d.attempts == 3
        assert len(sleeps) == 2  # 2 delays: 2s + 4s

    def test_exhausts_after_max_attempts(self):
        sleeps = []
        proc = WebhookProcessor(
            max_attempts=3,
            http_post=_dummy_post(ok=False, status_code=500, error="down"),
            sleep=sleeps.append,
        )
        sub = WebhookSubscription(**_sub())
        event = WebhookEvent(event_type=WebhookEventType.ALERT_EXPIRING, payload={})
        d = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=event.id,
                                         event_type=event.event_type), sub, event)
        assert d.status == WebhookDeliveryStatus.FAILED
        assert d.attempts == 3
        assert d.last_error is not None
        assert len(sleeps) == 2  # intentos 1→2→3, delays entre ellos

    def test_exception_is_treated_as_failure(self):
        def _crash(url, body, headers):
            raise ConnectionError("timeout")

        sleeps = []
        proc = WebhookProcessor(max_attempts=2, http_post=_crash, sleep=sleeps.append)
        sub = WebhookSubscription(**_sub())
        event = WebhookEvent(event_type=WebhookEventType.ALERT_EXPIRING, payload={})
        d = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=event.id,
                                         event_type=event.event_type), sub, event)
        assert d.status == WebhookDeliveryStatus.FAILED
        assert d.attempts == 2
        assert "timeout" in (d.last_error or "")

    def test_headers_include_signature(self):
        captured = {}

        def _capture(url, body, headers):
            captured.update(headers)
            return {"ok": True, "status_code": 200}

        proc = WebhookProcessor(http_post=_capture)
        sub = WebhookSubscription(**_sub())
        event = WebhookEvent(event_type=WebhookEventType.CFDI_PROCESSED, payload={"rfc": "ABC"})
        proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=event.id,
                                     event_type=event.event_type), sub, event)
        assert "X-Likida-Signature" in captured
        assert captured["X-Likida-Signature"].startswith("sha256=")
        assert captured["X-Likida-Event"] == "cfdi.processed"
        assert captured["X-Likida-Event-Id"] == event.id


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_rate_limited_when_bucket_empty(self):
        # Capacidad 1 → el primer intento pasa, el segundo se limita.
        proc = WebhookProcessor(rate_capacity=1, rate_refill=0.0,
                                http_post=_dummy_post(ok=True), sleep=lambda s: None)
        sub = WebhookSubscription(**_sub())
        e1 = WebhookEvent(event_type=WebhookEventType.CFDI_PROCESSED, payload={})
        e2 = WebhookEvent(event_type=WebhookEventType.CFDI_PROCESSED, payload={})
        d1 = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=e1.id,
                                          event_type=e1.event_type), sub, e1)
        d2 = proc.deliver(WebhookDelivery(subscription_id=sub.id, event_id=e2.id,
                                          event_type=e2.event_type), sub, e2)
        assert d1.status == WebhookDeliveryStatus.DELIVERED
        assert d2.status == WebhookDeliveryStatus.RATE_LIMITED
        assert d2.attempts == 0

    def test_rate_limit_is_per_subscription(self):
        proc = WebhookProcessor(rate_capacity=1, rate_refill=0.0,
                                http_post=_dummy_post(ok=True), sleep=lambda s: None)
        s1 = WebhookSubscription(**_sub(url="https://a.com/cb"))
        s2 = WebhookSubscription(**_sub(url="https://b.com/cb"))
        e = WebhookEvent(event_type=WebhookEventType.CFDI_PROCESSED, payload={})
        d1 = proc.deliver(WebhookDelivery(subscription_id=s1.id, event_id=e.id,
                                          event_type=e.event_type), s1, e)
        d2 = proc.deliver(WebhookDelivery(subscription_id=s2.id, event_id=e.id,
                                          event_type=e.event_type), s2, e)
        assert d1.status == WebhookDeliveryStatus.DELIVERED
        assert d2.status == WebhookDeliveryStatus.DELIVERED  # bucket separado


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class TestService:
    @pytest.fixture(autouse=True)
    def _clean(self):
        reset_state()
        yield
        reset_state()

    def test_register_and_get(self):
        svc = WebhookService()
        sub = svc.register_subscription(
            url="https://hooks.example.com/cb", secret="s3cr3to-seguro",
            event_types=["cfdi.processed"],
        )
        assert svc.get_subscription(sub.id) is sub
        assert len(svc.list_subscriptions()) == 1

    def test_delete_subscription(self):
        svc = WebhookService()
        sub = svc.register_subscription(url="https://a.com/cb", secret="secreto-largo")
        assert svc.delete_subscription(sub.id) is True
        assert svc.get_subscription(sub.id) is None
        assert svc.delete_subscription(sub.id) is False  # ya no existe

    def test_publish_delivers_only_matching_active_subs(self):
        posts = []

        def _post(url, body, headers):
            posts.append(url)
            return {"ok": True, "status_code": 200}

        svc = WebhookService(processor=WebhookProcessor(http_post=_post, sleep=lambda s: None))
        svc.register_subscription(url="https://a.com/cb", secret="secreto-largo",
                                  event_types=["cfdi.processed"])
        svc.register_subscription(url="https://b.com/cb", secret="secreto-largo",
                                  event_types=["declaration.ready"])
        svc.register_subscription(url="https://c.com/cb", secret="secreto-largo",
                                  event_types=["cfdi.processed"], active=False)

        event = svc.publish(WebhookEventType.CFDI_PROCESSED, payload={"rfc": "ABC"})
        assert event.event_type == WebhookEventType.CFDI_PROCESSED
        assert posts == ["https://a.com/cb"]  # solo la sub activa y matching

    def test_publish_empty_event_types_gets_all(self):
        posts = []
        svc = WebhookService(processor=WebhookProcessor(
            http_post=lambda url, body, headers: (posts.append(url), {"ok": True, "status_code": 200})[1],
            sleep=lambda s: None,
        ))
        svc.register_subscription(url="https://a.com/cb", secret="secreto-largo")
        svc.publish(WebhookEventType.RECONCILIATION_COMPLETED, payload={})
        assert posts == ["https://a.com/cb"]

    def test_publish_from_string_event_type(self):
        svc = WebhookService()
        event = svc.publish("declaration.ready", payload={})
        assert isinstance(event.event_type, WebhookEventType)
        assert event.event_type.value == "declaration.ready"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class TestApi:
    @pytest.fixture(autouse=True)
    def _clean(self):
        reset_state()
        yield
        reset_state()

    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from b2b_ai.features.webhooks.routes import build_webhooks_router

        def fake_auth():
            return {"tenant_id": "t1"}

        app = FastAPI()
        app.include_router(build_webhooks_router(None, fake_auth))
        return TestClient(app)

    def test_create_subscription(self, client):
        r = client.post("/api/v1/webhooks/subscriptions", json=_sub())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["subscription"]["url"] == "https://hooks.example.com/cb"
        assert "secret" not in body["subscription"]

    def test_create_subscription_invalid_event_type(self, client):
        r = client.post("/api/v1/webhooks/subscriptions",
                        json=dict(_sub(), event_types=["bogus.event"]))
        assert r.status_code == 422

    def test_list_subscriptions(self, client):
        client.post("/api/v1/webhooks/subscriptions", json=_sub())
        r = client.get("/api/v1/webhooks/subscriptions")
        assert r.status_code == 200
        assert len(r.json()["subscriptions"]) == 1

    def test_get_subscription_not_found(self, client):
        r = client.get("/api/v1/webhooks/subscriptions/does-not-exist")
        assert r.status_code == 404

    def test_delete_subscription(self, client):
        created = client.post("/api/v1/webhooks/subscriptions", json=_sub()).json()
        sub_id = created["subscription"]["id"]
        r = client.delete(f"/api/v1/webhooks/subscriptions/{sub_id}")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert client.get("/api/v1/webhooks/subscriptions").json()["subscriptions"] == []

    def test_publish_invalid_event(self, client):
        r = client.post("/api/v1/webhooks/publish", json={"event_type": "nope.event"})
        assert r.status_code == 422

    def test_router_refuses_without_auth_dependency(self):
        from b2b_ai.features.webhooks.routes import build_webhooks_router
        with pytest.raises(ValueError):
            build_webhooks_router(None, None)
