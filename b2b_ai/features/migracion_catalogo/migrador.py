# -*- coding: utf-8 -*-
"""
migrador.py — Guardia de aprobación explícita (REQ-MIG-007, ADR-3) y
motor de migración transaccional por póliza (REQ-MIG-009).

Lo que implementa este archivo:

  1. La guardia que REQ-MIG-007 exige que CUALQUIER motor de migración
     de pólizas respete: ningún mapeo puede usarse para migrar una
     línea de póliza a menos que un humano ya lo haya decidido
     explícitamente vía `MigracionCatalogoService.aprobar()` o
     `.editar()` (nunca `.rechazar()`, nunca mientras siga
     `PENDIENTE`). La prueba adversarial de REQ-MIG-007
     (`tests/adversarial/test_migracion_requiere_aprobacion_explicita.py`)
     invoca `migrar_linea_con_mapeo` directamente sobre un mapeo en
     `estado=PENDIENTE` y exige que falle con una excepción explícita —
     nunca que migre en silencio ni que devuelva un resultado parcial.

  2. El motor de migración de pólizas (REQ-MIG-009): `migrar_poliza()`
     recibe una `PolizaOrigen` completa (todas sus líneas) y decide de
     forma atómica, por póliza:

       - Si TODAS sus líneas tienen un mapeo `aprobado`/`editado` para
         su cuenta origen: escribe TODAS las líneas en
         `lineas_poliza_migradas` dentro de una única transacción de
         Postgres (`conn.transaction()`). Cualquier error durante esa
         escritura (incluida una FK inválida a nivel de motor de BD)
         revierte la transacción completa — nunca queda una línea
         suelta en destino.
       - Si a UNA SOLA de sus líneas le falta un mapeo aprobado/editado
         (sin importar cuántas otras sí lo tengan): la póliza ENTERA se
         aborta, 0 líneas se escriben en `lineas_poliza_migradas`, y se
         inserta un registro en `polizas_bloqueadas` con las cuentas
         origen sin mapeo. Nunca se migra parcialmente dejando
         débito≠crédito en destino.

  3. Idempotencia (REQ-MIG-010): `migrar_poliza()` verifica, ANTES de
     intentar cualquier INSERT, si `lineas_poliza_migradas` ya tiene
     filas para `(tenant_id, poliza_origen_id)`. Si las tiene, la
     póliza se trata como ya migrada -- se devuelve el resultado
     idempotente (`ya_migrada=True`, `migrada=True`,
     `lineas_migradas=<conteo real ya existente en destino>`) sin
     ejecutar ningún INSERT nuevo. Esto es deliberadamente distinto de
     apoyarse solo en que la UNIQUE constraint
     (`uq_linea_poliza_migrada_origen`) rechace el reintento: si se
     dejara que el segundo intento choque contra la constraint, la
     excepción de Postgres caería en el mismo `except` que trata
     errores reales de escritura y la póliza terminaría encolada en
     `polizas_bloqueadas` como si hubiera FALLADO -- exactamente lo
     contrario de "reintentar no debe hacer nada distinto de la
     primera vez, ni marcar como bloqueada una póliza que en realidad
     ya se migró con éxito". El chequeo explícito por adelantado evita
     ese falso bloqueo y hace el criterio de REQ-MIG-010 verificable de
     forma directa (0 filas nuevas, resultado sigue siendo "migrada").

     Nota sobre `migrada_a_id`: el criterio original de REQ-MIG-010
     habla de marcar la póliza ORIGEN con `migrada_a_id=<id_destino>`.
     Este esquema (REQ-MIG-009/0013_polizas_bloqueadas) no crea una
     "póliza destino" con un id propio -- escribe líneas planas en
     `lineas_poliza_migradas` identificadas por
     `(tenant_id, poliza_origen_id)`, y ADR-3/REQ-MIG-011 prohíben
     tocar las tablas de origen (`asientos_contables`/
     `cuentas_contables`) para no alterar contabilidad electrónica ya
     dictaminada. Por eso la marca de "ya migrada" vive en
     `lineas_poliza_migradas` (destino), consultable por
     `poliza_ya_migrada()` más abajo, en vez de una columna nueva sobre
     el origen -- el efecto observable exigido por el criterio (0
     pólizas duplicadas en un reintento) queda igual de verificado sin
     mutar una tabla de origen.

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

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

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

    Remapea una única línea sin ninguna noción de "póliza completa": no
    aborta nada por el resto de una póliza ni escribe en
    `polizas_bloqueadas`. El motor real usado por REQ-MIG-009 es
    `migrar_poliza()`, más abajo en este mismo módulo, que sí es
    transaccional por póliza completa; esta función se conserva porque
    la prueba adversarial de REQ-MIG-007 la invoca directamente y porque
    `migrar_poliza()` reutiliza el mismo criterio de "migrable" que
    `validar_mapeo_migrable()` define aquí. Lo único que esta función
    garantiza es que ninguna migración de línea ocurre sin pasar antes
    por `validar_mapeo_migrable`: si el mapeo no está aprobado/editado,
    lanza `MapeoNoAprobadoError` sin tocar `linea_origen` en absoluto
    (ni siquiera para copiarla).
    """
    validar_mapeo_migrable(mapeo)
    return {
        **linea_origen,
        "cuenta_id": mapeo.destino_cuenta_id,
        "mapeo_id": mapeo.id,
    }


