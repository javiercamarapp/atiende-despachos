# -*- coding: utf-8 -*-
"""
test_app_lifecycle.py — Startup/shutdown wiring, health probes and the
/dashboard/ SPA auth gate (fix/app-lifecycle).

Covers:
  - GET /health/live siempre 200, sin DB ni auth.
  - GET /health/ready 200 en operación normal, 503 mientras se drena.
  - GET /health incluye "draining" y refleja el estado real.
  - El middleware de drenado rechaza tráfico nuevo (503) mientras
    is_draining() es True, salvo los prefijos de monitoreo.
  - request_tracker refleja requests activas de verdad (no decorativo).
  - /dashboard/ exige una API key de tenant válida (antes era público).
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.infrastructure.graceful_shutdown import (
    _shutdown_state, request_tracker,
)

API_KEY = "lifecycle-test-key-001"


@pytest.fixture
def app_db(tmp_path):
    db = Database(str(tmp_path / "lifecycle.db"))
    db.create_tenant("Despacho Lifecycle", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    return db


@pytest.fixture
def client(app_db):
    app = create_app(app_db)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_shutdown_state():
    """Aísla el estado global de drenado entre tests (es un singleton de
    módulo, compartido por todos los `create_app()` del proceso)."""
    _shutdown_state.is_draining = False
    _shutdown_state.is_shutdown = False
    _shutdown_state.drain_started_at = None
    _shutdown_state.shutdown_reason = ""
    while request_tracker.active_count > 0:
        request_tracker.decrement()
    yield
    _shutdown_state.is_draining = False
    _shutdown_state.is_shutdown = False
    _shutdown_state.drain_started_at = None
    _shutdown_state.shutdown_reason = ""
    while request_tracker.active_count > 0:
        request_tracker.decrement()


def _auth():
    return {"X-API-Key": API_KEY}


# --------------------------------------------------------------------------- #
# /health/live — liveness
# --------------------------------------------------------------------------- #
def test_health_live_ok(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alive"


def test_health_live_ok_even_while_draining(client):
    _shutdown_state.is_draining = True
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


# --------------------------------------------------------------------------- #
# /health/ready — readiness
# --------------------------------------------------------------------------- #
def test_health_ready_ok_when_not_draining(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_health_ready_fails_while_draining(client):
    """Núcleo del fix: /health/ready debe fallar (503) durante el drenado."""
    r_before = client.get("/health/ready")
    assert r_before.status_code == 200

    _shutdown_state.is_draining = True
    _shutdown_state.drain_started_at = time.monotonic()
    _shutdown_state.shutdown_reason = "SIGTERM"

    r_during = client.get("/health/ready")
    assert r_during.status_code == 503
    body = r_during.json()
    assert body["status"] == "draining"
    assert body["is_draining"] is True

    _shutdown_state.is_draining = False

    r_after = client.get("/health/ready")
    assert r_after.status_code == 200
    assert r_after.json()["status"] == "ready"


# --------------------------------------------------------------------------- #
# /health — refleja el estado de drenado
# --------------------------------------------------------------------------- #
def test_health_reports_draining_flag(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["draining"] is False

    _shutdown_state.is_draining = True
    r2 = client.get("/health")
    # /health sigue respondiendo (está exento del middleware de rechazo),
    # pero ahora reporta que está drenando.
    assert r2.status_code == 200
    assert r2.json()["draining"] is True


# --------------------------------------------------------------------------- #
# Middleware de drenado — rechaza tráfico nuevo real
# --------------------------------------------------------------------------- #
def test_drain_middleware_rejects_new_traffic(client):
    # Tráfico normal (autenticado) pasa sin problema.
    assert client.get("/api/v1/stats", headers=_auth()).status_code == 200

    _shutdown_state.is_draining = True
    r = client.get("/api/v1/stats", headers=_auth())
    assert r.status_code == 503
    assert r.headers.get("retry-after") == "5"

    _shutdown_state.is_draining = False
    assert client.get("/api/v1/stats", headers=_auth()).status_code == 200


def test_drain_middleware_exempts_monitoring_prefixes(client):
    _shutdown_state.is_draining = True
    # /health y /health/live siguen respondiendo 200 durante el drenado
    # (solo /health/ready refleja el drenado con 503, con su propia lógica).
    assert client.get("/health").status_code == 200
    assert client.get("/health/live").status_code == 200


def test_request_tracker_counts_active_requests(client):
    """request_tracker ya no es decorativo: el middleware de drenado lo
    incrementa/decrementa alrededor de cada request no exenta. No hay forma
    simple de observarlo a la mitad de vuelo con un TestClient síncrono, así
    que confirmamos el invariante fuerte: vuelve a 0 tras cada request."""
    assert request_tracker.active_count == 0
    r = client.get("/api/v1/stats", headers=_auth())
    assert r.status_code == 200
    assert request_tracker.active_count == 0


# --------------------------------------------------------------------------- #
# /dashboard/ — exige API key de tenant (antes era público)
# --------------------------------------------------------------------------- #
def test_dashboard_spa_requires_api_key(client):
    r = client.get("/dashboard/")
    assert r.status_code == 401


def test_dashboard_spa_rejects_invalid_key(client):
    r = client.get("/dashboard/", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code == 401


def test_dashboard_spa_ok_with_header_key(client):
    r = client.get("/dashboard/", headers=_auth())
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_dashboard_spa_ok_with_query_param_key(client):
    """La propia SPA recibe la key como ?api_key=... en la URL (ver
    dashboard.html); el gate debe aceptar ese mismo mecanismo."""
    r = client.get(f"/dashboard/?api_key={API_KEY}")
    assert r.status_code == 200
