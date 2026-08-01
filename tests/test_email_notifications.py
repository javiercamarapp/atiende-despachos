# -*- coding: utf-8 -*-
"""Tests de EmailProvider, plantillas HTML, EmailScheduler y endpoints
POST /email + PUT /preferences."""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.notifications.email_provider import EmailProvider
from b2b_ai.notifications.scheduler import EmailScheduler
from b2b_ai.notifications.templates import (render_html, html_subject,
                                            html_template_path)
from b2b_ai.notifications.api import build_notifications_router

API_KEY = "test-secret-email-123"


def _auth():
    return {"X-API-Key": API_KEY}


def _make_api_key_loader(db):
    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    auth = APIKeyAuth(db)
    return make_require_api_key(auth)


# ---- Plantillas HTML ------------------------------------------------------ #
@pytest.mark.parametrize("name", [
    "welcome", "invoice_processed", "approval_required", "daily_summary",
    "weekly_report", "anomaly_detected", "subscription_renewal",
])
def test_plantillas_html_existen(name):
    assert html_template_path(name) is not None


def test_render_html_rellena_placeholders():
    subj, html = render_html("welcome", {
        "nombre": "Despacho X", "usuario": "Ana", "rfc": "XAXX010101000",
        "plan": "Pro", "fecha": "2026-08-01",
        "url_portal": "https://app/portal", "soporte_email": "s@corp.com"})
    assert "Despacho X" in html
    assert "XAXX010101000" in html
    assert "Despacho X" in subj


def test_render_html_falta_contexto():
    with pytest.raises(ValueError):
        render_html("welcome", {"nombre": "Solo"})


def test_render_html_plantilla_desconocida():
    with pytest.raises(KeyError):
        render_html("no_existe", {})


def test_html_subject_placeholder():
    assert "Despacho X" in html_subject("welcome", {"nombre": "Despacho X"})


# ---- EmailProvider -------------------------------------------------------- #
def test_provider_sin_smtp_simula():
    p = EmailProvider()  # sin B2B_SMTP_HOST → simulado
    assert not p.configured
    r = p.send("a@b.com", "Asunto", "Cuerpo")
    assert r["status"] == "simulado"
    assert len(p.sent) == 1


def test_provider_send_historial():
    p = EmailProvider()
    p.send("a@b.com", "S1", "B1")
    p.send("b@c.com", "S2", "B2")
    assert len(p.sent) == 2


def test_provider_send_vacio_rechaza():
    p = EmailProvider()
    r = p.send("", "S", "B")
    assert r["status"] == "error"


def test_provider_send_template():
    p = EmailProvider()
    r = p.send_template("a@b.com", "welcome", {
        "nombre": "X", "usuario": "U", "rfc": "R", "plan": "P",
        "fecha": "2026", "url_portal": "#", "soporte_email": "s@c.com"})
    assert r["status"] == "simulado"
    assert r["template"] == "welcome"
    assert r["html"] is True


def test_provider_send_template_sin_destino():
    p = EmailProvider(default_recipient=None)
    r = p.send_template(None, "welcome", {
        "nombre": "X", "usuario": "U", "rfc": "R", "plan": "P",
        "fecha": "2026", "url_portal": "#", "soporte_email": "s@c.com"})
    assert r["status"] == "error"


def test_provider_send_bulk():
    p = EmailProvider()
    out = p.send_bulk(["a@b.com", "c@d.com", ""], "Asunto", "Cuerpo")
    assert out["simulated"] == 2
    assert out["failed"] == 1
    assert len(out["results"]) == 3


def test_provider_attachments_por_bytes():
    p = EmailProvider()
    r = p.send("a@b.com", "S", "B", attachments=[("f.txt", b"contenido")])
    assert r["status"] == "simulado"
    assert r["attachments"] == 1


def test_provider_attachment_por_ruta():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-fake")
        path = f.name
    try:
        p = EmailProvider()
        r = p.send("a@b.com", "S", "B", attachments=[path])
        assert r["attachments"] == 1
    finally:
        os.remove(path)


# ---- EmailScheduler ------------------------------------------------------- #
def test_scheduler_email_envia_y_vacia_cola():
    p = EmailProvider()
    sched = EmailScheduler(provider=p, max_retries=1)
    sched.enqueue("a@b.com", "Asunto", "Cuerpo")
    sched.enqueue("c@d.com", "Asunto2", "Cuerpo2")
    assert sched.pending() == 2
    sent = sched.process_once()
    assert sent == 2
    assert sched.pending() == 0
    assert len(p.sent) == 2
    assert sched.stats()["sent"] == 2


def test_scheduler_email_template():
    p = EmailProvider()
    sched = EmailScheduler(provider=p)
    sched.enqueue("a@b.com", "", template="welcome", context={
        "nombre": "X", "usuario": "U", "rfc": "R", "plan": "P",
        "fecha": "2026", "url_portal": "#", "soporte_email": "s@c.com"})
    sched.process_once()
    assert len(p.sent) == 1
    assert p.sent[0]["html"] is True


def test_scheduler_email_retry_agota():
    class AlwaysFail:
        configured = True

        def send(self, *a, **k):
            return {"status": "error", "message": "smtp down"}

    sched = EmailScheduler(provider=AlwaysFail(), max_retries=1,
                           retry_backoff_seconds=0.0)
    sched.enqueue("a@b.com", "S", "B")
    sched.process_once()
    assert sched.failed_count == 1
    assert sched.pending() == 0


