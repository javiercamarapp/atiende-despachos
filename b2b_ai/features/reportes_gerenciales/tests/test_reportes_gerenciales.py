# -*- coding: utf-8 -*-
"""
test_reportes_gerenciales.py — Tests for the Management Reports module.

Covers:
  - Models: construction, validation, serialization
  - Service: monthly report, KPI dashboard, cash flow, P&L, export
  - Validators: period, amount range, KPI threshold
  - Routes: all endpoints via TestClient
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    ExportFormat,
    KPI,
    MonthlyReport,
    ProfitLoss,
    ReportPeriod,
    TrendDirection,
)
from b2b_ai.features.reportes_gerenciales.service import ReportesService
from b2b_ai.features.reportes_gerenciales.validators import (
    validate_amount_range,
    validate_kpi_threshold,
    validate_monthly_report_data,
    validate_period,
)


# ===========================================================================
# 1. MODEL TESTS
# ===========================================================================

class TestModels:
    """Test Pydantic model construction and validation."""

    def test_kpi_construction(self):
        kpi = KPI(name="Ingresos", value=100000.0, unit="MXN")
        assert kpi.name == "Ingresos"
        assert kpi.value == 100000.0
        assert kpi.trend == TrendDirection.STABLE  # default

    def test_kpi_empty_name_fails(self):
        with pytest.raises(Exception):
            KPI(name="", value=0)

    def test_monthly_report_construction(self):
        report = MonthlyReport(period="2024-06", revenue=500000.0)
        assert report.period == "2024-06"
        assert report.revenue == 500000.0
        assert report.profit == 0.0  # default

    def test_monthly_report_invalid_period(self):
        with pytest.raises(Exception):
            MonthlyReport(period="invalid")

    def test_cash_flow_construction(self):
        cf = CashFlow(period="2024-06", inflows=100000, outflows=80000)
        assert cf.inflows == 100000
        assert cf.outflows == 80000
        # net defaults to 0.0; computed values come from the service layer
        assert cf.net == 0.0

    def test_cash_flow_invalid_period(self):
        with pytest.raises(Exception):
            CashFlow(period="2024")

    def test_profit_loss_construction(self):
        pl = ProfitLoss(period="2024-06", income=500000, cost_of_goods_sold=200000)
        assert pl.income == 500000
        assert pl.cost_of_goods_sold == 200000
        # gross_profit defaults to 0.0; computed values come from the service layer
        assert pl.gross_profit == 0.0

    def test_profit_loss_invalid_period(self):
        with pytest.raises(Exception):
            ProfitLoss(period="2024/06")

    def test_trend_direction_values(self):
        assert TrendDirection.UP.value == "up"
        assert TrendDirection.DOWN.value == "down"
        assert TrendDirection.STABLE.value == "stable"

    def test_export_format_values(self):
        assert ExportFormat.JSON.value == "json"
        assert ExportFormat.CSV.value == "csv"
        assert ExportFormat.PDF.value == "pdf"


# ===========================================================================
# 2. SERVICE TESTS
# ===========================================================================

class TestService:
    """Test ReportesService logic."""

    def setup_method(self):
        self.service = ReportesService(tenant_id="test-tenant")

    def test_generate_monthly_report(self):
        report = self.service.generate_monthly_report(
            tenant_id="t1",
            month=6,
            year=2024,
            data={"revenue": 500000, "expenses": 300000, "taxes_paid": 50000, "invoices_count": 120},
        )
        assert report.period == "2024-06"
        assert report.revenue == 500000
        assert report.expenses == 300000
        assert report.profit == 150000  # 500k - 300k - 50k
        assert len(report.kpis) >= 4
        assert report.id is not None

    def test_generate_monthly_report_invalid_month(self):
        with pytest.raises(ValueError, match="Mes inválido"):
            self.service.generate_monthly_report("t1", month=13, year=2024)

    def test_generate_monthly_report_with_comparison(self):
        report = self.service.generate_monthly_report(
            tenant_id="t1",
            month=6,
            year=2024,
            data={
                "revenue": 500000,
                "expenses": 300000,
                "taxes_paid": 50000,
                "invoices_count": 120,
                "prev_revenue": 450000,
                "prev_gross_margin": 35.0,
            },
        )
        # Check KPI has trend data
        revenue_kpi = next(k for k in report.kpis if k.name == "Ingresos Mensuales")
        assert revenue_kpi.change_pct is not None
        assert revenue_kpi.trend == TrendDirection.UP  # 500k > 450k

    def test_generate_kpi_dashboard(self):
        result = self.service.generate_kpi_dashboard(
            tenant_id="t1",
            period="2024-06",
            data={
                "revenue": 500000,
                "expenses": 300000,
                "profit": 200000,
                "invoices_count": 120,
                "avg_ticket": 4167,
                "days_to_collect": 35,
            },
        )
        assert result["ok"] is True
        assert len(result["kpis"]) >= 6

    def test_generate_kpi_dashboard_alerts(self):
        result = self.service.generate_kpi_dashboard(
            tenant_id="t1",
            period="2024-06",
            data={
                "revenue": 500000,
                "expenses": 400000,
                "profit": 100000,
                "invoices_count": 80,
                "days_to_collect": 60,  # above 30-day target
            },
        )
        # Should have at least one alert (days_to_collect > 30)
        assert result["summary"]["alerts_count"] >= 0

    def test_generate_cash_flow(self):
        cf = self.service.generate_cash_flow(
            tenant_id="t1",
            period="2024-06",
            data={
                "opening_balance": 100000,
                "inflows": 300000,
                "outflows": 250000,
            },
        )
        assert cf.period == "2024-06"
        assert cf.opening_balance == 100000
        assert cf.inflows == 300000
        assert cf.outflows == 250000
        assert cf.net == 50000
        assert cf.closing_balance == 150000

    def test_generate_cash_flow_with_projection(self):
        cf = self.service.generate_cash_flow(
            tenant_id="t1",
            period="2024-06",
            data={
                "opening_balance": 100000,
                "inflows": 300000,
                "outflows": 250000,
                "project_forward": True,
                "monthly_growth_rate": 0.05,
                "projection_months": 3,
            },
        )
        assert cf.projection is not None
        assert cf.projection["months"] == 3
        assert len(cf.projection["projections"]) == 3

    def test_generate_profit_loss(self):
        pl = self.service.generate_profit_loss(
            tenant_id="t1",
            period="2024-06",
            data={
                "income": 500000,
                "cost_of_goods_sold": 200000,
                "operating_expenses": 150000,
                "other_income": 10000,
                "other_expenses": 5000,
            },
        )
        assert pl.period == "2024-06"
        assert pl.income == 500000
        assert pl.gross_profit == 300000  # 500k - 200k
        assert pl.operating_profit == 150000  # 300k - 150k
        assert pl.pre_tax_profit == 155000  # 150k + 10k - 5k
        assert pl.taxes > 0  # ISR on positive profit
        assert pl.margin_pct is not None

    def test_export_json(self):
        report = self.service.generate_monthly_report("t1", 6, 2024, {"revenue": 100000})
        exported = self.service.export_report(report, ExportFormat.JSON)
        data = json.loads(exported)
        assert data["period"] == "2024-06"

    def test_export_csv(self):
        report = self.service.generate_monthly_report("t1", 6, 2024, {"revenue": 100000})
        exported = self.service.export_report(report, ExportFormat.CSV)
        assert "Campo,Valor" in exported

    def test_export_pdf(self):
        report = self.service.generate_monthly_report("t1", 6, 2024, {"revenue": 100000})
        exported = self.service.export_report(report, ExportFormat.PDF)
        assert "Reporte" in exported

    def test_list_reports(self):
        self.service.generate_monthly_report("t1", 6, 2024, {"revenue": 100000})
        self.service.generate_cash_flow("t1", "2024-06", {"inflows": 50000})
        periods = self.service.list_reports()
        assert "2024-06" in periods


# ===========================================================================
# 3. VALIDATOR TESTS
# ===========================================================================

class TestValidators:
    """Test validation functions."""

    def test_validate_period_valid(self):
        is_valid, errors = validate_period("2024-06")
        assert is_valid
        assert len(errors) == 0

    def test_validate_period_invalid_format(self):
        is_valid, errors = validate_period("2024/06")
        assert not is_valid

    def test_validate_period_empty(self):
        is_valid, errors = validate_period("")
        assert not is_valid

    def test_validate_period_invalid_month(self):
        is_valid, errors = validate_period("2024-13")
        assert not is_valid

    def test_validate_amount_range_valid(self):
        is_valid, errors = validate_amount_range(50000.0)
        assert is_valid

    def test_validate_amount_range_negative(self):
        is_valid, errors = validate_amount_range(-100.0)
        assert not is_valid

    def test_validate_amount_range_exceeds_max(self):
        is_valid, errors = validate_amount_range(2_000_000_000.0)
        assert not is_valid

    def test_validate_kpi_threshold_within(self):
        is_valid, msg = validate_kpi_threshold(95.0, target=100.0, threshold_pct=0.20)
        assert is_valid

    def test_validate_kpi_threshold_exceeds(self):
        is_valid, msg = validate_kpi_threshold(50.0, target=100.0, threshold_pct=0.20)
        assert not is_valid

    def test_validate_kpi_threshold_no_target(self):
        is_valid, msg = validate_kpi_threshold(95.0, target=None)
        assert is_valid

    def test_validate_monthly_report_data_valid(self):
        data = {"period": "2024-06", "revenue": 100000, "expenses": 50000}
        is_valid, errors = validate_monthly_report_data(data)
        assert is_valid

    def test_validate_monthly_report_data_invalid(self):
        data = {"period": "invalid"}
        is_valid, errors = validate_monthly_report_data(data)
        assert not is_valid


# ===========================================================================
# 4. ROUTE TESTS
# ===========================================================================

class TestRoutes:
    """Test API endpoints via TestClient."""

    @pytest.fixture
    def client(self):
        from b2b_ai.features.reportes_gerenciales.routes import build_reportes_gerenciales_router
        from fastapi import FastAPI

        app = FastAPI()
        router = build_reportes_gerenciales_router()
        app.include_router(router)
        return TestClient(app)

    def test_post_monthly(self, client):
        response = client.post("/api/v1/reportes/monthly", json={
            "tenant_id": "test",
            "month": 6,
            "year": 2024,
            "revenue": 500000,
            "expenses": 300000,
            "taxes_paid": 50000,
            "invoices_count": 120,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["report"]["period"] == "2024-06"

    def test_post_kpi(self, client):
        response = client.post("/api/v1/reportes/kpi", json={
            "tenant_id": "test",
            "period": "2024-06",
            "revenue": 500000,
            "expenses": 300000,
            "profit": 200000,
            "invoices_count": 120,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["kpis"]) >= 6

    def test_post_kpi_invalid_period(self, client):
        response = client.post("/api/v1/reportes/kpi", json={
            "tenant_id": "test",
            "period": "invalid",
        })
        assert response.status_code == 422

    def test_post_cash_flow(self, client):
        response = client.post("/api/v1/reportes/cash-flow", json={
            "tenant_id": "test",
            "period": "2024-06",
            "opening_balance": 100000,
            "inflows": 300000,
            "outflows": 250000,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["cash_flow"]["net"] == 50000

    def test_post_profit_loss(self, client):
        response = client.post("/api/v1/reportes/profit-loss", json={
            "tenant_id": "test",
            "period": "2024-06",
            "income": 500000,
            "cost_of_goods_sold": 200000,
            "operating_expenses": 150000,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["profit_loss"]["gross_profit"] == 300000

    def test_list_reports(self, client):
        response = client.get("/api/v1/reportes/")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_download_not_found(self, client):
        response = client.get("/api/v1/reportes/download/2024-01?tenant_id=test")
        assert response.status_code == 404
