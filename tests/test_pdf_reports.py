# -*- coding: utf-8 -*-
"""Tests FASE reportes — Generador de reportes PDF (reportlab) + API /reports.

Cubre:
  - Formato de moneda MXN y fechas MX.
  - Los 6 métodos de PDFGenerator devuelven PDF válidos (cabecera %PDF).
  - Render HTML con Chart.js (plantillas), sin placeholders sin reemplazar.
  - Endpoints /api/v1/reports/* con TestClient sobre una DB aislada.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from b2b_ai.db.db import Database
from b2b_ai.db.tenants import TenantManager
from b2b_ai.reports.pdf_generator import PDFGenerator, mxn, fecha_mx

PERIOD = "2026-07"


@pytest.fixture
def tenant_db(tmp_path):
    """DB aislada con un tenant y facturas del periodo de prueba."""
    db = Database(path=str(tmp_path / "test.db"), migrate=True)
    out = TenantManager(db).onboard_tenant(
        "Despacho Prueba", rfc="XAM010101XXX", user_name="a", user_email="a@b.c")
    tid, key = out["id"], out["api_key"]
    for i in range(6):
        base = 10000 + i * 1000
        db.insert_invoice(
            tenant_id=tid,
            datos={
                "folio_fiscal": f"FF-{i}", "fecha": f"{PERIOD}-{i+1:02d}",
                "tipo": "I" if i % 2 == 0 else "E", "serie": "A", "folio": str(i),
                "emisor_rfc": "ABC991231ZZ9", "emisor_nombre": f"Prov {i}",
                "receptor_rfc": "XAM010101XXX", "subtotal": base,
                "iva": round(base * 0.16, 2), "total": round(base * 1.16, 2),
                "moneda": "MXN", "descripcion": f"Servicio {i}",
            },
            clasif={"categoria": f"cat{i % 3}", "confianza": 0.9},
            validacion={"ok": True, "issues": [], "requires_human_review": False},
        )
    return db, tid, key


# ------------------------------------------------------------------------- #
# Formato
# ------------------------------------------------------------------------- #
def test_formato_mxn():
    assert mxn(1234567.89) == "$1,234,567.89 MXN"
    assert mxn("-500") == "-$500.00 MXN"
    assert mxn(None) == "$0.00 MXN"
    assert mxn("3,200.50") == "$3,200.50 MXN"


def test_formato_fecha_mx():
    assert fecha_mx("2026-07-31") == "31/07/2026"
    assert fecha_mx("2026-07-31T10:30:00") == "31/07/2026"
    assert fecha_mx("") == ""
    assert fecha_mx(None) == ""


# ------------------------------------------------------------------------- #
# PDFGenerator (reportlab)
# ------------------------------------------------------------------------- #
@pytest.fixture
def gen(tenant_db):
    db, tid, key = tenant_db
    return PDFGenerator(db=db), db, tid


def _valid_pdf(b):
    assert b[:5] == b"%PDF-", "no es un PDF"
    assert b.find(b"%%EOF") != -1, "PDF sin fin de archivo"
    assert len(b) > 1000


def test_invoice_report(gen):
    g, db, tid = gen
    inv = db.list_invoices(tenant_id=tid)[0]
    _valid_pdf(g.invoice_report(dict(inv), tenant_id=tid))


def test_monthly_summary(gen):
    g, db, tid = gen
    _valid_pdf(g.monthly_summary(tid, PERIOD))


def test_tax_report(gen):
    g, db, tid = gen
    _valid_pdf(g.tax_report(tid, PERIOD))


def test_reconciliation_report(gen):
    g, db, tid = gen
    data = {
        "periodo": PERIOD, "facturas": 6, "movimientos_banco": 5,
        "conciliados": 4, "pendientes_banco": 1, "pendientes_facturas": 2,
        "monto_conciliado": 40000, "monto_banco_total": 50000,
        "monto_pendiente_banco": 10000, "monto_pendiente_facturas": 12000,
        "tasa_conciliacion": 80.0, "matched": [], "unmatched_bank": [],
    }
    _valid_pdf(g.reconciliation_report(data, tenant_id=tid))


def test_anomaly_report(gen):
    g, db, tid = gen
    anomalies = [
        {"tipo": "duplicado", "severity": "high", "fecha": f"{PERIOD}-10",
         "monto": 5000, "descripcion": "Posible duplicado"},
        {"tipo": "iva_inconsistente", "severity": "medium",
         "fecha": f"{PERIOD}-11", "monto": 200, "descripcion": "IVA no coincide"},
    ]
    _valid_pdf(g.anomaly_report(anomalies, tenant_id=tid))


def test_custom_report(gen):
    g, db, tid = gen
    data = {
        "title": "Custom", "subtitle": "s", "summary": {"a": 1, "b": "x"},
        "table": {"headers": ["h1", "h2"], "rows": [[1, 2], [3, 4]]},
        "chart": {"labels": ["A", "B"], "values": [3, 7]},
    }
    _valid_pdf(g.custom_report(data, tenant_id=tid))


# ------------------------------------------------------------------------- #
# HTML (Chart.js)
# ------------------------------------------------------------------------- #
def test_render_html(gen):
    g, db, tid = gen
    html = g.render_html("monthly_summary", {
        "title": "Resumen Mensual", "subtitle": PERIOD,
        "kpis": [{"label": "Total", "value": "$100,000.00 MXN"}],
        "chart": {"labels": ["A"], "values": [5], "type": "bar"},
    }, tenant_id=tid)
    assert "const DATA = {" in html          # datos embebidos
    assert "chart.js" in html                # CDN de Chart.js
    assert "{{" not in html                  # sin placeholders sin reemplazar
    assert "Despacho Prueba" in html         # nombre del tenant en el header


def test_render_html_missing_template(gen):
    g, db, tid = gen
    with pytest.raises(FileNotFoundError):
        g.render_html("no_existe", {}, tenant_id=tid)


# ------------------------------------------------------------------------- #
# API
# ------------------------------------------------------------------------- #
@pytest.fixture
def client(tenant_db):
    from fastapi.testclient import TestClient
    from b2b_ai.api.app import create_app
    db, tid, key = tenant_db
    app = create_app(db)
    c = TestClient(app)
    return c, tid, key


def _expect_pdf(resp):
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:5] == b"%PDF-"


def test_api_all_report_types(client):
    c, tid, key = client
    H = {"X-API-Key": key}
    for rtype in ("monthly", "tax", "invoices", "anomaly", "reconciliation"):
        r = c.get(f"/api/v1/reports/{rtype}/{PERIOD}", headers=H)
        _expect_pdf(r)
        assert "x-report-id" in r.headers


def test_api_download_roundtrip(client):
    c, tid, key = client
    H = {"X-API-Key": key}
    r = c.get(f"/api/v1/reports/monthly/{PERIOD}", headers=H)
    rid = r.headers["x-report-id"]
    r2 = c.get(f"/api/v1/reports/{rid}/download", headers=H)
    _expect_pdf(r2)
    assert r2.content == r.content


def test_api_custom(client):
    c, tid, key = client
    H = {"X-API-Key": key}
    r = c.post("/api/v1/reports/custom", json={
        "data": {"title": "C", "summary": {"a": 1},
                 "table": {"headers": ["x", "y"], "rows": [[1, 2]]},
                 "chart": {"labels": ["A"], "values": [1]}},
        "tenant_id": tid}, headers=H)
    _expect_pdf(r)


def test_api_custom_html(client):
    c, tid, key = client
    H = {"X-API-Key": key}
    r = c.post("/api/v1/reports/custom", json={
        "data": {"title": "C", "kpis": [{"label": "a", "value": "b"}]},
        "as_html": True, "tenant_id": tid}, headers=H)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "chart.js" in r.text


def test_api_validation(client):
    c, tid, key = client
    H = {"X-API-Key": key}
    assert c.get("/api/v1/reports/bogus/2026-07", headers=H).status_code == 400
    assert c.get("/api/v1/reports/monthly/bad-period",
                 headers=H).status_code == 422
    assert c.get("/api/v1/reports/monthly/2026-07").status_code == 401
    assert c.get("/api/v1/reports/nope/download", headers=H).status_code == 404
