# -*- coding: utf-8 -*-
"""
multi_tenant — Módulo de aislamiento de datos multi-tenant.

Proporciona:
  - Modelos de tenant, configuración y auditoría
  - Servicio de CRUD de tenants con aislamiento por schema
  - Validación de acceso y bloqueo cross-tenant
  - API REST para gestión de tenants
  - Middleware de contexto de tenant
"""
from b2b_ai.features.multi_tenant.models import (
    TenantStatus,
    IsolationLevel,
    Tenant,
    TenantConfig,
    TenantAuditLog,
    TenantContext,
    CreateTenantRequest,
    TenantResponse,
)
from b2b_ai.features.multi_tenant.service import (
    MultiTenantService,
    create_tenant,
    switch_tenant_context,
    tenant_scoped_query,
    data_isolation_validator,
)
from b2b_ai.features.multi_tenant.validators import (
    validate_tenant_access,
    validate_cross_tenant_block,
    validate_tenant_name,
    validate_schema_name,
    validate_tenant_config_key,
)
from b2b_ai.features.multi_tenant.routes import (
    build_multi_tenant_router,
)

__all__ = [
    # Enums
    "TenantStatus",
    "IsolationLevel",
    # Models
    "Tenant",
    "TenantConfig",
    "TenantAuditLog",
    "TenantContext",
    "CreateTenantRequest",
    "TenantResponse",
    # Service
    "MultiTenantService",
    "create_tenant",
    "switch_tenant_context",
    "tenant_scoped_query",
    "data_isolation_validator",
    # Validators
    "validate_tenant_access",
    "validate_cross_tenant_block",
    "validate_tenant_name",
    "validate_schema_name",
    "validate_tenant_config_key",
    # Router
    "build_multi_tenant_router",
]
