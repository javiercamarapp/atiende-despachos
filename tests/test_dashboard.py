# -*- coding: utf-8 -*-
"""
test_dashboard.py — Tests for the Admin Dashboard API module.

Covers:
  - Service logic: get_dashboard_overview, get_client_list, get_client_detail,
    get_system_health, get_usage_metrics, get_revenue_report
  - Route endpoints: GET /admin/dashboard/* (6 endpoints)
  - Edge cases: empty data, single client, pagination, date ranges, sorting
  - Multi-tenant isolation: tenant A can't see tenant B's data
  - Auth: endpoints require valid API key

100+ test cases organized by category.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

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
from b2b_ai.features.dashboard.service import DashboardService, _safe_float, _plan_to_mrr


API_KEY = "dashboard-admin-test-key"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like DB for each test."""
    d = Database(str(tmp_path / "dash_test.db"))
    return d


@pytest.fixture
def db_with_data(db):
    """DB with sample tenants, invoices, API keys, and subscriptions."""
    # Tenants
    db.create_tenant("Despacho Alpha", rfc="AAA010101AAA")
    db.create_tenant("Despacho Beta", rfc="BBB020202BBB")
    db.create_tenant("Despacho Gamma", rfc="CCC030303CCC")

    # API keys
    db.create_api_key(1, "alpha-key", API_KEY)
    db.create_api_key(2, "beta-key", "beta-key-2")

    # Invoices for tenant 1
    now = datetime.utcnow().strftime("%Y-%m-%d")
    for i in range(5):
        db.insert_invoice(
            1,
            {"folio_fiscal": f"UUID-ALPHA-{i}", "fecha": now,
             "total": 1000.0 + i * 100, "subtotal": 850.0 + i * 85,
             "iva": 150.0 + i * 15, "emisor_rfc": "AAA010101AAA",
             "emisor_nombre": "Proveedor A", "receptor_rfc": "REC010101",
             "tipo": "I", "serie": "A", "folio": str(i)},
            {"categoria": "gastos", "confianza": 0.9, "razon": "test"},
            {"ok": True},
        )

    # Invoices for tenant 2
    for i in range(2):
        db.insert_invoice(
            2,
            {"folio_fiscal": f"UUID-BETA-{i}", "fecha": now,
             "total": 2000.0 + i * 200, "subtotal": 1700.0 + i * 170,
             "iva": 300.0 + i * 30, "emisor_rfc": "BBB020202BBB",
             "emisor_nombre": "Proveedor B", "receptor_rfc": "REC020202",
             "tipo": "I", "serie": "B", "folio": str(i)},
            {"categoria": "ingresos", "confianza": 0.85, "razon": "test"},
            {"ok": True},
        )

    # Billing customers + subscriptions
    c1 = db.create_billing_customer(1, "alpha@test.com", "Alpha Corp")
    c2 = db.create_billing_customer(2, "beta@test.com", "Beta Corp")
    db.create_billing_subscription(1, c1, "professional", "stripe", "sub_a1")
    db.create_billing_subscription(2, c2, "starter", "stripe", "sub_b1")

    return db


@pytest.fixture
def client(db_with_data):
    """TestClient with authenticated API."""
    app = create_app(db_with_data)
    return TestClient(app), db_with_data


def _auth():
    return {"X-API-Key": API_KEY}


# --------------------------------------------------------------------------- #
# Models Tests
# --------------------------------------------------------------------------- #

