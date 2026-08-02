# -*- coding: utf-8 -*-
"""test_api_contracts.py — Tests de contratos de la API del piloto.

Valida que los endpoints del flujo piloto:
  1. Existen y responden (no 404).
  2. Devuelven formatos JSON consistentes con los schemas declarados.
  3. Aplican autenticación en endpoints protegidos (X-API-Key).
  4. Aplican rate limiting (429 + Retry-After).

Se monta `create_app()` completo (con auth real de API key) para probar los
contratos de red; el rate limiting se prueba de forma aislada (limiter en
memoria) igual que `test_rate_limiter.py`, porque el limiter global del app
depende de la IP del cliente y no es determinista para contrato.

MODO: los módulos del piloto corren en memoria (sin PostgreSQL real) y el
proveedor de pago en MOCK. Cumple la restricción de no ejecutar pytest contra
la base de producción.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app() -> FastAPI:
    """App completa con auth real de API key (env) + routers del piloto."""
    from b2b_ai.api.app import create_app
    return create_app(db=None)


@pytest.fixture
def api_client(monkeypatch):
    """TestClient con create_app() y una API key standalone configurada."""
    monkeypatch.setenv("B2B_API_KEY", "contract-test-key-123456")
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")  # aislar del test de rate limit
    monkeypatch.setenv("B2B_JWT_SECRET", "contract-test-jwt-secret-ok")
    return TestClient(_make_app())


@pytest.fixture
def api_key():
    return "contract-test-key-123456"


# ---------------------------------------------------------------------------
# 1. Existencia de endpoints y status codes
# ---------------------------------------------------------------------------

class TestEndpointsExist:
    """Los endpoints del flujo piloto deben existir (no 404 con auth ok)."""

    def test_health_public(self, api_client):
        r = api_client.get("/health")
        assert r.status_code in (200, 503)  # 503 si DB no está
        assert r.headers.get("content-type", "").startswith(("application/json", "text"))

    def test_onboarding_wizard_endpoints(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        assert api_client.post("/api/v1/onboarding-wizard/start",
                               json={}, headers=h).status_code == 200
        r = api_client.get("/api/v1/onboarding-wizard/nonexistent",
                           headers=h)
        assert r.status_code == 404  # existe la ruta, no la sesión

    def test_billing_piloto_plans(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.get("/api/v1/billing-piloto/plans", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["currency"] == "MXN"
        assert isinstance(body["plans"], list)
        assert len(body["plans"]) > 0

    def test_billing_piloto_checkout_contract(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.post(
            "/api/v1/billing-piloto/checkout",
            json={"plan": "pro",
                  "success_url": "https://app.likida.ai/ok",
                  "cancel_url": "https://app.likida.ai/cancel"},
            headers=h,
        )
        # Con tenant ausente (key global, sin tenant_id) el checkout puede
        # rechazar con 400 — el contrato exige que NO sea 404 ni 500.
        assert r.status_code in (200, 400), r.text

    def test_batch_endpoints(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        # Ruta de consulta existe → 404 para id inexistente (no 405/404 de ruta).
        r = api_client.get("/api/v1/cfdi/batch/nonexistent", headers=h)
        assert r.status_code == 404

    def test_bank_feeds_endpoints(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.get("/api/v1/bank-feeds/accounts", headers=h)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_reports_endpoints(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.get("/api/v1/reports/monthly/2026-08", headers=h)
        # monthly exige tenant_id; con key global (sin tenant) → 422.
        assert r.status_code in (200, 422), r.text


# ---------------------------------------------------------------------------
# 2. Formato de respuesta (JSON schema)
# ---------------------------------------------------------------------------

class TestResponseSchemas:
    def test_batch_upload_response_shape(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.post(
            "/api/v1/cfdi/batch",
            files={"file": ("empty.zip", b"", "application/zip")},
            headers=h,
        )
        # Archivo vacío → 400 con detail (shape de error JSON).
        assert r.status_code == 400
        body = r.json()
        assert "detail" in body

    def test_bank_feeds_connect_schema(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        r = api_client.post(
            "/api/v1/bank-feeds/accounts",
            json={"provider": "BBVA", "clabe": "0123456789"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "data" in body
        assert "id" in body["data"]

    def test_billing_plans_schema(self, api_client, api_key):
        h = {"X-API-Key": api_key}
        body = api_client.get("/api/v1/billing-piloto/plans", headers=h).json()
        assert body["ok"] is True
        for plan in body["plans"]:
            assert "code" in plan
            assert "name" in plan
            assert "price_mxn" in plan


# ---------------------------------------------------------------------------
# 3. Autenticación en endpoints protegidos
# ---------------------------------------------------------------------------

class TestAuthOnProtectedEndpoints:
    """Todos los endpoints /api/v1/* exigen X-API-Key válida."""

    PROTECTED = [
        ("POST", "/api/v1/onboarding-wizard/start", {}),
        ("GET", "/api/v1/billing-piloto/plans", None),
        ("GET", "/api/v1/bank-feeds/accounts", None),
        ("GET", "/api/v1/cfdi/batch/nonexistent", None),
    ]

    @pytest.mark.parametrize("method,path,payload", PROTECTED)
    def test_missing_key_rejected(self, api_client, method, path, payload):
        kwargs = {}
        if payload is not None:
            kwargs["json"] = payload
        r = getattr(api_client, method.lower())(path, **kwargs)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"

    @pytest.mark.parametrize("method,path,payload", PROTECTED)
    def test_invalid_key_rejected(self, api_client, method, path, payload):
        kwargs = {"headers": {"X-API-Key": "wrong-key"}}
        if payload is not None:
            kwargs["json"] = payload
        r = getattr(api_client, method.lower())(path, **kwargs)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"

    @pytest.mark.parametrize("method,path,payload", PROTECTED)
    def test_valid_key_accepted(self, api_client, method, path, payload,
                                api_key):
        kwargs = {"headers": {"X-API-Key": api_key}}
        if payload is not None:
            kwargs["json"] = payload
        r = getattr(api_client, method.lower())(path, **kwargs)
        # Con key válida: no debe ser 401. 404 (ruta ok / recurso no hallado)
        # y 200 son aceptables; 400 si el payload no aplica en ese contexto.
        assert r.status_code != 401, f"{method} {path} -> {r.status_code}"


# ---------------------------------------------------------------------------
# 4. Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Rate limiter en memoria del app: 429 + Retry-After + rutas exentas."""

    def _client_with_limiter(self, limit=5):
        from b2b_ai.api.app import RateLimiter
        from fastapi import APIRouter

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
