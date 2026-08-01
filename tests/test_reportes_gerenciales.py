# -*- coding: utf-8 -*-
"""
test_reportes_gerenciales.py — Tests del módulo de Reportes Gerenciales.

Cobertura:
  Monthly Report: cálculo de márgenes, KPIs, resumen, profit/loss.
  KPIs:           dashboard completo, métricas vacías.
  Cash Flow:      neto, proyección, beginning balance.
  P&L:            EBIT, depreciación, interés, neto.
  Export:         JSON, CSV, HTML.
  Routes:         POST /monthly, POST /kpi, POST /cash-flow, POST /pnl,
                  GET /download, GET /formats, reporte no encontrado.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    KPI,
    MonthlyReport,
)
from b2b_ai.features.reportes_gerenciales.service import (
    export_report,
    generate_cash_flow,
    generate_kpi_dashboard,
    generate_monthly_report,
    generate_profit_loss,
)
from b2b_ai.features.reportes_gerenciales.routes import build_reportes_gerenciales_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_reportes_gerenciales_router())
    return app


def _client() -> TestClient:
    return TestClient(_app())


# ===========================================================================
# Tests: Monthly Report
# ===========================================================================
class TestMonthlyReport:
    def test_basic_report(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=100000, cost_of_goods=40000,
            operating_expenses=25000, taxes=5000,
        )
        assert report.revenue == 100000
        assert report.gross_profit == 60000
        assert report.net_profit == 30000

    def test_kpis_generated(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=100000, cost_of_goods=40000,
            operating_expenses=25000,
        )
        assert len(report.kpis) >= 4

    def test_margen_bruto_kpi(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=100000, cost_of_goods=40000,
        )
        margen_kpi = next(k for k in report.kpis if k.name == "Margen Bruto")
        assert abs(margen_kpi.value - 60.0) < 0.1

    def test_loss_summary(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=10000, cost_of_goods=5000,
            operating_expenses=8000,
        )
        assert report.net_profit < 0
        assert "pérdida" in report.summary.lower()

    def test_profit_summary(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=100000, cost_of_goods=40000,
            operating_expenses=25000,
        )
        assert report.net_profit > 0
        assert "utilidad" in report.summary.lower()

    def test_previous_revenue(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026,
            revenue=100000, previous_revenue=80000,
        )
        var_kpi = next(k for k in report.kpis if k.name == "Variación de Ingresos")
        assert var_kpi.value > 0  # 25% growth

    def test_zero_revenue(self):
        report = generate_monthly_report(tenant_id=1, month=7, year=2026)
        assert report.revenue == 0
        assert report.net_profit == 0

    def test_to_dict(self):
        report = generate_monthly_report(
            tenant_id=1, month=7, year=2026, revenue=50000,
        )
        d = report.to_dict()
        assert "kpis" in d
        assert "revenue" in d


# ===========================================================================
# Tests: KPI Dashboard
# ===========================================================================
class TestKPIDashboard:
    def test_basic_dashboard(self):
        kpis = generate_kpi_dashboard(
            tenant_id=1, period="2026-07",
            metrics={"revenue": 100000, "employees": 10,
                     "billed": 100000, "collected": 90000},
        )
        assert len(kpis) >= 5
        names = [k.name for k in kpis]
        assert "Tasa de Cobro" in names
        assert "DSO (Días de Cobro)" in names

    def test_tasa_de_cobro(self):
        kpis = generate_kpi_dashboard(
            tenant_id=1, period="2026-07",
            metrics={"revenue": 100000, "billed": 100000, "collected": 85000},
        )
        cobro = next(k for k in kpis if k.name == "Tasa de Cobro")
        assert abs(cobro.value - 85.0) < 0.1

    def test_empty_metrics(self):
        kpis = generate_kpi_dashboard(tenant_id=1, period="2026-07")
        assert len(kpis) >= 5  # Still generates all KPIs with defaults


# ===========================================================================
# Tests: Cash Flow
# ===========================================================================
class TestCashFlow:
    def test_basic_flow(self):
        cf = generate_cash_flow(
            tenant_id=1, period="2026-07",
            inflows=80000, outflows=60000,
            beginning_balance=50000,
        )
        assert cf.net == 20000
        assert cf.ending_balance == 70000
        assert cf.projection_next_month == 90000

    def test_negative_flow(self):
        cf = generate_cash_flow(
            tenant_id=1, period="2026-07",
            inflows=30000, outflows=50000,
            beginning_balance=40000,
        )
        assert cf.net == -20000
        assert cf.ending_balance == 20000

    def test_to_dict(self):
        cf = generate_cash_flow(
            tenant_id=1, period="2026-07",
            inflows=100000, outflows=70000,
        )
        d = cf.to_dict()
        assert "inflows" in d
        assert "projection_next_month" in d


# ===========================================================================
# Tests: P&L
# ===========================================================================
class TestProfitLoss:
    def test_basic_pnl(self):
        report = generate_profit_loss(
            tenant_id=1, period="2026-07",
            revenue=200000, cost_of_goods=80000,
            operating_expenses=50000, taxes=15000,
            depreciation=10000, interest=5000,
        )
        assert report.gross_profit == 120000
        assert report.net_profit > 0

    def test_pnl_kpis(self):
        report = generate_profit_loss(
            tenant_id=1, period="2026-07",
            revenue=200000, cost_of_goods=80000,
            operating_expenses=50000, depreciation=10000,
        )
        names = [k.name for k in report.kpis]
        assert "EBIT" in names
        assert "Costo Financiero" in names


# ===========================================================================
# Tests: Export
# ===========================================================================
class TestExport:
    def test_export_json(self):
        report = generate_monthly_report(tenant_id=1, month=7, year=2026, revenue=50000)
        result = export_report(report, "json")
        data = json.loads(result)
        assert data["revenue"] == 50000

    def test_export_csv(self):
        report = generate_monthly_report(tenant_id=1, month=7, year=2026, revenue=50000)
        result = export_report(report, "csv")
        assert "Ingresos" in result
        assert "50000" in result

    def test_export_html(self):
        report = generate_monthly_report(tenant_id=1, month=7, year=2026, revenue=50000)
        result = export_report(report, "html")
        assert "<html>" in result
        assert "Reporte Gerencial" in result

    def test_export_invalid_format(self):
        report = generate_monthly_report(tenant_id=1, month=7, year=2026)
        with pytest.raises(ValueError, match="Formato no soportado"):
            export_report(report, "xml")


# ===========================================================================
# Tests: Routes
# ===========================================================================
class TestReportesGerencialesRoutes:
    def test_monthly_json(self):
        resp = _client().post("/reportes-gerenciales/monthly", json={
            "tenant_id": 1, "month": 7, "year": 2026,
            "revenue": 100000, "cost_of_goods": 40000,
            "operating_expenses": 25000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_monthly_html(self):
        resp = _client().post("/reportes-gerenciales/monthly", json={
            "tenant_id": 1, "month": 7, "year": 2026,
            "revenue": 100000, "formato": "html",
        })
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_monthly_csv(self):
        resp = _client().post("/reportes-gerenciales/monthly", json={
            "tenant_id": 1, "month": 7, "year": 2026,
            "revenue": 100000, "formato": "csv",
        })
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_kpi(self):
        resp = _client().post("/reportes-gerenciales/kpi", json={
            "tenant_id": 1, "period": "2026-07",
            "metrics": {"revenue": 100000, "employees": 10},
        })
        assert resp.status_code == 200
        assert "kpis" in resp.json()

    def test_cash_flow(self):
        resp = _client().post("/reportes-gerenciales/cash-flow", json={
            "tenant_id": 1, "period": "2026-07",
            "inflows": 80000, "outflows": 60000,
            "beginning_balance": 50000,
        })
        assert resp.status_code == 200
        cf = resp.json()["cash_flow"]
        assert cf["net"] == 20000

    def test_pnl(self):
        resp = _client().post("/reportes-gerenciales/pnl", json={
            "tenant_id": 1, "period": "2026-07",
            "revenue": 200000, "cost_of_goods": 80000,
            "operating_expenses": 50000,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_download_not_found(self):
        resp = _client().get("/reportes-gerenciales/download/nonexistent")
        assert resp.status_code == 404

    def test_formats(self):
        resp = _client().get("/reportes-gerenciales/formats")
        assert resp.status_code == 200
        assert len(resp.json()["formats"]) == 3
