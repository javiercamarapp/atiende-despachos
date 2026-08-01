# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Reportes Gerenciales.

Endpoints:
    POST /reportes-gerenciales/monthly   — Genera reporte financiero mensual.
    POST /reportes-gerenciales/kpi       — Genera dashboard de KPIs.
    POST /reportes-gerenciales/cash-flow — Genera análisis de flujo.
    POST /reportes-gerenciales/pnl       — Genera Estado de Resultados.
    GET  /reportes-gerenciales/download/{id} — Descarga reporte en formato.
    GET  /reportes-gerenciales/formats   — Lista formatos disponibles.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.reportes_gerenciales.service import (
    export_report,
    generate_cash_flow,
    generate_kpi_dashboard,
    generate_monthly_report,
    generate_profit_loss,
)
from b2b_ai.features.reportes_gerenciales.models import MonthlyReport


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class MonthlyReportRequest(BaseModel):
    """Request para generar reporte financiero mensual."""
    tenant_id: int
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2020)
    revenue: float = Field(0.0, description="Ingresos totales")
    cost_of_goods: float = Field(0.0, description="Costo de ventas")
    operating_expenses: float = Field(0.0, description="Gastos de operación")
    taxes: float = Field(0.0, description="Impuestos")
    previous_revenue: float = Field(0.0, description="Ingresos del periodo anterior")
    formato: str = Field("json", description="Formato de salida: json, csv, html")


class KPIDashboardRequest(BaseModel):
    """Request para generar dashboard de KPIs."""
    tenant_id: int
    period: str = Field(..., description="Periodo YYYY-MM")
    metrics: dict = Field(default_factory=dict, description="Métricas personalizadas")


class CashFlowRequest(BaseModel):
    """Request para análisis de flujo de efectivo."""
    tenant_id: int
    period: str
    inflows: float = 0.0
    outflows: float = 0.0
    beginning_balance: float = 0.0
    details: dict = Field(default_factory=dict)


class PnLRequest(BaseModel):
    """Request para Estado de Resultados."""
    tenant_id: int
    period: str
    revenue: float = 0.0
    cost_of_goods: float = 0.0
    operating_expenses: float = 0.0
    other_income: float = 0.0
    taxes: float = 0.0
    depreciation: float = 0.0
    interest: float = 0.0
    formato: str = Field("json")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_reportes_gerenciales_router() -> APIRouter:
    """Devuelve un APIRouter con endpoints /reportes-gerenciales/*.

    Almacena reportes generados para descarga posterior.
    """
    router = APIRouter(prefix="/reportes-gerenciales", tags=["reportes-gerenciales"])

    _reports: dict[str, dict] = {}

    @router.post(
        "/monthly",
        summary="Genera un reporte financiero mensual.",
        response_model=None,
    )
    def generar_reporte_mensual(req: MonthlyReportRequest):
        """Genera reporte con márgenes, KPIs y resumen ejecutivo."""
        report = generate_monthly_report(
            tenant_id=req.tenant_id,
            month=req.month,
            year=req.year,
            revenue=req.revenue,
            cost_of_goods=req.cost_of_goods,
            operating_expenses=req.operating_expenses,
            taxes=req.taxes,
            previous_revenue=req.previous_revenue,
        )
        key = f"{req.tenant_id}-{req.year}-{req.month:02d}"
        _reports[key] = report.to_dict()

        # Exportar en formato solicitado
        content = export_report(report, req.formato)
        if req.formato == "html":
            return HTMLResponse(content=content, status_code=200)
        elif req.formato == "csv":
            return PlainTextResponse(
                content=content, status_code=200,
                media_type="text/csv; charset=utf-8",
            )
        return {"ok": True, "report": report.to_dict()}

    @router.post(
        "/kpi",
        summary="Genera un dashboard de KPIs.",
        response_model=None,
    )
    def generar_kpis(req: KPIDashboardRequest):
        """Genera indicadores clave de desempeño para el periodo."""
        kpis = generate_kpi_dashboard(
            tenant_id=req.tenant_id,
            period=req.period,
            metrics=req.metrics,
        )
        return {
            "ok": True,
            "period": req.period,
            "kpis": [k.to_dict() for k in kpis],
        }

    @router.post(
        "/cash-flow",
        summary="Genera análisis de flujo de efectivo.",
        response_model=None,
    )
    def generar_flujo(req: CashFlowRequest):
        """Análisis de entradas, salidas y proyección de efectivo."""
        cf = generate_cash_flow(
            tenant_id=req.tenant_id,
            period=req.period,
            inflows=req.inflows,
            outflows=req.outflows,
            beginning_balance=req.beginning_balance,
            details=req.details,
        )
        return {"ok": True, "cash_flow": cf.to_dict()}

    @router.post(
        "/pnl",
        summary="Genera Estado de Resultados (P&L).",
        response_model=None,
    )
    def generar_pnl(req: PnLRequest):
        """Estado de Resultados con desglose de gastos, depreciación e interés."""
        report = generate_profit_loss(
            tenant_id=req.tenant_id,
            period=req.period,
            revenue=req.revenue,
            cost_of_goods=req.cost_of_goods,
            operating_expenses=req.operating_expenses,
            other_income=req.other_income,
            taxes=req.taxes,
            depreciation=req.depreciation,
            interest=req.interest,
        )
        key = f"pnl-{req.tenant_id}-{req.period}"
        _reports[key] = report.to_dict()
        content = export_report(report, req.formato)
        if req.formato == "html":
            return HTMLResponse(content=content, status_code=200)
        elif req.formato == "csv":
            return PlainTextResponse(content=content, status_code=200,
                                     media_type="text/csv; charset=utf-8")
        return {"ok": True, "report": report.to_dict()}

    @router.get(
        "/download/{report_id}",
        summary="Descarga un reporte generado.",
        response_model=None,
    )
    def descargar_reporte(
        report_id: str,
        formato: str = Query(default="json", description="json, csv, html"),
    ):
        """Descarga un reporte previamente generado en el formato solicitado."""
        report_data = _reports.get(report_id)
        if report_data is None:
            raise HTTPException(status_code=404, detail=f"Reporte '{report_id}' no encontrado.")
        report = MonthlyReport(
            period=report_data.get("period", ""),
            tenant_id=report_data.get("tenant_id"),
            revenue=report_data.get("revenue", 0),
            cost_of_goods=report_data.get("cost_of_goods", 0),
            gross_profit=report_data.get("gross_profit", 0),
            operating_expenses=report_data.get("operating_expenses", 0),
            ebitda=report_data.get("ebitda", 0),
            taxes=report_data.get("taxes", 0),
            net_profit=report_data.get("net_profit", 0),
            summary=report_data.get("summary", ""),
        )
        content = export_report(report, formato)
        if formato == "html":
            return HTMLResponse(content=content, status_code=200)
        elif formato == "csv":
            return PlainTextResponse(content=content, status_code=200,
                                     media_type="text/csv; charset=utf-8")
        return {"ok": True, "report": report_data}

    @router.get(
        "/formats",
        summary="Lista los formatos de exportación disponibles.",
        response_model=None,
    )
    def listar_formatos():
        return {
            "formats": [
                {"name": "json", "description": "JSON estructurado"},
                {"name": "csv", "description": "CSV para importación"},
                {"name": "html", "description": "HTML profesional con estilos"},
            ]
        }

    return router
