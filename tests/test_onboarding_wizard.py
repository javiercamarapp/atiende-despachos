# -*- coding: utf-8 -*-
"""
test_onboarding_wizard.py — Tests del wizard de onboarding (5 pasos).

Cubre:
    - Wizard state machine (persistence, advance, resume, complete)
    - Validación por paso (happy paths + error cases)
    - Checklist scoring
    - API endpoints (status, steps, step get/put, complete, plans, erp-options)
"""
import json
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.onboarding.wizard import (
    OnboardingWizard, OnboardingError,
    STEP_ORDER, STEP_NAMES, ERP_OPTIONS, PLAN_OPTIONS, PLAN_DETAILS,
)
from b2b_ai.onboarding.checklist import OnboardingChecklist
from b2b_ai.api.app import create_app

API_KEY = "onboarding-wizard-test-key"

# ────────────────────────────────────────────────────────────────────────── #
# Fixtures
# ────────────────────────────────────────────────────────────────────────── #

def _valid_company():
    return {
        "name": "Despacho Contable ABC",
        "rfc": "CACR850101AB1",
        "address": "Av. Reforma 123, Col. Centro, CDMX 06000",
        "contact_name": "Roberto Campos",
        "contact_email": "roberto@abc-contadores.mx",
        "contact_phone": "+52 55 1234 5678",
        "industry": "Servicios contables",
    }


def _valid_sat():
    return {
        "ciec": "ABC123",
        "efirma_certificado": "/path/to/cert.cer",
        "efirma_llave": "/path/to/key.key",
        "efirma_password": "password123",
    }


def _valid_erp_contpaqi():
    return {
        "erp": "ContPAQi",
        "credentials_host": "192.168.1.100",
        "credentials_user": "admin",
        "credentials_password": "secret",
    }


def _valid_erp_csv():
    return {
        "erp": "CSV",
        "csv_file": "/data/contabilidad.csv",
    }


def _valid_billing():
    return {"plan": "profesional"}


def _valid_cfdi():
    return {
        "cfdi_xml": """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Serie="A" Folio="001"
    Fecha="2026-01-15T10:30:00" SubTotal="1000.00"
    Total="1160.00" Moneda="MXN" TipoDeComprobante="I">
  <cfdi:Emisor Rfc="CACR850101AB1" Nombre="Despacho ABC"/>
  <cfdi:Receptor Rfc="XAXX010101000" Nombre="Cliente"/>
</cfdi:Comprobante>""",
    }


@pytest.fixture
def db(tmp_path):
    """Database en archivo temporal."""
    return Database(str(tmp_path / "wizard_test.db"))


@pytest.fixture
def tenant(db):
    """Tenant creado para tests."""
    tid = db.create_tenant("Despacho Test", rfc="XAXX010101000")
    return tid


@pytest.fixture
def wizard(db, tenant):
    """Wizard con tenant ya creado."""
    return OnboardingWizard(db, tenant_id=tenant)


