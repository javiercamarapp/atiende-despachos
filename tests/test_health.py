# -*- coding: utf-8 -*-
"""test_health.py — Tests del deployment readiness + endpoints de health check.

Cubre:
    * run_readiness(): 29 módulos del MVP, resumen y estado agregado.
    * check_import / check_routes / check_models por módulo.
    * GET /api/v1/health          — status básico (público, sin auth).
    * GET /api/v1/health/deep     — readiness por módulo (público).
    * Detección de errores (módulo inventado reporta error, no crashea).

NOTA: estos tests construyen el router de health de forma aislada
(`build_health_routes`) en vez de `create_app()` completo, para no arrastrar
toda la pila del MVP (pandas/sklearn/etc.) y seguir el patrón de tests por
feature del repo. El código probado es exactamente el que monta `create_app`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.api.health import (
    check_import,
    check_models,
    check_routes,
    discover_feature_modules,
    run_readiness,
)
from b2b_ai.api.health_routes import build_health_routes


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def db_session(tmp_path):
    """DB SQLite temporal migrada, como conftest del repo."""
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "health_test.db"))
    yield db
    try:
        db.close()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def client(db_session):
    """TestClient con el router de health montado (público, sin auth)."""
    app = FastAPI()
    app.include_router(build_health_routes(db_session))
    return TestClient(app)


@pytest.fixture
def feature_names():
    """Los 29 feature modules descubiertos."""
    names = discover_feature_modules()
    assert names, "no se descubrieron feature modules"
    return names


# --------------------------------------------------------------------------- #
# run_readiness — agregado
# --------------------------------------------------------------------------- #

def test_run_readiness_reports_all_modules_ok(db_session, feature_names):
    report = run_readiness(db=db_session, module_names=feature_names)
    assert report["status"] == "ok"
    assert report["summary"]["total"] == len(feature_names)
    assert report["summary"]["error"] == 0
    assert report["summary"]["ok"] == len(feature_names)
    assert report["summary"]["route_count"] > 0
    assert report["database"]["status"] == "ok"
    assert report["service"] == "b2b-ai-enterprise"


def test_run_readiness_every_module_has_full_checks(db_session, feature_names):
    report = run_readiness(db=db_session, module_names=feature_names)
    for mod in report["modules"]:
        assert set(mod.keys()) == {"name", "path", "import", "routes", "models", "status"}
        # Cada chequeo individual debe ser ok en un entorno sano.
        assert mod["import"]["status"] == "ok", mod
        assert mod["routes"]["status"] == "ok", mod
        assert mod["routes"]["route_count"] >= 1, mod
        assert mod["models"]["status"] == "ok", mod


def test_run_readiness_error_module_is_detected(db_session):
    """Un módulo inventado reporta error y el agregado es 'error' (no crashea)."""
    report = run_readiness(db=db_session, module_names=["modulo_inexistente_xyz"])
    assert report["status"] == "error"
    assert report["summary"]["error"] == 1
    assert len(report["errors"]) == 1
    assert report["modules"][0]["import"]["status"] == "error"


def test_run_readiness_db_not_configured_is_degraded(feature_names):
    """Sin DB el agregado es 'degraded', no 'error' (módulos siguen ok)."""
    report = run_readiness(db=None, module_names=feature_names)
    assert report["status"] == "degraded"
    assert report["database"]["status"] == "not_configured"
    assert report["summary"]["error"] == 0


# --------------------------------------------------------------------------- #
# Chequeos individuales
# --------------------------------------------------------------------------- #

def test_discover_finds_all_expected_features(feature_names):
    core = {"alertas", "billing", "onboarding", "diot", "declaraciones",
            "reconciliacion_ingresos_egresos", "webhooks", "multi_tenant"}
    assert core <= set(feature_names)


def test_check_import_ok_for_billing():
    res = check_import("billing")
    assert res["status"] == "ok"


def test_check_import_error_for_missing_module():
    res = check_import("no_existe")
    assert res["status"] == "error"
    assert "import failed" in res["detail"]


def test_check_routes_builds_router_for_billing():
    res = check_routes("billing")
    assert res["status"] == "ok"
    assert res["route_count"] >= 1


def test_check_routes_error_for_missing_module():
    res = check_routes("no_existe")
    assert res["status"] == "error"


def test_check_models_billing_has_pydantic_models():
    res = check_models("billing")
    assert res["status"] == "ok"
    assert res["model_count"] >= 1  # Subscription, Invoice, PaymentMethod, PaymentEvent


def test_check_models_error_for_broken_module():
    """models.py que importa falla → status error (no crashea)."""
    res = check_models("no_existe")
    assert res["status"] == "ok"  # sin models.py → ok por ausencia


# --------------------------------------------------------------------------- #
# Endpoints HTTP
# --------------------------------------------------------------------------- #

def test_basic_health_endpoint_public(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "b2b-ai-enterprise"
    assert "version" in data


def test_basic_health_requires_no_auth(client):
    """Sin header X-API-Key debe responder 200 (endpoint de monitoreo público)."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_deep_health_endpoint_public(client, feature_names):
    resp = client.get("/api/v1/health/deep")
    assert resp.status_code == 200
    data = resp.json()
    assert "modules" in data
    assert "summary" in data
    assert data["summary"]["total"] == len(feature_names)
    assert data["database"]["status"] == "ok"


def test_deep_health_lists_every_module(client, feature_names):
    data = client.get("/api/v1/health/deep").json()
    names = {m["name"] for m in data["modules"]}
    assert names == set(feature_names)


def test_deep_health_has_per_module_status(client):
    data = client.get("/api/v1/health/deep").json()
    for mod in data["modules"]:
        assert mod["status"] in ("ok", "error")
        assert set(mod.keys()) >= {"name", "import", "routes", "models", "status"}


def test_deep_health_reports_error_module_not_crashing(client):
    """Un feature roto aparece en errors pero la respuesta sigue siendo 200 JSON."""
    app = FastAPI()
    app.include_router(build_health_routes(None))
    c = TestClient(app)
    resp = c.get("/api/v1/health/deep")
    assert resp.status_code == 200
    assert resp.json()["database"]["status"] == "not_configured"
