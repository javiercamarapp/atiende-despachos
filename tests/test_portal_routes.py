# -*- coding: utf-8 -*-
"""Tests del client portal — self-service dashboard (t_44a27c1b).

Cubre los endpoints de datos del portal:
    GET /portal/summary
    GET /portal/cfdis        (con filtros de fecha, estatus, monto)
    GET /portal/declaraciones
    GET /portal/alertas
    GET /portal/metrics
    GET /portal/activity
    GET /portal/selfservice  (página HTML)

Verifica el aislamiento multi-tenant (cada cliente solo ve SU tenant) y
la protección por sesión (401 sin login).
"""
import bcrypt
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app


def _hash(pw):
    return bcrypt.hashpw(pw.encode("utf-8"),
                         bcrypt.gensalt(rounds=4)).decode("utf-8")


@pytest.fixture
def portal(tmp_path):
    """App con 2 tenants, un cliente en cada uno + CFDI/paquetes sembrados."""
    db = Database(str(tmp_path / "portal_routes.db"))
    t1 = db.create_tenant("Despacho A", rfc="XAXX010101000")
    t2 = db.create_tenant("Despacho B", rfc="XAXX020202000")
    db.create_client_user(t1, "cliente1@a.mx", _hash("pass1"), "Cliente Uno")
    db.create_client_user(t2, "cliente2@b.mx", _hash("pass2"), "Cliente Dos")
    # CFDIs en t1: 1 procesada/válida y 1 anomalía (requiere revisión).
    db.insert_invoice(t1, {"folio_fiscal": "A-0001", "archivo": "a.xml",
                           "fecha": "2026-02-01", "total": "100.00",
                           "iva": "16.00", "emisor_rfc": "XAXX010101000",
                           "emisor_nombre": "Proveedor Uno",
                           "receptor_rfc": "XAXX010101000"},
                      {"categoria": "gasto_operativo", "confianza": 0.95},
                      {"ok": True, "requires_human_review": False,
                       "issues": []})
    db.insert_invoice(t1, {"folio_fiscal": "A-0002", "archivo": "b.xml",
                           "fecha": "2026-02-02", "total": "20.00",
                           "emisor_rfc": "XAXX010101000",
                           "emisor_nombre": "Proveedor Uno",
                           "receptor_rfc": "XAXX010101000"},
                      {"categoria": "gasto_operativo", "confianza": 0.5},
                      {"ok": False, "requires_human_review": True,
                       "issues": []})
    # Un CFDI en t2 para verificar aislamiento.
    db.insert_invoice(t2, {"folio_fiscal": "B-0001", "archivo": "c.xml",
                           "fecha": "2026-02-03", "total": "999.00",
                           "emisor_rfc": "XAXX020202000",
                           "emisor_nombre": "Proveedor B",
                           "receptor_rfc": "XAXX020202000"},
                      {"categoria": "gasto_operativo", "confianza": 0.9},
                      {"ok": True, "requires_human_review": False,
                       "issues": []})
    # Paquete de declaración pendiente en t1.
    db.insert_paquete_contabilidad(t1, "2026-01", "XAXX010101000",
                                   "borrador",
                                   {"tipo": "iva", "monto": 1000.0})
    # Notificación enviada (resuelta) en t1.
    db.insert_notification(t1, "portal", "email", "cliente1@a.mx",
                           "Bienvenida", "Portal listo", status="sent")
    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "t1": t1, "t2": t2}


def _login(client, email, pw):
    return client.post("/portal/login", data={"email": email, "password": pw},
                       follow_redirects=False)


def _session(client, email="cliente1@a.mx", pw="pass1"):
    r = _login(client, email, pw)
    assert r.status_code == 302
    cookie = r.headers["set-cookie"]
    token = cookie.split("portal_session=")[1].split(";")[0]
    client.cookies.set("portal_session", token)
    return token


