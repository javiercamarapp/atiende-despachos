# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Periodic Declarations API.

Endpoints:
    POST /api/v1/declaraciones/iva              — Generate IVA declaration draft
    POST /api/v1/declaraciones/isr-provisional   — Generate ISR provisional draft
    POST /api/v1/declaraciones/isr-anual         — Generate annual ISR draft
    GET  /api/v1/declaraciones/deadlines         — Upcoming deadlines
    POST /api/v1/declaraciones/reminders         — Send reminders
    GET  /api/v1/declaraciones/{id}             — Get declaration by ID
    GET  /api/v1/declaraciones/tenant/{tenant_id} — List declarations by tenant

The router is built with `build_declaraciones_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.declaraciones.models import (
    Declaracion,
    DeclaracionStatus,
    DeclaracionType,
    Deadline,
    ReminderResult,
)
from b2b_ai.features.declaraciones.service import DeclaracionesService
from b2b_ai.features.declaraciones.validators import (
    validate_period_consistency,
    validate_rfc,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class IvaRequest(BaseModel):
    """Request to generate an IVA declaration."""
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=2000, le=2100, description="Year (e.g., 2024)")
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(default="", description="Taxpayer RFC")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="IVA data: {iva_cobrado, iva_pagado}",
    )


class IsrProvisionalRequest(BaseModel):
    """Request to generate an ISR provisional declaration."""
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=2000, le=2100, description="Year (e.g., 2024)")
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(default="", description="Taxpayer RFC")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ISR data: {ingresos, deducciones, pagos_provisionales}",
    )


class IsrAnualRequest(BaseModel):
    """Request to generate an ISR annual declaration."""
    year: int = Field(..., ge=2000, le=2100, description="Year (e.g., 2024)")
    tenant_id: str = Field(..., description="Tenant identifier")
    rfc: str = Field(default="", description="Taxpayer RFC")
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ISR data: {ingresos, deducciones, pagos_provisionales}",
    )


class ReminderRequest(BaseModel):
    """Request to send reminders for upcoming deadlines."""
    tenant_id: str = Field(..., description="Tenant identifier")
    days_before: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Send reminder if deadline is within N days",
    )


class UpdateStatusRequest(BaseModel):
    """Request to update declaration status."""
    status: DeclaracionStatus = Field(
        ...,
        description="New status (pending, filed, accepted, rejected)",
    )


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_declaraciones_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the periodic declarations API router.

    Parameters
    ----------
    db : Database instance (unused for now; declarations are in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    auth_dep = require_api_key or (lambda: None)

    # In-memory service (singleton per router)
    service = DeclaracionesService()

    router = APIRouter(prefix="/api/v1/declaraciones", tags=["declaraciones"])

    # -- Generate IVA declaration ----------------------------------------
    @router.post(
        "/iva",
        summary="Generate a monthly IVA declaration draft.",
        response_model=None,
    )
    def generate_iva(
        req: IvaRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate an IVA declaration draft for a given month/year.

        IVA calculation:
          - iva_cobrado: IVA collected from sales
          - iva_pagado: IVA paid on purchases
          - saldo_favor: If iva_pagado > iva_cobrado (credit)
          - saldo_contra: If iva_cobrado > iva_pagado (debit)
        """
        try:
            declaracion = service.generate_monthly_iva(
                month=req.month,
                year=req.year,
                tenant_id=req.tenant_id,
                rfc=req.rfc,
                data=req.data,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        return {
            "ok": True,
            "declaracion": declaracion.model_dump(),
        }

    # -- Generate ISR provisional -----------------------------------------
    @router.post(
        "/isr-provisional",
        summary="Generate a monthly ISR provisional declaration.",
        response_model=None,
    )
    def generate_isr_provisional(
        req: IsrProvisionalRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate an ISR provisional declaration for a given month/year.

        ISR calculation uses the progressive tax table (CFF Art. 113).
        """
        try:
            declaracion = service.generate_provisional_isr(
                month=req.month,
                year=req.year,
                tenant_id=req.tenant_id,
                rfc=req.rfc,
                data=req.data,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        return {
            "ok": True,
            "declaracion": declaracion.model_dump(),
        }

    # -- Generate ISR annual ----------------------------------------------
    @router.post(
        "/isr-anual",
        summary="Generate an annual ISR declaration.",
        response_model=None,
    )
    def generate_isr_anual(
        req: IsrAnualRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate an ISR annual declaration for a given year.

        ISR Anual is due by April 30th of the following year.
        Uses the annual progressive tax table (CFF Art. 113).
        """
        try:
            declaracion = service.generate_annual_isr(
                year=req.year,
                tenant_id=req.tenant_id,
                rfc=req.rfc,
                data=req.data,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        return {
            "ok": True,
            "declaracion": declaracion.model_dump(),
        }

    # -- Get deadlines ----------------------------------------------------
    @router.get(
        "/deadlines",
        summary="Get upcoming deadlines for a tenant.",
        response_model=None,
    )
    def get_deadlines(
        tenant_id: str = Query(..., description="Tenant identifier"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get upcoming fiscal deadlines for a tenant.

        Deadlines are sorted by fecha_limite ascending.
        Status is auto-updated: PENDING → URGENT (≤5 days) → OVERDUE.
        """
        deadlines = service.calculate_deadlines(tenant_id)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "count": len(deadlines),
            "deadlines": [d.model_dump() for d in deadlines],
        }

    # -- Send reminders ---------------------------------------------------
    @router.post(
        "/reminders",
        summary="Send reminders for upcoming deadlines.",
        response_model=None,
    )
    def send_reminders(
        req: ReminderRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Send reminder notifications for deadlines approaching within days_before.

        Only sends one reminder per deadline (track via recordatorio_enviado).
        """
        reminders = service.send_reminders(
            tenant_id=req.tenant_id,
            days_before=req.days_before,
        )
        return {
            "ok": True,
            "tenant_id": req.tenant_id,
            "count": len(reminders),
            "reminders": [r.model_dump() for r in reminders],
        }

    # -- Get declaration by ID --------------------------------------------
    @router.get(
        "/{declaracion_id}",
        summary="Get a declaration by ID.",
        response_model=None,
    )
    def get_declaracion(
        declaracion_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve a declaration by its unique ID."""
        declaracion = service.get_declaracion(declaracion_id)
        if declaracion is None:
            raise HTTPException(
                status_code=404,
                detail=f"Declaración '{declaracion_id}' no encontrada.",
            )
        return {
            "ok": True,
            "declaracion": declaracion.model_dump(),
        }

    # -- List declarations by tenant --------------------------------------
    @router.get(
        "/tenant/{tenant_id}",
        summary="List all declarations for a tenant.",
        response_model=None,
    )
    def list_declaraciones(
        tenant_id: str,
        tipo: Optional[DeclaracionType] = Query(
            default=None,
            description="Filter by type (iva, isr_provisional, isr_anual)",
        ),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """List all declarations for a tenant, optionally filtered by type."""
        declaraciones = service.get_declaraciones_by_tenant(
            tenant_id=tenant_id,
            tipo=tipo,
        )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "count": len(declaraciones),
            "declaraciones": [d.model_dump() for d in declaraciones],
        }

    # -- Update declaration status ----------------------------------------
    @router.put(
        "/{declaracion_id}/status",
        summary="Update declaration status.",
        response_model=None,
    )
    def update_status(
        declaracion_id: str,
        req: UpdateStatusRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Update the status of a declaration.

        Valid transitions:
          - draft → pending → filed → accepted/rejected
        """
        declaracion = service.update_status(
            declaracion_id=declaracion_id,
            status=req.status,
        )
        if declaracion is None:
            raise HTTPException(
                status_code=404,
                detail=f"Declaración '{declaracion_id}' no encontrada.",
            )
        return {
            "ok": True,
            "declaracion": declaracion.model_dump(),
        }

    return router
