# -*- coding: utf-8 -*-
"""routes.py — Endpoints REST del módulo de roles y permisos (RBAC).

Endpoints (todos exigen autenticación por API key; los de administración
exigen el permiso `users:manage`):

    GET   /api/v1/roles/permissions        — catálogo de permisos reconocidos
    GET   /api/v1/roles                    — lista roles (builtin + custom)
    GET   /api/v1/roles/{role_id}          — detalle de un rol
    POST  /api/v1/roles/custom             — crea un rol custom  [users:manage]
    PUT   /api/v1/roles/{role_id}          — actualiza un rol     [users:manage]
    DELETE /api/v1/roles/{role_id}         — elimina un rol custom [users:manage]
    POST  /api/v1/roles/assign             — asigna rol a usuario  [users:manage]
    DELETE /api/v1/roles/assignments/{id}  — quita una asignación  [users:manage]
    GET   /api/v1/roles/users/{user_id}    — roles de un usuario
    GET   /api/v1/roles/me/permissions     — permisos propios
    GET   /api/v1/roles/check              — verifica un permiso propio
    POST  /api/v1/roles/seed               — siembra roles por defecto [users:manage]

Sigue el patrón `build_*_router(db, require_api_key)` del proyecto. El prefijo
`/api/v1/roles` no colisiona con ningún módulo existente.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.roles.models import Permission, UserRole
from b2b_ai.features.roles.service import (
    RolesError,
    RolesService,
    seed_default_roles,
)
from b2b_ai.features.roles.middleware import make_require_permission

ROUTER_PREFIX = "/api/v1/roles"

# ---------------------------------------------------------------------------
# Schemas de request / response
# ---------------------------------------------------------------------------

class CreateCustomRoleRequest(BaseModel):
    name: str = Field(..., description="Nombre del rol custom")
    permissions: List[str] = Field(..., description="Permisos del rol")
    description: str = Field("", description="Descripción del rol")


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="Nuevo nombre")
    permissions: Optional[List[str]] = Field(default=None, description="Nuevos permisos")
    description: Optional[str] = Field(default=None, description="Nueva descripción")


class AssignRoleRequest(BaseModel):
    user_id: str = Field(..., description="ID del usuario a asignar")
    role_id: str = Field(..., description="ID del rol a asignar")


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_roles_router(db: Any = None,
                       require_api_key: Any = None) -> APIRouter:
    """Construye el router /api/v1/roles/* de roles y permisos (RBAC)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = RolesService()
    require_permission = make_require_permission(require_api_key, service)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["roles", "rbac"])

    # ------------------------------------------------------------------ #
    # Catálogos (lectura)
    # ------------------------------------------------------------------ #
    @router.get(
        "/permissions",
        summary="Catálogo de permisos reconocidos por la plataforma.",
    )
    def list_permissions(auth_info: dict = Depends(auth_dep)) -> dict:
        return {"ok": True, "permissions": service.list_permissions()}

    @router.get(
        "",
        summary="Lista los roles (builtin + custom del tenant).",
    )
    def list_roles(
        tenant_id: Optional[str] = Query(default=None,
                                         description="Filtra roles por tenant"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tid = tenant_id or auth_info.get("tenant_id")
        roles = service.list_roles(tenant_id=tid)
        return {"ok": True, "roles": [r.to_dict() for r in roles]}

    @router.get(
        "/me/permissions",
        summary="Permisos efectivos del usuario autenticado en su tenant.",
    )
    def my_permissions(auth_info: dict = Depends(auth_dep)) -> dict:
        user_id = auth_info.get("user_id")
        tenant_id = auth_info.get("tenant_id")
        if not user_id or not tenant_id:
            raise HTTPException(
                status_code=403,
                detail="RBAC: el contexto de autenticación no trae user_id/tenant_id.",
            )
        perms = service.user_permissions(user_id, tenant_id)
        roles = [r.to_dict() for r in service.get_user_roles(user_id, tenant_id)]
        return {"ok": True, "permissions": perms, "roles": roles}

    @router.get(
        "/check",
        summary="Verifica si el usuario autenticado tiene un permiso.",
    )
    def check_permission(
        permission: str = Query(..., description="Permiso a verificar, ej: cfdi:write"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        user_id = auth_info.get("user_id")
        tenant_id = auth_info.get("tenant_id")
        if not user_id or not tenant_id:
            raise HTTPException(
                status_code=403,
                detail="RBAC: el contexto de autenticación no trae user_id/tenant_id.",
            )
        granted = service.check_permission(user_id, tenant_id, permission)
        return {"ok": True, "user_id": user_id, "tenant_id": tenant_id,
                "permission": permission, "granted": granted}

    # ------------------------------------------------------------------ #
    # CRUD de roles  [users:manage]
    # ------------------------------------------------------------------ #
    @router.post(
        "/custom",
        summary="Crea un rol custom para el tenant. [users:manage]",
    )
    def create_custom_role(
        req: CreateCustomRoleRequest,
        auth_info: dict = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> dict:
        tenant_id = auth_info.get("tenant_id")
        try:
            role = service.create_custom_role(
                tenant_id=tenant_id, name=req.name,
                permissions=req.permissions, description=req.description)
        except RolesError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        return {"ok": True, "message": "Rol custom creado.",
                "role": role.to_dict()}

    @router.get("/{role_id}", summary="Detalle de un rol.")
    def get_role(role_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        try:
            role = service.get_role(role_id)
        except RolesError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        return {"ok": True, "role": role.to_dict()}

    @router.put(
        "/{role_id}",
        summary="Actualiza un rol (permisos/descripción/nombre). [users:manage]",
    )
    def update_role(
        role_id: str,
        req: UpdateRoleRequest,
        auth_info: dict = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> dict:
        try:
            role = service.update_role(
                role_id, name=req.name, permissions=req.permissions,
                description=req.description)
        except RolesError as exc:
            status = 400 if exc.code != "not_found" else 404
            raise HTTPException(status_code=status, detail=exc.message) from exc
        return {"ok": True, "message": "Rol actualizado.",
                "role": role.to_dict()}

    @router.delete(
        "/{role_id}",
        summary="Elimina un rol custom. [users:manage]",
    )
    def delete_role(role_id: str,
                    auth_info: dict = Depends(require_permission(
                        Permission.USERS_MANAGE))) -> dict:
        try:
            deleted = service.delete_role(role_id)
        except RolesError as exc:
            status = 400 if exc.code == "builtin_protected" else 404
            raise HTTPException(status_code=status, detail=exc.message) from exc
        return {"ok": True, "deleted": deleted, "message": "Rol eliminado."}

    # ------------------------------------------------------------------ #
    # Asignaciones  [users:manage]
    # ------------------------------------------------------------------ #
    @router.post(
        "/assign",
        summary="Asigna un rol a un usuario del tenant. [users:manage]",
    )
    def assign_role(
        req: AssignRoleRequest,
        auth_info: dict = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> dict:
        tenant_id = auth_info.get("tenant_id")
        actor = auth_info.get("user_id")
        try:
            ur = service.assign_role(
                user_id=req.user_id, tenant_id=tenant_id,
                role_id=req.role_id, assigned_by=actor)
        except RolesError as exc:
            status = 400 if exc.code != "not_found" else 404
            raise HTTPException(status_code=status, detail=exc.message) from exc
        return {"ok": True, "message": "Rol asignado.",
                "user_role": ur.to_dict()}

    @router.delete(
        "/assignments/{user_role_id}",
        summary="Quita una asignación de rol. [users:manage]",
    )
    def remove_assignment(
        user_role_id: str,
        auth_info: dict = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> dict:
        deleted = service.remove_role(user_role_id)
        if not deleted:
            raise HTTPException(status_code=404,
                                detail="Asignación no encontrada.")
        return {"ok": True, "deleted": True, "message": "Rol removido."}

    @router.get(
        "/users/{user_id}",
        summary="Roles efectivos de un usuario en el tenant.",
    )
    def user_roles(user_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = auth_info.get("tenant_id")
        roles = service.get_user_roles(user_id, tenant_id)
        return {"ok": True, "user_id": user_id, "roles": [r.to_dict() for r in roles]}

    # ------------------------------------------------------------------ #
    # Seed  [users:manage]
    # ------------------------------------------------------------------ #
    @router.post(
        "/seed",
        summary="Siembra los roles por defecto (idempotente). [users:manage]",
    )
    def seed(
        auth_info: dict = Depends(require_permission(Permission.USERS_MANAGE)),
    ) -> dict:
        roles = seed_default_roles()
        return {"ok": True, "seeded": len(roles),
                "roles": [r.to_dict() for r in roles]}

    return router
