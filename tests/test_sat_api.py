# -*- coding: utf-8 -*-
"""Tests de los endpoints /api/v1/sat/* (auth + download + verify + schedule).

`/verify` usa SATValidator, que desde FIS-024 hace una llamada SOAP real al
WSDL público del SAT. `client` (sin validador inyectado) solo prueba el
camino fail-closed por falta de rfc_emisor/rfc_receptor/total — nunca toca
la red. `client_sat_simulator` inyecta un SATValidator apuntando al
simulador local (tests/fixtures/sat_consulta_cfdi_simulator.py) para probar
el camino feliz/real sin tocar consultaqr.facturaelectronica.sat.gob.mx.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.sat.api import build_sat_router
from b2b_ai.sat.validator import SATValidator

API_KEY = "sat-test-key-123"
RFC = "XAXX010101000"

SAT_SIM_PORT = 18779
SAT_SIM_URL = f"http://127.0.0.1:{SAT_SIM_PORT}"


def _auth():
    return {"X-API-Key": API_KEY}


@pytest.fixture(scope="module")
def sat_consulta_cfdi_simulator():
    from tests.fixtures.sat_consulta_cfdi_simulator import start_sat_consulta_cfdi_simulator
    server = start_sat_consulta_cfdi_simulator(port=SAT_SIM_PORT)
    yield SAT_SIM_URL
    server.shutdown()


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "sat_api.db"))
    db.create_tenant("Despacho SAT", rfc=RFC)
    db.create_api_key(1, "test-key", API_KEY)
    app = FastAPI()
    app.include_router(build_sat_router(db, _make_require(db)))
    return TestClient(app), db


@pytest.fixture
def client_sat_simulator(tmp_path, sat_consulta_cfdi_simulator):
    """Igual que `client`, pero con SATValidator apuntando al simulador
    local en vez de al servicio real del SAT (nunca red real en tests)."""
    db = Database(str(tmp_path / "sat_api_sim.db"))
    db.create_tenant("Despacho SAT", rfc=RFC)
    db.create_api_key(1, "test-key", API_KEY)
    validator = SATValidator(base_url=sat_consulta_cfdi_simulator)
    app = FastAPI()
    app.include_router(build_sat_router(db, _make_require(db), validator=validator))
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


def test_verify_sin_datos_suficientes_no_toca_red(client):
    """Sin rfc_emisor/rfc_receptor/total, SATValidator falla cerrado antes
    de intentar cualquier llamada de red — nunca un estatus inventado."""
    c, _ = client
    r = c.post("/api/v1/sat/verify", headers=_auth(), json={
        "folio_fiscal": "12345678901234567890123456789011"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["valido"] is False
    assert body["estado"] is None
    assert "rfc_emisor" in body["estatus"]["error"]


def test_verify_ok_contra_simulador(client_sat_simulator):
    c, _ = client_sat_simulator
    r = c.post("/api/v1/sat/verify", headers=_auth(), json={
        "folio_fiscal": "12345678901234567890123456789011",
        "rfc_emisor": "AAA010101AAA", "rfc_receptor": "XAXX010101000",
        "total": 1000.0})
    assert r.status_code == 200
    body = r.json()
    assert body["valido"] is True
    assert body["estado"] == "vigente"
    assert body["estatus"]["simulado"] is False
    assert body["estatus"]["verificado_contra_real"] is False


def test_verify_no_encontrado_404_contra_simulador(client_sat_simulator):
    from tests.fixtures.sat_consulta_cfdi_simulator import FOLIO_NO_ENCONTRADO_TEST
    c, _ = client_sat_simulator
    r = c.post("/api/v1/sat/verify", headers=_auth(), json={
        "folio_fiscal": FOLIO_NO_ENCONTRADO_TEST,
        "rfc_emisor": "AAA010101AAA", "rfc_receptor": "XAXX010101000",
        "total": 1000.0})
    assert r.status_code == 404


def test_verify_cancelado_contra_simulador(client_sat_simulator):
    c, _ = client_sat_simulator
    r = c.post("/api/v1/sat/verify", headers=_auth(), json={
        "folio_fiscal": "12345678901234567890123456789010",  # termina en 0
        "rfc_emisor": "AAA010101AAA", "rfc_receptor": "XAXX010101000",
        "total": 1000.0})
    assert r.status_code == 200
    body = r.json()
    assert body["valido"] is False
    assert body["estado"] == "cancelado"


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
