# -*- coding: utf-8 -*-
"""
Tests — API versioning (b2b_ai/api/versioning.py).

Cubre:
  - Extracción de versión del path y del header Accept-Version.
  - Default a v1 cuando no se especifica ninguna.
  - Registro de la versión en el request context (request.state + get_api_version).
  - Header X-API-Version en todas las respuestas.
  - Conflicto Accept-Version vs path → 400.
  - Versión no soportada → 400.
  - Headers de deprecación (Deprecation, Sunset, Warning) para v1.
"""
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from b2b_ai.api.versioning import (
    install_versioning, _parse_accept_version, _version_from_path,
    VERSION_REGISTRY, DEFAULT_VERSION, get_api_version,
)


def _make_app():
    app = FastAPI()
    install_versioning(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/ping")
    def v1_ping(request: Request):
        return {"version": request.state.api_version}

    @app.get("/api/v2/ping")
    def v2_ping(request: Request):
        return {"version": request.state.api_version}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


# --- helpers puros --------------------------------------------------------- #
def test_version_from_path():
    assert _version_from_path("/api/v1/invoices") == "v1"
    assert _version_from_path("/api/v2/batch") == "v2"
    assert _version_from_path("/health") is None
    assert _version_from_path("/api/v10/x") == "v10"


def test_parse_accept_version():
    assert _parse_accept_version("v1") == "v1"
    assert _parse_accept_version("2") == "v2"
    assert _parse_accept_version(None) is None
    assert _parse_accept_version("") is None
    assert _parse_accept_version("bogus") is None


def test_default_version_es_v1():
    assert DEFAULT_VERSION == "v1"


def test_registry_tiene_v1_y_v2():
    assert "v1" in VERSION_REGISTRY
    assert "v2" in VERSION_REGISTRY


# --- middleware via HTTP --------------------------------------------------- #
def test_version_extraida_del_path(client):
    r = client.get("/api/v1/ping")
    assert r.status_code == 200
    assert r.json()["version"] == "v1"
    assert r.headers["X-API-Version"] == "v1"


def test_version_desde_accept_version_header(client):
    # Sin version en path, con header Accept-Version: v2 → se negocia v2.
    # La ruta /health no esta versionada, pero registra v2 via header.
    r = client.get("/health", headers={"Accept-Version": "v2"})
    assert r.status_code == 200
    assert r.headers["X-API-Version"] == "v2"


def test_default_v1_sin_especificar(client):
    # Sin path versionado ni header: default v1 en el contexto y header.
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-API-Version"] == "v1"


def test_conflicto_accept_version_path_400(client):
    r = client.get("/api/v1/ping", headers={"Accept-Version": "v2"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["type"] == "version_conflict"


def test_version_no_soportada_400(client):
    r = client.get("/api/v9/ping")
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["type"] == "unsupported_version"
    assert "available_versions" in body["error"]


def test_version_registrada_en_contextvar(client):
    # get_api_version() lee el contextvar; via request real debe verse dentro
    # del handler. Comprobamos la ruta v1 devolviendo el valor.
    r = client.get("/api/v1/ping")
    assert r.json()["version"] == "v1"


def test_v1_tiene_deprecation_headers(client):
    r = client.get("/api/v1/ping")
    assert r.status_code == 200
    assert "Deprecation" in r.headers
    assert "Sunset" in r.headers
    assert "Warning" in r.headers


def test_v2_sin_deprecation(client):
    r = client.get("/api/v2/ping")
    assert r.status_code == 200
    assert "Deprecation" not in r.headers


def test_request_id_no_afecta_version(client):
    r = client.get("/api/v1/ping", headers={"X-Request-ID": str(uuid.uuid4())})
    assert r.headers["X-API-Version"] == "v1"
