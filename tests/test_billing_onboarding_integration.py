# -*- coding: utf-8 -*-
"""test_billing_onboarding_integration.py — Tests de la integración
billing (Conekta checkout) <-> onboarding wizard del piloto.

Cubre:
  - El paso 6 (checkout) en el flujo del wizard.
  - start_checkout() persiste la referencia de pago en la sesión.
  - BillingService.activate_pilot() y create_trial().
  - Endpoints API /api/v1/onboarding-wizard/{id}/checkout y .../callback.
  - La generación de datos de demo (seed.demo_data).

Nota: todos los proveedores de pago corren en modo MOCK (sin red ni API real).
"""
import os

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from b2b_ai.features.onboarding import models as onb_models
from b2b_ai.features.onboarding.wizard import (
    OnboardingWizard,
    OnboardingWizardError,
    _reset_state as reset_onboarding,
)
from b2b_ai.features.onboarding.routes import build_onboarding_wizard_router

from b2b_ai.features.billing import models as bill_store
from b2b_ai.features.billing.conekta_client import ConektaClient
from b2b_ai.features.billing.models import SubscriptionStatus
from b2b_ai.features.billing.service import BillingError, BillingService

from seed import demo_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    reset_onboarding()
    bill_store._reset_state()
    yield
    reset_onboarding()
    bill_store._reset_state()


@pytest.fixture
def client():
    """TestClient con el router del wizard de onboarding (auth stub)."""
    app = FastAPI()

    def fake_require_api_key():
        return {"tenant_id": "tenant_test_123", "api_key": "key"}

    app.include_router(
        build_onboarding_wizard_router(db=None, require_api_key=fake_require_api_key)
    )
    return TestClient(app)


@pytest.fixture
def wizard():
    return OnboardingWizard()


def _run_to_test_cfdi(wizard):
    """Avanza los 4 pasos de datos (tenant..test_cfdi)."""
    session = wizard.start()
    wizard.advance_step(session.session_id, "tenant", {
        "company_name": "Despacho Fides, S.C.",
        "admin_name": "Mariana Fernández",
        "admin_email": "mariana@fides.mx",
    })
    wizard.advance_step(session.session_id, "fiscal", {
        "rfc": "DCF920101AB1",
        "regimen_fiscal": "601",
        "codigo_postal": "06600",
    })
    wizard.advance_step(session.session_id, "data_source", {"source": "cfdi_upload"})
    wizard.advance_step(session.session_id, "test_cfdi", {
        "record": {"rfc": "DCF920101AB1", "total": "7818.61"},
    })
    return session


# ---------------------------------------------------------------------------
# Wizard: paso 6 checkout en el flujo
# ---------------------------------------------------------------------------

class TestWizardCheckoutStep:
    def test_checkout_is_step_6_in_order(self):
        assert onb_models.OnboardingStep.CHECKOUT.value == "checkout"
        assert [s.value for s in onb_models.STEP_ORDER][-2:] == ["checkout", "health_check"]

    def test_full_flow_includes_checkout(self, wizard):
        session = _run_to_test_cfdi(wizard)
        # El siguiente paso tras test_cfdi es checkout.
        assert session.current_step == "checkout"
        session = wizard.advance_step(session.session_id, "checkout", {"plan": "pro"})
        assert "checkout" in session.completed_steps
        ref = session.data["checkout"]
        assert ref["checkout_url"].startswith("https://checkout.conekta.com/")
        assert ref["plan"] == "pro"
        assert ref["status"] == "pending"
        assert ref["order_id"] and ref["customer_id"]

    def test_checkout_requires_valid_plan(self, wizard):
        session = _run_to_test_cfdi(wizard)
        with pytest.raises(OnboardingWizardError, match="plan inválido 'nope'"):
            wizard.advance_step(session.session_id, "checkout", {"plan": "nope"})

    def test_checkout_requires_plan(self, wizard):
        session = _run_to_test_cfdi(wizard)
        with pytest.raises(OnboardingWizardError, match="plan es obligatorio"):
            wizard.advance_step(session.session_id, "checkout", {})

    def test_health_check_reports_checkout(self, wizard):
        session = _run_to_test_cfdi(wizard)
        wizard.advance_step(session.session_id, "checkout", {"plan": "pro"})
        report = wizard.health_check(session.session_id)
        checkout_check = next(c for c in report["checks"] if c["step"] == "checkout")
        assert checkout_check["ok"] is True


# ---------------------------------------------------------------------------
# Wizard: start_checkout persiste la referencia
# ---------------------------------------------------------------------------

class TestStartCheckout:
    def test_persists_reference_in_session(self, wizard):
        session = _run_to_test_cfdi(wizard)
        ref = wizard.start_checkout(session.session_id, "starter")
        assert ref["checkout_url"].startswith("https://checkout.conekta.com/")
        assert session.data["checkout"]["plan"] == "starter"
        assert session.data["checkout"]["checkout_url"] == ref["checkout_url"]

    def test_requires_tenant(self, wizard):
        session = wizard.start()
        with pytest.raises(OnboardingWizardError, match="Debe completar primero"):
            wizard.start_checkout(session.session_id, "pro")

    def test_invalid_plan_raises(self, wizard):
        session = _run_to_test_cfdi(wizard)
        with pytest.raises(OnboardingWizardError, match="Plan inválido"):
            wizard.start_checkout(session.session_id, "ultra")

    def test_defaults_to_starter(self, wizard):
        session = _run_to_test_cfdi(wizard)
        ref = wizard.start_checkout(session.session_id, "pro")
        assert ref["amount_mxn"] == 20000
        assert ref["currency"] == "MXN"


