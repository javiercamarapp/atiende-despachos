# -*- coding: utf-8 -*-
"""Tests de la API dashboard (FastAPI)."""
import pytest

from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho Demo")
    db.create_api_key(1, "key", "legacy-test-key-001")
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": "legacy-test-key-001"}


def test_health(client):
    c, db = client
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["schema_version"] >= 1


def test_invoices_vacio(client):
    c, db = client
    # los endpoints legacy ahora requieren API key
    assert c.get("/invoices").status_code == 401
    r = c.get("/invoices", headers=_auth())
    assert r.status_code == 200
    assert r.json()["invoices"] == []


def test_stats(client):
    c, db = client
    assert c.get("/stats").status_code == 401
    r = c.get("/stats", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["invoices_total"] == 0
    assert "audit_calls" in body
    assert "report" in body


def test_tools_endpoint(client):
    c, db = client
    assert c.get("/tools").status_code == 401
    r = c.get("/tools", headers=_auth())
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tools"]]
    assert "parse_cfdi" in names


def test_process_xml(client, sample_consultoria):
    c, db = client
    r = c.post("/process", json={"xml_path": sample_consultoria},
               headers=_auth())
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["insertado"] is True
    assert res["valido"] is True
    assert res["erp_poliza"]
    assert res["categoria"] == "inversion"


def test_process_archivo_no_existe(client):
    c, db = client
    r = c.post("/process", json={"xml_path": "/no/existe.xml"},
               headers=_auth())
    assert r.status_code == 404


def test_process_folder(client, fixture_dir):
    c, db = client
    r = c.post("/process", json={"folder": fixture_dir}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["procesadas"] >= 5
    assert len(body["results"]) >= 5


def test_process_sin_argumento(client):
    c, db = client
    r = c.post("/process", json={}, headers=_auth())
    assert r.status_code == 400
