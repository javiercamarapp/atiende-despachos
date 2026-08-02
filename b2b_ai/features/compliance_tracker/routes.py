# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de Tracking de Obligaciones SAT
(compliance_tracker).

Endpoints (/api/v1/compliance/*):
    GET  /api/v1/compliance/obligations              Lista obligaciones (año/mes opcional).
    POST /api/v1/compliance/obligations              Crea una obligación.
    POST /api/v1/compliance/obligations/{id}/complete  Marca una obligación cumplida.
    GET  /api/v1/compliance/overdue                  Obligaciones vencidas.
    GET  /api/v1/compliance/upcoming                 Obligaciones próximas a vencer.
    GET  /api/v1/compliance/calendar/{year}          Calendario anual SAT (idempotente).
    POST /api/v1/compliance/alerts/generate          Genera alertas de vencimiento.
    GET  /api/v1/compliance/alerts                   Lista alertas del tenant.
    POST /api/v1/compliance/alerts/{id}/ack          Reconoce una alerta.

PREFIJO DISTINTO: el módulo legacy vencimientos posee /api/v1/vencimientos y
compliance.py es infraestructura legal compartida (no router). Para evitar
colisión silenciosa de rutas, este módulo usa /api/v1/compliance.

Todos los endpoints exigen autenticación por API key (require_api_key).
RBAC fino: lectura exige COMPLIANCE_VIEW; mutación exige COMPLIANCE_MANAGE.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from b2b_ai.features.compliance_tracker.models import ObligationType
from b2b_ai.features.compliance_tracker.service import ComplianceService
from b2b_ai.features.roles.middleware import make_require_permission
from b2b_ai.features.roles.models import Permission
from b2b_ai.features.roles.service import RolesService

ROUTER_PREFIX = "/api/v1/compliance"


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class CreateObligationRequest(BaseModel):
    obligation_type: ObligationType = Field(
        ..., description="Tipo de obligación (DIOT, ISR_MENSUAL, ...)")
    due_date: date = Field(..., description="Fecha de vencimiento (YYYY-MM-DD)")
    notes: str = Field(default="", description="Notas / seguimiento")


class CompleteObligationRequest(BaseModel):
    user_id: str = Field(default="", description="Usuario que completa la obligación")


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


def _get_owned_obligation(service: ComplianceService, obligation_id: str, tenant_id: str):
    """Devuelve la obligación SOLO si pertenece al tenant autenticado.

    Resuelve por id global en el store, pero exige `obligation.tenant_id ==
    tenant_id`. Si no existe O no pertenece al tenant, devuelve 404 (no 403)
    para no filtrar la existencia de datos de otros tenants (IDOR).
    """
    try:
        obl = service.get_obligation(obligation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if str(obl.tenant_id) != str(tenant_id):
        raise HTTPException(
            status_code=404,
            detail=f"Obligación no encontrada: {obligation_id}",
        )
    return obl


def build_compliance_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router de tracking de obligaciones SAT (/api/v1/compliance)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    require_permission = make_require_permission(require_api_key, RolesService())
    service = ComplianceService(db=db)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["compliance-tracker"])

    @router.post("/obligations", summary="Crea una obligación fiscal.",
                 response_model=None)
    def create_obligation(
        req: CreateObligationRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        obl = service.create_obligation(
            tenant_id=tenant_id,
            obligation_type=req.obligation_type,
            due_date=req.due_date,
            notes=req.notes,
        )
        return {"ok": True, "obligation": obl.to_dict()}

    @router.get("/obligations", summary="Lista obligaciones (año/mes opcional).",
                response_model=None)
    def list_obligations(
        year: Optional[int] = Query(default=None, description="Año (YYYY)"),
        month: Optional[int] = Query(default=None, ge=1, le=12,
                                     description="Mes (1-12)"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        obligations = service.get_obligations(tenant_id, year=year, month=month)
        return {
            "ok": True,
            "count": len(obligations),
            "obligations": [o.to_dict() for o in obligations],
        }

    @router.post("/obligations/{obligation_id}/complete",
                 summary="Marca una obligación como cumplida.", response_model=None)
    def complete_obligation(
        obligation_id: str,
        req: Optional[CompleteObligationRequest] = None,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        _get_owned_obligation(service, obligation_id, tenant_id)
        user_id = req.user_id if req else ""
        try:
            obl = service.complete_obligation(obligation_id, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "obligation": obl.to_dict()}

    @router.get("/overdue", summary="Obligaciones vencidas del tenant.",
                response_model=None)
    def overdue_obligations(
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        obligations = service.get_overdue(tenant_id)
        return {
            "ok": True,
            "count": len(obligations),
            "obligations": [o.to_dict() for o in obligations],
        }

    @router.get("/upcoming", summary="Obligaciones próximas a vencer.",
                response_model=None)
    def upcoming_obligations(
        days: int = Query(default=7, ge=1, le=365,
                          description="Ventana en días hacia adelante"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        obligations = service.get_upcoming(tenant_id, days=days)
        return {
            "ok": True,
            "count": len(obligations),
            "obligations": [o.to_dict() for o in obligations],
        }

    @router.get("/calendar/{year}", summary="Calendario anual SAT (idempotente).",
                response_model=None)
    def annual_calendar(
        year: int = Path(..., ge=2014, le=2099, description="Año del calendario"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        obligations = service.generate_calendar(tenant_id, year)
        return {
            "ok": True,
            "year": year,
            "count": len(obligations),
            "obligations": [o.to_dict() for o in obligations],
        }

    @router.post("/alerts/generate", summary="Genera alertas de vencimiento.",
                 response_model=None)
    def generate_alerts(
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        alerts = service.generate_alerts(tenant_id)
        return {
            "ok": True,
            "count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }

    @router.get("/alerts", summary="Lista alertas del tenant.",
                response_model=None)
    def list_alerts(
        acknowledged: Optional[bool] = Query(default=None,
                                             description="Filtrar por reconocidas"),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_VIEW)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        alerts = service.list_alerts(tenant_id, acknowledged=acknowledged)
        return {
            "ok": True,
            "count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }

    @router.post("/alerts/{alert_id}/ack", summary="Reconoce una alerta.",
                 response_model=None)
    def acknowledge_alert(
        alert_id: str,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.COMPLIANCE_MANAGE)),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            alert = service.acknowledge_alert(alert_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(alert.tenant_id) != str(tenant_id):
            raise HTTPException(
                status_code=404, detail=f"Alerta no encontrada: {alert_id}")
        return {"ok": True, "alert": alert.to_dict()}

    return router
