# -*- coding: utf-8 -*-
"""Tests del portal del cliente (FASE 5): subida de facturas desde el navegador.

Cubre: login (email+password con bcrypt), magic link, subida multipart +
polling de estado, listado multi-tenant (aislamiento), dashboard/stats y
protección por sesión.
"""
import time

import bcrypt
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app


def _hash(pw):
    return bcrypt.hashpw(pw.encode("utf-8"),
                         bcrypt.gensalt(rounds=4)).decode("utf-8")


@pytest.fixture
def ctx(tmp_path):
    """App con 2 tenants y 2 usuarios de portal (aislamiento multi-tenant)."""
    db = Database(str(tmp_path / "portal.db"))
    t1 = db.create_tenant("Despacho A", rfc="XAXX010101000")
    t2 = db.create_tenant("Despacho B", rfc="XAXX020202000")
    db.create_client_user(t1, "cliente1@a.mx", _hash("pass1"), "Cliente Uno")
    db.create_client_user(t2, "cliente2@b.mx", _hash("pass2"), "Cliente Dos")
    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "t1": t1, "t2": t2}


def _login(client, email, pw):
    return client.post("/portal/auth/login",
                       json={"email": email, "password": pw})


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _sample_xml():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "fixtures", "cfdis",
                        "01_gasto_operativo_papeleria.xml")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def test_login_ok(ctx):
    r = _login(ctx["client"], "cliente1@a.mx", "pass1")
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["tenant_id"] == ctx["t1"]
    assert body["user"]["email"] == "cliente1@a.mx"
    assert body["user"]["name"] == "Cliente Uno"


def test_login_wrong_password(ctx):
    r = _login(ctx["client"], "cliente1@a.mx", "mala")
    assert r.status_code == 401


def test_login_unknown_email(ctx):
    r = _login(ctx["client"], "nadie@a.mx", "x")
    assert r.status_code == 401


def test_me_requires_token(ctx):
    c = ctx["client"]
    assert c.get("/portal/auth/me").status_code == 401
    assert c.get("/portal/invoices.json").status_code == 401


