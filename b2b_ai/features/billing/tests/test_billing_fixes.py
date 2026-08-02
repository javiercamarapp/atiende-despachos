# -*- coding: utf-8 -*-
"""test_billing_fixes.py — Tests de los fixes P1 del módulo billing.

Cubre los 6 fixes P1/P2 que desbloquean el cobro real en producción:

  P1-1: `_post()` hace HTTP real (httpx) cuando `mock=False`, con timeout y
        retry; en mock no toca la red.
  P1-2: `process_webhook` exige firma HMAC OBLIGATORIA en modo producción
        (ausente/inválida -> rechazo); en dev/mock la permite sin firma.
  P1-3: el servicio resuelve la suscripción por `subscription_id` del evento
        (no por `object.id`, que es el charge/order id).
  P1-4: `create_checkout_session` envía el `unit_price` real del plan (ya no
        None).
  P1-5: `create_customer` recibe el RFC real del tenant, nunca el plan_code.
  P1-6: documentado el requisito de capa DB para el store en memoria.

NOTA: estos tests corren en modo mock / con transporte httpx inyectado; no
hacen llamadas reales a la red de Conekta.
"""
import hashlib
import hmac
import json
import os
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.billing import models as store
from b2b_ai.features.billing.conekta_client import (
    ConektaAPIError,
    ConektaClient,
    ConektaEnvironment,
    ConektaWebhookError,
)
from b2b_ai.features.billing.models import SubscriptionStatus
from b2b_ai.features.billing.plans import get_plan
from b2b_ai.features.billing.service import BillingError, BillingService
from b2b_ai.features.billing.routes import build_billing_router


@pytest.fixture(autouse=True)
def _reset():
    store._reset_state()
    yield
    store._reset_state()


def _header(secret: str, payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"))
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}{raw}".encode(), hashlib.sha256).hexdigest()
    return f"hmac_sha256={digest},t={ts}"


# ---------------------------------------------------------------------------
# P1-1: POST real (httpx) cuando mock=False
# ---------------------------------------------------------------------------

