# -*- coding: utf-8 -*-
"""
test_multi_tenant_coverage_gaps.py — Targeted tests to reach 100% coverage
on the multi_tenant module, plus additional security-critical edge cases.

Covers:
  - service.py lines 139, 141, 654 (schema validation errors, config init)
  - validators.py line 53 (invalid status fallback)
  - routes.py lines 102, 117-139, 158 (TenantContextMiddleware, router guard)
  - Security edge cases: SQL injection in names, concurrent isolation,
    config isolation between tenants, boundary conditions
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.multi_tenant.models import (
    AuditAction,
    CreateTenantRequest,
    IsolationLevel,
    Tenant,
    TenantStatus,
)
from b2b_ai.features.multi_tenant.service import (
    MultiTenantService,
    TenantBlockedError,
    TenantConflictError,
    TenantNotFoundError,
    TENANT_CONFIG_DEFAULTS,
)
from b2b_ai.features.multi_tenant.validators import (
    validate_cross_tenant_block,
    validate_schema_name,
    validate_tenant_access,
    validate_tenant_config_key,
    validate_tenant_name,
)
from b2b_ai.features.multi_tenant.routes import (
    TenantContextMiddleware,
    build_multi_tenant_router,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(**overrides) -> CreateTenantRequest:
    defaults = dict(
        name="Test Tenant",
        rfc="TST010101XYZ",
        isolation_level=IsolationLevel.SHARED_SCHEMA,
        config={},
        metadata={},
    )
    defaults.update(overrides)
    return CreateTenantRequest(**defaults)


def _svc_with(n: int = 1, **kw) -> MultiTenantService:
    svc = MultiTenantService()
    for i in range(n):
        svc.create_tenant(_req(
            name=f"Tenant {i + 1}",
            rfc=f"RFC{i + 1:03d}",
            **kw,
        ))
    return svc


# ===========================================================================
# 1. Coverage Gaps — service.py
# ===========================================================================

class TestServiceCoverageGaps:
    """Close remaining uncovered lines in service.py."""

    def test_schema_name_validation_error_during_create(self):
        """service.py:139 — Schema name invalid when name has hyphen
        + SCHEMA_PER_TENANT. The name 'Mi-Despacho' is valid for tenants,
        but generates schema 'tenant_mi-despacho' with invalid hyphen."""
        svc = MultiTenantService()
        req = _req(
            name="Mi-Despacho",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        with pytest.raises(ValueError, match="caracteres no válidos"):
            svc.create_tenant(req)

    def test_duplicate_schema_different_names(self):
        """service.py:141 — Schema conflict when two different valid names
        produce the same schema. We test this by injecting a collision into
        the schema registry (simulating the rare case)."""
        svc = MultiTenantService()
        t1 = svc.create_tenant(_req(
            name="Alpha",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        ))
        assert t1.schema_name == "tenant_alpha"
        # Inject a schema collision: add "tenant_beta" to registry manually
        svc._schema_registry["tenant_beta"] = "fake-id"
        req2 = _req(
            name="Beta",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        # This will try to register 'tenant_beta' which already exists
        with pytest.raises(TenantConflictError, match="schema"):
            svc.create_tenant(req2)

    def test_set_config_on_uninitialized_tenant_config(self):
        """service.py:654 — set_config when _configs[tenant_id] not
        yet initialized (defensive path, normally impossible)."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        # Manually remove the config store entry
        del svc._configs[tid]
        assert tid not in svc._configs
        # set_config should re-initialize it
        cfg = svc.set_config(tid, "recovered_key", "recovered_value")
        assert cfg.value == "recovered_value"
        assert cfg.key == "recovered_key"


# ===========================================================================
# 2. Coverage Gaps — validators.py
# ===========================================================================

class TestValidatorCoverageGaps:
    """Close remaining uncovered lines in validators.py."""

    def test_validate_tenant_access_invalid_status(self):
        """validators.py:53 — Fallback for an unrecognized status value.
        Since TenantStatus is an enum, this is a defensive branch."""
        # Create a Tenant and manually override its status to something
        # that won't match any of the explicit checks.
        tenant = Tenant(name="Edge Tenant")
        # Monkey-patch status to bypass enum validation
        tenant._object_setattr = object.__setattr__
        # Use object.__setattr__ to set an invalid status value
        object.__setattr__(tenant, "status", "bogus_status")
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False
        assert "inválido" in err.lower()


# ===========================================================================
# 3. Coverage Gaps — routes.py (TenantContextMiddleware + router guard)
# ===========================================================================

