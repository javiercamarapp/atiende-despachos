# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de Cierre Mensual (monthly_close).

Endpoints (/api/v1/close-monthly/*):
    POST /api/v1/close-monthly/open                      Abre un período de cierre.
    GET  /api/v1/close-monthly/{period_id}               Estado del período + árbol de tareas.
    POST /api/v1/close-monthly/{period_id}/tasks/{task_id}/complete   Completa una tarea.
    POST /api/v1/close-monthly/{period_id}/auto-check    Ejecuta auto-checks.
    POST /api/v1/close-monthly/{period_id}/close         Cierra el período.
    GET  /api/v1/close-monthly/history                   Histórico de períodos cerrados.

PREFIJO DISTINTO: el módulo close_management ya posee /api/v1/close. Para
evitar colisión silenciosa de rutas (primera registración gana), este módulo
usa /api/v1/close-monthly.

Todos los endpoints exigen autenticación por API key (require_api_key).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.monthly_close.models import (
    ClosePeriodStatus,
    TaskCategory,
    TaskStatus,
)
from b2b_ai.features.monthly_close.service import MonthlyCloseService
from b2b_ai.features.roles.middleware import make_require_permission
from b2b_ai.features.roles.models import Permission
from b2b_ai.features.roles.service import RolesService

ROUTER_PREFIX = "/api/v1/close-monthly"


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class OpenPeriodRequest(BaseModel):
    year: int = Field(..., ge=2014, le=2099, description="Año del período")
    month: int = Field(..., ge=1, le=12, description="Mes (1-12)")
    template: Optional[str] = Field(
        default=None, description="Nombre de plantilla (default: cierre_mensual)")


class CompleteTaskRequest(BaseModel):
    task_id: str = Field(..., description="ID de la tarea a completar")
    user_id: str = Field(default="", description="Usuario que completa")


class AutoCheckRequest(BaseModel):
    module_state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Señales de otros módulos (cfdi_pending_count, "
                    "bank_feeds_sync_status, nomina_status, ...)")


class ClosePeriodRequest(BaseModel):
    user_id: str = Field(default="", description="Usuario que cierra")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _require_tenant(auth_info: dict) -> str:
    """Extrae tenant_id del contexto de auth; rechaza si no está presente."""
    tenant_id = (auth_info or {}).get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Falta tenant_id en el contexto de autenticación.",
        )
    return str(tenant_id)


def build_monthly_close_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router de cierre mensual (/api/v1/close-monthly)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    require_permission = make_require_permission(require_api_key, RolesService())
    service = MonthlyCloseService(db=db)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["monthly-close"])

    def _get_owned_period(period_id: str, tenant_id: str):
        """Devuelve el período SOLO si pertenece al tenant autenticado.

        Resuelve por id global en el store, pero exige `period.tenant_id ==
        tenant_id`. Si el período no existe O no pertenece al tenant, devuelve
        404 (no 403) para no filtrar la existencia de períodos de otros
        tenants (defensa contra IDOR multi-tenant).
        """
        try:
            period = service.get_period(period_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(period.tenant_id) != str(tenant_id):
            raise HTTPException(
                status_code=404,
                detail=f"Período no encontrado: {period_id}",
            )
        return period

    @router.post("/open", summary="Abre un período de cierre mensual.",
                 response_model=None)
    def open_period(
        req: OpenPeriodRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            period = service.open_period(
                year=req.year,
                month=req.month,
                tenant_id=tenant_id,
                template_name=req.template,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "period": period.to_dict(),
            "tasks": [t.to_dict() for t in service.get_tasks(period.id)],
        }

    @router.get("/history", summary="Histórico de períodos de cierre.",
                response_model=None)
    def close_history(
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        periods = service.list_history(tenant_id=tenant_id)
        return {"ok": True, "count": len(periods),
                "periods": [p.to_dict() for p in periods]}

    @router.get("/{period_id}", summary="Estado del período + árbol de tareas.",
                response_model=None)
    def get_period(
        period_id: str,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _get_owned_period(period_id, tenant_id)
        try:
            status = service.get_period_status(period_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, **status}

    @router.post("/{period_id}/tasks/{task_id}/complete",
                 summary="Completa una tarea del checklist.",
                 response_model=None)
    def complete_task(
        period_id: str,
        task_id: str,
        req: Optional[CompleteTaskRequest] = None,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _get_owned_period(period_id, tenant_id)
        user_id = req.user_id if req else ""
        try:
            task = service.complete_task(period_id, task_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "task": task.to_dict()}

    @router.post("/{period_id}/auto-check",
                 summary="Ejecuta auto-checks sobre las tareas del período.",
                 response_model=None)
    def auto_check(
        period_id: str,
        req: AutoCheckRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _get_owned_period(period_id, tenant_id)
        try:
            completed = service.auto_check_tasks(
                period_id, module_state=req.module_state)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "auto_completed": len(completed),
                "completed_tasks": [t.to_dict() for t in completed]}

    @router.post("/{period_id}/close", summary="Cierra el período de cierre.",
                 response_model=None)
    def close_period(
        period_id: str,
        req: Optional[ClosePeriodRequest] = None,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.CLOSE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _get_owned_period(period_id, tenant_id)
        user_id = req.user_id if req else ""
        try:
            period = service.close_period(period_id, user_id=user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "period": period.to_dict()}

    return router
