# -*- coding: utf-8 -*-
"""Tests for b2b_ai/features/api.py — feature flag API endpoints."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from b2b_ai.db.db import Database
from b2b_ai.features.api import build_features_router, FeatureFlagUpdate


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def client(db):
    app = FastAPI()

    # Mock auth dependency
    def require_api_key():
        return {"tenant_id": 1, "api_key": "test-key"}

    tenant = db.create_tenant("Test", "RFC1")
    router = build_features_router(db, require_api_key)
    app.include_router(router)
    return TestClient(app)


class TestListFlags:
    def test_list(self, client):
        r = client.get("/api/v1/features")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0


class TestGetFlag:
    def test_get_existing(self, client):
        r = client.get("/api/v1/features/portal_cliente")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "portal_cliente"


class TestUpdateFlag:
    def test_enable(self, client):
        r = client.put("/api/v1/features/cobranza_automatizada",
                       json={"enabled": True, "rollout_percentage": 100})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_disable(self, client):
        r = client.put("/api/v1/features/portal_cliente",
                       json={"enabled": False})
        assert r.status_code == 200

    def test_update_then_get(self, client):
        # The mock auth returns tenant_id=1; the feature should be enabled
        # for that specific tenant
        r_put = client.put("/api/v1/features/cobranza_automatizada",
                   json={"enabled": True, "rollout_percentage": 100})
        assert r_put.status_code == 200
        # Get the flag status
        r_get = client.get("/api/v1/features/cobranza_automatizada")
        assert r_get.status_code == 200
        assert r_get.json()["enabled"] is True