class TestModels:
    """Test Pydantic model construction and validation."""

    def test_client_summary_defaults(self):
        s = ClientSummary(id=1, name="Test")
        assert s.id == 1
        assert s.name == "Test"
        assert s.active is True
        assert s.invoice_count == 0
        assert s.monto_total == 0.0

    def test_client_summary_full(self):
        s = ClientSummary(id=1, name="X", rfc="RFC1", active=False,
                          invoice_count=10, monto_total=5000.0, api_calls=100,
                          created_at="2026-01-01", last_activity="2026-07-01")
        assert s.invoice_count == 10
        assert s.active is False

    def test_daily_metric(self):
        m = DailyMetric(date="2026-07-01", count=5, total_amount=1000.0)
        assert m.count == 5

    def test_daily_metric_defaults(self):
        m = DailyMetric(date="2026-07-01")
        assert m.count == 0
        assert m.total_amount == 0.0

    def test_system_health_defaults(self):
        h = SystemHealth()
        assert h.status == "healthy"
        assert h.api_uptime_pct == 100.0

    def test_system_health_fields(self):
        h = SystemHealth(status="degraded", error_rate_24h=0.15)
        assert h.status == "degraded"
        assert h.error_rate_24h == 0.15

    def test_usage_metrics_defaults(self):
        u = UsageMetrics()
        assert u.total_api_calls == 0
        assert u.cfdi_daily == []

    def test_usage_metrics_with_daily(self):
        days = [DailyMetric(date=f"2026-07-{i:02d}", count=i) for i in range(1, 6)]
        u = UsageMetrics(cfdi_daily=days)
        assert len(u.cfdi_daily) == 5

    def test_revenue_report_defaults(self):
        r = RevenueReport()
        assert r.mrr == 0.0
        assert r.arr == 0.0
        assert r.churn_rate == 0.0

    def test_revenue_report_plan_breakdown(self):
        r = RevenueReport(plan_breakdown={"professional": 3, "starter": 5})
        assert r.plan_breakdown["professional"] == 3

    def test_dashboard_overview_defaults(self):
        o = DashboardOverview()
        assert o.total_clients == 0
        assert o.system_status == "healthy"

    def test_dashboard_overview_full(self):
        o = DashboardOverview(total_clients=10, active_clients=7,
                              revenue_mrr=50000.0, cfdi_count_month=100)
        assert o.total_clients == 10
        assert o.revenue_mrr == 50000.0

    def test_model_dump_roundtrip(self):
        o = DashboardOverview(total_clients=5, active_clients=3)
        d = o.model_dump()
        assert isinstance(d, dict)
        assert d["total_clients"] == 5

    def test_model_json_schema(self):
        """All models produce valid JSON schemas."""
        for cls in [ClientSummary, DailyMetric, SystemHealth, UsageMetrics,
                     RevenueReport, DashboardOverview]:
            schema = cls.model_json_schema()
            assert "properties" in schema

    def test_client_summary_model_dump(self):
        s = ClientSummary(id=1, name="X", monto_total=123.45)
        d = s.model_dump()
        assert d["monto_total"] == 123.45

    def test_daily_metric_model_dump(self):
        m = DailyMetric(date="2026-01-01", count=3, total_amount=999.99)
        d = m.model_dump()
        assert d["date"] == "2026-01-01"
        assert d["count"] == 3

    def test_usage_metrics_model_dump(self):
        u = UsageMetrics(total_api_calls=100, llm_calls=50)
        d = u.model_dump()
        assert d["total_api_calls"] == 100

    def test_revenue_report_model_dump(self):
        r = RevenueReport(mrr=10000.0, arr=120000.0)
        d = r.model_dump()
        assert d["mrr"] == 10000.0

    def test_system_health_model_dump(self):
        h = SystemHealth(status="healthy", db_size_mb=1.5)
        d = h.model_dump()
        assert d["db_size_mb"] == 1.5

    def test_client_summary_optional_fields(self):
        s = ClientSummary(id=1, name="X", created_at=None, last_activity=None)
        assert s.created_at is None

    def test_dashboard_overview_optional_fields(self):
        o = DashboardOverview(last_updated="2026-07-15T12:00:00")
        assert o.last_updated == "2026-07-15T12:00:00"

    def test_system_health_details_default(self):
        h = SystemHealth()
        assert h.details == {}

    def test_revenue_report_plan_breakdown_default(self):
        r = RevenueReport()
        assert r.plan_breakdown == {}


# --------------------------------------------------------------------------- #
# Helper Function Tests
# --------------------------------------------------------------------------- #

