# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI del Pipeline de Prospectos/Leads (CRM).

Endpoints (prefijo /api/v1/pipeline-crm):
    GET    /stages                          — Lista etapas del pipeline del tenant.
    POST   /stages                          — Crea una etapa personalizada.
    POST   /leads                           — Crea un lead (score automático).
    GET    /leads                           — Lista leads con filtros.
    GET    /leads/{id}                      — Detalle de un lead.
    PATCH  /leads/{id}                      — Actualiza un lead.
    POST   /leads/{id}/move                 — Mueve a otra etapa.
    GET    /leads/{id}/activities           — Timeline de actividades.
    POST   /leads/{id}/activities           — Registra una actividad.
    GET    /next-actions                    — Próximas acciones del tenant.
    POST   /leads/{id}/proposals            — Crea una propuesta.
    GET    /leads/{id}/proposals            — Lista propuestas del lead.
    POST   /proposals/{id}/send             — Envía (DRAFT → SENT).
    POST   /proposals/{id}/accept           — Acepta (SENT → ACCEPTED).
    POST   /proposals/{id}/reject           — Rechaza (SENT → REJECTED).
    GET    /analytics/conversion-rates      — Tasa de conversión por etapa.
    GET    /analytics/average-time-in-stage — Días promedio en etapa.
    GET    /analytics/win-rate              — Tasa de cierre ganado.
    GET    /analytics/pipeline-value        — Valor del pipeline.

El router se construye con `build_prospect_pipeline_router(require_api_key)`.
Todos los endpoints exigen `require_api_key` y aislamiento multi-tenant: el
`tenant_id` se deriva SIEMPRE del contexto de auth — nunca del body.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from b2b_ai.features.prospect_pipeline.models import (
    ActivityCreate,
    LeadCreate,
    LeadSource,
    LeadStatus,
    PipelineStageCreate,
    ProposalCreate,
)
from b2b_ai.features.prospect_pipeline.service import (
    ActivityTracker,
    PipelineAnalytics,
    PipelineManager,
    ProposalManager,
)


# ---------------------------------------------------------------------------
# Schemas de request no cubiertos por los *Create
# ---------------------------------------------------------------------------

class LeadUpdate(BaseModel):
    """Schema de actualización parcial de un lead."""
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    source: Optional[LeadSource] = None
    company_size: Optional[str] = None
    budget: Optional[float] = None
    timeline: Optional[str] = None
    notes: Optional[str] = None


class MoveRequest(BaseModel):
    """Request para mover un lead de etapa."""
    stage: Optional[LeadStatus] = None   # por estado
    stage_id: Optional[str] = None       # por id de PipelineStage


