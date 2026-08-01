# -*- coding: utf-8 -*-
"""
Tests del subsistema de cobros (billing): Stripe + Conekta.

Cubre: precios/planes, validación de modelos, proveedores en modo mock
(tarjeta / SPEI / OXXO), endpoints de la API (/api/v1/billing/*) y el
aislamiento multi-tenant de las facturas.

Todos los proveedores se testean en modo mock (sin red, sin API keys):
B2B_PAYMENTS_MOCK se fuerza a 1 vía monkeypatch para que el router de la
API use el MockPaymentProvider por defecto.
"""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.billing.pricing import (
    get_plan, list_plans, exceeds_cfdi_limit, PLANS,
)
from b2b_ai.billing.models import (
    Customer, PaymentMethodType, Provider, SubscriptionStatus,
)
from b2b_ai.billing.base import MockPaymentProvider, PaymentError
from b2b_ai.billing.stripe_provider import StripeProvider
from b2b_ai.billing.conekta_provider import ConektaProvider

API_KEY = "billing-test-key-123"


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    """Fuerza modo mock para que la API use el provider sin red."""
    monkeypatch.setenv("B2B_PAYMENTS_MOCK", "1")


@pytest.fixture
def client(tmp_path, _force_mock):
    db = Database(str(tmp_path / "billing.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_tenant("Despacho B", rfc="XAXX020202000")
    db.create_api_key(1, "k1", API_KEY)
    db.create_api_key(2, "k2", "tenant2-key")
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": API_KEY}


def _auth2():
    return {"X-API-Key": "tenant2-key"}


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def test_planes_precios():
    plans = {p["key"]: p for p in list_plans()}
    assert plans["starter"]["price_mxn"] == 4999.0
    assert plans["starter"]["cfdi_limit"] == 500
    assert plans["growth"]["price_mxn"] == 9999.0
    assert plans["growth"]["cfdi_limit"] == 2000
    assert plans["enterprise"]["cfdi_limit"] is None


def test_limites_cfdi():
    assert exceeds_cfdi_limit("starter", 501) is True
    assert exceeds_cfdi_limit("starter", 500) is False
    assert exceeds_cfdi_limit("growth", 2000) is False
    assert exceeds_cfdi_limit("enterprise", 999999) is False
    assert exceeds_cfdi_limit("no_existe", 10) is False


def test_get_plan_invalido():
    assert get_plan("nope") is None


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
def test_customer_email_validacion():
    c = Customer(email="a@b.com", name="Ana")
    assert c.email == "a@b.com"
    with pytest.raises(ValidationError):
        Customer(email="malo", name="Ana")


def test_provider_enum():
    assert Provider.STRIPE.value == "stripe"
    assert Provider.CONEKTA.value == "conekta"


# ---------------------------------------------------------------------------
# Proveedores (modo mock)
# ---------------------------------------------------------------------------
def test_mock_provider_contrato():
    p = MockPaymentProvider()
    c = p.create_customer("a@b.com", "Ana")
    assert c.provider_customer_id.startswith("customer_")
    sub = p.create_subscription(c.provider_customer_id, "growth")
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.provider_subscription_id.startswith("subscription_")
    inv = p.create_invoice(c.provider_customer_id, 9999)
    assert inv.amount == 9999.0
    res = p.process_payment("pm_1", 100)
    assert res.ok is True and res.status == "succeeded"
    wh = p.webhook_handler("invoice.paid", {"data": {"object": {"id": "inv_1"}}})
    assert wh["handled"] is True


def test_stripe_mock_ids():
    p = StripeProvider(mock=True)
    c = p.create_customer("a@b.com", "Ana")
    assert c.provider == Provider.STRIPE
    assert c.provider_customer_id.startswith("customer_")


def test_stripe_sin_key_real_lanza():
    """En modo real sin B2B_STRIPE_KEY debe fallar con error claro, no red."""
    p = StripeProvider(mock=False, api_key="")
    with pytest.raises(PaymentError) as exc:
        p.create_customer("a@b.com", "Ana")
    assert "B2B_STRIPE_KEY" in str(exc.value)
    assert exc.value.code == "missing_api_key"


def test_conekta_spei_oxxo_card():
    p = ConektaProvider(mock=True)
    # SPEI → pending_payment + instrucciones con CLABE
    spei = p.process_payment("cus_1", 4999, method=PaymentMethodType.SPEI)
    assert spei.status == "pending_payment"
    assert spei.payment_instructions["type"] == "spei"
    assert spei.payment_instructions["clabe"]
    # OXXO → referencia de barcode
    oxxo = p.process_payment("cus_1", 4999, method=PaymentMethodType.OXXO)
    assert oxxo.payment_instructions["type"] == "oxxo"
    assert oxxo.payment_instructions["reference"]
    # Tarjeta → succeeded
    card = p.process_payment("cus_1", 4999, method=PaymentMethodType.CARD)
    assert card.status == "succeeded"
    assert card.payment_method_type == PaymentMethodType.CARD


def test_conekta_metodos_soportados():
    p = ConektaProvider(mock=True)
    # Los tres métodos MX se aceptan sin lanzar error.
    for m in (PaymentMethodType.CARD, PaymentMethodType.SPEI,
              PaymentMethodType.OXXO):
        p._validate_method(m)  # noqa: SLF001 — no debe lanzar
    # Un método ajeno a Conekta (tipo inválido inexistente) sí lanza.
    with pytest.raises(PaymentError):
        p._validate_method("bitcoin")  # type: ignore[arg-type]


def test_conekta_webhook_charge_paid():
    p = ConektaProvider(mock=True)
    res = p.webhook_handler("charge.paid",
                            {"data": {"object": {"id": "ord_1", "status": "paid"}}})
    assert res["handled"] is True and res["mark_paid"] is True


def test_conekta_sin_key_real_lanza():
    p = ConektaProvider(mock=False, api_key="")
    with pytest.raises(PaymentError) as exc:
        p.create_customer("a@b.com", "Ana")
    assert "B2B_CONEKTA_KEY" in str(exc.value)


# ---------------------------------------------------------------------------
# API — auth
# ---------------------------------------------------------------------------
def test_billing_sin_key_rechaza(client):
    c, _ = client
    assert c.get("/api/v1/billing/invoices").status_code == 401
    assert c.post("/api/v1/billing/checkout", json={}).status_code == 401
    assert c.post("/api/v1/billing/webhook", json={}).status_code == 401


# ---------------------------------------------------------------------------
# API — checkout
# ---------------------------------------------------------------------------
def test_checkout_crea_factura(client):
    c, db = client
    r = c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "cliente@despacho.mx", "name": "Cliente Demo",
        "plan": "growth"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["payment"]["status"] == "succeeded"
    assert body["plan"]["price_mxn"] == 9999.0
    invs = db.list_billing_invoices(tenant_id=1)
    assert len(invs) == 1
    assert invs[0]["amount"] == 9999.0
    assert invs[0]["email"] == "cliente@despacho.mx"


def test_checkout_plan_invalido(client):
    c, _ = client
    r = c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "a@b.com", "name": "X", "plan": "enterprise"})
    assert r.status_code == 400  # enterprise requiere cotización


