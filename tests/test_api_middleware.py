# -*- coding: utf-8 -*-
"""Tests for b2b_ai.api.middleware — request size limit enforcement."""
import os
import pytest


class TestRequestSizeLimitMiddleware:
    """Verify middleware blocks oversized requests."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        """Create a minimal FastAPI app with the middleware."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from b2b_ai.api.middleware import install_request_size_limit

        self.app = FastAPI()
        install_request_size_limit(self.app, max_bytes=1024)  # 1KB for tests

        @self.app.post("/api/test")
        async def test_endpoint():
            return {"status": "ok"}

        @self.app.get("/health")
        async def health():
            return {"status": "healthy"}

        @self.app.get("/health/detailed")
        async def health_detailed():
            return {"status": "ok"}

        self.client = TestClient(self.app)

    def test_small_request_passes(self):
        """Normal-sized request should pass through."""
        resp = self.client.post("/api/test", json={"data": "small"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_large_request_blocked(self):
        """Request exceeding limit should return 413."""
        payload = "x" * 2048  # 2KB > 1KB limit
        resp = self.client.post(
            "/api/test",
            content=payload.encode(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert resp.status_code == 413
        body = resp.json()
        assert "too large" in body["detail"].lower()
        assert "1 KB" in body["detail"] or "1024" in body["detail"]

    def test_get_requests_exempt(self):
        """GET requests should always pass regardless of Content-Length."""
        resp = self.client.get("/api/test")
        assert resp.status_code in (200, 404, 405)  # not 413

    def test_health_endpoint_exempt(self):
        """Health endpoints should be exempt from size checks."""
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_health_detailed_exempt(self):
        """Health/detailed endpoints should be exempt."""
        resp = self.client.get("/health/detailed")
        assert resp.status_code == 200

    def test_exact_limit_passes(self):
        """Request at exactly the limit should pass."""
        payload = "x" * 1024  # exactly 1KB
        resp = self.client.post(
            "/api/test",
            content=payload.encode(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert resp.status_code == 200

    def test_env_override(self, monkeypatch):
        """B2B_MAX_REQUEST_SIZE_MB env var should override default."""
        from b2b_ai.api.middleware import _get_max_bytes
        monkeypatch.setenv("B2B_MAX_REQUEST_SIZE_MB", "5")
        assert _get_max_bytes() == 5 * 1024 * 1024

    def test_env_invalid_value_falls_back(self, monkeypatch):
        """Invalid env value should fall back to default."""
        from b2b_ai.api.middleware import _get_max_bytes, _DEFAULT_MAX_BYTES
        monkeypatch.setenv("B2B_MAX_REQUEST_SIZE_MB", "not_a_number")
        assert _get_max_bytes() == _DEFAULT_MAX_BYTES
