# -*- coding: utf-8 -*-
"""
test_pipeline.py — Tests del Pipeline de Prospectos/Leads (CRM).

Cubre:
  1. CRUD completo de leads (crear, leer, actualizar).
  2. Movimiento entre etapas (por status y por stage_id).
  3. Actividades y timeline + próximas acciones.
  4. Propuestas (crear, enviar, aceptar, rechazar).
  5. Analytics (conversión, tiempo en etapa, win rate, valor).
  6. Aislamiento multi-tenant (los tenants no ven ni mutan datos ajenos).
  7. Endpoints HTTP vía TestClient con auth fake.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.prospect_pipeline.models import (
    ActivityCreate,
    LeadCreate,
    LeadSource,
    LeadStatus,
    PipelineStageCreate,
    ProposalCreate,
)
from b2b_ai.features.prospect_pipeline.service import (
    ActivityTracker,
    LeadScoring,
    PipelineAnalytics,
    PipelineManager,
    ProposalManager,
    _reset_state,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_state():
    """Limpia el store en memoria entre tests."""
    _reset_state()
    yield
    _reset_state()


def _lead_req(**overrides) -> LeadCreate:
    defaults = dict(
        company_name="Acme SA de CV",
        contact_name="Ana López",
        contact_email="ana@acme.mx",
        contact_phone="5551234567",
        source=LeadSource.WEBSITE,
        company_size="51-200",
        budget=120000.0,
        timeline="0-3 meses",
        notes="Lead de la landing",
    )
    defaults.update(overrides)
    return LeadCreate(**defaults)


# -----------------------------------------------------------------------
# LeadScoring
# -----------------------------------------------------------------------

class TestLeadScoring:
    def test_score_high_quality_lead(self):
        sc = LeadScoring()
        score = sc.calculate_score(company_size="201+", budget=200000, timeline="0-3 meses")
        assert score >= 90
        assert score <= 100

    def test_score_low_quality_lead(self):
        sc = LeadScoring()
        score = sc.calculate_score(company_size="", budget=None, timeline="")
        assert score == 0

    def test_score_clamped_to_100(self):
        sc = LeadScoring()
        score = sc.calculate_score(company_size="201+", budget=1_000_000, timeline="0-3 meses")
        assert score <= 100

    def test_score_clamped_to_0(self):
        sc = LeadScoring()
        score = sc.calculate_score(company_size="", budget=0, timeline="")
        assert score == 0


# -----------------------------------------------------------------------
# PipelineManager — CRUD de leads
# -----------------------------------------------------------------------

class TestPipelineCrud:
    def test_create_lead_sets_score(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        assert lead.id
        assert lead.tenant_id == "t1"
        assert lead.status == LeadStatus.NEW
        assert lead.score >= 85  # 30 (size 51-200) + 40 (120k) + 25 (0-3) = 95

    def test_create_lead_requires_tenant(self):
        m = PipelineManager()
        with pytest.raises(ValueError):
            m.create_lead("", _lead_req())

    def test_create_lead_requires_company_name(self):
        m = PipelineManager()
        with pytest.raises(ValueError):
            m.create_lead("t1", _lead_req(company_name="  "))

    def test_get_lead(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        fetched = m.get_lead("t1", lead.id)
        assert fetched.id == lead.id

    def test_get_lead_missing_raises(self):
        m = PipelineManager()
        with pytest.raises(KeyError):
            m.get_lead("t1", "nope")

    def test_update_lead_recalculates_score(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req(company_size="", budget=None, timeline=""))
        assert lead.score == 0
        updated = m.update_lead("t1", lead.id, company_size="201+", budget=50000, timeline="0-3 meses")
        assert updated.score >= 80
        assert updated.updated_at >= updated.created_at

    def test_update_lead_cannot_blank_company(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        with pytest.raises(ValueError):
            m.update_lead("t1", lead.id, company_name="   ")


# -----------------------------------------------------------------------
# Movimiento entre etapas
# -----------------------------------------------------------------------

class TestMoveStage:
    def test_move_by_status(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        moved = m.move_stage("t1", lead.id, LeadStatus.QUALIFIED)
        assert moved.status == LeadStatus.QUALIFIED

    def test_move_by_stage_id(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        stages = m.list_stages("t1")
        # "Ganado" es la etapa is_won.
        won = next(s for s in stages if s.is_won)
        moved = m.move_to_stage("t1", lead.id, won.id)
        assert moved.status == LeadStatus.WON

    def test_move_lead_not_found(self):
        m = PipelineManager()
        with pytest.raises(KeyError):
            m.move_stage("t1", "nope", LeadStatus.CONTACTED)

    def test_move_invalid_status(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        with pytest.raises(ValueError):
            m.move_stage("t1", lead.id, "BAD_STATUS")


# -----------------------------------------------------------------------
# Listado con filtros
# -----------------------------------------------------------------------

class TestListLeads:
    def test_filter_by_stage(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="A"))
        b = m.create_lead("t1", _lead_req(company_name="B"))
        m.move_stage("t1", b.id, LeadStatus.WON)
        leads = m.list_leads("t1", stage=LeadStatus.WON)
        assert [l.id for l in leads] == [b.id]

    def test_filter_by_score_range(self):
        m = PipelineManager()
        low = m.create_lead("t1", _lead_req(company_name="Low", company_size="1-10", budget=None, timeline=""))
        high = m.create_lead("t1", _lead_req(company_name="High"))
        leads = m.list_leads("t1", score_min=50)
        assert high.id in [l.id for l in leads]
        assert low.id not in [l.id for l in leads]

    def test_filter_by_source(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="Web", source=LeadSource.WEBSITE))
        b = m.create_lead("t1", _lead_req(company_name="Cold", source=LeadSource.COLD_CALL))
        leads = m.list_leads("t1", source=LeadSource.COLD_CALL)
        assert [l.id for l in leads] == [b.id]

    def test_date_range_filter(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="A"))
        # Rango que cubre la fecha actual.
        from datetime import date, timedelta
        today = date.today().isoformat()
        before = (date.today() - timedelta(days=10)).isoformat()
        after = (date.today() + timedelta(days=10)).isoformat()
        leads = m.list_leads("t1", date_from=before, date_to=after)
        assert a.id in [l.id for l in leads]

    def test_get_lead_details_includes_empty_lists(self):
        m = PipelineManager()
        lead = m.create_lead("t1", _lead_req())
        details = m.get_lead_details("t1", lead.id)
        assert details["lead"]["id"] == lead.id
        assert details["activities"] == []
        assert details["proposals"] == []


# -----------------------------------------------------------------------
# Actividades y timeline
# -----------------------------------------------------------------------

class TestActivities:
    def test_log_and_get_timeline(self):
        m = PipelineManager()
        tracker = ActivityTracker()
        lead = m.create_lead("t1", _lead_req())
        req = ActivityCreate(
            activity_type="CALL",
            description="Llamada inicial",
            outcome="Interesado",
            next_action="Enviar propuesta",
            next_action_date="2026-09-01",
            created_by="user1",
        )
        act = tracker.log_activity("t1", lead.id, req)
        assert act.lead_id == lead.id
        assert act.activity_type.value == "CALL"
        timeline = tracker.get_timeline("t1", lead.id)
        assert len(timeline) == 1
        assert timeline[0].id == act.id

    def test_log_activity_unknown_lead(self):
        tracker = ActivityTracker()
        with pytest.raises(KeyError):
            tracker.log_activity("t1", "nope", ActivityCreate())

    def test_get_timeline_unknown_lead(self):
        tracker = ActivityTracker()
        with pytest.raises(KeyError):
            tracker.get_timeline("t1", "nope")

    def test_next_actions_only_pending(self):
        m = PipelineManager()
        tracker = ActivityTracker()
        lead = m.create_lead("t1", _lead_req())
        # Actividad con próxima acción futura.
        tracker.log_activity(
            "t1", lead.id,
            ActivityCreate(description="Llamada", next_action="Seguimiento", next_action_date="2099-01-01"),
        )
        # Actividad sin próxima acción.
        tracker.log_activity("t1", lead.id, ActivityCreate(description="Nota", next_action=""))
        actions = tracker.get_next_actions("t1")
        assert len(actions) == 1
        assert actions[0].next_action == "Seguimiento"


# -----------------------------------------------------------------------
# Propuestas
# -----------------------------------------------------------------------

class TestProposals:
    def test_full_proposal_lifecycle(self):
        m = PipelineManager()
        tracker = ActivityTracker()
        pm = ProposalManager()
        lead = m.create_lead("t1", _lead_req())

        prop = pm.create_proposal("t1", lead.id, ProposalCreate(amount=50000, currency="MXN"))
        assert prop.status.value == "DRAFT"
        assert prop.lead_id == lead.id

        sent = pm.send_proposal("t1", prop.id)
        assert sent.status.value == "SENT"

        accepted = pm.accept_proposal("t1", prop.id)
        assert accepted.status.value == "ACCEPTED"
        # Al aceptar, el lead pasa a NEGOTIATION.
        updated_lead = m.get_lead("t1", lead.id)
        assert updated_lead.status == LeadStatus.NEGOTIATION

    def test_send_requires_draft(self):
        m = PipelineManager()
        pm = ProposalManager()
        lead = m.create_lead("t1", _lead_req())
        prop = pm.create_proposal("t1", lead.id, ProposalCreate(amount=1000))
        pm.send_proposal("t1", prop.id)
        with pytest.raises(ValueError):
            pm.send_proposal("t1", prop.id)  # ya está SENT

    def test_accept_requires_sent(self):
        m = PipelineManager()
        pm = ProposalManager()
        lead = m.create_lead("t1", _lead_req())
        prop = pm.create_proposal("t1", lead.id, ProposalCreate(amount=1000))
        with pytest.raises(ValueError):
            pm.accept_proposal("t1", prop.id)  # DRAFT no puede aceptarse

    def test_reject_proposal(self):
        m = PipelineManager()
        pm = ProposalManager()
        lead = m.create_lead("t1", _lead_req())
        prop = pm.create_proposal("t1", lead.id, ProposalCreate(amount=1000))
        pm.send_proposal("t1", prop.id)
        rejected = pm.reject_proposal("t1", prop.id)
        assert rejected.status.value == "REJECTED"

    def test_create_proposal_unknown_lead(self):
        pm = ProposalManager()
        with pytest.raises(KeyError):
            pm.create_proposal("t1", "nope", ProposalCreate(amount=100))


# -----------------------------------------------------------------------
# Analytics
# -----------------------------------------------------------------------

class TestAnalytics:
    def test_conversion_rates(self):
        m = PipelineManager()
        for name in ("A", "B", "C", "D"):
            m.create_lead("t1", _lead_req(company_name=name))
        rates = PipelineAnalytics().conversion_rates("t1")
        assert rates[LeadStatus.NEW.value] == 1.0
        assert len(rates) == 7

    def test_win_rate(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="A"))
        b = m.create_lead("t1", _lead_req(company_name="B"))
        m.move_stage("t1", a.id, LeadStatus.WON)
        m.move_stage("t1", b.id, LeadStatus.LOST)
        wr = PipelineAnalytics().win_rate("t1")
        assert wr["won"] == 1
        assert wr["lost"] == 1
        assert wr["win_rate"] == 0.5

    def test_win_rate_no_closed(self):
        m = PipelineManager()
        m.create_lead("t1", _lead_req())
        wr = PipelineAnalytics().win_rate("t1")
        assert wr["win_rate"] == 0.0

    def test_pipeline_value(self):
        m = PipelineManager()
        pm = ProposalManager()
        lead = m.create_lead("t1", _lead_req())
        pm.create_proposal("t1", lead.id, ProposalCreate(amount=30000))
        pm.create_proposal("t1", lead.id, ProposalCreate(amount=20000))
        pv = PipelineAnalytics().pipeline_value("t1")
        assert pv["active_proposals"] == 2
        assert pv["total_value"] == 50000.0

    def test_average_time_in_stage_empty(self):
        assert PipelineAnalytics().average_time_in_stage("t1") == {}


# -----------------------------------------------------------------------
# Aislamiento multi-tenant
# -----------------------------------------------------------------------

class TestMultiTenant:
    def test_leads_are_isolated(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="T1"))
        b = m.create_lead("t2", _lead_req(company_name="T2"))
        assert [l.id for l in m.list_leads("t1")] == [a.id]
        assert [l.id for l in m.list_leads("t2")] == [b.id]

    def test_cannot_read_other_tenant_lead(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req())
        with pytest.raises(KeyError):
            m.get_lead("t2", a.id)

    def test_cannot_update_other_tenant_lead(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req())
        with pytest.raises(KeyError):
            m.update_lead("t2", a.id, contact_name="Hacker")

    def test_cannot_move_other_tenant_lead(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req())
        with pytest.raises(KeyError):
            m.move_stage("t2", a.id, LeadStatus.WON)

    def test_cannot_log_activity_on_other_tenant_lead(self):
        m = PipelineManager()
        tracker = ActivityTracker()
        a = m.create_lead("t1", _lead_req())
        with pytest.raises(KeyError):
            tracker.log_activity("t2", a.id, ActivityCreate())

    def test_cannot_create_proposal_on_other_tenant_lead(self):
        m = PipelineManager()
        pm = ProposalManager()
        a = m.create_lead("t1", _lead_req())
        with pytest.raises(KeyError):
            pm.create_proposal("t2", a.id, ProposalCreate(amount=100))

    def test_stages_are_isolated(self):
        m = PipelineManager()
        m.create_lead("t1", _lead_req())
        stages_t2 = m.list_stages("t2")
        assert len(stages_t2) == 7
        # Custom stage on t2 shouldn't leak to t1.
        m.add_stage("t2", PipelineStageCreate(name="Custom T2", order=99))
        assert not any(s.name == "Custom T2" for s in m.list_stages("t1"))

    def test_analytics_are_tenant_scoped(self):
        m = PipelineManager()
        a = m.create_lead("t1", _lead_req(company_name="A"))
        m.move_stage("t1", a.id, LeadStatus.WON)
        m.create_lead("t2", _lead_req(company_name="B"))
        wr = PipelineAnalytics().win_rate("t1")
        assert wr["won"] == 1
        assert wr["closed"] == 1


# -----------------------------------------------------------------------
# Endpoints HTTP (TestClient con auth fake)
# -----------------------------------------------------------------------

def _build_client():
    """App de prueba con auth fake que devuelve tenant_id de un header."""
    from fastapi import Depends, FastAPI, Header
    from fastapi.testclient import TestClient

    from b2b_ai.features.prospect_pipeline.routes import build_prospect_pipeline_router

    def fake_require_api_key(x_tenant: str = Header(default="", alias="X-Tenant")):
        return {"tenant_id": x_tenant or ""}

    app = FastAPI()
    app.include_router(build_prospect_pipeline_router(fake_require_api_key))
    return TestClient(app)


class TestRoutes:
    def test_create_and_get_lead_http(self):
        c = _build_client()
        r = c.post(
            "/api/v1/pipeline-crm/leads",
            headers={"X-Tenant": "t1"},
            json={
                "company_name": "Acme",
                "contact_email": "a@acme.mx",
                "company_size": "201+",
                "budget": 100000,
                "timeline": "0-3 meses",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["lead"]
        assert data["score"] > 80

        rid = c.get(f"/api/v1/pipeline-crm/leads/{data['id']}", headers={"X-Tenant": "t1"})
        assert rid.status_code == 200
        assert rid.json()["lead"]["id"] == data["id"]

    def test_tenant_isolation_http(self):
        c = _build_client()
        r1 = c.post(
            "/api/v1/pipeline-crm/leads",
            headers={"X-Tenant": "t1"},
            json={"company_name": "Tenant1"},
        )
        lead_id = r1.json()["lead"]["id"]
        # Tenant t2 no puede leer el lead de t1.
        r2 = c.get(f"/api/v1/pipeline-crm/leads/{lead_id}", headers={"X-Tenant": "t2"})
        assert r2.status_code == 404
        # Y listando t2 no ve el lead de t1.
        listing = c.get("/api/v1/pipeline-crm/leads", headers={"X-Tenant": "t2"})
        assert listing.json()["count"] == 0

    def test_full_flow_http(self):
        c = _build_client()
        h = {"X-Tenant": "t1"}

        lead = c.post("/api/v1/pipeline-crm/leads", headers=h,
                      json={"company_name": "Flujo"}).json()["lead"]

        c.post(f"/api/v1/pipeline-crm/leads/{lead['id']}/move", headers=h,
               json={"stage": "QUALIFIED"})

        c.post(f"/api/v1/pipeline-crm/leads/{lead['id']}/activities", headers=h,
               json={"activity_type": "EMAIL", "description": "Intro", "next_action": "Call back"})

        prop = c.post(f"/api/v1/pipeline-crm/leads/{lead['id']}/proposals", headers=h,
                      json={"amount": 40000}).json()["proposal"]

        sent = c.post(f"/api/v1/pipeline-crm/proposals/{prop['id']}/send", headers=h)
        assert sent.status_code == 200
        assert sent.json()["proposal"]["status"] == "SENT"

        accepted = c.post(f"/api/v1/pipeline-crm/proposals/{prop['id']}/accept", headers=h)
        assert accepted.json()["proposal"]["status"] == "ACCEPTED"

        detail = c.get(f"/api/v1/pipeline-crm/leads/{lead['id']}", headers=h).json()
        assert detail["lead"]["status"] == "NEGOTIATION"
        assert len(detail["activities"]) == 1
        assert len(detail["proposals"]) == 1

    def test_missing_tenant_400(self):
        c = _build_client()
        r = c.post("/api/v1/pipeline-crm/leads", json={"company_name": "NoTenant"})
        assert r.status_code == 400

    def test_analytics_endpoints_http(self):
        c = _build_client()
        h = {"X-Tenant": "t1"}
        c.post("/api/v1/pipeline-crm/leads", headers=h, json={"company_name": "A"})
        for ep in ("conversion-rates", "average-time-in-stage", "win-rate", "pipeline-value"):
            r = c.get(f"/api/v1/pipeline-crm/analytics/{ep}", headers=h)
            assert r.status_code == 200, ep
