# -*- coding: utf-8 -*-
import os
import resource
import sys
import tempfile

import pytest

# macOS: raise file-descriptor limit so 800+ SQLite connections don't exhaust
# the default ulimit (256).  Safe to call on Linux too (no-op if already ≥ 10240).
try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (10240, 10240))
except (ValueError, OSError):
    pass  # already higher or unprivileged container — ignore

# Ensure a JWT secret is available for tests that exercise auth middleware.
# The production code reads B2B_JWT_SECRET from the environment; in tests we
# supply a deterministic value so nothing falls through to the (now removed)
# hardcoded dev secret.
os.environ.setdefault("B2B_JWT_SECRET", "test-jwt-secret-safe-for-ci-only")
os.environ.setdefault("B2B_ENV", "test")

# Asegurar que el paquete b2b_ai sea importable (root = directorio con el paquete)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")


def fixture_path(name):
    return os.path.join(FIXTURES, name)


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    """Reset the portal login rate limiter between tests to avoid 429 collisions."""
    from b2b_ai.portal.routes import _login_limiter
    _login_limiter.reset()
    yield
    _login_limiter.reset()


@pytest.fixture(autouse=True)
def _ingesta_local_habilitada(monkeypatch, tmp_path_factory):
    """Habilita la ingesta por ruta local para toda la suite.

    `xml_path` / `folder` dejan que el cliente elija una ruta DEL SERVIDOR, así
    que ahora son opt-in y están confinadas a `B2B_LOCAL_XML_DIRS` (ver
    `_resolve_local_path` en api/app.py). Sin esta variable la API responde 400.

    Las pruebas que usan `xml_path` representan un despliegue que SÍ habilitó la
    ingesta local, así que se apuntan los dos directorios de los que leen: las
    fixtures del repo y la raíz de los temporales de pytest. Que el confinamiento
    funcione lo cubre `tests/test_ingesta_local.py`, que limpia esta variable a
    propósito.
    """
    roots = os.pathsep.join([FIXTURES, ROOT,
                             str(tmp_path_factory.getbasetemp()),
                             tempfile.gettempdir()])
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", roots)
    # `B2B_ENV` sin definir cuenta como PRODUCCIÓN (ver auth/middleware.py), y
    # en producción la ausencia de B2B_JWT_SECRET aborta el arranque. La suite
    # se declara entorno de test para tomar el secreto efímero por proceso.
    monkeypatch.setenv("B2B_ENV", "test")


@pytest.fixture
def fixture_dir():
    return FIXTURES


@pytest.fixture
def sample_papeleria():
    return fixture_path("01_gasto_operativo_papeleria.xml")


@pytest.fixture
def sample_consultoria():
    return fixture_path("02_inversion_consultoria.xml")


@pytest.fixture
def sample_nomina():
    return fixture_path("04_nomina_pago.xml")


@pytest.fixture
def sample_honorarios():
    return fixture_path("06_honorarios_retenciones.xml")


@pytest.fixture
def sample_pago():
    return fixture_path("07_pago_parcialidad.xml")


@pytest.fixture
def tmp_db(tmp_path):
    """Devuelve una Database en un archivo temporal."""
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def parsed_consultoria(sample_consultoria):
    from b2b_ai.cfdi.parser import parse_cfdi
    return parse_cfdi(sample_consultoria)

# ---------------------------------------------------------------------------
# Enterprise hardening fixtures (from conftest_enterprise.py)
# ---------------------------------------------------------------------------
import secrets

@pytest.fixture
def db_session(tmp_path):
    """Fresh SQLite database per test, fully migrated."""
    from b2b_ai.db.db import Database
    db_path = str(tmp_path / "test_enterprise.db")
    db = Database(db_path)
    yield db
    try:
        db.close()
    except Exception:
        pass

@pytest.fixture
def tenant_context():
    """Simulated tenant context."""
    return {
        "tenant_id": 1,
        "name": "Test Despacho",
        "rfc": "TDE220101AB1",
    }

@pytest.fixture
def api_key():
    return "test-api-key-enterprise-12345678"

@pytest.fixture
def auth_headers(api_key):
    return {"X-API-Key": api_key}

