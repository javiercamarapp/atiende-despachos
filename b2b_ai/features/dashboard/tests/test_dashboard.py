# -*- coding: utf-8 -*-
"""Tests for the Admin Dashboard module."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from b2b_ai.features.dashboard.models import (
    ClientSummary, DailyMetric, DashboardOverview, RevenueReport,
    SystemHealth, UsageMetrics,
)
from b2b_ai.features.dashboard.service import DashboardService, _safe_float, _plan_to_mrr
from unittest.mock import MagicMock


# ── Model Tests ──

class TestModels:
    def test_client_summary(self):
        cs = ClientSummary(id=1, name="Test")
        assert cs.invoice_count == 0
        assert cs.monto_total == 0.0

    def test_daily_metric(self):
        dm = DailyMetric(date="2025-01-15")
        assert dm.count == 0
        assert dm.total_amount == 0.0

    def test_system_health(self):
        sh = SystemHealth()
        assert sh.status == "healthy"
        assert sh.api_uptime_pct == 100.0

    def test_usage_metrics(self):
        um = UsageMetrics()
        assert um.total_api_calls == 0
        assert um.cfdi_daily == []

    def test_revenue_report(self):
        rr = RevenueReport()
        assert rr.mrr == 0.0
        assert rr.plan_breakdown == {}

    def test_dashboard_overview(self):
        do = DashboardOverview()
        assert do.total_clients == 0
        assert do.system_status == "healthy"


# ── Helper Tests ──

class TestHelpers:
    def test_safe_float_none(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_string(self):
        assert _safe_float("123.45") == 123.45

    def test_safe_float_currency(self):
        assert _safe_float("$1,234.56") == 1234.56

    def test_safe_float_bool(self):
        assert _safe_float(True) == 1.0
        assert _safe_float(False) == 0.0

    def test_safe_float_empty(self):
        assert _safe_float("") == 0.0

    def test_safe_float_invalid(self):
        assert _safe_float("abc") == 0.0

    def test_plan_to_mrr_starter(self):
        assert _plan_to_mrr("starter") == 2999.0

    def test_plan_to_mrr_professional(self):
        assert _plan_to_mrr("professional") == 7999.0

    def test_plan_to_mrr_unknown(self):
        assert _plan_to_mrr("unknown_plan") == 4999.0


# ── Service Tests ──

class TestDashboardService:
    def _mock_db(self):
        db = MagicMock()
        db.list_tenants.return_value = [
            {"id": 1, "name": "Client A", "rfc": "RFC1", "created_at": "2025-01-01"},
            {"id": 2, "name": "Client B", "rfc": "RFC2", "created_at": "2025-02-01"},
        ]
        db.get_all_usage.return_value = [
            {"tenant_id": 1, "api_calls": 100, "invoices_processed": 50},
            {"tenant_id": 2, "api_calls": 200, "invoices_processed": 80},
        ]
        db.count_invoices.return_value = 10
        db.list_invoices.return_value = [
            {"total": "1000", "fecha": "2025-01-15", "procesado_en": "2025-01-15T10:00:00"}
        ]
        db.count_audit.return_value = 100
        db.get_usage.return_value = {"api_calls": 100, "invoices_processed": 50}
        db.get_tenant_by_id.return_value = {"id": 1, "name": "Client A", "rfc": "RFC1", "created_at": "2025-01-01"}
        db.list_billing_subscriptions.return_value = [
            {"status": "active", "plan": "starter"},
            {"status": "active", "plan": "professional"},
        ]
        return db

    def test_overview(self):
        db = self._mock_db()
        # Make count_audit(tool_name="error") return 0 so status is healthy
        db.count_audit.side_effect = lambda tool_name=None: 0 if tool_name else 100
        svc = DashboardService(db)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 2
        assert ov.system_status == "healthy"

    def test_client_list(self):
        svc = DashboardService(self._mock_db())
        result = svc.get_client_list()
        assert result["total"] == 2
        assert len(result["clients"]) == 2

    def test_client_list_search(self):
        svc = DashboardService(self._mock_db())
        result = svc.get_client_list(search="Client A")
        assert result["total"] == 1

    def test_client_detail(self):
        svc = DashboardService(self._mock_db())
        detail = svc.get_client_detail(1)
        assert detail is not None
        assert detail["name"] == "Client A"

    def test_client_detail_not_found(self):
        db = self._mock_db()
        db.get_tenant_by_id.return_value = None
        svc = DashboardService(db)
        assert svc.get_client_detail(999) is None

    def test_health(self):
        db = self._mock_db()
        db.path = ""
        db.count_audit.side_effect = lambda tool_name=None: 0 if tool_name else 100
        svc = DashboardService(db)
        h = svc.get_system_health()
        assert h.status in ("healthy", "warning", "degraded")

    def test_usage_metrics(self):
        svc = DashboardService(self._mock_db())
        um = svc.get_usage_metrics(days=7)
        assert len(um.cfdi_daily) == 7
        assert um.total_api_calls >= 0

    def test_revenue_report(self):
        svc = DashboardService(self._mock_db())
        rr = svc.get_revenue_report()
        assert rr.active_subscriptions == 2


# ── Route Tests ──

class TestRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.dashboard.routes import build_dashboard_admin_router
        from fastapi import FastAPI
        app = FastAPI()
        db = MagicMock()
        db.list_tenants.return_value = [{"id": 1, "name": "Test", "rfc": "RFC", "created_at": "2025-01-01"}]
        db.get_all_usage.return_value = [{"tenant_id": 1, "api_calls": 50, "invoices_processed": 10}]
        db.count_invoices.return_value = 5
        db.list_invoices.return_value = [{"total": "500", "fecha": "2025-01-15", "procesado_en": "2025-01-15T10:00:00", "id": 1, "folio_fiscal": "FF1", "categoria": "ingreso", "status": "ok"}]
        db.count_audit.return_value = 50
        db.path = ""
        db.get_usage.return_value = {"api_calls": 50, "invoices_processed": 10}
        def mock_get_tenant(tid):
            if tid == 1:
                return {"id": 1, "name": "Test", "rfc": "RFC", "created_at": "2025-01-01"}
            return None
        db.get_tenant_by_id.side_effect = mock_get_tenant
        db.list_billing_subscriptions.return_value = []
        router = build_dashboard_admin_router(db=db, require_api_key=lambda: None)
        app.include_router(router)
        return TestClient(app)

    def test_overview(self, client):
        resp = client.get("/admin/dashboard/overview")
        assert resp.status_code == 200

    def test_clients(self, client):
        resp = client.get("/admin/dashboard/clients")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_client_detail(self, client):
        resp = client.get("/admin/dashboard/clients/1")
        assert resp.status_code == 200

    def test_client_not_found(self, client):
        resp = client.get("/admin/dashboard/clients/999")
        assert resp.status_code == 404

    def test_health(self, client):
        resp = client.get("/admin/dashboard/health")
        assert resp.status_code == 200

    def test_usage(self, client):
        resp = client.get("/admin/dashboard/usage?days=7")
        assert resp.status_code == 200

    def test_revenue(self, client):
        resp = client.get("/admin/dashboard/revenue")
        assert resp.status_code == 200