class TestTenantContextMiddleware:
    """Test TenantContextMiddleware class (routes.py:102-139)."""

    def test_middleware_init(self):
        """routes.py:102 — TenantContextMiddleware.__init__ stores service."""
        svc = MultiTenantService()
        middleware = TenantContextMiddleware(svc)
        assert middleware._service is svc

    def test_middleware_no_tenant_id_returns_none(self):
        """routes.py:117-118 — No tenant_id → returns None."""
        svc = MultiTenantService()
        middleware = TenantContextMiddleware(svc)
        assert middleware() is None
        assert middleware(tenant_id=None) is None
        assert middleware(tenant_id="") is None

    def test_middleware_with_matching_context(self):
        """routes.py:120-129 — Current context matches tenant_id."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.switch_tenant_context(tid, user_id="u1", user_role="admin")
        middleware = TenantContextMiddleware(svc)
        ctx = middleware(tenant_id=tid)
        assert ctx is not None
        assert ctx["tenant_id"] == tid
        assert ctx["user_id"] == "u1"
        assert ctx["user_role"] == "admin"

    def test_middleware_falls_through_to_get_tenant(self):
        """routes.py:131-137 — Context doesn't match, falls through
        to get_tenant for direct lookup."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        # Set context for tenant 1
        svc.switch_tenant_context(tenants[0].id)
        # Request for tenant 2 (doesn't match context)
        middleware = TenantContextMiddleware(svc)
        ctx = middleware(tenant_id=tenants[1].id)
        assert ctx is not None
        assert ctx["tenant_id"] == tenants[1].id
        assert ctx["tenant_name"] == tenants[1].name

    def test_middleware_nonexistent_tenant_returns_none(self):
        """routes.py:138-139 — TenantNotFoundError → returns None."""
        svc = MultiTenantService()
        middleware = TenantContextMiddleware(svc)
        ctx = middleware(tenant_id="nonexistent-id")
        assert ctx is None

    def test_middleware_blocked_tenant_returns_context(self):
        """routes.py:131-137 — Blocked tenant can still be fetched by
        get_tenant (blocking only applies to context switching)."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.block_tenant(tid)
        middleware = TenantContextMiddleware(svc)
        # get_tenant succeeds for blocked tenants (no TenantNotFoundError)
        # The middleware returns tenant info — access control is at service level
        ctx = middleware(tenant_id=tid)
        assert ctx is not None
        assert ctx["tenant_id"] == tid


class TestRouterGuard:
    """Test build_multi_tenant_router guard (routes.py:158)."""

    def test_router_raises_without_auth_dependency(self):
        """routes.py:158 — Router refuses to build without require_api_key."""
        with pytest.raises(ValueError, match="require_api_key es obligatorio"):
            build_multi_tenant_router(db=None, require_api_key=None)


# ===========================================================================
# 4. Security-Critical Edge Cases
# ===========================================================================

class TestSecurityIsolation:
    """Security-focused tests for multi-tenant isolation."""

    def test_cross_tenant_data_leakage_prevention(self):
        """Verify tenant A's data is completely invisible to tenant B."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()

        # Inject data for both tenants
        data_a = [
            {"tenant_id": tenants[0].id, "secret": "A_secret_123"},
            {"tenant_id": tenants[0].id, "secret": "A_secret_456"},
        ]
        data_b = [
            {"tenant_id": tenants[1].id, "secret": "B_secret_789"},
        ]
        all_data = data_a + data_b

        # Tenant A should only see its data
        result_a = svc.tenant_scoped_query(tenants[0].id, "secrets", all_data)
        assert len(result_a) == 2
        assert all(r["secret"].startswith("A_") for r in result_a)

        # Tenant B should only see its data
        result_b = svc.tenant_scoped_query(tenants[1].id, "secrets", all_data)
        assert len(result_b) == 1
        assert result_b[0]["secret"] == "B_secret_789"

    def test_sql_injection_in_tenant_name(self):
        """Verify SQL-injection-style names are rejected by validators."""
        malicious_names = [
            "'; DROP TABLE tenants; --",
            "admin' OR '1'='1",
            "tenant\"; DELETE FROM users; --",
            "Robert'); DROP TABLE students;--",
            "1' UNION SELECT * FROM users--",
        ]
        for name in malicious_names:
            is_valid, _ = validate_tenant_name(name)
            assert is_valid is False, f"SQL injection name should be rejected: {name}"

    def test_tenant_context_isolation_between_threads(self):
        """Verify that concurrent context switches don't leak between threads."""
        svc = _svc_with(3)
        tenants = svc.list_tenants()
        results = {}
        barrier = threading.Barrier(3)
        errors = []

        def worker(tenant_idx, label):
            try:
                svc.switch_tenant_context(tenants[tenant_idx].id)
                barrier.wait(timeout=5)
                # After barrier, check that our context is still our tenant
                ctx = svc.get_current_context()
                if ctx and ctx.tenant_id != tenants[tenant_idx].id:
                    errors.append(
                        f"{label}: expected {tenants[tenant_idx].id}, "
                        f"got {ctx.tenant_id}"
                    )
                results[label] = ctx.tenant_id if ctx else None
            except Exception as e:
                errors.append(f"{label}: {e}")

        threads = [
            threading.Thread(target=worker, args=(i, f"t{i}"))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Context leakage detected: {errors}"
        for i in range(3):
            assert results[f"t{i}"] == tenants[i].id

    def test_config_isolation_between_tenants(self):
        """Verify that config changes for one tenant don't affect another."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()

        svc.set_config(tenants[0].id, "erp_type", "csv")
        svc.set_config(tenants[1].id, "erp_type", "aspel")

        assert svc.get_config_value(tenants[0].id, "erp_type") == "csv"
        assert svc.get_config_value(tenants[1].id, "erp_type") == "aspel"

    def test_blocked_tenant_cannot_switch_context(self):
        """Security: blocked tenant must be completely denied access."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.block_tenant(tid)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tid)

    def test_suspended_tenant_cannot_switch_context(self):
        """Security: suspended tenant must be denied context switching."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tid)

    def test_deleted_tenant_cannot_be_accessed(self):
        """Security: deleted tenant raises TenantNotFoundError."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant(tid)

    def test_audit_trail_for_cross_tenant_blocked(self):
        """Security: cross-tenant access attempts must be logged for forensics."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        svc.data_isolation_validator(
            tenants[0].id, tenants[1].id, resource="invoices"
        )
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.CROSS_TENANT_BLOCKED
        )
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].resource == "invoices"
        assert logs[0].details["target_tenant_id"] == tenants[1].id

    def test_suspension_does_not_leak_config(self):
        """Security: suspended tenant's config should not be accessible
        through context switching but config_get should still work."""
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.set_config(tid, "erp_type", "siigo")
        svc.suspend_tenant(tid)
        # Config is still readable (data preserved, access blocked)
        assert svc.get_config_value(tid, "erp_type") == "siigo"
        # But context switching is blocked
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tid)

    def test_many_tenants_isolation(self):
        """Scalability: isolation holds with many tenants (N=50)."""
        n = 50
        svc = _svc_with(n)
        tenants = svc.list_tenants()
        assert len(tenants) == n

        # Each tenant should only see its own data
        for i, tenant in enumerate(tenants):
            data = [{"tenant_id": t.id, "idx": j} for j, t in enumerate(tenants)]
            result = svc.tenant_scoped_query(tenant.id, "test", data)
            assert len(result) == 1
            assert result[0]["idx"] == i


# ===========================================================================
# 5. Additional Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases for boundary conditions."""

    def test_tenant_name_with_accents(self):
        """Valid tenant name with Spanish accents."""
        svc = MultiTenantService()
        req = _req(name="Despacho José María")
        tenant = svc.create_tenant(req)
        assert tenant.name == "Despacho José María"

    def test_tenant_name_boundary_2_chars(self):
        """Minimum valid name length."""
        svc = MultiTenantService()
        req = _req(name="AB")
        tenant = svc.create_tenant(req)
        assert tenant.name == "AB"

    def test_tenant_name_boundary_100_chars(self):
        """Maximum valid name length."""
        svc = MultiTenantService()
        req = _req(name="A" * 100)
        tenant = svc.create_tenant(req)
        assert len(tenant.name) == 100

    def test_schema_name_boundary_3_chars(self):
        """Minimum valid schema name."""
        ok, _ = validate_schema_name("abc")
        assert ok is True

    def test_schema_name_boundary_63_chars(self):
        """Maximum valid schema name (PostgreSQL limit)."""
        ok, _ = validate_schema_name("a" * 63)
        assert ok is True

    def test_config_key_boundary_1_char(self):
        """Minimum valid config key."""
        ok, _ = validate_tenant_config_key("a")
        assert ok is True

    def test_config_key_boundary_64_chars(self):
        """Maximum valid config key."""
        ok, _ = validate_tenant_config_key("a" * 64)
        assert ok is True

    def test_delete_and_recreate_same_name(self):
        """After soft-delete, same name should be reusable."""
        svc = MultiTenantService()
        t1 = svc.create_tenant(_req(name="Recyclable"))
        svc.delete_tenant(t1.id)
        t2 = svc.create_tenant(_req(name="Recyclable"))
        assert t2.id != t1.id
        assert t2.name == "Recyclable"

    def test_multiple_operations_produce_independent_audit_logs(self):
        """Each tenant's audit log is independent."""
        svc = _svc_with(3)
        tenants = svc.list_tenants()

        # Operations on different tenants
        svc.suspend_tenant(tenants[0].id)
        svc.set_config(tenants[1].id, "k", "v")
        svc.switch_tenant_context(tenants[2].id)

        # Each tenant should only have its own logs
        logs_0 = svc.get_audit_logs(tenants[0].id)
        logs_1 = svc.get_audit_logs(tenants[1].id)
        logs_2 = svc.get_audit_logs(tenants[2].id)

        assert all(l.tenant_id == tenants[0].id for l in logs_0)
        assert all(l.tenant_id == tenants[1].id for l in logs_1)
        assert all(l.tenant_id == tenants[2].id for l in logs_2)

    def test_context_switch_audit_records_from_tenant(self):
        """Context switch audit log records the previous tenant."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id)
        svc.switch_tenant_context(tenants[1].id, user_id="u1", ip_address="10.0.0.1")

        logs = svc.get_audit_logs(tenants[1].id, action=AuditAction.CONTEXT_SWITCHED)
        assert len(logs) >= 1
        assert logs[0].details.get("from_tenant") == tenants[0].id
        assert logs[0].ip_address == "10.0.0.1"
        assert logs[0].user_id == "u1"

    def test_validate_cross_tenant_empty_ids(self):
        """Cross-tenant validation with empty strings."""
        ok, _ = validate_cross_tenant_block("", "")
        assert ok is True  # Same (both empty)

        ok, _ = validate_cross_tenant_block("", "other")
        assert ok is False

    def test_validate_schema_name_reserved_words(self):
        """All reserved schema names are rejected."""
        reserved = [
            "public", "information_schema", "pg_catalog", "pg_toast",
            "schema", "table", "column", "index", "user", "role",
        ]
        for word in reserved:
            ok, _ = validate_schema_name(word)
            assert ok is False, f"Reserved word '{word}' should be rejected"
            # Case-insensitive check
            ok2, _ = validate_schema_name(word.upper())
            assert ok2 is False, f"Reserved word '{word.upper()}' should be rejected"

    def test_router_full_crud_cycle(self):
        """Test the full CRUD cycle through the API routes."""
        app = FastAPI()
        app.include_router(build_multi_tenant_router(
            db=None,
            require_api_key=lambda: {"tenant_id": "test", "key": "test"},
        ))
        client = TestClient(app)

        # Create
        resp = client.post("/api/v1/tenants", json={
            "name": "API Test Tenant", "rfc": "API123"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        tid = data["data"]["id"]

        # Get
        resp = client.get(f"/api/v1/tenants/{tid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "API Test Tenant"

        # Update
        resp = client.put(f"/api/v1/tenants/{tid}", json={
            "name": "Updated Tenant"
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "Updated Tenant"

        # Config
        resp = client.get(f"/api/v1/tenants/{tid}/config")
        assert resp.status_code == 200
        assert "erp_type" in resp.json()["data"]

        # Audit
        resp = client.get(f"/api/v1/tenants/{tid}/audit")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Context switch
        resp = client.post(f"/api/v1/tenants/{tid}/context", json={
            "user_id": "api_user", "user_role": "admin"
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Suspend → Activate → Block → Delete
        resp = client.post(f"/api/v1/tenants/{tid}/suspend")
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/tenants/{tid}/activate")
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/tenants/{tid}/block")
        assert resp.status_code == 200
        resp = client.delete(f"/api/v1/tenants/{tid}")
        assert resp.status_code == 200

    def test_validate_isolation_route(self):
        """Test the /validate-isolation endpoint."""
        app = FastAPI()
        svc = MultiTenantService()
        t1 = svc.create_tenant(_req(name="V1"))
        t2 = svc.create_tenant(_req(name="V2"))

        app.include_router(build_multi_tenant_router(
            db=None,
            require_api_key=lambda: {"tenant_id": "test", "key": "test"},
        ))
        client = TestClient(app)

        # Same tenant → ok
        resp = client.post("/api/v1/tenants/validate-isolation", json={
            "source_tenant_id": t1.id,
            "target_tenant_id": t1.id,
        })
        assert resp.json()["ok"] is True

        # Cross tenant → blocked
        resp = client.post("/api/v1/tenants/validate-isolation", json={
            "source_tenant_id": t1.id,
            "target_tenant_id": t2.id,
            "resource": "invoices",
        })
        assert resp.json()["ok"] is False
