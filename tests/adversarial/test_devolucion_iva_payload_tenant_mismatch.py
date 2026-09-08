# -*- coding: utf-8 -*-
"""
REQ-IVA-018 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "El endpoint `POST /api/v1/devolucion-iva/conciliar` debe rechazar
  (HTTP 422) una solicitud cuyo `tenant_id` del token no coincida con el
  `tenant_id` de las facturas/DIOT/declaraciones enviadas en el body,
  para blindar el aislamiento multi-tenant también a nivel de payload,
  no solo de lectura (complementa REQ-IVA-007)."

Antes del fix, `conciliar()` pasaba `req.facturas`/`req.diot_entries`/
`req.declaraciones` directo al servicio sin comparar nada contra el
tenant del token: un tenant autenticado como "A" podía enviar un body
con registros marcados `tenant_id="B"` (o un `tenant_id` de request
completo distinto al suyo) y el endpoint los conciliaba igual — una
fuga/mezcla multi-tenant a nivel de escritura, distinta de la de
REQ-IVA-007 (que es sobre `listar_solicitudes`, una lectura).

Este archivo ejercita el router HTTP real (FastAPI TestClient, sin
mocks del código bajo prueba) con una dependencia de auth fake que
únicamente fija el `tenant_id` del token — exactamente el mismo patrón
que `tests/test_tenant_isolation_fixes.py` usa para los P1 de
aislamiento por tenant ya corregidos en el repo.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router


def _auth_for(tenant_id):
    """Dependencia de auth fake: token fijo con el tenant_id indicado.

    `tenant_id=None` simula un token sin tenant (contexto administrativo/
    legado) — no debe usarse en los casos que sí esperan una
    autenticación con tenant real.
    """
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _client(tenant_id):
    router = build_devolucion_iva_router(db=None, require_api_key=_auth_for(tenant_id))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _factura(tenant_id=None, **overrides) -> dict:
    d = {
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "rfc_emisor": "EMP850101AB1",
        "rfc_receptor": "REC850101CD2",
        "fecha": "2026-01-15",
        "subtotal": 10000.0,
        "iva": 1600.0,
        "total": 11600.0,
    }
    if tenant_id is not None:
        d["tenant_id"] = tenant_id
    d.update(overrides)
    return d


def _diot_entry(tenant_id=None, **overrides) -> dict:
    d = {
        "rfc_tercero": "EMP850101AB1",
        "nombre": "Proveedor SA de CV",
        "monto_neto": 10000.0,
        "iva_trasladado": 1600.0,
        "iva_acreditable": 1600.0,
    }
    if tenant_id is not None:
        d["tenant_id"] = tenant_id
    d.update(overrides)
    return d


def _declaracion(tenant_id=None, **overrides) -> dict:
    d = {
        "mes": 1,
        "año": 2026,
        "iva_cobrado": 0.0,
        "iva_pagado": 1600.0,
    }
    if tenant_id is not None:
        d["tenant_id"] = tenant_id
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# Casos que deben rechazarse con 422
# ---------------------------------------------------------------------------

def test_conciliar_rechaza_factura_de_otro_tenant_en_el_body():
    """Token de tenant "A"; una factura del body está marcada "B"."""
    client = _client("A")
    payload = {
        "facturas": [_factura(tenant_id="B")],
        "diot_entries": [],
        "declaraciones": [],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 422, resp.text
    assert "tenant_id" in resp.json()["detail"]


def test_conciliar_rechaza_diot_entry_de_otro_tenant_en_el_body():
    client = _client("A")
    payload = {
        "facturas": [],
        "diot_entries": [_diot_entry(tenant_id="B")],
        "declaraciones": [],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 422, resp.text


def test_conciliar_rechaza_declaracion_de_otro_tenant_en_el_body():
    client = _client("A")
    payload = {
        "facturas": [],
        "diot_entries": [],
        "declaraciones": [_declaracion(tenant_id="B")],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 422, resp.text


def test_conciliar_rechaza_tenant_id_de_request_completo_distinto():
    """El campo `tenant_id` a nivel de request completo también cuenta,
    no solo el de cada item individual."""
    client = _client("A")
    payload = {
        "tenant_id": "B",
        "facturas": [_factura()],
        "diot_entries": [],
        "declaraciones": [],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 422, resp.text


def test_conciliar_rechaza_aunque_solo_un_item_de_varios_sea_ajeno():
    """Basta con que UN registro del body sea de otro tenant para
    rechazar toda la solicitud, aunque el resto sí sea del tenant A."""
    client = _client("A")
    payload = {
        "facturas": [
            _factura(tenant_id="A"),
            _factura(uuid="11111111-2222-3333-4444-555555555555", tenant_id="B"),
        ],
        "diot_entries": [],
        "declaraciones": [],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Casos que deben aceptarse (no regresión)
# ---------------------------------------------------------------------------

def test_conciliar_acepta_cuando_todo_el_body_es_del_mismo_tenant():
    client = _client("A")
    payload = {
        "tenant_id": "A",
        "facturas": [_factura(tenant_id="A")],
        "diot_entries": [_diot_entry(tenant_id="A")],
        "declaraciones": [_declaracion(tenant_id="A")],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_conciliar_acepta_cuando_el_body_no_declara_tenant_id():
    """Uso normal actual: ni el request completo ni los items individuales
    traen `tenant_id` — no hay nada que comparar, no debe rechazarse
    (evita romper el flujo existente de /conciliar)."""
    client = _client("A")
    payload = {
        "facturas": [_factura()],
        "diot_entries": [_diot_entry()],
        "declaraciones": [_declaracion()],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 200, resp.text


def test_conciliar_sin_tenant_id_en_el_token_no_rechaza_nada():
    """Sin tenant en el token (contexto administrativo/legado) no hay
    tenant de referencia contra el cual comparar; mismo criterio que
    `listar_solicitudes()` sin filtro (REQ-IVA-007)."""
    client = _client(None)
    payload = {
        "tenant_id": "B",
        "facturas": [_factura(tenant_id="C")],
        "diot_entries": [],
        "declaraciones": [],
    }
    resp = client.post("/api/v1/devolucion-iva/conciliar", json=payload)
    assert resp.status_code == 200, resp.text
