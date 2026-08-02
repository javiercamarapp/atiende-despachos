# -*- coding: utf-8 -*-
"""middleware.py — Dependencia FastAPI de control de permisos (RBAC).

`make_require_permission(require_api_key, service=None)` produce una fábrica
`require_permission(permission)` que se usa como `Depends(...)` en los
endpoints:

    @router.post("/cfdi", dependencies=[Depends(require_permission("cfdi:write"))])
    def crear_cfdi(...): ...

La dependencia lee `user_id` y `tenant_id` del dict que devuelve
`require_api_key` (el patrón de auth de los módulos del piloto) y consulta
`RolesService.check_permission`. Si el usuario no tiene el permiso, responde
403. En producción la resolución real de `user_id` debe inyectarse en
`require_api_key` (p. ej. desde el token JWT o la API key).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from fastapi import Depends, HTTPException

from b2b_ai.features.roles.service import RolesError, RolesService

logger = logging.getLogger("b2b_ai.roles")


class PermissionDeniedError(Exception):
    """Excepción interna: permiso denegado (se traduce a 403)."""

    def __init__(self, permission: str, user_id: str = "", tenant_id: str = ""):
        super().__init__(f"Permiso requerido: {permission}")
        self.permission = permission
        self.user_id = user_id
        self.tenant_id = tenant_id


def make_require_permission(require_api_key: Callable[..., Any],
                            service: Optional[RolesService] = None) -> Callable[..., Callable[..., Any]]:
    """Construye la fábrica `require_permission(permission)` para el API.

    Enlaza la dependencia de auth del proyecto (`require_api_key`, que debe
    devolver un dict con `user_id` y `tenant_id`) con el servicio RBAC.
    """
    svc = service or RolesService()

    def require_permission(permission: str) -> Callable[..., Any]:
        if not permission:
            raise RolesError("Permiso vacío", code="invalid_permission")

        def dependency(auth_info: Dict[str, Any] = Depends(require_api_key)) -> Dict[str, Any]:
            user_id = (auth_info or {}).get("user_id")
            tenant_id = (auth_info or {}).get("tenant_id")
            if not user_id:
                raise HTTPException(
                    status_code=403,
                    detail="RBAC: falta user_id en el contexto de autenticación.",
                )
            if not tenant_id:
                raise HTTPException(
                    status_code=403,
                    detail="RBAC: falta tenant_id en el contexto de autenticación.",
                )
            if not svc.check_permission(user_id, tenant_id, permission):
                logger.info("permission denied user=%s tenant=%s perm=%s",
                            user_id, tenant_id, permission)
                raise HTTPException(
                    status_code=403,
                    detail=f"Permiso requerido: {permission}",
                )
            return auth_info

        return dependency

    return require_permission
