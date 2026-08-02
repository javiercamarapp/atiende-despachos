# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Vencimientos API.

Endpoints:
    GET  /api/v1/vencimientos/upcoming     — Get upcoming deadlines
    GET  /api/v1/vencimientos/overdue      — Get overdue deadlines
    POST /api/v1/vencimientos/acknowledge  — Acknowledge/mark deadline completed
    POST /api/v1/vencimientos/calculate    — Calculate deadlines for a period
    GET  /api/v1/vencimientos/summary      — Get deadline summary
    GET  /api/v1/vencimientos/escalations  — Get escalation history

The router is built with `build_vencimientos_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.vencimientos.models import Deadline, Escalation, VencimientoSummary
from b2b_ai.features.vencimientos.service import VencimientosService
from b2b_ai.features.vencimientos.validators import (
    validate_date,
    validate_date_range_venc,
    validate_priority,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AcknowledgeRequest(BaseModel):
    """Request to acknowledge/complete a deadline."""
    deadline_id: str = Field(
        ...,
        description="ID del vencimiento a completar",
    )
    proof: str = Field(
        default="",
        description="URL o referencia del comprobante de presentación",
    )
    note: str = Field(
        default="",
        description="Nota adicional",
    )


class CalculateRequest(BaseModel):
    """Request to calculate deadlines for a period."""
    month: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Mes (1-12). Default: mes actual.",
    )
    year: Optional[int] = Field(
        default=None,
        ge=2014,
        le=2099,
        description="Año. Default: año actual.",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class VencimientosResponse(BaseModel):
    """Standard response for vencimientos operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_vencimientos_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the vencimientos API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory service
    service = VencimientosService()

    router = APIRouter(prefix="/api/v1/vencimientos", tags=["vencimientos"])

    # -----------------------------------------------------------------------
    # GET /upcoming — Get upcoming deadlines
    # -----------------------------------------------------------------------
    @router.get(
        "/upcoming",
        summary="Get upcoming fiscal deadlines.",
        response_model=None,
    )
    def get_upcoming(
        days_ahead: int = Query(default=30, ge=1, le=365, description="Días a proyectar"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get deadlines that are approaching within N days."""
        tenant_id = auth_info.get("tenant_id") if auth_info else None
        deadlines = service.get_upcoming(tenant_id=tenant_id, days_ahead=days_ahead)

        return {
            "ok": True,
            "total": len(deadlines),
            "deadlines": [d.model_dump() for d in deadlines],
        }

    # -----------------------------------------------------------------------
    # GET /overdue — Get overdue deadlines
    # -----------------------------------------------------------------------
    @router.get(
        "/overdue",
        summary="Get overdue fiscal deadlines.",
        response_model=None,
    )
    def get_overdue(
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get deadlines that are past their due date."""
        tenant_id = auth_info.get("tenant_id") if auth_info else None
        overdue = service.check_overdue(tenant_id=tenant_id)

        return {
            "ok": True,
            "total": len(overdue),
            "deadlines": [d.model_dump() for d in overdue],
        }

    # -----------------------------------------------------------------------
    # POST /acknowledge — Acknowledge/mark deadline completed
    # -----------------------------------------------------------------------
    @router.post(
        "/acknowledge",
        summary="Mark a deadline as completed.",
        response_model=None,
    )
    def acknowledge_deadline(
        req: AcknowledgeRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Mark a deadline as completed with optional proof."""
        completed = service.mark_completed(
            deadline_id=req.deadline_id,
            proof=req.proof,
        )

        if not completed:
            raise HTTPException(
                status_code=404,
                detail=f"Vencimiento '{req.deadline_id}' no encontrado.",
            )

        return {
            "ok": True,
            "message": f"Vencimiento '{req.deadline_id}' marcado como completado.",
            "deadline_id": req.deadline_id,
            "proof": req.proof,
            "note": req.note,
        }

    # -----------------------------------------------------------------------
    # POST /calculate — Calculate deadlines for a period
    # -----------------------------------------------------------------------
    @router.post(
        "/calculate",
        summary="Calculate fiscal deadlines for a period.",
        response_model=None,
    )
    def calculate_deadlines(
        req: CalculateRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Calculate standard fiscal deadlines for a given period."""
        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        deadlines = service.calculate_deadlines(
            tenant_id=tenant_id,
            month=req.month,
            year=req.year,
        )

        return {
            "ok": True,
            "message": f"Se calcularon {len(deadlines)} vencimientos.",
            "total": len(deadlines),
            "deadlines": [d.model_dump() for d in deadlines],
        }

    # -----------------------------------------------------------------------
    # GET /summary — Get deadline summary
    # -----------------------------------------------------------------------
    @router.get(
        "/summary",
        summary="Get deadline summary.",
        response_model=None,
    )
    def get_summary(
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get a summary of all deadlines."""
        tenant_id = auth_info.get("tenant_id") if auth_info else None
        summary = service.get_summary(tenant_id=tenant_id)

        return {
            "ok": True,
            "summary": summary.model_dump(),
        }

    # -----------------------------------------------------------------------
    # GET /escalations — Get escalation history
    # -----------------------------------------------------------------------
    @router.get(
        "/escalations",
        summary="Get escalation history.",
        response_model=None,
    )
    def get_escalations(
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get all escalation events."""
        return {
            "ok": True,
            "total": len(service._escalations),
            "escalations": [e.model_dump() for e in service._escalations],
        }

    return router
