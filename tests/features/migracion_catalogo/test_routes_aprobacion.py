# -*- coding: utf-8 -*-
"""
test_routes_aprobacion.py — REQ-MIG-007.

Ejercita el router HTTP real (FastAPI TestClient, sin mocks del código
bajo prueba) de `POST /api/v1/migracion-catalogo/{mapeo_id}/aprobar`,
`/rechazar` y `/editar` -- el mismo patrón que
`tests/adversarial/test_devolucion_iva_payload_tenant_mismatch.py` usa
para otros routers de este repo.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.routes import build_migracion_catalogo_router
from b2b_ai.features.migracion_catalogo.service import MigracionCatalogoService

ORIGEN_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
DESTINO_ID = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"
DESTINO_CORREGIDO_ID = "11111111-2222-3333-4444-555555555555"


async def _auth_dep():
    return {"key": "test-key", "tenant_id": "T1", "user_id": "u1"}


def _mapeo_pendiente(tipo_match=TipoMatchMigracion.FUZZY) -> MapeoMigracionCuenta:
    return MapeoMigracionCuenta(
        origen_cuenta_id=ORIGEN_ID,
        destino_cuenta_id=DESTINO_ID,
        tipo_match=tipo_match,
        score=87.5,
        estado=EstadoMapeoMigracion.PENDIENTE,
    )


def _client_con_mapeo(mapeo: MapeoMigracionCuenta):
    service = MigracionCatalogoService()
    service.registrar(mapeo)
    router = build_migracion_catalogo_router(require_api_key=_auth_dep, service=service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), service


# ---------------------------------------------------------------------------
# El router se niega a construirse sin dependencia de auth.
# ---------------------------------------------------------------------------

def test_build_router_exige_require_api_key():
    import pytest

    with pytest.raises(ValueError):
        build_migracion_catalogo_router(require_api_key=None)


# ---------------------------------------------------------------------------
# POST /aprobar
# ---------------------------------------------------------------------------

def test_aprobar_mueve_pendiente_a_aprobado():
    mapeo = _mapeo_pendiente()
    client, service = _client_con_mapeo(mapeo)

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/aprobar",
        json={"decidido_por": "contador_lider", "nota": "confirmado, misma cuenta"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["estado"] == "aprobado"
    assert body["data"]["aprobado_por"] == "contador_lider"
    assert body["data"]["aprobado_en"] is not None

    # El repositorio del servicio refleja el cambio (mismo objeto que
    # usaría el resto del proceso, p.ej. el motor de migración).
    assert service.obtener(mapeo.id).estado == EstadoMapeoMigracion.APROBADO


def test_aprobar_sin_decidido_por_es_rechazado_por_validacion_de_request():
    mapeo = _mapeo_pendiente()
    client, _ = _client_con_mapeo(mapeo)

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/aprobar",
        json={"decidido_por": ""},
    )
    assert resp.status_code == 422, resp.text


def test_aprobar_dos_veces_falla_con_422_y_no_sobrescribe_la_decision():
    mapeo = _mapeo_pendiente()
    client, service = _client_con_mapeo(mapeo)

    primera = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/aprobar",
        json={"decidido_por": "contador_lider"},
    )
    assert primera.status_code == 200, primera.text

    segunda = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/aprobar",
        json={"decidido_por": "otro_contador"},
    )
    assert segunda.status_code == 422, segunda.text
    # La decisión original no debe haberse sobrescrito.
    assert service.obtener(mapeo.id).aprobado_por == "contador_lider"


def test_aprobar_mapeo_inexistente_da_404():
    _, service = _client_con_mapeo(_mapeo_pendiente())
    router = build_migracion_catalogo_router(require_api_key=_auth_dep, service=service)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/migracion-catalogo/no-existe-este-id/aprobar",
        json={"decidido_por": "contador_lider"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# POST /rechazar
# ---------------------------------------------------------------------------

def test_rechazar_mueve_pendiente_a_rechazado_y_exige_nota():
    mapeo = _mapeo_pendiente()
    client, service = _client_con_mapeo(mapeo)

    sin_nota = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/rechazar",
        json={"decidido_por": "contador_lider", "nota": ""},
    )
    assert sin_nota.status_code == 422, sin_nota.text

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/rechazar",
        json={"decidido_por": "contador_lider", "nota": "las cuentas no son equivalentes"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["estado"] == "rechazado"
    assert service.obtener(mapeo.id).estado == EstadoMapeoMigracion.RECHAZADO


# ---------------------------------------------------------------------------
# POST /editar
# ---------------------------------------------------------------------------

def test_editar_corrige_destino_y_queda_en_estado_editado():
    mapeo = _mapeo_pendiente()
    client, service = _client_con_mapeo(mapeo)

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/editar",
        json={
            "decidido_por": "contador_lider",
            "destino_cuenta_id": DESTINO_CORREGIDO_ID,
            "nota": "el destino correcto es la cuenta de bancos MXN, no USD",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["estado"] == "editado"
    assert data["destino_cuenta_id"] == DESTINO_CORREGIDO_ID

    actualizado = service.obtener(mapeo.id)
    assert actualizado.destino_cuenta_id == DESTINO_CORREGIDO_ID
    assert actualizado.estado == EstadoMapeoMigracion.EDITADO


def test_editar_exige_destino_cuenta_id_no_vacio():
    mapeo = _mapeo_pendiente()
    client, _ = _client_con_mapeo(mapeo)

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo.id}/editar",
        json={"decidido_por": "contador_lider", "destino_cuenta_id": "", "nota": "correccion"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Un mapeo ya con tipo_match=exacto (nacido aprobado por el motor de
# matching, REQ-MIG-003) no puede volver a "aprobarse" por este camino:
# ya no está pendiente.
# ---------------------------------------------------------------------------

def test_no_se_puede_aprobar_un_mapeo_exacto_ya_nacido_aprobado():
    mapeo_exacto = MapeoMigracionCuenta(
        origen_cuenta_id=ORIGEN_ID,
        destino_cuenta_id=DESTINO_ID,
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
    )
    client, _ = _client_con_mapeo(mapeo_exacto)

    resp = client.post(
        f"/api/v1/migracion-catalogo/{mapeo_exacto.id}/aprobar",
        json={"decidido_por": "contador_lider"},
    )
    assert resp.status_code == 422, resp.text