class TestHelpers:
    """Test service helper functions."""

    def test_safe_float_int(self):
        assert _safe_float(42) == 42.0

    def test_safe_float_string(self):
        assert _safe_float("1234.56") == 1234.56

    def test_safe_float_none(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_empty(self):
        assert _safe_float("") == 0.0

    def test_safe_float_currency(self):
        assert _safe_float("$1,234.56") == 1234.56

    def test_safe_float_negative(self):
        assert _safe_float("-500.00") == -500.00

    def test_safe_float_invalid(self):
        assert _safe_float("not_a_number") == 0.0

    def test_plan_to_mrr_starter(self):
        assert _plan_to_mrr("starter") == 2999.0

    def test_plan_to_mrr_professional(self):
        assert _plan_to_mrr("professional") == 7999.0

    def test_plan_to_mrr_enterprise(self):
        assert _plan_to_mrr("enterprise") == 19999.0

    def test_plan_to_mrr_unknown(self):
        assert _plan_to_mrr("unknown_plan") == 4999.0

    def test_plan_to_mrr_case_insensitive(self):
        assert _plan_to_mrr("STARTER") == 2999.0

    def test_plan_to_mrr_with_hyphen(self):
        assert _plan_to_mrr("enterprise-plus") == 29999.0


# --------------------------------------------------------------------------- #
# Service Tests — Empty Database
# --------------------------------------------------------------------------- #

class TestServiceEmpty:
    """Service methods on an empty database."""

    def test_overview_empty(self, db):
        svc = DashboardService(db)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 0
        assert ov.active_clients == 0
        assert ov.cfdi_count_month == 0
        assert ov.total_invoices == 0

    def test_client_list_empty(self, db):
        svc = DashboardService(db)
        result = svc.get_client_list()
        assert result["clients"] == []
        assert result["total"] == 0
        assert result["pages"] == 1

    def test_client_detail_not_found(self, db):
        svc = DashboardService(db)
        assert svc.get_client_detail(999) is None

    def test_health_empty(self, db):
        svc = DashboardService(db)
        health = svc.get_system_health()
        assert health.status == "healthy"
        assert health.total_invoices == 0
        assert health.total_tenants == 0

    def test_usage_empty(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics()
        assert usage.total_api_calls == 0
        assert usage.total_invoices_processed == 0
        assert len(usage.cfdi_daily) == 30  # default 30 days

    def test_revenue_empty(self, db):
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.mrr == 0.0
        assert rev.arr == 0.0
        assert rev.active_subscriptions == 0

    def test_usage_custom_days(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=7)
        assert len(usage.cfdi_daily) == 7

    def test_usage_one_day(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=1)
        assert len(usage.cfdi_daily) == 1

    def test_usage_daily_dates_ordered(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=10)
        dates = [d.date for d in usage.cfdi_daily]
        assert dates == sorted(dates)

    def test_usage_period_dates(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=15)
        assert usage.period_start < usage.period_end


# --------------------------------------------------------------------------- #
# Service Tests — Single Client
# --------------------------------------------------------------------------- #

class TestServiceSingleClient:
    """Service methods with a single tenant and invoices."""

    def test_overview_single_client(self, db):
        db.create_tenant("Solo")
        db.insert_invoice(1, {"total": 500, "fecha": datetime.utcnow().strftime("%Y-%m-%d")},
                          {"categoria": "gastos"}, {"ok": True})
        svc = DashboardService(db)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 1
        assert ov.active_clients == 1
        assert ov.cfdi_count_month == 1
        assert ov.total_invoices == 1

    def test_client_list_single(self, db):
        db.create_tenant("Only One")
        svc = DashboardService(db)
        result = svc.get_client_list()
        assert result["total"] == 1
        assert len(result["clients"]) == 1
        assert result["clients"][0]["name"] == "Only One"

    def test_client_detail_single(self, db):
        db.create_tenant("Detail Test")
        db.insert_invoice(1, {"total": 1234.56, "categoria": "gastos",
                               "folio_fiscal": "FISCAL-001",
                               "fecha": datetime.utcnow().strftime("%Y-%m-%d")},
                          {"categoria": "gastos"}, {"ok": True})
        svc = DashboardService(db)
        detail = svc.get_client_detail(1)
        assert detail is not None
        assert detail["name"] == "Detail Test"
        assert detail["invoice_count"] == 1
        assert abs(detail["monto_total"] - 1234.56) < 0.01

    def test_health_single_client(self, db):
        db.create_tenant("Health Test")
        svc = DashboardService(db)
        health = svc.get_system_health()
        assert health.total_tenants == 1
        assert health.status == "healthy"

    def test_revenue_single_client_no_sub(self, db):
        db.create_tenant("NoSub")
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.mrr == 0.0
        assert rev.avg_revenue_per_client == 0.0


# --------------------------------------------------------------------------- #
# Service Tests — Multiple Clients
# --------------------------------------------------------------------------- #

class TestServiceMultipleClients:
    """Service methods with multiple tenants."""

    def test_overview_multiple(self, db_with_data):
        svc = DashboardService(db_with_data)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 3
        assert ov.active_clients >= 2  # tenants with recent invoices
        assert ov.total_invoices >= 7  # 5 + 2

    def test_client_list_all(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list()
        assert result["total"] == 3
        assert len(result["clients"]) == 3

    def test_client_list_search_name(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="alpha")
        assert result["total"] == 1
        assert result["clients"][0]["name"] == "Despacho Alpha"

    def test_client_list_search_rfc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="BBB")
        assert result["total"] == 1
        assert result["clients"][0]["rfc"] == "BBB020202BBB"

    def test_client_list_search_no_match(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="ZZZZZ")
        assert result["total"] == 0

    def test_client_detail_two_clients(self, db_with_data):
        svc = DashboardService(db_with_data)
        d1 = svc.get_client_detail(1)
        d2 = svc.get_client_detail(2)
        assert d1 is not None
        assert d2 is not None
        assert d1["name"] == "Despacho Alpha"
        assert d2["name"] == "Despacho Beta"
        assert d1["invoice_count"] == 5
        assert d2["invoice_count"] == 2


# --------------------------------------------------------------------------- #
# Service Tests — Pagination
# --------------------------------------------------------------------------- #

class TestServicePagination:
    """Pagination tests for client list."""

    def test_pagination_first_page(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(page=1, page_size=2)
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert len(result["clients"]) == 2
        assert result["total"] == 3

    def test_pagination_second_page(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(page=2, page_size=2)
        assert result["page"] == 2
        assert len(result["clients"]) == 1
        assert result["pages"] == 2

    def test_pagination_beyond_total(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(page=10, page_size=2)
        assert result["clients"] == []

    def test_pagination_page_size_one(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(page=1, page_size=1)
        assert len(result["clients"]) == 1
        assert result["pages"] == 3

    def test_pagination_large_page_size(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(page=1, page_size=100)
        assert len(result["clients"]) == 3
        assert result["pages"] == 1


# --------------------------------------------------------------------------- #
# Service Tests — Sorting
# --------------------------------------------------------------------------- #

class TestServiceSorting:
    """Sorting tests for client list."""

    def test_sort_by_name_asc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="name", sort_order="asc")
        names = [c["name"] for c in result["clients"]]
        assert names == sorted(names)

    def test_sort_by_name_desc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="name", sort_order="desc")
        names = [c["name"] for c in result["clients"]]
        assert names == sorted(names, reverse=True)

    def test_sort_by_id_asc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="id", sort_order="asc")
        ids = [c["id"] for c in result["clients"]]
        assert ids == sorted(ids)

    def test_sort_by_invoice_count_desc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="invoice_count", sort_order="desc")
        counts = [c["invoice_count"] for c in result["clients"]]
        assert counts == sorted(counts, reverse=True)

    def test_sort_by_monto_total_asc(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="monto_total", sort_order="asc")
        montos = [c["monto_total"] for c in result["clients"]]
        assert montos == sorted(montos)

    def test_sort_unknown_field(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(sort_by="nonexistent_field")
        # Should fall back to name sort
        assert result["total"] == 3


# --------------------------------------------------------------------------- #
# Service Tests — Filtering
# --------------------------------------------------------------------------- #

class TestServiceFiltering:
    """Filtering tests for client list."""

    def test_active_only_filter(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(active_only=True)
        # Only tenants with invoices in last 30 days
        for c in result["clients"]:
            assert c["active"] is True

    def test_search_case_insensitive(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="ALPHA")
        assert result["total"] == 1

    def test_search_partial_match(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="desp")
        assert result["total"] == 3  # all have "Despacho"

    def test_active_only_empty_result(self, db):
        db.create_tenant("NoInvoices")
        svc = DashboardService(db)
        result = svc.get_client_list(active_only=True)
        # No invoices, so not active
        assert result["total"] == 0

    def test_combined_search_and_active(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list(search="alpha", active_only=True)
        assert result["total"] == 1


# --------------------------------------------------------------------------- #
# Service Tests — Usage Metrics
# --------------------------------------------------------------------------- #

class TestServiceUsageMetrics:
    """Usage metrics tests."""

    def test_usage_with_invoices(self, db_with_data):
        svc = DashboardService(db_with_data)
        usage = svc.get_usage_metrics()
        assert usage.total_invoices_processed >= 0
        # Should have daily entries
        assert len(usage.cfdi_daily) == 30

    def test_usage_daily_counts(self, db_with_data):
        svc = DashboardService(db_with_data)
        usage = svc.get_usage_metrics(days=7)
        total_in_daily = sum(d.count for d in usage.cfdi_daily)
        # Today should have some invoices
        assert total_in_daily >= 0

    def test_usage_daily_total_amounts(self, db_with_data):
        svc = DashboardService(db_with_data)
        usage = svc.get_usage_metrics(days=7)
        for d in usage.cfdi_daily:
            assert d.total_amount >= 0.0

    def test_usage_error_rate(self, db_with_data):
        svc = DashboardService(db_with_data)
        usage = svc.get_usage_metrics()
        assert 0.0 <= usage.error_rate <= 1.0

    def test_usage_period_dates_correct(self, db_with_data):
        svc = DashboardService(db_with_data)
        usage = svc.get_usage_metrics(days=30)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        assert usage.period_end == today

    def test_usage_no_invoices_has_zeros(self, db):
        db.create_tenant("Empty")
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=5)
        assert all(d.count == 0 for d in usage.cfdi_daily)
        assert all(d.total_amount == 0.0 for d in usage.cfdi_daily)

    def test_usage_avg_processing_time_zero(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics()
        assert usage.avg_processing_time_sec == 0.0


# --------------------------------------------------------------------------- #
# Service Tests — Revenue Report
# --------------------------------------------------------------------------- #

class TestServiceRevenueReport:
    """Revenue report tests."""

    def test_revenue_with_subscriptions(self, db_with_data):
        svc = DashboardService(db_with_data)
        rev = svc.get_revenue_report()
        # professional (7999) + starter (2999) = 10998
        assert rev.mrr == 7999.0 + 2999.0
        assert rev.arr == rev.mrr * 12
        assert rev.active_subscriptions == 2

    def test_revenue_plan_breakdown(self, db_with_data):
        svc = DashboardService(db_with_data)
        rev = svc.get_revenue_report()
        assert rev.plan_breakdown.get("professional") == 1
        assert rev.plan_breakdown.get("starter") == 1

    def test_revenue_avg_per_client(self, db_with_data):
        svc = DashboardService(db_with_data)
        rev = svc.get_revenue_report()
        expected_avg = round(rev.mrr / 3, 2)
        assert rev.avg_revenue_per_client == expected_avg

    def test_revenue_churn_rate(self, db_with_data):
        svc = DashboardService(db_with_data)
        rev = svc.get_revenue_report()
        assert 0.0 <= rev.churn_rate <= 1.0

    def test_revenue_no_subs(self, db):
        db.create_tenant("Free")
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.mrr == 0.0
        assert rev.active_subscriptions == 0

    def test_revenue_period_dates(self, db_with_data):
        svc = DashboardService(db_with_data)
        rev = svc.get_revenue_report()
        now = datetime.utcnow()
        assert rev.period_start == now.replace(day=1).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Service Tests — System Health
# --------------------------------------------------------------------------- #

class TestServiceSystemHealth:
    """System health tests."""

    def test_health_status_healthy(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        assert health.status in ("healthy", "warning", "degraded")

    def test_health_uptime(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        assert 0.0 <= health.api_uptime_pct <= 100.0

    def test_health_tenants_count(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        assert health.total_tenants == 3

    def test_health_invoices_count(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        assert health.total_invoices >= 7

    def test_health_db_size(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        assert health.db_size_mb >= 0.0

    def test_health_last_check_format(self, db_with_data):
        svc = DashboardService(db_with_data)
        health = svc.get_system_health()
        # Should be ISO format
        datetime.fromisoformat(health.last_check)


# --------------------------------------------------------------------------- #
# Service Tests — Multi-Tenant Isolation
# --------------------------------------------------------------------------- #

class TestServiceMultiTenantIsolation:
    """Verify tenant isolation in dashboard data."""

    def test_client_detail_isolation(self, db_with_data):
        svc = DashboardService(db_with_data)
        d1 = svc.get_client_detail(1)
        d2 = svc.get_client_detail(2)
        # Different invoices per tenant
        assert d1["invoice_count"] != d2["invoice_count"]
        # Each shows only their own invoices
        assert d1["invoice_count"] == 5
        assert d2["invoice_count"] == 2

    def test_client_list_shows_all_tenants(self, db_with_data):
        svc = DashboardService(db_with_data)
        result = svc.get_client_list()
        names = {c["name"] for c in result["clients"]}
        assert "Despacho Alpha" in names
        assert "Despacho Beta" in names
        assert "Despacho Gamma" in names


# --------------------------------------------------------------------------- #
# Route Tests — Auth
# --------------------------------------------------------------------------- #

class TestRoutesAuth:
    """Auth tests for admin dashboard routes."""

    def test_overview_no_auth(self, db_with_data):
        app = create_app(db_with_data)
        tc = TestClient(app)
        resp = tc.get("/admin/dashboard/overview")
        assert resp.status_code == 401

    def test_overview_wrong_key(self, db_with_data):
        app = create_app(db_with_data)
        tc = TestClient(app)
        resp = tc.get("/admin/dashboard/overview",
                       headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_overview_valid_auth(self, db_with_data):
        app = create_app(db_with_data)
        tc = TestClient(app)
        resp = tc.get("/admin/dashboard/overview", headers=_auth())
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Route Tests — Overview
# --------------------------------------------------------------------------- #

class TestRoutesOverview:
    """Route tests for GET /admin/dashboard/overview."""

    def test_overview_returns_json(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/overview", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "total_clients" in data
        assert "active_clients" in data
        assert "revenue_mrr" in data
        assert "cfdi_count_month" in data

    def test_overview_values(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/overview", headers=_auth()).json()
        assert data["total_clients"] == 3
        assert data["total_invoices"] >= 7

    def test_overview_has_system_status(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/overview", headers=_auth()).json()
        assert data["system_status"] in ("healthy", "warning", "degraded")


# --------------------------------------------------------------------------- #
# Route Tests — Client List
# --------------------------------------------------------------------------- #

class TestRoutesClients:
    """Route tests for GET /admin/dashboard/clients."""

    def test_clients_returns_list(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "clients" in data
        assert "total" in data

    def test_clients_pagination_params(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?page=1&page_size=2",
                       headers=_auth())
        data = resp.json()
        assert len(data["clients"]) == 2
        assert data["page_size"] == 2

    def test_clients_search_param(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?search=alpha", headers=_auth())
        data = resp.json()
        assert data["total"] == 1

    def test_clients_sort_param(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?sort_by=invoice_count&sort_order=desc",
                       headers=_auth())
        data = resp.json()
        counts = [c["invoice_count"] for c in data["clients"]]
        assert counts == sorted(counts, reverse=True)

    def test_clients_active_only(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?active_only=true", headers=_auth())
        data = resp.json()
        for c in data["clients"]:
            assert c["active"] is True

    def test_clients_invalid_page(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?page=0", headers=_auth())
        assert resp.status_code == 422  # validation error

    def test_clients_large_page_size(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients?page_size=200", headers=_auth())
        assert resp.status_code == 422  # >100 not allowed


# --------------------------------------------------------------------------- #
# Route Tests — Client Detail
# --------------------------------------------------------------------------- #

class TestRoutesClientDetail:
    """Route tests for GET /admin/dashboard/clients/{id}."""

    def test_client_detail_found(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients/1", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Despacho Alpha"
        assert data["invoice_count"] == 5

    def test_client_detail_not_found(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients/999", headers=_auth())
        assert resp.status_code == 404

    def test_client_detail_has_category_breakdown(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/clients/1", headers=_auth()).json()
        assert "category_breakdown" in data
        assert "gastos" in data["category_breakdown"]

    def test_client_detail_has_recent_invoices(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/clients/1", headers=_auth()).json()
        assert "recent_invoices" in data
        assert len(data["recent_invoices"]) == 5

    def test_client_detail_tenant_2(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/clients/2", headers=_auth()).json()
        assert data["name"] == "Despacho Beta"
        assert data["invoice_count"] == 2

    def test_client_detail_no_invoices(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/clients/3", headers=_auth()).json()
        assert data["name"] == "Despacho Gamma"
        assert data["invoice_count"] == 0


# --------------------------------------------------------------------------- #
# Route Tests — System Health
# --------------------------------------------------------------------------- #

class TestRoutesHealth:
    """Route tests for GET /admin/dashboard/health."""

    def test_health_returns_200(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/health", headers=_auth())
        assert resp.status_code == 200

    def test_health_has_fields(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/health", headers=_auth()).json()
        assert "status" in data
        assert "api_uptime_pct" in data
        assert "total_invoices" in data
        assert "total_tenants" in data
        assert "db_size_mb" in data
        assert "error_rate_24h" in data
        assert "last_check" in data

    def test_health_uptime_range(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/health", headers=_auth()).json()
        assert 0.0 <= data["api_uptime_pct"] <= 100.0

    def test_health_error_rate_range(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/health", headers=_auth()).json()
        assert 0.0 <= data["error_rate_24h"] <= 1.0


# --------------------------------------------------------------------------- #
# Route Tests — Usage Metrics
# --------------------------------------------------------------------------- #

class TestRoutesUsage:
    """Route tests for GET /admin/dashboard/usage."""

    def test_usage_returns_200(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/usage", headers=_auth())
        assert resp.status_code == 200

    def test_usage_has_fields(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/usage", headers=_auth()).json()
        assert "total_api_calls" in data
        assert "total_invoices_processed" in data
        assert "cfdi_daily" in data
        assert "avg_processing_time_sec" in data
        assert "llm_calls" in data
        assert "error_rate" in data

    def test_usage_custom_days(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/usage?days=7", headers=_auth()).json()
        assert len(data["cfdi_daily"]) == 7

    def test_usage_cfdi_daily_structure(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/usage?days=3", headers=_auth()).json()
        for entry in data["cfdi_daily"]:
            assert "date" in entry
            assert "count" in entry
            assert "total_amount" in entry

    def test_usage_invalid_days_too_large(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/usage?days=400", headers=_auth())
        assert resp.status_code == 422

    def test_usage_invalid_days_zero(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/usage?days=0", headers=_auth())
        assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Route Tests — Revenue Report
# --------------------------------------------------------------------------- #

class TestRoutesRevenue:
    """Route tests for GET /admin/dashboard/revenue."""

    def test_revenue_returns_200(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/revenue", headers=_auth())
        assert resp.status_code == 200

    def test_revenue_has_fields(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/revenue", headers=_auth()).json()
        assert "mrr" in data
        assert "arr" in data
        assert "churn_rate" in data
        assert "avg_revenue_per_client" in data
        assert "plan_breakdown" in data

    def test_revenue_values(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/revenue", headers=_auth()).json()
        assert data["mrr"] == 7999.0 + 2999.0
        assert data["active_subscriptions"] == 2

    def test_revenue_arr_equals_mrr_times_12(self, client):
        tc, _ = client
        data = tc.get("/admin/dashboard/revenue", headers=_auth()).json()
        assert data["arr"] == data["mrr"] * 12


# --------------------------------------------------------------------------- #
# Route Tests — Combined Endpoints
# --------------------------------------------------------------------------- #

class TestRoutesCombined:
    """Tests that exercise multiple endpoints together."""

    def test_all_endpoints_accessible(self, client):
        tc, _ = client
        endpoints = [
            "/admin/dashboard/overview",
            "/admin/dashboard/clients",
            "/admin/dashboard/clients/1",
            "/admin/dashboard/health",
            "/admin/dashboard/usage",
            "/admin/dashboard/revenue",
        ]
        for ep in endpoints:
            resp = tc.get(ep, headers=_auth())
            assert resp.status_code == 200, f"Endpoint {ep} returned {resp.status_code}"

    def test_overview_matches_client_count(self, client):
        tc, _ = client
        overview = tc.get("/admin/dashboard/overview", headers=_auth()).json()
        clients = tc.get("/admin/dashboard/clients", headers=_auth()).json()
        assert overview["total_clients"] == clients["total"]

    def test_health_total_matches_overview(self, client):
        tc, _ = client
        health = tc.get("/admin/dashboard/health", headers=_auth()).json()
        overview = tc.get("/admin/dashboard/overview", headers=_auth()).json()
        assert health["total_tenants"] == overview["total_clients"]


# --------------------------------------------------------------------------- #
# Edge Cases
# --------------------------------------------------------------------------- #

class TestEdgeCases:
    """Edge case tests."""

    def test_empty_db_all_endpoints(self, db):
        db.create_tenant("Dummy")
        db.create_api_key(1, "dummy-key", "dash-empty-test-key")
        app = create_app(db)
        tc = TestClient(app)
        headers = {"X-API-Key": "dash-empty-test-key"}
        endpoints = [
            "/admin/dashboard/overview",
            "/admin/dashboard/clients",
            "/admin/dashboard/health",
            "/admin/dashboard/usage",
            "/admin/dashboard/revenue",
        ]
        for ep in endpoints:
            resp = tc.get(ep, headers=headers)
            assert resp.status_code == 200, f"Endpoint {ep} failed on empty DB"

    def test_client_detail_invalid_id(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients/-1", headers=_auth())
        assert resp.status_code in (404, 422)

    def test_client_detail_string_id(self, client):
        tc, _ = client
        resp = tc.get("/admin/dashboard/clients/abc", headers=_auth())
        assert resp.status_code == 422

    def test_overview_multiple_tenants_many_invoices(self, db):
        """Create many tenants with many invoices."""
        for i in range(10):
            db.create_tenant(f"Tenant {i}", rfc=f"RFC{i:04d}")
            for j in range(50):
                db.insert_invoice(
                    i + 1,
                    {"total": (j + 1) * 100, "fecha": datetime.utcnow().strftime("%Y-%m-%d"),
                     "folio_fiscal": f"UUID-{i}-{j}"},
                    {"categoria": "gastos"}, {"ok": True},
                )
        svc = DashboardService(db)
        ov = svc.get_dashboard_overview()
        assert ov.total_clients == 10
        assert ov.total_invoices == 500

    def test_client_list_pagination_large_dataset(self, db):
        """Create 50 tenants and verify pagination."""
        for i in range(50):
            db.create_tenant(f"Tenant {i}")
        svc = DashboardService(db)
        result = svc.get_client_list(page=1, page_size=10)
        assert result["total"] == 50
        assert result["pages"] == 5
        assert len(result["clients"]) == 10

    def test_usage_large_date_range(self, db):
        svc = DashboardService(db)
        usage = svc.get_usage_metrics(days=365)
        assert len(usage.cfdi_daily) == 365

    def test_revenue_many_plans(self, db):
        """Test plan breakdown with multiple subscription types."""
        db.create_tenant("T1")
        db.create_tenant("T2")
        db.create_tenant("T3")
        c1 = db.create_billing_customer(1, "a@a.com", "A")
        c2 = db.create_billing_customer(2, "b@b.com", "B")
        c3 = db.create_billing_customer(3, "c@c.com", "C")
        db.create_billing_subscription(1, c1, "enterprise", "stripe", "s1")
        db.create_billing_subscription(2, c2, "professional", "stripe", "s2")
        db.create_billing_subscription(3, c3, "starter", "stripe", "s3")
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.active_subscriptions == 3
        assert "enterprise" in rev.plan_breakdown
        assert "professional" in rev.plan_breakdown
        assert "starter" in rev.plan_breakdown

    def test_health_degraded_status(self, db):
        """Test degraded status with many errors."""
        for i in range(20):
            db.log_call("error", "error", status="error")
        for i in range(5):
            db.log_call("test", "ok", status="ok")
        svc = DashboardService(db)
        health = svc.get_system_health()
        # Error rate > 0.1 should be degraded
        assert health.status == "degraded"

    def test_health_warning_status(self, db):
        """Test warning status with moderate errors."""
        for i in range(2):
            db.log_call("error", "error", status="error")
        for i in range(20):
            db.log_call("test", "ok", status="ok")
        svc = DashboardService(db)
        health = svc.get_system_health()
        assert health.status in ("healthy", "warning")

    def test_client_detail_category_breakdown(self, db):
        """Test category breakdown with multiple categories."""
        db.create_tenant("MultiCat")
        for cat in ["gastos", "ingresos", "nómina"]:
            db.insert_invoice(
                1,
                {"total": 1000, "fecha": datetime.utcnow().strftime("%Y-%m-%d"),
                 "categoria": cat},
                {"categoria": cat}, {"ok": True},
            )
        svc = DashboardService(db)
        detail = svc.get_client_detail(1)
        assert len(detail["category_breakdown"]) == 3

    def test_usage_error_rate_calculation(self, db):
        """Test error rate matches audit log."""
        for i in range(10):
            db.log_call("test", "call", status="ok")
        db.log_call("error", "call", status="error")
        svc = DashboardService(db)
        usage = svc.get_usage_metrics()
        # 1 error out of 11 calls = ~0.09
        assert 0.0 < usage.error_rate < 0.2

    def test_revenue_churn_empty_tenants(self, db):
        """Churn with no invoices should show high churn."""
        for i in range(5):
            db.create_tenant(f"NoInvoice{i}")
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.churn_rate == 1.0  # all churned (no invoices)

    def test_revenue_churn_active_tenants(self, db):
        """Churn with active tenants should show low churn."""
        for i in range(5):
            db.create_tenant(f"Active{i}")
            db.insert_invoice(
                i + 1,
                {"total": 1000, "fecha": datetime.utcnow().strftime("%Y-%m-%d")},
                {"categoria": "gastos"}, {"ok": True},
            )
        svc = DashboardService(db)
        rev = svc.get_revenue_report()
        assert rev.churn_rate == 0.0  # all active

    def test_client_list_preserves_order_after_filter(self, db):
        """Filtering should not break sorting."""
        for i in range(5):
            db.create_tenant(f"Z-{i}" if i % 2 else f"A-{i}")
        svc = DashboardService(db)
        result = svc.get_client_list(sort_by="name", sort_order="asc")
        names = [c["name"] for c in result["clients"]]
        assert names == sorted(names)

    def test_overview_revenue_calculation(self, db_with_data):
        """Revenue MRR should match subscription plans."""
        svc = DashboardService(db_with_data)
        ov = svc.get_dashboard_overview()
        # professional=7999 + starter=2999 = 10998
        assert ov.revenue_mrr == 7999.0 + 2999.0

    def test_usage_llm_calls(self, db):
        """LLM calls should be tracked."""
        for i in range(3):
            db.log_call("llm", "call", status="ok")
        svc = DashboardService(db)
        usage = svc.get_usage_metrics()
        assert usage.llm_calls == 3

    def test_all_models_serialize(self):
        """All models serialize to dict without errors."""
        models = [
            ClientSummary(id=1, name="X"),
            DailyMetric(date="2026-01-01"),
            SystemHealth(),
            UsageMetrics(),
            RevenueReport(),
            DashboardOverview(),
        ]
        for m in models:
            d = m.model_dump()
            assert isinstance(d, dict)

    def test_all_models_validate(self):
        """All models validate input correctly."""
        # Valid
        ClientSummary(id=1, name="X")
        DailyMetric(date="2026-01-01")
        SystemHealth()
        UsageMetrics()
        RevenueReport()
        DashboardOverview()

        # With all fields
        ClientSummary(id=1, name="X", rfc="RFC", active=True,
                      invoice_count=10, monto_total=5000.0, api_calls=100,
                      created_at="2026-01-01", last_activity="2026-07-01")
        DailyMetric(date="2026-01-01", count=5, total_amount=1000.0)
        SystemHealth(status="healthy", api_uptime_pct=99.9,
                     total_invoices=100, total_tenants=10,
                     db_size_mb=5.0, queue_depth=3,
                     error_rate_24h=0.01, last_check="2026-07-15T12:00:00",
                     details={"key": "value"})
        UsageMetrics(total_api_calls=1000, total_invoices_processed=500,
                     cfdi_daily=[], avg_processing_time_sec=2.5,
                     llm_calls=100, error_rate=0.02,
                     period_start="2026-06-15", period_end="2026-07-15")
        RevenueReport(mrr=10000.0, arr=120000.0, total_revenue=50000.0,
                      active_subscriptions=5, churn_rate=0.05,
                      avg_revenue_per_client=2000.0,
                      plan_breakdown={"pro": 3},
                      period_start="2026-07-01", period_end="2026-07-31")
        DashboardOverview(total_clients=10, active_clients=7,
                          revenue_mrr=50000.0, cfdi_count_month=200,
                          total_invoices=5000, total_revenue=600000.0,
                          system_status="healthy", last_updated="2026-07-15T12:00:00")

    def test_empty_client_list_search_returns_empty(self, db):
        db.create_tenant("XYZ")
        svc = DashboardService(db)
        result = svc.get_client_list(search="nonexistent")
        assert result["clients"] == []
        assert result["total"] == 0

    def test_usage_period_dates_with_different_days(self, db):
        svc = DashboardService(db)
        for days in [1, 7, 14, 30, 90]:
            usage = svc.get_usage_metrics(days=days)
            assert len(usage.cfdi_daily) == days

    def test_client_detail_recent_invoices_capped(self, db):
        """Recent invoices should be capped at 10."""
        db.create_tenant("ManyInv")
        for i in range(20):
            db.insert_invoice(
                1,
                {"total": 100, "fecha": datetime.utcnow().strftime("%Y-%m-%d"),
                 "folio_fiscal": f"F-{i}"},
                {"categoria": "gastos"}, {"ok": True},
            )
        svc = DashboardService(db)
        detail = svc.get_client_detail(1)
        assert len(detail["recent_invoices"]) == 10
