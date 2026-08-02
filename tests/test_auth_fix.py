# -*- coding: utf-8 -*-
"""Tests for the P1 auth fix: make_require_api_key returns a dict.

Regression for QA 195 (docmanagement-diot-roles): the dependency returned a
bare string, so every router that read `auth_info.get("tenant_id")` crashed
with AttributeError -> HTTP 500. Now it returns a dict context
{key, tenant_id, user_id} and enforces multi-tenant isolation (a valid key
with no tenant_id is rejected with 400, never degraded to "default").
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from b2b_ai.api.auth import APIKeyAuth, make_require_api_key  # noqa: E402
from b2b_ai.db.db import Database  # noqa: E402

TENANT_A_KEY = "tenant-a-key-0001"
TENANT_B_KEY = "tenant-b-key-0002"


def _db_with_tenants(tmp_path):
    """SQLite DB with two tenants, each with its own API key."""
    db = Database(str(tmp_path / "auth_fix.db"))
    ta = db.create_tenant("Despacho A")
    tb = db.create_tenant("Despacho B")
    db.create_api_key(ta, "a", TENANT_A_KEY)
    db.create_api_key(tb, "b", TENANT_B_KEY)
    return db, ta, tb


def _make_app(auth):
    require = make_require_api_key(auth)
    app = FastAPI()

    @app.get("/protected")
    def protected(auth_info: dict = Depends(require)):
        # What the real routers do: dict-style access must not crash.
        return {
            "ok": True,
            "tenant_id": auth_info.get("tenant_id"),
            "user_id": auth_info.get("user_id"),
            "key": auth_info.get("key"),
            "is_dict": isinstance(auth_info, dict),
        }

    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. make_require_api_key returns a dict with key / tenant_id / user_id
# ---------------------------------------------------------------------------
class TestReturnsDict:
    def test_db_key_returns_dict(self, tmp_path):
        db, ta, _ = _db_with_tenants(tmp_path)
        c = _make_app(APIKeyAuth(db))
        r = c.get("/protected", headers={"X-API-Key": TENANT_A_KEY})
        assert r.status_code == 200
        body = r.json()
        assert body["is_dict"] is True
        assert body["tenant_id"] == ta
        assert body["key"] == TENANT_A_KEY

    def test_dict_has_user_id_key_and_tenant_id(self, tmp_path):
        db, _, _ = _db_with_tenants(tmp_path)
        c = _make_app(APIKeyAuth(db))
        r = c.get("/protected", headers={"X-API-Key": TENANT_A_KEY})
        body = r.json()
        assert "user_id" in body
        assert "tenant_id" in body
        assert "key" in body


# ---------------------------------------------------------------------------
# 2. Routers receive a dict (not a str) — the P1 regression
# ---------------------------------------------------------------------------
class TestRoutersReceiveDict:
    def test_dep_injection_yields_dict_not_str(self, tmp_path):
        db, _, _ = _db_with_tenants(tmp_path)
        require = make_require_api_key(APIKeyAuth(db))
        app = FastAPI()

        @app.get("/probe")
        def probe(auth_info: dict = Depends(require)):
            # .get() is exactly what document_management / billing / diot /
            # dashboard / onboarding / sat / collections routers call.
            assert isinstance(auth_info, dict)
            assert auth_info.get("tenant_id") is not None
            return auth_info

        c = TestClient(app)
        r = c.get("/probe", headers={"X-API-Key": TENANT_A_KEY})
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


# ---------------------------------------------------------------------------
# 3. Missing key -> 401
# ---------------------------------------------------------------------------
class TestMissingKey:
    def test_no_header_401(self, tmp_path):
        db, _, _ = _db_with_tenants(tmp_path)
        c = _make_app(APIKeyAuth(db))
        r = c.get("/protected")
        assert r.status_code in (401, 422)

    def test_invalid_key_401(self, tmp_path):
        db, _, _ = _db_with_tenants(tmp_path)
        c = _make_app(APIKeyAuth(db))
        r = c.get("/protected", headers={"X-API-Key": "not-a-real-key"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 4. Valid key with no tenant_id (standalone env mode, no default) -> 400
# ---------------------------------------------------------------------------
class TestIsolationRejectsNoTenant:
    def test_valid_env_key_without_tenant_is_400(self, tmp_path, monkeypatch):
        # Standalone mode: single env key, no DB, no default tenant.
        monkeypatch.setenv("B2B_API_KEY", "standalone-env-key-123")
        monkeypatch.delenv("B2B_DEFAULT_TENANT_ID", raising=False)
        auth = APIKeyAuth(db=None)
        c = _make_app(auth)
        r = c.get("/protected", headers={"X-API-Key": "standalone-env-key-123"})
        # Valid key but no tenant -> 400, NOT 200 and NOT "default".
        assert r.status_code == 400

    def test_does_not_degrade_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("B2B_API_KEY", "standalone-env-key-123")
        monkeypatch.delenv("B2B_DEFAULT_TENANT_ID", raising=False)
        auth = APIKeyAuth(db=None)
        c = _make_app(auth)
        r = c.get("/protected", headers={"X-API-Key": "standalone-env-key-123"})
        body = r.json() if r.status_code != 400 else {}
        assert r.status_code == 400
        # If it somehow returned a dict, it must not contain a fabricated
        # "default" tenant.
        if body:
            assert body.get("tenant_id") != "default"

    def test_env_fallback_default_tenant_allows_standalone(self, tmp_path, monkeypatch):
        # Explicit single-tenant config: key resolves to B2B_DEFAULT_TENANT_ID.
        monkeypatch.setenv("B2B_API_KEY", "standalone-env-key-123")
        monkeypatch.setenv("B2B_DEFAULT_TENANT_ID", "42")
        auth = APIKeyAuth(db=None)
        c = _make_app(auth)
        r = c.get("/protected", headers={"X-API-Key": "standalone-env-key-123"})
        assert r.status_code == 200
        assert r.json()["tenant_id"] == "42"


# ---------------------------------------------------------------------------
# 5. Tenant isolation: key of tenant A cannot act as tenant B
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_tenant_a_key_resolves_to_tenant_a(self, tmp_path):
        db, ta, _ = _db_with_tenants(tmp_path)
        auth = APIKeyAuth(db)
        assert auth.get_tenant_id(TENANT_A_KEY) == ta

    def test_tenant_b_key_resolves_to_tenant_b(self, tmp_path):
        db, _, tb = _db_with_tenants(tmp_path)
        auth = APIKeyAuth(db)
        assert auth.get_tenant_id(TENANT_B_KEY) == tb

    def test_router_scopes_tenant_a_does_not_see_tenant_b_data(self, tmp_path):
        db, ta, tb = _db_with_tenants(tmp_path)
        require = make_require_api_key(APIKeyAuth(db))
        app = FastAPI()

        # Two tenants write to a shared store; each request must be scoped.
        store: dict = {"tenant": {}, "owner": {}}

        @app.get("/data")
        def read(auth_info: dict = Depends(require)):
            return {"data": store["tenant"].get(auth_info["tenant_id"], []),
                    "tenant_id": auth_info["tenant_id"]}

        @app.post("/data")
        def write(auth_info: dict = Depends(require)):
            tid = auth_info["tenant_id"]
            item = {"owner": TENANT_A_KEY if tid == ta else TENANT_B_KEY}
            store["tenant"].setdefault(tid, []).append(item)
            return {"ok": True}

        c = TestClient(app)
        # A writes, B writes.
        assert c.post("/data", headers={"X-API-Key": TENANT_A_KEY}).status_code == 200
        assert c.post("/data", headers={"X-API-Key": TENANT_B_KEY}).status_code == 200
        # A reads only its own data.
        a_data = c.get("/data", headers={"X-API-Key": TENANT_A_KEY}).json()
        assert a_data["tenant_id"] == ta
        assert len(a_data["data"]) == 1
        assert a_data["data"][0]["owner"] == TENANT_A_KEY
        # B reads only its own data — never A's.
        b_data = c.get("/data", headers={"X-API-Key": TENANT_B_KEY}).json()
        assert b_data["tenant_id"] == tb
        assert len(b_data["data"]) == 1
        assert b_data["data"][0]["owner"] == TENANT_B_KEY