def test_me_with_valid_token(ctx):
    tok = _login(ctx["client"], "cliente2@b.mx", "pass2").json()["token"]
    r = ctx["client"].get("/portal/auth/me", headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["tenant_id"] == ctx["t2"]


def test_magic_link_issues_session(ctx):
    c = ctx["client"]
    r = c.post("/portal/auth/magic-link", json={"email": "cliente1@a.mx"})
    assert r.status_code == 200
    dev_token = r.json().get("dev_token")
    assert dev_token
    # El token del magic link funciona como sesión.
    me = c.get("/portal/auth/me", headers=_auth(dev_token))
    assert me.status_code == 200
    assert me.json()["tenant_id"] == ctx["t1"]


def test_logout_invalidates(ctx):
    c = ctx["client"]
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    assert c.post("/portal/auth/logout", headers=_auth(tok)).status_code == 200
    assert c.get("/portal/auth/me", headers=_auth(tok)).status_code == 401


# --------------------------------------------------------------------------
# Upload + status (async)
# --------------------------------------------------------------------------
def test_upload_requires_auth(ctx):
    with open(_sample_xml(), "rb") as f:
        r = ctx["client"].post("/portal/invoices/upload", files={"file": f})
    assert r.status_code == 401


def test_upload_rejects_non_xml(ctx):
    tok = _login(ctx["client"], "cliente1@a.mx", "pass1").json()["token"]
    r = ctx["client"].post("/portal/invoices/upload", headers=_auth(tok),
                           files={"file": ("nota.txt", b"hola")})
    assert r.status_code == 422


def test_upload_processes_and_polls_status(ctx):
    c, db = ctx["client"], ctx["db"]
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    with open(_sample_xml(), "rb") as f:
        r = c.post("/portal/invoices/upload", headers=_auth(tok),
                   files={"file": f})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "processing"

    # Polling hasta que el job termina (timeout generoso).
    done = None
    for _ in range(60):
        st = c.get("/portal/invoices/%s/status" % job_id,
                   headers=_auth(tok)).json()
        if st["status"] in ("done", "error"):
            done = st
            break
        time.sleep(0.2)
    assert done is not None, "el job no terminó"
    assert done["status"] == "done", done
    assert done["invoice_id"]

    # La factura quedó persistida en el tenant del usuario.
    inv = db.get_invoice(done["invoice_id"], tenant_id=ctx["t1"])
    assert inv is not None


def test_status_for_persisted_invoice(ctx):
    c, db = ctx["client"], ctx["db"]
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    inv_id = db.insert_invoice(ctx["t1"],
                               {"folio_fiscal": "TEST-0001", "archivo": "x.xml",
                                "fecha": "2026-01-01", "total": "100.00",
                                "emisor_rfc": "XAXX010101000"},
                               {"categoria": "gasto_operativo", "confianza": 0.9},
                               {"ok": True, "requires_human_review": False,
                                "issues": []})[0]
    r = c.get("/portal/invoices/%s/status" % inv_id, headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["status"] == "procesado"


# --------------------------------------------------------------------------
# Multi-tenant: cada usuario solo ve SUS facturas
# --------------------------------------------------------------------------
def test_list_isolation_between_tenants(ctx):
    c, db = ctx["client"], ctx["db"]
    # Factura solo en tenant 1.
    db.insert_invoice(ctx["t1"],
                      {"folio_fiscal": "ISO-1", "archivo": "a.xml",
                       "fecha": "2026-01-01", "total": "50.00",
                       "emisor_rfc": "XAXX010101000"},
                      {"categoria": "gasto_operativo", "confianza": 0.8},
                      {"ok": True, "requires_human_review": False,
                       "issues": []})
    tok1 = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    tok2 = _login(c, "cliente2@b.mx", "pass2").json()["token"]

    r1 = c.get("/portal/invoices.json", headers=_auth(tok1)).json()
    r2 = c.get("/portal/invoices.json", headers=_auth(tok2)).json()
    assert r1["count"] == 1
    assert r1["invoices"][0]["folio_fiscal"] == "ISO-1"
    assert r2["count"] == 0


def test_filters_categoria_y_estado(ctx):
    c, db = ctx["client"], ctx["db"]
    db.insert_invoice(ctx["t1"],
                      {"folio_fiscal": "F1", "archivo": "a.xml",
                       "fecha": "2026-02-01", "total": "10.00"},
                      {"categoria": "nomina", "confianza": 0.9},
                      {"ok": True, "requires_human_review": False, "issues": []})
    db.insert_invoice(ctx["t1"],
                      {"folio_fiscal": "F2", "archivo": "b.xml",
                       "fecha": "2026-02-02", "total": "20.00"},
                      {"categoria": "gasto_operativo", "confianza": 0.5},
                      {"ok": False, "requires_human_review": True, "issues": []})
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]

    r = c.get("/portal/invoices.json?categoria=nomina", headers=_auth(tok)).json()
    assert r["count"] == 1 and r["invoices"][0]["folio_fiscal"] == "F1"

    r = c.get("/portal/invoices.json?estado=anomalia", headers=_auth(tok)).json()
    assert r["count"] == 1 and r["invoices"][0]["folio_fiscal"] == "F2"

    r = c.get("/portal/invoices.json?fecha_desde=2026-02-02&fecha_hasta=2026-02-02",
              headers=_auth(tok)).json()
    assert r["count"] == 1 and r["invoices"][0]["folio_fiscal"] == "F2"


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def test_dashboard_stats(ctx):
    c, db = ctx["client"], ctx["db"]
    db.insert_invoice(ctx["t1"],
                      {"folio_fiscal": "S1", "archivo": "a.xml",
                       "fecha": "2026-01-01", "total": "100.00", "iva": "16.00"},
                      {"categoria": "gasto_operativo", "confianza": 0.9},
                      {"ok": True, "requires_human_review": False, "issues": []})
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    r = c.get("/portal/dashboard/stats", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["total_facturas"] == 1
    assert body["monto_total"] == 100.0
    assert body["iva_total"] == 16.0
    assert "por_categoria" in body


def test_csv_export(ctx):
    c, db = ctx["client"], ctx["db"]
    db.insert_invoice(ctx["t1"],
                      {"folio_fiscal": "C1", "archivo": "a.xml",
                       "fecha": "2026-01-01", "total": "77.00"},
                      {"categoria": "gasto_operativo", "confianza": 0.9},
                      {"ok": True, "requires_human_review": False, "issues": []})
    tok = _login(c, "cliente1@a.mx", "pass1").json()["token"]
    r = c.get("/portal/invoices/export.csv", headers=_auth(tok))
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "C1" in r.text
    assert "folio_fiscal" in r.text


# --------------------------------------------------------------------------
# SPA se sirve en /portal/
# --------------------------------------------------------------------------
def test_portal_spa_served(ctx):
    r = ctx["client"].get("/portal/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Portal de facturas" in r.text
