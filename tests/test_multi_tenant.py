# -*- coding: utf-8 -*-
"""
test_multi_tenant.py — Tests for Multi-Tenant Data Isolation module.

Minimum 80 tests covering:
  - Tenant CRUD (create, read, update, delete, list)
  - Schema isolation (schema_per_tenant, shared_schema)
  - Cross-tenant data blocking
  - Tenant-scoped queries
  - Audit logging
  - Configuration management
  - Context switching
  - Validators
  - API routes
  - Edge cases and error handling
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.multi_tenant.models import (
    AuditAction,
    CreateTenantRequest,
    IsolationLevel,
    Tenant,
    TenantAuditLog,
    TenantConfig,
    TenantContext,
    TenantStatus,
)
from b2b_ai.features.multi_tenant.service import (
    CrossTenantAccessError,
    MultiTenantService,
    TenantBlockedError,
    TenantConflictError,
    TenantNotFoundError,
)
from b2b_ai.features.multi_tenant.validators import (
    validate_cross_tenant_block,
    validate_schema_name,
    validate_tenant_access,
    validate_tenant_config_key,
    validate_tenant_name,
)
from b2b_ai.features.multi_tenant.routes import build_multi_tenant_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_create_request(**overrides) -> CreateTenantRequest:
    defaults = dict(
        name="Despacho Test",
        rfc="TST010101XYZ",
        isolation_level=IsolationLevel.SHARED_SCHEMA,
        config={},
        metadata={},
    )
    defaults.update(overrides)
    return CreateTenantRequest(**defaults)


def _make_tenant(**overrides) -> Tenant:
    defaults = dict(
        name="Tenant Test",
        rfc="TST010101XYZ",
        isolation_level=IsolationLevel.SHARED_SCHEMA,
        status=TenantStatus.ACTIVE,
        config={},
        metadata={},
        blocked=False,
    )
    defaults.update(overrides)
    return Tenant(**defaults)


def _make_service_with_tenants(count: int = 2) -> MultiTenantService:
    """Create a service with pre-populated tenants."""
    svc = MultiTenantService()
    for i in range(count):
        svc.create_tenant(_make_create_request(
            name=f"Tenant {i+1}",
            rfc=f"RFC{i+1:03d}",
        ))
    return svc


# ===========================================================================
# 1. Tenant CRUD Tests
# ===========================================================================

class TestTenantCreate:
    """Test tenant creation."""

    def test_create_tenant_basic(self):
        """Create a basic tenant."""
        svc = MultiTenantService()
        req = _make_create_request(name="Mi Despacho")
        tenant = svc.create_tenant(req)
        assert tenant.name == "Mi Despacho"
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.id

    def test_create_tenant_with_rfc(self):
        """Create a tenant with RFC."""
        svc = MultiTenantService()
        req = _make_create_request(name="Despacho RFC", rfc="GYA850101XYZ")
        tenant = svc.create_tenant(req)
        assert tenant.rfc == "GYA850101XYZ"

    def test_create_tenant_with_config(self):
        """Create a tenant with initial config."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Despacho Config",
            config={"erp_type": "csv", "notif_channel": "slack"},
        )
        tenant = svc.create_tenant(req)
        config = svc.get_config(tenant.id)
        assert config["erp_type"] == "csv"
        assert config["notif_channel"] == "slack"

    def test_create_tenant_with_metadata(self):
        """Create a tenant with metadata."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Despacho Meta",
            metadata={"sector": "contabilidad", "employees": 10},
        )
        tenant = svc.create_tenant(req)
        assert tenant.metadata["sector"] == "contabilidad"

    def test_create_tenant_duplicate_name_fails(self):
        """Cannot create tenant with duplicate name."""
        svc = MultiTenantService()
        req1 = _make_create_request(name="Despacho Dup")
        svc.create_tenant(req1)
        req2 = _make_create_request(name="Despacho Dup")
        with pytest.raises(TenantConflictError):
            svc.create_tenant(req2)

    def test_create_tenant_duplicate_name_case_insensitive(self):
        """Duplicate name check is case-insensitive."""
        svc = MultiTenantService()
        req1 = _make_create_request(name="Mi Despacho")
        svc.create_tenant(req1)
        req2 = _make_create_request(name="mi despacho")
        with pytest.raises(TenantConflictError):
            svc.create_tenant(req2)

    def test_create_tenant_empty_name_fails(self):
        """Cannot create tenant with empty name."""
        svc = MultiTenantService()
        req = _make_create_request(name="")
        with pytest.raises(ValueError):
            svc.create_tenant(req)

    def test_create_tenant_schema_per_tenant(self):
        """Create tenant with schema_per_tenant isolation."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Despacho Schema",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        tenant = svc.create_tenant(req)
        assert tenant.isolation_level == IsolationLevel.SCHEMA_PER_TENANT
        assert tenant.schema_name == "tenant_despacho_schema"

    def test_create_tenant_duplicate_schema_fails(self):
        """Cannot create two tenants with same schema name."""
        svc = MultiTenantService()
        req1 = _make_create_request(
            name="Despacho Schema Dup",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        svc.create_tenant(req1)
        req2 = _make_create_request(
            name="Despacho Schema Dup",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        with pytest.raises(TenantConflictError):
            svc.create_tenant(req2)


class TestTenantRead:
    """Test tenant retrieval."""

    def test_get_tenant_existing(self):
        """Get an existing tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        tenant = svc.get_tenant(tenants[0].id)
        assert tenant.name == "Tenant 1"

    def test_get_tenant_nonexistent_fails(self):
        """Getting a non-existent tenant raises error."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant("nonexistent-id")

    def test_get_tenant_deleted_fails(self):
        """Getting a deleted tenant raises error."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.delete_tenant(tenants[0].id)
        with pytest.raises(TenantNotFoundError):
            svc.get_tenant(tenants[0].id)


class TestTenantUpdate:
    """Test tenant updates."""

    def test_update_tenant_name(self):
        """Update tenant name."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        updated = svc.update_tenant(tenants[0].id, name="Nuevo Nombre")
        assert updated.name == "Nuevo Nombre"
        assert updated.updated_at is not None

    def test_update_tenant_rfc(self):
        """Update tenant RFC."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        updated = svc.update_tenant(tenants[0].id, rfc="NEW123456")
        assert updated.rfc == "NEW123456"

    def test_update_tenant_metadata(self):
        """Update tenant metadata."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        updated = svc.update_tenant(
            tenants[0].id, metadata={"new_key": "new_value"}
        )
        assert updated.metadata["new_key"] == "new_value"

    def test_update_tenant_duplicate_name_fails(self):
        """Cannot update to a duplicate name."""
        svc = _make_service_with_tenants(2)
        tenants = svc.list_tenants()
        with pytest.raises(TenantConflictError):
            svc.update_tenant(tenants[0].id, name=tenants[1].name)

    def test_update_tenant_nonexistent_fails(self):
        """Updating non-existent tenant raises error."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.update_tenant("nonexistent", name="X")


class TestTenantDelete:
    """Test tenant deletion."""

    def test_delete_tenant(self):
        """Soft-delete a tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        assert svc.delete_tenant(tenants[0].id) is True
        assert len(svc.list_tenants()) == 0

    def test_delete_tenant_not_in_list(self):
        """Deleted tenant not in default list."""
        svc = _make_service_with_tenants(2)
        tenants = svc.list_tenants()
        svc.delete_tenant(tenants[0].id)
        remaining = svc.list_tenants()
        assert len(remaining) == 1
        assert remaining[0].id == tenants[1].id

    def test_delete_tenant_included_if_requested(self):
        """Deleted tenant appears when include_deleted=True."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.delete_tenant(tenants[0].id)
        all_tenants = svc.list_tenants(include_deleted=True)
        assert len(all_tenants) == 1
        assert all_tenants[0].status == TenantStatus.DELETED

    def test_delete_tenant_unregisters_schema(self):
        """Deleting a tenant unregisters its schema."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Schema Tenant",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        tenant = svc.create_tenant(req)
        assert "tenant_schema_tenant" in svc._schema_registry
        svc.delete_tenant(tenant.id)
        assert "tenant_schema_tenant" not in svc._schema_registry

    def test_delete_tenant_nonexistent_fails(self):
        """Deleting non-existent tenant raises error."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.delete_tenant("nonexistent")


class TestTenantList:
    """Test tenant listing."""

    def test_list_tenants_empty(self):
        """List tenants when none exist."""
        svc = MultiTenantService()
        assert svc.list_tenants() == []

    def test_list_tenants_multiple(self):
        """List multiple tenants."""
        svc = _make_service_with_tenants(3)
        tenants = svc.list_tenants()
        assert len(tenants) == 3

    def test_list_tenants_filter_by_status(self):
        """Filter tenants by status."""
        svc = _make_service_with_tenants(2)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        active = svc.list_tenants(status=TenantStatus.ACTIVE)
        suspended = svc.list_tenants(status=TenantStatus.SUSPENDED)
        assert len(active) == 1
        assert len(suspended) == 1


# ===========================================================================
# 2. Schema Isolation Tests
# ===========================================================================

class TestSchemaIsolation:
    """Test schema-level isolation."""

    def test_shared_schema_tenant(self):
        """Shared schema tenant has no schema_name."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Shared",
            isolation_level=IsolationLevel.SHARED_SCHEMA,
        )
        tenant = svc.create_tenant(req)
        assert tenant.schema_name == ""

    def test_schema_per_tenant_generation(self):
        """Schema name is auto-generated for schema_per_tenant."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Mi Despacho",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        tenant = svc.create_tenant(req)
        assert tenant.schema_name == "tenant_mi_despacho"

    def test_schema_registry_tracking(self):
        """Schemas are tracked in registry."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="Track Schema",
            isolation_level=IsolationLevel.SCHEMA_PER_TENANT,
        )
        tenant = svc.create_tenant(req)
        assert svc._schema_registry["tenant_track_schema"] == tenant.id

    def test_database_per_tenant_isolation_level(self):
        """Database_per_tenant is a valid isolation level."""
        svc = MultiTenantService()
        req = _make_create_request(
            name="DB Tenant",
            isolation_level=IsolationLevel.DATABASE_PER_TENANT,
        )
        tenant = svc.create_tenant(req)
        assert tenant.isolation_level == IsolationLevel.DATABASE_PER_TENANT


