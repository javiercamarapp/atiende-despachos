# -*- coding: utf-8 -*-
"""Tests del módulo de Tracking de Piloto (pilot_tracker)."""
import pytest

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.pilot_tracker.models import (
    PilotHealth,
    PilotMetric,
    PilotMetricType,
    PilotReport,
)
from b2b_ai.features.pilot_tracker.routes import build_pilot_tracker_router
from b2b_ai.features.pilot_tracker.service import (
    CFDI_SAVINGS_MINUTES,
    BANK_RECON_SAVINGS_MINUTES,
    NOMINA_SAVINGS_HOURS,
    DEFAULT_ACCOUNTANT_HOURLY_COST_MXN,
    PilotTrackerService,
    _reset_state,
)
from b2b_ai.features.roles.models import _reset_state as roles_reset


@pytest.fixture(autouse=True)
def _clean():
    _reset_state()
    roles_reset()
    yield
    _reset_state()
    roles_reset()


P1 = date(2025, 6, 1)
P2 = date(2025, 6, 30)


class TestRecordAndGetMetrics:
    def test_record_metric_stores_and_returns(self):
        svc = PilotTrackerService()
        m = svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 120, P1, P2)
        assert isinstance(m, PilotMetric)
        assert m.tenant_id == "t1"
        assert m.metric_type == PilotMetricType.CFDI_PROCESSED
        assert m.value == 120
        got = svc.get_metric(m.id)
        assert got.id == m.id

    def test_get_tenant_metrics_filters_by_period(self):
        svc = PilotTrackerService()
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 10, P1, P2)
        svc.record_metric("t1", PilotMetricType.BANK_RECONCILED, 5,
                         date(2025, 7, 1), date(2025, 7, 31))
        # Solo junio.
        only_june = svc.get_tenant_metrics("t1", date(2025, 6, 1), date(2025, 6, 30))
        assert len(only_june) == 1
        assert only_june[0].metric_type == PilotMetricType.CFDI_PROCESSED
        # Todo.
        assert len(svc.get_tenant_metrics("t1")) == 2
        # Sin datos para otro tenant.
        assert svc.get_tenant_metrics("other") == []

    def test_metric_period_end_must_be_ge_start(self):
        svc = PilotTrackerService()
        with pytest.raises(ValueError):
            svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 1,
                              date(2025, 6, 30), date(2025, 6, 1))


class TestHealthScore:
    def test_no_metrics_gives_zero_health(self):
        svc = PilotTrackerService()
        h = svc.calculate_health_score("t1")
        assert isinstance(h, PilotHealth)
        assert h.health_score == 0.0
        # Factores todos en 0 (sin datos).
        for k in ("usage_frequency", "data_quality",
                  "automation_adoption", "response_time"):
            assert h.factors[k] == 0.0

    def test_full_activity_gives_high_health(self):
        svc = PilotTrackerService()
        # Datos core + automatización alta + actividad reciente.
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 100, P1, P2)
        svc.record_metric("t1", PilotMetricType.BANK_RECONCILED, 50, P1, P2)
        svc.record_metric("t1", PilotMetricType.NOMINA_TIMBRED, 20, P1, P2)
        svc.record_metric("t1", PilotMetricType.AUTOMATION_RATE, 90, P1, P2)
        h = svc.calculate_health_score("t1")
        # usage ~30+ ; data_quality 100 ; automation 90 ; response 100
        assert h.health_score > 50.0

    def test_health_factors_are_weighted(self):
        svc = PilotTrackerService()
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 100, P1, P2)
        svc.record_metric("t1", PilotMetricType.AUTOMATION_RATE, 100, P1, P2)
        h = svc.calculate_health_score("t1")
        weights = h.factors["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert weights["usage_frequency"] == 0.30
        assert weights["automation_adoption"] == 0.25


class TestROI:
    def test_roi_summary_computes_hours_and_cost(self):
        svc = PilotTrackerService()
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 60, P1, P2)   # 60*14min=14h
        svc.record_metric("t1", PilotMetricType.BANK_RECONCILED, 12, P1, P2)  # 12*25min=5h
        svc.record_metric("t1", PilotMetricType.NOMINA_TIMBRED, 4, P1, P2)    # 4*1.75h=7h
        roi = svc.get_roi_summary("t1")
        expected_hours = (60 * CFDI_SAVINGS_MINUTES / 60
                          + 12 * BANK_RECON_SAVINGS_MINUTES / 60
                          + 4 * NOMINA_SAVINGS_HOURS)
        assert roi["total_hours_saved"] == round(expected_hours, 2)
        assert roi["total_cost_saved_mxn"] == round(
            expected_hours * DEFAULT_ACCOUNTANT_HOURLY_COST_MXN, 2)

    def test_roi_automation_rate_reflects_latest(self):
        svc = PilotTrackerService()
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 10, P1, P2)
        svc.record_metric("t1", PilotMetricType.AUTOMATION_RATE, 45, P1, P2)
        svc.record_metric("t1", PilotMetricType.AUTOMATION_RATE, 70, P1, P2)
        roi = svc.get_roi_summary("t1")
        assert roi["automation_rate_percent"] == 70.0


