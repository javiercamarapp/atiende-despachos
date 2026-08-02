# -*- coding: utf-8 -*-
"""models.py — Entidades de dominio del módulo de roles y permisos (RBAC).

Define el modelo de control de acceso basado en roles para el sistema
multi-tenant. Cada tenant (despacho) tiene su propio conjunto de usuarios con
roles granulares:

    Role       — un rol (admin, contador, auditor, readonly o custom) con una
                 lista de permisos.
    UserRole   — vínculo usuario↔rol dentro de un tenant (una asignación).
    Permission — constantes de los permisos reconocidos por la plataforma.

Sigue el patrón del proyecto (pydantic v2, Field con description, enums,
timestamps ISO UTC y store en memoria) usado por `data_migration`, `onboarding`
y `billing`. El store en memoria es la iteración del piloto; la persistencia
real (PostgreSQL) queda como siguiente iteración.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Permisos reconocidos
# ---------------------------------------------------------------------------

class Permission:
    """Catálogo de permisos de la plataforma (constantes de cadena).

    Convención `<recurso>:<acción>`:

        cfdi:read / cfdi:write         — facturas CFDI
        nominas:read / nominas:write   — nómina / CFDI de nómina
        reportes:read / reportes:write — reportes gerenciales
        billing:read / billing:write   — suscripción / facturación
        settings:read / settings:write — configuración del despacho
        users:manage                   — administrar usuarios y roles
    """

    CFDI_READ = "cfdi:read"
    CFDI_WRITE = "cfdi:write"
    NOMINAS_READ = "nominas:read"
    NOMINAS_WRITE = "nominas:write"
    REPORTES_READ = "reportes:read"
    REPORTES_WRITE = "reportes:write"
    BILLING_READ = "billing:read"
    BILLING_WRITE = "billing:write"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"
    USERS_MANAGE = "users:manage"
    # Pipeline end-to-end (pipeline/routes.py): ejecución del flujo CFDI →
    # bookkeeping → conciliación.
    PIPELINE_RUN = "pipeline:run"
    # Bank feeds (bank_feeds/routes.py): lectura de cuentas/transacciones,
    # sincronización de feeds y gestión/categorización.
    BANK_FEEDS_VIEW = "bank_feeds:view"
    BANK_FEEDS_SYNC = "bank_feeds:sync"
    BANK_FEEDS_MANAGE = "bank_feeds:manage"
    # Gestión documental (document_management/routes.py): borrado físico.
    DOCUMENTS_DELETE = "documents:delete"
    # Cierre mensual (monthly_close/routes.py): checklist de cierre.
    CLOSE_VIEW = "close:view"
    CLOSE_MANAGE = "close:manage"

    ALL = (
        CFDI_READ, CFDI_WRITE,
        NOMINAS_READ, NOMINAS_WRITE,
        REPORTES_READ, REPORTES_WRITE,
        BILLING_READ, BILLING_WRITE,
        SETTINGS_READ, SETTINGS_WRITE,
        USERS_MANAGE,
        PIPELINE_RUN,
        BANK_FEEDS_VIEW, BANK_FEEDS_SYNC, BANK_FEEDS_MANAGE,
        DOCUMENTS_DELETE,
        CLOSE_VIEW, CLOSE_MANAGE,
    )


def is_valid_permission(permission: str) -> bool:
    """True si la cadena es un permiso reconocido por la plataforma."""
    return permission in Permission.ALL


# ---------------------------------------------------------------------------
# Helpers de tiempo
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Entidades
# ---------------------------------------------------------------------------

class Role(BaseModel):
    """Un rol con su lista de permisos.

    Los roles por defecto (admin, contador, auditor, readonly) son globales
    (`builtin=True`); los roles custom se crean por tenant y llevan `tenant_id`.
    """
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno del rol")
    name: str = Field(..., description="Nombre del rol (admin, contador, ...)")
    permissions: List[str] = Field(
        default_factory=list, description="Permisos otorgados por el rol")
    description: str = Field("", description="Descripción del rol")
    tenant_id: Optional[str] = Field(
        default=None, description="Tenant dueño (solo roles custom); None = builtin")
    builtin: bool = Field(False, description="True si es un rol por defecto")
    created_at: str = Field(default_factory=_utcnow_iso,
                            description="Fecha de creación ISO UTC")
    updated_at: Optional[str] = Field(default=None,
                                      description="Última actualización ISO UTC")

    @field_validator("permissions")
    @classmethod
    def _validar_permisos(cls, v: List[str]) -> List[str]:
        for p in v:
            if not is_valid_permission(p):
                raise ValueError(f"Permiso no reconocido: {p}")
        return list(dict.fromkeys(v))  # sin duplicados

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "permissions": list(self.permissions),
            "description": self.description,
            "tenant_id": self.tenant_id,
            "builtin": self.builtin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class UserRole(BaseModel):
    """Vínculo usuario↔rol dentro de un tenant (una asignación)."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno de la asignación")
    user_id: str = Field(..., description="ID del usuario")
    tenant_id: str = Field(..., description="Tenant donde aplica el rol")
    role_id: str = Field(..., description="ID del rol asignado")
    assigned_by: Optional[str] = Field(
        default=None, description="ID del admin que asignó el rol")
    created_at: str = Field(default_factory=_utcnow_iso,
                            description="Fecha de asignación ISO UTC")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "role_id": self.role_id,
            "assigned_by": self.assigned_by,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Store en memoria (patrón data_migration / onboarding / billing)
# ---------------------------------------------------------------------------

# role_id -> Role
_roles: Dict[str, Role] = {}
# user_role_id -> UserRole
_user_roles: Dict[str, UserRole] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _roles.clear()
    _user_roles.clear()


def save_role(role: Role) -> Role:
    _roles[role.id] = role
    return role


def get_role(role_id: str) -> Optional[Role]:
    return _roles.get(role_id)


def list_roles(tenant_id: Optional[str] = None) -> List[Role]:
    """Lista roles. Con `tenant_id` incluye builtin + custom de ese tenant."""
    if tenant_id is None:
        return list(_roles.values())
    out = [r for r in _roles.values()
           if r.builtin or r.tenant_id == tenant_id]
    return sorted(out, key=lambda r: (0 if r.builtin else 1, r.name))


def delete_role(role_id: str) -> bool:
    """Elimina un rol (no aplica a builtin). Devuelve True si se eliminó."""
    role = _roles.get(role_id)
    if role is None or role.builtin:
        return False
    del _roles[role_id]
    return True


def find_role_by_name(name: str, tenant_id: Optional[str] = None) -> Optional[Role]:
    """Busca un rol por nombre (builtin global o custom por tenant)."""
    for r in _roles.values():
        if r.name.lower() == name.lower():
            if r.builtin or tenant_id is None or r.tenant_id == tenant_id:
                return r
    return None


def save_user_role(ur: UserRole) -> UserRole:
    _user_roles[ur.id] = ur
    return ur


def get_user_role(ur_id: str) -> Optional[UserRole]:
    return _user_roles.get(ur_id)


def list_user_roles(user_id: Optional[str] = None,
                    tenant_id: Optional[str] = None) -> List[UserRole]:
    out = list(_user_roles.values())
    if user_id is not None:
        out = [u for u in out if u.user_id == user_id]
    if tenant_id is not None:
        out = [u for u in out if u.tenant_id == tenant_id]
    return out


def delete_user_role(ur_id: str) -> bool:
    if ur_id not in _user_roles:
        return False
    del _user_roles[ur_id]
    return True