# ===========================================================================
# 3. Cross-Tenant Data Blocking Tests
# ===========================================================================

class TestCrossTenantBlocking:
    """Test cross-tenant access blocking."""

    def test_same_tenant_access_allowed(self):
        """Access to own tenant data is allowed."""
        svc = MultiTenantService()
        is_valid, err = svc.data_isolation_validator("t1", "t1")
        assert is_valid is True
        assert err == ""

    def test_cross_tenant_access_blocked(self):
        """Cross-tenant access is blocked."""
        svc = MultiTenantService()
        is_valid, err = svc.data_isolation_validator("t1", "t2")
        assert is_valid is False
        assert "cross-tenant" in err.lower() or "bloqueado" in err.lower()

    def test_cross_tenant_blocked_logged(self):
        """Cross-tenant access attempt is logged."""
        svc = MultiTenantService()
        svc.create_tenant(_make_create_request(name="Source Tenant"))
        svc.create_tenant(_make_create_request(name="Target Tenant"))
        tenants = svc.list_tenants()
        svc.data_isolation_validator(tenants[0].id, tenants[1].id, resource="invoices")
        logs = svc.get_audit_logs(tenants[0].id, action=AuditAction.CROSS_TENANT_BLOCKED)
        assert len(logs) == 1
        assert logs[0].success is False

    def test_cross_tenant_with_resource(self):
        """Cross-tenant validation includes resource info."""
        svc = MultiTenantService()
        svc.create_tenant(_make_create_request(name="Source"))
        svc.create_tenant(_make_create_request(name="Target"))
        tenants = svc.list_tenants()
        is_valid, err = svc.data_isolation_validator(
            tenants[0].id, tenants[1].id, resource="invoices"
        )
        assert is_valid is False


