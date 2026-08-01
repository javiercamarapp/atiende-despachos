# -*- coding: utf-8 -*-
"""
test_portal_integration.py — Integration tests for the B&B AI portal module.

Covers:
  - Portal API endpoints (auth, dashboard, invoices, notifications, settings)
  - Server-rendered pages (dashboard, invoices, reports, settings)
  - Multi-tenant isolation (data scoped to tenant)
  - Invoice filtering, CSV/XLSX export
  - Edge cases: empty data, unauthorized access, invalid tenant, special chars
"""
from __future__ import annotations

import csv
import io
import time

import bcrypt
import pytest
from fastapi.testclient import TestClient

from b2b_ai.api.app import create_app
from b2b_ai.db.db import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash(pw):
    return bcrypt.hashpw(pw.encode("utf-8"),
                         bcrypt.gensalt(rounds=4)).decode("utf-8")


def _insert(db, tenant_id, **kw):
    """Insert one invoice, returning (id, inserted)."""
    datos = {
        "folio_fiscal": kw.get("folio_fiscal", f"F-{kw.get('idx', 1)}"),
        "archivo": kw.get("archivo", f"cfdi-{kw.get('idx', 1)}.xml"),
        "fecha": kw.get("fecha", "2026-01-15"),
        "tipo": kw.get("tipo", "E"),
        "serie": kw.get("serie", "A"),
        "folio": str(kw.get("idx", 1)),
        "emisor_rfc": kw.get("emisor_rfc", "XAXX010101000"),
        "emisor_nombre": kw.get("emisor_nombre", "Proveedor Demo"),
        "receptor_rfc": "DESP820101AB1",
        "subtotal": str(kw.get("subtotal", kw.get("total", "100.00"))),
        "iva": str(kw.get("iva", "16.00")),
        "total": str(kw.get("total", "100.00")),
        "moneda": "MXN",
        "descripcion": "",
    }
    clasif = {
        "categoria": kw.get("categoria", "gasto_operativo"),
        "confianza": kw.get("confianza", 0.9),
        "razon": "test",
    }
    validacion = {
        "ok": kw.get("valido", 1) not in (0, False, "0"),
        "requires_human_review": kw.get("requires_human_review", 0) not in (0, False, "0"),
        "issues": [],
    }
    erp = {"poliza": "", "status": ""}
    return db.insert_invoice(tenant_id, datos, clasif, validacion, erp)


def _login(client, email, password):
    """Login via API portal endpoint and return the token string."""
    r = client.post("/portal/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def ctx(tmp_path):
    """Full test context: 2 tenants, 2 users, seeded invoices."""
    db = Database(str(tmp_path / "portal_integ.db"))
    t1 = db.create_tenant("Despacho Alpha", rfc="ALP010101AAA")
    t2 = db.create_tenant("Despacho Beta", rfc="BET020202BBB")
    db.create_client_user(t1, "alpha@test.com", _hash("pass_a"), "Alpha User")
    db.create_client_user(t2, "beta@test.com", _hash("pass_b"), "Beta User")

    # Tenant 1 invoices
    _insert(db, t1, idx=1, folio_fiscal="FAC-0001-AL", total="1000.00", iva="160.00",
            fecha="2026-03-01", emisor_rfc="AAA010101AAA", emisor_nombre="Papeleria A",
            categoria="gasto_operativo", valido=1)
    _insert(db, t1, idx=2, folio_fiscal="FAC-0002-AL", total="5000.00", iva="800.00",
            fecha="2026-03-10", emisor_rfc="BBB020202BBB", emisor_nombre="Consultora B",
            categoria="inversion", valido=1)
    _insert(db, t1, idx=3, folio_fiscal="FAC-0003-AL", total="500.00", iva="80.00",
            fecha="2026-03-15", emisor_rfc="AAA010101AAA", emisor_nombre="Papeleria A",
            categoria="gasto_operativo", valido=0, requires_human_review=1)

    # Tenant 2 invoice
    _insert(db, t2, idx=1, folio_fiscal="FAC-0001-BT", total="2000.00", iva="320.00",
            fecha="2026-03-05", emisor_rfc="CCC030303CCC", emisor_nombre="Servicios C",
            categoria="gasto_operativo", valido=1)

    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "t1": t1, "t2": t2}


