# -*- coding: utf-8 -*-
"""Tests de los endpoints /api/v1/onboarding/* (wizard + checklist)."""
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
              json={"name": "X", "rfc": "XAXX010101000", "industry": "comercio"})
    assert r.status_code == 200
    assert r.json()["onboarding"]["current_step"] == 2

    r = c.put("/api/v1/onboarding/step/2", headers=_auth(), json={"erp": "ASPEL"})
    assert r.status_code == 200
    assert r.json()["onboarding"]["current_step"] == 3


def test_put_paso_invalido_400(client):
    c, db = client
    r = c.put("/api/v1/onboarding/step/2", headers=_auth(), json={"erp": "SAP"})
    assert r.status_code == 400


def test_put_paso_inexistente_404_o_400(client):
    c, db = client
    r = c.put("/api/v1/onboarding/step/9", headers=_auth(), json={})
    assert r.status_code == 400


# ---- complete -------------------------------------------------------------
def test_complete_incompleto_rechaza(client):
    c, db = client
    r = c.post("/api/v1/onboarding/complete", headers=_auth())
    assert r.status_code == 400


def test_complete_flujo_ok(client):
    c, db = client
    steps = {
        1: {"name": "X", "rfc": "XAXX010101000", "industry": "comercio"},
        2: {"erp": "CONTPAQi"},
        3: {"mode": "csv", "csv_file": "c.csv"},
        4: {"catalog": [{"codigo": "1000"}]},
        5: {"invoice_id": 1},
        6: {"invites": [{"name": "Ana", "email": "ana@x.com"}]},
        7: {"plan": "starter"},
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
    assert body["users_created"] == 1
    assert body["onboarding"]["complete"] is True
    assert body["checklist"]["score"] == 100
    assert body["checklist"]["complete"] is True