# ---------------------------------------------------------------------------
# BillingService: activate_pilot y create_trial
# ---------------------------------------------------------------------------

class TestBillingServicePilot:
    def _service(self):
        return BillingService(client=ConektaClient(mock=True))

    def test_create_trial_30_days(self):
        svc = self._service()
        sub = svc.create_trial("tenant_trial")
        assert sub.status == SubscriptionStatus.TRIALING
        assert sub.plan_code.value == "starter"
        assert sub.metadata.get("trial_days") == 30

    def test_activate_pilot_creates_active_subscription(self):
        svc = self._service()
        sub = svc.activate_pilot("tenant_pilot", "business", payment_method_id="pm_123")
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.plan_code.value == "business"
        assert sub.price_mxn == 40000
        assert sub.provider_customer_id
        assert sub.provider_subscription_id
        # Se registró el medio de pago.
        pms = bill_store.get_payment_methods("tenant_pilot")
        assert len(pms) == 1
        assert pms[0].provider_payment_method_id == "pm_123"
        # Se emitió la primera factura pagada.
        invoices = svc.get_invoice_history("tenant_pilot")
        assert len(invoices) == 1
        assert invoices[0]["amount_mxn"] == 40000

    def test_activate_pilot_invalid_plan(self):
        svc = self._service()
        with pytest.raises(BillingError, match="Plan inválido"):
            svc.activate_pilot("tenant_x", "no-plan")

    def test_activate_pilot_duplicate_rejected(self):
        svc = self._service()
        svc.activate_pilot("tenant_dup", "starter")
        with pytest.raises(BillingError, match="ya tiene una suscripción"):
            svc.activate_pilot("tenant_dup", "pro")


# ---------------------------------------------------------------------------
# API: checkout y callback
# ---------------------------------------------------------------------------

class TestCheckoutAPI:
    def test_checkout_endpoint_returns_url(self, client, wizard):
        session = _run_to_test_cfdi(wizard)
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
        assert body["currency"] == "MXN"

    def test_checkout_endpoint_invalid_plan(self, client, wizard):
        session = _run_to_test_cfdi(wizard)
        r = client.post(
            f"/api/v1/onboarding-wizard/{session.session_id}/checkout",
            json={"plan": "nope"},
        )
        assert r.status_code == 400

    def test_checkout_endpoint_unknown_session(self, client):
        r = client.post(
            "/api/v1/onboarding-wizard/no-such-session/checkout",
            json={"plan": "pro"},
        )
        assert r.status_code in (400, 404)

    def test_callback_paid_activates_subscription(self, client, wizard):
        session = _run_to_test_cfdi(wizard)
        # Se inicia el checkout para tener tenant + plan persistido.
        client.post(f"/api/v1/onboarding-wizard/{session.session_id}/checkout",
                    json={"plan": "starter"})
        r = client.post(
            f"/api/v1/onboarding-wizard/{session.session_id}/checkout/callback",
            json={"status": "paid", "plan": "starter", "payment_method_id": "pm_abc"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["status"] == "paid"
        assert body["subscription"]["plan_code"] == "starter"
        assert body["subscription"]["status"] == "active"

    def test_callback_failed_no_subscription(self, client, wizard):
        session = _run_to_test_cfdi(wizard)
        r = client.post(
            f"/api/v1/onboarding-wizard/{session.session_id}/checkout/callback",
            json={"status": "failed", "plan": "pro"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert r.json()["subscription"] is None


# ---------------------------------------------------------------------------
# Seed data de demo
# ---------------------------------------------------------------------------

class TestSeedDemoData:
    def test_despacho_generated(self):
        d = demo_data.generate_despacho()
        assert d["name"] == "Despacho Contable Fides, S.C."
        assert d["rfc"] == "DCF920101AB1"
        assert d["regimen_fiscal"] == "601"

    def test_generate_cfdis_count_and_shape(self):
        cfdis = demo_data.generate_cfdis(50)
        assert len(cfdis) == 50
        first = cfdis[0]
        for k in ("uuid", "emisor_rfc", "receptor_rfc", "subtotal", "iva", "total", "moneda"):
            assert first.get(k) is not None
        # Montos MXN realistas: total = subtotal + IVA 16%.
        for c in cfdis:
            assert abs((c["subtotal"] + c["iva"]) - c["total"]) < 0.01
            assert c["moneda"] == "MXN"
            assert c["total"] > 0

    def test_generate_bank_transactions_count(self):
        txs = demo_data.generate_bank_transactions(20)
        assert len(txs) == 20
        for t in txs:
            assert t["banco"] in {"BBVA", "Banorte", "Santander", "HSBC", "Banamex", "Scotiabank"}
            assert t["tipo"] in {"deposito", "retiro"}
            assert t["monto_mxn"] > 0

    def test_build_dataset_counts(self):
        ds = demo_data.build_dataset(cfdis=50, txs=20)
        assert ds["counts"] == {"despachos": 1, "cfdis": 50, "bank_transactions": 20}
        assert len(ds["cfdis"]) == 50
        assert len(ds["bank_transactions"]) == 20

    def test_persist_json_writes_files(self, tmp_path):
        ds = demo_data.build_dataset(cfdis=3, txs=2)
        paths = demo_data._persist_json(ds, str(tmp_path))
        assert len(paths) == 3
        for p in paths:
            assert os.path.exists(p)
        assert os.path.exists(os.path.join(tmp_path, "manifest.json"))
