# -*- coding: utf-8 -*-
"""service.py — Lógica de negocio del módulo de roles y permisos (RBAC).

`RolesService` coordina la administración de roles y la evaluación de permisos
por usuario y tenant:

    assign_role(user_id, tenant_id, role_id, assigned_by) -> UserRole
        Asigna un rol a un usuario dentro de un tenant (idempotente: reasigna
        si ya tenía otro rol en ese tenant).

    remove_role(user_role_id) -> bool
        Quita la asignación de un rol.

    check_permission(user_id, tenant_id, permission) -> bool
        Devuelve True si el usuario tiene el permiso en el tenant (vía los
        roles que se le hayan asignado, unión de permisos).

    get_user_roles(user_id, tenant_id) -> list[Role]
        Roles efectivos de un usuario en un tenant.

    list_roles(tenant_id=None) -> list[Role]
        Roles visibles (builtin + custom del tenant).

    create_custom_role(...) / update_role(...) / delete_role(...)
        CRUD de roles custom por tenant (los builtin no se borran).

    list_permissions() -> list[str]
        Catálogo completo de permisos reconocidos.

El store es en memoria (patrón `data_migration` / `onboarding` / `billing`),
con `reset_state()` para los tests. La persistencia real (PostgreSQL) queda
como siguiente iteración.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from b2b_ai.features.roles.models import (
    Permission,
    Role,
    UserRole,
    _reset_state,
    delete_role as _delete_role,
    delete_user_role as _delete_user_role,
    find_role_by_name,
    get_role as _get_role,
    list_roles as _list_roles,
    list_user_roles,
    save_role,
    save_user_role,
    is_valid_permission,
)
from b2b_ai.features.roles.seed import DEFAULT_ROLE_DEFS, seed_default_roles

logger = logging.getLogger("b2b_ai.roles")


class RolesError(Exception):
    """Error controlado del módulo de roles (expuesto al API)."""

    def __init__(self, message: str, code: str = "roles_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class RolesService:
    """Servicio de administración de roles y evaluación de permisos."""

    def __init__(self, auto_seed: bool = True):
        # Los roles por defecto deben existir siempre.
        if auto_seed and not self._seeded():
            seed_default_roles()

    @staticmethod
    def _seeded() -> bool:
        for name in DEFAULT_ROLE_DEFS:
            if find_role_by_name(name) is None:
                return False
        return True

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------
    def list_roles(self, tenant_id: Optional[str] = None) -> List[Role]:
        return _list_roles(tenant_id=tenant_id)

    def get_role(self, role_id: str) -> Role:
        role = _get_role(role_id)
        if role is None:
            raise RolesError(f"Rol no encontrado: {role_id}", code="not_found")
        return role

    def list_permissions(self) -> List[str]:
        return list(Permission.ALL)

    def create_custom_role(self, tenant_id: str, name: str,
                           permissions: List[str],
                           description: str = "") -> Role:
        """Crea un rol custom para un tenant."""
        if not tenant_id:
            raise RolesError("tenant_id es obligatorio", code="missing_tenant")
        name = (name or "").strip()
        if not name:
            raise RolesError("El nombre del rol no puede estar vacío.",
                             code="invalid_name")
        # P2-1: validar permisos explícitamente. Antes una ValidationError de
        # pydantic escapaba como 500; ahora se traduce a RolesError -> 400.
        for p in (permissions or []):
            if not is_valid_permission(p):
                raise RolesError(f"Permiso no reconocido: {p}",
                                 code="invalid_permission")
        if find_role_by_name(name, tenant_id) is not None:
            raise RolesError(f"Ya existe un rol llamado '{name}'.",
                             code="duplicate")
        role = Role(name=name, permissions=permissions,
                    description=description, tenant_id=tenant_id,
                    builtin=False)
        save_role(role)
        logger.info("custom role created tenant=%s name=%s", tenant_id, name)
        return role

    def update_role(self, role_id: str, name: Optional[str] = None,
                    permissions: Optional[List[str]] = None,
                    description: Optional[str] = None) -> Role:
        """Actualiza un rol custom. Los builtin (globales) NO se modifican."""
        role = self.get_role(role_id)
        # P1-3: los roles builtin son globales (tenant_id=None). Permitir
        # editarlos es escalación cross-tenant: un admin del tenant A podría
        # alterar el rol global admin/contador y afectar a todos los tenants.
        if role.builtin:
            raise RolesError("No se puede modificar un rol por defecto.",
                             code="builtin_protected")
        if name is not None:
            name = name.strip()
            if not name:
                raise RolesError("El nombre del rol no puede estar vacío.",
                                 code="invalid_name")
            dup = find_role_by_name(name, role.tenant_id)
            if dup is not None and dup.id != role.id:
                raise RolesError(f"Ya existe un rol llamado '{name}'.",
                                 code="duplicate")
            role.name = name
        if permissions is not None:
            for p in permissions:
                if not is_valid_permission(p):
                    raise RolesError(f"Permiso no reconocido: {p}",
                                     code="invalid_permission")
            role.permissions = list(dict.fromkeys(permissions))
        if description is not None:
            role.description = description
        role.updated_at = _utcnow_iso()
        save_role(role)
        return role

    def delete_role(self, role_id: str) -> bool:
        """Elimina un rol custom (los builtin no se eliminan)."""
        role = self.get_role(role_id)
        if role.builtin:
            raise RolesError("No se puede eliminar un rol por defecto.",
                             code="builtin_protected")
        # Quita las asignaciones de ese rol para no dejar huérfanos.
        for ur in list_user_roles():
            if ur.role_id == role_id:
                _delete_user_role(ur.id)
        return _delete_role(role_id)

    # ------------------------------------------------------------------
    # Asignación de roles
    # ------------------------------------------------------------------
    def assign_role(self, user_id: str, tenant_id: str, role_id: str,
                    assigned_by: Optional[str] = None) -> UserRole:
        """Asigna un rol a un usuario dentro de un tenant (idempotente).

        Si el usuario ya tenía una asignación en ese tenant, se reemplaza
        (un usuario tiene un rol efectivo por tenant).
        """
        if not user_id or not tenant_id:
            raise RolesError("user_id y tenant_id son obligatorios.",
                             code="missing_fields")
        role = self.get_role(role_id)
        if not (role.builtin or role.tenant_id == tenant_id):
            raise RolesError(
                f"El rol '{role.name}' no pertenece al tenant {tenant_id}.",
                code="role_not_scoped")

        # Idempotencia / reasignación en el mismo tenant.
        existing = list_user_roles(user_id=user_id, tenant_id=tenant_id)
        for ur in existing:
            if ur.role_id == role_id:
                return ur  # ya tiene ese rol exacto
            _delete_user_role(ur.id)  # reemplaza el rol anterior

        ur = UserRole(user_id=user_id, tenant_id=tenant_id,
                      role_id=role_id, assigned_by=assigned_by)
        save_user_role(ur)
        logger.info("role assigned user=%s tenant=%s role=%s", user_id,
                    tenant_id, role.name)
        return ur

    def remove_role(self, user_role_id: str) -> bool:
        return _delete_user_role(user_role_id)

    def ensure_first_user_admin(self, user_id: str, tenant_id: str) -> bool:
        """P2-2: auto-asigna el rol admin al primer usuario de un tenant.

        Utilidad de BOOTSTRAP. En modo DB, `user_id = api_keys.id` pero nada
        asigna roles de forma automática. La primera vez que un usuario aparece
        en un tenant sin ningún rol asignado, se le otorga el rol builtin
        `admin` (bootstrap), de modo que RBAC nunca quede "muerto" por falta
        de vínculo user->rol.

        ⚠️ INVARIANTE DE SEGURIDAD: este método DEBE llamarse SOLO desde la
        capa de creación de api_key o desde el seed script (provisión
        explícita), NUNCA dentro del request path del middleware RBAC.
        Auto-promover dentro de un request rompe el aislamiento multi-tenant:
        un usuario sin rol de otro tenant que consiga contexto con tenant ajeno
        obtendría admin. El request path debe devolver 403 si el usuario no
        tiene rol. (Ver test_p2_2_middleware_no_auto_asigna_admin_al_sin_rol.)
        Devuelve True si asignó el rol admin.
        """
        if not user_id or not tenant_id:
            return False
        # Si el usuario ya tiene roles efectivos en el tenant, no reasignamos.
        if self.get_user_roles(user_id, tenant_id):
            return False
        admin = find_role_by_name("admin")
        if admin is None:
            seed_default_roles()
            admin = find_role_by_name("admin")
        if admin is None:
            return False
        self.assign_role(user_id=user_id, tenant_id=tenant_id,
                         role_id=admin.id, assigned_by="bootstrap:first_user")
        return True

    def remove_user_roles(self, user_id: str, tenant_id: str) -> int:
        """Quita todas las asignaciones de un usuario en un tenant."""
        removed = 0
        for ur in list_user_roles(user_id=user_id, tenant_id=tenant_id):
            if _delete_user_role(ur.id):
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # Evaluación de permisos
    # ------------------------------------------------------------------
    def get_user_roles(self, user_id: str,
                       tenant_id: Optional[str] = None) -> List[Role]:
        """Roles efectivos de un usuario (opcionalmente filtrados por tenant).

        El mismo rol puede estar asignado en varios tenants: se devuelve una
        entrada por asignación (dedupe por rol+tenant, no solo por rol).
        """
        assign = list_user_roles(user_id=user_id, tenant_id=tenant_id)
        roles: List[Role] = []
        seen: set = set()
        for ur in assign:
            role = _get_role(ur.role_id)
            key = (ur.role_id, ur.tenant_id)
            if role is not None and key not in seen:
                seen.add(key)
                roles.append(role)
        return roles

    def user_permissions(self, user_id: str, tenant_id: str) -> List[str]:
        """Unión de permisos del usuario en el tenant (sin duplicados)."""
        out: List[str] = []
        seen: set = set()
        for role in self.get_user_roles(user_id, tenant_id):
            for perm in role.permissions:
                if perm not in seen:
                    seen.add(perm)
                    out.append(perm)
        return out

    def check_permission(self, user_id: str, tenant_id: str,
                         permission: str) -> bool:
        """True si el usuario tiene `permission` en el tenant."""
        if not is_valid_permission(permission):
            return False
        return permission in self.user_permissions(user_id, tenant_id)


def reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _reset_state()


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "RolesError",
    "RolesService",
    "reset_state",
    "seed_default_roles",
]
