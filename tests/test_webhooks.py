# -*- coding: utf-8 -*-
"""Tests del sistema de webhooks (FASE 4): retry logic, notificador outbound,
email inbound (mock Mailgun/SendGrid) y endpoints de la API."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.db.tenants import TenantManager
from b2b_ai.api.webhooks import (retry_deliver, WebhookNotifier,
                                 EmailWebhook, process_email_inbound)
from b2b_ai.api.app import create_app

API_KEY = "webhook-secret"


def _ok_post(url, payload):
    return 200


def _fail_post(url, payload):
    raise RuntimeError("connection refused")


# ---- retry logic ---------------------------------------------------------
def test_retry_entrega_a_la_primera():
    r = retry_deliver("https://x/h", {"a": 1}, post=_ok_post, delay_fn=lambda a: 0)
    assert r["ok"] is True
    assert r["attempts"] == 1


def test_retry_reintenta_y_falla():
    r = retry_deliver("https://x/h", {"a": 1}, max_attempts=3,
                      post=_fail_post, delay_fn=lambda a: 0)
    assert r["ok"] is False
    assert r["attempts"] == 3
    assert r["last_status"] == "error"


def test_retry_fracasa_y_luego_aprende():
    calls = {"n": 0}

    def flaky(url, payload):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporal")
        return 200

    r = retry_deliver("https://x/h", {}, max_attempts=4,
                      post=flaky, delay_fn=lambda a: 0)
    assert r["ok"] is True
    assert r["attempts"] == 3


# ---- notificador outbound -------------------------------------------------
@pytest.fixture
def wh_env(tmp_path):
    db = Database(str(tmp_path / "webhooks.db"))
    tm = TenantManager(db)
    t = tm.onboard_tenant("Cliente A", "XAXX010101000",
                          webhook_url="https://cliente/hook")
    return db, tm, t["id"]


def test_notifier_entrega_y_bitacora(wh_env):
    db, tm, tid = wh_env
    n = WebhookNotifier(db, post=_ok_post)
    res = n.notify(tid, "invoice_processed", {"invoice_id": 1})
    assert res["ok"] is True
    assert res["delivery_id"] is not None
    d = db.get_webhook_delivery(res["delivery_id"])
    assert d["last_status"] == "delivered"
    assert d["completed_at"] is not None


def test_notifier_sin_webhook_url_no_entrega(tmp_path):
    db = Database(str(tmp_path / "n.db"))
    tm = TenantManager(db)
    t = tm.onboard_tenant("Cliente Sin Webhook")
    n = WebhookNotifier(db, post=_ok_post)
    res = n.notify(t["id"], "invoice_processed", {})
    assert res["ok"] is False
    assert res["reason"] == "no_webhook_url"


def test_notifier_registra_fallo_y_queda_pendiente(wh_env):
    db, tm, tid = wh_env
    n = WebhookNotifier(db, post=_fail_post)
    res = n.notify(tid, "invoice_processed", {})
    assert res["ok"] is False
    pending = db.list_pending_webhook_deliveries(tenant_id=tid)
    assert len(pending) == 1
    assert pending[0]["last_status"] == "error"


# ---- email inbound --------------------------------------------------------
def test_extract_cfdi_base64(sample_papeleria):
    xml = open(sample_papeleria).read()
    b64 = base64.b64encode(xml.encode()).decode()
    eh = EmailWebhook()
    found = eh.extract_cfdi({"attachments": [{"filename": "f.xml",
                                              "content_base64": b64}]})
    assert len(found) == 1
    assert "Comprobante" in found[0]["xml"]


def test_extract_cfdi_ignora_no_xml():
    eh = EmailWebhook()
    found = eh.extract_cfdi({"attachments": [{"filename": "nota.pdf",
                                              "content": "hola"}]})
    assert found == []


def test_extract_cfdi_xml_embebido(sample_papeleria):
    xml = open(sample_papeleria).read()
    found = EmailWebhook().extract_cfdi({"xml": xml})
    assert len(found) == 1


def test_process_email_inbound_pipeline(sample_papeleria, tmp_path):
    db = Database(str(tmp_path / "pi.db"))
    tm = TenantManager(db)
    t = tm.onboard_tenant("Cliente A")
    xml = open(sample_papeleria).read()
    b64 = base64.b64encode(xml.encode()).decode()
    results = process_email_inbound(
        db, {"attachments": [{"filename": "f.xml", "content_base64": b64}]},
        t["id"], send_notifications=False)
    assert len(results) == 1
    assert results[0]["decision"] == "auto_processed"
    assert db.count_invoices(t["id"]) == 1


# ---- API endpoints --------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", "XAXX010101000")
    db.create_api_key(1, "k", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _h():
    return {"X-API-Key": API_KEY}


def test_email_webhook_endpoint(client, sample_consultoria):
    c, db = client
    xml = open(sample_consultoria).read()
    b64 = base64.b64encode(xml.encode()).decode()
    r = c.post("/api/v1/webhooks/email", headers=_h(), json={
        "from": "proveedor@x.com", "subject": "Factura",
        "attachments": [{"filename": "f.xml", "content_base64": b64}],
        "tenant_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["procesadas"] == 1
    assert body["results"][0]["decision"] == "auto_processed"
    assert body["results"][0]["categoria"] == "inversion"


def test_email_webhook_sin_cfdi_422(client):
    c, db = client
    r = c.post("/api/v1/webhooks/email", headers=_h(), json={
        "from": "x@y.com", "subject": "nada", "attachments": []})
    assert r.status_code == 422


def test_email_webhook_requiere_key(client):
    c, db = client
    r = c.post("/api/v1/webhooks/email", json={})
    assert r.status_code == 401


def test_subscribe_y_list_webhook(client):
    c, db = client
    r = c.post("/api/v1/webhooks/subscriptions", headers=_h(),
               json={"url": "https://cliente.com/hook"})
    assert r.status_code == 200
    assert r.json()["webhook_url"] == "https://cliente.com/hook"
    r2 = c.get("/api/v1/webhooks/subscriptions", headers=_h())
    assert r2.json()["webhook_url"] == "https://cliente.com/hook"


def test_subscribe_url_invalida_422(client):
    c, db = client
    r = c.post("/api/v1/webhooks/subscriptions", headers=_h(),
               json={"url": "not-a-url"})
    assert r.status_code == 422


def test_notify_sin_url_409(client):
    c, db = client
    r = c.post("/api/v1/webhooks/notify", headers=_h(),
               json={"event": "invoice_processed", "invoice_id": 1})
    assert r.status_code == 409


def test_onboarding_tenant_endpoint(client):
    c, db = client
    r = c.post("/api/v1/tenants", headers=_h(), json={
        "name": "Cliente Nuevo", "rfc": "ABC123", "erp_type": "csv"})
    assert r.status_code == 200
    tid = r.json()["tenant"]["id"]
    assert tid >= 1
    # aislamiento: la nueva config quedó guardada
    from b2b_ai.db.tenants import TenantManager
    cfg = TenantManager(db).get_config(tid)
    assert cfg["erp_type"] == "csv"


def test_openapi_incluye_webhooks(client):
    c, db = client
    paths = c.get("/openapi.json").json()["paths"]
    assert "/api/v1/webhooks/email" in paths
    assert "/api/v1/webhooks/subscriptions" in paths
    assert "/api/v1/webhooks/notify" in paths
    assert "/api/v1/tenants" in paths
