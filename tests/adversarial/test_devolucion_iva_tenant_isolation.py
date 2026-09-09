# -*- coding: utf-8 -*-
"""
REQ-IVA-007 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "`listar_solicitudes(tenant_id=...)` debe filtrar realmente por
  `tenant_id` (hoy recibe el parámetro y lo ignora, recorriendo todo
  `_solicitudes`); prueba adversarial: crear solicitudes para
  `tenant_id="A"` y `tenant_id="B"`, llamar
  `listar_solicitudes(tenant_id="A")` y confirmar
  `len(resultado) == 1` y que ninguna fila pertenece a `"B"`."

Antes del fix, `listar_solicitudes()` recorría `_solicitudes` completo
sin comparar el parámetro `tenant_id` contra nada (el modelo
`SolicitudDevolucion` ni siquiera tenía un campo `tenant_id`), así que
cualquier tenant podía ver las solicitudes de devolución de IVA de
cualquier otro tenant — una fuga multi-tenant real sobre datos
fiscales. Este archivo ejercita el servicio real (sin mocks) contra
ese escenario, y contra el wrapper `DevolucionIVAService.listar()`
usado por el router HTTP.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.devolucion_iva import service as devolucion_iva_service
from b2b_ai.features.devolucion_iva.service import (
    DevolucionIVAService,
    listar_solicitudes,
    preparar_solicitud,
    registrar_solicitud,
)


@pytest.fixture(autouse=True)
def _almacen_limpio():
    """El almacenamiento actual de `devolucion_iva` es en memoria de
    proceso a nivel de módulo (`_solicitudes`, `_status`) — sin esto,
    solicitudes creadas por otros tests del proceso quedarían visibles
    y el criterio exacto `len(resultado) == 1` del blueprint no sería
    verificable de forma determinista. No es un mock de la lógica bajo
    prueba: es aislamiento de estado entre tests contra el mismo
    almacén compartido real."""
    devolucion_iva_service._solicitudes.clear()
    devolucion_iva_service._status.clear()
    yield
    devolucion_iva_service._solicitudes.clear()
    devolucion_iva_service._status.clear()


def _crear_solicitud(periodo: str, monto: float, tenant_id: str):
    sol = preparar_solicitud(
        periodo,
        {"monto_devolucion_sugerido": monto},
        tenant_id=tenant_id,
    )
    registrar_solicitud(sol)
    return sol


def test_listar_solicitudes_filtra_realmente_por_tenant_id():
    """Caso adversarial del blueprint: tenant A nunca debe ver
    solicitudes de tenant B al pedir su propio listado filtrado."""
    sol_a = _crear_solicitud("2026-01", 15000.0, tenant_id="A")
    sol_b1 = _crear_solicitud("2026-01", 20000.0, tenant_id="B")
    sol_b2 = _crear_solicitud("2026-02", 5000.0, tenant_id="B")

    resultado = listar_solicitudes(tenant_id="A")

    assert len(resultado) == 1
    assert resultado[0]["solicitud_id"] == sol_a.solicitud_id
    assert resultado[0]["tenant_id"] == "A"

    ids_devueltos = {row["solicitud_id"] for row in resultado}
    assert sol_b1.solicitud_id not in ids_devueltos
    assert sol_b2.solicitud_id not in ids_devueltos
    assert all(row["tenant_id"] != "B" for row in resultado)


def test_listar_solicitudes_tenant_b_tampoco_ve_a_tenant_a():
    """Simétrico: B pide su propio listado y no debe ver nada de A."""
    sol_a = _crear_solicitud("2026-03", 8000.0, tenant_id="A")
    sol_b = _crear_solicitud("2026-03", 9000.0, tenant_id="B")

    resultado = listar_solicitudes(tenant_id="B")

    assert len(resultado) == 1
    assert resultado[0]["solicitud_id"] == sol_b.solicitud_id
    assert all(row["solicitud_id"] != sol_a.solicitud_id for row in resultado)


def test_listar_solicitudes_sin_tenant_id_no_rompe_uso_existente():
    """Sin `tenant_id` (uso legado/administrativo), el listado sigue
    sin filtrar — el fix no debe romper el comportamiento previo de
    listar todo cuando explícitamente no se pide aislar por tenant."""
    sol_a = _crear_solicitud("2026-04", 1234.0, tenant_id="A")
    sol_b = _crear_solicitud("2026-04", 4321.0, tenant_id="B")

    resultado = listar_solicitudes()
    ids_devueltos = {row["solicitud_id"] for row in resultado}

    assert sol_a.solicitud_id in ids_devueltos
    assert sol_b.solicitud_id in ids_devueltos


def test_devolucion_iva_service_listar_wrapper_filtra_por_tenant():
    """El wrapper `DevolucionIVAService.listar()` que usa el router
    HTTP (endpoint GET /historical) debe propagar el filtro, no solo
    la función de módulo."""
    svc = DevolucionIVAService()
    sol_a = _crear_solicitud("2026-05", 777.0, tenant_id="A")
    sol_b = _crear_solicitud("2026-05", 888.0, tenant_id="B")

    resultado = svc.listar(tenant_id="A")

    assert len(resultado) == 1
    assert resultado[0]["solicitud_id"] == sol_a.solicitud_id
    assert all(row["solicitud_id"] != sol_b.solicitud_id for row in resultado)
