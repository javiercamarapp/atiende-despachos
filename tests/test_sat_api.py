# -*- coding: utf-8 -*-
"""Tests de los endpoints /api/v1/sat/* (auth + download + verify + schedule)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.sat.api import build_sat_router

API_KEY = "sat-test-key-123"
RFC = "XAXX010101000"


def _auth():
    return {"X-API-Key": API_KEY}


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "sat_api.db"))
    db.create_tenant("Despacho SAT", rfc=RFC)
    db.create_api_key(1, "test-key", API_KEY)
    app = FastAPI()
    app.include_router(build_sat_router(db, _make_require(db)))
    return TestClient(app), db


def _make_require(db):
    from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
    auth = APIKeyAuth(db)
    return make_require_api_key(auth)


def test_sat_sin_key_rechaza(client):
    c, _ = client
    assert c.get("/api/v1/sat/status").status_code == 401
    assert c.post("/api/v1/sat/download", json={}).status_code == 401
    assert c.post("/api/v1/sat/verify", json={}).status_code == 401
    assert c.post("/api/v1/sat/schedule", json={}).status_code == 401


def test_download_ok(client):
    c, _ = client
    r = c.post("/api/v1/sat/download", headers=_auth(), json={
        "rfc": RFC, "ciec": "ciEc123",
        "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-02",
        "tipo": "emitidas"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 4
    assert body["cfdis"][0]["emisor_rfc"] == RFC


def test_download_fechas_invalidas_422(client):
    c, _ = client
    r = c.post("/api/v1/sat/download", headers=_auth(), json={
        "rfc": RFC, "ciec": "x",
        "fecha_inicio": "mal", "fecha_fin": "2026-01-02", "tipo": "emitidas"})
    assert r.status_code == 422


def test_download_login_fallido_400(client):
    c, _ = client
    r = c.post("/api/v1/sat/download", headers=_auth(), json={
        "rfc": "123", "ciec": "x",
        "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-02",
        "tipo": "emitidas"})
    assert r.status_code == 400


def test_verify_ok(client):
    c, _ = client
    r = c.post("/api/v1/sat/verify", headers=_auth(), json={
        "folio_fiscal": "12345678901234567890123456789011"})
    assert r.status_code == 200
    body = r.json()
    assert body["valido"] is True
    assert body["estado"] == "vigente"


def test_verify_no_encontrado_404(client):
    c, _ = client
    r = c.post("/api/v1/sat/verify", headers=_auth(),
               json={"folio_fiscal": "corto"})
    assert r.status_code == 404


def test_status_ok(client):
    c, _ = client
    r = c.get("/api/v1/sat/status", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == 1
    assert "downloader" in body and "scheduler" in body


def test_schedule_requires_tenant(client):
    # key de servicio sin tenant → 400
    import tempfile
    db = Database(tempfile.mktemp(suffix=".db"))
    db.create_api_key(None, "svc", "svc-key")
    app = FastAPI()
    app.include_router(build_sat_router(db, _make_require(db)))
    c = TestClient(app)
    r = c.post("/api/v1/sat/schedule",
               headers={"X-API-Key": "svc-key"},
               json={"rfc": RFC, "ciec": "x", "frequency": "daily"})
    assert r.status_code == 400


def test_schedule_daily_ejecuta_y_persiste(client):
    c, db = client
    r = c.post("/api/v1/sat/schedule", headers=_auth(), json={
        "rfc": RFC, "ciec": "ciEc123", "frequency": "daily"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["frequency"] == "daily"
    assert body["executed"][0]["task"] == "daily"
    assert db.get_tenant_config(1, "sat_schedule_frequency") == "daily"
    assert db.get_tenant_config(1, "sat_rfc") == RFC
    # descarga quedó en ledger
    assert db.get_tenant_config(1, "sat_cfdi_ledger") is not None


def test_schedule_frequency_invalido_422(client):
    c, _ = client
    r = c.post("/api/v1/sat/schedule", headers=_auth(), json={
        "rfc": RFC, "ciec": "x", "frequency": "mensual"})
    assert r.status_code == 422


def test_schedule_sin_rfc_422(client):
    c, _ = client
    r = c.post("/api/v1/sat/schedule", headers=_auth(), json={
        "ciec": "x", "frequency": "daily"})
    assert r.status_code == 422