class TestRealHttpPost:
    def test_post_real_network_when_not_mock(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["has_auth"] = "Authorization" in request.headers
            return httpx.Response(200, json={"id": "cus_abc", "object": "customer"})

        transport = httpx.MockTransport(handler)
        c = ConektaClient(api_key="key_123", mock=False, environment="production")
        c._http = httpx.Client(transport=transport)

        res = c._post("/customers", {"name": "x"})

        assert res["id"] == "cus_abc"
        assert "api.conekta.io" in captured["url"]
        assert captured["body"] == {"name": "x"}
        assert captured["has_auth"] is True

    def test_post_mock_never_hits_network(self):
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200, json={})

        transport = httpx.MockTransport(handler)
        c = ConektaClient(api_key="key_123", mock=True, environment="production")
        c._http = httpx.Client(transport=transport)

        res = c._post("/customers", {"name": "x"})
        assert res["id"].startswith("cus_")
        assert called["n"] == 0

    def test_post_4xx_raises_upstream_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, text="invalid params")

        transport = httpx.MockTransport(handler)
        c = ConektaClient(api_key="key_123", mock=False, environment="production")
        c._http = httpx.Client(transport=transport)

        with pytest.raises(ConektaAPIError) as e:
            c._post("/orders", {})
        assert e.value.code == "upstream_error"
        assert e.value.status_code == 422

    def test_post_retries_then_raises_on_5xx(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(500, text="boom")

        transport = httpx.MockTransport(handler)
        c = ConektaClient(api_key="key_123", mock=False, environment="production")
        c._http = httpx.Client(transport=transport)
        c._max_retries = 3

        with pytest.raises(ConektaAPIError) as e:
            c._post("/orders", {})
        assert e.value.code == "upstream_error"
        assert attempts["n"] == 3  # se reintentó el máximo de veces


# ---------------------------------------------------------------------------
# P1-2: firma de webhook obligatoria en producción
# ---------------------------------------------------------------------------

class TestMandatorySignature:
    def test_production_missing_signature_raises(self):
        c = ConektaClient(api_key="k", webhook_secret="secret",
                          environment="production", mock=True)
        with pytest.raises(ConektaWebhookError):
            c.process_webhook({"type": "charge.paid", "data": {"object": {}}})

    def test_production_invalid_signature_raises(self):
        c = ConektaClient(api_key="k", webhook_secret="secret",
                          environment="production", mock=True)
        with pytest.raises(ConektaWebhookError):
            c.process_webhook(
                {"type": "charge.paid", "data": {"object": {}}},
                signature="hmac_sha256=deadbeef,t=123",
            )

    def test_production_valid_signature_ok(self):
        c = ConektaClient(api_key="k", webhook_secret="secret",
                          environment="production", mock=True)
        payload = {"type": "charge.paid", "data": {"object": {"id": "chg_1"}}}
        header = _header("secret", payload)
        result = c.process_webhook(payload, header)
        assert result["mark_paid"] is True

    def test_dev_mock_missing_signature_ok(self):
        c = ConektaClient(mock=True)  # sandbox por defecto
        result = c.process_webhook({"type": "charge.paid", "data": {"object": {}}})
        assert result["handled"] is True

    def test_dev_mock_invalid_signature_raises(self):
        c = ConektaClient(api_key="k", webhook_secret="secret", mock=True)
        with pytest.raises(ConektaWebhookError):
            c.process_webhook(
                {"type": "charge.paid", "data": {"object": {}}},
                signature="hmac_sha256=bad,t=123",
            )


# ---------------------------------------------------------------------------
# P1-3: resolver suscripción por subscription_id del evento
# ---------------------------------------------------------------------------

class TestSubscriptionLookup:
    def _make_subscription(self):
        sub = store.Subscription(
            tenant_id="tenant_1",
            plan_code="pro",
            status=SubscriptionStatus.ACTIVE,
            provider_subscription_id="sub_actual",
        )
        store.save_subscription(sub)
        return sub

    def test_event_subscription_id_finds_subscription(self):
        self._make_subscription()
        svc = BillingService(client=ConektaClient(mock=True))

        # object.id es el charge_id; el subscription_id real va en el evento.
        event = {
            "type": "charge.paid",
            "data": {"object": {"id": "chg_999", "subscription_id": "sub_actual"}},
        }
        result = svc.handle_webhook_event(event)
        assert result["subscription_id"] is not None
        assert store.get_subscription_by_tenant("tenant_1").status == SubscriptionStatus.ACTIVE

    def test_object_id_alone_does_not_match(self):
        self._make_subscription()
        svc = BillingService(client=ConektaClient(mock=True))

        # Sin subscription_id: object.id = chg_999 no coincide con sub_actual.
        event = {"type": "charge.paid", "data": {"object": {"id": "chg_999"}}}
        result = svc.handle_webhook_event(event)
        assert result["subscription_id"] is None


# ---------------------------------------------------------------------------
# P1-4: unit_price real en el checkout
# ---------------------------------------------------------------------------

class TestCheckoutUnitPrice:
    def test_create_checkout_session_sends_unit_price(self):
        c = ConektaClient(mock=True)
        captured = {}

        def fake_post(path, body):
            captured["body"] = body
            return {"id": "ord_1", "checkout": {"url": "https://checkout/x"},
                    "object": "order"}

        c._post = fake_post  # type: ignore[method-assign]
        c.create_checkout_session("pro", "https://a", "https://b", unit_price=20000)
        assert captured["body"]["line_items"][0]["unit_price"] == 20000

    def test_default_unit_price_from_plan(self):
        c = ConektaClient(mock=True)
        captured = {}

        def fake_post(path, body):
            captured["body"] = body
            return {"id": "ord_1", "checkout": {"url": "https://checkout/x"},
                    "object": "order"}

        c._post = fake_post  # type: ignore[method-assign]
        c.create_checkout_session("business", "https://a", "https://b")
        assert captured["body"]["line_items"][0]["unit_price"] == get_plan("business").price_mxn
        assert get_plan("business").price_mxn == 40000

    def test_service_passes_plan_price(self):
        svc = BillingService(client=ConektaClient(mock=True))
        captured = {}

        def fake_post(path, body):
            captured["body"] = body
            return {"id": "ord_1", "checkout": {"url": "https://checkout/x"},
                    "object": "order"}

        svc.client._post = fake_post  # type: ignore[method-assign]
        svc.create_checkout("tenant_1", "pro", "https://a", "https://b", rfc="GYA850101XYZ")
        assert captured["body"]["line_items"][0]["unit_price"] == 20000


# ---------------------------------------------------------------------------
# P1-5: RFC real del tenant en create_customer
# ---------------------------------------------------------------------------

class TestCustomerRfc:
    def test_uses_real_rfc_when_provided(self):
        svc = BillingService(client=ConektaClient(mock=True))
        captured = {}
        svc.client.create_customer = lambda rfc, email, name: (
            captured.update(rfc=rfc) or {"id": "cus_1"}
        )
        svc.client.create_checkout_session = lambda **kw: {
            "id": "ord_1", "checkout": {"url": "https://checkout/x"}, "object": "order"
        }
        svc.create_checkout("tenant_1", "pro", "https://a", "https://b",
                            rfc="GYA850101XYZ")
        assert captured["rfc"] == "GYA850101XYZ"

    def test_fallback_never_uses_plan_code(self):
        svc = BillingService(client=ConektaClient(mock=True))
        captured = {}
        svc.client.create_customer = lambda rfc, email, name: (
            captured.update(rfc=rfc) or {"id": "cus_1"}
        )
        svc.client.create_checkout_session = lambda **kw: {
            "id": "ord_1", "checkout": {"url": "https://checkout/x"}, "object": "order"
        }
        svc.create_checkout("tenant_1", "pro", "https://a", "https://b")
        assert captured["rfc"] != "pro"
        assert captured["rfc"].startswith("TENANT")

    def test_activate_pilot_uses_real_rfc(self):
        svc = BillingService(client=ConektaClient(mock=True))
        captured = {}
        svc.client.create_customer = lambda rfc, email, name: (
            captured.update(rfc=rfc) or {"id": "cus_1"}
        )
        svc.client.create_subscription = lambda **kw: {"id": "sub_1", "status": "active"}
        svc.activate_pilot("tenant_1", "pro", rfc="GYA850101XYZ")
        assert captured["rfc"] == "GYA850101XYZ"


# ---------------------------------------------------------------------------
# P1-6: documentación de capa DB (comentario presente en models.py)
# ---------------------------------------------------------------------------

class TestStoreDbNote:
    def test_production_db_note_documented(self):
        import b2b_ai.features.billing.models as m
        src = open(m.__file__, encoding="utf-8").read()
        assert "P1-6" in src
        assert "PostgreSQL" in src
        assert "NO cambiar la implementación" in src


# ---------------------------------------------------------------------------
# P1-2 en el router: webhook sin firma -> 400 en producción
# ---------------------------------------------------------------------------

class TestWebhookRoute:
    def _app(self, env: dict) -> TestClient:
        app = FastAPI()

        def fake_require_api_key():
            return {"tenant_id": "tenant_test_123", "api_key": "key"}

        app.include_router(
            build_billing_router(db=None, require_api_key=fake_require_api_key)
        )
        return TestClient(app)

    def test_webhook_no_signature_in_production_400(self, monkeypatch):
        monkeypatch.setenv("B2B_CONEKTA_ENV", "production")
        monkeypatch.setenv("B2B_CONEKTA_KEY", "key_123")
        monkeypatch.setenv("B2B_CONEKTA_WEBHOOK_SECRET", "secret")
        client = self._app({})
        r = client.post("/api/v1/billing-piloto/webhook",
                        json={"type": "charge.paid", "data": {"object": {}}})
        assert r.status_code == 400

    def test_webhook_invalid_signature_in_production_400(self, monkeypatch):
        monkeypatch.setenv("B2B_CONEKTA_ENV", "production")
        monkeypatch.setenv("B2B_CONEKTA_KEY", "key_123")
        monkeypatch.setenv("B2B_CONEKTA_WEBHOOK_SECRET", "secret")
        client = self._app({})
        r = client.post(
            "/api/v1/billing-piloto/webhook",
            json={"type": "charge.paid", "data": {"object": {}}},
            headers={"X-Conekta-Signature": "hmac_sha256=bad,t=1"},
        )
        assert r.status_code == 400

    def test_webhook_valid_signature_in_production_200(self, monkeypatch):
        monkeypatch.setenv("B2B_CONEKTA_ENV", "production")
        monkeypatch.setenv("B2B_CONEKTA_KEY", "key_123")
        monkeypatch.setenv("B2B_CONEKTA_WEBHOOK_SECRET", "secret")
        client = self._app({})
        payload = {"type": "charge.paid", "data": {"object": {"id": "chg_1"}}}
        header = _header("secret", payload)
        r = client.post(
            "/api/v1/billing-piloto/webhook",
            json=payload,
            headers={"X-Conekta-Signature": header},
        )
        assert r.status_code == 200
