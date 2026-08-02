# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Management Reports API.

Endpoints:
    POST /api/v1/reportes/monthly      — Generate monthly report
    POST /api/v1/reportes/kpi          — Generate KPI dashboard
    POST /api/v1/reportes/cash-flow    — Generate cash flow analysis
    POST /api/v1/reportes/profit-loss  — Generate P&L statement
    GET  /api/v1/reportes/download/{id} — Download report in specified format
    GET  /api/v1/reportes/             — List all available reports

The router is built with `build_reportes_gerenciales_router(db, require_api_key)`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    ExportFormat,
    KPI,
    MonthlyReport,
    ProfitLoss,
    ReportPeriod,
)
from b2b_ai.features.reportes_gerenciales.service import ReportesService
from b2b_ai.features.reportes_gerenciales.validators import (
    validate_amount_range,
    validate_period,
    validate_monthly_report_data,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class MonthlyReportRequest(BaseModel):
    """Request to generate a monthly report."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    year: int = Field(..., ge=2020, le=2030, description="Year")
    revenue: float = Field(default=0.0, ge=0, description="Total revenue")
    expenses: float = Field(default=0.0, ge=0, description="Total expenses")
    taxes_paid: float = Field(default=0.0, ge=0, description="Taxes paid")
    invoices_count: int = Field(default=0, ge=0, description="Invoice count")
    prev_revenue: Optional[float] = Field(default=None, description="Previous month revenue for comparison")
    prev_gross_margin: Optional[float] = Field(default=None, description="Previous month gross margin %")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")


class KPIRequest(BaseModel):
    """Request to generate a KPI dashboard."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    revenue: float = Field(default=0.0, ge=0, description="Revenue")
    expenses: float = Field(default=0.0, ge=0, description="Expenses")
    profit: float = Field(default=0.0, description="Profit")
    invoices_count: int = Field(default=0, ge=0, description="Invoice count")
    avg_ticket: float = Field(default=0.0, ge=0, description="Average ticket size")
    days_to_collect: float = Field(default=0.0, ge=0, description="Average days to collect")
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional KPI data")


class CashFlowRequest(BaseModel):
    """Request to generate cash flow analysis."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    opening_balance: float = Field(default=0.0, description="Opening balance")
    inflows: float = Field(default=0.0, ge=0, description="Cash inflows")
    outflows: float = Field(default=0.0, ge=0, description="Cash outflows")
    categories: Dict[str, float] = Field(default_factory=dict, description="Category breakdown")
    project_forward: bool = Field(default=False, description="Generate projection")
    monthly_growth_rate: float = Field(default=0.0, description="Monthly growth rate for projection")
    projection_months: int = Field(default=3, ge=1, le=12, description="Months to project")


class ProfitLossRequest(BaseModel):
    """Request to generate P&L statement."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    income: float = Field(default=0.0, ge=0, description="Total income")
    cost_of_goods_sold: float = Field(default=0.0, ge=0, description="Cost of goods sold")
    operating_expenses: float = Field(default=0.0, ge=0, description="Operating expenses")
    other_income: float = Field(default=0.0, description="Other income")
    other_expenses: float = Field(default=0.0, ge=0, description="Other expenses")
    isr_rate: float = Field(default=0.30, ge=0, le=1, description="ISR rate (default 30%)")
    cost_breakdown: Dict[str, float] = Field(default_factory=dict, description="Cost breakdown")
    expense_breakdown: Dict[str, float] = Field(default_factory=dict, description="Expense breakdown")


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_reportes_gerenciales_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the management reports API router.

    Parameters
    ----------
    db : Database instance.
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory stores
    _services: Dict[str, ReportesService] = {}

    def _get_service(tenant_id: str) -> ReportesService:
        if tenant_id not in _services:
            _services[tenant_id] = ReportesService(tenant_id=tenant_id)
        return _services[tenant_id]

    router = APIRouter(prefix="/api/v1/reportes", tags=["reportes_gerenciales"])

    # -----------------------------------------------------------------------
    # POST /monthly — Generate monthly report
    # -----------------------------------------------------------------------
    @router.post(
        "/monthly",
        summary="Generate a monthly financial report.",
        response_model=None,
    )
    def generate_monthly(
        req: MonthlyReportRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate a monthly financial summary with KPIs."""
        service = _get_service(req.tenant_id)

        try:
            report = service.generate_monthly_report(
                tenant_id=req.tenant_id,
                month=req.month,
                year=req.year,
                data={
                    "revenue": req.revenue,
                    "expenses": req.expenses,
                    "taxes_paid": req.taxes_paid,
                    "invoices_count": req.invoices_count,
                    "prev_revenue": req.prev_revenue,
                    "prev_gross_margin": req.prev_gross_margin,
                    "details": req.details,
                },
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        return {
            "ok": True,
            "report": report.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /kpi — Generate KPI dashboard
    # -----------------------------------------------------------------------
    @router.post(
        "/kpi",
        summary="Generate a KPI dashboard for the given period.",
        response_model=None,
    )
    def generate_kpi(
        req: KPIRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate a KPI dashboard with alerts for out-of-target metrics."""
        is_valid, errors = validate_period(req.period)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Período inválido: {'; '.join(errors)}",
            )

        service = _get_service(req.tenant_id)

        data = {
            "revenue": req.revenue,
            "expenses": req.expenses,
            "profit": req.profit,
            "invoices_count": req.invoices_count,
            "avg_ticket": req.avg_ticket,
            "days_to_collect": req.days_to_collect,
            **req.data,
        }

        result = service.generate_kpi_dashboard(
            tenant_id=req.tenant_id,
            period=req.period,
            data=data,
        )

        return result

    # -----------------------------------------------------------------------
    # POST /cash-flow — Generate cash flow analysis
    # -----------------------------------------------------------------------
    @router.post(
        "/cash-flow",
        summary="Generate cash flow analysis.",
        response_model=None,
    )
    def generate_cash_flow(
        req: CashFlowRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate cash flow with optional forward projection."""
        is_valid, errors = validate_period(req.period)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Período inválido: {'; '.join(errors)}",
            )

        service = _get_service(req.tenant_id)

        cash_flow = service.generate_cash_flow(
            tenant_id=req.tenant_id,
            period=req.period,
            data={
                "opening_balance": req.opening_balance,
                "inflows": req.inflows,
                "outflows": req.outflows,
                "categories": req.categories,
                "project_forward": req.project_forward,
                "monthly_growth_rate": req.monthly_growth_rate,
                "projection_months": req.projection_months,
            },
        )

        return {
            "ok": True,
            "cash_flow": cash_flow.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /profit-loss — Generate P&L statement
    # -----------------------------------------------------------------------
    @router.post(
        "/profit-loss",
        summary="Generate a Profit & Loss (Estado de Resultados) statement.",
        response_model=None,
    )
    def generate_profit_loss(
        req: ProfitLossRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate P&L with ISR/IVA estimation."""
        is_valid, errors = validate_period(req.period)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Período inválido: {'; '.join(errors)}",
            )

        service = _get_service(req.tenant_id)

        pl = service.generate_profit_loss(
            tenant_id=req.tenant_id,
            period=req.period,
            data={
                "income": req.income,
                "cost_of_goods_sold": req.cost_of_goods_sold,
                "operating_expenses": req.operating_expenses,
                "other_income": req.other_income,
                "other_expenses": req.other_expenses,
                "isr_rate": req.isr_rate,
                "cost_breakdown": req.cost_breakdown,
                "expense_breakdown": req.expense_breakdown,
            },
        )

        return {
            "ok": True,
            "profit_loss": pl.model_dump(),
        }

    # -----------------------------------------------------------------------
    # GET / — List all available reports
    # -----------------------------------------------------------------------
    @router.get(
        "/",
        summary="List all available report periods.",
        response_model=None,
    )
    def list_reports(
        tenant_id: str = Query(default="default", description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """List all available report periods for a tenant."""
        service = _get_service(tenant_id)
        periods = service.list_reports()
        return {
            "ok": True,
            "total": len(periods),
            "periods": periods,
        }

    # -----------------------------------------------------------------------
    # GET /download/{period} — Export report
    # -----------------------------------------------------------------------
    @router.get(
        "/download/{period}",
        summary="Download a report in the specified format.",
        response_model=None,
    )
    def download_report(
        period: str,
        tenant_id: str = Query(default="default", description="Tenant ID"),
        report_type: str = Query(default="monthly", description="Report type: monthly, cash-flow, profit-loss"),
        format: str = Query(default="json", description="Export format: json, csv, pdf"),
        auth_info: dict = Depends(auth_dep),
    ) -> Any:
        """Export a report in the specified format."""
        is_valid, errors = validate_period(period)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Período inválido: {'; '.join(errors)}",
            )

        service = _get_service(tenant_id)

        # Get the report
        report = None
        if report_type == "monthly":
            report = service.get_report(period)
        elif report_type == "cash-flow":
            report = service.get_cash_flow(period)
        elif report_type == "profit-loss":
            report = service.get_profit_loss(period)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Tipo de reporte inválido: '{report_type}'",
            )

        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró reporte {report_type} para el período '{period}'.",
            )

        # Parse format
        try:
            export_format = ExportFormat(format)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Formato inválido: '{format}'. Permitidos: json, csv, pdf.",
            )

        exported = service.export_report(report, export_format)

        if export_format == ExportFormat.CSV:
            return PlainTextResponse(content=exported, media_type="text/csv")
        elif export_format == ExportFormat.PDF:
            return PlainTextResponse(content=exported, media_type="text/markdown")
        else:
            return exported

    return router
