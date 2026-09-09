# -*- coding: utf-8 -*-
"""
migrador.py — Guardia de aprobación explícita para el motor de migración
de pólizas (REQ-MIG-007, ADR-3).

Este archivo NO implementa el motor de migración de pólizas completo
(REQ-MIG-009: transaccionalidad por póliza completa, cola
`polizas_bloqueadas`, idempotencia vía `migrada_a_id` — requisito
separado de esta matriz, con sus propias pruebas en
`tests/features/migracion_catalogo/test_migracion_atomica_por_poliza.py`
y `test_migracion_idempotente.py`, y que requiere credenciales de BD de
pruebas).

Lo que sí implementa es la guardia que REQ-MIG-007 exige que CUALQUIER
motor de migración de pólizas respete: ningún mapeo puede usarse para
migrar una línea de póliza a menos que un humano ya lo haya decidido
explícitamente vía `MigracionCatalogoService.aprobar()` o `.editar()`
(nunca `.rechazar()`, nunca mientras siga `PENDIENTE`). La prueba
adversarial de REQ-MIG-007
(`tests/adversarial/test_migracion_requiere_aprobacion_explicita.py`)
invoca `migrar_linea_con_mapeo` directamente sobre un mapeo en
`estado=PENDIENTE` y exige que falle con una excepción explícita —
nunca que migre en silencio ni que devuelva un resultado parcial.

Interpretación de ADR-3 para `EDITADO`: el texto del ADR usa
`estado="aprobado"` como la puerta de entrada, pero el esquema de
REQ-MIG-002 define `EDITADO` como una decisión humana igual de explícita
— el humano corrigió `destino_cuenta_id` y firmó el cambio con
`aprobado_por`/`aprobado_en` vía `MigracionCatalogoService.editar()` —
no una variante de `PENDIENTE`. Tratar `EDITADO` como no migrable
dejaría sin salida a todo mapeo que un humano corrigió explícitamente
(el propósito mismo del endpoint `/editar`), lo cual contradice la razón
de ser de esa operación. Por eso este módulo trata `APROBADO` y
`EDITADO` como igualmente migrables, y `PENDIENTE`/`RECHAZADO` como
nunca migrables, sin excepción.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet

from .models import EstadoMapeoMigracion, MapeoMigracionCuenta

# Ver docstring del módulo: ambos representan una decisión humana
# explícita y auditable (aprobado_por/aprobado_en poblados). PENDIENTE y
# RECHAZADO nunca están en este conjunto, sin excepción.
_ESTADOS_MIGRABLES: FrozenSet[EstadoMapeoMigracion] = frozenset(
    {EstadoMapeoMigracion.APROBADO, EstadoMapeoMigracion.EDITADO}
)


class MapeoNoAprobadoError(Exception):
    """Se intentó migrar una línea de póliza usando un
    `MapeoMigracionCuenta` que nunca pasó por la revisión humana
    explícita de REQ-MIG-007 (`estado` distinto de `aprobado`/`editado`).

    Esta excepción es la barrera dura de ADR-3: el motor de migración de
    pólizas (REQ-MIG-009) debe lanzarla ANTES de tocar cualquier dato de
    la póliza destino — nunca migrar parcialmente y fallar después.
    """


def validar_mapeo_migrable(mapeo: MapeoMigracionCuenta) -> None:
    """Lanza `MapeoNoAprobadoError` si `mapeo` no puede usarse todavía
    para migrar una línea de póliza; no devuelve nada (ni lanza nada) si
    sí puede.

    Debe ser lo PRIMERO que ejecute el motor de migración de pólizas
    (REQ-MIG-009) por cada línea, antes de leer o escribir cualquier
    dato de la póliza destino.
    """
    if mapeo.estado not in _ESTADOS_MIGRABLES:
        raise MapeoNoAprobadoError(
            f"El mapeo {mapeo.id} (origen_cuenta_id={mapeo.origen_cuenta_id}, "
            f"tipo_match={mapeo.tipo_match.value}) está en "
            f"estado={mapeo.estado.value!r}; no puede usarse para migrar "
            "ninguna línea de póliza. Solo un mapeo en estado='aprobado' o "
            "'editado' -- decidido explícitamente vía "
            "POST /api/v1/migracion-catalogo/{mapeo_id}/aprobar o "
            "/editar (REQ-MIG-007, ADR-3) -- puede migrarse. Ningún mapeo "
            "alerta_riesgo/fuzzy/sin_match pendiente o rechazado se migra "
            "jamás automáticamente."
        )


def migrar_linea_con_mapeo(
    mapeo: MapeoMigracionCuenta, linea_origen: Dict[str, Any]
) -> Dict[str, Any]:
    """Punto de entrada mínimo de "el motor de migración de pólizas" que
    la prueba adversarial de REQ-MIG-007 invoca directamente.

    La lógica completa de migración transaccional por póliza (REQ-MIG-009:
    abortar la póliza entera si falta un mapeo aprobado para alguna de
    sus líneas, cola `polizas_bloqueadas`, idempotencia) es un requisito
    separado y NO se implementa aquí. Lo único que este stub garantiza —
    y que la prueba adversarial verifica — es que ninguna migración
    ocurre sin pasar antes por `validar_mapeo_migrable`: si el mapeo no
    está aprobado/editado, esta función lanza `MapeoNoAprobadoError` sin
    tocar `linea_origen` en absoluto (ni siquiera para copiarla).
    """
    validar_mapeo_migrable(mapeo)
    return {
        **linea_origen,
        "cuenta_id": mapeo.destino_cuenta_id,
        "mapeo_id": mapeo.id,
    }
