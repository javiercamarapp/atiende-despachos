# -*- coding: utf-8 -*-
"""Tests de los endpoints /api/v1/onboarding/* (wizard 5 pasos + checklist)."""
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

API_KEY = "onboarding-test-key-1"


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "onb_api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": API_KEY}


# ---- status ---------------------------------------------------------------
def test_status_requiere_api_key(client):
    c, db = client
    assert c.get("/api/v1/onboarding/status").status_code == 401


def test_status_ok_vacio(client):
    c, db = client
    r = c.get("/api/v1/onboarding/status", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["onboarding"]["current_step"] == 1
    assert body["checklist"]["score"] == 0


# ---- step -----------------------------------------------------------------
def test_put_paso_valida_y_avanza(client):
    c, db = client
    r = c.put("/api/v1/onboarding/step/1", headers=_auth(),
              json={"name": "X", "rfc": "XAXX010101000",
                    "address": "Calle 1, CDMX",
                    "contact_name": "Ana", "contact_email": "ana@test.mx"})
    assert r.status_code == 200
    assert r.json()["onboarding"]["current_step"] == 2

    r = c.put("/api/v1/onboarding/step/2", headers=_auth(),
              json={"ciec": "ABC123"})
    assert r.status_code == 200
    assert r.json()["onboarding"]["current_step"] == 3


def test_put_paso_invalido_400(client):
    c, db = client
    r = c.put("/api/v1/onboarding/step/3", headers=_auth(),
              json={"erp": "SAP"})
    assert r.status_code == 400


def test_put_paso_inexistente_404_o_400(client):
    c, db = client
    r = c.put("/api/v1/onboarding/step/9", headers=_auth(), json={})
    assert r.status_code == 400


# ---- plans & erp-options --------------------------------------------------
def test_plans_endpoint(client):
    c, db = client
    r = c.get("/api/v1/onboarding/plans")
    assert r.status_code == 200
    plans = r.json()["plans"]
    assert len(plans) == 3
    prices = {p["key"]: p["price_mxn"] for p in plans}
    assert prices["basico"] == 4900.0
    assert prices["profesional"] == 12000.0
    assert prices["enterprise"] == 48000.0


def test_erp_options_endpoint(client):
    c, db = client
    r = c.get("/api/v1/onboarding/erp-options")
    assert r.status_code == 200
    erps = r.json()["erp_options"]
    assert set(erps) == {"ContPAQi", "Aspel", "CSV"}


# ---- steps endpoint -------------------------------------------------------
def test_steps_endpoint(client):
    c, db = client
    r = c.get("/api/v1/onboarding/steps", headers=_auth())
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert len(steps) == 5


# ---- get step -------------------------------------------------------------
def test_get_step(client):
    c, db = client
    r = c.get("/api/v1/onboarding/step/1", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["step"] == 1
    assert body["complete"] is False


# ---- complete -------------------------------------------------------------
def test_complete_incompleto_rechaza(client):
    c, db = client
    r = c.post("/api/v1/onboarding/complete", headers=_auth())
    assert r.status_code == 400


def test_complete_flujo_ok(client):
    c, db = client
    steps = {
        1: {"name": "X", "rfc": "XAXX010101000",
            "address": "Calle 1", "contact_name": "Ana",
            "contact_email": "ana@x.com"},
        2: {"ciec": "ABC123"},
        3: {"erp": "ContPAQi", "credentials_host": "192.168.1.1",
            "credentials_user": "admin", "credentials_password": "secret"},
        4: {"plan": "basico"},
        5: {"cfdi_xml": '<?xml version="1.0"?><cfdi:Comprobante '
            'xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
            'Version="4.0" SubTotal="1000" Total="1160">'
            '<cfdi:Emisor Rfc="XAXX010101000" Nombre="X"/>'
            '</cfdi:Comprobante>'},
    }
    for s, d in steps.items():
        r = c.put(f"/api/v1/onboarding/step/{s}", headers=_auth(), json=d)
        assert r.status_code == 200, (s, r.text)

    # Factura real para el chequeo de primera factura.
    db.insert_invoice(1, {"archivo": "x.xml", "folio_fiscal": "F-1"},
                      {"categoria": "gasto"}, {"ok": True})

    r = c.post("/api/v1/onboarding/complete", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["onboarding"]["complete"] is True
    assert body["checklist"]["score"] == 100
    assert body["checklist"]["complete"] is True
