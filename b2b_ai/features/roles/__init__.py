# -*- coding: utf-8 -*-
"""roles — Módulo de roles y permisos (RBAC) para el sistema multi-tenant.

Controla quién puede hacer qué dentro de un tenant (despacho contable) en el
piloto. Un tenant tiene roles granulares (admin, contador, auditor, readonly o
custom) y cada usuario recibe un rol dentro de su tenant.

Expone:
  - Permission — catálogo de permisos (cfdi:read, cfdi:write, nominas:*,
                 reportes:*, billing:*, settings:*, users:manage)
  - Role, UserRole — entidades de dominio (pydantic v2, store en memoria)
  - RolesService — assign_role / check_permission / get_user_roles /
                   list_roles / create_custom_role / user_permissions
  - make_require_permission — dependencia FastAPI `require_permission(perm)`
                              para proteger endpoints de escritura
  - build_roles_router() — router FastAPI /api/v1/roles/*
  - seed_default_roles() — roles por defecto con permisos predefinidos
"""
from __future__ import annotations

from b2b_ai.features.roles.models import (
    Permission,
    Role,
    UserRole,
    _reset_state,
    is_valid_permission,
)
from b2b_ai.features.roles.seed import DEFAULT_ROLE_DEFS, seed_default_roles
from b2b_ai.features.roles.service import RolesError, RolesService, reset_state
from b2b_ai.features.roles.middleware import (
    PermissionDeniedError,
    make_require_permission,
)
from b2b_ai.features.roles.routes import build_roles_router

__all__ = [
    "Permission",
    "Role",
    "UserRole",
    "is_valid_permission",
    "DEFAULT_ROLE_DEFS",
    "seed_default_roles",
    "RolesError",
    "RolesService",
    "reset_state",
    "PermissionDeniedError",
    "make_require_permission",
    "build_roles_router",
    "_reset_state",
]