class TestGenerateReport:
    def test_report_shape_and_period_filtering(self):
        svc = PilotTrackerService()
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 30, P1, P2)
        svc.record_metric("t1", PilotMetricType.HOURS_SAVED, 8, P1, P2)
        # Fuera del período.
        svc.record_metric("t1", PilotMetricType.CFDI_PROCESSED, 999,
                         date(2025, 8, 1), date(2025, 8, 31))
        report = svc.generate_pilot_report("t1", "2025-06")
        assert isinstance(report, PilotReport)
        assert report.period == "2025-06"
        summary = report.metrics_summary
        # Solo cuenta junio (30 CFDI), no el 999 de agosto.
        assert summary["metric_totals"]["CFDI_PROCESSED"] == 30
        assert summary["metric_count"] == 2
        assert "roi" in summary

    def test_report_invalid_period_format(self):
        svc = PilotTrackerService()
        with pytest.raises(ValueError):
            svc.generate_pilot_report("t1", "not-a-period")


# ---------------------------------------------------------------------------
# Multi-tenant (IDOR) + RBAC fino
# ---------------------------------------------------------------------------

def _auth_for(tenant_id: str, user_id: str = ""):
    ctx = {"key": "test-key", "tenant_id": tenant_id}
    if user_id:
        ctx["user_id"] = user_id
    return lambda: ctx


def _router_client(tenant_id: str, user_id: str = ""):
    app = FastAPI()
    app.include_router(build_pilot_tracker_router(
        db=None, require_api_key=_auth_for(tenant_id, user_id)))
    return TestClient(app)


def _seed_metrics(tenant_id: str):
    svc = PilotTrackerService()
    svc.record_metric(tenant_id, PilotMetricType.CFDI_PROCESSED, 30, P1, P2)
    svc.record_metric(tenant_id, PilotMetricType.BANK_RECONCILED, 10, P1, P2)
    svc.record_metric(tenant_id, PilotMetricType.NOMINA_TIMBRED, 2, P1, P2)


class TestIDORTenantIsolation:
    """Un tenant no debe leer métricas/health/roi de otro (PILOT)."""

    def test_metrics_of_other_tenant_returns_404(self):
        _seed_metrics("tenant_A")
        c_b = _router_client("tenant_B")
        r = c_b.get("/api/v1/pilot/tenant_A/metrics")
        assert r.status_code == 404

    def test_health_of_other_tenant_returns_404(self):
        _seed_metrics("tenant_A")
        c_b = _router_client("tenant_B")
        r = c_b.get("/api/v1/pilot/tenant_A/health")
        assert r.status_code == 404

    def test_owner_can_read_own_metrics(self):
        _seed_metrics("tenant_A")
        c_a = _router_client("tenant_A")
        r = c_a.get("/api/v1/pilot/tenant_A/metrics")
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 3

    def test_record_uses_auth_tenant(self):
        c_a = _router_client("tenant_A")
        r = c_a.post("/api/v1/pilot/record", json={
            "metric_type": "CFDI_PROCESSED",
            "value": 5,
            "period_start": "2025-06-01",
            "period_end": "2025-06-30",
        })
        assert r.status_code == 200, r.text
        assert r.json()["metric"]["tenant_id"] == "tenant_A"


class TestRBACPilotPermissions:
    """Lectura exige PILOT_VIEW; mutación exige PILOT_MANAGE."""

    def test_record_requires_pilot_manage(self):
        from b2b_ai.features.roles.seed import seed_default_roles
        from b2b_ai.features.roles.service import RolesService

        svc = RolesService()
        seed_default_roles()
        readonly = next(r for r in svc.list_roles() if r.name == "readonly")
        svc.assign_role("user_ro", "tenant_A", readonly.id)

        c = _router_client("tenant_A", user_id="user_ro")
        r = c.post("/api/v1/pilot/record", json={
            "metric_type": "CFDI_PROCESSED",
            "value": 1,
            "period_start": "2025-06-01",
            "period_end": "2025-06-30",
        })
        assert r.status_code == 403

    def test_read_metrics_allowed_for_contador_with_view(self):
        from b2b_ai.features.roles.seed import seed_default_roles
        from b2b_ai.features.roles.service import RolesService

        svc = RolesService()
        seed_default_roles()
        contador = next(r for r in svc.list_roles() if r.name == "contador")
        svc.assign_role("user_cont", "tenant_A", contador.id)
        _seed_metrics("tenant_A")

        c = _router_client("tenant_A", user_id="user_cont")
        r = c.get("/api/v1/pilot/tenant_A/metrics")
        assert r.status_code == 200, r.text
