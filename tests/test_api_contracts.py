# -*- coding: utf-8 -*-
"""test_api_contracts.py — Tests de contratos de la API.

Valida que los endpoints:
  1. Existen y responden (no 404).
  2. Devuelven formatos JSON consistentes con los schemas declarados.
  3. Aplican autenticación (X-API-Key) en endpoints protegidos.
  4. Aplican rate limiting (429 + Retry-After).

Estrategia:
  - Los contratos de ruta/schema se validan contra un puñado de routers
    reales montados a mano con un auth-stub que devuelve dict (fixture
    `pilot_client` del conftest: batch, bank-feeds, reports).
  - El contrato de AUTENTICACIÓN se valida contra `make_require_api_key` real
    de `b2b_ai.api.auth`, aislado en una mini-app, para probar 422/401.
  - El rate limiting se prueba de forma aislada (limiter en memoria).

NOTA (consolidación de billing, fix/billing-consolidacion): este archivo
probaba también onboarding-wizard y billing-piloto
(`b2b_ai.features.onboarding` / `b2b_ai.features.billing`). Ambos se
eliminaron — nunca estuvieron montados en `create_app()` y el billing piloto
tenía un bypass real de firma de webhook. Ver la nota en `TestEndpointsExist`
para el contrato real que los reemplaza.

HALLAZGO QA (bug de producción, no de estos tests): `make_require_api_key()` en
`b2b_ai/api/auth.py` (1) expone la key como query param "key" en vez de leer el
header X-API-Key, y (2) devuelve el STRING de la key mientras algunos routers
de `features/` hacen `auth_info.get("tenant_id")` esperando un dict. Requiere
fix de Zuck; los tests de auth de abajo lo documentan y las suites de
contrato usan el auth-stub para no depender de él.
"""
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


@pytest.fixture
def api_key():
    return "contract-test-key-123456"


# ---------------------------------------------------------------------------
# 1. Existencia de endpoints y status codes (auth-stub → dict)
# ---------------------------------------------------------------------------

class TestEndpointsExist:
    """Los endpoints del flujo piloto deben existir (no 404 con auth ok)."""

    # NOTA (consolidación de billing, fix/billing-consolidacion):
    # test_onboarding_wizard_endpoints, test_billing_piloto_plans y
    # test_billing_piloto_checkout_contract probaban rutas de
    # `b2b_ai.features.onboarding` / `b2b_ai.features.billing` (el módulo
    # "piloto", eliminado). Esas rutas nunca existieron en `create_app()`
    # (no eran contrato de producción, solo de esta app de test aislada), y
    # el billing piloto tenía un bypass real de firma de webhook. El
    # contrato real de billing/onboarding en producción está cubierto por
    # tests/test_billing.py, tests/test_conekta_gateway.py,
    # tests/test_webhook_receiver.py (b2b_ai.billing) y
    # tests/test_onboarding_wizard.py (b2b_ai.onboarding).

    def test_batch_endpoints(self, pilot_client):
        # Ruta de consulta existe → 404 para id inexistente (no 405/404 de ruta).
        r = pilot_client.get("/api/v1/cfdi/batch/nonexistent")
        assert r.status_code == 404

    def test_bank_feeds_endpoints(self, pilot_client):
        r = pilot_client.get("/api/v1/bank-feeds/accounts")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_reports_endpoints(self, pilot_client):
        r = pilot_client.get("/api/v1/reports/monthly/2026-08")
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")


# ---------------------------------------------------------------------------
# 2. Formato de respuesta (JSON schema)
# ---------------------------------------------------------------------------

