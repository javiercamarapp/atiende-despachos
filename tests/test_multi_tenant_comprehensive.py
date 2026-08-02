# -*- coding: utf-8 -*-
"""
test_multi_tenant_comprehensive.py — Comprehensive tests for Multi-Tenant module.

60+ tests covering:
  1. Tenant CRUD — create, get, update, soft-delete, duplicate/invalid name rejection
  2. Status transitions — suspend, activate, block, delete lifecycle
  3. Context switching — switch context, concurrent context safety via contextvars
  4. Data isolation — cross-tenant blocking, tenant-scoped queries
  5. Config management — set/get config, default values, sensitive config
  6. Audit logging — all actions logged with correct details
  7. Validators — validate_tenant_access, validate_cross_tenant_block, etc.
  8. Module-level convenience functions
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from b2b_ai.features.multi_tenant.models import (
    AuditAction,
    CreateTenantRequest,
    IsolationLevel,
    Tenant,
    TenantAuditLog,
    TenantConfig,
    TenantContext,
    TenantResponse,
    TenantStatus,
)
from b2b_ai.features.multi_tenant.service import (
    MultiTenantService,
    TenantBlockedError,
    TenantConflictError,
    TenantNotFoundError,
    CrossTenantAccessError,
    TENANT_CONFIG_DEFAULTS,
)
from b2b_ai.features.multi_tenant.validators import (
    validate_cross_tenant_block,
    validate_schema_name,
    validate_tenant_access,
    validate_tenant_config_key,
    validate_tenant_name,
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


def _active_tenant(**overrides) -> Tenant:
    defaults = dict(name="Active Tenant", status=TenantStatus.ACTIVE, blocked=False)
    defaults.update(overrides)
    return Tenant(**defaults)


# ===========================================================================
# 1. Tenant CRUD
# ===========================================================================

class TestTenantCreate:
    def test_create_basic(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="Acme Corp"))
        assert t.name == "Acme Corp"
        assert t.status == TenantStatus.ACTIVE
        assert t.id
        assert t.created_at

    def test_create_with_rfc(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="RFC Tenant", rfc="GYA850101XYZ"))
        assert t.rfc == "GYA850101XYZ"

    def test_create_duplicate_name_rejected(self):
        svc = MultiTenantService()
        svc.create_tenant(_req(name="Dup Tenant"))
        with pytest.raises(TenantConflictError):
            svc.create_tenant(_req(name="Dup Tenant"))

    def test_create_duplicate_name_case_insensitive(self):
        svc = MultiTenantService()
        svc.create_tenant(_req(name="Case Tenant"))
        with pytest.raises(TenantConflictError):
            svc.create_tenant(_req(name="case tenant"))

    def test_create_duplicate_allows_deleted_same_name(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="Recycle Name"))
        svc.delete_tenant(t.id)
        t2 = svc.create_tenant(_req(name="Recycle Name"))
        assert t2.id != t.id

    def test_create_empty_name_rejected(self):
        svc = MultiTenantService()
        with pytest.raises(ValueError):
            svc.create_tenant(_req(name=""))

    def test_create_whitespace_only_name_rejected(self):
        svc = MultiTenantService()
        with pytest.raises(ValueError):
            svc.create_tenant(_req(name="   "))

    def test_create_name_too_short(self):
        svc = MultiTenantService()
        with pytest.raises(ValueError, match="al menos 2"):
            svc.create_tenant(_req(name="A"))

    def test_create_name_too_long(self):
        svc = MultiTenantService()
        with pytest.raises(ValueError, match="100 caracteres"):
            svc.create_tenant(_req(name="X" * 101))

    def test_create_name_with_invalid_chars(self):
        svc = MultiTenantService()
        with pytest.raises(ValueError, match="caracteres no válidos"):
            svc.create_tenant(_req(name="Bad@Name!"))

    def test_create_schema_per_tenant(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="Schema Tenant",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        ))
        assert t.isolation_level == IsolationLevel.SCHEMA_PER_TENANT
        assert t.schema_name == "tenant_schema_tenant"

    def test_create_duplicate_schema_rejected(self):
        svc = MultiTenantService()
        svc.create_tenant(_req(
            name="Dup Schema",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        ))
        with pytest.raises(TenantConflictError):
            svc.create_tenant(_req(
                name="Dup Schema",
                isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
            ))

    def test_create_database_per_tenant(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="DB Tenant",
            isolation_level=IsolationLevel.DATABASE_PER_TENANT,
        ))
        assert t.isolation_level == IsolationLevel.DATABASE_PER_TENANT
        assert t.schema_name == ""


class TestTenantRead:
    def test_get_existing(self):
        svc = _svc_with(1)
        tenants = svc.list_tenants()
        t = svc.get_tenant(tenants[0].id)
        assert t.name == "Tenant 1"

    def test_get_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant("no-such-id")

    def test_get_deleted_raises(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant(tid)


class TestTenantUpdate:
    def test_update_name(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.update_tenant(tid, name="New Name")
        assert t.name == "New Name"
        assert t.updated_at is not None

    def test_update_rfc(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.update_tenant(tid, rfc="NEW12345")
        assert t.rfc == "NEW12345"

    def test_update_metadata_merges(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.update_tenant(tid, metadata={"a": 1})
        t = svc.update_tenant(tid, metadata={"b": 2})
        assert t.metadata == {"a": 1, "b": 2}

    def test_update_duplicate_name_rejected(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        with pytest.raises(TenantConflictError):
            svc.update_tenant(tenants[0].id, name=tenants[1].name)

    def test_update_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.update_tenant("no-id", name="X")

    def test_update_invalid_name_rejected(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        with pytest.raises(ValueError):
            svc.update_tenant(tid, name="")

    def test_update_name_too_long_rejected(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        with pytest.raises(ValueError, match="100 caracteres"):
            svc.update_tenant(tid, name="X" * 101)


class TestTenantDelete:
    def test_soft_delete(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        assert svc.delete_tenant(tid) is True
        assert len(svc.list_tenants()) == 0

    def test_deleted_shows_with_flag(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        all_t = svc.list_tenants(include_deleted=True)
        assert len(all_t) == 1
        assert all_t[0].status == TenantStatus.DELETED

    def test_delete_unregisters_schema(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="Del Schema",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        ))
        assert "tenant_del_schema" in svc._schema_registry
        svc.delete_tenant(t.id)
        assert "tenant_del_schema" not in svc._schema_registry

    def test_delete_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.delete_tenant("no-id")


class TestTenantList:
    def test_list_empty(self):
        assert MultiTenantService().list_tenants() == []

    def test_list_multiple(self):
        svc = _svc_with(3)
        assert len(svc.list_tenants()) == 3

    def test_list_filter_by_status(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        assert len(svc.list_tenants(status=TenantStatus.ACTIVE)) == 1
        assert len(svc.list_tenants(status=TenantStatus.SUSPENDED)) == 1


# ===========================================================================
# 2. Status Transitions
# ===========================================================================

class TestStatusTransitions:
    def test_suspend(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.suspend_tenant(tid)
        assert t.status == TenantStatus.SUSPENDED

    def test_activate_from_suspended(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        t = svc.activate_tenant(tid)
        assert t.status == TenantStatus.ACTIVE

    def test_block(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.block_tenant(tid)
        assert t.status == TenantStatus.BLOCKED
        assert t.blocked is True

    def test_delete(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant(tid)

    def test_full_lifecycle_suspend_activate_delete(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        svc.activate_tenant(tid)
        svc.block_tenant(tid)
        svc.delete_tenant(tid)
        assert svc.list_tenants(include_deleted=True)[0].status == TenantStatus.DELETED

    def test_suspend_updates_updated_at(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.suspend_tenant(tid)
        assert t.updated_at is not None

    def test_activate_updates_updated_at(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        t = svc.activate_tenant(tid)
        assert t.updated_at is not None

    def test_block_updates_updated_at(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        t = svc.block_tenant(tid)
        assert t.updated_at is not None


# ===========================================================================
# 3. Context Switching
# ===========================================================================

class TestContextSwitching:
    def test_switch_context(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        ctx = svc.switch_tenant_context(tid, user_id="u1", user_role="admin")
        assert ctx.tenant_id == tid
        assert ctx.user_id == "u1"
        assert ctx.user_role == "admin"

    def test_get_current_context(self):
        svc = MultiTenantService()
        assert svc.get_current_context() is None
        svc.create_tenant(_req(name="Ctx Tenant"))
        tid = svc.list_tenants()[0].id
        svc.switch_tenant_context(tid)
        ctx = svc.get_current_context()
        assert ctx is not None
        assert ctx.tenant_id == tid

    def test_clear_context(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.switch_tenant_context(tid)
        svc.clear_context()
        assert svc.get_current_context() is None

    def test_switch_blocks_suspended_tenant(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tid)

    def test_switch_blocks_blocked_tenant(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.block_tenant(tid)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tid)

    def test_switch_blocks_deleted_tenant(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        with pytest.raises(TenantNotFoundError):
            svc.switch_tenant_context(tid)

    def test_switch_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.switch_tenant_context("no-id")

    def test_context_records_ip(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        ctx = svc.switch_tenant_context(tid, ip_address="10.0.0.1")
        assert ctx.ip_address == "10.0.0.1"

    def test_context_records_isolation_level(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="Iso Tenant",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        ))
        ctx = svc.switch_tenant_context(t.id)
        assert ctx.isolation_level == IsolationLevel.SCHEMA_PER_TENANT
        assert ctx.schema_name == "tenant_iso_tenant"

    def test_context_switch_audit_log(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.switch_tenant_context(tid, user_id="u1")
        logs = svc.get_audit_logs(tid, action=AuditAction.CONTEXT_SWITCHED)
        assert len(logs) >= 1
        assert logs[0].user_id == "u1"

    def test_context_switch_records_from_tenant(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id)
        svc.switch_tenant_context(tenants[1].id)
        logs = svc.get_audit_logs(
            tenants[1].id, action=AuditAction.CONTEXT_SWITCHED
        )
        assert len(logs) >= 1
        assert logs[0].details.get("from_tenant") == tenants[0].id

    def test_contextvar_thread_safety(self):
        """Verify contextvars isolate context across threads."""
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        results = {}
        barrier = threading.Barrier(2)

        def worker(tid, label):
            svc.switch_tenant_context(tid)
            barrier.wait(timeout=5)
            ctx = svc.get_current_context()
            results[label] = ctx.tenant_id if ctx else None

        t1 = threading.Thread(target=worker, args=(tenants[0].id, "a"))
        t2 = threading.Thread(target=worker, args=(tenants[1].id, "b"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        # Each thread's view should match what it set
        assert results["a"] == tenants[0].id
        assert results["b"] == tenants[1].id


# ===========================================================================
# 4. Data Isolation
# ===========================================================================

class TestDataIsolation:
    def test_same_tenant_access_allowed(self):
        svc = MultiTenantService()
        ok, _ = svc.data_isolation_validator("t1", "t1")
        assert ok is True

    def test_cross_tenant_access_blocked(self):
        svc = MultiTenantService()
        ok, err = svc.data_isolation_validator("t1", "t2")
        assert ok is False
        assert "cross-tenant" in err.lower() or "bloqueado" in err.lower()

    def test_cross_tenant_blocked_logged(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        svc.data_isolation_validator(tenants[0].id, tenants[1].id, resource="invoices")
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.CROSS_TENANT_BLOCKED
        )
        assert len(logs) == 1
        assert logs[0].success is False

    def test_scoped_query_filters_by_tenant(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        data = [
            {"tenant_id": tenants[0].id, "amount": 100},
            {"tenant_id": tenants[1].id, "amount": 200},
            {"tenant_id": tenants[0].id, "amount": 300},
        ]
        result = svc.tenant_scoped_query(tenants[0].id, "invoices", data)
        assert len(result) == 2
        assert all(r["tenant_id"] == tenants[0].id for r in result)

    def test_scoped_query_empty_data(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        assert svc.tenant_scoped_query(tid, "invoices", []) == []

    def test_scoped_query_with_filters(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        data = [
            {"tenant_id": tid, "status": "active", "amount": 100},
            {"tenant_id": tid, "status": "inactive", "amount": 200},
        ]
        result = svc.tenant_scoped_query(tid, "inv", data, filters={"status": "active"})
        assert len(result) == 1
        assert result[0]["status"] == "active"

    def test_scoped_query_skips_tenant_id_in_filters(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        data = [
            {"tenant_id": tenants[0].id, "amount": 100},
            {"tenant_id": tenants[1].id, "amount": 200},
        ]
        result = svc.tenant_scoped_query(
            tenants[0].id, "inv", data,
            filters={"tenant_id": tenants[1].id},
        )
        assert len(result) == 1
        assert result[0]["tenant_id"] == tenants[0].id

    def test_scoped_query_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.tenant_scoped_query("no-id", "inv", [])

    def test_scoped_query_audit_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.tenant_scoped_query(tid, "invoices", [{"tenant_id": tid}])
        logs = svc.get_audit_logs(tid, action=AuditAction.DATA_ACCESSED)
        assert len(logs) >= 1
        assert logs[0].resource == "invoices"

    def test_scoped_query_no_matching_tenant_returns_empty(self):
        svc = _svc_with(2)
        tenants = svc.list_tenants()
        data = [{"tenant_id": tenants[1].id, "amount": 999}]
        result = svc.tenant_scoped_query(tenants[0].id, "inv", data)
        assert result == []


# ===========================================================================
# 5. Config Management
# ===========================================================================

class TestConfigManagement:
    def test_defaults_loaded_on_create(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="Cfg Tenant"))
        cfg = svc.get_config(t.id)
        assert cfg["erp_type"] == "contpaqi"
        assert cfg["plantilla_contable"] == "SAT"
        assert cfg["notif_channel"] == "email"

    def test_set_config(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        cfg = svc.set_config(tid, "custom_key", "custom_val")
        assert cfg.value == "custom_val"
        assert cfg.key == "custom_key"

    def test_get_config_value(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.set_config(tid, "mykey", "myval")
        assert svc.get_config_value(tid, "mykey") == "myval"

    def test_get_config_value_fallback_to_default(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        assert svc.get_config_value(tid, "erp_type") == "contpaqi"

    def test_get_config_value_nonexistent_returns_default_or_none(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        assert svc.get_config_value(tid, "totally_unknown") is None

    def test_update_existing_config(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.set_config(tid, "key1", "v1")
        cfg = svc.set_config(tid, "key1", "v2")
        assert cfg.value == "v2"
        assert cfg.updated_at is not None

    def test_delete_config(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.set_config(tid, "to_delete", "val")
        assert svc.delete_config(tid, "to_delete") is True
        assert svc.get_config_value(tid, "to_delete") is None

    def test_delete_config_nonexistent_returns_false(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        assert svc.delete_config(tid, "no_key") is False

    def test_sensitive_config_flag(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        cfg = svc.set_config(tid, "api_secret", "abc123", sensitive=True)
        assert cfg.sensitive is True

    def test_config_with_description(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        cfg = svc.set_config(tid, "desc_key", "val", description="My desc")
        assert cfg.description == "My desc"

    def test_config_overrides_defaults(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="Override Cfg",
            config={"erp_type": "siigo"},
        ))
        assert svc.get_config_value(t.id, "erp_type") == "siigo"

    def test_extra_config_not_in_defaults(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(
            name="Extra Cfg",
            config={"custom_field": "hello"},
        ))
        assert svc.get_config_value(t.id, "custom_field") == "hello"

    def test_get_config_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.get_config("no-id")

    def test_set_config_nonexistent_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.set_config("no-id", "k", "v")

    def test_all_defaults_present(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="All Defaults"))
        cfg = svc.get_config(t.id)
        for key, val in TENANT_CONFIG_DEFAULTS.items():
            assert cfg[key] == val


# ===========================================================================
# 6. Audit Logging
# ===========================================================================

class TestAuditLogging:
    def test_create_logged(self):
        svc = MultiTenantService()
        t = svc.create_tenant(_req(name="Audit Tenant"))
        logs = svc.get_audit_logs(t.id, action=AuditAction.TENANT_CREATED)
        assert len(logs) == 1
        assert logs[0].details["name"] == "Audit Tenant"

    def test_update_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.update_tenant(tid, name="Updated")
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_UPDATED)
        assert len(logs) >= 1

    def test_suspend_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_SUSPENDED)
        assert len(logs) == 1

    def test_activate_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        svc.activate_tenant(tid)
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_ACTIVATED)
        assert len(logs) == 1

    def test_block_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.block_tenant(tid)
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_BLOCKED)
        assert len(logs) == 1

    def test_delete_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_DELETED)
        assert len(logs) == 1

    def test_config_updated_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.set_config(tid, "k", "v")
        logs = svc.get_audit_logs(tid, action=AuditAction.CONFIG_UPDATED)
        assert len(logs) >= 1
        assert logs[0].details["key"] == "k"

    def test_data_access_logged(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.tenant_scoped_query(tid, "invoices", [{"tenant_id": tid, "x": 1}])
        logs = svc.get_audit_logs(tid, action=AuditAction.DATA_ACCESSED)
        assert len(logs) >= 1

    def test_get_audit_logs_not_found_raises(self):
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.get_audit_logs("no-id")

    def test_audit_logs_accessible_for_deleted_tenant(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.delete_tenant(tid)
        logs = svc.get_audit_logs(tid)
        assert any(l.action == AuditAction.TENANT_DELETED for l in logs)

    def test_audit_logs_sorted_newest_first(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        svc.activate_tenant(tid)
        svc.block_tenant(tid)
        logs = svc.get_audit_logs(tid)
        timestamps = [l.timestamp for l in logs]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_audit_logs_filter_by_action(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.suspend_tenant(tid)
        svc.activate_tenant(tid)
        logs = svc.get_audit_logs(tid, action=AuditAction.TENANT_ACTIVATED)
        assert all(l.action == AuditAction.TENANT_ACTIVATED for l in logs)

    def test_audit_logs_limit(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        for _ in range(5):
            svc.suspend_tenant(tid)
            svc.activate_tenant(tid)
        logs = svc.get_audit_logs(tid, limit=3)
        assert len(logs) <= 3

    def test_audit_logs_include_ip_address(self):
        svc = _svc_with(1)
        tid = svc.list_tenants()[0].id
        svc.switch_tenant_context(tid, ip_address="192.168.1.1")
        logs = svc.get_audit_logs(tid, action=AuditAction.CONTEXT_SWITCHED)
        assert logs[0].ip_address == "192.168.1.1"


# ===========================================================================
# 7. Validators
# ===========================================================================

class TestValidateTenantAccess:
    def test_active_allowed(self):
        ok, _ = validate_tenant_access(_active_tenant())
        assert ok is True

    def test_deleted_denied(self):
        ok, err = validate_tenant_access(_active_tenant(status=TenantStatus.DELETED))
        assert ok is False
        assert "eliminado" in err.lower()

    def test_blocked_denied(self):
        ok, err = validate_tenant_access(_active_tenant(status=TenantStatus.BLOCKED))
        assert ok is False
        assert "bloqueado" in err.lower()

    def test_blocked_flag_denied(self):
        ok, _ = validate_tenant_access(_active_tenant(blocked=True))
        assert ok is False

    def test_suspended_denied(self):
        ok, err = validate_tenant_access(_active_tenant(status=TenantStatus.SUSPENDED))
        assert ok is False
        assert "suspendido" in err.lower()

    def test_pending_denied(self):
        ok, err = validate_tenant_access(_active_tenant(status=TenantStatus.PENDING))
        assert ok is False
        assert "pendiente" in err.lower()

    def test_blocked_status_and_flag(self):
        ok, _ = validate_tenant_access(
            _active_tenant(status=TenantStatus.BLOCKED, blocked=True)
        )
        assert ok is False


class TestValidateCrossTenantBlock:
    def test_same_tenant_allowed(self):
        ok, _ = validate_cross_tenant_block("t1", "t1")
        assert ok is True

    def test_different_tenants_blocked(self):
        ok, err = validate_cross_tenant_block("t1", "t2")
        assert ok is False
        assert "t1" in err
        assert "t2" in err

    def test_empty_ids_different(self):
        ok, _ = validate_cross_tenant_block("", "x")
        assert ok is False

    def test_empty_ids_same(self):
        ok, _ = validate_cross_tenant_block("", "")
        assert ok is True


class TestValidateTenantName:
    def test_valid_name(self):
        ok, _ = validate_tenant_name("Mi Despacho")
        assert ok is True

    def test_empty_rejected(self):
        ok, err = validate_tenant_name("")
        assert ok is False
        assert "vacío" in err.lower()

    def test_whitespace_rejected(self):
        ok, _ = validate_tenant_name("   ")
        assert ok is False

    def test_too_short(self):
        ok, _ = validate_tenant_name("A")
        assert ok is False

    def test_too_long(self):
        ok, _ = validate_tenant_name("X" * 101)
        assert ok is False

    def test_invalid_chars(self):
        ok, _ = validate_tenant_name("Bad@Name!")
        assert ok is False

    def test_valid_with_accents(self):
        ok, _ = validate_tenant_name("Despacho José")
        assert ok is True

    def test_valid_with_hyphens_underscores(self):
        ok, _ = validate_tenant_name("My-Company_2.0")
        assert ok is True

    def test_boundary_2_chars(self):
        ok, _ = validate_tenant_name("AB")
        assert ok is True

    def test_boundary_100_chars(self):
        ok, _ = validate_tenant_name("A" * 100)
        assert ok is True

    def test_just_spaces_rejected(self):
        ok, _ = validate_tenant_name("  ")
        assert ok is False


class TestValidateSchemaName:
    def test_valid(self):
        ok, _ = validate_schema_name("tenant_my_company")
        assert ok is True

    def test_empty_rejected(self):
        ok, _ = validate_schema_name("")
        assert ok is False

    def test_whitespace_rejected(self):
        ok, _ = validate_schema_name("   ")
        assert ok is False

    def test_too_short(self):
        ok, _ = validate_schema_name("ab")
        assert ok is False

    def test_too_long(self):
        ok, _ = validate_schema_name("x" * 64)
        assert ok is False

    def test_starts_with_digit_rejected(self):
        ok, _ = validate_schema_name("1schema")
        assert ok is False

    def test_starts_with_hyphen_rejected(self):
        ok, _ = validate_schema_name("-schema")
        assert ok is False

    def test_valid_starts_with_underscore(self):
        ok, _ = validate_schema_name("_private")
        assert ok is True

    def test_reserved_word_public(self):
        ok, _ = validate_schema_name("public")
        assert ok is False

    def test_reserved_word_information_schema(self):
        ok, _ = validate_schema_name("information_schema")
        assert ok is False

    def test_reserved_word_pg_catalog(self):
        ok, _ = validate_schema_name("pg_catalog")
        assert ok is False

    def test_reserved_word_pg_toast(self):
        ok, _ = validate_schema_name("pg_toast")
        assert ok is False

    def test_reserved_word_schema(self):
        ok, _ = validate_schema_name("schema")
        assert ok is False

    def test_reserved_word_table(self):
        ok, _ = validate_schema_name("table")
        assert ok is False

    def test_reserved_word_column(self):
        ok, _ = validate_schema_name("column")
        assert ok is False

    def test_reserved_word_user(self):
        ok, _ = validate_schema_name("user")
        assert ok is False

    def test_invalid_chars(self):
        ok, _ = validate_schema_name("has space")
        assert ok is False

    def test_valid_boundary_3_chars(self):
        ok, _ = validate_schema_name("abc")
        assert ok is True

    def test_valid_boundary_63_chars(self):
        ok, _ = validate_schema_name("a" * 63)
        assert ok is True

    def test_reserved_word_case_insensitive(self):
        ok, _ = validate_schema_name("PUBLIC")
        assert ok is False


class TestValidateTenantConfigKey:
    def test_valid(self):
        ok, _ = validate_tenant_config_key("erp_type")
        assert ok is True

    def test_empty_rejected(self):
        ok, _ = validate_tenant_config_key("")
        assert ok is False

    def test_whitespace_rejected(self):
        ok, _ = validate_tenant_config_key("  ")
        assert ok is False

    def test_too_long(self):
        ok, _ = validate_tenant_config_key("k" * 65)
        assert ok is False

    def test_uppercase_rejected(self):
        ok, _ = validate_tenant_config_key("MyKey")
        assert ok is False

    def test_starts_with_digit_rejected(self):
        ok, _ = validate_tenant_config_key("1key")
        assert ok is False

    def test_starts_with_underscore_rejected(self):
        ok, _ = validate_tenant_config_key("_key")
        assert ok is False

    def test_with_hyphen_rejected(self):
        ok, _ = validate_tenant_config_key("my-key")
        assert ok is False

    def test_valid_with_underscores(self):
        ok, _ = validate_tenant_config_key("my_cool_key")
        assert ok is True

    def test_valid_with_numbers(self):
        ok, _ = validate_tenant_config_key("key2")
        assert ok is True

    def test_boundary_1_char(self):
        ok, _ = validate_tenant_config_key("a")
        assert ok is True

    def test_boundary_64_chars(self):
        ok, _ = validate_tenant_config_key("a" * 64)
        assert ok is True


# ===========================================================================
# 8. Module-level Convenience Functions
# ===========================================================================

class TestModuleLevelFunctions:
    def test_create_tenant_function(self):
        import b2b_ai.features.multi_tenant.service as mod
        old = mod._default_service
        try:
            mod._default_service = None
            from b2b_ai.features.multi_tenant.service import (
                create_tenant as create_fn,
            )
            t = create_fn(_req(name="Func Tenant"))
            assert t.name == "Func Tenant"
        finally:
            mod._default_service = old

    def test_switch_tenant_context_function(self):
        import b2b_ai.features.multi_tenant.service as mod
        old = mod._default_service
        try:
            mod._default_service = None
            from b2b_ai.features.multi_tenant.service import (
                switch_tenant_context as switch_fn,
            )
            from b2b_ai.features.multi_tenant.service import (
                create_tenant as create_fn,
            )
            t = create_fn(_req(name="Switch Func"))
            ctx = switch_fn(t.id, user_id="u1")
            assert ctx.tenant_id == t.id
        finally:
            mod._default_service = old

    def test_tenant_scoped_query_function(self):
        import b2b_ai.features.multi_tenant.service as mod
        old = mod._default_service
        try:
            mod._default_service = None
            from b2b_ai.features.multi_tenant.service import (
                tenant_scoped_query as query_fn,
                create_tenant as create_fn,
            )
            t = create_fn(_req(name="Query Func"))
            data = [{"tenant_id": t.id, "v": 1}, {"tenant_id": "other", "v": 2}]
            result = query_fn(t.id, "res", data)
            assert len(result) == 1
        finally:
            mod._default_service = old

    def test_data_isolation_validator_function(self):
        import b2b_ai.features.multi_tenant.service as mod
        old = mod._default_service
        try:
            mod._default_service = None
            from b2b_ai.features.multi_tenant.service import (
                data_isolation_validator as iso_fn,
            )
            ok, _ = iso_fn("a", "a")
            assert ok is True
            ok, _ = iso_fn("a", "b")
            assert ok is False
        finally:
            mod._default_service = old

    def test_get_service_singleton(self):
        import b2b_ai.features.multi_tenant.service as mod
        old = mod._default_service
        try:
            mod._default_service = None
            from b2b_ai.features.multi_tenant.service import _get_service
            svc1 = _get_service()
            svc2 = _get_service()
            assert svc1 is svc2
        finally:
            mod._default_service = old


# ===========================================================================
# 9. Tenant Model Edge Cases
# ===========================================================================

class TestTenantModel:
    def test_default_id_is_uuid(self):
        t = Tenant(name="Test")
        assert len(t.id) == 36  # UUID format

    def test_unique_ids(self):
        t1 = Tenant(name="A")
        t2 = Tenant(name="B")
        assert t1.id != t2.id

    def test_default_status_pending(self):
        t = Tenant(name="Test")
        assert t.status == TenantStatus.PENDING

    def test_default_isolation_shared(self):
        t = Tenant(name="Test")
        assert t.isolation_level == IsolationLevel.SHARED_SCHEMA

    def test_name_stripped(self):
        t = Tenant(name="  Padded  ")
        assert t.name == "Padded"

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            Tenant(name="")

    def test_tenant_config_default_sensitive_false(self):
        tc = TenantConfig(tenant_id="t1", key="k", value="v")
        assert tc.sensitive is False

    def test_tenant_config_empty_key_rejected(self):
        with pytest.raises(ValueError):
            TenantConfig(tenant_id="t1", key="", value="v")

    def test_audit_log_success_default_true(self):
        log = TenantAuditLog(
            tenant_id="t1", action=AuditAction.TENANT_CREATED
        )
        assert log.success is True

    def test_tenant_context_defaults(self):
        ctx = TenantContext(tenant_id="t1")
        assert ctx.tenant_name is None
        assert ctx.user_id is None
        assert ctx.isolation_level == IsolationLevel.SHARED_SCHEMA

    def test_create_tenant_request_defaults(self):
        req = CreateTenantRequest(name="Test")
        assert req.rfc == ""
        assert req.isolation_level == IsolationLevel.SHARED_SCHEMA
        assert req.config == {}
        assert req.metadata == {}

    def test_tenant_response(self):
        resp = TenantResponse(ok=True, message="Done", data={"id": "1"})
        assert resp.ok is True
        assert resp.data == {"id": "1"}

    def test_tenant_response_defaults(self):
        resp = TenantResponse(ok=True)
        assert resp.message == ""
        assert resp.data is None

    def test_tenant_config_timestamps(self):
        tc = TenantConfig(tenant_id="t1", key="k", value="v")
        assert tc.created_at is not None
        assert tc.updated_at is None

    def test_tenant_blocked_default_false(self):
        t = Tenant(name="Test")
        assert t.blocked is False
