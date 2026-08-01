# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Fiscal Conciliation API.

Endpoints:
    POST /api/v1/fiscal/compare        — Compare ERP vs SAT data
    GET  /api/v1/fiscal/report/{id}    — Get fiscal report
    POST /api/v1/fiscal/resolve        — Resolve an omission or discrepancy

The router is built with `build_fiscal_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.conciliacion_fiscal.models import FiscalComparison, FiscalReport
from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
from b2b_ai.features.conciliacion_fiscal.validators import (
    cross_reference_data,
    validate_fiscal_amounts,
    validate_fiscal_period,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    """Request to compare ERP vs SAT data."""
    month: int = Field(
        ...,
        ge=1,
        le=12,
        description="Mes del período (1-12)",
    )
    year: int = Field(
        ...,
        ge=2014,
        le=2099,
        description="Año del período",
    )
    erp_data: List[dict] = Field(
        default_factory=list,
        description="Registros ERP (uuid, rfc, monto, fecha, concepto)",
    )
    sat_data: List[dict] = Field(
        default_factory=list,
        description="Registros SAT (uuid, rfc, monto, fecha, concepto)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ResolveRequest(BaseModel):
    """Request to resolve an omission or discrepancy."""
    comparison_periodo: str = Field(
        ...,
        description="Período de la comparación (YYYY-MM)",
    )
    omission_id: Optional[str] = Field(
        default=None,
        description="ID de la omisión a resolver",
    )
    discrepancy_id: Optional[str] = Field(
        default=None,
        description="ID de la discrepancia a resolver",
    )
    resolution_note: str = Field(
        default="",
        description="Nota de resolución",
    )


class FiscalResponse(BaseModel):
    """Standard response for fiscal operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_fiscal_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the fiscal conciliation API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    auth_dep = require_api_key or (lambda: None)

    # In-memory service
    service = FiscalConciliationService()

    router = APIRouter(prefix="/api/v1/fiscal", tags=["fiscal"])

    # -----------------------------------------------------------------------
    # POST /compare — Compare ERP vs SAT data
    # -----------------------------------------------------------------------
    @router.post(
        "/compare",
        summary="Compare ERP records against SAT declarations.",
        response_model=None,
    )
    def compare_erp_vs_sat(
        req: CompareRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Compare ERP and SAT records for a given period, detecting omissions and discrepancies."""
        # Validate period
        periodo = f"{req.year}-{req.month:02d}"
        is_valid_period, period_err = validate_fiscal_period(periodo)
        if not is_valid_period:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        comparison = service.compare_erp_vs_sat(
            tenant_id=tenant_id,
            month=req.month,
            year=req.year,
            erp_data=req.erp_data,
            sat_data=req.sat_data,
        )

        # Generate report
        report = service.generate_fiscal_report(comparison)

        return {
            "ok": True,
            "message": f"Comparación fiscal completada para {periodo}.",
            "report_id": report.id,
            "comparison": comparison.model_dump(),
            "report": report.model_dump(),
        }

    # -----------------------------------------------------------------------
    # GET /report/{id} — Get fiscal report
    # -----------------------------------------------------------------------
    @router.get(
        "/report/{report_id}",
        summary="Get a fiscal conciliation report.",
        response_model=None,
    )
    def get_fiscal_report(
        report_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve a fiscal conciliation report by ID."""
        report = service.get_report(report_id)
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"Reporte fiscal '{report_id}' no encontrado.",
            )

        return {
            "ok": True,
            "report": report.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /resolve — Resolve an omission or discrepancy
    # -----------------------------------------------------------------------
    @router.post(
        "/resolve",
        summary="Mark an omission or discrepancy as resolved.",
        response_model=None,
    )
    def resolve_issue(
        req: ResolveRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Resolve an omission or discrepancy in a fiscal comparison."""
        resolved = False

        if req.omission_id:
            resolved = service.resolve_omission(
                req.comparison_periodo, req.omission_id
            )
        elif req.discrepancy_id:
            # For now, just return not found for discrepancies (would need similar logic)
            raise HTTPException(
                status_code=401,
                detail="Resolución de discrepancias aún no implementada.",
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="Se requiere omission_id o discrepancy_id.",
            )

        if not resolved:
            raise HTTPException(
                status_code=404,
                detail=f"Omición '{req.omission_id}' no encontrada en período '{req.comparison_periodo}'.",
            )

        return {
            "ok": True,
            "message": f"Omición '{req.omission_id}' marcada como resuelta.",
            "resolution_note": req.resolution_note,
        }

    return router