# --------------------------------------------------------------------------
# Protección por sesión
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/portal/summary", "/portal/cfdis", "/portal/declaraciones",
    "/portal/alertas", "/portal/metrics", "/portal/activity",
])
def test_endpoints_requieren_sesion(portal, path):
    r = portal["client"].get(path)
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def test_summary_resumen(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == portal["t1"]
    assert data["cfdis_total"] == 2
    assert data["cfdis_procesados"] == 2      # ambos con status=procesado
    assert data["cfdis_anomalias"] == 1
    assert data["declaraciones_total"] == 1
    assert data["declaraciones_pendientes"] == 1  # borrador
    assert data["alertas_activas"] >= 1       # 1 anomalía (+0 notif. enviadas)
    assert data["monto_total"] == 120.0


def test_summary_aislada_por_tenant(portal):
    c, db, t1, t2 = (portal["client"], portal["db"],
                     portal["t1"], portal["t2"])
    # t1 tiene 2 CFDIs; t2 solo 1.
    _session(c, "cliente1@a.mx", "pass1")
    d1 = c.get("/portal/summary").json()
    assert d1["cfdis_total"] == 2
    _session(c, "cliente2@b.mx", "pass2")
    d2 = c.get("/portal/summary").json()
    assert d2["cfdis_total"] == 1
    assert d2["cfdis_anomalias"] == 0


# --------------------------------------------------------------------------
# CFDI list
# --------------------------------------------------------------------------
def test_cfdis_lista(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/cfdis")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    folios = {x["folio_fiscal"] for x in data["cfdis"]}
    assert folios == {"A-0001", "A-0002"}


def test_cfdis_filtro_estatus(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/cfdis", params={"estatus": "procesado"})
    assert r.json()["count"] == 1
    assert r.json()["cfdis"][0]["folio_fiscal"] == "A-0001"


def test_cfdis_filtro_fecha(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/cfdis", params={"fecha_desde": "2026-02-02"})
    data = r.json()
    assert data["count"] == 1
    assert data["cfdis"][0]["folio_fiscal"] == "A-0002"


def test_cfdis_filtro_monto(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/cfdis", params={"monto_min": 50, "monto_max": 200})
    data = r.json()
    assert data["count"] == 1
    assert data["cfdis"][0]["total"] == 100.0


def test_cfdis_aislada_por_tenant(portal):
    c = portal["client"]
    _session(c, "cliente2@b.mx", "pass2")
    data = c.get("/portal/cfdis").json()
    assert data["count"] == 1
    assert data["cfdis"][0]["folio_fiscal"] == "B-0001"


# --------------------------------------------------------------------------
# Declaraciones
# --------------------------------------------------------------------------
def test_declaraciones(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/declaraciones")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["declaraciones"][0]["periodo"] == "2026-01"
    assert data["declaraciones"][0]["estado"] == "borrador"
    assert data["pendientes"] == 1


# --------------------------------------------------------------------------
# Alertas
# --------------------------------------------------------------------------
def test_alertas_activas_y_resueltas(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/alertas")
    assert r.status_code == 200
    data = r.json()
    # 1 anomalía (activa) + 1 notificación enviada (resuelta).
    assert data["activas"] >= 1
    assert data["resueltas"] >= 1
    tipos = {a["tipo"] for a in data["alertas"]}
    assert "anomalia" in tipos
    assert "notificacion" in tipos


def test_alertas_aislada_por_tenant(portal):
    c = portal["client"]
    _session(c, "cliente2@b.mx", "pass2")
    data = c.get("/portal/alertas").json()
    assert data["activas"] == 0


# --------------------------------------------------------------------------
# Metrics (ahorro)
# --------------------------------------------------------------------------
def test_metrics_ahorro(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/metrics")
    assert r.status_code == 200
    data = r.json()
    # Solo 1 CFDI procesado y válido cuenta para el ahorro.
    assert data["cfdis_procesados"] == 1
    assert data["horas_ahorradas"] > 0
    assert data["errores_evitados"] >= 0
    assert data["roi"] > 0


def test_metrics_aislada_por_tenant(portal):
    c = portal["client"]
    _session(c, "cliente2@b.mx", "pass2")
    data = c.get("/portal/metrics").json()
    assert data["cfdis_procesados"] == 1  # solo B-0001


# --------------------------------------------------------------------------
# Activity
# --------------------------------------------------------------------------
def test_activity_timeline(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/activity")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 3  # 2 CFDIs + 1 declaración (+notif)
    tipos = {e["tipo"] for e in data["activity"]}
    assert "cfdi" in tipos
    assert "declaracion" in tipos


def test_activity_aislada_por_tenant(portal):
    c = portal["client"]
    _session(c, "cliente2@b.mx", "pass2")
    data = c.get("/portal/activity").json()
    # t2: solo su CFDI B-0001 (sin declaraciones ni notificaciones).
    assert data["count"] == 1
    assert "B-0001" in data["activity"][0]["titulo"]


# --------------------------------------------------------------------------
# Página HTML self-service
# --------------------------------------------------------------------------
def test_selfservice_pagina(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/selfservice")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Mi empresa" in r.text
    assert "Ahorro con Likida AI" in r.text


def test_selfservice_sin_sesion_redirige(portal):
    r = portal["client"].get("/portal/selfservice", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/portal/login"
