# -*- coding: utf-8 -*-
"""Tests de la API real /api/v1/* (auth por API key, process, listado, stats)."""
import os

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

API_KEY = "test-secret-key-123"


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    # Crear una API key en la DB para el tenant 1
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _auth_headers():
    return {"X-API-Key": API_KEY}


# ---- auth ------------------------------------------------------------------
def test_api_sin_key_rechaza(client):
    c, db = client
    r = c.get("/api/v1/stats")
    assert r.status_code == 401


def test_api_key_invalida_rechaza(client):
    c, db = client
    r = c.get("/api/v1/stats", headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_api_key_valida_ok(client):
    c, db = client
    r = c.get("/api/v1/stats", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["total_facturas"] == 0


# ---- process ---------------------------------------------------------------
def test_process_xml_path_con_auth(client, sample_consultoria):
    c, db = client
    r = c.post("/api/v1/invoices/process",
               headers=_auth_headers(),
               json={"xml_path": sample_consultoria})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["insertado"] is True
    assert res["valido"] is True
    assert res["erp_poliza"]
    assert res["categoria"] == "inversion"


def test_process_multipart_upload(client, sample_papeleria):
    c, db = client
    with open(sample_papeleria, "rb") as f:
        r = c.post("/api/v1/invoices/process",
                   headers=_auth_headers(),
                   files={"xml_file": ("papeleria.xml", f, "text/xml")})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["insertado"] is True
    assert res["categoria"] == "gasto_operativo"


def test_process_xml_vacio(client):
    c, db = client
    r = c.post("/api/v1/invoices/process",
               headers=_auth_headers(),
               files={"xml_file": ("vacio.xml", b"", "text/xml")})
    assert r.status_code == 400


def test_process_sin_archivo(client):
    c, db = client
    r = c.post("/api/v1/invoices/process", headers=_auth_headers())
    assert r.status_code == 400


def test_process_path_inexistente(client):
    c, db = client
    r = c.post("/api/v1/invoices/process",
               headers=_auth_headers(),
               json={"xml_path": "/no/existe.xml"})
    assert r.status_code == 404


# ---- listado + filtros -----------------------------------------------------
def test_listado_y_filtros(client, sample_consultoria, sample_papeleria,
                           sample_nomina):
    c, db = client
    for f in (sample_consultoria, sample_papeleria, sample_nomina):
        r = c.post("/api/v1/invoices/process", headers=_auth_headers(),
                   json={"xml_path": f})
        assert r.status_code == 200

    # listado completo
    r = c.get("/api/v1/invoices", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["count"] == 3

    # filtro por categoría
    r = c.get("/api/v1/invoices", headers=_auth_headers(),
              params={"categoria": "inversion"})
    assert r.json()["count"] == 1
    assert r.json()["invoices"][0]["categoria"] == "inversion"

    # filtro por validez
    r = c.get("/api/v1/invoices", headers=_auth_headers(),
              params={"valido": "true"})
    assert r.json()["count"] >= 3

    # filtro por fecha (rango que lo excluya)
    r = c.get("/api/v1/invoices", headers=_auth_headers(),
              params={"fecha_desde": "2030-01-01"})
    assert r.json()["count"] == 0


def test_detalle_factura(client, sample_consultoria):
    c, db = client
    c.post("/api/v1/invoices/process", headers=_auth_headers(),
           json={"xml_path": sample_consultoria})
    invs = c.get("/api/v1/invoices", headers=_auth_headers()).json()["invoices"]
    inv_id = invs[0]["id"]
    r = c.get(f"/api/v1/invoices/{inv_id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["invoice"]["id"] == inv_id


def test_detalle_no_existe(client):
    c, db = client
    r = c.get("/api/v1/invoices/99999", headers=_auth_headers())
    assert r.status_code == 404


# ---- stats / tools / leads -------------------------------------------------
def test_stats_con_datos(client, sample_consultoria):
    c, db = client
    c.post("/api/v1/invoices/process", headers=_auth_headers(),
           json={"xml_path": sample_consultoria})
    r = c.get("/api/v1/stats", headers=_auth_headers())
    body = r.json()
    assert body["total_facturas"] == 1
    assert body["por_categoria"]["inversion"]["count"] == 1
    assert "report" in body
    assert "audit_calls" in body


def test_tools_con_auth(client):
    c, db = client
    r = c.get("/api/v1/tools", headers=_auth_headers())
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tools"]]
    assert "parse_cfdi" in names


def test_leads_publico(client):
    c, db = client
    r = c.post("/api/v1/leads", json={
        "nombre": "Ana", "email": "ana@despacho.com", "despacho": "Despacho A",
        "facturas": "100-500"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(db.list_leads()) == 1


def test_leads_publico_sin_email(client):
    c, db = client
    r = c.post("/api/v1/leads", json={"nombre": "Ana", "email": ""})
    assert r.status_code == 422


def test_leads_no_requiere_key(client):
    c, db = client  # sin headers → debe funcionar igual
    r = c.post("/api/v1/leads", json={"nombre": "X", "email": "x@y.com"})
    assert r.status_code == 200


# ---- OpenAPI ---------------------------------------------------------------
def test_openapi_disponible(client):
    c, db = client
    r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/v1/invoices/process" in paths
    assert "/api/v1/invoices" in paths
    assert "/api/v1/stats" in paths
