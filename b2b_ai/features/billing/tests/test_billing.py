# -*- coding: utf-8 -*-
"""test_billing.py — Tests del módulo de billing por suscripción con Conekta.

Cubre (todos los proveedores en modo MOCK, sin API real ni red):
  - Definición y pricing de planes (Starter/Pro/Business/Enterprise)
  - Ciclo de vida de la suscripción (trial -> paid -> cancel)
  - Checkout: creación de sesión de checkout y URL de pago
  - Webhooks: pago exitoso, fallido, cancelado (firma HMAC)
  - Conversión trial -> paid con emisión de factura
  - Endpoints de la API /api/v1/billing-piloto/*
"""
import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from b2b_ai.features.billing import models as store
from b2b_ai.features.billing.conekta_client import (
    ConektaAPIError,
    ConektaClient,
    ConektaEnvironment,
    ConektaWebhookError,
)
from b2b_ai.features.billing.plans import (
    DEFAULT_TRIAL_PLAN,
    TRIAL_DAYS,
    PlanCode,
    exceeds_cfdi_limit,
    get_plan,
    get_plan_or_none,
    list_plans,
)
from b2b_ai.features.billing.models import (
    InvoiceStatus,
    PaymentEventType,
    PaymentMethodType,
    SubscriptionStatus,
)
from b2b_ai.features.billing.service import (
    BillingError,
    BillingService,
    subscription_to_dict,
)
from b2b_ai.features.billing.routes import build_billing_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    store._reset_state()
    yield
    store._reset_state()


@pytest.fixture
def client():
    """TestClient sobre un app mínimo con el router de billing.

    `require_api_key` es un stub que devuelve un tenant_id fijo.
    """
    app = FastAPI()

    def fake_require_api_key():
        return {"tenant_id": "tenant_test_123", "api_key": "key"}

    app.include_router(build_billing_router(db=None, require_api_key=fake_require_api_key))
    return TestClient(app)


@pytest.fixture
def service():
    """BillingService con ConektaClient en modo mock."""
    return BillingService(client=ConektaClient(mock=True))


