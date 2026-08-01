# -*- coding: utf-8 -*-
"""
test_api_integration.py — Integration tests for the FastAPI app.

Covers:
  - POST /api/v1/invoices/process → 200 + ID
  - GET  /api/v1/invoices/{id} → invoice detail
  - GET  /api/v1/stats → aggregated metrics
  - POST /api/v1/leads → public lead endpoint
  - Multipart upload of XML file
  - Rate limiting (429) under burst
  - Auth: missing key → 401, bad key → 401
"""
import pytest
import io

from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_api(tmp_path):
    """Returns a Database pre-wired with a tenant and API key."""
    db = Database(str(tmp_path / "api_integ.db"))
    db.create_tenant("Despacho Integración")
    db.create_api_key(1, "integ-key", "integration-test-key-001")
    return db


@pytest.fixture
def client(db_api):
    """Returns TestClient + the DB for assertions."""
    app = create_app(db_api)
    return TestClient(app), db_api


AUTH = {"X-API-Key": "integration-test-key-001"}


# ---------------------------------------------------------------------------
# 1. POST /api/v1/invoices/process → 200 + response with ID
# ---------------------------------------------------------------------------
def test_api_process_devuelve_resultado(client, sample_consultoria):
    c, db = client
    r = c.post("/api/v1/invoices/process",
               json={"xml_path": sample_consultoria},
               headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    res = body["result"]
    assert res["insertado"] is True
    assert res["valido"] is True
    assert res["total"] is not None
    assert res["categoria"] == "inversion"


# ---------------------------------------------------------------------------
# 2. GET /api/v1/invoices/{id} → invoice detail
# ---------------------------------------------------------------------------
def test_api_get_invoice_by_id(client, sample_consultoria):
    c, db = client
    # Process first to have an invoice then find it by listing
    c.post("/api/v1/invoices/process",
           json={"xml_path": sample_consultoria},
           headers=AUTH)
    # List to find the invoice id
    r_list = c.get("/api/v1/invoices", headers=AUTH)
    assert r_list.status_code == 200
    invoices = r_list.json()["invoices"]
    assert len(invoices) >= 1
    inv_id = invoices[0]["id"]

    r = c.get(f"/api/v1/invoices/{inv_id}", headers=AUTH)
    assert r.status_code == 200
    inv = r.json()["invoice"]
    assert inv["id"] == inv_id
    assert inv["categoria"] == "inversion"
    assert inv["folio_fiscal"]


def test_api_get_invoice_not_found(client):
    c, db = client
    r = c.get("/api/v1/invoices/99999", headers=AUTH)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. GET /api/v1/stats → aggregated report
# ---------------------------------------------------------------------------
def test_api_stats(client, sample_consultoria):
    c, db = client
    # Process a few invoices first
    from b2b_ai.services.pipeline import process_file
    process_file(sample_consultoria, db=db)
    process_file(sample_consultoria, db=db)

    r = c.get("/api/v1/stats", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "total_facturas" in body
    assert "por_categoria" in body
    assert body["total_facturas"] >= 1


# ---------------------------------------------------------------------------
# 4. POST /api/v1/leads → public lead endpoint
# ---------------------------------------------------------------------------
def test_api_leads(client):
    c, db = client
    r = c.post("/api/v1/leads", json={
        "nombre": "Cliente Test",
        "email": "test@ejemplo.com",
        "despacho": "Despacho XYZ",
        "facturas": "50-100",
        "mensaje": "Quiero automatizar",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["lead_id"] is not None
    assert len(db.list_leads()) == 1


# ---------------------------------------------------------------------------
# 5. Multipart upload of XML file
# ---------------------------------------------------------------------------
def test_api_upload_xml_multipart(client, sample_consultoria):
    c, db = client
    with open(sample_consultoria, "rb") as f:
        xml_content = f.read()
    files = {"xml_file": ("test_factura.xml", xml_content, "text/xml")}
    r = c.post("/api/v1/invoices/process", files=files, headers=AUTH)
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["insertado"] is True
    assert db.count_invoices() >= 1


def test_api_upload_xml_vacio(client):
    c, db = client
    files = {"xml_file": ("vacio.xml", io.BytesIO(), "text/xml")}
    r = c.post("/api/v1/invoices/process", files=files, headers=AUTH)
    assert r.status_code == 400 or r.status_code == 422


def test_api_upload_extension_no_permitida(client):
    c, db = client
    files = {"xml_file": ("malware.exe", b"data", "application/x-msdownload")}
    r = c.post("/api/v1/invoices/process", files=files, headers=AUTH)
    assert r.status_code == 422  # only .xml/.pdf allowed


# ---------------------------------------------------------------------------
# 6. Auth: missing key → 401, bad key → 401
# ---------------------------------------------------------------------------
def test_api_sin_auth_devuelve_401(client):
    c, db = client
    r = c.get("/api/v1/invoices")
    assert r.status_code == 401
    assert "X-API-Key" in r.json()["detail"] or "API key" in r.json()["detail"]


def test_api_key_invalida_devuelve_401(client):
    c, db = client
    r = c.get("/api/v1/invoices", headers={"X-API-Key": "clave-mala"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 7. Rate limiting → 429 under burst
# ---------------------------------------------------------------------------
def test_rate_limit_429_en_burst(client, monkeypatch):
    """Send requests above the rate limit threshold (limit=300/min by default).
    To make this test fast and deterministic, we temporarily lower the limit
    by monkey-patching the env variable."""
    c, db = client
    monkeypatch.setenv("B2B_RATE_LIMIT_PER_MIN", "5")
    # Re-create app with low limit
    app_low = create_app(db)
    c_low = TestClient(app_low)

    # Send 6 requests (limit=5 → 6th should be 429)
    for i in range(6):
        r = c_low.get("/api/v1/invoices", headers=AUTH)
        if r.status_code == 429:
            assert "Retry-After" in r.headers
            break