# ---------------------------------------------------------------------------
# Helpers de tenant / auth
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


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_prospect_pipeline_router(require_api_key=None) -> APIRouter:
    """Construye el router del pipeline de prospectos/leads.

    Requiere `require_api_key` (nunca construir sin auth). Usa managers por
    build (estado en memoria compartido por el módulo service, con
    `_reset_state()` para tests).
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin auth."
        )

    manager = PipelineManager()
    tracker = ActivityTracker()
    proposals = ProposalManager()
    analytics = PipelineAnalytics()

    router = APIRouter(prefix="/api/v1/pipeline-crm", tags=["pipeline-crm"])
    router.dependencies.append(Depends(require_api_key))

    # -- Etapas ----------------------------------------------------------
    @router.get(
        "/stages",
        summary="Lista las etapas del pipeline del tenant.",
        response_model=None,
    )
    def list_stages(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        stages = manager.list_stages(tenant_id)
        return {"ok": True, "count": len(stages), "stages": [s.to_dict() for s in stages]}

    @router.post(
        "/stages",
        summary="Crea una etapa personalizada del pipeline.",
        response_model=None,
    )
    def create_stage(req: PipelineStageCreate, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            stage = manager.add_stage(tenant_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "stage": stage.to_dict()}

    # -- Leads -----------------------------------------------------------
    @router.post(
        "/leads",
        summary="Crea un lead con score automático.",
        response_model=None,
    )
    def create_lead(req: LeadCreate, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            lead = manager.create_lead(tenant_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "lead": lead.to_dict()}

    @router.get(
        "/leads",
        summary="Lista leads con filtros (stage, source, score, fecha).",
        response_model=None,
    )
    def list_leads(
        stage: Optional[LeadStatus] = Query(default=None),
        source: Optional[LeadSource] = Query(default=None),
        score_min: Optional[int] = Query(default=None, ge=0, le=100),
        score_max: Optional[int] = Query(default=None, ge=0, le=100),
        date_from: Optional[str] = Query(default=None),
        date_to: Optional[str] = Query(default=None),
        auth_info: dict = Depends(require_api_key),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        leads = manager.list_leads(
            tenant_id,
            stage=stage,
            source=source,
            score_min=score_min,
            score_max=score_max,
            date_from=date_from,
            date_to=date_to,
        )
        return {"ok": True, "count": len(leads), "leads": [l.to_dict() for l in leads]}

    @router.get(
        "/leads/{lead_id}",
        summary="Detalle completo de un lead (lead + actividades + propuestas).",
        response_model=None,
    )
    def get_lead(lead_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            details = manager.get_lead_details(tenant_id, lead_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, **details}

    @router.patch(
        "/leads/{lead_id}",
        summary="Actualiza un lead (recalcula score).",
        response_model=None,
    )
    def update_lead(lead_id: str, req: LeadUpdate, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            lead = manager.update_lead(
                tenant_id,
                lead_id,
                company_name=req.company_name,
                contact_name=req.contact_name,
                contact_email=req.contact_email,
                contact_phone=req.contact_phone,
                source=req.source,
                company_size=req.company_size,
                budget=req.budget,
                timeline=req.timeline,
                notes=req.notes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "lead": lead.to_dict()}

    @router.post(
        "/leads/{lead_id}/move",
        summary="Mueve un lead a otra etapa (por status o stage_id).",
        response_model=None,
    )
    def move_lead(lead_id: str, req: MoveRequest, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            if req.stage_id:
                lead = manager.move_to_stage(tenant_id, lead_id, req.stage_id)
            elif req.stage:
                lead = manager.move_stage(tenant_id, lead_id, req.stage)
            else:
                raise HTTPException(status_code=400, detail="Se requiere stage o stage_id.")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "lead": lead.to_dict()}

    # -- Actividades -----------------------------------------------------
    @router.get(
        "/leads/{lead_id}/activities",
        summary="Timeline de actividades de un lead.",
        response_model=None,
    )
    def get_timeline(lead_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            timeline = tracker.get_timeline(tenant_id, lead_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "count": len(timeline), "activities": [a.to_dict() for a in timeline]}

    @router.post(
        "/leads/{lead_id}/activities",
        summary="Registra una actividad sobre un lead.",
        response_model=None,
    )
    def log_activity(lead_id: str, req: ActivityCreate, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            activity = tracker.log_activity(tenant_id, lead_id, req)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "activity": activity.to_dict()}

    @router.get(
        "/next-actions",
        summary="Próximas acciones pendientes del tenant.",
        response_model=None,
    )
    def next_actions(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        actions = tracker.get_next_actions(tenant_id)
        return {"ok": True, "count": len(actions), "actions": [a.to_dict() for a in actions]}

    # -- Propuestas ------------------------------------------------------
    @router.post(
        "/leads/{lead_id}/proposals",
        summary="Crea una propuesta para un lead.",
        response_model=None,
    )
    def create_proposal(lead_id: str, req: ProposalCreate, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            proposal = proposals.create_proposal(tenant_id, lead_id, req)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "proposal": proposal.to_dict()}

    @router.get(
        "/leads/{lead_id}/proposals",
        summary="Lista propuestas de un lead.",
        response_model=None,
    )
    def list_proposals(lead_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        details = manager.get_lead_details(tenant_id, lead_id)
        return {"ok": True, "count": len(details["proposals"]), "proposals": details["proposals"]}

    @router.post(
        "/proposals/{proposal_id}/send",
        summary="Envía una propuesta (DRAFT → SENT).",
        response_model=None,
    )
    def send_proposal(proposal_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            prop = proposals.send_proposal(tenant_id, proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "proposal": prop.to_dict()}

    @router.post(
        "/proposals/{proposal_id}/accept",
        summary="Acepta una propuesta (SENT → ACCEPTED).",
        response_model=None,
    )
    def accept_proposal(proposal_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            prop = proposals.accept_proposal(tenant_id, proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "proposal": prop.to_dict()}

    @router.post(
        "/proposals/{proposal_id}/reject",
        summary="Rechaza una propuesta (SENT → REJECTED).",
        response_model=None,
    )
    def reject_proposal(proposal_id: str, auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            prop = proposals.reject_proposal(tenant_id, proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "proposal": prop.to_dict()}

    # -- Analytics -------------------------------------------------------
    @router.get(
        "/analytics/conversion-rates",
        summary="Tasa de conversión por etapa.",
        response_model=None,
    )
    def conversion_rates(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        return {"ok": True, "rates": analytics.conversion_rates(tenant_id)}

    @router.get(
        "/analytics/average-time-in-stage",
        summary="Días promedio en cada etapa.",
        response_model=None,
    )
    def average_time(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        return {"ok": True, "avg_days": analytics.average_time_in_stage(tenant_id)}

    @router.get(
        "/analytics/win-rate",
        summary="Tasa de cierre ganado.",
        response_model=None,
    )
    def win_rate(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        return {"ok": True, **analytics.win_rate(tenant_id)}

    @router.get(
        "/analytics/pipeline-value",
        summary="Valor del pipeline (propuestas activas).",
        response_model=None,
    )
    def pipeline_value(auth_info: dict = Depends(require_api_key)) -> dict:
        tenant_id = _require_tenant(auth_info)
        return {"ok": True, **analytics.pipeline_value(tenant_id)}

    return router


__all__ = ["build_prospect_pipeline_router"]
