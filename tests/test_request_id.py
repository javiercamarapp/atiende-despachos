# -*- coding: utf-8 -*-
"""
Tests — Request ID tracking (b2b_ai/api/request_id.py).

Cubre:
  - Generación de UUID4 como X-Request-ID si el cliente no lo envía.
  - Reutilización del X-Request-ID entrante.
  - Header X-Request-ID presente en TODAS las respuestas (incluidos errores).
  - request_id en request.state (accesible en handlers).
  - request_id en el body de respuestas de error (integración errors.py).
  - contextvar get_request_id().
"""
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from b2b_ai.api.request_id import (
    install_request_id, get_request_id, generate_request_id, REQUEST_ID_HEADER,
)
from b2b_ai.api.errors import install_error_handlers


def _make_app():
    app = FastAPI()
    install_request_id(app)
    install_error_handlers(app)

    @app.get("/ok")
    def ok(request: Request):
        # Devolver el request_id registrado en state para verificarlo.
        return {"request_id": request.state.request_id}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")  # dispara el exception handler 500

    return app


@pytest.fixture
def client():
    # raise_server_exceptions=False para poder testear respuestas de error (500).
    return TestClient(_make_app(), raise_server_exceptions=False)


def test_genera_uuid4_si_no_se_envia(client):
    r = client.get("/ok")
    assert r.status_code == 200
    rid = r.headers[REQUEST_ID_HEADER]
    # UUID4 válido (formato canónico con guiones).
    uuid.UUID(rid)
    assert r.json()["request_id"] == rid


def test_reutiliza_header_entrante(client):
    sent = str(uuid.uuid4())
    r = client.get("/ok", headers={REQUEST_ID_HEADER: sent})
    assert r.status_code == 200
    assert r.headers[REQUEST_ID_HEADER] == sent
    assert r.json()["request_id"] == sent


def test_request_id_en_respuesta_de_error(client):
    r = client.get("/boom")
    assert r.status_code == 500
    assert REQUEST_ID_HEADER in r.headers
    rid = r.headers[REQUEST_ID_HEADER]
    # request_id en el body JSON de error (integración errors.py).
    assert r.json()["error"]["request_id"] == rid


def test_request_id_en_state_y_contextvar(client):
    rid = str(uuid.uuid4())
    r = client.get("/ok", headers={REQUEST_ID_HEADER: rid})
    assert r.status_code == 200
    assert r.json()["request_id"] == rid
    # El contextvar queda reseteado al terminar el request (aislamiento).
    assert get_request_id() == ""


def test_ids_aislados_entre_requests(client):
    r1 = client.get("/ok")
    r2 = client.get("/ok")
    assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]


def test_generate_request_id_formato():
    rid = generate_request_id()
    assert len(rid) == 36
    uuid.UUID(rid)