class TestResponseSchemas:
    def test_batch_upload_response_shape(self, pilot_client):
        r = pilot_client.post(
            "/api/v1/cfdi/batch",
            files={"file": ("empty.zip", b"", "application/zip")},
        )
        # Archivo vacío → 400 con detail (shape de error JSON).
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_bank_feeds_connect_schema(self, pilot_client):
        r = pilot_client.post(
            "/api/v1/bank-feeds/accounts",
            json={"provider": "BBVA", "clabe": "012180001234567899"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "data" in body
        assert "id" in body["data"]

    # test_billing_plans_schema (billing-piloto) eliminado junto con el
    # módulo piloto — ver nota arriba.

# ---------------------------------------------------------------------------
# 3. Autenticación (make_require_api_key real, aislado)
# ---------------------------------------------------------------------------

def _auth_app():
    """Mini-app con make_require_api_key() real para probar el contrato auth."""
    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    auth = APIKeyAuth(db=None)  # lee B2B_API_KEY del entorno
    require_key = make_require_api_key(auth)
    app = FastAPI()

    @app.get("/protected")
    def protected(auth_info: dict = Depends(require_key)):
        return {"ok": True, "auth": auth_info}

    return TestClient(app)


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("B2B_API_KEY", "contract-test-key-123456")
    # AISLAMIENTO MULTI-TENANT (P1 fix): una key válida sin tenant es rechazada
    # con 400 y nunca degrada a "default". Para standalone, se configura un
    # tenant explícito vía B2B_DEFAULT_TENANT_ID.
    monkeypatch.setenv("B2B_DEFAULT_TENANT_ID", "1")
    return _auth_app()


class TestAuthOnProtectedEndpoints:
    def test_missing_key_returns_422_or_401(self, auth_client):
        """FastAPI expone la key como query param → sin header da 422/401."""
        r = auth_client.get("/protected")
        assert r.status_code in (401, 422)

    def test_invalid_key_rejected(self, auth_client):
        r = auth_client.get("/protected", headers={"X-API-Key": "wrong-key"})
        # Si la key se lee como query param "key", un header X-API-Key no
        # matchea → 422 (param faltante). El contrato exige rechazo, no 200.
        assert r.status_code in (401, 422)

    def test_valid_key_via_query(self, auth_client):
        """La key NO se acepta como query param: el auth usa el header."""
        r = auth_client.get("/protected", params={"key": "contract-test-key-123456"})
        # Sin header X-API-Key → 401 (la key debe ir por header, no por query).
        assert r.status_code == 401

    def test_valid_key_via_header(self, auth_client):
        """La key válida en el header X-API-Key autentica y devuelve dict.

        Antes del fix de Zuck (P1, QA 195) la dependencia devolvía el string y
        trataba la key como query param, así que el header se ignoraba → 422.
        Ahora `make_require_api_key` lee el header y devuelve un dict de
        contexto de auth, así que una key válida por header da 200.
        """
        r = auth_client.get("/protected", headers={"X-API-Key": "contract-test-key-123456"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["auth"], dict)  # auth_info es dict, no str


# ---------------------------------------------------------------------------
# 4. Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Rate limiter en memoria del app: 429 + Retry-After + rutas exentas."""

    def _client_with_limiter(self, limit=5):
        from b2b_ai.api.app import RateLimiter

        limiter = RateLimiter(limit=limit, window=60.0)
        app = FastAPI()

        @app.get("/limited")
        def limited():
            return {"ok": True}

        @app.get("/health")
        def health():
            return {"ok": True}

        @app.middleware("http")
        async def mw(request, call_next):
            if request.url.path.startswith(("/health", "/docs", "/openapi.json")):
                return await call_next(request)
            key = (request.client.host, request.url.path)
            if not limiter.allow(key):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas peticiones."},
                    headers={"Retry-After": str(int(limiter.window))},
                )
            return await call_next(request)

        return TestClient(app), limiter

    def test_rate_limit_returns_429_and_retry_after(self):
        client, _ = self._client_with_limiter(limit=3)
        for _ in range(3):
            assert client.get("/limited").status_code == 200
        r = client.get("/limited")
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_rate_limit_exempts_health(self):
        client, _ = self._client_with_limiter(limit=2)
        for _ in range(5):
            assert client.get("/health").status_code == 200

    def test_rate_limit_resets(self):
        client, limiter = self._client_with_limiter(limit=2)
        client.get("/limited")
        client.get("/limited")
        assert client.get("/limited").status_code == 429
        limiter.reset()
        assert client.get("/limited").status_code == 200