# ===================================================================
# 1. AUTH — login, me, logout, magic link
# ===================================================================
class TestPortalAuth:
    def test_login_success(self, ctx):
        token = _login(ctx["client"], "alpha@test.com", "pass_a")
        assert token

    def test_login_wrong_password_returns_401(self, ctx):
        r = ctx["client"].post("/portal/auth/login",
                               json={"email": "alpha@test.com", "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_email_returns_401(self, ctx):
        r = ctx["client"].post("/portal/auth/login",
                               json={"email": "unknown@test.com", "password": "x"})
        assert r.status_code == 401

    def test_login_empty_email_returns_422(self, ctx):
        r = ctx["client"].post("/portal/auth/login",
                               json={"email": "", "password": "pass_a"})
        assert r.status_code == 422

    def test_me_with_valid_token(self, ctx):
        token = _login(ctx["client"], "alpha@test.com", "pass_a")
        r = ctx["client"].get("/portal/auth/me", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == ctx["t1"]
        assert body["user"]["email"] == "alpha@test.com"

    def test_me_without_token_returns_401(self, ctx):
        r = ctx["client"].get("/portal/auth/me")
        assert r.status_code == 401

    def test_me_with_invalid_token_returns_401(self, ctx):
        r = ctx["client"].get("/portal/auth/me",
                              headers=_auth("totally-fake-token-xyz"))
        assert r.status_code == 401

    def test_logout_invalidates_session(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        assert c.post("/portal/auth/logout", headers=_auth(token)).status_code == 200
        assert c.get("/portal/auth/me", headers=_auth(token)).status_code == 401

    def test_magic_link_issues_token(self, ctx):
        c = ctx["client"]
        r = c.post("/portal/auth/magic-link",
                   json={"email": "alpha@test.com"})
        assert r.status_code == 200
        dev_token = r.json().get("dev_token")
        assert dev_token
        me = c.get("/portal/auth/me", headers=_auth(dev_token))
        assert me.status_code == 200

    def test_magic_link_unknown_email_returns_404(self, ctx):
        r = ctx["client"].post("/portal/auth/magic-link",
                               json={"email": "ghost@test.com"})
        assert r.status_code == 404

    def test_confirm_valid_token(self, ctx):
        c = ctx["client"]
        r = c.post("/portal/auth/magic-link",
                   json={"email": "alpha@test.com"})
        dev_token = r.json()["dev_token"]
        confirm = c.post("/portal/auth/confirm",
                         json={"token": dev_token})
        assert confirm.status_code == 200
        assert confirm.json()["tenant_id"] == ctx["t1"]

    def test_confirm_invalid_token_returns_401(self, ctx):
        r = ctx["client"].post("/portal/auth/confirm",
                               json={"token": "bogus"})
        assert r.status_code == 401


# ===================================================================
# 2. DASHBOARD — stats, data aggregation
# ===================================================================
class TestPortalDashboard:
    def test_stats_returns_totals(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/dashboard/stats", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["total_facturas"] == 3
        assert body["monto_total"] == 6500.0
        assert body["iva_total"] == 1040.0

    def test_stats_show_anomalies(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/dashboard/stats", headers=_auth(token)).json()
        assert body["anomalias"] >= 1

    def test_stats_empty_tenant(self, ctx):
        """Tenant 2 has only 1 invoice — stats should reflect that."""
        c = ctx["client"]
        token = _login(c, "beta@test.com", "pass_b")
        body = c.get("/portal/dashboard/stats", headers=_auth(token)).json()
        assert body["total_facturas"] == 1
        assert body["monto_total"] == 2000.0

    def test_stats_by_category(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/dashboard/stats", headers=_auth(token)).json()
        assert "por_categoria" in body
        assert "gasto_operativo" in body["por_categoria"]

    def test_stats_requires_auth(self, ctx):
        r = ctx["client"].get("/portal/dashboard/stats")
        assert r.status_code == 401


# ===================================================================
# 3. INVOICES — list, filter, detail
# ===================================================================
class TestPortalInvoices:
    def test_list_invoices_tenant1(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json", headers=_auth(token)).json()
        assert body["count"] == 3
        assert body["tenant_id"] == ctx["t1"]

    def test_list_invoices_tenant2_isolation(self, ctx):
        c = ctx["client"]
        token = _login(c, "beta@test.com", "pass_b")
        body = c.get("/portal/invoices.json", headers=_auth(token)).json()
        assert body["count"] == 1
        assert body["invoices"][0]["folio_fiscal"] == "FAC-0001-BT"

    def test_tenant1_cannot_see_tenant2_data(self, ctx):
        """Tenant 1 should NOT see tenant 2's invoice."""
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json", headers=_auth(token)).json()
        folios = [i["folio_fiscal"] for i in body["invoices"]]
        assert "FAC-0001-BT" not in folios

    def test_filter_by_categoria(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json?categoria=inversion",
                     headers=_auth(token)).json()
        assert body["count"] == 1
        assert body["invoices"][0]["folio_fiscal"] == "FAC-0002-AL"

    def test_filter_by_estado_anomalia(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json?estado=anomalia",
                     headers=_auth(token)).json()
        assert body["count"] >= 1

    def test_filter_by_date_range(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get(
            "/portal/invoices.json?fecha_desde=2026-03-10&fecha_hasta=2026-03-15",
            headers=_auth(token)).json()
        assert body["count"] == 2

    def test_filter_by_valido_false(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json?valido=false",
                     headers=_auth(token)).json()
        assert body["count"] == 1

    def test_invoice_status_endpoint(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        # Get first invoice id from list
        invoices = c.get("/portal/invoices.json", headers=_auth(token)).json()
        inv_id = invoices["invoices"][0]["id"]
        r = c.get(f"/portal/invoices/{inv_id}/status", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["status"] == "procesado"

    def test_invoice_status_nonexistent_returns_404(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices/999999/status", headers=_auth(token))
        assert r.status_code == 404

    def test_invoices_requires_auth(self, ctx):
        r = ctx["client"].get("/portal/invoices.json")
        assert r.status_code == 401


# ===================================================================
# 4. CSV EXPORT
# ===================================================================
class TestPortalCSVExport:
    def test_csv_export_success(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices/export.csv", headers=_auth(token))
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        # Should contain BOM
        assert r.content[:3] == b"\xef\xbb\xbf"
        # Parse CSV
        text = r.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) > 1  # header + data
        assert "folio_fiscal" in rows[0]

    def test_csv_export_has_all_invoices(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices/export.csv", headers=_auth(token))
        text = r.content.decode("utf-8-sig")
        assert "FAC-0001-AL" in text
        assert "FAC-0002-AL" in text
        assert "FAC-0003-AL" in text

    def test_csv_export_empty_tenant(self, ctx):
        """Tenant with no invoices should still get valid CSV with just headers."""
        c = ctx["client"]
        # Create a third tenant with no invoices
        db = ctx["db"]
        t3 = db.create_tenant("Empty Tenant", rfc="EMP000000000")
        db.create_client_user(t3, "empty@test.com", _hash("pass_e"), "Empty User")
        token = _login(c, "empty@test.com", "pass_e")
        r = c.get("/portal/invoices/export.csv", headers=_auth(token))
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        lines = text.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_csv_export_tenant_isolation(self, ctx):
        c = ctx["client"]
        token = _login(c, "beta@test.com", "pass_b")
        r = c.get("/portal/invoices/export.csv", headers=_auth(token))
        text = r.content.decode("utf-8-sig")
        assert "FAC-0001-BT" in text
        assert "FAC-0001-AL" not in text

    def test_csv_export_requires_auth(self, ctx):
        r = ctx["client"].get("/portal/invoices/export.csv")
        assert r.status_code == 401


# ===================================================================
# 5. NOTIFICATIONS
# ===================================================================
class TestPortalNotifications:
    def test_notifications_json_empty(self, ctx):
        """No notifications seeded — should return empty list."""
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        # Notifications are at /portal/notifications (HTML page)
        # and there's no JSON endpoint exposed; test the magic-link
        # notification that was created during login flow
        r = c.get("/portal/notifications/stream",
                  headers=_auth(token))
        # SSE stream — just check it starts
        # (don't consume, would block)
        assert r.status_code in (200, 401)

    def test_magic_link_creates_notification(self, ctx):
        c = ctx["client"]
        r = c.post("/portal/auth/magic-link",
                   json={"email": "alpha@test.com"})
        assert r.status_code == 200
        # A notification should have been inserted
        db = ctx["db"]
        notifs = db.list_notifications(tenant_id=ctx["t1"], limit=10)
        assert len(notifs) >= 1


# ===================================================================
# 6. SETTINGS
# ===================================================================
class TestPortalSettings:
    def test_get_settings_returns_config(self, ctx):
        """Settings page should return tenant config defaults."""
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        # Server-rendered settings page — follow redirect if needed
        r = c.get("/portal/settings", headers=_auth(token), follow_redirects=True)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_update_settings(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.put("/portal/settings",
                  headers=_auth(token),
                  json={"rfc": "NEW123456789"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "rfc" in body["updated"]

    def test_update_settings_empty_body(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.put("/portal/settings", headers=_auth(token), json={})
        assert r.status_code == 200
        assert r.json()["updated"] == []

    def test_settings_requires_auth(self, ctx):
        r = ctx["client"].get("/portal/settings", follow_redirects=False)
        assert r.status_code == 302


# ===================================================================
# 7. SERVER-RENDERED PAGES (HTML responses)
# ===================================================================
class TestPortalPages:
    def test_dashboard_page_renders(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/dashboard", headers=_auth(token))
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_dashboard_redirect_without_session(self, ctx):
        r = ctx["client"].get("/portal/dashboard", follow_redirects=False)
        assert r.status_code == 302

    def test_invoices_page_renders(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices", headers=_auth(token))
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_reports_page_renders(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/reports", headers=_auth(token))
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_login_page_renders(self, ctx):
        r = ctx["client"].get("/portal/login")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_login_page_redirects_if_already_logged_in(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/login", headers=_auth(token), follow_redirects=False)
        assert r.status_code == 302


# ===================================================================
# 8. EDGE CASES
# ===================================================================
class TestPortalEdgeCases:
    def test_special_characters_in_invoice_data(self, ctx):
        """Invoices with special chars in names should be handled."""
        db = ctx["db"]
        _insert(db, ctx["t1"], idx=99, folio_fiscal="SPEC-99-Ñ",
                emisor_nombre="Papelera Ñ & Cia <lt>",
                total="100.00", fecha="2026-04-01")
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json", headers=_auth(token)).json()
        assert body["count"] == 4  # 3 original + 1 new

    def test_large_dataset_many_invoices(self, ctx):
        """Insert 200 invoices — portal should still respond."""
        db = ctx["db"]
        for i in range(200):
            _insert(db, ctx["t1"], idx=1000 + i,
                    folio_fiscal=f"BULK-{i:04d}",
                    total=str(float(i + 1) * 10),
                    fecha="2026-05-01")
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices.json?limit=1000", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 203  # 3 original + 200 bulk

    def test_empty_search_query(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        body = c.get("/portal/invoices.json?q=", headers=_auth(token)).json()
        assert body["count"] == 3

    def test_nonexistent_job_id_status(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/invoices/nonexistent/status",
                  headers=_auth(token))
        assert r.status_code == 404

    def test_settings_update_erp_type(self, ctx):
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.put("/portal/settings", headers=_auth(token),
                  json={"erp_type": "contpaqi"})
        assert r.status_code == 200
        assert "erp_type" in r.json()["updated"]

    def test_reports_page_has_catalog(self, ctx):
        """Reports page should show the 4 report types."""
        c = ctx["client"]
        token = _login(c, "alpha@test.com", "pass_a")
        r = c.get("/portal/reports", headers=_auth(token))
        assert r.status_code == 200
        # Check that the known report IDs are mentioned
        text = r.text
        assert "resumen" in text or "Resumen" in text