# ---------------------------------------------------------------------------
# REQ-MIG-009 — motor de migración transaccional por póliza completa
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LineaPolizaOrigen:
    """Una línea (un movimiento a una cuenta) dentro de una póliza de
    origen. `debe`/`haber` son mutuamente excluyentes en la práctica
    contable (una línea es débito O crédito), pero no se fuerza aquí:
    el balance que importa es el de la póliza completa, no el de una
    línea individual."""

    cuenta_origen_id: str
    debe: Decimal = Decimal("0")
    haber: Decimal = Decimal("0")
    descripcion: str = ""


@dataclass(frozen=True)
class PolizaOrigen:
    """Una póliza completa del sistema de origen: un conjunto de líneas
    que, en conjunto, deben cuadrar (`sum(debe) == sum(haber)`) — ese
    cuadre ya viene garantizado por el sistema de origen; este motor
    solo lo reverifica como defensa antes de confirmar la migración."""

    id: str
    tenant_id: int
    lineas: Sequence[LineaPolizaOrigen]


@dataclass(frozen=True)
class ResultadoMigracionPoliza:
    """Resultado de `migrar_poliza()` para una `PolizaOrigen`."""

    poliza_id: str
    migrada: bool
    lineas_migradas: int
    bloqueada: bool
    motivo_bloqueo: Optional[str] = None
    cuentas_sin_mapeo_aprobado: Tuple[str, ...] = field(default_factory=tuple)
    # REQ-MIG-010: True cuando esta póliza YA estaba migrada antes de esta
    # llamada -- `migrar_poliza()` no ejecutó ningún INSERT nuevo, solo
    # reportó el estado ya existente en `lineas_poliza_migradas`.
    ya_migrada: bool = False


class PolizaDesbalanceadaError(Exception):
    """La suma de `debe` y `haber` de las líneas con mapeo aprobado de
    una póliza no cuadra. No debería ocurrir nunca en la práctica (el
    remapeo de cuenta no altera montos, y una póliza de origen bien
    formada ya viene cuadrada) — existe como defensa en profundidad:
    si de algún modo ocurriera, la póliza se aborta y se encola en
    `polizas_bloqueadas` exactamente igual que una línea sin mapeo,
    nunca se confirma un desbalance en destino."""


# Mismo conjunto que `_ESTADOS_MIGRABLES`; se repite el nombre aquí para
# que quede explícito en el contexto de la póliza completa (una línea
# es "migrable" si y solo si su mapeo está en uno de estos estados).
_ESTADOS_MIGRABLES_POLIZA: FrozenSet[EstadoMapeoMigracion] = _ESTADOS_MIGRABLES


def _mapeo_migrable_para_linea(
    linea: LineaPolizaOrigen,
    mapeos_por_cuenta_origen: Mapping[str, MapeoMigracionCuenta],
) -> Optional[MapeoMigracionCuenta]:
    """Devuelve el `MapeoMigracionCuenta` a usar para `linea` si -- y
    solo si -- existe, está en `estado` aprobado/editado, Y tiene un
    `destino_cuenta_id` real. `None` en cualquier otro caso (sin mapeo
    en absoluto, mapeo pendiente/rechazado, o -- defensivamente -- un
    mapeo aprobado sin destino, que nunca debería existir para
    `tipo_match` distinto de `sin_match`, pero `sin_match` tampoco trae
    destino y por tanto nunca es migrable)."""
    mapeo = mapeos_por_cuenta_origen.get(linea.cuenta_origen_id)
    if mapeo is None:
        return None
    if mapeo.estado not in _ESTADOS_MIGRABLES_POLIZA:
        return None
    if mapeo.destino_cuenta_id is None:
        return None
    return mapeo


