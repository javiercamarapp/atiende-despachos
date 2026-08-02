# -*- coding: utf-8 -*-
"""test_onboarding_fixes.py — Tests de los fixes P1 del módulo onboarding.

Cubre los 3 hallazgos de QA (deliverable 206) que bloqueaban el piloto:

  P1-1: Tenant spoofing en `start` (routes.py)
        El tenant ya NO se toma del body; se deriva del auth. Si el body
        intenta spoofear otro tenant -> 403.

  P1-2: Aislamiento por tenant en acceso a sesiones (routes.py)
        get_state / advance / complete / checkout / checkout_callback rechazan
        con 404 cualquier sesión que no pertenezca al tenant autenticado.

  P1-3: No se puede completar sin checkout (wizard.py)
        `complete()` exige que el paso checkout esté completado (progress>=5).
        Si falta checkout devuelve error con el paso faltante.

Se construye el router con un auth stub que devuelve el MISMO contrato que el
auth real (`make_require_api_key`): un dict con `tenant_id`. Se varía el tenant
del stub para probar el aislamiento entre tenants.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.onboarding import models as onb_models
from b2b_ai.features.onboarding.wizard import (
    OnboardingWizard,
    OnboardingWizardError,
    _reset_state as reset_onboarding,
)
from b2b_ai.features.onboarding.routes import build_onboarding_wizard_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    reset_onboarding()
    yield
    reset_onboarding()


@pytest.fixture
def auth_tenant():
    """Holder mutable para el tenant que devuelve el stub de auth."""
    return {"tenant_id": "tenant_A"}


@pytest.fixture
def client(auth_tenant):
    """TestClient con el router del wizard y un auth stub configurable."""
    app = FastAPI()

    def fake_require_api_key():
        return {"tenant_id": auth_tenant["tenant_id"], "api_key": "stub-key"}

    app.include_router(
        build_onboarding_wizard_router(db=None, require_api_key=fake_require_api_key)
    )
    return TestClient(app)


@pytest.fixture
def wizard():
    return OnboardingWizard()


# ---------------------------------------------------------------------------
# Helpers de flujo
# ---------------------------------------------------------------------------

def _run_to_checkout(wizard, session_id):
    """Avanza los pasos 1..4 (tenant..test_cfdi) sobre una sesión ya creada."""
    wizard.advance_step(session_id, "tenant", {
        "company_name": "Despacho Fides, S.C.",
        "admin_name": "Mariana Fernández",
        "admin_email": "mariana@fides.mx",
    })
    wizard.advance_step(session_id, "fiscal", {
        "rfc": "DCF920101AB1",
        "regimen_fiscal": "601",
        "codigo_postal": "06600",
    })
    wizard.advance_step(session_id, "data_source", {"source": "cfdi_upload"})
    wizard.advance_step(session_id, "test_cfdi", {
        "record": {"rfc": "DCF920101AB1", "total": "7818.61"},
    })


def _start_session(client):
    """Crea una sesión vía el endpoint (usa el tenant del auth)."""
    r = client.post("/api/v1/onboarding-wizard/start")
    assert r.status_code == 200
    return r.json()["session"]["session_id"]


# ---------------------------------------------------------------------------
# P1-1: Tenant spoofing en start
# ---------------------------------------------------------------------------

class TestP1TenantSpoofing:
    def test_start_usa_tenant_del_auth(self, client, auth_tenant, wizard):
        """El tenant de la sesión sale del auth, no del body.

        El body solo se acepta si coincide con el tenant autenticado; si
        intenta spoofear otro tenant se rechaza (403). Así, el tenant SIEMPRE
        se deriva de la API key.
        """
        # Un body con otro tenant (spoofing) se rechaza: el auth manda.
        r = client.post(
            "/api/v1/onboarding-wizard/start",
            json={"tenant_id": "algun_otro_tenant"},
        )
        assert r.status_code == 403
        # Con el body alineado al auth, la sesión hereda el tenant autenticado.
        r = client.post(
            "/api/v1/onboarding-wizard/start",
            json={"tenant_id": auth_tenant["tenant_id"]},
        )
        assert r.status_code == 200
        assert r.json()["session"]["tenant_id"] == auth_tenant["tenant_id"]

    def test_start_acepta_tenant_igual_al_auth(self, client, auth_tenant):
        """Si el body coincide con el tenant autenticado, es válido."""
        r = client.post(
            "/api/v1/onboarding-wizard/start",
            json={"tenant_id": auth_tenant["tenant_id"]},
        )
        assert r.status_code == 200

    def test_start_rechaza_spoofing_de_otro_tenant(self, client):
        """Si el body difiere del tenant autenticado -> 403."""
        r = client.post(
            "/api/v1/onboarding-wizard/start",
            json={"tenant_id": "tenant_MALO"},
        )
        assert r.status_code == 403

    def test_start_sin_tenant_en_body_ok(self, client):
        """Sin tenant en el body, se usa el del auth."""
        r = client.post("/api/v1/onboarding-wizard/start")
        assert r.status_code == 200
        assert r.json()["session"]["tenant_id"] == "tenant_A"


# ---------------------------------------------------------------------------
# P1-2: Aislamiento por tenant
# ---------------------------------------------------------------------------

class TestP2SessionIsolation:
    def _make_session_for_tenant(self, client, auth_tenant, tenant):
        """Crea una sesión bajo un tenant específico."""
        auth_tenant["tenant_id"] = tenant
        return _start_session(client)

    def test_get_state_sesion_ajena_rechaza(self, client, auth_tenant, wizard):
        """Un tenant NO puede leer la sesión de otro tenant (404)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        # Cambiamos de tenant: el auth ahora es tenant_B.
        auth_tenant["tenant_id"] = "tenant_B"
        r = client.get(f"/api/v1/onboarding-wizard/{sid}")
        assert r.status_code == 404

    def test_get_state_sesion_propia_ok(self, client, auth_tenant):
        """El dueño sí lee su sesión (200)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        r = client.get(f"/api/v1/onboarding-wizard/{sid}")
        assert r.status_code == 200
        assert r.json()["session"]["tenant_id"] == "tenant_A"

    def test_advance_sesion_ajena_rechaza(self, client, auth_tenant, wizard):
        """Un tenant NO puede avanzar la sesión de otro (404)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        auth_tenant["tenant_id"] = "tenant_B"
        r = client.post(
            f"/api/v1/onboarding-wizard/{sid}/step/tenant",
            json={"payload": {"company_name": "X", "admin_name": "Y",
                              "admin_email": "y@x.mx"}},
        )
        assert r.status_code == 404

    def test_complete_sesion_ajena_rechaza(self, client, auth_tenant, wizard):
        """Un tenant NO puede completar la sesión de otro (404)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        auth_tenant["tenant_id"] = "tenant_B"
        r = client.post(f"/api/v1/onboarding-wizard/{sid}/complete")
        assert r.status_code == 404

    def test_checkout_sesion_ajena_rechaza(self, client, auth_tenant, wizard):
        """Un tenant NO puede iniciar checkout de la sesión de otro (404)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        auth_tenant["tenant_id"] = "tenant_B"
        r = client.post(
            f"/api/v1/onboarding-wizard/{sid}/checkout",
            json={"plan": "pro"},
        )
        assert r.status_code == 404

    def test_callback_sesion_ajena_rechaza(self, client, auth_tenant, wizard):
        """Un tenant NO puede procesar el callback de la sesión de otro (404)."""
        sid = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        auth_tenant["tenant_id"] = "tenant_B"
        r = client.post(
            f"/api/v1/onboarding-wizard/{sid}/checkout/callback",
            json={"status": "paid", "plan": "pro"},
        )
        assert r.status_code == 404

    def test_dos_tenants_conversan_aislados(self, client, auth_tenant, wizard):
        """Cada tenant ve SOLO sus sesiones; no hay fuga entre ambos."""
        sid_a = self._make_session_for_tenant(client, auth_tenant, "tenant_A")
        auth_tenant["tenant_id"] = "tenant_B"
        sid_b = self._make_session_for_tenant(client, auth_tenant, "tenant_B")

        # tenant_B ve su sesión...
        assert client.get(f"/api/v1/onboarding-wizard/{sid_b}").status_code == 200
        # ...pero NO la de tenant_A.
        assert client.get(f"/api/v1/onboarding-wizard/{sid_a}").status_code == 404

        # tenant_A recupera la suya al volver.
        auth_tenant["tenant_id"] = "tenant_A"
        assert client.get(f"/api/v1/onboarding-wizard/{sid_a}").status_code == 200
        assert client.get(f"/api/v1/onboarding-wizard/{sid_b}").status_code == 404