# ===========================================================================
# 4. Tenant-Scoped Query Tests
# ===========================================================================

class TestTenantScopedQuery:
    """Test tenant-scoped queries."""

    def test_scoped_query_filters_by_tenant(self):
        """Query returns only data belonging to the tenant."""
        svc = _make_service_with_tenants(2)
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
        """Query with empty data returns empty list."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        result = svc.tenant_scoped_query(tenants[0].id, "invoices", [])
        assert result == []

    def test_scoped_query_no_matching_data(self):
        """Query returns empty when no data matches tenant."""
        svc = _make_service_with_tenants(2)
        tenants = svc.list_tenants()
        data = [{"tenant_id": tenants[1].id, "amount": 100}]
        result = svc.tenant_scoped_query(tenants[0].id, "invoices", data)
        assert result == []

    def test_scoped_query_with_filters(self):
        """Query supports additional filters."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        data = [
            {"tenant_id": tenants[0].id, "status": "active", "amount": 100},
            {"tenant_id": tenants[0].id, "status": "inactive", "amount": 200},
            {"tenant_id": tenants[0].id, "status": "active", "amount": 300},
        ]
        result = svc.tenant_scoped_query(
            tenants[0].id, "invoices", data, filters={"status": "active"}
        )
        assert len(result) == 2
        assert all(r["status"] == "active" for r in result)

    def test_scoped_query_ignores_tenant_id_in_filters(self):
        """tenant_id filter is ignored (already applied)."""
        svc = _make_service_with_tenants(2)
        tenants = svc.list_tenants()
        data = [
            {"tenant_id": tenants[0].id, "amount": 100},
            {"tenant_id": tenants[1].id, "amount": 200},
        ]
        result = svc.tenant_scoped_query(
            tenants[0].id, "invoices", data,
            filters={"tenant_id": tenants[1].id},
        )
        # tenant_id filter is skipped, so only tenant_id filter applies
        assert len(result) == 1
        assert result[0]["tenant_id"] == tenants[0].id

    def test_scoped_query_logged(self):
        """Scoped queries are audit-logged."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        data = [{"tenant_id": tenants[0].id, "amount": 100}]
        svc.tenant_scoped_query(tenants[0].id, "invoices", data)
        logs = svc.get_audit_logs(tenants[0].id, action=AuditAction.DATA_ACCESSED)
        assert len(logs) >= 1

    def test_scoped_query_nonexistent_tenant_fails(self):
        """Query for non-existent tenant raises error."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.tenant_scoped_query("nonexistent", "invoices", [])