def _valid_webhook_header(secret: str, payload: dict) -> str:
    """Construye un header de firma HMAC válido para `payload`."""
    import json
    raw = json.dumps(payload, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signed = f"{timestamp}{raw}"
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"hmac_sha256={digest},t={timestamp}"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class TestPlans:
    def test_plans_pricing(self):
        assert get_plan("starter").price_mxn == 8000
        assert get_plan("pro").price_mxn == 20000
        assert get_plan("business").price_mxn == 40000
        assert get_plan("enterprise").price_mxn == 80000

    def test_plans_limits(self):
        assert get_plan("starter").max_users == 1
        assert get_plan("starter").max_cfdis_month == 500
        assert get_plan("pro").max_users == 5
        assert get_plan("pro").max_cfdis_month == 2000
        assert get_plan("business").max_users == 15
        assert get_plan("business").max_cfdis_month == 10000
        assert get_plan("enterprise").max_users is None
        assert get_plan("enterprise").max_cfdis_month is None

    def test_plans_sorted_by_price(self):
        codes = [p.code.value for p in list_plans()]
        assert codes == ["starter", "pro", "business", "enterprise"]

    def test_exceeds_cfdi_limit(self):
        assert exceeds_cfdi_limit("starter", 500) is False
        assert exceeds_cfdi_limit("starter", 501) is True
        assert exceeds_cfdi_limit("enterprise", 10_000_000) is False

    def test_get_plan_or_none(self):
        assert get_plan_or_none("nonexistent") is None
        assert get_plan_or_none("pro") is not None

    def test_default_trial_plan(self):
        assert DEFAULT_TRIAL_PLAN == "starter"
        assert TRIAL_DAYS == 30


# ---------------------------------------------------------------------------
# ConektaClient (mock)
# ---------------------------------------------------------------------------

class TestConektaClient:
    def test_missing_api_key_raises(self):
        c = ConektaClient(api_key="", mock=True)
        with pytest.raises(ConektaAPIError) as e:
            c._headers()
        assert e.value.code == "missing_api_key"

    def test_create_customer(self):
        c = ConektaClient(mock=True)
        res = c.create_customer(rfc="GYA850101XYZ", email="a@b.mx", name="ABC")
        assert res["id"].startswith("cus_")
        assert res["email"] == "a@b.mx"

    def test_create_subscription(self):
        c = ConektaClient(mock=True)
        res = c.create_subscription(customer_id="cus_1", plan_id="pro")
        assert res["id"].startswith("sub_")
        assert res["plan_id"] == "pro"

    def test_create_checkout_session(self):
        c = ConektaClient(mock=True)
        res = c.create_checkout_session("pro", "https://a/success", "https://a/cancel")
        assert res["checkout"]["url"].startswith("https://checkout.conekta.com/")

    def test_cancel_subscription(self):
        c = ConektaClient(mock=True)
        res = c.cancel_subscription("sub_123")
        assert res["status"] == "canceled"

    def test_environment_enum(self):
        assert ConektaEnvironment.SANDBOX.value == "sandbox"
        assert ConektaEnvironment.PRODUCTION.value == "production"


# ---------------------------------------------------------------------------
# Webhook signature
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_verify_valid_signature(self):
        secret = "test_webhook_secret_123"
        c = ConektaClient(mock=True, webhook_secret=secret)
        payload = {"event": "charge.paid"}
        header = _valid_webhook_header(secret, payload)
        import json
        raw = json.dumps(payload, separators=(",", ":"))
        assert c.verify_webhook_signature(raw, header) is True

    def test_verify_invalid_signature(self):
        secret = "test_webhook_secret_123"
        c = ConektaClient(mock=True, webhook_secret=secret)
        assert c.verify_webhook_signature("payload", "hmac_sha256=0" * 10) is False

    def test_verify_without_secret_is_false(self):
        c = ConektaClient(mock=True, webhook_secret="")
        assert c.verify_webhook_signature("payload", "anything") is False

    def test_process_webhook_bad_signature_raises(self):
        c = ConektaClient(mock=True, webhook_secret="secret")
        with pytest.raises(ConektaWebhookError):
            c.process_webhook({"type": "charge.paid"}, signature="bad")

    def test_process_webhook_valid_signature(self):
        secret = "secret"
        c = ConektaClient(mock=True, webhook_secret=secret)
        payload = {"type": "charge.paid", "data": {"object": {"id": "chg_1"}}}
        header = _valid_webhook_header(secret, payload)
        result = c.process_webhook(payload, header)
        assert result["handled"] is True
        assert result["mark_paid"] is True

    def test_process_webhook_no_signature_ok(self):
        c = ConektaClient(mock=True)
        result = c.process_webhook({"type": "charge.paid", "data": {"object": {"id": "x"}}})
        assert result["mark_paid"] is True

    def test_webhook_failed_and_canceled(self):
        c = ConektaClient(mock=True)
        failed = c.process_webhook({"type": "charge.failed", "data": {"object": {"id": "c"}}})
        assert failed["mark_failed"] is True
        canceled = c.process_webhook({"type": "subscription.canceled", "data": {"object": {"id": "s"}}})
        assert canceled["mark_canceled"] is True

    def test_webhook_unknown_event(self):
        c = ConektaClient(mock=True)
        result = c.process_webhook({"type": "unknown.event", "data": {"object": {}}})
        assert result["handled"] is False


# ---------------------------------------------------------------------------
# BillingService — trial y ciclo de vida
# ---------------------------------------------------------------------------

class TestBillingServiceTrial:
    def test_start_trial(self, service):
        sub = service.start_trial("tenant_1", "pro")
        assert sub.status == SubscriptionStatus.TRIALING
        assert sub.plan_code == PlanCode.PRO
        assert sub.price_mxn == 20000
        assert sub.trial_end is not None

    def test_start_trial_default_plan(self, service):
        sub = service.start_trial("tenant_2")
        assert sub.plan_code.value == "starter"
        assert sub.price_mxn == 8000

    def test_start_trial_invalid_plan(self, service):
        with pytest.raises(BillingError) as e:
            service.start_trial("tenant_3", "nonexistent")
        assert e.value.code == "invalid_plan"

    def test_start_trial_duplicate(self, service):
        service.start_trial("tenant_1", "pro")
        with pytest.raises(BillingError) as e:
            service.start_trial("tenant_1", "pro")
        assert e.value.code == "subscription_exists"

    def test_start_trial_missing_tenant(self, service):
        with pytest.raises(BillingError) as e:
            service.start_trial("", "pro")
        assert e.value.code == "missing_tenant"


class TestBillingServiceLifecycle:
    def test_convert_trial_to_paid(self, service):
        sub = service.start_trial("tenant_1", "pro")
        converted = service.convert_trial_to_paid(sub.id)
        assert converted.status == SubscriptionStatus.ACTIVE
        invoices = service.get_invoice_history("tenant_1")
        assert len(invoices) == 1
        assert invoices[0]["amount_mxn"] == 20000
        assert invoices[0]["status"] == InvoiceStatus.PAID.value

    def test_convert_non_trial_raises(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.convert_trial_to_paid(sub.id)
        with pytest.raises(BillingError) as e:
            service.convert_trial_to_paid(sub.id)
        assert e.value.code == "invalid_status"

    def test_cancel_subscription(self, service):
        sub = service.start_trial("tenant_1", "pro")
        canceled = service.cancel_subscription(sub.id)
        assert canceled.status == SubscriptionStatus.CANCELED
        assert canceled.canceled_at is not None

    def test_cancel_is_idempotent(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.cancel_subscription(sub.id)
        again = service.cancel_subscription(sub.id)
        assert again.status == SubscriptionStatus.CANCELED

    def test_handle_payment_failed(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.convert_trial_to_paid(sub.id)
        failed = service.handle_payment_failed(sub.id)
        assert failed.status == SubscriptionStatus.PAST_DUE

    def test_mark_paid_after_failed(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.convert_trial_to_paid(sub.id)
        service.handle_payment_failed(sub.id)
        active = service.mark_paid(sub.id)
        assert active.status == SubscriptionStatus.ACTIVE
        # Al recuperarse se emite factura nueva
        invoices = service.get_invoice_history("tenant_1")
        assert len(invoices) >= 2


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

class TestCheckout:
    def test_create_checkout_returns_url(self, service):
        result = service.create_checkout(
            "tenant_1", "pro", "https://a/success", "https://a/cancel"
        )
        assert result["checkout_url"].startswith("https://checkout.conekta.com/")
        assert result["plan_code"] == "pro"
        assert result["amount_mxn"] == 20000

    def test_create_checkout_invalid_plan(self, service):
        with pytest.raises(BillingError) as e:
            service.create_checkout("tenant_1", "nope", "https://a", "https://b")
        assert e.value.code == "invalid_plan"


# ---------------------------------------------------------------------------
# Webhook processing vía servicio
# ---------------------------------------------------------------------------

class TestBillingWebhooks:
    def test_webhook_paid_activates(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.convert_trial_to_paid(sub.id)
        assert sub.provider_subscription_id is not None
        service.handle_payment_failed(sub.id)
        assert store.get_subscription_by_tenant("tenant_1").status == SubscriptionStatus.PAST_DUE

        result = service.handle_webhook_event({
            "type": "subscription.paid",
            "data": {"object": {"id": sub.provider_subscription_id}},
        })
        assert result["mark_paid"] is True
        assert store.get_subscription_by_tenant("tenant_1").status == SubscriptionStatus.ACTIVE

    def test_webhook_failed_marks_past_due(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.convert_trial_to_paid(sub.id)
        service.handle_webhook_event({
            "type": "subscription.payment_failed",
            "data": {"object": {"id": sub.provider_subscription_id}},
        })
        assert store.get_subscription_by_tenant("tenant_1").status == SubscriptionStatus.PAST_DUE

    def test_webhook_bad_signature_raises(self, service):
        with pytest.raises(BillingError) as e:
            service.handle_webhook_event({"type": "charge.paid"}, signature="bad")
        assert e.value.code == "invalid_webhook_signature"

    def test_webhook_records_payment_event(self, service):
        sub = service.start_trial("tenant_1", "pro")
        service.handle_webhook_event({
            "type": "charge.paid",
            "data": {"object": {"id": "chg_evt"}},
        })
        events = store.get_payment_events()
        assert len(events) == 1
        assert events[0].event_type == PaymentEventType.PAYMENT_SUCCEEDED


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

class TestBillingAPI:
    def test_get_subscription_empty(self, client):
        r = client.get("/api/v1/billing-piloto/subscription")
        assert r.status_code == 200
        assert r.json()["subscription"] is None

    def test_checkout_endpoint(self, client):
        r = client.post("/api/v1/billing-piloto/checkout", json={
            "plan": "pro",
            "success_url": "https://a/success",
            "cancel_url": "https://a/cancel",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["checkout_url"].startswith("https://checkout.conekta.com/")
        assert body["plan_code"] == "pro"
        assert body["amount_mxn"] == 20000

    def test_checkout_invalid_plan(self, client):
        r = client.post("/api/v1/billing-piloto/checkout", json={
            "plan": "nope",
            "success_url": "https://a",
            "cancel_url": "https://b",
        })
        assert r.status_code == 400

    def test_cancel_no_subscription(self, client):
        r = client.post("/api/v1/billing-piloto/cancel", json={})
        assert r.status_code == 404

    def test_invoices_empty(self, client):
        r = client.get("/api/v1/billing-piloto/invoices")
        assert r.status_code == 200
        assert r.json()["invoices"] == []

    def test_plans_catalog(self, client):
        r = client.get("/api/v1/billing-piloto/plans")
        assert r.status_code == 200
        plans = r.json()["plans"]
        assert len(plans) == 4
        assert plans[0]["price_mxn"] == 8000


# ---------------------------------------------------------------------------
# Integración con el onboarding wizard (paso 5 -> checkout de Conekta)
# ---------------------------------------------------------------------------

class TestOnboardingBillingIntegration:
    def test_onboarding_checkout_redirect(self):
        from b2b_ai.features.onboarding.routes import build_onboarding_wizard_router
        from b2b_ai.features.onboarding.wizard import OnboardingWizard

        app = FastAPI()

        def fake_require_api_key():
            return {"tenant_id": "tenant_test_123", "api_key": "key"}

        app.include_router(
            build_onboarding_wizard_router(db=None, require_api_key=fake_require_api_key)
        )
        client = TestClient(app)

        # Completa el onboarding del piloto.
        w = OnboardingWizard()
        session = w.start()
        w.advance_step(session.session_id, "tenant", {
            "company_name": "ABC Contadores",
            "admin_name": "Juan",
            "admin_email": "juan@abc.mx",
        })
        w.advance_step(session.session_id, "fiscal", {
            "rfc": "GYA850101XYZ",
            "regimen_fiscal": "601",
            "codigo_postal": "06600",
        })
        w.advance_step(session.session_id, "data_source", {"source": "cfdi_upload"})
        w.advance_step(session.session_id, "test_cfdi", {
            "record": {"rfc": "GYA850101XYZ", "total": "1280.50"},
        })
        w.complete(session.session_id)

        r = client.post(
            f"/api/v1/onboarding-wizard/{session.session_id}/checkout",
            json={"plan": "pro"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["checkout_url"].startswith("https://checkout.conekta.com/")
        assert body["plan_code"] == "pro"
        assert body["amount_mxn"] == 20000
