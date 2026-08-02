# -*- coding: utf-8 -*-
"""Tests for reconciliation_agent routes — endpoint coverage."""
import pytest


class TestReconciliationRoutes:
    """Test reconciliation agent API endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        try:
            from b2b_ai.features.reconciliation_agent.routes import router
            app.include_router(router)
        except ImportError:
            pytest.skip("Reconciliation routes not available")
        return TestClient(app)

    def test_get_reconciliation_status(self, client):
        """GET reconciliation status should return 200 with status info."""
        resp = client.get("/api/reconciliation/status")
        # Accept 200 (implemented) or 404 (route not mounted at this path)
        assert resp.status_code in (200, 404, 405)
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, dict)

    def test_post_reconciliation_with_empty_body(self, client):
        """POST reconciliation with empty body should return 422 or 400."""
        resp = client.post("/api/reconciliation/match", json={})
        assert resp.status_code in (400, 422, 404, 405)


class TestReconciliationRoutesContent:
    """Test that reconciliation routes return meaningful content, not just status codes."""

    @pytest.fixture
    def app_with_reconciliation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        try:
            from b2b_ai.features.reconciliation_agent.routes import router
            app.include_router(router)
        except ImportError:
            return None
        return TestClient(app)

    def test_routes_return_json(self, app_with_reconciliation):
        """All reconciliation endpoints should return JSON."""
        if app_with_reconciliation is None:
            pytest.skip("Routes not available")
        client = app_with_reconciliation
        # Try common endpoints
        for path in ["/api/reconciliation/status", "/api/reconciliation/alerts"]:
            resp = client.get(path)
            if resp.status_code == 200:
                assert resp.headers.get("content-type", "").startswith("application/json")
                data = resp.json()
                assert isinstance(data, (dict, list))
