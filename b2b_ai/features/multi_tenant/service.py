# -*- coding: utf-8 -*-
"""
service.py — MultiTenantService: gestión de aislamiento de datos multi-tenant.

This service:
  - Creates and manages tenants with schema isolation
  - Switches tenant context for request scoping
  - Provides tenant-scoped queries that enforce data isolation
  - Validates data isolation rules and prevents cross-tenant access
  - Logs all tenant operations for audit trail
"""
from __future__ import annotations

import contextvars
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from b2b_ai.features.multi_tenant.validators import (
    validate_tenant_access,
    validate_cross_tenant_block,
    validate_tenant_name,
    validate_schema_name,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TenantNotFoundError(Exception):
    """Se lanza al operar sobre un tenant que no existe."""


class TenantBlockedError(Exception):
    """Se lanza cuando un tenant bloqueado intenta acceder a datos."""


class CrossTenantAccessError(Exception):
    """Se lanza cuando se detecta acceso cross-tenant no autorizado."""


class TenantConflictError(Exception):
    """Se lanza cuando hay conflicto (nombre duplicado, schema duplicado)."""


# ---------------------------------------------------------------------------
# Default config values
# ---------------------------------------------------------------------------

TENANT_CONFIG_DEFAULTS: Dict[str, str] = {
    "erp_type": "contpaqi",
    "plantilla_contable": "SAT",
    "notif_channel": "email",
    "notif_recipient": "admin@tenant.local",
    "webhook_url": "",
    "policy_human_review": "hold",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MultiTenantService:
    """Core service for Multi-Tenant Data Isolation.

    Manages the complete tenant lifecycle:
      1. Tenant creation with schema setup
      2. Context switching for request scoping
      3. Tenant-scoped queries
      4. Data isolation validation
      5. Audit logging
      6. Configuration management
    """

    def __init__(self) -> None:
        # In-memory stores (for MVP; replace with DB in production)
        self._tenants: Dict[str, Tenant] = {}
        self._configs: Dict[str, Dict[str, TenantConfig]] = {}
        self._audit_logs: Dict[str, List[TenantAuditLog]] = {}
        self._schema_registry: Dict[str, str] = {}  # schema_name -> tenant_id
        # SECURITY: Use contextvars for thread-safe tenant isolation.
        # Instance variables are shared across threads in async servers.
        self._current_context_var: contextvars.ContextVar[Optional[TenantContext]] = (
            contextvars.ContextVar("tenant_context", default=None)
        )

    # -------------------------------------------------------------------
    # 1. Tenant CRUD
    # -------------------------------------------------------------------

    def create_tenant(self, request: CreateTenantRequest) -> Tenant:
        """Create a new tenant with schema isolation.

        Parameters
        ----------
        request : CreateTenantRequest
            Request data for the new tenant.

        Returns
        -------
        Tenant
            The created tenant.

        Raises
        ------
        TenantConflictError
            If a tenant with the same name or schema already exists.
        """
        # Validate name
        is_valid, err = validate_tenant_name(request.name)
        if not is_valid:
            raise ValueError(err)

        # Check duplicate name
        for t in self._tenants.values():
            if t.name.lower() == request.name.lower() and t.status != TenantStatus.DELETED:
                raise TenantConflictError(
                    f"Ya existe un tenant con el nombre '{request.name}'."
                )

        # Generate schema name if needed
        schema_name = ""
        if request.isolation_level == IsolationLevel.SCHEMA_PER_TENANT:
            schema_name = f"tenant_{request.name.lower().replace(' ', '_')}"
            is_valid, err = validate_schema_name(schema_name)
            if not is_valid:
                raise ValueError(err)
            if schema_name in self._schema_registry:
                raise TenantConflictError(
                    f"Ya existe un schema con el nombre '{schema_name}'."
                )

        # Create tenant
        tenant = Tenant(
            name=request.name,
            rfc=request.rfc,
            schema_name=schema_name,
            isolation_level=request.isolation_level,
            status=TenantStatus.ACTIVE,
            config=request.config or {},
            metadata=request.metadata or {},
        )

        # Register schema
        if schema_name:
            self._schema_registry[schema_name] = tenant.id

        # Store tenant
        self._tenants[tenant.id] = tenant

        # Initialize config with defaults
        self._configs[tenant.id] = {}
        for key, default_value in TENANT_CONFIG_DEFAULTS.items():
            value = request.config.get(key, default_value)
            self.set_config(tenant.id, key, value)

        # Apply any extra config from request
        for key, value in request.config.items():
            if key not in TENANT_CONFIG_DEFAULTS:
                self.set_config(tenant.id, key, value)

        # Audit log
        self._log_audit(
            tenant.id,
            AuditAction.TENANT_CREATED,
            details={"name": request.name, "isolation_level": request.isolation_level.value},
        )

        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        """Get a tenant by ID.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        Tenant
            The tenant.

        Raises
        ------
        TenantNotFoundError
            If the tenant does not exist.
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None or tenant.status == TenantStatus.DELETED:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' no existe.")
        return tenant

    def update_tenant(
        self,
        tenant_id: str,
        name: Optional[str] = None,
        rfc: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tenant:
        """Update a tenant's basic information.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.
        name : Optional[str]
            New name (if changing).
        rfc : Optional[str]
            New RFC (if changing).
        metadata : Optional[Dict[str, Any]]
            New metadata (if changing).

        Returns
        -------
        Tenant
            The updated tenant.

        Raises
        ------
        TenantNotFoundError
            If the tenant does not exist.
        """
        tenant = self.get_tenant(tenant_id)

        if name is not None:
            is_valid, err = validate_tenant_name(name)
            if not is_valid:
                raise ValueError(err)
            # Check duplicate
            for t in self._tenants.values():
                if (t.id != tenant_id
                        and t.name.lower() == name.lower()
                        and t.status != TenantStatus.DELETED):
                    raise TenantConflictError(
                        f"Ya existe un tenant con el nombre '{name}'."
                    )
            tenant.name = name

        if rfc is not None:
            tenant.rfc = rfc

        if metadata is not None:
            tenant.metadata.update(metadata)

        tenant.updated_at = datetime.now(timezone.utc).isoformat()
        self._tenants[tenant_id] = tenant

        self._log_audit(
            tenant_id,
            AuditAction.TENANT_UPDATED,
            details={"fields_updated": [
                k for k, v in [("name", name), ("rfc", rfc), ("metadata", metadata)]
                if v is not None
            ]},
        )

        return tenant

    def suspend_tenant(self, tenant_id: str) -> Tenant:
        """Suspend a tenant (data preserved, access blocked).

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        Tenant
            The suspended tenant.
        """
        tenant = self.get_tenant(tenant_id)
        tenant.status = TenantStatus.SUSPENDED
        tenant.updated_at = datetime.now(timezone.utc).isoformat()
        self._tenants[tenant_id] = tenant

        self._log_audit(tenant_id, AuditAction.TENANT_SUSPENDED)
        return tenant

    def activate_tenant(self, tenant_id: str) -> Tenant:
        """Activate a suspended tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        Tenant
            The activated tenant.
        """
        tenant = self.get_tenant(tenant_id)
        tenant.status = TenantStatus.ACTIVE
        tenant.updated_at = datetime.now(timezone.utc).isoformat()
        self._tenants[tenant_id] = tenant

        self._log_audit(tenant_id, AuditAction.TENANT_ACTIVATED)
        return tenant

    def block_tenant(self, tenant_id: str) -> Tenant:
        """Block a tenant (complete access denial).

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        Tenant
            The blocked tenant.
        """
        tenant = self.get_tenant(tenant_id)
        tenant.status = TenantStatus.BLOCKED
        tenant.blocked = True
        tenant.updated_at = datetime.now(timezone.utc).isoformat()
        self._tenants[tenant_id] = tenant

        self._log_audit(tenant_id, AuditAction.TENANT_BLOCKED)
        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """Soft-delete a tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        bool
            True if deleted successfully.
        """
        tenant = self.get_tenant(tenant_id)
        tenant.status = TenantStatus.DELETED
        tenant.updated_at = datetime.now(timezone.utc).isoformat()
        self._tenants[tenant_id] = tenant

        # Unregister schema
        if tenant.schema_name and tenant.schema_name in self._schema_registry:
            del self._schema_registry[tenant.schema_name]

        self._log_audit(tenant_id, AuditAction.TENANT_DELETED)
        return True

    def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        include_deleted: bool = False,
    ) -> List[Tenant]:
        """List tenants with optional filtering.

        Parameters
        ----------
        status : Optional[TenantStatus]
            Filter by status.
        include_deleted : bool
            If True, include soft-deleted tenants.

        Returns
        -------
        List[Tenant]
            List of matching tenants.
        """
        tenants = list(self._tenants.values())
        if not include_deleted:
            tenants = [t for t in tenants if t.status != TenantStatus.DELETED]
        if status is not None:
            tenants = [t for t in tenants if t.status == status]
        return tenants

    # -------------------------------------------------------------------
    # 2. Context switching
    # -------------------------------------------------------------------

    def switch_tenant_context(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> TenantContext:
        """Switch the active tenant context for a session/request.

        Parameters
        ----------
        tenant_id : str
            The tenant to switch to.
        user_id : Optional[str]
            The authenticated user's ID.
        user_role : Optional[str]
            The user's role.
        ip_address : Optional[str]
            The client's IP address.

        Returns
        -------
        TenantContext
            The new active context.

        Raises
        ------
        TenantNotFoundError
            If the tenant does not exist.
        TenantBlockedError
            If the tenant is blocked or suspended.
        """
        tenant = self.get_tenant(tenant_id)

        # Validate tenant is not blocked
        is_valid, err = validate_tenant_access(tenant)
        if not is_valid:
            raise TenantBlockedError(err)

        # Capture old context BEFORE switching (for audit trail)
        old_context = self._current_context_var.get()

        context = TenantContext(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            user_id=user_id,
            user_role=user_role,
            isolation_level=tenant.isolation_level,
            schema_name=tenant.schema_name or None,
            ip_address=ip_address,
        )

        self._current_context_var.set(context)

        self._log_audit(
            tenant_id,
            AuditAction.CONTEXT_SWITCHED,
            user_id=user_id,
            ip_address=ip_address,
            details={"from_tenant": old_context.tenant_id if old_context else None},
        )

        return context

    def get_current_context(self) -> Optional[TenantContext]:
        """Get the current active tenant context (thread-safe).

        Returns
        -------
        Optional[TenantContext]
            The current context, or None if no context is set.
        """
        return self._current_context_var.get()

    def clear_context(self) -> None:
        """Clear the current tenant context (thread-safe)."""
        self._current_context_var.set(None)

    # -------------------------------------------------------------------
    # 3. Tenant-scoped queries
    # -------------------------------------------------------------------

    def tenant_scoped_query(
        self,
        tenant_id: str,
        resource: str,
        data: List[Dict[str, Any]],
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a tenant-scoped query that enforces data isolation.

        Parameters
        ----------
        tenant_id : str
            The tenant ID to scope results to.
        resource : str
            The resource/table name being queried.
        data : List[Dict[str, Any]]
            The full dataset to filter.
        filters : Optional[Dict[str, Any]]
            Additional filters to apply.

        Returns
        -------
        List[Dict[str, Any]]
            Filtered data that belongs to the specified tenant.
        """
        # Validate tenant exists and is accessible
        tenant = self.get_tenant(tenant_id)

        # Apply tenant isolation filter
        scoped = [item for item in data if item.get("tenant_id") == tenant_id]

        # Apply additional filters
        if filters:
            for key, value in filters.items():
                if key == "tenant_id":
                    continue  # Already filtered
                scoped = [
                    item for item in scoped
                    if item.get(key) == value
                ]

        self._log_audit(
            tenant_id,
            AuditAction.DATA_ACCESSED,
            resource=resource,
            details={
                "query_size": len(data),
                "result_size": len(scoped),
                "filters": filters,
            },
        )

        return scoped

    # -------------------------------------------------------------------
    # 4. Data isolation validation
    # -------------------------------------------------------------------

    def data_isolation_validator(
        self,
        source_tenant_id: str,
        target_tenant_id: str,
        resource: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Validate that data access does not cross tenant boundaries.

        Parameters
        ----------
        source_tenant_id : str
            The tenant attempting the access.
        target_tenant_id : str
            The tenant whose data is being accessed.
        resource : Optional[str]
            The resource being accessed (for audit).

        Returns
        -------
        (is_valid, error_message)
        """
        # Same tenant access is always allowed
        if source_tenant_id == target_tenant_id:
            return True, ""

        # Cross-tenant access is blocked
        is_valid, err = validate_cross_tenant_block(
            source_tenant_id, target_tenant_id
        )

        if not is_valid:
            self._log_audit(
                source_tenant_id,
                AuditAction.CROSS_TENANT_BLOCKED,
                resource=resource,
                details={
                    "target_tenant_id": target_tenant_id,
                    "reason": err,
                },
                success=False,
                error_message=err,
            )

        return is_valid, err

    # -------------------------------------------------------------------
    # 5. Configuration management
    # -------------------------------------------------------------------

    def get_config(self, tenant_id: str) -> Dict[str, str]:
        """Get all configuration for a tenant, merged with defaults.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.

        Returns
        -------
        Dict[str, str]
            Configuration dictionary.
        """
        self.get_tenant(tenant_id)  # Validates existence
        config_store = self._configs.get(tenant_id, {})
        result = dict(TENANT_CONFIG_DEFAULTS)
        for key, cfg in config_store.items():
            result[key] = cfg.value
        return result

    def get_config_value(self, tenant_id: str, key: str) -> Optional[str]:
        """Get a specific config value for a tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.
        key : str
            The config key.

        Returns
        -------
        Optional[str]
            The config value, or the default if not set.
        """
        self.get_tenant(tenant_id)  # Validates existence
        config_store = self._configs.get(tenant_id, {})
        if key in config_store:
            return config_store[key].value
        return TENANT_CONFIG_DEFAULTS.get(key)

    def set_config(
        self,
        tenant_id: str,
        key: str,
        value: str,
        description: str = "",
        sensitive: bool = False,
    ) -> TenantConfig:
        """Set a configuration value for a tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.
        key : str
            The config key.
        value : str
            The config value.
        description : str
            Description of the config.
        sensitive : bool
            If True, the value should be encrypted at rest.

        Returns
        -------
        TenantConfig
            The updated config entry.
        """
        self.get_tenant(tenant_id)  # Validates existence

        now = datetime.now(timezone.utc).isoformat()

        if tenant_id not in self._configs:
            self._configs[tenant_id] = {}

        existing = self._configs[tenant_id].get(key)
        if existing:
            existing.value = value
            existing.updated_at = now
            if description:
                existing.description = description
            existing.sensitive = sensitive
            cfg = existing
        else:
            cfg = TenantConfig(
                tenant_id=tenant_id,
                key=key,
                value=value,
                description=description,
                sensitive=sensitive,
            )
            self._configs[tenant_id][key] = cfg

        self._log_audit(
            tenant_id,
            AuditAction.CONFIG_UPDATED,
            details={"key": key, "sensitive": sensitive},
        )

        return cfg

    def delete_config(self, tenant_id: str, key: str) -> bool:
        """Delete a config entry for a tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.
        key : str
            The config key to delete.

        Returns
        -------
        bool
            True if deleted, False if not found.
        """
        self.get_tenant(tenant_id)
        config_store = self._configs.get(tenant_id, {})
        if key in config_store:
            del config_store[key]
            return True
        return False

    # -------------------------------------------------------------------
    # 6. Audit log
    # -------------------------------------------------------------------

    def get_audit_logs(
        self,
        tenant_id: str,
        action: Optional[AuditAction] = None,
        limit: int = 100,
    ) -> List[TenantAuditLog]:
        """Get audit logs for a tenant.

        Parameters
        ----------
        tenant_id : str
            The tenant ID.
        action : Optional[AuditAction]
            Filter by action type.
        limit : int
            Maximum number of records to return.

        Returns
        -------
        List[TenantAuditLog]
            Audit log entries.
        """
        # Note: we do NOT call get_tenant() here because deleted tenants
        # should still have their audit history accessible.
        if tenant_id not in self._tenants:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' no existe.")
        logs = self._audit_logs.get(tenant_id, [])
        if action is not None:
            logs = [l for l in logs if l.action == action]
        # Return most recent first
        return sorted(logs, key=lambda x: x.timestamp, reverse=True)[:limit]

    def _log_audit(
        self,
        tenant_id: str,
        action: AuditAction,
        user_id: Optional[str] = None,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> TenantAuditLog:
        """Internal: log an audit event."""
        log = TenantAuditLog(
            tenant_id=tenant_id,
            action=action,
            user_id=user_id,
            resource=resource,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            success=success,
            error_message=error_message,
        )

        if tenant_id not in self._audit_logs:
            self._audit_logs[tenant_id] = []
        self._audit_logs[tenant_id].append(log)

        return log


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_service: Optional[MultiTenantService] = None


def _get_service() -> MultiTenantService:
    """Get or create the default service instance."""
    global _default_service
    if _default_service is None:
        _default_service = MultiTenantService()
    return _default_service


def create_tenant(request: CreateTenantRequest) -> Tenant:
    """Atajo funcional: crear un tenant."""
    return _get_service().create_tenant(request)


def switch_tenant_context(
    tenant_id: str,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> TenantContext:
    """Atajo funcional: cambiar contexto de tenant."""
    return _get_service().switch_tenant_context(
        tenant_id, user_id, user_role, ip_address
    )


def tenant_scoped_query(
    tenant_id: str,
    resource: str,
    data: List[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Atajo funcional: query con aislamiento de tenant."""
    return _get_service().tenant_scoped_query(tenant_id, resource, data, filters)


def data_isolation_validator(
    source_tenant_id: str,
    target_tenant_id: str,
    resource: Optional[str] = None,
) -> Tuple[bool, str]:
    """Atajo funcional: validar aislamiento de datos."""
    return _get_service().data_isolation_validator(
        source_tenant_id, target_tenant_id, resource
    )
