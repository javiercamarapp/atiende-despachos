# -*- coding: utf-8 -*-
"""Tests de los endpoints /api/v1/notifications/* (auth + envío + historial)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.notifications.api import build_notifications_router
from b2b_ai.notifications.scheduler import NotificationScheduler
from b2b_ai.notifications.whatsapp import MockWhatsApp

API_KEY = "test-secret-notif-123"


def _make_api_key_loader(db):
    """Crea una dependencia require_api_key mínima para el router aislado."""
    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    auth = APIKeyAuth(db)
    return make_require_api_key(auth)


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    app = create_app(db)
    return TestClient(app), db


@pytest.fixture
def router_client(tmp_path):
    """App aislada con el router de notificaciones + scheduler mock inyectado."""
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    wa = MockWhatsApp()
    sched = NotificationScheduler(wa=wa)
    app = FastAPI()
    app.include_router(build_notifications_router(
        db, _make_api_key_loader(db), scheduler=sched))
    return TestClient(app), db, sched, wa


def _auth():
    return {"X-API-Key": API_KEY}


# ---- auth ----------------------------------------------------------------- #
def test_notifications_sin_key_rechaza(client):
    c, _ = client
    assert c.get("/api/v1/notifications/history").status_code == 401
    assert c.post("/api/v1/notifications/send", json={}).status_code == 401


# ---- send ----------------------------------------------------------------- #
def test_send_envia_y_persiste(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/send", headers=_auth(), json={
        "recipient": "+5215512345678", "message": "Hola", "template": "exception"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued"] is True
    rows = db.list_notifications(tenant_id=1)
    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
    sched.process_once()
    assert len(wa.messages) == 1
    assert wa.messages[0]["text"] == "Hola"


def test_send_sin_recipiente_rechaza(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/send", headers=_auth(),
               json={"message": "sin tel"})
    assert r.status_code == 422


def test_send_plantilla_desconocida_rechaza(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/send", headers=_auth(),
               json={"recipient": "+5215512345678",
                     "template": "no_existe"})
    assert r.status_code == 422


def test_send_schedule_invalido_rechaza(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/send", headers=_auth(),
               json={"recipient": "+5215512345678", "message": "x",
                     "schedule_at": "no-fecha"})
    assert r.status_code == 422


def test_send_diferido_no_se_envia_aun(router_client):
    c, db, sched, wa = router_client
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(days=1)).isoformat()
    r = c.post("/api/v1/notifications/send", headers=_auth(), json={
        "recipient": "+5215512345678", "message": "futuro",
        "schedule_at": future})
    assert r.status_code == 200
    sched.process_once()
    assert len(wa.messages) == 0  # diferido → aún en cola


# ---- history -------------------------------------------------------------- #
def test_history_vacio(client):
    c, db = client
    r = c.get("/api/v1/notifications/history", headers=_auth())
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_history_muestra_envios(router_client):
    c, db, sched, wa = router_client
    c.post("/api/v1/notifications/send", headers=_auth(),
           json={"recipient": "+5215512345678", "message": "A"})
    c.post("/api/v1/notifications/send", headers=_auth(),
           json={"recipient": "+5215512345678", "message": "B"})
    r = c.get("/api/v1/notifications/history", headers=_auth())
    assert r.status_code == 200
    assert r.json()["count"] == 2


# ---- config --------------------------------------------------------------- #
def test_config_guarda_y_lee(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/config", headers=_auth(), json={
        "recipient": "+5215512345678", "whatsapp_token": "tok-secreto",
        "whatsapp_phone_number_id": "1234567890"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert set(r.json()["updated"]) == {"recipient", "whatsapp_token",
                                        "whatsapp_phone_number_id"}
    assert db.get_tenant_config(1, "notif_recipient") == "+5215512345678"
    assert db.get_tenant_config(1, "whatsapp_token") == "tok-secreto"


def test_config_sin_campos_rechaza(router_client):
    c, db, sched, wa = router_client
    r = c.post("/api/v1/notifications/config", headers=_auth(), json={})
    assert r.status_code == 422


def test_config_es_scoped_por_tenant(client):
    """La key de tenant 1 solo ve/guarda su propio config (no crashea)."""
    c, db = client
    r = c.post("/api/v1/notifications/config", headers=_auth(),
               json={"recipient": "+5215512345678"})
    assert r.status_code == 200
    assert db.get_tenant_config(1, "notif_recipient") == "+5215512345678"


def test_config_sin_tenant_devuelve_400():
    """Una key de servicio (sin tenant) no puede guardar config de tenant."""
    import tempfile

    from fastapi import FastAPI
    from fastapi.testclient import TestClient as TC

    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    from b2b_ai.db.db import Database
    from b2b_ai.notifications.api import build_notifications_router
    from b2b_ai.notifications.scheduler import NotificationScheduler
    from b2b_ai.notifications.whatsapp import MockWhatsApp

    db = Database(tempfile.mktemp(suffix=".db"))
    db.create_api_key(None, "service-key", "svc-key")  # tenant=None
    auth = APIKeyAuth(db)
    require = make_require_api_key(auth)
    sched = NotificationScheduler(wa=MockWhatsApp())
    app = FastAPI()
    app.include_router(build_notifications_router(db, require, scheduler=sched))
    c = TC(app)
    r = c.post("/api/v1/notifications/config",
               headers={"X-API-Key": "svc-key"},
               json={"recipient": "+5215512345678"})
    assert r.status_code == 400