@pytest.fixture
def jwt_token():
    from b2b_ai.auth.middleware import encode_token
    return encode_token(
        {"type": "access", "sub": "1", "tenant_id": 1,
         "role": "admin", "email": "test@test.com",
         "jti": secrets.token_urlsafe(16)},
        ttl_seconds=3600,
    )

@pytest.fixture
def jwt_headers(jwt_token):
    return {"Authorization": f"Bearer {jwt_token}"}


# ---------------------------------------------------------------------------
# Fixtures compartidas del E2E del piloto (Leonardo, t_1b328fae)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tenant():
    """Tenant (despacho contable) de referencia para el flujo del piloto.

    Reutiliza el shape de `seed.demo_data.generate_despacho()` para que los
    tests E2E validen contra datos realistas (RFC, régimen, CP).
    """
    from seed import demo_data
    return demo_data.generate_despacho()


@pytest.fixture
def mock_cfdi_data(mock_tenant):
    """Lista de CFDIs de muestra (receptor = despacho del tenant).

    Reutiliza `demo_data.generate_cfdis()` para reproducibilidad (seed fijo)
    y para que el test de categorización tenga varios emisores/categorías.
    """
    from seed import demo_data
    return demo_data.generate_cfdis(n=8, despacho_rfc=mock_tenant["rfc"])


@pytest.fixture
def mock_bank_transactions():
    """Transacciones bancarias de muestra para conciliación."""
    from seed import demo_data
    return demo_data.generate_bank_transactions(n=6)


@pytest.fixture
def mock_conekta_responses():
    """Respuestas Mock del cliente de Conekta.

    Shape fiel a `features/billing` (service + conekta_client en modo mock):
      - checkout: URL real de checkout.conekta.com + order/customer ids.
      - subscription: suscripción activa (plan_code, status, price_mxn).
    Permite testear billing sin red ni credenciales.
    """
    return {
        "checkout": {
            "ok": True,
            "checkout_url": "https://checkout.conekta.com/pay/order_test_123",
            "order_id": "order_test_123",
            "customer_id": "cus_test_456",
            "plan": "pro",
            "amount_mxn": 20000,
            "currency": "MXN",
        },
        "subscription": {
            "ok": True,
            "plan_code": "pro",
            "status": "active",
            "price_mxn": 20000,
            "currency": "MXN",
            "provider_subscription_id": "sub_test_789",
        },
        "webhook_paid": {
            "type": "order.paid",
            "data": {"order": {"id": "order_test_123"}},
        },
    }


@pytest.fixture
def pilot_client():
    """TestClient con los routers del piloto (auth stub → tenant_id).

    Patrón del repo (test_billing_onboarding_integration.py): se montan los
    routers de onboarding-wizard, billing-piloto, batch, bank-feeds y reports
    con una dependencia de auth que devuelve un dict con tenant_id, de modo
    que los endpoints que hacen `auth_info.get("tenant_id")` funcionen.

    NOTA: NO se usa create_app() completo para aislar el E2E del overhead de
    toda la app (rate limit, audit, JWT). Los tests de contrato API cubren
    create_app() por separado.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from b2b_ai.features.onboarding.routes import build_onboarding_wizard_router
    from b2b_ai.features.billing.routes import (
        build_billing_router as build_pilot_billing_router,
    )
    from b2b_ai.features.batch.routes import build_batch_router
    from b2b_ai.features.bank_feeds.routes import build_bank_feeds_router
    from b2b_ai.reports.router import build_reports_router

    def fake_require_api_key():
        return {"tenant_id": "tenant_test_123", "api_key": "key"}

    app = FastAPI()
    app.include_router(build_onboarding_wizard_router(
        db=None, require_api_key=fake_require_api_key))
    app.include_router(build_pilot_billing_router(
        db=None, require_api_key=fake_require_api_key))
    app.include_router(build_batch_router(
        db=None, require_api_key=fake_require_api_key))
    app.include_router(build_bank_feeds_router(
        db=None, require_api_key=fake_require_api_key))
    app.include_router(build_reports_router(
        db=None, require_api_key=fake_require_api_key))
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_pilot_state():
    """Limpia el estado en memoria de onboarding/billing entre tests."""
    from b2b_ai.features.onboarding.wizard import _reset_state as reset_onb
    from b2b_ai.features.billing.models import _reset_state as reset_bill
    reset_onb()
    reset_bill()
    yield
    reset_onb()
    reset_bill()