# ===========================================================================
# 5. Audit Logging Tests
# ===========================================================================

class TestAuditLogging:
    """Test audit log functionality."""

    def test_audit_log_created_on_tenant_create(self):
        """Audit log is created when tenant is created."""
        svc = MultiTenantService()
        req = _make_create_request(name="Audit Tenant")
        tenant = svc.create_tenant(req)
        logs = svc.get_audit_logs(tenant.id)
        created_logs = [l for l in logs if l.action == AuditAction.TENANT_CREATED]
        assert len(created_logs) == 1
        assert created_logs[0].action == AuditAction.TENANT_CREATED

    def test_audit_log_created_on_context_switch(self):
        """Audit log is created on context switch."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id, user_id="user1")
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.CONTEXT_SWITCHED
        )
        assert len(logs) == 1

    def test_audit_log_created_on_config_update(self):
        """Audit log is created on config update."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "custom_audit_key", "custom_value")
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.CONFIG_UPDATED
        )
        # At least 1 explicit config update + default configs
        assert len(logs) >= 1
        # The last one should be our explicit update
        custom_logs = [l for l in logs if l.details.get("key") == "custom_audit_key"]
        assert len(custom_logs) == 1

    def test_audit_log_created_on_suspend(self):
        """Audit log is created on tenant suspend."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.TENANT_SUSPENDED
        )
        assert len(logs) == 1

    def test_audit_log_created_on_block(self):
        """Audit log is created on tenant block."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.block_tenant(tenants[0].id)
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.TENANT_BLOCKED
        )
        assert len(logs) == 1

    def test_audit_log_created_on_delete(self):
        """Audit log is created on tenant delete."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.delete_tenant(tenants[0].id)
        logs = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.TENANT_DELETED
        )
        # At least 1 delete log (audit logs are still accessible for deleted tenants)
        assert len(logs) >= 1

    def test_audit_log_limit(self):
        """Audit log respects limit parameter."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        for _ in range(5):
            svc.set_config(tenants[0].id, "test_key", "value")
        logs = svc.get_audit_logs(tenants[0].id, limit=3)
        assert len(logs) == 3

    def test_audit_log_filter_by_action(self):
        """Audit log can be filtered by action type."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "key1", "val1")
        svc.set_config(tenants[0].id, "key2", "val2")
        logs_all = svc.get_audit_logs(tenants[0].id)
        logs_config = svc.get_audit_logs(
            tenants[0].id, action=AuditAction.CONFIG_UPDATED
        )
        assert len(logs_all) >= 3  # created + 2 config
        # At least 2 explicit config updates + default config logs
        assert len(logs_config) >= 2

    def test_audit_log_timestamp(self):
        """Audit log entries have timestamps."""
        svc = MultiTenantService()
        req = _make_create_request(name="Timestamp Tenant")
        tenant = svc.create_tenant(req)
        logs = svc.get_audit_logs(tenant.id)
        assert logs[0].timestamp is not None
        assert "T" in logs[0].timestamp  # ISO format


# ===========================================================================
# 6. Configuration Management Tests
# ===========================================================================

class TestConfigManagement:
    """Test tenant configuration management."""

    def test_get_config_defaults(self):
        """Config includes defaults."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        config = svc.get_config(tenants[0].id)
        assert "erp_type" in config
        assert "notif_channel" in config

    def test_set_config_value(self):
        """Set a config value."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        cfg = svc.set_config(tenants[0].id, "erp_type", "csv")
        assert cfg.key == "erp_type"
        assert cfg.value == "csv"

    def test_get_config_value(self):
        """Get a specific config value."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "custom_key", "custom_value")
        value = svc.get_config_value(tenants[0].id, "custom_key")
        assert value == "custom_value"

    def test_get_config_value_default(self):
        """Get config value returns default if not set."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        value = svc.get_config_value(tenants[0].id, "erp_type")
        assert value == "contpaqi"  # default

    def test_update_config_value(self):
        """Update an existing config value."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "erp_type", "csv")
        svc.set_config(tenants[0].id, "erp_type", "aspel")
        value = svc.get_config_value(tenants[0].id, "erp_type")
        assert value == "aspel"

    def test_delete_config_value(self):
        """Delete a config value."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "temp_key", "temp_value")
        assert svc.delete_config(tenants[0].id, "temp_key") is True
        # Should revert to default if it's a default key, or be None
        value = svc.get_config_value(tenants[0].id, "temp_key")
        assert value is None

    def test_delete_config_nonexistent(self):
        """Delete non-existent config returns False."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        assert svc.delete_config(tenants[0].id, "nonexistent") is False

    def test_config_with_sensitive_flag(self):
        """Config can be marked as sensitive."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        cfg = svc.set_config(
            tenants[0].id, "webhook_url", "https://example.com",
            sensitive=True,
        )
        assert cfg.sensitive is True

    def test_config_with_description(self):
        """Config can have a description."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        cfg = svc.set_config(
            tenants[0].id, "my_key", "my_value",
            description="My custom config",
        )
        assert cfg.description == "My custom config"

    def test_config_on_nonexistent_tenant_fails(self):
        """Config operations on non-existent tenant fail."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.get_config("nonexistent")
        with pytest.raises(TenantNotFoundError):
            svc.set_config("nonexistent", "key", "value")


# ===========================================================================
# 7. Context Switching Tests
# ===========================================================================

class TestContextSwitching:
    """Test tenant context switching."""

    def test_switch_context_basic(self):
        """Switch tenant context."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        ctx = svc.switch_tenant_context(tenants[0].id)
        assert ctx.tenant_id == tenants[0].id
        assert ctx.tenant_name == tenants[0].name

    def test_switch_context_with_user(self):
        """Switch context with user info."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        ctx = svc.switch_tenant_context(
            tenants[0].id, user_id="user123", user_role="admin"
        )
        assert ctx.user_id == "user123"
        assert ctx.user_role == "admin"

    def test_switch_context_with_ip(self):
        """Switch context with IP address."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        ctx = svc.switch_tenant_context(
            tenants[0].id, ip_address="192.168.1.1"
        )
        assert ctx.ip_address == "192.168.1.1"

    def test_switch_context_blocked_tenant_fails(self):
        """Cannot switch to a blocked tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.block_tenant(tenants[0].id)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tenants[0].id)

    def test_switch_context_suspended_tenant_fails(self):
        """Cannot switch to a suspended tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tenants[0].id)

    def test_switch_context_nonexistent_fails(self):
        """Cannot switch to non-existent tenant."""
        svc = MultiTenantService()
        with pytest.raises(TenantNotFoundError):
            svc.switch_tenant_context("nonexistent")

    def test_get_current_context(self):
        """Get current context returns active context."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id)
        ctx = svc.get_current_context()
        assert ctx is not None
        assert ctx.tenant_id == tenants[0].id

    def test_clear_context(self):
        """Clear context removes active context."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id)
        svc.clear_context()
        assert svc.get_current_context() is None

    def test_context_switch_logged(self):
        """Context switch is audit-logged."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.switch_tenant_context(tenants[0].id, user_id="u1")
        logs = svc.get_audit_logs(tenants[0].id)
        switch_logs = [l for l in logs if l.action == AuditAction.CONTEXT_SWITCHED]
        assert len(switch_logs) == 1


# ===========================================================================
# 8. Tenant Lifecycle (Suspend/Activate/Block) Tests
# ===========================================================================

class TestTenantLifecycle:
    """Test tenant lifecycle operations."""

    def test_suspend_tenant(self):
        """Suspend a tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        suspended = svc.suspend_tenant(tenants[0].id)
        assert suspended.status == TenantStatus.SUSPENDED

    def test_activate_tenant(self):
        """Activate a suspended tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        activated = svc.activate_tenant(tenants[0].id)
        assert activated.status == TenantStatus.ACTIVE

    def test_block_tenant(self):
        """Block a tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        blocked = svc.block_tenant(tenants[0].id)
        assert blocked.status == TenantStatus.BLOCKED
        assert blocked.blocked is True

    def test_suspend_blocks_access(self):
        """Suspended tenant cannot switch context."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.suspend_tenant(tenants[0].id)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tenants[0].id)

    def test_block_blocks_access(self):
        """Blocked tenant cannot switch context."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.block_tenant(tenants[0].id)
        with pytest.raises(TenantBlockedError):
            svc.switch_tenant_context(tenants[0].id)


