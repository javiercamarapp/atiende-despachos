# -*- coding: utf-8 -*-
"""Tests de la API v2 enterprise (multi-tenant robusto).

Cubre: batch (sync/async/limite), analytics (+cache), webhooks por evento,
audit, export (CSV/XLSX/PDF), tenant admin (bloqueo/usage), aislamiento
entre tenants y rate limiting por tenant.
"""
import io
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.api import v2 as api_v2

API_KEY_1 = "tenant1-key"
API_KEY_2 = "tenant2-key"
SERVICE_KEY = "service-master-key"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Cliente con tenant 1 (key) y tenant 2 (key), + key de servicio."""
    monkeypatch.setenv("B2B_API_KEY", SERVICE_KEY)
    db = Database(str(tmp_path / "v2.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")   # id 1
    db.create_tenant("Despacho B", rfc="XAXX020202000")   # id 2
    db.create_api_key(1, "k1", API_KEY_1)
    db.create_api_key(2, "k2", API_KEY_2)
    app = create_app(db)
    return TestClient(app), db


def _h1():
    return {"X-API-Key": API_KEY_1}


def _h2():
    return {"X-API-Key": API_KEY_2}


def _hsvc():
    return {"X-API-Key": SERVICE_KEY}


# --------------------------------------------------------------------------
# Auth / aislamiento
# --------------------------------------------------------------------------
def test_v2_sin_key_rechaza(client):
    c, _db = client
    assert c.get("/api/v2/usage").status_code == 401


def test_v2_aislamiento_entre_tenants(client, sample_consultoria):
    c, db = client
    # Procesa una factura SOLO en tenant 1.
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria]})
    assert r.status_code == 200
    assert r.json()["summary"]["procesadas"] == 1
    # Tenant 2 no ve esa factura.
    r2 = c.get("/api/v2/analytics", headers=_h2())
    assert r2.status_code == 200
    assert r2.json()["data"]["resumen"]["facturas"] == 0


# --------------------------------------------------------------------------
# /batch
# --------------------------------------------------------------------------
def test_batch_sync(client, sample_consultoria, sample_papeleria):
    c, db = client
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria, sample_papeleria]})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["procesadas"] == 2
    assert body["summary"]["validas"] == 2
    assert body["results"][0]["insertado"] is True
    # Usage: facturas procesadas + 1 llamada API.
    u = db.get_usage(1)
    assert u["invoices_processed"] == 2
    assert u["api_calls"] >= 1


def test_batch_sin_inputs_rechaza(client):
    c, _db = client
    r = c.post("/api/v2/batch", headers=_h1(), json={"paths": []})
    assert r.status_code == 400


def test_batch_excede_1000_rechaza(client, tmp_path, monkeypatch):
    c, _db = client
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", str(tmp_path))
    for i in range(1001):
        (tmp_path / f"x{i}.xml").write_text("<xml/>")
    paths = [str(tmp_path / f"x{i}.xml") for i in range(1001)]
    r = c.post("/api/v2/batch", headers=_h1(), json={"paths": paths})
    assert r.status_code == 422


def test_batch_async(client, sample_consultoria):
    c, _db = client
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria], "async": True})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["accepted"] is True
    # Poll del job (thread en background).
    done = None
    for _ in range(50):
        rr = c.get(f"/api/v2/batch/{job_id}", headers=_h1())
        assert rr.status_code == 200
        if rr.json()["status"] == "completed":
            done = rr.json()
            break
        time.sleep(0.05)
    assert done is not None, "job async no completó"
    assert done["summary"]["procesadas"] == 1


def test_batch_async_no_ve_job_de_otro_tenant(client, sample_consultoria):
    c, _db = client
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria], "async": True})
    job_id = r.json()["job_id"]
    # Tenant 2 no puede leer el job de tenant 1.
    assert c.get(f"/api/v2/batch/{job_id}", headers=_h2()).status_code == 404


# --------------------------------------------------------------------------
# /analytics + cache
# --------------------------------------------------------------------------
def test_analytics_estructura_y_cache(client, sample_consultoria):
    c, _db = client
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria]})
    assert r.status_code == 200
    r1 = c.get("/api/v2/analytics", headers=_h1())
    assert r1.status_code == 200
    d = r1.json()["data"]
    assert d["resumen"]["facturas"] == 1
    assert "tendencia_mensual" in d
    assert "por_proveedor" in d
    assert "validez" in d
    assert "monto_promedio" in d
    # Segunda llamada → cache hit.
    r2 = c.get("/api/v2/analytics", headers=_h1())
    assert r2.json()["cached"] is True


# --------------------------------------------------------------------------
# /webhooks
# --------------------------------------------------------------------------
def test_webhooks_registrar_listar_borrar(client):
    c, _db = client
    r = c.post("/api/v2/webhooks", headers=_h1(),
               json={"url": "https://cliente-a/hook",
                     "events": ["invoice_processed", "invoice_failed"]})
    assert r.status_code == 200
    subs = r.json()["subscriptions"]
    assert len(subs) == 2
    # listar
    rl = c.get("/api/v2/webhooks", headers=_h1())
    assert rl.status_code == 200
    assert len(rl.json()["subscriptions"]) == 2
    # tenant 2 no ve las de tenant 1
    rl2 = c.get("/api/v2/webhooks", headers=_h2())
    assert len(rl2.json()["subscriptions"]) == 0
    # borrar
    sid = subs[0]["id"]
    assert c.delete(f"/api/v2/webhooks/{sid}", headers=_h1()).status_code == 200
    # tenant 2 no puede borrar la de tenant 1 (404 por scope)
    assert c.delete(f"/api/v2/webhooks/{sid}", headers=_h2()).status_code == 404


def test_webhooks_url_invalida_rechaza(client):
    c, _db = client
    r = c.post("/api/v2/webhooks", headers=_h1(),
               json={"url": "ftp://malo", "events": ["x"]})
    assert r.status_code == 422


def test_batch_despacha_webhooks(client, sample_consultoria, monkeypatch):
    c, db = client
    c.post("/api/v2/webhooks", headers=_h1(),
           json={"url": "https://cliente-a/hook", "events": ["invoice_processed"]})
    calls = []

    def fake_post(url, payload, timeout=15):
        calls.append(url)
        return 200

    monkeypatch.setattr(api_v2, "default_post", fake_post)
    r = c.post("/api/v2/batch", headers=_h1(),
               json={"paths": [sample_consultoria], "webhook": True})
    assert r.status_code == 200
    assert calls == ["https://cliente-a/hook"]
    assert r.json()["webhook_deliveries"][0]["ok"] is True


# --------------------------------------------------------------------------
# /audit
# --------------------------------------------------------------------------
def test_audit_por_tenant(client):
    c, _db = client
    # Genera audit al llamar endpoints de tenant 1.
    c.get("/api/v2/health", headers=_h1())
    r = c.get("/api/v2/audit", headers=_h1())
    assert r.status_code == 200
    assert isinstance(r.json()["audit"], list)
    # Tenant 2 no ve el audit de tenant 1.
    r2 = c.get("/api/v2/audit", headers=_h2())
    assert all(row["tenant_id"] == 2 for row in r2.json()["audit"])


# --------------------------------------------------------------------------
# /export
# --------------------------------------------------------------------------
def _seed(client, sample_consultoria):
    r = client.post("/api/v2/batch", headers=_h1(),
                    json={"paths": [sample_consultoria]})
    assert r.status_code == 200


def test_export_csv(client, sample_consultoria):
    c, _db = client
    _seed(c, sample_consultoria)
    r = c.post("/api/v2/export", headers=_h1(),
               json={"format": "csv", "scope": "invoices"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "Content-Disposition" in r.headers
    body = r.content.decode("utf-8")
    assert "archivo" in body
    assert sample_consultoria.split("/")[-1] in body


def test_export_xlsx(client, sample_consultoria):
    c, _db = client
    _seed(c, sample_consultoria)
    r = c.post("/api/v2/export", headers=_h1(),
               json={"format": "xlsx", "scope": "invoices"})
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    # Es un zip válido (xlsx).
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "xl/worksheets/sheet1.xml" in z.namelist()


def test_export_pdf(client, sample_consultoria):
    c, _db = client
    _seed(c, sample_consultoria)
    r = c.post("/api/v2/export", headers=_h1(),
               json={"format": "pdf", "scope": "invoices"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"


def test_export_formato_invalido(client):
    c, _db = client
    r = c.post("/api/v2/export", headers=_h1(),
               json={"format": "doc", "scope": "invoices"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# /usage + /health
# --------------------------------------------------------------------------
def test_usage_y_health(client):
    c, _db = client
    r = c.get("/api/v2/usage", headers=_h1())
    assert r.status_code == 200
    assert r.json()["usage"]["api_calls"] >= 1
    h = c.get("/api/v2/health", headers=_h1())
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert "connection_pool" in h.json()
    assert "cache" in h.json()


# --------------------------------------------------------------------------
# Tenant admin: bloquear / desbloquear / usage
# --------------------------------------------------------------------------
def test_admin_bloquea_tenant(client):
    c, _db = client
    # Antes de bloquear, tenant 1 funciona.
    assert c.get("/api/v2/usage", headers=_h1()).status_code == 200
    # Bloquear con key de servicio.
    r = c.post("/api/v2/tenants/1/block", headers=_hsvc())
    assert r.status_code == 200
    assert r.json()["blocked"] is True
    # Tenant 1 ya NO puede autenticarse (403).
    assert c.get("/api/v2/usage", headers=_h1()).status_code == 403
    # Desbloquear.
    r = c.post("/api/v2/tenants/1/unblock", headers=_hsvc())
    assert r.json()["blocked"] is False
    assert c.get("/api/v2/usage", headers=_h1()).status_code == 200


def test_admin_sin_privilegios_no_bloquea_otro(client):
    c, _db = client
    # Tenant 2 no puede bloquear al tenant 1.
    assert c.post("/api/v2/tenants/1/block", headers=_h2()).status_code == 403


def test_admin_lista_tenants_con_usage(client):
    c, _db = client
    c.get("/api/v2/usage", headers=_h1())  # genera uso en tenant 1
    r = c.get("/api/v2/tenants", headers=_hsvc())
    assert r.status_code == 200
    by_id = {t["id"]: t for t in r.json()["tenants"]}
    assert by_id[1]["usage"]["api_calls"] >= 1
    assert "blocked" in by_id[1]


def test_admin_usage_por_tenant(client):
    c, _db = client
    r = c.get("/api/v2/tenants/1/usage", headers=_hsvc())
    assert r.status_code == 200
    assert r.json()["usage"]["api_calls"] >= 0


def test_admin_config_tenant(client):
    c, _db = client
    r = c.patch("/api/v2/tenants/1", headers=_hsvc(),
                json={"config": {"notif_channel": "whatsapp",
                                 "rate_limit_per_min": "600"}})
    assert r.status_code == 200
    assert r.json()["config"]["notif_channel"] == "whatsapp"
    assert r.json()["config"]["rate_limit_per_min"] == "600"


# --------------------------------------------------------------------------
# Rate limiting por tenant
# --------------------------------------------------------------------------
def test_rate_limit_por_tenant(client):
    c, _db = client
    # Configura límite de 2 llamadas/minuto para tenant 1 (admin).
    c.patch("/api/v2/tenants/1", headers=_hsvc(),
            json={"config": {"rate_limit_per_min": "2"}})
    # 2 llamadas OK.
    assert c.get("/api/v2/usage", headers=_h1()).status_code == 200
    assert c.get("/api/v2/usage", headers=_h1()).status_code == 200
    # 3ª → 429.
    r = c.get("/api/v2/usage", headers=_h1())
    assert r.status_code == 429
    # Tenant 2 no se ve afectado (su propio límite, default 300).
    assert c.get("/api/v2/usage", headers=_h2()).status_code == 200


# --------------------------------------------------------------------------
# Service key NO puede usar endpoints tenant-scoped
# --------------------------------------------------------------------------
def test_service_key_no_usa_endpoints_de_tenant(client):
    c, _db = client
    r = c.get("/api/v2/usage", headers=_hsvc())
    assert r.status_code == 422