def poliza_ya_migrada(conn: Any, tenant_id: int, poliza_id: str) -> int:
    """Cuenta cuántas líneas de `poliza_id` (del tenant dado) ya existen
    en `lineas_poliza_migradas` -- REQ-MIG-010.

    Se usa como chequeo de idempotencia ANTES de intentar migrar: `0`
    significa que la póliza nunca se migró (o se migró y quedó
    bloqueada -- una póliza bloqueada nunca deja filas en destino, ver
    REQ-MIG-009); cualquier valor `> 0` significa que ya está migrada y
    `migrar_poliza()` debe tratar el reintento como un no-op idempotente
    en vez de volver a escribir.

    Consulta de solo lectura: nunca modifica `lineas_poliza_migradas`.
    """
    cur = conn.execute(
        "SELECT COUNT(*) FROM lineas_poliza_migradas "
        "WHERE tenant_id = %s AND poliza_origen_id = %s",
        (tenant_id, poliza_id),
    )
    return cur.fetchone()[0]


def _encolar_poliza_bloqueada(
    conn: Any,
    poliza: PolizaOrigen,
    motivo: str,
    cuentas_sin_mapeo: Sequence[str],
) -> None:
    """Inserta la póliza abortada en `polizas_bloqueadas`, en su propia
    transacción -- independiente de la transacción (revertida) de las
    líneas de destino, para que el registro de bloqueo sobreviva aunque
    la escritura en destino haya fallado."""
    with conn.transaction():
        conn.execute(
            "INSERT INTO polizas_bloqueadas "
            "(tenant_id, poliza_origen_id, motivo, cuentas_sin_mapeo) "
            "VALUES (%s, %s, %s, %s)",
            (
                poliza.tenant_id,
                poliza.id,
                motivo,
                json.dumps(sorted(set(cuentas_sin_mapeo))),
            ),
        )


