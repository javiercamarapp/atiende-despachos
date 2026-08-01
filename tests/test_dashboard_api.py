# -*- coding: utf-8 -*-
"""Tests FASE 2 — API: dashboard web, conciliación, nómina y contabilidad."""
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

API_KEY = "test-secret-key-123"


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    # Insertar una factura para que el dashboard tenga datos
    import os
    from b2b_ai.services.pipeline import process_file
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = os.path.join(root, "fixtures", "cfdis", "02_inversion_consultoria.xml")
    process_file(fixture, db=db, tenant_id=1)
    app = create_app(db)
    return TestClient(app), db


def _h():
    return {"X-API-Key": API_KEY}


def test_dashboard_html_con_auth(client):
    c, db = client
    r = c.get("/api/v1/dashboard", headers=_h())
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Dashboard" in body
    assert "Facturas procesadas" in body
    assert "Estado de conciliación" in body


def test_dashboard_html_sin_key_rechaza(client):
    c, db = client
    assert c.get("/api/v1/dashboard").status_code == 401


def test_dashboard_data_json(client):
    c, db = client
    r = c.get("/api/v1/dashboard/data", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert "metricas" in data
    assert data["metricas"]["total_facturas"] == 1
    assert "graficas" in data
    assert data["graficas"]["por_categoria"]
    assert "conciliacion" in data
    assert data["conciliacion"]["es_muestra"] is True


def test_reconcile_run_endpoint(client):
    c, db = client
    body = {
        "invoices": [{"folio_fiscal": "u1", "fecha": "2026-07-03", "total": "5800.00",
                      "emisor": "X"}],
        "bank_transactions": [{"fecha": "2026-07-03", "monto": "5800.00",
                               "descripcion": "T", "ref": "REF-1"}],
    }
    r = c.post("/api/v1/reconcile/run", headers=_h(), json=body)
    assert r.status_code == 200
    assert r.json()["conciliados"] == 1


def test_accounting_catalog_endpoint(client):
    c, db = client
    r = c.get("/api/v1/accounting/catalog", headers=_h())
    assert r.status_code == 200
    assert r.json()["count"] > 20


def test_accounting_balance_endpoint(client):
    c, db = client
    r = c.get("/api/v1/accounting/balance", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert "lineas" in body


def test_accounting_sat_send_endpoint(client):
    c, db = client
    r = c.post("/api/v1/accounting/sat/send", headers=_h(),
               params={"ejercicio": 2026, "mes": 7})
    assert r.status_code == 200
    assert r.json()["estatus"] == "Aceptado"


def test_payroll_calculate_endpoint(client):
    c, db = client
    body = {
        "empleado": {"nombre": "JUAN", "rfc": "JCCP840101HDA", "salario_diario": 1000},
        "periodo": {"sueldo_bruto": 15000, "dias_pagados": 15},
        "generar_cfdi": True,
    }
    r = c.post("/api/v1/payroll/calculate", headers=_h(), json=body)
    assert r.status_code == 200
    res = r.json()
    assert res["neto_a_pagar"]
    assert "<cfdi:Comprobante" in res["cfdi_xml"]
