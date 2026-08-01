# -*- coding: utf-8 -*-
"""
routes.py — FastAPI routes for Deadline Management (Vencimientos).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .models import (
    Deadline,
    DeadlineWithEscalations,
    Prioridad,
    UpcomingSummary,
)
from .service import (
    acknowledge_deadline,
    calculate_deadlines,
    check_overdue,
    create_deadline,
    escalate,
    get_deadline,
    get_deadline_with_escalations,
    get_upcoming_summary,
    mark_completed,
)


router = APIRouter(prefix="/vencimientos", tags=["vencimientos"])


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class CreateDeadlineRequest(BaseModel):
    """Request body for creating a deadline."""
    tenant_id: str = Field(..., description="Company/tenant identifier")
    tipo: str = Field(..., description="Deadline type (diot, iva, isr, provisional, contabilidad_electronica, sat)")
    fecha_limite: str = Field(..., description="Deadline date in YYYY-MM-DD format")
    prioridad: str = Field(default="media", description="Priority (baja, media, alta, critica)")
    descripcion: str = Field(default="", description="Additional details")
    responsable: str = Field(default="", description="Responsible person")


class AcknowledgeRequest(BaseModel):
    """Request to acknowledge a deadline."""
    deadline_id: str = Field(..., description="Deadline ID")
    responsable: str = Field(default="", description="Person acknowledging")


class CompleteRequest(BaseModel):
    """Request to mark a deadline as completed."""
    deadline_id: str = Field(..., description="Deadline ID")
    proof: str = Field(default="", description="Completion proof URL or description")


class EscalateRequest(BaseModel):
    """Request to escalate a deadline."""
    deadline_id: str = Field(..., description="Deadline ID to escalate")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/upcoming", response_model=UpcomingSummary)
async def get_upcoming(
    tenant_id: str = Query(..., description="Tenant identifier"),
    days: int = Query(30, ge=1, le=90, description="Days to look ahead"),
) -> UpcomingSummary:
    """Get upcoming deadlines within the next N days."""
    return get_upcoming_summary(tenant_id, days_ahead=days)


@router.get("/overdue", response_model=list[Deadline])
async def get_overdue(
    tenant_id: str = Query(..., description="Tenant identifier"),
) -> list[Deadline]:
    """Get all overdue deadlines."""
    return check_overdue(tenant_id)


@router.get("/deadline/{deadline_id}")
async def get_single_deadline(deadline_id: str) -> DeadlineWithEscalations:
    """Get a deadline with its escalation history."""
    result = get_deadline_with_escalations(deadline_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Deadline not found")
    return result


@router.post("/create", response_model=Deadline, status_code=201)
async def create_new_deadline(request: CreateDeadlineRequest) -> Deadline:
    """Create a new fiscal deadline."""
    try:
        tipo = request.tipo.lower()
        prioridad = request.prioridad.lower()
    except AttributeError:
        raise HTTPException(status_code=400, detail="Invalid tipo or prioridad")

    deadline = create_deadline(
        tenant_id=request.tenant_id,
        tipo=tipo,
        fecha_limite=request.fecha_limite,
        prioridad=prioridad,
        descripcion=request.descripcion,
        responsable=request.responsable,
    )
    return deadline


@router.post("/acknowledge")
async def acknowledge(request: AcknowledgeRequest) -> dict:
    """Acknowledge a deadline, moving it to en_proceso."""
    success = acknowledge_deadline(
        deadline_id=request.deadline_id,
        responsable=request.responsable,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Deadline not found")
    return {"status": "acknowledged", "deadline_id": request.deadline_id}


@router.post("/complete")
async def complete(request: CompleteRequest) -> dict:
    """Mark a deadline as completed with proof."""
    success = mark_completed(
        deadline_id=request.deadline_id,
        proof=request.proof,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Deadline not found")
    return {"status": "completed", "deadline_id": request.deadline_id}


@router.post("/escalate")
async def escalate_deadline(request: EscalateRequest) -> dict:
    """Escalate a deadline to the next notification level."""
    deadline = get_deadline(request.deadline_id)
    if deadline is None:
        raise HTTPException(status_code=404, detail="Deadline not found")
    escalation = escalate(deadline)
    return {
        "status": "escalated",
        "deadline_id": request.deadline_id,
        "escalation_level": escalation.level.value,
        "channel": ["email", "whatsapp", "call"][escalation.level.value - 1],
    }
