# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for Multi-Tenant Data Isolation.

Validates:
  - Tenant access (active status, not blocked)
  - Cross-tenant access blocking
  - Tenant name format and uniqueness
  - Schema name format
  - Config key format
"""
from __future__ import annotations

import re
from typing import Tuple

from b2b_ai.features.multi_tenant.models import (
    Tenant,
    TenantStatus,
)


def validate_tenant_access(tenant: Tenant) -> Tuple[bool, str]:
    """Validate that a tenant is allowed to access resources.

    A tenant can access resources if:
      - It exists and is not DELETED
      - Its status is ACTIVE (not SUSPENDED or BLOCKED)
      - It is not blocked

    Parameters
    ----------
    tenant : Tenant
        The tenant to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if tenant.status == TenantStatus.DELETED:
        return False, f"Tenant '{tenant.name}' ha sido eliminado."

    if tenant.status == TenantStatus.BLOCKED or tenant.blocked:
        return False, f"Tenant '{tenant.name}' está bloqueado. Acceso denegado."

    if tenant.status == TenantStatus.SUSPENDED:
        return False, f"Tenant '{tenant.name}' está suspendido. Acceso denegado."

    if tenant.status == TenantStatus.PENDING:
        return False, f"Tenant '{tenant.name}' está en estado pendiente. Acceso denegado."

    if tenant.status != TenantStatus.ACTIVE:
        return False, f"Tenant '{tenant.name}' tiene estado inválido: {tenant.status}."

    return True, ""


def validate_cross_tenant_block(
    source_tenant_id: str,
    target_tenant_id: str,
) -> Tuple[bool, str]:
    """Validate that cross-tenant access is blocked.

    Cross-tenant access is never allowed in a multi-tenant system.
    Each tenant's data must be completely isolated.

    Parameters
    ----------
    source_tenant_id : str
        The tenant attempting the access.
    target_tenant_id : str
        The tenant whose data is being accessed.

    Returns
    -------
    (is_valid, error_message)
    """
    if source_tenant_id == target_tenant_id:
        return True, ""

    return (
        False,
        f"Acceso cross-tenant bloqueado: tenant '{source_tenant_id}' "
        f"no puede acceder a datos del tenant '{target_tenant_id}'.",
    )


def validate_tenant_name(name: str) -> Tuple[bool, str]:
    """Validate a tenant name.

    Rules:
      - Cannot be empty or whitespace only
      - Must be between 2 and 100 characters
      - Can contain letters, numbers, spaces, hyphens, and underscores
      - No leading/trailing whitespace

    Parameters
    ----------
    name : str
        The tenant name to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "El nombre del tenant no puede estar vacío."

    name = name.strip()

    if len(name) < 2:
        return False, f"El nombre del tenant debe tener al menos 2 caracteres: '{name}'."

    if len(name) > 100:
        return False, f"El nombre del tenant no puede exceder 100 caracteres: '{name}'."

    if not re.match(r"^[a-zA-Z0-9áéíóúñüÁÉÍÓÚÑÜ\s_\-\.]+$", name):
        return False, (
            f"El nombre del tenant contiene caracteres no válidos: '{name}'. "
            "Solo se permiten letras, números, espacios, guiones, puntos y guiones bajos."
        )

    return True, ""


def validate_schema_name(schema_name: str) -> Tuple[bool, str]:
    """Validate a database schema name.

    Rules:
      - Cannot be empty
      - Must start with a letter or underscore
      - Can only contain letters, numbers, and underscores
      - Must be between 3 and 63 characters (PostgreSQL limit)

    Parameters
    ----------
    schema_name : str
        The schema name to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not schema_name or not schema_name.strip():
        return False, "El nombre del schema no puede estar vacío."

    schema_name = schema_name.strip()

    if len(schema_name) < 3:
        return False, (
            f"El nombre del schema debe tener al menos 3 caracteres: '{schema_name}'."
        )

    if len(schema_name) > 63:
        return False, (
            f"El nombre del schema no puede exceder 63 caracteres: '{schema_name}'."
        )

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", schema_name):
        return False, (
            f"El nombre del schema contiene caracteres no válidos: '{schema_name}'. "
            "Debe empezar con letra o guión bajo y solo contener letras, números y guiones bajos."
        )

    # Reserved words
    reserved = {
        "public", "information_schema", "pg_catalog", "pg_toast",
        "schema", "table", "column", "index", "user", "role",
    }
    if schema_name.lower() in reserved:
        return False, f"El nombre del schema '{schema_name}' es una palabra reservada."

    return True, ""


def validate_tenant_config_key(key: str) -> Tuple[bool, str]:
    """Validate a tenant configuration key.

    Rules:
      - Cannot be empty
      - Must be between 1 and 64 characters
      - Can only contain lowercase letters, numbers, and underscores
      - Must start with a letter

    Parameters
    ----------
    key : str
        The config key to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not key or not key.strip():
        return False, "La clave de configuración no puede estar vacía."

    key = key.strip()

    if len(key) > 64:
        return False, (
            f"La clave de configuración no puede exceder 64 caracteres: '{key}'."
        )

    if not re.match(r"^[a-z][a-z0-9_]*$", key):
        return False, (
            f"La clave de configuración contiene caracteres no válidos: '{key}'. "
            "Debe empezar con letra minúscula y solo contener letras minúsculas, "
            "números y guiones bajos."
        )

    return True, ""
