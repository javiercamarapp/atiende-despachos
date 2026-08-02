# -*- coding: utf-8 -*-
"""Tests para b2b_ai.middleware.rate_limiter — token bucket + middleware.

Cubre:
  - Semántica del token bucket (recarga, ráfaga, techo).
  - Clasificación de endpoint (auth/api/webhooks).
  - Middleware: límites por clase, headers X-RateLimit-*, 429 + Retry-After,
    rutas exentas, fallback a memoria.
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.middleware.rate_limiter import (
    _endpoint_class,
    _get_backend,
    _MemoryBackend,
    _resolve_limit,
    TokenBucket,
    install_rate_limit,
    RateLimitMiddleware,
)


# ---------------------------------------------------------------------------
# Token bucket puro
# ---------------------------------------------------------------------------
class TestTokenBucket:
    def test_full_capacity_allows_burst(self):
        bucket = TokenBucket(capacity=5, rate=1.0, now=0.0)
        for _ in range(5):
            allowed, rem, _ = bucket.try_consume(now=0.0)
            assert allowed is True
        # 6º consumo sin tiempo transcurrido -> denegado
        allowed, rem, until = bucket.try_consume(now=0.0)
        assert allowed is False
        assert until > 0

    def test_refills_over_time(self):
        bucket = TokenBucket(capacity=2, rate=1.0, now=0.0)
        bucket.try_consume(now=0.0)
        bucket.try_consume(now=0.0)
        allowed, _, _ = bucket.try_consume(now=0.0)
        assert allowed is False
        # Después de 1 segundo se recarga 1 token.
        allowed, rem, _ = bucket.try_consume(now=1.0)
        assert allowed is True

    def test_tokens_capped_at_capacity(self):
        bucket = TokenBucket(capacity=3, rate=5.0, now=0.0)
        bucket.try_consume(now=0.0)
        # Mucho tiempo después: no excede capacity.
        _, rem, _ = bucket.try_consume(now=100.0)
        assert rem <= 3.0 + 1e-9

    def test_rate_zero_never_recovers(self):
        bucket = TokenBucket(capacity=1, rate=0.0, now=0.0)
        bucket.try_consume(now=0.0)
        allowed, _, until = bucket.try_consume(now=999.0)
        assert allowed is False
        # until_full con rate 0 se maneja sin división por cero.
        assert until == 0.0


# ---------------------------------------------------------------------------
# Helpers de configuración
# ---------------------------------------------------------------------------
class TestEndpointClass:
    def test_auth_class(self):
        assert _endpoint_class("/api/v1/auth/login") == "auth"
        assert _endpoint_class("/api/v1/auth/refresh") == "auth"

    def test_webhooks_class(self):
        assert _endpoint_class("/api/v1/webhooks/subscriptions") == "webhooks"
        assert _endpoint_class("/webhooks/notify") == "webhooks"

    def test_default_api_class(self):
        assert _endpoint_class("/api/v1/invoices") == "api"
        assert _endpoint_class("/health") == "api"  # clase pero exento por prefix


class TestResolveLimit:
    def test_defaults(self):
        tokens, rate = _resolve_limit({"limit": 100, "window": 60})
        assert tokens == 100
        assert rate == pytest.approx(100 / 60)

    def test_clamps_to_minimum(self):
        tokens, rate = _resolve_limit({"limit": 0, "window": 0})
        assert tokens == 1
        assert rate > 0


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
def _build_app(backend=None, limits=None, prefix=""):
    app = FastAPI()

    @app.post(prefix + "/api/v1/auth/login")
    async def login():
        return {"ok": True}

    @app.post(prefix + "/api/v1/data")
    async def data():
        return {"ok": True}

    @app.post(prefix + "/api/v1/webhooks/subscriptions")
    async def wh():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": "healthy"}

    install_rate_limit(app, backend=backend or _MemoryBackend(), limits=limits)
    return TestClient(app)


class TestRateLimitMiddleware:
    def test_headers_present_on_allowed(self):
        client = _build_app()
        r = client.post("/api/v1/data")
        assert r.status_code == 200
        assert r.headers.get("X-RateLimit-Limit") == "100"
        assert r.headers.get("X-RateLimit-Remaining") is not None
        assert r.headers.get("X-RateLimit-Reset") is not None

    def test_auth_limited_after_5(self):
        # auth: 5/min -> el 6º devuelve 429
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        for _ in range(5):
            r = client.post("/api/v1/auth/login", headers={"X-API-Key": "k"})
            assert r.status_code == 200
        r = client.post("/api/v1/auth/login", headers={"X-API-Key": "k"})
        assert r.status_code == 429
        assert r.headers.get("Retry-After") is not None
        assert r.headers.get("X-RateLimit-Limit") == "5"
        assert r.headers.get("X-RateLimit-Remaining") == "0"

    def test_api_limited_after_100(self):
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        for _ in range(100):
            assert client.post("/api/v1/data").status_code == 200
        assert client.post("/api/v1/data").status_code == 429

    def test_webhooks_limited_after_30(self):
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        for _ in range(30):
            assert client.post("/api/v1/webhooks/subscriptions").status_code == 200
        assert client.post("/api/v1/webhooks/subscriptions").status_code == 429

    def test_separate_buckets_per_endpoint_class(self):
        # El mismo cliente golpeando auth y api no se contamina entre sí.
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        for _ in range(5):
            client.post("/api/v1/auth/login")
        # auth agotado...
        assert client.post("/api/v1/auth/login").status_code == 429
        # ...pero api sigue entero.
        assert client.post("/api/v1/data").status_code == 200

    def test_exempt_health_not_limited(self):
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        for _ in range(200):
            assert client.get("/health").status_code == 200

    def test_custom_limits(self):
        custom = {"auth": {"limit": 2, "window": 60},
                  "api": {"limit": 3, "window": 60}}
        backend = _MemoryBackend()
        client = _build_app(backend=backend, limits=custom)
        for _ in range(2):
            assert client.post("/api/v1/auth/login").status_code == 200
        assert client.post("/api/v1/auth/login").status_code == 429
        assert client.post("/api/v1/data").status_code == 200

    def test_429_error_body_shape(self):
        client = _build_app()
        for _ in range(5):
            client.post("/api/v1/auth/login")
        r = client.post("/api/v1/auth/login")
        assert r.status_code == 429
        body = r.json()
        assert "error" in body
        assert body["error"]["type"] == "rate_limit_exceeded"
        assert body["error"]["limit"] == 5

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("B2B_RATE_LIMIT", "off")
        backend = _MemoryBackend()
        client = _build_app(backend=backend)
        # Aunque se golpee 1000 veces, todo pasa porque está desactivado.
        for _ in range(1000):
            assert client.post("/api/v1/auth/login").status_code == 200


class TestMemoryBackend:
    def test_reset_key(self):
        b = _MemoryBackend()
        for _ in range(100):
            b.check_and_consume("k:api", 100, 100 / 60)
        allowed, _, _ = b.check_and_consume("k:api", 100, 100 / 60)
        assert allowed is False
        b.reset("k:api")
        allowed, _, _ = b.check_and_consume("k:api", 100, 100 / 60)
        assert allowed is True

    def test_reset_all(self):
        b = _MemoryBackend()
        for _ in range(100):
            b.check_and_consume("a:api", 100, 1.0)
        b.reset()
        allowed, _, _ = b.check_and_consume("a:api", 100, 1.0)
        assert allowed is True
