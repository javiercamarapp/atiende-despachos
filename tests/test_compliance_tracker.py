# -*- coding: utf-8 -*-
"""Tests del módulo de Tracking de Obligaciones SAT (compliance_tracker)."""
import pytest

from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.compliance_tracker.models import (
    AlertType,
    Obligation,
    ObligationStatus,
    ObligationType,
)
from b2b_ai.features.compliance_tracker.routes import build_compliance_router
from b2b_ai.features.compliance_tracker.service import (
    ComplianceService,
    _reset_state,
)
from b2b_ai.features.compliance_tracker.templates import (
    generate_annual_template,
    monthly_obligations,
    nomina_bimestral_obligations,
)
from b2b_ai.features.roles.models import _reset_state as roles_reset


@pytest.fixture(autouse=True)
def _clean():
    _reset_state()
    roles_reset()
    yield
    _reset_state()
    roles_reset()


TODAY = date.today()
T1 = "tenant-a"
T2 = "tenant-b"


def _make_auth(tenant_id: str):
    """Auth stub que devuelve el tenant_id del contexto (como require_api_key)."""
    def require_api_key(*args, **kwargs):
        return {"tenant_id": tenant_id, "user_id": "u1", "key": "k"}
    return require_api_key


def _client(tenant_id: str = T1) -> TestClient:
    app = FastAPI()
    router = build_compliance_router(db=None, require_api_key=_make_auth(tenant_id))
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestCreateObligation:
    def test_create_obligation_stores_and_returns(self):
        svc = ComplianceService()
        obl = svc.create_obligation(T1, ObligationType.DIOT, date(2025, 6, 17))
        assert isinstance(obl, Obligation)
        assert obl.tenant_id == T1
        assert obl.obligation_type == ObligationType.DIOT
        assert obl.due_date == date(2025, 6, 17)
        assert obl.status == ObligationStatus.PENDING
        got = svc.get_obligation(obl.id)
        assert got.id == obl.id

    def test_past_due_date_starts_overdue(self):
        svc = ComplianceService()
        past = TODAY - timedelta(days=10)
        obl = svc.create_obligation(T1, ObligationType.IVA_MENSUAL, past)
        assert obl.status == ObligationStatus.OVERDUE

    def test_requires_tenant(self):
        svc = ComplianceService()
        with pytest.raises(ValueError):
            svc.create_obligation("", ObligationType.DIOT, date(2025, 6, 17))


class TestCompleteObligation:
    def test_complete_marks_done(self):
        svc = ComplianceService()
        obl = svc.create_obligation(T1, ObligationType.ISR_MENSUAL, date(2025, 6, 17))
        done = svc.complete_obligation(obl.id, user_id="contador1")
        assert done.status == ObligationStatus.COMPLETED
        assert done.completed_by == "contador1"
        assert done.completed_at is not None

    def test_complete_twice_raises(self):
        svc = ComplianceService()
        obl = svc.create_obligation(T1, ObligationType.DIOT, date(2025, 6, 17))
        svc.complete_obligation(obl.id)
        with pytest.raises(ValueError):
            svc.complete_obligation(obl.id)

    def test_complete_unknown_raises(self):
        svc = ComplianceService()
        with pytest.raises(KeyError):
            svc.complete_obligation("no-existe")


class TestGetOverdue:
    def test_overdue_returns_past_due(self):
        svc = ComplianceService()
        past = TODAY - timedelta(days=5)
        svc.create_obligation(T1, ObligationType.DIOT, past)
        svc.create_obligation(T1, ObligationType.ISR_MENSUAL,
                              TODAY + timedelta(days=30))  # futura, no vencida
        overdue = svc.get_overdue(T1)
        assert len(overdue) == 1
        assert overdue[0].obligation_type == ObligationType.DIOT

    def test_completed_not_overdue(self):
        svc = ComplianceService()
        past = TODAY - timedelta(days=5)
        obl = svc.create_obligation(T1, ObligationType.DIOT, past)
        svc.complete_obligation(obl.id)
        assert svc.get_overdue(T1) == []

    def test_overdue_tenant_isolation(self):
        svc = ComplianceService()
        past = TODAY - timedelta(days=5)
        svc.create_obligation(T1, ObligationType.DIOT, past)
        assert svc.get_overdue(T2) == []


class TestGetUpcoming:
    def test_upcoming_within_window(self):
        svc = ComplianceService()
        soon = TODAY + timedelta(days=3)
        later = TODAY + timedelta(days=40)
        svc.create_obligation(T1, ObligationType.IVA_MENSUAL, soon)
        svc.create_obligation(T1, ObligationType.ANUAL, later)
        upcoming = svc.get_upcoming(T1, days=7)
        assert len(upcoming) == 1
        assert upcoming[0].obligation_type == ObligationType.IVA_MENSUAL

    def test_upcoming_excludes_overdue_and_completed(self):
        svc = ComplianceService()
        past = TODAY - timedelta(days=1)
        soon = TODAY + timedelta(days=2)
        svc.create_obligation(T1, ObligationType.DIOT, past)  # vencida
        completed = svc.create_obligation(T1, ObligationType.CONTAB_ELECTRONICA, soon)
        svc.complete_obligation(completed.id)
        assert svc.get_upcoming(T1, days=7) == []

    def test_custom_window(self):
        svc = ComplianceService()
        svc.create_obligation(T1, ObligationType.ISR_MENSUAL,
                              TODAY + timedelta(days=3))
        # Ventana de 1 día: la obligación a 3 días NO cuenta.
        assert svc.get_upcoming(T1, days=1) == []