# ===========================================================================
# 9. Validator Tests
# ===========================================================================

class TestValidators:
    """Test validation functions."""

    def test_validate_tenant_access_active(self):
        """Active tenant passes access validation."""
        tenant = _make_tenant(status=TenantStatus.ACTIVE)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is True

    def test_validate_tenant_access_suspended(self):
        """Suspended tenant fails access validation."""
        tenant = _make_tenant(status=TenantStatus.SUSPENDED)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False
        assert "suspendido" in err.lower()

    def test_validate_tenant_access_blocked(self):
        """Blocked tenant fails access validation."""
        tenant = _make_tenant(status=TenantStatus.BLOCKED, blocked=True)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False
        assert "bloqueado" in err.lower()

    def test_validate_tenant_access_deleted(self):
        """Deleted tenant fails access validation."""
        tenant = _make_tenant(status=TenantStatus.DELETED)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False
        assert "eliminado" in err.lower()

    def test_validate_tenant_access_pending(self):
        """Pending tenant fails access validation."""
        tenant = _make_tenant(status=TenantStatus.PENDING)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False
        assert "pendiente" in err.lower()

    def test_validate_tenant_access_blocked_flag(self):
        """Tenant with blocked=True fails even if status is active."""
        tenant = _make_tenant(status=TenantStatus.ACTIVE, blocked=True)
        is_valid, err = validate_tenant_access(tenant)
        assert is_valid is False

    def test_validate_cross_tenant_same(self):
        """Same tenant access passes validation."""
        is_valid, err = validate_cross_tenant_block("t1", "t1")
        assert is_valid is True

    def test_validate_cross_tenant_different(self):
        """Different tenant access fails validation."""
        is_valid, err = validate_cross_tenant_block("t1", "t2")
        assert is_valid is False
        assert "cross-tenant" in err.lower() or "bloqueado" in err.lower()

    def test_validate_tenant_name_valid(self):
        """Valid tenant name passes."""
        is_valid, err = validate_tenant_name("Mi Despacho")
        assert is_valid is True

    def test_validate_tenant_name_empty(self):
        """Empty tenant name fails."""
        is_valid, err = validate_tenant_name("")
        assert is_valid is False

    def test_validate_tenant_name_whitespace(self):
        """Whitespace-only name fails."""
        is_valid, err = validate_tenant_name("   ")
        assert is_valid is False

    def test_validate_tenant_name_too_short(self):
        """Single character name fails."""
        is_valid, err = validate_tenant_name("A")
        assert is_valid is False
        assert "2 caracteres" in err

    def test_validate_tenant_name_too_long(self):
        """Very long name fails."""
        is_valid, err = validate_tenant_name("A" * 101)
        assert is_valid is False
        assert "100 caracteres" in err

    def test_validate_tenant_name_invalid_chars(self):
        """Name with invalid characters fails."""
        is_valid, err = validate_tenant_name("Despacho@#$%")
        assert is_valid is False

    def test_validate_tenant_name_valid_chars(self):
        """Name with valid special chars passes."""
        is_valid, err = validate_tenant_name("Despacho García-Asoc. S.A.")
        assert is_valid is True

    def test_validate_schema_name_valid(self):
        """Valid schema name passes."""
        is_valid, err = validate_schema_name("tenant_mi_despacho")
        assert is_valid is True

    def test_validate_schema_name_empty(self):
        """Empty schema name fails."""
        is_valid, err = validate_schema_name("")
        assert is_valid is False

    def test_validate_schema_name_too_short(self):
        """Schema name < 3 chars fails."""
        is_valid, err = validate_schema_name("ab")
        assert is_valid is False

    def test_validate_schema_name_invalid_start(self):
        """Schema name starting with number fails."""
        is_valid, err = validate_schema_name("1schema")
        assert is_valid is False

    def test_validate_schema_name_reserved(self):
        """Reserved schema names fail."""
        is_valid, err = validate_schema_name("public")
        assert is_valid is False
        assert "reservada" in err.lower()

    def test_validate_schema_name_valid_with_underscore(self):
        """Schema name starting with underscore passes."""
        is_valid, err = validate_schema_name("_internal")
        assert is_valid is True

    def test_validate_config_key_valid(self):
        """Valid config key passes."""
        is_valid, err = validate_tenant_config_key("erp_type")
        assert is_valid is True

    def test_validate_config_key_empty(self):
        """Empty config key fails."""
        is_valid, err = validate_tenant_config_key("")
        assert is_valid is False

    def test_validate_config_key_uppercase(self):
        """Uppercase config key fails."""
        is_valid, err = validate_tenant_config_key("ERP_TYPE")
        assert is_valid is False

    def test_validate_config_key_with_spaces(self):
        """Config key with spaces fails."""
        is_valid, err = validate_tenant_config_key("erp type")
        assert is_valid is False

    def test_validate_config_key_too_long(self):
        """Very long config key fails."""
        is_valid, err = validate_tenant_config_key("a" * 65)
        assert is_valid is False


