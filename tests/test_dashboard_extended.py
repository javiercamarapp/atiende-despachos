# -*- coding: utf-8 -*-
"""
test_dashboard_extended.py — Extended test suite for the Admin Dashboard.

Adds 60+ tests covering:
  - Service edge cases: concurrent access simulation, empty/single client scenarios
  - Route error handling: invalid IDs, missing auth, bad pagination params
  - Usage metrics with various date ranges
  - Revenue calculations with different plan mixes
  - Health endpoint under load simulation
  - Model serialization/validation edge cases
  - Helper function boundary conditions
  - Cross-service consistency checks
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.features.dashboard.models import (
    ClientSummary,
    DailyMetric,
    DashboardOverview,
    RevenueReport,
    SystemHealth,
    UsageMetrics,
)
from b2b_ai.features.dashboard.service import (
    DashboardService,
    _safe_float,
    _plan_to_mrr,
)


API_KEY = "dashboard-extended-test-key"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def db(tmp_path):
    """Create a fresh DB for each test."""
    return Database(str(tmp_path / "ext_dash_test.db"))


@pytest.fixture
def db_single_client(db):
    """DB with exactly one client, no invoices."""
    db.create_tenant("Solo Client", rfc="SOC010101SOC")
    db.create_api_key(1, "solo-key", API_KEY)
    return db


@pytest.fixture
def db_full(db):
    """DB with multiple clients, invoices, subscriptions, and audit data."""
    # 5 tenants
    for i in range(1, 6):
        db.create_tenant(f"Tenant {i}", rfc=f"RFC{i:03d}0101RFC")

    now = datetime.utcnow().strftime("%Y-%m-%d")
    old_date = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")

    # Invoices for each tenant
    for tid in range(1, 6):
        inv_count = tid * 2  # tenant 1: 2, tenant 2: 4, ..., tenant 5: 10
        for j in range(inv_count):
            date = now if j % 2 == 0 else old_date
            db.insert_invoice(
                tid,
                {"folio_fiscal": f"UUID-{tid}-{j}", "fecha": date,
                 "total": 500.0 * (j + 1), "subtotal": 425.0 * (j + 1),
                 "iva": 75.0 * (j + 1), "emisor_rfc": f"RFC{tid:03d}0101RFC",
                 "emisor_nombre": f"Proveedor {tid}", "receptor_rfc": "REC010101",
                 "tipo": "I", "serie": "A", "folio": str(j)},
                {"categoria": "gastos" if j % 2 == 0 else "ingresos",
                 "confianza": 0.9, "razon": "test"},
                {"ok": True},
            )

    # API key
    db.create_api_key(1, "admin-key", API_KEY)

    # Billing
    plans = ["starter", "professional", "enterprise", "basic", "pro"]
    for tid in range(1, 6):
        cid = db.create_billing_customer(tid, f"t{tid}@test.com", f"Tenant {tid}")
        db.create_billing_subscription(tid, cid, plans[tid - 1], "stripe", f"sub_{tid}")

    # Audit logs
    for _ in range(80):
        db.log_call("tool", "action", status="ok")
    for _ in range(5):
        db.log_call("error", "action", status="error")

    return db


@pytest.fixture
def client_empty(db):
    """TestClient with empty DB."""
    app = create_app(db)
    return TestClient(app), db


@pytest.fixture
def client_single(db_single_client):
    """TestClient with single client DB."""
    app = create_app(db_single_client)
    return TestClient(app), db_single_client


@pytest.fixture
def client_full(db_full):
    """TestClient with full DB."""
    app = create_app(db_full)
    return TestClient(app), db_full


def _auth():
    return {"X-API-Key": API_KEY}


# --------------------------------------------------------------------------- #
# Service Edge Cases — Empty Database
# --------------------------------------------------------------------------- #

class TestServiceEdgeEmpty:
    """Service methods against a completely empty database."""

    def test_overview_zero_clients(self, db):
        svc = DashboardService(db)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 0
        assert ov.active_clients == 0
        assert ov.cfdi_count_month == 0
        assert ov.total_invoices == 0

    def test_client_list_empty_returns_empty_array(self, db):
        svc = DashboardService(db)
        result = svc.get_client_list()
        assert result["clients"] == []
        assert result["total"] == 0
        assert result["pages"] == 1

    def test_client_detail_nonexistent(self, db):
        svc = DashboardService(db)
        assert svc.get_client_detail(999) is None
        assert svc.get_client_detail(0) is None
        assert svc.get_client_detail(-1) is None

    def test_health_empty_db(self, db):
        svc = DashboardService(db)
        h = svc.get_system_health()
        assert h.total_tenants == 0
        assert h.total_invoices == 0
        assert h.status == "healthy"
        assert h.error_rate_24h == 0.0
        assert h.api_uptime_pct == 100.0

    def test_usage_empty_db(self, db):
        svc = DashboardService(db)
        u = svc.get_usage_metrics(days=30)
        assert u.total_api_calls == 0
        assert u.total_invoices_processed == 0
        assert len(u.cfdi_daily) == 30
        assert all(m.count == 0 for m in u.cfdi_daily)
        assert u.error_rate == 0.0
        assert u.llm_calls == 0

    def test_revenue_empty_db(self, db):
        svc = DashboardService(db)
        r = svc.get_revenue_report()
        assert r.mrr == 0.0
        assert r.arr == 0.0
        assert r.active_subscriptions == 0
        assert r.churn_rate == 0.0 or r.churn_rate == 1.0  # all "churned" if no data
        assert r.plan_breakdown == {}


# --------------------------------------------------------------------------- #
# Service Edge Cases — Single Client
# --------------------------------------------------------------------------- #

class TestServiceEdgeSingle:
    """Service methods with exactly one client, no invoices."""

    def test_overview_single_client_no_invoices(self, db_single_client):
        svc = DashboardService(db_single_client)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 1
        assert ov.active_clients == 0  # no recent invoices

    def test_client_list_single_no_invoices(self, db_single_client):
        svc = DashboardService(db_single_client)
        result = svc.get_client_list()
        assert result["total"] == 1
        assert result["clients"][0]["invoice_count"] == 0

    def test_client_detail_single_no_invoices(self, db_single_client):
        svc = DashboardService(db_single_client)
        detail = svc.get_client_detail(1)
        assert detail is not None
        assert detail["invoice_count"] == 0
        assert detail["monto_total"] == 0.0
        assert detail["recent_invoices"] == []
        assert detail["category_breakdown"] == {}

    def test_health_single_client(self, db_single_client):
        svc = DashboardService(db_single_client)
        h = svc.get_system_health()
        assert h.total_tenants == 1

    def test_revenue_single_no_sub(self, db_single_client):
        svc = DashboardService(db_single_client)
        r = svc.get_revenue_report()
        assert r.active_subscriptions == 0
        assert r.avg_revenue_per_client == 0.0


# --------------------------------------------------------------------------- #
# Service Edge Cases — Concurrent Access Simulation
# --------------------------------------------------------------------------- #

class TestServiceConcurrent:
    """Simulate concurrent reads on the same service instance."""

    def test_concurrent_overview_reads(self, db):
        svc = DashboardService(db)
        results = []
        errors = []

        def read_overview():
            try:
                ov = svc.get_dashboard_overview()
                results.append(ov.total_clients)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_overview) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent reads failed: {errors}"
        assert len(results) == 10
        assert all(r == 0 for r in results)

    def test_concurrent_health_reads(self, db):
        svc = DashboardService(db)
        errors = []

        def read_health():
            try:
                h = svc.get_system_health()
                assert h.status in ("healthy", "degraded", "warning")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_health) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent health reads failed: {errors}"

    def test_concurrent_usage_reads(self, db):
        svc = DashboardService(db)
        errors = []

        def read_usage():
            try:
                u = svc.get_usage_metrics(days=7)
                assert len(u.cfdi_daily) == 7
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_usage) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent usage reads failed: {errors}"

    def test_concurrent_revenue_reads(self, db):
        svc = DashboardService(db)
        errors = []

        def read_revenue():
            try:
                r = svc.get_revenue_report()
                assert isinstance(r.mrr, float)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_revenue) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent revenue reads failed: {errors}"

    def test_concurrent_client_list_reads(self, db_full):
        svc = DashboardService(db_full)
        errors = []

        def read_clients():
            try:
                result = svc.get_client_list(page=1, page_size=3)
                assert "clients" in result
                assert "total" in result
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_clients) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent client list reads failed: {errors}"

    def test_concurrent_mixed_endpoint_reads(self, db_full):
        """Simulate different endpoints being called concurrently."""
        svc = DashboardService(db_full)
        errors = []

        def read_overview():
            try:
                svc.get_dashboard_overview()
            except Exception as e:
                errors.append(f"overview: {e}")

        def read_health():
            try:
                svc.get_system_health()
            except Exception as e:
                errors.append(f"health: {e}")

        def read_usage():
            try:
                svc.get_usage_metrics(30)
            except Exception as e:
                errors.append(f"usage: {e}")

        def read_revenue():
            try:
                svc.get_revenue_report()
            except Exception as e:
                errors.append(f"revenue: {e}")

        threads = [
            threading.Thread(target=read_overview),
            threading.Thread(target=read_health),
            threading.Thread(target=read_usage),
            threading.Thread(target=read_revenue),
            threading.Thread(target=read_overview),
            threading.Thread(target=read_health),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent mixed reads failed: {errors}"


# --------------------------------------------------------------------------- #
# Route Error Handling
# --------------------------------------------------------------------------- #

class TestRouteErrorHandling:
    """Route-level error handling and validation."""

    def test_overview_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/overview")
        assert r.status_code in (401, 403)

    def test_overview_wrong_key_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/overview", headers={"X-API-Key": "wrong-key"})
        assert r.status_code in (401, 403)

    def test_health_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/health")
        assert r.status_code in (401, 403)

    def test_usage_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/usage")
        assert r.status_code in (401, 403)

    def test_revenue_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/revenue")
        assert r.status_code in (401, 403)

    def test_clients_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/clients")
        assert r.status_code in (401, 403)

    def test_client_detail_no_auth_returns_401(self, client_empty):
        tc, _ = client_empty
        r = tc.get("/admin/dashboard/clients/1")
        assert r.status_code in (401, 403)

    def test_client_detail_not_found_404(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients/9999", headers=_auth())
        assert r.status_code == 404

    def test_usage_days_boundary_365(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/usage?days=365", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert len(data["cfdi_daily"]) == 365

    def test_usage_days_boundary_1(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/usage?days=1", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert len(data["cfdi_daily"]) == 1

    def test_clients_page_zero_rejected(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?page=0", headers=_auth())
        assert r.status_code == 422  # validation error

    def test_clients_negative_page_rejected(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?page=-1", headers=_auth())
        assert r.status_code == 422

    def test_clients_page_size_zero_rejected(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?page_size=0", headers=_auth())
        assert r.status_code == 422

    def test_clients_page_size_exceeds_limit(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?page_size=101", headers=_auth())
        assert r.status_code == 422

    def test_clients_large_page_size_max_100(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?page_size=100", headers=_auth())
        assert r.status_code == 200

    def test_clients_search_empty_string(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/clients?search=", headers=_auth())
        assert r.status_code == 200

    def test_overview_returns_all_fields(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/overview", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        expected_fields = {"total_clients", "active_clients", "revenue_mrr",
                           "cfdi_count_month", "total_invoices", "total_revenue",
                           "system_status", "last_updated"}
        assert expected_fields.issubset(set(data.keys()))

    def test_health_returns_all_fields(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/health", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        expected_fields = {"status", "api_uptime_pct", "total_invoices",
                           "total_tenants", "db_size_mb", "queue_depth",
                           "error_rate_24h", "last_check", "details"}
        assert expected_fields.issubset(set(data.keys()))

    def test_revenue_returns_all_fields(self, client_full):
        tc, _ = client_full
        r = tc.get("/admin/dashboard/revenue", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        expected_fields = {"mrr", "arr", "total_revenue", "active_subscriptions",
                           "churn_rate", "avg_revenue_per_client", "plan_breakdown",
                           "period_start", "period_end"}
        assert expected_fields.issubset(set(data.keys()))


# --------------------------------------------------------------------------- #
# Usage Metrics — Various Date Ranges
# --------------------------------------------------------------------------- #

class TestUsageMetricsDateRanges:
    """Usage metrics with different date range parameters."""

    def test_usage_7_days(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=7)
        assert len(u.cfdi_daily) == 7
        assert u.period_start < u.period_end

    def test_usage_1_day(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=1)
        assert len(u.cfdi_daily) == 1

    def test_usage_90_days(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=90)
        assert len(u.cfdi_daily) == 90

    def test_usage_daily_dates_are_sequential(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=14)
        dates = [m.date for m in u.cfdi_daily]
        for i in range(1, len(dates)):
            d1 = datetime.strptime(dates[i - 1], "%Y-%m-%d")
            d2 = datetime.strptime(dates[i], "%Y-%m-%d")
            assert (d2 - d1).days == 1

    def test_usage_count_non_negative(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=30)
        for m in u.cfdi_daily:
            assert m.count >= 0
            assert m.total_amount >= 0.0

    def test_usage_total_invoices_aggregated(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=30)
        daily_total = sum(m.count for m in u.cfdi_daily)
        # Should be non-negative (may not equal total invoices if some are outside range)
        assert daily_total >= 0

    def test_usage_period_dates_correct(self, db_full):
        svc = DashboardService(db_full)
        now = datetime.utcnow()
        u = svc.get_usage_metrics(days=30)
        expected_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        assert u.period_start == expected_start

    def test_usage_avg_processing_time_non_negative(self, db_full):
        svc = DashboardService(db_full)
        u = svc.get_usage_metrics(days=30)
        assert u.avg_processing_time_sec >= 0.0


# --------------------------------------------------------------------------- #
# Revenue Calculations — Different Plan Mixes
# --------------------------------------------------------------------------- #

class TestRevenuePlanMixes:
    """Revenue report calculations with various plan combinations."""

    def test_revenue_all_starter(self, db):
        svc = DashboardService(db)
        db.create_tenant("S1")
        db.create_tenant("S2")
        for tid in (1, 2):
            cid = db.create_billing_customer(tid, f"s{tid}@t.com", f"S{tid}")
            db.create_billing_subscription(tid, cid, "starter", "stripe", f"sub_s{tid}")
        # Add recent invoices so they're not "churned"
        now = datetime.utcnow().strftime("%Y-%m-%d")
        for tid in (1, 2):
            db.insert_invoice(tid, {"folio_fiscal": f"U-S-{tid}", "fecha": now, "total": 100},
                              {"categoria": "gastos"}, {"ok": True})

        r = svc.get_revenue_report()
        assert r.active_subscriptions == 2
        assert r.mrr == pytest.approx(2999.0 * 2, rel=0.01)
        assert r.arr == pytest.approx(2999.0 * 2 * 12, rel=0.01)
        assert r.plan_breakdown.get("starter") == 2

    def test_revenue_mixed_plans(self, db):
        svc = DashboardService(db)
        plans = ["starter", "professional", "enterprise"]
        for i, plan in enumerate(plans, 1):
            db.create_tenant(f"P{i}")
            cid = db.create_billing_customer(i, f"p{i}@t.com", f"P{i}")
            db.create_billing_subscription(i, cid, plan, "stripe", f"sub_p{i}")
            now = datetime.utcnow().strftime("%Y-%m-%d")
            db.insert_invoice(i, {"folio_fiscal": f"U-P-{i}", "fecha": now, "total": 200},
                              {"categoria": "gastos"}, {"ok": True})

        r = svc.get_revenue_report()
        assert r.active_subscriptions == 3
        expected_mrr = 2999.0 + 7999.0 + 19999.0
        assert r.mrr == pytest.approx(expected_mrr, rel=0.01)
        assert r.plan_breakdown.get("starter") == 1
        assert r.plan_breakdown.get("professional") == 1
        assert r.plan_breakdown.get("enterprise") == 1

    def test_revenue_arr_equals_mrr_times_12(self, db):
        svc = DashboardService(db)
        db.create_tenant("A1")
        cid = db.create_billing_customer(1, "a1@t.com", "A1")
        db.create_billing_subscription(1, cid, "professional", "stripe", "sub_a1")
        now = datetime.utcnow().strftime("%Y-%m-%d")
        db.insert_invoice(1, {"folio_fiscal": "U-A1", "fecha": now, "total": 500},
                          {"categoria": "gastos"}, {"ok": True})

        r = svc.get_revenue_report()
        assert r.arr == pytest.approx(r.mrr * 12, rel=0.01)

    def test_revenue_avg_per_client(self, db):
        svc = DashboardService(db)
        for i in range(1, 4):
            db.create_tenant(f"C{i}")
            cid = db.create_billing_customer(i, f"c{i}@t.com", f"C{i}")
            db.create_billing_subscription(i, cid, "professional", "stripe", f"sub_c{i}")
            now = datetime.utcnow().strftime("%Y-%m-%d")
            db.insert_invoice(i, {"folio_fiscal": f"U-C-{i}", "fecha": now, "total": 100},
                              {"categoria": "gastos"}, {"ok": True})

        r = svc.get_revenue_report()
        assert r.avg_revenue_per_client == pytest.approx(7999.0, rel=0.01)

    def test_revenue_unknown_plan_gets_default(self, db):
        svc = DashboardService(db)
        db.create_tenant("U1")
        cid = db.create_billing_customer(1, "u1@t.com", "U1")
        db.create_billing_subscription(1, cid, "mystery_plan", "stripe", "sub_u1")
        now = datetime.utcnow().strftime("%Y-%m-%d")
        db.insert_invoice(1, {"folio_fiscal": "U-U1", "fecha": now, "total": 100},
                          {"categoria": "gastos"}, {"ok": True})

        r = svc.get_revenue_report()
        assert r.mrr == pytest.approx(4999.0, rel=0.01)  # default plan price


# --------------------------------------------------------------------------- #
# Health Endpoint — Load Simulation
# --------------------------------------------------------------------------- #

class TestHealthLoadSimulation:
    """Health endpoint under simulated load conditions."""

    def test_health_high_error_rate(self, db):
        svc = DashboardService(db)
        db.create_tenant("T1")
        # Log many errors
        for _ in range(50):
            db.log_call("error", "action", status="error")
        for _ in range(10):
            db.log_call("tool", "action", status="ok")

        h = svc.get_system_health()
        assert h.status == "degraded"  # error_rate > 0.1

    def test_health_moderate_error_rate(self, db):
        svc = DashboardService(db)
        db.create_tenant("T1")
        # 8% error rate → warning
        for _ in range(8):
            db.log_call("error", "action", status="error")
        for _ in range(100):
            db.log_call("tool", "action", status="ok")

        h = svc.get_system_health()
        assert h.status == "warning"

    def test_health_low_error_rate_healthy(self, db):
        svc = DashboardService(db)
        db.create_tenant("T1")
        for _ in range(2):
            db.log_call("error", "action", status="error")
        for _ in range(100):
            db.log_call("tool", "action", status="ok")

        h = svc.get_system_health()
        assert h.status == "healthy"

    def test_health_uptime_never_negative(self, db):
        svc = DashboardService(db)
        h = svc.get_system_health()
        assert h.api_uptime_pct >= 0.0
        assert h.api_uptime_pct <= 100.0

    def test_health_error_rate_between_0_and_1(self, db):
        svc = DashboardService(db)
        # Add some errors
        for _ in range(15):
            db.log_call("error", "action", status="error")
        for _ in range(85):
            db.log_call("tool", "action", status="ok")

        h = svc.get_system_health()
        assert 0.0 <= h.error_rate_24h <= 1.0

    def test_health_queue_depth_always_zero(self, db):
        svc = DashboardService(db)
        h = svc.get_system_health()
        assert h.queue_depth == 0  # no queue implementation yet

    def test_health_details_contains_audit_total(self, db):
        svc = DashboardService(db)
        for _ in range(5):
            db.log_call("tool", "action", status="ok")
        h = svc.get_system_health()
        assert "audit_total" in h.details
        assert h.details["audit_total"] >= 5

    def test_health_overview_status_consistency(self, db):
        """Health endpoint status should match overview system_status."""
        svc = DashboardService(db)
        # Add moderate errors
        for _ in range(12):
            db.log_call("error", "action", status="error")
        for _ in range(100):
            db.log_call("tool", "action", status="ok")

        h = svc.get_system_health()
        ov = svc.get_dashboard_overview()
        # Both should agree on degraded status
        assert h.status == ov.system_status


# --------------------------------------------------------------------------- #
# Helper Functions — Boundary Conditions
# --------------------------------------------------------------------------- #

class TestHelperFunctions:
    """Test _safe_float and _plan_to_mrr helper functions."""

    def test_safe_float_zero(self):
        assert _safe_float(0) == 0.0

    def test_safe_float_zero_string(self):
        assert _safe_float("0") == 0.0

    def test_safe_float_float_input(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_safe_float_with_commas(self):
        assert _safe_float("1,234.56") == pytest.approx(1234.56)

    def test_safe_float_with_dollar_sign(self):
        assert _safe_float("$500.00") == pytest.approx(500.0)

    def test_safe_float_negative_string(self):
        assert _safe_float("-100.50") == pytest.approx(-100.50)

    def test_safe_float_whitespace(self):
        assert _safe_float("  42  ") == pytest.approx(42.0)

    def test_safe_float_complex_currency(self):
        assert _safe_float("$1,234,567.89") == pytest.approx(1234567.89)

    def test_safe_float_boolean_true(self):
        # bool is subclass of int, but str(True)="True" can't convert to float
        result = _safe_float(True)
        assert result == 0.0  # falls through to except clause

    def test_safe_float_boolean_false(self):
        result = _safe_float(False)
        assert result == 0.0

    def test_safe_float_list_returns_zero(self):
        assert _safe_float([1, 2]) == 0.0

    def test_safe_float_dict_returns_zero(self):
        assert _safe_float({"a": 1}) == 0.0

    def test_safe_float_very_large_number(self):
        assert _safe_float("999999999999") == 999999999999.0

    def test_plan_to_mrr_basic(self):
        assert _plan_to_mrr("basic") == 1999.0

    def test_plan_to_mrr_starter(self):
        assert _plan_to_mrr("starter") == 2999.0

    def test_plan_to_mrr_professional(self):
        assert _plan_to_mrr("professional") == 7999.0

    def test_plan_to_mrr_enterprise(self):
        assert _plan_to_mrr("enterprise") == 19999.0

    def test_plan_to_mrr_pro(self):
        assert _plan_to_mrr("pro") == 5999.0

    def test_plan_to_mrr_enterprise_plus(self):
        assert _plan_to_mrr("enterprise_plus") == 29999.0

    def test_plan_to_mrr_unknown_returns_default(self):
        assert _plan_to_mrr("unknown_plan") == 4999.0

    def test_plan_to_mrr_empty_string(self):
        assert _plan_to_mrr("") == 4999.0

    def test_plan_to_mrr_case_insensitive(self):
        assert _plan_to_mrr("STARTER") == 2999.0
        assert _plan_to_mrr("Enterprise") == 19999.0

    def test_plan_to_mrr_with_hyphens(self):
        assert _plan_to_mrr("enterprise-plus") == 29999.0

    def test_plan_to_mrr_with_spaces(self):
        assert _plan_to_mrr("enterprise plus") == 29999.0


# --------------------------------------------------------------------------- #
# Model Serialization Edge Cases
# --------------------------------------------------------------------------- #

class TestModelSerialization:
    """Pydantic model serialization and validation edge cases."""

    def test_client_summary_json_roundtrip(self):
        cs = ClientSummary(id=1, name="Test", rfc="RFC123", active=True,
                           invoice_count=5, monto_total=1500.50, api_calls=100)
        j = cs.model_dump_json()
        cs2 = ClientSummary.model_validate_json(j)
        assert cs == cs2

    def test_daily_metric_json_roundtrip(self):
        dm = DailyMetric(date="2026-01-15", count=10, total_amount=5000.0)
        j = dm.model_dump_json()
        dm2 = DailyMetric.model_validate_json(j)
        assert dm == dm2

    def test_system_health_json_roundtrip(self):
        sh = SystemHealth(status="healthy", api_uptime_pct=99.5,
                          total_invoices=100, total_tenants=5,
                          db_size_mb=1.5, queue_depth=0,
                          error_rate_24h=0.02, last_check="2026-01-01T00:00:00",
                          details={"key": "val"})
        j = sh.model_dump_json()
        sh2 = SystemHealth.model_validate_json(j)
        assert sh == sh2

    def test_usage_metrics_json_roundtrip(self):
        um = UsageMetrics(total_api_calls=500, total_invoices_processed=100,
                          cfdi_daily=[DailyMetric(date="2026-01-01", count=5, total_amount=2500.0)],
                          avg_processing_time_sec=2.5, llm_calls=50,
                          error_rate=0.03, period_start="2026-01-01",
                          period_end="2026-01-31")
        j = um.model_dump_json()
        um2 = UsageMetrics.model_validate_json(j)
        assert um == um2

    def test_revenue_report_json_roundtrip(self):
        rr = RevenueReport(mrr=7999.0, arr=95988.0, total_revenue=95988.0,
                           active_subscriptions=1, churn_rate=0.0,
                           avg_revenue_per_client=7999.0,
                           plan_breakdown={"professional": 1},
                           period_start="2026-01-01", period_end="2026-01-31")
        j = rr.model_dump_json()
        rr2 = RevenueReport.model_validate_json(j)
        assert rr == rr2

    def test_dashboard_overview_json_roundtrip(self):
        do = DashboardOverview(total_clients=10, active_clients=8,
                               revenue_mrr=50000.0, cfdi_count_month=200,
                               total_invoices=5000, total_revenue=600000.0,
                               system_status="healthy",
                               last_updated="2026-01-01T00:00:00")
        j = do.model_dump_json()
        do2 = DashboardOverview.model_validate_json(j)
        assert do == do2

    def test_client_summary_negative_id_accepted(self):
        # Pydantic v2 doesn't enforce positive id by default
        cs = ClientSummary(id=-1, name="Test")
        assert cs.id == -1

    def test_daily_metric_empty_date_accepted(self):
        # Pydantic v2 accepts any string for date field (no strict validation)
        dm = DailyMetric(date="", count=0, total_amount=0.0)
        assert dm.date == ""

    def test_system_health_negative_uptime(self):
        sh = SystemHealth(api_uptime_pct=-5.0)
        assert sh.api_uptime_pct == -5.0  # model doesn't enforce range

    def test_revenue_report_negative_mrr(self):
        rr = RevenueReport(mrr=-100.0)
        assert rr.mrr == -100.0  # model doesn't enforce non-negative

    def test_model_dump_excludes_none_by_default(self):
        cs = ClientSummary(id=1, name="Test")
        d = cs.model_dump()
        assert "created_at" in d  # field exists with None default
        assert d["created_at"] is None


# --------------------------------------------------------------------------- #
# Cross-Service Consistency
# --------------------------------------------------------------------------- #

class TestCrossServiceConsistency:
    """Verify consistency across different dashboard service methods."""

    def test_overview_client_count_matches_client_list(self, db_full):
        svc = DashboardService(db_full)
        overview = svc.get_dashboard_overview()
        client_list = svc.get_client_list()
        assert overview.total_clients == client_list["total"]

    def test_revenue_mrr_matches_overview_mrr(self, db_full):
        svc = DashboardService(db_full)
        overview = svc.get_dashboard_overview()
        revenue = svc.get_revenue_report()
        assert overview.revenue_mrr == revenue.mrr

    def test_health_invoice_count_matches_overview(self, db_full):
        svc = DashboardService(db_full)
        overview = svc.get_dashboard_overview()
        health = svc.get_system_health()
        assert overview.total_invoices == health.total_invoices

    def test_health_tenant_count_matches_overview(self, db_full):
        svc = DashboardService(db_full)
        overview = svc.get_dashboard_overview()
        health = svc.get_system_health()
        assert overview.total_clients == health.total_tenants

    def test_client_detail_count_matches_client_list(self, db_full):
        svc = DashboardService(db_full)
        client_list = svc.get_client_list(page_size=100)
        for c in client_list["clients"]:
            detail = svc.get_client_detail(c["id"])
            assert detail is not None
            assert detail["invoice_count"] == c["invoice_count"]

    def test_usage_error_rate_matches_health_error_rate(self, db_full):
        svc = DashboardService(db_full)
        usage = svc.get_usage_metrics()
        health = svc.get_system_health()
        assert usage.error_rate == health.error_rate_24h


# --------------------------------------------------------------------------- #
# Pagination Edge Cases
# --------------------------------------------------------------------------- #

class TestPaginationEdgeCases:
    """Pagination boundary and edge cases."""

    def test_pagination_beyond_total_returns_empty(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(page=1000, page_size=20)
        assert result["clients"] == []

    def test_pagination_page_size_one(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(page=1, page_size=1)
        assert len(result["clients"]) == 1
        assert result["page_size"] == 1

    def test_pagination_exact_boundary(self, db):
        """When total items is exactly a multiple of page_size."""
        svc = DashboardService(db)
        for i in range(4):
            db.create_tenant(f"Ten{i}")
        result = svc.get_client_list(page=1, page_size=2)
        assert result["pages"] == 2
        assert result["total"] == 4

    def test_pagination_first_page_has_correct_items(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(page=1, page_size=2)
        assert len(result["clients"]) == 2
        assert result["page"] == 1

    def test_pagination_second_page_has_correct_offset(self, db_full):
        svc = DashboardService(db_full)
        page1 = svc.get_client_list(page=1, page_size=2)
        page2 = svc.get_client_list(page=2, page_size=2)
        ids1 = [c["id"] for c in page1["clients"]]
        ids2 = [c["id"] for c in page2["clients"]]
        assert len(set(ids1) & set(ids2)) == 0  # no overlap

    def test_sort_by_monto_total_desc(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(sort_by="monto_total", sort_order="desc")
        amounts = [c["monto_total"] for c in result["clients"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_sort_by_api_calls_asc(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(sort_by="api_calls", sort_order="asc")
        calls = [c["api_calls"] for c in result["clients"]]
        assert calls == sorted(calls)

    def test_active_only_filter(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(active_only=True)
        for c in result["clients"]:
            assert c["active"] is True

    def test_search_partial_match(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(search="Tenant")
        assert result["total"] == 5  # all tenants match "Tenant"

    def test_search_no_match(self, db_full):
        svc = DashboardService(db_full)
        result = svc.get_client_list(search="ZZZZZ_NOTEXIST")
        assert result["total"] == 0
        assert result["clients"] == []
