# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Multi-Tenant Data Isolation API.

Endpoints:
    POST   /api/v1/tenants                  — Create a new tenant
    GET    /api/v1/tenants                  — List tenants
    GET    /api/v1/tenants/{tenant_id}      — Get tenant details
    PUT    /api/v1/tenants/{tenant_id}      — Update tenant
    DELETE /api/v1/tenants/{tenant_id}      — Soft-delete tenant
    POST   /api/v1/tenants/{tenant_id}/suspend   — Suspend tenant
    POST   /api/v1/tenants/{tenant_id}/activate  — Activate tenant
    POST   /api/v1/tenants/{tenant_id}/block     — Block tenant
    POST   /api/v1/tenants/{tenant_id}/context   — Switch tenant context
    GET    /api/v1/tenants/{tenant_id}/config    — Get tenant config
    PUT    /api/v1/tenants/{tenant_id}/config    — Set tenant config
    GET    /api/v1/tenants/{tenant_id}/audit     — Get audit logs
    POST   /api/v1/tenants/validate-isolation    — Validate data isolation

The router is built with `build_multi_tenant_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.multi_tenant.models import (
    AuditAction,
    CreateTenantRequest,
    IsolationLevel,
    TenantStatus,
)
from b2b_ai.features.multi_tenant.service import (
    MultiTenantService,
    CrossTenantAccessError,
    TenantBlockedError,
    TenantConflictError,
    TenantNotFoundError,
)
from b2b_ai.features.multi_tenant.validators import (
    validate_tenant_access,
    validate_cross_tenant_block,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class UpdateTenantRequest(BaseModel):
    """Request to update a tenant."""
    name: Optional[str] = Field(default=None, description="Nuevo nombre del tenant")
    rfc: Optional[str] = Field(default=None, description="Nuevo RFC del tenant")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadatos adicionales"
    )


class SwitchContextRequest(BaseModel):
    """Request to switch tenant context."""
    user_id: Optional[str] = Field(default=None, description="ID del usuario")
    user_role: Optional[str] = Field(default=None, description="Rol del usuario")
    ip_address: Optional[str] = Field(default=None, description="IP del cliente")


class SetConfigRequest(BaseModel):
    """Request to set a tenant config value."""
    key: str = Field(..., description="Clave de configuración")
    value: str = Field(..., description="Valor de configuración")
    description: str = Field(default="", description="Descripción")
    sensitive: bool = Field(default=False, description="Si el valor es sensible")


class ValidateIsolationRequest(BaseModel):
    """Request to validate data isolation between tenants."""
    source_tenant_id: str = Field(..., description="Tenant que intenta acceder")
    target_tenant_id: str = Field(..., description="Tenant cuyos datos se acceden")
    resource: Optional[str] = Field(default=None, description="Recurso afectado")


class TenantResponse(BaseModel):
    """Standard response for tenant operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Middleware: Tenant Context Dependency
# ---------------------------------------------------------------------------

class TenantContextMiddleware:
    """Middleware that extracts tenant context from requests.

    Can be used as a FastAPI dependency to inject tenant context
    into endpoint handlers.
    """

    def __init__(self, service: MultiTenantService) -> None:
        self._service = service

    def __call__(self, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Extract tenant context from request.

        Parameters
        ----------
        tenant_id : Optional[str]
            Tenant ID from header, query param, or path.

        Returns
        -------
        Optional[Dict[str, Any]]
            Tenant context dict, or None if no tenant specified.
        """
        if not tenant_id:
            return None

        try:
            context = self._service.get_current_context()
            if context and context.tenant_id == tenant_id:
                return {
                    "tenant_id": context.tenant_id,
                    "tenant_name": context.tenant_name,
                    "user_id": context.user_id,
                    "user_role": context.user_role,
                    "isolation_level": context.isolation_level,
                }

            # Try to get tenant directly
            tenant = self._service.get_tenant(tenant_id)
            return {
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "isolation_level": tenant.isolation_level,
            }
        except (TenantNotFoundError, TenantBlockedError):
            return None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_multi_tenant_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the multi-tenant API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    auth_dep = require_api_key or (lambda: None)

    # In-memory service
    service = MultiTenantService()

    router = APIRouter(
        prefix="/api/v1/tenants",
        tags=["multi-tenant"],
    )

    # -------------------------------------------------------------------
    # POST /tenants — Create tenant
    # -------------------------------------------------------------------
    @router.post(
        "",
        summary="Crear un nuevo tenant.",
        response_model=None,
    )
    def create_new_tenant(
        req: CreateTenantRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Create a new tenant with schema isolation."""
        try:
            tenant = service.create_tenant(req)
            return {
                "ok": True,
                "message": f"Tenant '{tenant.name}' creado exitosamente.",
                "data": tenant.model_dump(),
            }
        except TenantConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # -------------------------------------------------------------------
    # GET /tenants — List tenants
    # -------------------------------------------------------------------
    @router.get(
        "",
        summary="Listar tenants.",
        response_model=None,
    )
    def list_tenants(
        status: Optional[str] = Query(default=None, description="Filtrar por estado"),
        include_deleted: bool = Query(default=False, description="Incluir eliminados"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """List tenants with optional filtering."""
        tenant_status = None
        if status:
            try:
                tenant_status = TenantStatus(status)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Estado inválido: '{status}'. Valores válidos: {[s.value for s in TenantStatus]}",
                )

        tenants = service.list_tenants(status=tenant_status, include_deleted=include_deleted)
        return {
            "ok": True,
            "data": [t.model_dump() for t in tenants],
            "total": len(tenants),
        }

    # -------------------------------------------------------------------
    # GET /tenants/{tenant_id} — Get tenant
    # -------------------------------------------------------------------
    @router.get(
        "/{tenant_id}",
        summary="Obtener detalles de un tenant.",
        response_model=None,
    )
    def get_tenant_details(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get tenant details by ID."""
        try:
            tenant = service.get_tenant(tenant_id)
            return {
                "ok": True,
                "data": tenant.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # PUT /tenants/{tenant_id} — Update tenant
    # -------------------------------------------------------------------
    @router.put(
        "/{tenant_id}",
        summary="Actualizar un tenant.",
        response_model=None,
    )
    def update_tenant(
        tenant_id: str,
        req: UpdateTenantRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Update tenant information."""
        try:
            tenant = service.update_tenant(
                tenant_id,
                name=req.name,
                rfc=req.rfc,
                metadata=req.metadata,
            )
            return {
                "ok": True,
                "message": f"Tenant '{tenant.name}' actualizado exitosamente.",
                "data": tenant.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except TenantConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # -------------------------------------------------------------------
    # DELETE /tenants/{tenant_id} — Soft-delete tenant
    # -------------------------------------------------------------------
    @router.delete(
        "/{tenant_id}",
        summary="Eliminar un tenant (soft-delete).",
        response_model=None,
    )
    def delete_tenant(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Soft-delete a tenant."""
        try:
            service.delete_tenant(tenant_id)
            return {
                "ok": True,
                "message": f"Tenant '{tenant_id}' eliminado exitosamente.",
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # POST /tenants/{tenant_id}/suspend — Suspend tenant
    # -------------------------------------------------------------------
    @router.post(
        "/{tenant_id}/suspend",
        summary="Suspender un tenant.",
        response_model=None,
    )
    def suspend_tenant(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Suspend a tenant (data preserved, access blocked)."""
        try:
            tenant = service.suspend_tenant(tenant_id)
            return {
                "ok": True,
                "message": f"Tenant '{tenant.name}' suspendido.",
                "data": tenant.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # POST /tenants/{tenant_id}/activate — Activate tenant
    # -------------------------------------------------------------------
    @router.post(
        "/{tenant_id}/activate",
        summary="Activar un tenant.",
        response_model=None,
    )
    def activate_tenant(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Activate a suspended tenant."""
        try:
            tenant = service.activate_tenant(tenant_id)
            return {
                "ok": True,
                "message": f"Tenant '{tenant.name}' activado.",
                "data": tenant.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # POST /tenants/{tenant_id}/block — Block tenant
    # -------------------------------------------------------------------
    @router.post(
        "/{tenant_id}/block",
        summary="Bloquear un tenant.",
        response_model=None,
    )
    def block_tenant(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Block a tenant (complete access denial)."""
        try:
            tenant = service.block_tenant(tenant_id)
            return {
                "ok": True,
                "message": f"Tenant '{tenant.name}' bloqueado.",
                "data": tenant.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # POST /tenants/{tenant_id}/context — Switch context
    # -------------------------------------------------------------------
    @router.post(
        "/{tenant_id}/context",
        summary="Cambiar contexto de tenant.",
        response_model=None,
    )
    def switch_context(
        tenant_id: str,
        req: SwitchContextRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Switch the active tenant context."""
        try:
            context = service.switch_tenant_context(
                tenant_id,
                user_id=req.user_id,
                user_role=req.user_role,
                ip_address=req.ip_address,
            )
            return {
                "ok": True,
                "message": f"Contexto cambiado a tenant '{context.tenant_name}'.",
                "data": context.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except TenantBlockedError as e:
            raise HTTPException(status_code=403, detail=str(e))

    # -------------------------------------------------------------------
    # GET /tenants/{tenant_id}/config — Get config
    # -------------------------------------------------------------------
    @router.get(
        "/{tenant_id}/config",
        summary="Obtener configuración del tenant.",
        response_model=None,
    )
    def get_tenant_config(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get all configuration for a tenant."""
        try:
            config = service.get_config(tenant_id)
            return {
                "ok": True,
                "data": config,
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # PUT /tenants/{tenant_id}/config — Set config
    # -------------------------------------------------------------------
    @router.put(
        "/{tenant_id}/config",
        summary="Establecer configuración del tenant.",
        response_model=None,
    )
    def set_tenant_config(
        tenant_id: str,
        req: SetConfigRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Set a configuration value for a tenant."""
        try:
            cfg = service.set_config(
                tenant_id,
                key=req.key,
                value=req.value,
                description=req.description,
                sensitive=req.sensitive,
            )
            return {
                "ok": True,
                "message": f"Configuración '{req.key}' actualizada.",
                "data": cfg.model_dump(),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # GET /tenants/{tenant_id}/audit — Get audit logs
    # -------------------------------------------------------------------
    @router.get(
        "/{tenant_id}/audit",
        summary="Obtener logs de auditoría del tenant.",
        response_model=None,
    )
    def get_audit_logs(
        tenant_id: str,
        action: Optional[str] = Query(default=None, description="Filtrar por acción"),
        limit: int = Query(default=100, ge=1, le=1000, description="Límite de registros"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get audit logs for a tenant."""
        try:
            audit_action = None
            if action:
                try:
                    audit_action = AuditAction(action)
                except ValueError:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Acción inválida: '{action}'.",
                    )

            logs = service.get_audit_logs(
                tenant_id, action=audit_action, limit=limit
            )
            return {
                "ok": True,
                "data": [l.model_dump() for l in logs],
                "total": len(logs),
            }
        except TenantNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # -------------------------------------------------------------------
    # POST /tenants/validate-isolation — Validate data isolation
    # -------------------------------------------------------------------
    @router.post(
        "/validate-isolation",
        summary="Validar aislamiento de datos entre tenants.",
        response_model=None,
    )
    def validate_isolation(
        req: ValidateIsolationRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Validate that data access does not cross tenant boundaries."""
        is_valid, err = service.data_isolation_validator(
            req.source_tenant_id,
            req.target_tenant_id,
            req.resource,
        )
        return {
            "ok": is_valid,
            "message": err if err else "Acceso permitido.",
            "data": {
                "source_tenant_id": req.source_tenant_id,
                "target_tenant_id": req.target_tenant_id,
                "resource": req.resource,
                "is_valid": is_valid,
            },
        }

    return router