class TestCalendarGeneration:
    def test_calendar_has_expected_counts(self):
        svc = ComplianceService()
        obligations = svc.generate_calendar(T1, 2026)
        # 4 mensuales * 12 + 6 bimestrales + 1 anual
        assert len(obligations) == 48 + 6 + 1
        types = {o.obligation_type for o in obligations}
        assert ObligationType.ANUAL in types
        assert ObligationType.NOMINA_BIMESTRAL in types

    def test_calendar_idempotent(self):
        svc = ComplianceService()
        svc.generate_calendar(T1, 2026)
        second = svc.generate_calendar(T1, 2026)
        assert len(second) == 55  # no duplica

    def test_calendar_monthly_rules(self):
        obligations = monthly_obligations(T1, 2026, 3)
        for o in obligations:
            if o.obligation_type == ObligationType.CONTAB_ELECTRONICA:
                assert o.due_date.day == 20
            else:
                assert o.due_date.day == 17

    def test_nomina_bimestral_even_months(self):
        obligations = nomina_bimestral_obligations(T1, 2026)
        months = sorted(o.due_date.month for o in obligations)
        assert months == [2, 4, 6, 8, 10, 12]
        for o in obligations:
            assert o.due_date.day == 17

    def test_annual_april_30(self):
        obligations = generate_annual_template(T1, 2026)
        annual = [o for o in obligations if o.obligation_type == ObligationType.ANUAL]
        assert len(annual) == 1
        assert annual[0].due_date == date(2026, 4, 30)


class TestTenantIsolation:
    def test_obligations_isolated_by_tenant(self):
        svc = ComplianceService()
        svc.create_obligation(T1, ObligationType.DIOT, date(2025, 6, 17))
        svc.create_obligation(T2, ObligationType.ISR_MENSUAL, date(2025, 6, 17))
        assert len(svc.get_obligations(T1)) == 1
        assert svc.get_obligations(T1)[0].obligation_type == ObligationType.DIOT
        assert len(svc.get_obligations(T2)) == 1
        assert svc.get_obligations(T2)[0].obligation_type == ObligationType.ISR_MENSUAL

    def test_generate_calendar_isolated(self):
        svc = ComplianceService()
        svc.generate_calendar(T1, 2026)
        assert len(svc.get_obligations(T1)) == 55
        assert len(svc.get_obligations(T2)) == 0

    def test_get_obligation_unknown_raises(self):
        svc = ComplianceService()
        with pytest.raises(KeyError):
            svc.get_obligation("no-existe")


# ---------------------------------------------------------------------------
# Router / API tests
# ---------------------------------------------------------------------------


class TestApi:
    def test_create_via_api(self):
        c = _client()
        r = c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT",
            "due_date": "2025-06-17",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["obligation"]["obligation_type"] == "DIOT"

    def test_list_via_api(self):
        c = _client()
        c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT", "due_date": "2025-06-17"})
        r = c.get("/api/v1/compliance/obligations?year=2025&month=6")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_complete_via_api(self):
        c = _client()
        created = c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT", "due_date": "2025-06-17"}).json()
        oid = created["obligation"]["id"]
        r = c.post(f"/api/v1/compliance/obligations/{oid}/complete")
        assert r.status_code == 200
        assert r.json()["obligation"]["status"] == "COMPLETED"

    def test_overdue_via_api(self):
        c = _client()
        past = (TODAY - timedelta(days=3)).isoformat()
        c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT", "due_date": past})
        r = c.get("/api/v1/compliance/overdue")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_upcoming_via_api(self):
        c = _client()
        soon = (TODAY + timedelta(days=3)).isoformat()
        c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "IVA_MENSUAL", "due_date": soon})
        r = c.get("/api/v1/compliance/upcoming?days=7")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_calendar_via_api(self):
        c = _client()
        r = c.get("/api/v1/compliance/calendar/2026")
        assert r.status_code == 200
        assert r.json()["count"] == 55

    def test_idor_returns_404(self):
        # tenant A intenta completar una obligación de tenant B
        ca = _client(T1)
        cb = _client(T2)
        created_b = cb.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT", "due_date": "2025-06-17"}).json()
        oid_b = created_b["obligation"]["id"]
        r = ca.post(f"/api/v1/compliance/obligations/{oid_b}/complete")
        assert r.status_code == 404

    def test_alerts_generate_and_list(self):
        c = _client()
        past = (TODAY - timedelta(days=30)).isoformat()  # > critical(15) → CRITICAL
        c.post("/api/v1/compliance/obligations", json={
            "obligation_type": "DIOT", "due_date": past})
        gen = c.post("/api/v1/compliance/alerts/generate")
        assert gen.status_code == 200
        alerts = gen.json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "CRITICAL"
        # list + ack
        listed = c.get("/api/v1/compliance/alerts").json()["alerts"]
        assert len(listed) == 1
        ack = c.post(f"/api/v1/compliance/alerts/{alerts[0]['id']}/ack")
        assert ack.status_code == 200
        assert ack.json()["alert"]["acknowledged"] is True