# ===========================================================================
# 10. API Route Tests
# ===========================================================================

class TestAPIRoutes:
    """Test FastAPI routes."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.include_router(build_multi_tenant_router())
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_create_tenant_route(self, client):
        """POST /tenants creates a tenant."""
        response = client.post(
            "/api/v1/tenants",
            json={"name": "API Tenant", "rfc": "API123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "API Tenant"

    def test_create_tenant_invalid_name(self, client):
        """POST /tenants with invalid name returns 422."""
        response = client.post(
            "/api/v1/tenants",
            json={"name": ""},
        )
        assert response.status_code == 422

    def test_create_tenant_duplicate(self, client):
        """POST /tenants with duplicate name returns 409."""
        client.post("/api/v1/tenants", json={"name": "Dup Tenant"})
        response = client.post(
            "/api/v1/tenants",
            json={"name": "Dup Tenant"},
        )
        assert response.status_code == 409

    def test_list_tenants_route(self, client):
        """GET /tenants lists tenants."""
        client.post("/api/v1/tenants", json={"name": "List Tenant"})
        response = client.get("/api/v1/tenants")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["total"] >= 1

    def test_get_tenant_route(self, client):
        """GET /tenants/{id} returns tenant details."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Get Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.get(f"/api/v1/tenants/{tenant_id}")
        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Get Tenant"

    def test_get_tenant_not_found(self, client):
        """GET /tenants/{id} with invalid ID returns 404."""
        response = client.get("/api/v1/tenants/nonexistent")
        assert response.status_code == 404

    def test_update_tenant_route(self, client):
        """PUT /tenants/{id} updates a tenant."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Update Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.put(
            f"/api/v1/tenants/{tenant_id}",
            json={"name": "Updated Tenant"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Updated Tenant"

    def test_delete_tenant_route(self, client):
        """DELETE /tenants/{id} deletes a tenant."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Delete Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.delete(f"/api/v1/tenants/{tenant_id}")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_suspend_tenant_route(self, client):
        """POST /tenants/{id}/suspend suspends a tenant."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Suspend Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.post(f"/api/v1/tenants/{tenant_id}/suspend")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "suspended"

    def test_activate_tenant_route(self, client):
        """POST /tenants/{id}/activate activates a tenant."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Activate Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        client.post(f"/api/v1/tenants/{tenant_id}/suspend")
        response = client.post(f"/api/v1/tenants/{tenant_id}/activate")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "active"

    def test_block_tenant_route(self, client):
        """POST /tenants/{id}/block blocks a tenant."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Block Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.post(f"/api/v1/tenants/{tenant_id}/block")
        assert response.status_code == 200
        assert response.json()["data"]["blocked"] is True

    def test_switch_context_route(self, client):
        """POST /tenants/{id}/context switches context."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Context Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.post(
            f"/api/v1/tenants/{tenant_id}/context",
            json={"user_id": "u1", "user_role": "admin"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["user_id"] == "u1"

    def test_switch_context_blocked_tenant(self, client):
        """POST /tenants/{id}/context on blocked tenant returns 403."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Blocked CTX"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        client.post(f"/api/v1/tenants/{tenant_id}/block")
        response = client.post(
            f"/api/v1/tenants/{tenant_id}/context",
            json={},
        )
        assert response.status_code == 403

    def test_get_config_route(self, client):
        """GET /tenants/{id}/config returns config."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Config Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.get(f"/api/v1/tenants/{tenant_id}/config")
        assert response.status_code == 200
        assert "erp_type" in response.json()["data"]

    def test_set_config_route(self, client):
        """PUT /tenants/{id}/config sets config."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "SetConfig Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.put(
            f"/api/v1/tenants/{tenant_id}/config",
            json={"key": "custom_key", "value": "custom_value"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["value"] == "custom_value"

    def test_get_audit_logs_route(self, client):
        """GET /tenants/{id}/audit returns audit logs."""
        create_resp = client.post(
            "/api/v1/tenants", json={"name": "Audit Tenant"}
        )
        tenant_id = create_resp.json()["data"]["id"]
        response = client.get(f"/api/v1/tenants/{tenant_id}/audit")
        assert response.status_code == 200
        assert response.json()["total"] >= 1

    def test_validate_isolation_route(self, client):
        """POST /tenants/validate-isolation validates isolation."""
        resp1 = client.post(
            "/api/v1/tenants", json={"name": "Isolation Source"}
        )
        resp2 = client.post(
            "/api/v1/tenants", json={"name": "Isolation Target"}
        )
        source_id = resp1.json()["data"]["id"]
        target_id = resp2.json()["data"]["id"]
        response = client.post(
            "/api/v1/tenants/validate-isolation",
            json={
                "source_tenant_id": source_id,
                "target_tenant_id": target_id,
                "resource": "invoices",
            },
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False  # Cross-tenant blocked

    def test_validate_isolation_same_tenant(self, client):
        """POST /tenants/validate-isolation same tenant passes."""
        resp = client.post(
            "/api/v1/tenants", json={"name": "Same Isolation"}
        )
        tenant_id = resp.json()["data"]["id"]
        response = client.post(
            "/api/v1/tenants/validate-isolation",
            json={
                "source_tenant_id": tenant_id,
                "target_tenant_id": tenant_id,
            },
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True


# ===========================================================================
# 11. Module-Level Convenience Function Tests
# ===========================================================================

class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_module_create_tenant(self):
        """Module-level create_tenant function."""
        from b2b_ai.features.multi_tenant.service import create_tenant
        req = _make_create_request(name="Module Tenant")
        tenant = create_tenant(req)
        assert tenant.name == "Module Tenant"

    def test_module_switch_context(self):
        """Module-level switch_tenant_context function."""
        from b2b_ai.features.multi_tenant.service import (
            create_tenant, switch_tenant_context, _get_service,
        )
        req = _make_create_request(name="Module CTX Tenant")
        tenant = create_tenant(req)
        ctx = switch_tenant_context(tenant.id)
        assert ctx.tenant_id == tenant.id
        # Cleanup
        _get_service().clear_context()

    def test_module_scoped_query(self):
        """Module-level tenant_scoped_query function."""
        from b2b_ai.features.multi_tenant.service import (
            create_tenant, tenant_scoped_query,
        )
        req = _make_create_request(name="Module Query Tenant")
        tenant = create_tenant(req)
        data = [{"tenant_id": tenant.id, "amount": 100}]
        result = tenant_scoped_query(tenant.id, "test", data)
        assert len(result) == 1

    def test_module_isolation_validator(self):
        """Module-level data_isolation_validator function."""
        from b2b_ai.features.multi_tenant.service import data_isolation_validator
        is_valid, err = data_isolation_validator("t1", "t2")
        assert is_valid is False


# ===========================================================================
# 12. Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_many_tenants(self):
        """Service handles many tenants."""
        svc = MultiTenantService()
        for i in range(50):
            svc.create_tenant(_make_create_request(name=f"Tenant {i}"))
        tenants = svc.list_tenants()
        assert len(tenants) == 50

    def test_many_config_entries(self):
        """Service handles many config entries per tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        for i in range(20):
            svc.set_config(tenants[0].id, f"key_{i}", f"value_{i}")
        config = svc.get_config(tenants[0].id)
        assert len(config) >= 20 + len({"erp_type", "notif_channel", "notif_recipient", "webhook_url", "plantilla_contable", "policy_human_review"})

    def test_concurrent_context_switches(self):
        """Multiple context switches work correctly."""
        svc = _make_service_with_tenants(3)
        tenants = svc.list_tenants()
        for t in tenants:
            svc.switch_tenant_context(t.id)
        ctx = svc.get_current_context()
        assert ctx.tenant_id == tenants[-1].id

    def test_tenant_with_special_characters_name(self):
        """Tenant with special characters in name."""
        svc = MultiTenantService()
        req = _make_create_request(name="Despacho García-Asoc. S.A. de C.V.")
        tenant = svc.create_tenant(req)
        assert tenant.name == "Despacho García-Asoc. S.A. de C.V."

    def test_empty_data_scoped_query(self):
        """Scoped query with empty data list."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        result = svc.tenant_scoped_query(tenants[0].id, "invoices", [])
        assert result == []

    def test_audit_log_multiple_actions(self):
        """Multiple audit log actions for same tenant."""
        svc = _make_service_with_tenants(1)
        tenants = svc.list_tenants()
        svc.set_config(tenants[0].id, "k1", "v1")
        svc.set_config(tenants[0].id, "k2", "v2")
        svc.switch_tenant_context(tenants[0].id)
        logs = svc.get_audit_logs(tenants[0].id)
        assert len(logs) >= 4  # created + 2 config + context_switch
