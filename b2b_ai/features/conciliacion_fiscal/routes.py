# -*- coding: utf-8 -*-
"""
routes.py — FastAPI routes for Fiscal Conciliation (ERP vs SAT).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .models import FiscalComparison, FiscalReport
from .service import (
    compare_erp_vs_sat,
    generate_fiscal_report,
    get_comparison,
    get_report,
    resolve_discrepancy,
)


router = APIRouter(prefix="/fiscal", tags=["conciliacion_fiscal"])


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    """Request body for running an ERP vs SAT comparison."""
    tenant_id: str = Field(..., description="Company/tenant identifier")
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=2020, le=2030, description="Year")


class CompareResponse(BaseModel):
    """Response from the comparison endpoint."""
    comparison: FiscalComparison
    report: FiscalReport


class ResolveRequest(BaseModel):
    """Request to mark a discrepancy as resolved."""
    comparison_id: str = Field(..., description="Comparison result ID")
    discrepancy_index: int = Field(
        ...,
        ge=0,
        description="Index of the discrepancy to resolve",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/compare", response_model=CompareResponse, status_code=201)
async def run_comparison(request: CompareRequest) -> CompareResponse:
    """Run ERP vs SAT conciliation comparison for a given period.

    Cross-references ERP records with SAT filings to detect omissions
    and discrepancies.
    """
    comparison = compare_erp_vs_sat(
        tenant_id=request.tenant_id,
        month=request.month,
        year=request.year,
    )
    report = generate_fiscal_report(comparison)
    return CompareResponse(comparison=comparison, report=report)


@router.get("/report/{comparison_id}", response_model=FiscalReport)
async def get_fiscal_report(comparison_id: str) -> FiscalReport:
    """Get the fiscal conciliation report for a comparison."""
    report = get_report(comparison_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"Report not found for comparison {comparison_id}",
        )
    return report


@router.get("/comparison/{comparison_id}", response_model=FiscalComparison)
async def get_fiscal_comparison(comparison_id: str) -> FiscalComparison:
    """Get the full comparison result by ID."""
    comp = get_comparison(comparison_id)
    if comp is None:
        raise HTTPException(
            status_code=404,
            detail=f"Comparison {comparison_id} not found",
        )
    return comp


@router.post("/resolve", status_code=200)
async def resolve(request: ResolveRequest) -> dict:
    """Mark a specific discrepancy as resolved."""
    success = resolve_discrepancy(
        comparison_id=request.comparison_id,
        discrepancy_index=request.discrepancy_index,
    )
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Comparison not found or invalid discrepancy index",
        )
    return {"status": "resolved", "comparison_id": request.comparison_id}
