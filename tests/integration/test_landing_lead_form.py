# -*- coding: utf-8 -*-
"""Integración real: el formulario de leads de landing/index.html llega al
backend público POST /api/v1/leads y se persiste en la base de datos.

Cubre la regresión introducida por el rediseño (commit 32eebcb, "landing
page cloned from usehandle.ai design"): la nueva landing no traía ningún
<form>, así que ningún visitante podía dejar sus datos. Este test verifica,
de punta a punta (HTML servido -> JS servido -> POST -> fila en DB), que
el flujo real funciona.
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from b2b_ai.api.app import create_app
from b2b_ai.db.db import Database


def _client(tmp_path, name):
    db = Database(str(tmp_path / name))
    app = create_app(db)
    return TestClient(app), db


def test_landing_incluye_formulario_de_leads(tmp_path):
    """La landing servida en / trae un <form> con los campos que el backend
    espera (nombre, email) y carga landing.js (que hace el POST real)."""
    c, _db = _client(tmp_path, "l1.db")
    body = c.get("/").text

    assert 'id="leadForm"' in body
    assert re.search(r'<form[^>]*id="leadForm"', body), "falta <form id=\"leadForm\">"
    assert 'name="nombre"' in body
    assert 'name="email"' in body
    # El script que hace el fetch real debe estar enlazado (no inline: la
    # CSP de security_headers.py exige nonce para scripts inline).
    assert '/static/landing.js' in body


def test_landing_js_servido_y_apunta_al_endpoint_real(tmp_path):
    """/static/landing.js existe, se sirve, y su código apunta al endpoint
    público real (no es un alert() de mentiras)."""
    c, _db = _client(tmp_path, "l2.db")
    r = c.get("/static/landing.js")
    assert r.status_code == 200
    js = r.text
    assert "leadForm" in js
    assert "/api/v1/leads" in js
    assert "fetch(" in js


def test_submit_real_del_formulario_persiste_el_lead(tmp_path):
    """Simula exactamente lo que landing.js envía al backend cuando alguien
    llena el <form id="leadForm"> y confirma que el lead queda en la DB
    (mismo tenant público, tabla `leads`), no solo que responde 200."""
    c, db = _client(tmp_path, "l3.db")

    payload = {
        "nombre": "Ana Pérez",
        "email": "ana@despachoperez.mx",
        "despacho": "Despacho Pérez y Asociados",
        "facturas": "100 – 500",
        "mensaje": "",
    }
    r = c.post("/api/v1/leads", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["lead_id"], int)

    # Evidencia de persistencia real: leer directo de la DB, no solo confiar
    # en la respuesta HTTP.
    leads = db.list_leads()
    assert any(
        l["nombre"] == "Ana Pérez" and l["email"] == "ana@despachoperez.mx"
        for l in leads
    ), f"lead no encontrado en DB: {leads}"


def test_submit_sin_nombre_o_email_es_rechazado(tmp_path):
    """Validación de input: nombre/email vacíos -> 422, nada se persiste."""
    c, db = _client(tmp_path, "l4.db")
    r = c.post("/api/v1/leads", json={"nombre": "", "email": "x@y.com"})
    assert r.status_code == 422
    r2 = c.post("/api/v1/leads", json={"nombre": "X", "email": ""})
    assert r2.status_code == 422
    assert db.list_leads() == []


def test_submit_excede_rate_limit_devuelve_429(tmp_path, monkeypatch):
    """Rate limit básico: /api/v1/leads está cubierto por el limiter
    global por IP (`RateLimiter`/`_rate_limit_mw` en b2b_ai/api/app.py,
    activo por defecto). Con B2B_RATE_LIMIT_PER_MIN bajo, el request que
    excede la ventana debe devolver 429 con Retry-After.

    Nota: b2b_ai/api/rate_limiter.py también declara un límite específico
    de 10/min para "/api/v1/leads" vía ENDPOINT_LIMITS, pero ese limiter
    "enterprise" nunca llega a devolver 429 en la práctica —
    `EnterpriseRateLimitMiddleware.dispatch` compara
    `get_usage(key) > effective_limit`, y el backend en memoria nunca deja
    crecer el uso por encima del límite, así que esa comparación jamás es
    cierta (bug preexistente, no introducido por este cambio; no se
    modifica aquí por quedar fuera del alcance de esta tarea). La
    protección real y verificada de este endpoint es el limiter básico
    de abajo.
    """
    monkeypatch.setenv("B2B_RATE_LIMIT_PER_MIN", "5")
    monkeypatch.setenv("B2B_RATE_LIMIT", "on")
    c, _db = _client(tmp_path, "l5.db")
    codes = []
    for i in range(7):
        r = c.post("/api/v1/leads", json={
            "nombre": f"Lead {i}", "email": f"lead{i}@test.mx",
        })
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5, codes
    assert all(x == 429 for x in codes[5:]), codes
    last = c.post("/api/v1/leads", json={"nombre": "X", "email": "x@test.mx"})
    assert last.status_code == 429
    assert last.headers.get("retry-after")
