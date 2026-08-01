# -*- coding: utf-8 -*-
"""Tests del portal del cliente server-rendered (páginas HTML, t_6baa0aa7).

Cubre: login por formulario (cookie), dashboard, listado de facturas con
filtros/búsqueda, detalle, reportes (lista + descarga), settings (GET/PUT),
notificaciones JSON y exportación CSV/Excel. Verifica el aislamiento
multi-tenant y la protección por sesión en páginas y recursos.
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
    """App con 2 tenants y un cliente en cada uno + facturas sembradas."""
    db = Database(str(tmp_path / "portal_pages.db"))
    t1 = db.create_tenant("Despacho A", rfc="XAXX010101000")
    t2 = db.create_tenant("Despacho B", rfc="XAXX020202000")
    db.create_client_user(t1, "cliente1@a.mx", _hash("pass1"), "Cliente Uno")
    db.create_client_user(t2, "cliente2@b.mx", _hash("pass2"), "Cliente Dos")
    db.set_tenant_config(t1, "rfc", "XAXX010101000")
    db.set_tenant_config(t1, "notif_channel", "email")
    # 2 facturas en t1: una válida/procesada, otra en anomalía.
    db.insert_invoice(t1, {"folio_fiscal": "A-0001", "archivo": "a.xml",
                           "fecha": "2026-02-01", "total": "100.00",
                           "iva": "16.00", "emisor_rfc": "XAXX010101000",
                           "emisor_nombre": "Proveedor Uno",
                           "receptor_rfc": "XAXX010101000"},
                      {"categoria": "gasto_operativo", "confianza": 0.95},
                      {"ok": True, "requires_human_review": False, "issues": []})
    db.insert_invoice(t1, {"folio_fiscal": "A-0002", "archivo": "b.xml",
                           "fecha": "2026-02-02", "total": "20.00",
                           "emisor_rfc": "XAXX010101000",
                           "emisor_nombre": "Proveedor Uno",
                           "receptor_rfc": "XAXX010101000"},
                      {"categoria": "gasto_operativo", "confianza": 0.5},
                      {"ok": False, "requires_human_review": True, "issues": []})
    db.insert_notification(t1, "test", "email", "cliente1@a.mx",
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
# Sesión
# --------------------------------------------------------------------------
def test_page_sin_sesion_redirige_a_login(portal):
    r = portal["client"].get("/portal/dashboard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/portal/login"


def test_login_bueno_setea_cookie(portal):
    r = _login(portal["client"], "cliente1@a.mx", "pass1")
    assert r.status_code == 302
    assert r.headers["location"] == "/portal/dashboard"
    assert "portal_session=" in r.headers["set-cookie"]


def test_login_malo_redirige_con_error(portal):
    r = _login(portal["client"], "cliente1@a.mx", "mala")
    assert r.status_code == 302
    assert r.headers["location"] == "/portal/login?error=1"


def test_logout_invalida_sesion(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/logout", follow_redirects=False)
    assert r.status_code == 302
    assert c.get("/portal/dashboard", follow_redirects=False).status_code == 302


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def test_dashboard_renderiza_stats_y_nav(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/portal/invoices" in r.text
    assert "Facturas" in r.text


# --------------------------------------------------------------------------
# Facturas: filtros, búsqueda, detalle, aislamiento
# --------------------------------------------------------------------------
def test_invoices_html_lista_y_aislamiento(portal):
    c, t2 = portal["client"], portal["t2"]
    _session(c)
    r = c.get("/portal/invoices")
    assert r.status_code == 200
    assert "A-0001" in r.text
    # El cliente 1 no ve nada de tenant 2.
    assert "B-" not in r.text


def test_invoices_busqueda_por_folio(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/invoices", params={"q": "A-0001"})
    assert "A-0001" in r.text
    assert "A-0002" not in r.text


def test_invoices_filtro_estado(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/invoices", params={"estado": "procesado"})
    assert "A-0001" in r.text
    assert "A-0002" not in r.text


def test_invoice_detail_y_404(portal):
    c, db = portal["client"], portal["db"]
    _session(c)
    inv_id = db.get_invoice  # localizar id de A-0001
    rows = db.list_invoices(tenant_id=portal["t1"])
    detail = next(i for i in rows if i["folio_fiscal"] == "A-0001")
    r = c.get(f"/portal/invoices/{detail['id']}")
    assert r.status_code == 200
    assert "A-0001" in r.text
    assert c.get("/portal/invoices/999999").status_code == 404


def test_invoice_detail_aislada_por_tenant(portal):
    c, db, t1, t2 = (portal["client"], portal["db"], portal["t1"], portal["t2"])
    db.insert_invoice(t2, {"folio_fiscal": "B-1", "archivo": "c.xml",
                           "fecha": "2026-01-01", "total": "5.00"},
                      {"categoria": "gasto_operativo", "confianza": 0.9},
                      {"ok": True, "requires_human_review": False, "issues": []})
    b_id = db.list_invoices(tenant_id=t2)[0]["id"]
    _session(c, "cliente1@a.mx", "pass1")
    # El cliente 1 no puede ver facturas de t2.
    assert c.get(f"/portal/invoices/{b_id}").status_code == 404


# --------------------------------------------------------------------------
# Reportes
# --------------------------------------------------------------------------
def test_reports_lista_y_descargas(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/reports")
    assert r.status_code == 200
    for rid in ("resumen", "proveedores", "flujo_caja", "alertas"):
        rd = c.get(f"/portal/reports/{rid}/download")
        assert rd.status_code == 200
        assert f"reporte_{rid}.pdf" in rd.headers["content-disposition"]
        assert "text/html" in rd.headers["content-type"]
    assert c.get("/portal/reports/nope/download").status_code == 404


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def test_settings_get_y_put(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/settings")
    assert r.status_code == 200
    assert "XAXX010101000" in r.text
    r = c.put("/portal/settings", json={"rfc": "XAXX999999999"})
    assert r.status_code == 200
    assert r.json()["updated"] == ["rfc"]
    assert "XAXX999999999" in c.get("/portal/settings").text


def test_settings_put_requiere_sesion(portal):
    r = portal["client"].put("/portal/settings", json={"rfc": "X"})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Notificaciones + exportación
# --------------------------------------------------------------------------
def test_notifications_json(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/notifications")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_export_csv_y_xlsx(portal):
    c = portal["client"]
    _session(c)
    r = c.get("/portal/invoices/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "folio_fiscal" in r.text
    assert "A-0001" in r.text
    r = c.get("/portal/invoices/export.xlsx")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]


def test_export_requiere_sesion(portal):
    r = portal["client"].get("/portal/invoices/export.csv")
    assert r.status_code == 401
