# -*- coding: utf-8 -*-
"""
test_reportes_gerenciales.py — Tests for the Managerial Reports module.
"""
from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow, KPI, MonthlyReport, ProfitLoss,
)
from b2b_ai.features.reportes_gerenciales.service import (
    ReportesGerencialesService,
)
from b2b_ai.features.reportes_gerenciales.routes import (
    build_reportes_gerenciales_router,
)


@pytest.fixture
def svc():
    return ReportesGerencialesService()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(build_reportes_gerenciales_router())
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


TENANT = "test-tenant"


class TestMonthlyReport:
    def test_basic_monthly_report(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        assert isinstance(report, MonthlyReport)
        assert report.period == "2026-07"
        assert report.revenue >= 0
        assert report.expenses >= 0

    def test_monthly_report_has_kpis(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        assert report.kpis is not None
        assert len(report.kpis) > 0
        for kpi in report.kpis:
            assert isinstance(kpi, KPI)

    def test_profit_calculation(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        assert report.profit == report.revenue - report.expenses


class TestKPIDashboard:
    def test_basic_kpi_dashboard(self, svc):
        dashboard = svc.generate_kpi_dashboard(TENANT, "2026-07")
        assert isinstance(dashboard, dict)
        assert "kpis" in dashboard
        assert len(dashboard["kpis"]) > 0


class TestCashFlow:
    def test_basic_cash_flow(self, svc):
        cf = svc.generate_cash_flow(TENANT, "2026-07")
        assert isinstance(cf, CashFlow)
        assert cf.inflows >= 0
        assert cf.outflows >= 0
        assert cf.net == cf.inflows - cf.outflows


class TestProfitLoss:
    def test_basic_pnl(self, svc):
        pnl = svc.generate_profit_loss(TENANT, "2026-07")
        assert isinstance(pnl, ProfitLoss)
        assert pnl.income >= 0
        assert pnl.cost_of_goods_sold >= 0
        assert pnl.gross_profit == pnl.income - pnl.cost_of_goods_sold


class TestExport:
    def test_export_json(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        result = svc.export_report(report, "json")
        assert result
        data = json.loads(result)
        assert "period" in data

    def test_export_csv(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        result = svc.export_report(report, "csv")
        assert result

    def test_export_html(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        result = svc.export_report(report, "html")
        assert result

    def test_export_invalid_format(self, svc):
        report = svc.generate_monthly_report(TENANT, 7, 2026)
        # Invalid format returns a fallback dict, not an exception
        result = svc.export_report(report, "invalid_format")
        assert isinstance(result, dict)


class TestRoutes:
    def test_monthly_report_route(self, client):
        resp = client.post("/api/v1/reportes/monthly", json={
            "tenant_id": TENANT, "month": 7, "year": 2026
        })
        assert resp.status_code in (200, 201, 422)

    def test_kpi_route(self, client):
        resp = client.post("/api/v1/reportes/kpi", json={
            "tenant_id": TENANT, "month": 7, "year": 2026
        })
        assert resp.status_code in (200, 201, 422)

    def test_cash_flow_route(self, client):
        resp = client.post("/api/v1/reportes/cash-flow", json={
            "tenant_id": TENANT, "month": 7, "year": 2026
        })
        assert resp.status_code in (200, 201, 422)

    def test_pnl_route(self, client):
        resp = client.post("/api/v1/reportes/profit-loss", json={
            "tenant_id": TENANT, "month": 7, "year": 2026
        })
        assert resp.status_code in (200, 201, 422)