@pytest.fixture
def client(tmp_path):
    """TestClient con app montada y API key."""
    db = Database(str(tmp_path / "wizard_api.db"))
    tenant_id = db.create_tenant("API Test", rfc="XAXX010101000")
    db.create_api_key(tenant_id, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db, tenant_id


def _auth():
    return {"X-API-Key": API_KEY}


# ────────────────────────────────────────────────────────────────────────── #
# Wizard: constants and metadata
# ────────────────────────────────────────────────────────────────────────── #

class TestWizardConstants:
    def test_step_order_is_1_to_5(self):
        assert STEP_ORDER == [1, 2, 3, 4, 5]

    def test_step_names_match_order(self):
        assert list(STEP_NAMES.keys()) == STEP_ORDER

    def test_all_steps_have_titles(self):
        for s in STEP_ORDER:
            assert s in STEP_NAMES
            assert len(STEP_NAMES[s]) > 0

    def test_erp_options(self):
        assert set(ERP_OPTIONS) == {"ContPAQi", "Aspel", "CSV"}

    def test_plan_options(self):
        assert set(PLAN_OPTIONS) == {"basico", "profesional", "enterprise"}

    def test_plan_details_have_prices(self):
        for key, detail in PLAN_DETAILS.items():
            assert detail["key"] == key
            assert detail["price_mxn"] > 0
            assert "name" in detail
            assert "description" in detail


# ────────────────────────────────────────────────────────────────────────── #
# Wizard: initial state
# ────────────────────────────────────────────────────────────────────────── #

class TestWizardInitialState:
    def test_status_starts_at_step_1(self, wizard):
        status = wizard.status()
        assert status["current_step"] == 1
        assert status["complete"] is False
        assert status["completed_steps"] == []

    def test_get_step_returns_empty_data(self, wizard):
        for s in STEP_ORDER:
            info = wizard.get_step(s)
            assert info["step"] == s
            assert info["complete"] is False
            assert info["data"] == {}

    def test_get_step_definitions(self, wizard):
        defs = wizard.get_step_definitions()
        assert len(defs) == 5
        assert [d["step"] for d in defs] == STEP_ORDER

    def test_get_plan_options(self, wizard):
        plans = wizard.get_plan_options()
        assert len(plans) == 3
        prices = {p["key"]: p["price_mxn"] for p in plans}
        assert prices["basico"] == 4900.0
        assert prices["profesional"] == 12000.0
        assert prices["enterprise"] == 48000.0

    def test_get_erp_options(self, wizard):
        erps = wizard.get_erp_options()
        assert erps == ERP_OPTIONS


# ────────────────────────────────────────────────────────────────────────── #
# Wizard: step validation
# ────────────────────────────────────────────────────────────────────────── #

class TestStep1CompanyProfile:
    def test_valid_company_advances(self, wizard):
        status = wizard.set_step(1, _valid_company())
        assert status["current_step"] == 2
        assert "company_profile" in status["completed_steps"]

    def test_rfc_normalized_to_upper(self, wizard):
        data = _valid_company()
        data["rfc"] = "cacr850101ab1"
        wizard.set_step(1, data)
        step = wizard.get_step(1)
        assert step["data"]["rfc"] == "CACR850101AB1"

    def test_missing_name_fails(self, wizard):
        data = _valid_company()
        del data["name"]
        with pytest.raises(OnboardingError, match="name"):
            wizard.set_step(1, data)

    def test_missing_rfc_fails(self, wizard):
        data = _valid_company()
        del data["rfc"]
        with pytest.raises(OnboardingError, match="rfc"):
            wizard.set_step(1, data)

    def test_invalid_rfc_format_fails(self, wizard):
        data = _valid_company()
        data["rfc"] = "INVALID"
        with pytest.raises(OnboardingError, match="RFC inválido"):
            wizard.set_step(1, data)

    def test_invalid_email_fails(self, wizard):
        data = _valid_company()
        data["contact_email"] = "not-an-email"
        with pytest.raises(OnboardingError, match="Email"):
            wizard.set_step(1, data)

    def test_missing_address_fails(self, wizard):
        data = _valid_company()
        del data["address"]
        with pytest.raises(OnboardingError, match="address"):
            wizard.set_step(1, data)

    def test_missing_contact_name_fails(self, wizard):
        data = _valid_company()
        del data["contact_name"]
        with pytest.raises(OnboardingError, match="contact_name"):
            wizard.set_step(1, data)


class TestStep2SATCredentials:
    def test_valid_sat_advances(self, wizard):
        wizard.set_step(1, _valid_company())
        status = wizard.set_step(2, _valid_sat())
        assert status["current_step"] == 3
        assert "sat_credentials" in status["completed_steps"]

    def test_ciec_too_short_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        data = _valid_sat()
        data["ciec"] = "AB"
        with pytest.raises(OnboardingError, match="CIEC inválido"):
            wizard.set_step(2, data)

    def test_missing_ciec_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        with pytest.raises(OnboardingError, match="ciec"):
            wizard.set_step(2, {})

    def test_efirma_incomplete_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        data = _valid_sat()
        data["efirma_certificado"] = "/path/cert.cer"
        # Remove the llave so only cert is present
        data.pop("efirma_llave", None)
        with pytest.raises(OnboardingError, match="e.firma incompleta"):
            wizard.set_step(2, data)

    def test_optional_fields_accepted(self, wizard):
        """CIEC alone is enough; efirma is optional."""
        wizard.set_step(1, _valid_company())
        status = wizard.set_step(2, {"ciec": "ABC123"})
        assert status["current_step"] == 3


class TestStep3ERPConnection:
    def test_valid_contpaqi_advances(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        status = wizard.set_step(3, _valid_erp_contpaqi())
        assert status["current_step"] == 4

    def test_valid_aspel_advances(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        erp = _valid_erp_contpaqi()
        erp["erp"] = "Aspel"
        status = wizard.set_step(3, erp)
        assert status["current_step"] == 4

    def test_valid_csv_advances(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        status = wizard.set_step(3, _valid_erp_csv())
        assert status["current_step"] == 4

    def test_erp_normalized_case(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        erp = _valid_erp_contpaqi()
        erp["erp"] = "contpaqi"
        wizard.set_step(3, erp)
        step = wizard.get_step(3)
        assert step["data"]["erp"] == "ContPAQi"

    def test_invalid_erp_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        with pytest.raises(OnboardingError, match="ERP inválido"):
            wizard.set_step(3, {"erp": "SAP"})

    def test_contpaqi_missing_credentials_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        with pytest.raises(OnboardingError, match="credenciales"):
            wizard.set_step(3, {"erp": "ContPAQi"})

    def test_contpaqi_partial_credentials_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        with pytest.raises(OnboardingError, match="Faltan"):
            wizard.set_step(3, {
                "erp": "ContPAQi",
                "credentials_host": "192.168.1.100",
                "credentials_user": "admin",
                # missing password
            })

    def test_csv_missing_file_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        with pytest.raises(OnboardingError, match="csv_file"):
            wizard.set_step(3, {"erp": "CSV"})


class TestStep4BillingPlan:
    def test_valid_plan_advances(self, wizard):
        """Full flow to step 4 with basico plan."""
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        status = wizard.set_step(4, {"plan": "basico"})
        assert status["current_step"] == 5
        assert "billing_plan" in status["completed_steps"]

    def test_basico_plan(self, wizard):
        """Full flow to step 4 with basico plan."""
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        status = wizard.set_step(4, {"plan": "basico"})
        assert status["current_step"] == 5
        step4 = wizard.get_step(4)
        assert step4["data"]["plan"] == "basico"
        assert step4["data"]["plan_detail"]["price_mxn"] == 4900.0

    def test_profesional_plan(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        status = wizard.set_step(4, _valid_billing())
        assert status["current_step"] == 5
        step4 = wizard.get_step(4)
        assert step4["data"]["plan_detail"]["price_mxn"] == 12000.0

    def test_enterprise_plan(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        status = wizard.set_step(4, {"plan": "enterprise"})
        assert status["current_step"] == 5
        step4 = wizard.get_step(4)
        assert step4["data"]["plan_detail"]["price_mxn"] == 48000.0

    def test_invalid_plan_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        with pytest.raises(OnboardingError, match="Plan inválido"):
            wizard.set_step(4, {"plan": "ultra"})

    def test_plan_normalized_lowercase(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        wizard.set_step(4, {"plan": "BASICO"})
        step = wizard.get_step(4)
        assert step["data"]["plan"] == "basico"


class TestStep5FirstCFDI:
    def _go_to_step5(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        wizard.set_step(4, _valid_billing())

    def test_valid_cfdi_completes_wizard(self, wizard):
        self._go_to_step5(wizard)
        status = wizard.set_step(5, _valid_cfdi())
        assert status["current_step"] == 5
        assert status["complete"] is True

    def test_cfdi_too_short_fails(self, wizard):
        self._go_to_step5(wizard)
        with pytest.raises(OnboardingError, match="demasiado corto"):
            wizard.set_step(5, {"cfdi_xml": "<short/>"})

    def test_cfdi_not_cfdi_format_fails(self, wizard):
        self._go_to_step5(wizard)
        with pytest.raises(OnboardingError, match="no parece ser un CFDI"):
            wizard.set_step(5, {"cfdi_xml": "<html>" + "x" * 50})

    def test_missing_cfdi_xml_fails(self, wizard):
        self._go_to_step5(wizard)
        with pytest.raises(OnboardingError, match="cfdi_xml"):
            wizard.set_step(5, {})


# ────────────────────────────────────────────────────────────────────────── #
# Wizard: state machine — persistence and resume
# ────────────────────────────────────────────────────────────────────────── #

class TestWizardStateMachine:
    def test_resume_from_step_2(self, wizard):
        """If step 1 is done but step 2 is not, current_step stays at 2."""
        wizard.set_step(1, _valid_company())
        status = wizard.status()
        assert status["current_step"] == 2
        assert "company_profile" in status["completed_steps"]
        assert "sat_credentials" not in status["completed_steps"]

    def test_out_of_order_completion(self, wizard):
        """Steps can be completed out of order; current_step jumps ahead."""
        wizard.set_step(1, _valid_company())
        # Skip step 2, go to step 3 directly — this should work
        # if the data is valid
        wizard.set_step(3, _valid_erp_contpaqi(), advance=False)
        status = wizard.status()
        assert "company_profile" in status["completed_steps"]
        assert "erp_connection" in status["completed_steps"]
        assert "sat_credentials" not in status["completed_steps"]

    def test_step_data_persists(self, wizard):
        wizard.set_step(1, _valid_company())
        step1 = wizard.get_step(1)
        assert step1["complete"] is True
        assert step1["data"]["name"] == "Despacho Contable ABC"
        assert step1["data"]["rfc"] == "CACR850101AB1"

    def test_step_data_can_be_overwritten(self, wizard):
        """Re-sending a step updates its data."""
        wizard.set_step(1, _valid_company())
        data2 = _valid_company()
        data2["name"] = "Nombre Actualizado"
        wizard.set_step(1, data2, advance=False)
        step1 = wizard.get_step(1)
        assert step1["data"]["name"] == "Nombre Actualizado"

    def test_invalid_step_number_raises(self, wizard):
        with pytest.raises(OnboardingError, match="Paso inválido"):
            wizard.set_step(99, {})

    def test_invalid_step_number_on_get(self, wizard):
        with pytest.raises(OnboardingError, match="Paso inválido"):
            wizard.get_step(0)

    def test_no_tenant_raises(self, db):
        wiz = OnboardingWizard(db, tenant_id=None)
        with pytest.raises(OnboardingError, match="tenant_id"):
            wiz.status()

    def test_nonexistent_tenant_raises(self, db):
        wiz = OnboardingWizard(db, tenant_id=99999)
        from b2b_ai.db.tenants import TenantNotFoundError
        with pytest.raises(TenantNotFoundError):
            wiz.status()

    def test_data_must_be_dict(self, wizard):
        with pytest.raises(OnboardingError, match="objeto JSON"):
            wizard.set_step(1, "not a dict")


# ────────────────────────────────────────────────────────────────────────── #
# Wizard: complete
# ────────────────────────────────────────────────────────────────────────── #

class TestWizardComplete:
    def _complete_all_steps(self, wizard):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        wizard.set_step(4, _valid_billing())
        wizard.set_step(5, _valid_cfdi())

    def test_complete_all_steps_marks_complete(self, wizard):
        self._complete_all_steps(wizard)
        status = wizard.status()
        assert status["complete"] is True
        assert len(status["completed_steps"]) == 5

    def test_complete_with_missing_steps_fails(self, wizard):
        wizard.set_step(1, _valid_company())
        with pytest.raises(OnboardingError, match="faltan los pasos"):
            wizard.complete()

    def test_complete_explicit_after_auto_complete(self, wizard):
        """complete() should work even after auto-complete on step 5."""
        self._complete_all_steps(wizard)
        result = wizard.complete()
        assert result["complete"] is True


# ────────────────────────────────────────────────────────────────────────── #
# Checklist: scoring
# ────────────────────────────────────────────────────────────────────────── #

class TestChecklist:
    def test_empty_checklist_score_zero(self, wizard):
        cl = OnboardingChecklist(wizard.db, tenant_id=wizard.tenant_id)
        result = cl.evaluate()
        assert result["score"] == 0
        assert result["complete"] is False
        assert len(result["missing"]) == 5

    def test_company_profile_only_20pts(self, wizard):
        wizard.set_step(1, _valid_company())
        cl = OnboardingChecklist(wizard.db, tenant_id=wizard.tenant_id)
        result = cl.evaluate()
        assert result["score"] == 20
        assert "company_profile" not in result["missing"]

    def test_full_score_100(self, wizard, db):
        wizard.set_step(1, _valid_company())
        wizard.set_step(2, _valid_sat())
        wizard.set_step(3, _valid_erp_contpaqi())
        wizard.set_step(4, _valid_billing())
        wizard.set_step(5, _valid_cfdi())
        # Insert a real invoice for the first_cfdi check
        db.insert_invoice(
            wizard.tenant_id,
            {"archivo": "test.xml", "folio_fiscal": "F-TEST"},
            {"categoria": "gasto"},
            {"ok": True})
        cl = OnboardingChecklist(wizard.db, tenant_id=wizard.tenant_id)
        result = cl.evaluate()
        assert result["score"] == 100
        assert result["complete"] is True
        assert result["missing"] == []

    def test_score_shortcut(self, wizard):
        cl = OnboardingChecklist(wizard.db, tenant_id=wizard.tenant_id)
        assert cl.score() == 0

    def test_checklist_shortcut(self, wizard):
        cl = OnboardingChecklist(wizard.db, tenant_id=wizard.tenant_id)
        checks = cl.checklist()
        assert len(checks) == 5
        assert all(c["check"] in OnboardingChecklist.ALL_CHECKS for c in checks)

    def test_no_tenant_returns_zero(self, db):
        cl = OnboardingChecklist(db, tenant_id=None)
        result = cl.evaluate()
        assert result["score"] == 0
        assert result["tenant_id"] is None


# ────────────────────────────────────────────────────────────────────────── #
# API: endpoints
# ────────────────────────────────────────────────────────────────────────── #

class TestOnboardingAPI:
    # ---- status ----
    def test_status_requires_api_key(self, client):
        c, db, tid = client
        assert c.get("/api/v1/onboarding/status").status_code == 401

    def test_status_ok_empty(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/status", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["onboarding"]["current_step"] == 1
        assert body["checklist"]["score"] == 0

    # ---- steps ----
    def test_steps_endpoint(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/steps", headers=_auth())
        assert r.status_code == 200
        steps = r.json()["steps"]
        assert len(steps) == 5
        assert steps[0]["step"] == 1
        assert steps[0]["name"] == "company_profile"

    # ---- plans ----
    def test_plans_endpoint(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/plans")
        assert r.status_code == 200
        plans = r.json()["plans"]
        assert len(plans) == 3
        prices = {p["key"]: p["price_mxn"] for p in plans}
        assert prices["basico"] == 4900.0
        assert prices["profesional"] == 12000.0
        assert prices["enterprise"] == 48000.0

    # ---- erp-options ----
    def test_erp_options_endpoint(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/erp-options")
        assert r.status_code == 200
        erps = r.json()["erp_options"]
        assert set(erps) == {"ContPAQi", "Aspel", "CSV"}

    # ---- get step ----
    def test_get_step(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/step/1", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["step"] == 1
        assert body["complete"] is False
        assert body["data"] == {}

    def test_get_step_invalid(self, client):
        c, db, tid = client
        r = c.get("/api/v1/onboarding/step/99", headers=_auth())
        assert r.status_code == 400

    # ---- put step ----
    def test_put_step_validates_and_advances(self, client):
        c, db, tid = client
        r = c.put("/api/v1/onboarding/step/1", headers=_auth(),
                  json=_valid_company())
        assert r.status_code == 200
        assert r.json()["onboarding"]["current_step"] == 2

    def test_put_step_invalid_400(self, client):
        c, db, tid = client
        r = c.put("/api/v1/onboarding/step/1", headers=_auth(),
                  json={"name": "X"})
        assert r.status_code == 400

    def test_put_step_nonexistent_400(self, client):
        c, db, tid = client
        r = c.put("/api/v1/onboarding/step/9", headers=_auth(), json={})
        assert r.status_code == 400

    # ---- complete ----
    def test_complete_incomplete_rejected(self, client):
        c, db, tid = client
        r = c.post("/api/v1/onboarding/complete", headers=_auth())
        assert r.status_code == 400

    def test_complete_full_flow(self, client):
        c, db, tid = client
        steps = {
            1: _valid_company(),
            2: _valid_sat(),
            3: _valid_erp_contpaqi(),
            4: _valid_billing(),
            5: _valid_cfdi(),
        }
        for s, data in steps.items():
            r = c.put(f"/api/v1/onboarding/step/{s}", headers=_auth(),
                      json=data)
            assert r.status_code == 200, (s, r.text)

        # Insert real invoice for the first_cfdi checklist check
        db.insert_invoice(tid,
                          {"archivo": "test.xml", "folio_fiscal": "F-TEST"},
                          {"categoria": "gasto"}, {"ok": True})

        r = c.post("/api/v1/onboarding/complete", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["onboarding"]["complete"] is True
        assert body["checklist"]["score"] == 100
        assert body["checklist"]["complete"] is True

    # ---- resume test ----
    def test_resume_mid_flow(self, client):
        """Simulate partial onboarding, then resume."""
        c, db, tid = client
        # Complete step 1
        c.put("/api/v1/onboarding/step/1", headers=_auth(),
              json=_valid_company())
        # Check status
        r = c.get("/api/v1/onboarding/status", headers=_auth())
        body = r.json()
        assert body["onboarding"]["current_step"] == 2
        assert body["checklist"]["score"] == 20

        # Resume: complete step 2
        r = c.put("/api/v1/onboarding/step/2", headers=_auth(),
                  json=_valid_sat())
        assert r.status_code == 200
        assert r.json()["onboarding"]["current_step"] == 3

    # ---- out of order test ----
    def test_out_of_order_via_api(self, client):
        """Steps can be submitted out of order."""
        c, db, tid = client
        # Start with step 3
        r = c.put("/api/v1/onboarding/step/3", headers=_auth(),
                  json=_valid_erp_contpaqi())
        assert r.status_code == 200

        # Then step 1
        r = c.put("/api/v1/onboarding/step/1", headers=_auth(),
                  json=_valid_company())
        assert r.status_code == 200
