# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de Tracking de Piloto (pilot_tracker).

Endpoints (/api/v1/pilot/*):
    GET  /api/v1/pilot/{tenant_id}/metrics   Métricas de un tenant (uso/ahorro).
    GET  /api/v1/pilot/{tenant_id}/health    Health score 0-100 + factores.
    GET  /api/v1/pilot/{tenant_id}/report    Reporte agregado de un período.
    GET  /api/v1/pilot/{tenant_id}/roi       Resumen ROI (horas/costo).
    POST /api/v1/pilot/record                Registra una métrica.

Multi-tenant: los endpoints que reciben {tenant_id} en el path validan que
coincida con el tenant autenticado (devolviendo 404 si no, para no filtrar
existencia) — defensa contra IDOR (lección monthly_close). POST /record toma
el tenant del contexto de auth. RBAC fino: lectura exige PILOT_VIEW; mutación
exige PILOT_MANAGE.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from b2b_ai.features.pilot_tracker.models import PilotMetricType
from b2b_ai.features.pilot_tracker.service import PilotTrackerService
from b2b_ai.features.roles.middleware import make_require_permission
from b2b_ai.features.roles.models import Permission
from b2b_ai.features.roles.service import RolesService

ROUTER_PREFIX = "/api/v1/pilot"


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class RecordMetricRequest(BaseModel):
    metric_type: PilotMetricType = Field(
        ..., description="Tipo de métrica (CFDI_PROCESSED, HOURS_SAVED, ...)")
    value: float = Field(..., ge=0.0, description="Valor de la métrica (≥0)")
    period_start: date = Field(..., description="Inicio del período (YYYY-MM-DD)")
    period_end: date = Field(..., description="Fin del período (YYYY-MM-DD)")

    @field_validator("period_end")
    @classmethod
    def _end_ge_start(cls, v: date, info) -> date:
        start = info.data.get("period_start")
        if start is not None and v < start:
            raise ValueError("period_end no puede ser anterior a period_start")
        return v


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


def _require_owned_tenant(path_tenant: str, auth_tenant: str) -> None:
    """Valida que el tenant del path coincida con el autenticado (IDOR).

    Devuelve 404 (no 403) si no coinciden, para no filtrar la existencia de
    datos de otros tenants.
    """
    if str(path_tenant) != str(auth_tenant):
        raise HTTPException(
            status_code=404,
            detail=f"No se encontraron métricas para el tenant {path_tenant}.",
        )


def build_pilot_tracker_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router de tracking de piloto (/api/v1/pilot)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    require_permission = make_require_permission(require_api_key, RolesService())
    service = PilotTrackerService(db=db)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["pilot-tracker"])

    @router.post("/record", summary="Registra una métrica de uso/ahorro.",
                 response_model=None)
    def record_metric(
        req: RecordMetricRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PILOT_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        metric = service.record_metric(
            tenant_id=tenant_id,
            metric_type=req.metric_type,
            value=req.value,
            period_start=req.period_start,
            period_end=req.period_end,
        )
        return {"ok": True, "metric": metric.to_dict()}

    @router.get("/{tenant_id}/metrics",
                summary="Métricas de un tenant (uso/ahorro).",
                response_model=None)
    def get_metrics(
        tenant_id: str,
        period_start: Optional[date] = Query(
            default=None, description="Filtrar desde este período inicio"),
        period_end: Optional[date] = Query(
            default=None, description="Filtrar hasta este período fin"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PILOT_VIEW)),
    ) -> dict:
        auth_tenant = _require_tenant(auth_info)
        _require_owned_tenant(tenant_id, auth_tenant)
        metrics = service.get_tenant_metrics(tenant_id, period_start, period_end)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "count": len(metrics),
            "metrics": [m.to_dict() for m in metrics],
        }

    @router.get("/{tenant_id}/health",
                summary="Health score 0-100 + desglose de factores.",
                response_model=None)
    def get_health(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PILOT_VIEW)),
    ) -> dict:
        auth_tenant = _require_tenant(auth_info)
        _require_owned_tenant(tenant_id, auth_tenant)
        try:
            health = service.calculate_health_score(tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "health": health.to_dict()}

    @router.get("/{tenant_id}/report",
                summary="Reporte agregado de un período.",
                response_model=None)
    def get_report(
        tenant_id: str,
        period: str = Query(..., description="Período en formato YYYY-MM"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PILOT_VIEW)),
    ) -> dict:
        auth_tenant = _require_tenant(auth_info)
        _require_owned_tenant(tenant_id, auth_tenant)
        try:
            report = service.generate_pilot_report(tenant_id, period)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "report": report.to_dict()}

    @router.get("/{tenant_id}/roi",
                summary="Resumen ROI: horas ahorradas, costo, automatización.",
                response_model=None)
    def get_roi(
        tenant_id: str,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PILOT_VIEW)),
    ) -> dict:
        auth_tenant = _require_tenant(auth_info)
        _require_owned_tenant(tenant_id, auth_tenant)
        roi = service.get_roi_summary(tenant_id)
        return {"ok": True, **roi}

    return router