def migrar_poliza(
    conn: Any,
    poliza: PolizaOrigen,
    mapeos_por_cuenta_origen: Mapping[str, MapeoMigracionCuenta],
) -> ResultadoMigracionPoliza:
    """Motor de migración transaccional por póliza completa (REQ-MIG-009).

    `conn` es una conexión `psycopg` (Postgres) ya abierta, con
    autocommit desactivado (comportamiento por defecto de psycopg3):
    esta función abre y cierra sus propias transacciones vía
    `conn.transaction()`, nunca asume ni deja un estado de transacción
    a medias para quien la invoca.

    `mapeos_por_cuenta_origen` es responsabilidad de quien llama: debe
    contener, para cada cuenta origen relevante, el `MapeoMigracionCuenta`
    vigente (lo normal es construirlo a partir de
    `MigracionCatalogoService.listar()`, tomando el mapeo activo -- no
    rechazado -- más reciente por `origen_cuenta_id`). Esta función NO
    decide cardinalidad ni conflictos entre mapeos (eso es REQ-MIG-008,
    `service.py`); solo consulta si, para cada línea, el mapeo que se le
    pasó es uno migrable.

    Garantía dura del criterio de aceptación: si UNA SOLA línea de
    `poliza` no tiene mapeo aprobado/editado, la póliza ENTERA se aborta
    -- cero líneas de esa póliza llegan a `lineas_poliza_migradas` -- y
    se encola en `polizas_bloqueadas`. Nunca hay una migración parcial
    que deje débito≠crédito en destino: las líneas con mapeo válido de
    una póliza bloqueada tampoco se migran solas.
    """
    if not poliza.lineas:
        raise ValueError(
            f"La póliza {poliza.id} no tiene líneas que migrar; no hay "
            "nada que decidir (ni migrar ni bloquear)."
        )

    # REQ-MIG-010: idempotencia. Si esta póliza ya tiene líneas en
    # destino, un reintento no debe insertar nada de nuevo -- se
    # reporta el estado ya existente, sin tocar la base ni encolarla en
    # `polizas_bloqueadas` (no falló: ya estaba resuelta).
    lineas_ya_migradas = poliza_ya_migrada(conn, poliza.tenant_id, poliza.id)
    if lineas_ya_migradas > 0:
        return ResultadoMigracionPoliza(
            poliza_id=poliza.id,
            migrada=True,
            lineas_migradas=lineas_ya_migradas,
            bloqueada=False,
            ya_migrada=True,
        )

    lineas_con_mapeo: list = []
    cuentas_sin_mapeo: list = []
    for linea in poliza.lineas:
        mapeo = _mapeo_migrable_para_linea(linea, mapeos_por_cuenta_origen)
        if mapeo is None:
            cuentas_sin_mapeo.append(linea.cuenta_origen_id)
        else:
            lineas_con_mapeo.append((linea, mapeo))

    # -- Caso 1: al menos una línea sin mapeo aprobado -> abortar TODA la
    # póliza, sin escribir ni una sola línea (ni siquiera las que sí
    # tenían mapeo válido) en destino.
    if cuentas_sin_mapeo:
        cuentas_ordenadas = tuple(sorted(set(cuentas_sin_mapeo)))
        motivo = (
            f"{len(cuentas_sin_mapeo)} de {len(poliza.lineas)} línea(s) sin "
            "mapeo aprobado/editado para su cuenta origen: "
            f"{list(cuentas_ordenadas)!r}. Póliza completa abortada (0 "
            "líneas migradas) -- REQ-MIG-009: nunca se migra "
            "parcialmente una póliza."
        )
        _encolar_poliza_bloqueada(conn, poliza, motivo, cuentas_ordenadas)
        return ResultadoMigracionPoliza(
            poliza_id=poliza.id,
            migrada=False,
            lineas_migradas=0,
            bloqueada=True,
            motivo_bloqueo=motivo,
            cuentas_sin_mapeo_aprobado=cuentas_ordenadas,
        )

    # -- Caso 2: todas las líneas tienen mapeo válido -> escribir TODAS
    # en una única transacción de Postgres. Cualquier excepción (de
    # validación propia, o de la propia base de datos -- p.ej. una FK
    # inválida si un mapeo apunta a un destino_cuenta_id que ya no
    # existe) revierte la transacción entera antes de que este bloque
    # la deje salir, y la póliza se trata igual que el caso 1: se
    # encola en `polizas_bloqueadas`, 0 líneas quedan en destino.
    try:
        with conn.transaction():
            for linea, mapeo in lineas_con_mapeo:
                conn.execute(
                    "INSERT INTO lineas_poliza_migradas "
                    "(tenant_id, poliza_origen_id, mapeo_id, "
                    "cuenta_origen_id, cuenta_destino_id, debe, haber, "
                    "descripcion) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        poliza.tenant_id,
                        poliza.id,
                        mapeo.id,
                        linea.cuenta_origen_id,
                        mapeo.destino_cuenta_id,
                        str(linea.debe),
                        str(linea.haber),
                        linea.descripcion or None,
                    ),
                )
            total_debe = sum(linea.debe for linea, _ in lineas_con_mapeo)
            total_haber = sum(linea.haber for linea, _ in lineas_con_mapeo)
            if total_debe != total_haber:
                raise PolizaDesbalanceadaError(
                    f"Póliza {poliza.id}: debe total ({total_debe}) != "
                    f"haber total ({total_haber}) tras el remapeo; "
                    "abortada antes de confirmar la transacción."
                )
    except Exception as exc:
        motivo = (
            f"Error durante la escritura en destino de la póliza "
            f"{poliza.id}: {exc}. Transacción revertida -- 0 líneas "
            "quedaron en lineas_poliza_migradas."
        )
        _encolar_poliza_bloqueada(
            conn,
            poliza,
            motivo,
            [linea.cuenta_origen_id for linea, _ in lineas_con_mapeo],
        )
        return ResultadoMigracionPoliza(
            poliza_id=poliza.id,
            migrada=False,
            lineas_migradas=0,
            bloqueada=True,
            motivo_bloqueo=motivo,
        )

    return ResultadoMigracionPoliza(
        poliza_id=poliza.id,
        migrada=True,
        lineas_migradas=len(lineas_con_mapeo),
        bloqueada=False,
    )
