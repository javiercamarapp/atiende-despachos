# -*- coding: utf-8 -*-
"""
test_reportes_gerenciales.py — Tests for the Managerial Reports module.

Covers:
  Monthly Report: margins, KPIs, summary, profit/loss.
  KPIs: dashboard with metrics, empty metrics.
  Cash Flow: net, projection, beginning balance.
  P&L: EBIT, depreciation, interest, net.
  Export: JSON, CSV, HTML.
  Routes: POST /monthly, POST /kpi, POST /cash-flow, POST /pnl,
          GET /download, GET /formats, report not found.
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
from b2b_ai.features.reportes_gerenciales.service import ReportesGerencialesService
from b2b_ai.features.reportes_gerenciales.routes import build_reportes_gerenciales_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_reportes_gerenciales_router())
    return app


@pytest.fixture
def service():
    """Fresh ReportesGerencialesService."""
    return ReportesGerencialesService()


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(_app())


# ---------------------------------------------------------------------------
# Monthly Report
# ---------------------------------------------------------------------------

class TestMonthlyReport:
    def test_basic_report(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026,
            revenue=100000, cost_of_goods=40000,
            operating_expenses=20000, taxes=5000,
        )
        assert report.period == "2026-06"
        assert report.tenant_id == 1
        assert report.revenue == 100000.0
        assert report.cost_of_goods == 40000.0
        assert report.gross_profit == 60000.0
        assert report.operating_expenses == 20000.0
        assert report.ebitda == 40000.0
        assert report.taxes == 5000.0
        assert report.net_profit == 35000.0

    def test_report_with_previous_revenue(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026,
            revenue=100000, cost_of_goods=40000,
            previous_revenue=80000,
        )
        # Should have KPI for revenue variation
        kpi_names = [k.name for k in report.kpis]
        assert "Variación de Ingresos" in kpi_names

    def test_loss_report(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026,
            revenue=10000, cost_of_goods=5000,
            operating_expenses=8000, taxes=1000,
        )
        assert report.net_profit < 0
        assert "pérdida" in report.summary.lower()


# ---------------------------------------------------------------------------
# KPI Dashboard
# ---------------------------------------------------------------------------

class TestKPIDashboard:
    def test_default_kpis(self, service):
        kpis = service.generate_kpi_dashboard(tenant_id=1, period="2026-06")
        assert len(kpis) >= 3

    def test_custom_metrics(self, service):
        kpis = service.generate_kpi_dashboard(
            tenant_id=1, period="2026-06",
            metrics={"employees": 10, "revenue": 500000},
        )
        names = [k.name for k in kpis]
        assert "Ingresos por Empleado" in names
        assert "Tasa de Cobro" in names


# ---------------------------------------------------------------------------
# Cash Flow
# ---------------------------------------------------------------------------

class TestCashFlow:
    def test_basic_cash_flow(self, service):
        cf = service.generate_cash_flow(
            tenant_id=1, period="2026-06",
            inflows=200000, outflows=150000,
            beginning_balance=50000,
        )
        assert cf.inflows == 200000.0
        assert cf.outflows == 150000.0
        assert cf.net == 50000.0
        assert cf.beginning_balance == 50000.0
        assert cf.ending_balance == 100000.0
        assert cf.projection_next_month == 150000.0


# ---------------------------------------------------------------------------
# P&L
# ---------------------------------------------------------------------------

class TestProfitLoss:
    def test_basic_pnl(self, service):
        report = service.generate_profit_loss(
            tenant_id=1, period="2026-06",
            revenue=200000, cost_of_goods=80000,
            operating_expenses=40000, taxes=15000,
            depreciation=5000, interest=3000,
        )
        assert report.revenue == 200000.0
        assert report.gross_profit == 120000.0
        assert report.net_profit > 0
        kpi_names = [k.name for k in report.kpis]
        assert "EBIT" in kpi_names


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_json(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026, revenue=100000,
        )
        output = service.export_report(report, "json")
        data = json.loads(output)
        assert data["period"] == "2026-06"
        assert data["revenue"] == 100000.0

    def test_export_csv(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026, revenue=100000,
        )
        output = service.export_report(report, "csv")
        assert "Ingresos" in output
        assert "100000" in output

    def test_export_html(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026, revenue=100000,
        )
        output = service.export_report(report, "html")
        assert "<html" in output
        assert "Reporte Gerencial" in output

    def test_export_invalid_format(self, service):
        report = service.generate_monthly_report(
            tenant_id=1, month=6, year=2026, revenue=100000,
        )
        with pytest.raises(ValueError, match="Formato no soportado"):
            service.export_report(report, "xml")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class TestRoutes:
    def test_monthly_report_route(self, client):
        resp = client.post("/reportes-gerenciales/monthly", json={
            "tenant_id": 1, "month": 6, "year": 2026,
            "revenue": 100000, "cost_of_goods": 40000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["report"]["period"] == "2026-06"

    def test_kpi_route(self, client):
        resp = client.post("/reportes-gerenciales/kpi", json={
            "tenant_id": 1, "period": "2026-06",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_cash_flow_route(self, client):
        resp = client.post("/reportes-gerenciales/cash-flow", json={
            "tenant_id": 1, "period": "2026-06",
            "inflows": 100000, "outflows": 80000,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_pnl_route(self, client):
        resp = client.post("/reportes-gerenciales/pnl", json={
            "tenant_id": 1, "period": "2026-06",
            "revenue": 200000, "cost_of_goods": 80000,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_formats_route(self, client):
        resp = client.get("/reportes-gerenciales/formats")
        assert resp.status_code == 200
        formats = resp.json()["formats"]
        assert len(formats) == 3

    def test_download_not_found(self, client):
        resp = client.get("/reportes-gerenciales/download/nonexistent")
        assert resp.status_code == 404

    def test_monthly_html(self, client):
        resp = client.post("/reportes-gerenciales/monthly", json={
            "tenant_id": 1, "month": 6, "year": 2026,
            "revenue": 100000, "formato": "html",
        })
        assert resp.status_code == 200
        assert "<html" in resp.text