def test_scheduler_daily_programa_futuro():
    sched = EmailScheduler(provider=EmailProvider())
    msg = sched.schedule_daily("a@b.com", "daily_summary", {
        "nombre": "X", "fecha": "2026", "facturas": "1", "monto_total": "1",
        "pendientes": "0", "anomalias": "0", "soporte_email": "s@c.com"},
        hour=23, minute=59)
    assert msg.run_at is not None
    assert msg.due is False  # no vence aún (próxima ocurrencia)
    assert sched.pending() == 1


def test_scheduler_weekly_programa_futuro():
    sched = EmailScheduler(provider=EmailProvider())
    msg = sched.schedule_weekly("a@b.com", "weekly_report", {
        "nombre": "X", "periodo": "2026-W31", "facturas": "1", "total": "1",
        "aprobadas": "1", "pendientes": "0", "soporte_email": "s@c.com"},
        weekday=0, hour=9, minute=0)
    assert msg.run_at is not None
    assert sched.pending() == 1


def test_next_daily_calcula_hora():
    from datetime import datetime
    # hoy 10:00, programar 08:00 → mañana 08:00
    n = EmailScheduler._next_daily(8, 0, datetime(2026, 7, 31, 10, 0))
    assert (n.hour, n.minute) == (8, 0)
    assert n.date() != datetime(2026, 7, 31).date()


# ---- API endpoints -------------------------------------------------------- #
@pytest.fixture
def email_client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = FastAPI()
    app.include_router(build_notifications_router(db, _make_api_key_loader(db)))
    return TestClient(app), db


def test_email_sin_key_rechaza(email_client):
    c, _ = email_client
    assert c.post("/api/v1/notifications/email", json={}).status_code == 401
    assert c.put("/api/v1/notifications/preferences",
                 json={}).status_code == 401


def test_email_sin_to_rechaza(email_client):
    c, _ = email_client
    r = c.post("/api/v1/notifications/email", headers=_auth(),
               json={"subject": "S", "body": "B"})
    assert r.status_code == 422


def test_email_envia_y_persiste(email_client):
    c, db = email_client
    r = c.post("/api/v1/notifications/email", headers=_auth(), json={
        "to": "a@b.com", "subject": "Hola", "body": "Cuerpo"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["sent"] is True
    rows = db.list_notifications(tenant_id=1)
    assert len(rows) == 1
    assert rows[0]["channel"] == "email"


def test_email_plantilla_ok(email_client):
    c, db = email_client
    r = c.post("/api/v1/notifications/email", headers=_auth(), json={
        "to": "a@b.com", "template": "welcome", "context": {
            "nombre": "X", "usuario": "U", "rfc": "R", "plan": "P",
            "fecha": "2026", "url_portal": "#", "soporte_email": "s@c.com"}})
    assert r.status_code == 200
    assert "Bienvenido" in r.json()["subject"]


def test_email_plantilla_desconocida(email_client):
    c, _ = email_client
    r = c.post("/api/v1/notifications/email", headers=_auth(), json={
        "to": "a@b.com", "template": "no_existe"})
    assert r.status_code == 422


def test_email_schedule_invalido(email_client):
    c, _ = email_client
    r = c.post("/api/v1/notifications/email", headers=_auth(), json={
        "to": "a@b.com", "subject": "S", "schedule_at": "no-fecha"})
    assert r.status_code == 422


def test_email_programado_encola(email_client):
    c, db = email_client
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(days=1)).isoformat()
    r = c.post("/api/v1/notifications/email", headers=_auth(), json={
        "to": "a@b.com", "subject": "Futuro", "schedule_at": future})
    assert r.status_code == 200
    assert r.json()["queued"] is True
    assert r.json()["sent"] is False
    rows = db.list_notifications(tenant_id=1)
    assert rows[0]["status"] == "queued"


def test_preferences_guarda(email_client):
    c, db = email_client
    r = c.put("/api/v1/notifications/preferences", headers=_auth(), json={
        "channel": "email", "digest": "daily", "digest_time": "08:30",
        "weekly_weekday": 1, "email": "ana@corp.com"})
    assert r.status_code == 200
    assert set(r.json()["updated"]) == {"notif_pref_channel",
                                        "notif_pref_digest",
                                        "notif_pref_digest_time",
                                        "notif_pref_weekly_weekday",
                                        "notif_pref_email"}
    assert db.get_tenant_config(1, "notif_pref_digest") == "daily"
    assert db.get_tenant_config(1, "notif_pref_email") == "ana@corp.com"


def test_preferences_validacion(email_client):
    c, _ = email_client
    assert c.put("/api/v1/notifications/preferences", headers=_auth(),
                 json={"digest": "mensual"}).status_code == 422
    assert c.put("/api/v1/notifications/preferences", headers=_auth(),
                 json={"digest_time": "25:99"}).status_code == 422
    assert c.put("/api/v1/notifications/preferences", headers=_auth(),
                 json={"weekly_weekday": 9}).status_code == 422
    assert c.put("/api/v1/notifications/preferences", headers=_auth(),
                 json={}).status_code == 422


def test_preferences_sin_tenant_devuelve_400():
    import tempfile as tf
    db = Database(tf.mktemp(suffix=".db"))
    db.create_api_key(None, "svc", "svc-key")
    app = FastAPI()
    app.include_router(build_notifications_router(db, _make_api_key_loader(db)))
    c = TestClient(app)
    r = c.put("/api/v1/notifications/preferences",
              headers={"X-API-Key": "svc-key"}, json={"channel": "email"})
    assert r.status_code == 400


# ---- Integración create_app ----------------------------------------------- #
def test_create_app_expone_endpoints(tmp_path):
    db = Database(str(tmp_path / "full.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    c = TestClient(app)
    assert c.get("/api/v1/notifications/history",
                 headers=_auth()).status_code == 200
    assert c.put("/api/v1/notifications/preferences", headers=_auth(),
                 json={"channel": "email"}).status_code == 200