# ---------------------------------------------------------------------------
# P1-3: No se puede completar sin checkout
# ---------------------------------------------------------------------------

class TestP3CheckoutRequired:
    def test_complete_sin_checkout_rechaza(self, wizard):
        """completa con los 4 primeros pasos pero sin checkout -> error."""
        session = wizard.start(tenant_id="tenant_A")
        _run_to_checkout(wizard, session.session_id)
        # Aún no se avanzó checkout ni health_check.
        assert session.progress == 4
        with pytest.raises(OnboardingWizardError, match="checkout"):
            wizard.complete(session.session_id)
        # La sesión sigue sin completarse.
        assert session.is_complete is False

    def test_complete_con_checkout_ok(self, wizard):
        """Con checkout completado, complete() cierra el onboarding."""
        session = wizard.start(tenant_id="tenant_A")
        _run_to_checkout(wizard, session.session_id)
        wizard.advance_step(session.session_id, "checkout", {"plan": "pro"})
        assert session.progress == 5
        result = wizard.complete(session.session_id)
        assert result["ok"] is True
        assert result["session"]["status"] == "completed"
        assert session.is_complete is True

    def test_complete_sin_ningun_paso_rechaza(self, wizard):
        """completa sin pasos -> error con paso faltante (checkout)."""
        session = wizard.start(tenant_id="tenant_A")
        with pytest.raises(OnboardingWizardError, match="checkout"):
            wizard.complete(session.session_id)

    def test_complete_exige_progress_5(self, wizard):
        """El mensaje refleja el progreso y que falta checkout."""
        session = wizard.start(tenant_id="tenant_A")
        _run_to_checkout(wizard, session.session_id)
        with pytest.raises(OnboardingWizardError, match="Progreso 4/6"):
            wizard.complete(session.session_id)

    def test_api_complete_sin_checkout_422(self, client, auth_tenant, wizard):
        """El endpoint /complete devuelve 422 si falta el checkout."""
        sid = _start_session(client)
        _run_to_checkout(wizard, sid)
        r = client.post(f"/api/v1/onboarding-wizard/{sid}/complete")
        assert r.status_code == 422
        assert "checkout" in r.json()["detail"]

    def test_api_flujo_completo_con_checkout_ok(self, client, auth_tenant, wizard,
                                               monkeypatch):
        """Flujo completo por API: checkout completado -> complete() 200."""
        monkeypatch.setenv("B2B_PAYMENTS_MOCK", "1")
        sid = _start_session(client)
        _run_to_checkout(wizard, sid)
        r = client.post(f"/api/v1/onboarding-wizard/{sid}/step/checkout",
                        json={"payload": {"plan": "pro"}})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/v1/onboarding-wizard/{sid}/complete")
        assert r.status_code == 200, r.text
        assert r.json()["session"]["status"] == "completed"