def test_checkout_email_invalido(client):
    c, _ = client
    r = c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "no-es-email", "name": "X", "plan": "growth"})
    assert r.status_code == 422


def test_checkout_reusa_cliente_existente(client):
    c, db = client
    email = "reusa@despacho.mx"
    for _ in range(2):
        r = c.post("/api/v1/billing/checkout", headers=_auth(), json={
            "email": email, "name": "Reuso", "plan": "starter"})
        assert r.status_code == 200
    customers = db.conn.execute(
        "SELECT COUNT(*) FROM billing_customers WHERE email=?",
        (email,)).fetchone()[0]
    assert customers == 1  # no duplica cliente


# ---------------------------------------------------------------------------
# API — subscription
# ---------------------------------------------------------------------------
def test_subscription_crea_suscripcion(client):
    c, db = client
    r = c.post("/api/v1/billing/subscription", headers=_auth(), json={
        "email": "sub@despacho.mx", "name": "Suscrip", "plan": "starter"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "active"
    subs = db.list_billing_subscriptions(tenant_id=1)
    assert len(subs) == 1
    assert subs[0]["plan"] == "starter"


def test_subscription_plan_invalido(client):
    c, _ = client
    r = c.post("/api/v1/billing/subscription", headers=_auth(), json={
        "email": "a@b.com", "name": "X", "plan": "noexiste"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# API — invoices
# ---------------------------------------------------------------------------
def test_list_invoices_vacio_y_poblado(client):
    c, db = client
    r = c.get("/api/v1/billing/invoices", headers=_auth())
    assert r.status_code == 200
    assert r.json()["count"] == 0
    c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "a@despacho.mx", "name": "A", "plan": "starter"})
    r = c.get("/api/v1/billing/invoices", headers=_auth())
    assert r.json()["count"] == 1


def test_invoices_aislamiento_entre_tenants(client):
    """Tenant 2 no ve las facturas del tenant 1."""
    c, db = client
    c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "t1@despacho.mx", "name": "T1", "plan": "growth"})
    r1 = c.get("/api/v1/billing/invoices", headers=_auth())
    assert r1.json()["count"] == 1
    r2 = c.get("/api/v1/billing/invoices", headers=_auth2())
    assert r2.json()["count"] == 0


# ---------------------------------------------------------------------------
# API — webhook
# ---------------------------------------------------------------------------
def test_webhook_marca_factura_pagada(client):
    c, db = client
    c.post("/api/v1/billing/checkout", headers=_auth(), json={
        "email": "wh@despacho.mx", "name": "WH", "plan": "growth"})
    inv = db.list_billing_invoices(tenant_id=1)[0]
    ref = inv["provider_invoice_id"]
    assert inv["status"] == "succeeded"
    # marcamos como paid vía webhook (estatus de pago independiente del cobro)
    ok = db.mark_billing_invoice_paid_by_ref(ref, "stripe")
    assert ok is True
    db2 = db.list_billing_invoices(tenant_id=1)[0]
    assert db2["status"] == "paid"
    assert db2["paid_at"] is not None


def test_webhook_endpoint_procesa_evento(client):
    c, db = client
    r = c.post("/api/v1/billing/webhook", headers=_auth(), json={
        "provider": "conekta", "event_type": "charge.paid",
        "data": {"data": {"object": {"id": "ord_1"}}}})
    assert r.status_code == 200
    body = r.json()
    assert body["received"] is True
    assert body["result"]["handled"] is True


# ---------------------------------------------------------------------------
# API — plans
# ---------------------------------------------------------------------------
def test_plans_endpoint(client):
    c, _ = client
    r = c.get("/api/v1/billing/plans", headers=_auth())
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()["plans"]}
    assert {"starter", "growth", "enterprise"} <= keys
