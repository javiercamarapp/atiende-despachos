# -*- coding: utf-8 -*-
"""
REQ-IVA-006 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "`DevolucionIVAService` debe leer/escribir `_solicitudes`, `_status` y
  `_papeles_trabajo` desde las tablas de REQ-IVA-005 en vez de dicts de
  proceso; verificable reiniciando el proceso entre el `POST` de creación
  y el `GET` de consulta y confirmando que la solicitud sigue existiendo
  (hoy se perdería)."

Antes del fix, `_solicitudes`/`_status`/`_papeles_trabajo` eran dicts a
nivel de módulo de `b2b_ai/features/devolucion_iva/service.py`: cualquier
reinicio del proceso Python (deploy, crash, restart de un worker) borraba
por completo las solicitudes de devolución de IVA ya presentadas.

No se puede reiniciar el intérprete de Python real dentro de un mismo test
de pytest, así que "reinicio del proceso" se simula de la única forma
honesta posible sin mocks: creando una `Database` (conexión SQLite) NUEVA
apuntando al MISMO archivo en disco, y una `DevolucionIVAService`/router
NUEVO sobre ella — si los datos sólo vivieran en un dict de Python, esta
segunda instancia jamás los vería (justo el bug que describía el
criterio); si viven en la tabla del archivo, sí. Esto ejercita el
servicio real (sin mocks) tanto a nivel de `DevolucionIVAService` como del
router HTTP end-to-end.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.features.devolucion_iva.models import (
    EstatusDevolucion,
    FacturaCFDI,
    PapelTrabajo,
)
from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router
from b2b_ai.features.devolucion_iva.service import DevolucionIVAService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_for(tenant_id):
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _client(db, tenant_id="T1"):
    router = build_devolucion_iva_router(db=db, require_api_key=_auth_for(tenant_id))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Nivel servicio: dos `DevolucionIVAService` distintos sobre el mismo
# archivo simulan dos "procesos" (dos conexiones SQLite independientes).
# ---------------------------------------------------------------------------

def test_solicitud_sobrevive_reinicio_del_proceso_via_service(tmp_path):
    db_path = str(tmp_path / "devolucion_iva.db")

    # "Proceso 1": crea y registra la solicitud.
    db_proceso_1 = Database(db_path)
    svc_1 = DevolucionIVAService(db=db_proceso_1)
    sol = svc_1.preparar_solicitud(
        "2026-01",
        {"monto_devolucion_sugerido": 5000.0},
        cuenta_banco="Banorte",
        clabe="072180001234567897",
        tenant_id="T1",
    )
    svc_1.registrar(sol)

    # Nada de `db_proceso_1`/`svc_1` sobrevive de aquí en adelante: se
    # simula un reinicio real abriendo una conexión y un servicio nuevos
    # contra el mismo archivo.
    del svc_1
    del db_proceso_1

    db_proceso_2 = Database(db_path)
    svc_2 = DevolucionIVAService(db=db_proceso_2)

    status = svc_2.consultar_status(sol.solicitud_id)
    assert status is not None, (
        "La solicitud se perdió al 'reiniciar' el proceso — "
        "REQ-IVA-006 no está persistiendo en DB."
    )
    assert status.status == EstatusDevolucion.PENDIENTE
    assert status.fecha_presentacion == sol.created_at[:10]

    reporte = svc_2.generar_reporte(sol.solicitud_id)
    assert reporte is not None
    assert reporte["solicitud_id"] == sol.solicitud_id
    assert reporte["periodo"] == "2026-01"
    assert reporte["monto_solicitado"] == 5000.0
    assert reporte["cuenta_banco"] == "Banorte"

    items = svc_2.listar(tenant_id="T1")
    assert len(items) == 1
    assert items[0]["solicitud_id"] == sol.solicitud_id


def test_solicitud_no_visible_en_base_distinta(tmp_path):
    """Control negativo: si el 'proceso 2' apunta a OTRO archivo, no debe
    ver nada — confirma que la persistencia es real (por archivo/base),
    no un singleton de Python que hiciera pasar cualquier instancia."""
    db_a = Database(str(tmp_path / "a.db"))
    db_b = Database(str(tmp_path / "b.db"))

    svc_a = DevolucionIVAService(db=db_a)
    sol = svc_a.preparar_solicitud(
        "2026-02", {"monto_devolucion_sugerido": 1000.0}, tenant_id="T1",
    )
    svc_a.registrar(sol)

    svc_b = DevolucionIVAService(db=db_b)
    assert svc_b.consultar_status(sol.solicitud_id) is None
    assert svc_b.listar() == []


def test_actualizar_status_persiste_entre_instancias(tmp_path):
    db_path = str(tmp_path / "devolucion_iva.db")

    svc_1 = DevolucionIVAService(db=Database(db_path))
    sol = svc_1.preparar_solicitud(
        "2026-01", {"monto_devolucion_sugerido": 25000.0}, tenant_id="T1",
    )
    svc_1.registrar(sol)
    svc_1.actualizar_status(
        sol.solicitud_id,
        EstatusDevolucion.APROBADA,
        fecha_respuesta="2026-03-01",
        monto_aprobado=25000.0,
        observaciones="Aprobada sin observaciones.",
    )
    del svc_1

    svc_2 = DevolucionIVAService(db=Database(db_path))
    status = svc_2.consultar_status(sol.solicitud_id)
    assert status.status == EstatusDevolucion.APROBADA
    assert status.fecha_respuesta == "2026-03-01"
    assert status.monto_aprobado == 25000.0
    assert status.observaciones == "Aprobada sin observaciones."


# ---------------------------------------------------------------------------
# Nivel HTTP: POST /solicitud y GET /status/{id} desde routers/apps
# distintos sobre el mismo archivo — el caso exacto que describe el
# criterio de aceptación ("reiniciando el proceso entre el POST de
# creación y el GET de consulta").
# ---------------------------------------------------------------------------

def test_post_solicitud_luego_get_status_tras_reinicio_del_proceso(tmp_path):
    db_path = str(tmp_path / "devolucion_iva_http.db")

    # "Proceso 1": app + router + service sobre una conexión propia.
    client_1 = _client(Database(db_path), tenant_id="T1")
    resp_post = client_1.post(
        "/api/v1/devolucion-iva/solicitud",
        json={
            "periodo": "2026-01",
            "saldo_favor": 12000.0,
            "cuenta_banco": "BBVA",
            "clabe": "072180001234567897",
        },
    )
    assert resp_post.status_code == 200, resp_post.text
    solicitud_id = resp_post.json()["data"]["solicitud_id"]

    # "Proceso 2": app + router + service NUEVOS, conexión NUEVA al mismo
    # archivo — nada del proceso 1 sigue vivo en memoria.
    client_2 = _client(Database(db_path), tenant_id="T1")
    resp_get = client_2.get(f"/api/v1/devolucion-iva/status/{solicitud_id}")

    assert resp_get.status_code == 200, resp_get.text
    body = resp_get.json()
    assert body["data"]["solicitud_id"] == solicitud_id
    assert body["data"]["periodo"] == "2026-01"
    assert body["data"]["status_actual"] == EstatusDevolucion.PENDIENTE.value


def test_get_status_sin_solicitud_previa_da_404():
    """No hay ambigüedad entre 'no encontrada' (404 correcto) y una
    solicitud que en verdad existe pero el proceso 'perdió' — control de
    que el 404 del test anterior, si lo hubiera, no sería un falso
    negativo por bug en el endpoint mismo."""
    client = _client(db=None, tenant_id="T1")
    resp = client.get("/api/v1/devolucion-iva/status/no-existe-este-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Papeles de trabajo (`_papeles_trabajo`)
# ---------------------------------------------------------------------------

def test_papel_trabajo_sobrevive_reinicio_del_proceso(tmp_path):
    db_path = str(tmp_path / "papeles.db")

    svc_1 = DevolucionIVAService(db=Database(db_path))
    papel = svc_1.generar_papel_trabajo(
        periodo="2026-01",
        facturas=[{
            "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "rfc_emisor": "EMP850101AB1",
            "rfc_receptor": "REC850101CD2",
            "fecha": "2026-01-15",
            "subtotal": 10000.0,
            "iva": 1600.0,
            "total": 11600.0,
        }],
        diot_entries=[],
        declaraciones=[],
        saldo=1600.0,
        monto=1600.0,
        tenant_id="T1",
    )
    svc_1.registrar_papel_trabajo(papel)
    papel_id = papel.id
    del svc_1

    svc_2 = DevolucionIVAService(db=Database(db_path))
    recuperado = svc_2.obtener_papel_trabajo("2026-01", tenant_id="T1")

    assert recuperado is not None, (
        "El papel de trabajo se perdió al 'reiniciar' el proceso — "
        "REQ-IVA-006 no está persistiendo _papeles_trabajo en DB."
    )
    assert recuperado.id == papel_id
    assert recuperado.periodo == "2026-01"
    assert recuperado.saldo_a_favor == 1600.0
    assert len(recuperado.facturas) == 1
    assert isinstance(recuperado.facturas[0], FacturaCFDI)
    assert recuperado.facturas[0].uuid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_registrar_papel_trabajo_upsert_por_periodo_y_tenant(tmp_path):
    """Regenerar el papel de trabajo del mismo (tenant, periodo) reemplaza
    al anterior en vez de acumular filas obsoletas."""
    db = Database(str(tmp_path / "papeles_upsert.db"))
    svc = DevolucionIVAService(db=db)

    papel_v1 = PapelTrabajo(periodo="2026-01", tenant_id="T1", saldo_a_favor=100.0)
    svc.registrar_papel_trabajo(papel_v1)

    papel_v2 = PapelTrabajo(periodo="2026-01", tenant_id="T1", saldo_a_favor=999.0)
    svc.registrar_papel_trabajo(papel_v2)

    recuperado = svc.obtener_papel_trabajo("2026-01", tenant_id="T1")
    assert recuperado.saldo_a_favor == 999.0

    rows = db.conn.execute(
        "SELECT COUNT(*) AS n FROM devolucion_iva_papeles_trabajo "
        "WHERE tenant_id = 'T1' AND periodo = '2026-01'"
    ).fetchone()
    assert rows["n"] == 1


def test_papel_trabajo_aislado_por_tenant(tmp_path):
    db = Database(str(tmp_path / "papeles_tenant.db"))
    svc = DevolucionIVAService(db=db)

    svc.registrar_papel_trabajo(
        PapelTrabajo(periodo="2026-03", tenant_id="A", saldo_a_favor=1.0)
    )
    svc.registrar_papel_trabajo(
        PapelTrabajo(periodo="2026-03", tenant_id="B", saldo_a_favor=2.0)
    )

    solo_a = svc.obtener_papel_trabajo("2026-03", tenant_id="A")
    solo_b = svc.obtener_papel_trabajo("2026-03", tenant_id="B")

    assert solo_a.saldo_a_favor == 1.0
    assert solo_b.saldo_a_favor == 2.0


# ---------------------------------------------------------------------------
# Compatibilidad: `_solicitudes`/`_status`/`_papeles_trabajo` ya no son
# dicts de proceso, pero código/tests preexistentes que hacían
# `_solicitudes.clear()` deben seguir funcionando (ahora vacían la tabla
# real de la base compartida por defecto del módulo).
# ---------------------------------------------------------------------------

def test_clear_compat_vacia_la_tabla_real():
    from b2b_ai.features.devolucion_iva import service as svc_module

    sol = svc_module.preparar_solicitud(
        "2026-06", {"monto_devolucion_sugerido": 100.0}, tenant_id="T-clear",
    )
    svc_module.registrar_solicitud(sol)
    assert svc_module.consultar_status(sol.solicitud_id) is not None

    svc_module._solicitudes.clear()

    assert svc_module.consultar_status(sol.solicitud_id) is None
