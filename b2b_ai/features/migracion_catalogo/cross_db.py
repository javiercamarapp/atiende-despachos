# -*- coding: utf-8 -*-
"""
cross_db.py — Migración de catálogo de cuentas y pólizas entre DOS bases
de datos PostgreSQL físicamente distintas (origen y destino), extendiendo
el motor de matching (REQ-MIG-003..006, `matching.py`) y el motor de
migración transaccional por póliza (REQ-MIG-007/009/010, `migrador.py`)
SIN MODIFICARLOS.

Contexto (caso real que motivó este módulo, ver PR/branch
`fix/migracion-cross-database-catalogo`): un despacho regularizó 5 años
de una empresa creando DOS bases de datos físicamente distintas — una
para 2020-2023, otra para 2024-2026, cada una un servidor/instancia de
Postgres potencialmente distinto — y ahora necesita migrar pólizas
completas de la base 2024-2026 (origen) hacia la base 2020-2023
(destino), sin sobrescribir ninguna subcuenta del catálogo destino ni
alterar nada ya contabilizado ahí.

Antes de este módulo, `matching.py`/`migrador.py` ya estaban escritos de
forma agnóstica a la fuente de los datos:
  - `matching.py` opera sobre dataclasses en memoria (`CuentaCatalogo`,
    `CuentaCatalogoPar`) — nunca abre una conexión ni asume que ambos
    catálogos viven en la misma base.
  - `migrador.py::migrar_poliza` recibe una `PolizaOrigen` YA CARGADA en
    memoria y una única `conn` — la usa exclusivamente para ESCRIBIR en
    destino (`lineas_poliza_migradas`/`polizas_bloqueadas`); nunca lee ni
    escribe ninguna tabla de origen.

Lo que faltaba (confirmado por la auditoría de producción: "cero
mecanismo cross-database, ni siquiera un esqueleto") era el PEGAMENTO
que conecta ese motor, ya agnóstico, con DOS conexiones reales:
  1. Abrir dos conexiones simultáneas, cada una con su propio DSN
     (`ConexionesMigracion`).
  2. Leer el catálogo REAL de cada base por su propia conexión
     (`cargar_catalogo_origen`/`cargar_catalogo_destino`) en vez de
     asumir (como hacía implícitamente el diseño single-DB de
     `verificacion.py::_obtener_cuenta`, ver su docstring de REQ-MIG-012)
     que ambos catálogos viven en las mismas filas de una sola tabla vía
     `tenant_id`.
  3. Cargar una póliza real de origen (`cargar_poliza_origen`) y pasarla,
     ya en memoria, a `migrar_poliza()` sin cambiar esa función.

Garantía central (REQ adversarial de este módulo): el origen NUNCA se
modifica, bajo ningún escenario — éxito, fallo a medias, o fallo total.
Esto se cumple por DOS razones independientes, no solo una:
  (a) Estructuralmente: ninguna función de este módulo ejecuta INSERT/
      UPDATE/DELETE contra la conexión de origen. `cargar_poliza_origen`
      y `cargar_catalogo_origen` son SELECT puros, y toda la escritura
      ocurre exclusivamente en `migrar_poliza()` (migrador.py, sin
      cambios) usando la conexión de DESTINO.
  (b) A nivel de motor de base de datos: `ConexionesMigracion` abre la
      conexión de origen con `read_only=True` (psycopg3,
      `SET TRANSACTION READ ONLY` de sesión) — cualquier intento de
      escritura contra origen, incluso por un bug futuro en este mismo
      módulo o en quien lo invoque, es rechazado por Postgres mismo con
      `psycopg.errors.ReadOnlySqlTransaction`. Ver
      `tests/features/migracion_catalogo/test_cross_db_origen_nunca_se_modifica.py`.

Como las dos conexiones son procesos/transacciones de Postgres
COMPLETAMENTE independientes (nunca hay una sola transacción compartida
entre origen y destino, ni dos-phase-commit), un rollback en destino
jamás puede "arrastrar" ni afectar a origen y viceversa — no es una
garantía que dependa de que el código nunca se equivoque, es imposible
por construcción.
"""
from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import psycopg

from .matching import UMBRAL_SIN_MATCH, CuentaCatalogo, clasificar_cuenta_origen
from .migrador import (
    LineaPolizaOrigen,
    PolizaOrigen,
    ResultadoMigracionPoliza,
    migrar_poliza,
)
from .models import MapeoMigracionCuenta


def _leer_todas(conn: Any, sql: str, params: Sequence[Any]) -> list:
    """`conn.execute(sql, params).fetchall()` envuelto en su propia
    transacción -- ver la nota extensa en
    `migrador.py::poliza_ya_migrada` sobre por qué un `conn.execute()`
    SUELTO (fuera de un `with conn.transaction():`) deja una
    transacción implícita abierta que puede convertir el PRÓXIMO
    `with conn.transaction():` sobre esa MISMA conexión (p.ej. el de
    `migrar_poliza()`, si se reutiliza la conexión de destino después
    de leer su catálogo con `cargar_catalogo_destino`) en un SAVEPOINT
    anidado que nunca hace el COMMIT real -- reproducido exactamente
    así (catálogo leído, luego una póliza migrada en la misma sesión,
    conexión cerrada, reabierta: 0 filas) antes de esta función
    existir. Toda lectura de este módulo pasa por aquí para que ninguna
    dependa de que el llamador reutilice o no la misma conexión
    después."""
    with conn.transaction():
        return conn.execute(sql, tuple(params)).fetchall()


def _leer_una(conn: Any, sql: str, params: Sequence[Any]) -> Optional[Any]:
    with conn.transaction():
        return conn.execute(sql, tuple(params)).fetchone()


# ---------------------------------------------------------------------------
# Conexiones — dos DSN, dos conexiones psycopg reales, origen read-only
# ---------------------------------------------------------------------------

class ConexionesInvalidasError(Exception):
    """DSN de origen/destino inválidos para abrir una migración
    cross-database (vacío, o el mismo valor para ambos -- ver
    `ConexionesMigracion.__init__`)."""


class ConexionesMigracion:
    """Abre y mantiene DOS conexiones `psycopg` simultáneas — origen y
    destino — cada una con su propio DSN, potencialmente dos hosts
    Postgres distintos.

    La conexión de origen se abre con `read_only=True`: esto no es solo
    disciplina de código, es una garantía impuesta por Postgres mismo
    (`psycopg.errors.ReadOnlySqlTransaction` en cualquier intento de
    escritura). Ver el docstring del módulo.

    Uso:
        with ConexionesMigracion(origen_dsn, destino_dsn) as c:
            ... c.origen ... c.destino ...
        # ambas conexiones cerradas al salir del bloque, incluso si algo
        # lanzó una excepción dentro.
    """

    def __init__(self, origen_dsn: str, destino_dsn: str) -> None:
        if not origen_dsn or not str(origen_dsn).strip():
            raise ConexionesInvalidasError(
                "origen_dsn no puede estar vacío -- se requiere un DSN "
                "explícito a la base de datos de origen."
            )
        if not destino_dsn or not str(destino_dsn).strip():
            raise ConexionesInvalidasError(
                "destino_dsn no puede estar vacío -- se requiere un DSN "
                "explícito a la base de datos de destino."
            )
        self._origen_dsn = origen_dsn
        self._destino_dsn = destino_dsn
        self._origen: Optional[psycopg.Connection] = None
        self._destino: Optional[psycopg.Connection] = None

    def abrir(self) -> "ConexionesMigracion":
        self._origen = psycopg.connect(self._origen_dsn)
        # Guardia dura (no solo convención): ver docstring del módulo.
        self._origen.read_only = True
        try:
            self._destino = psycopg.connect(self._destino_dsn)
        except Exception:
            self._origen.close()
            self._origen = None
            raise
        return self

    def cerrar(self) -> None:
        for conn in (self._origen, self._destino):
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
        self._origen = None
        self._destino = None

    def __enter__(self) -> "ConexionesMigracion":
        return self.abrir()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cerrar()

    @property
    def origen(self) -> psycopg.Connection:
        if self._origen is None:
            raise RuntimeError(
                "Conexión de origen no abierta -- usa "
                "'with ConexionesMigracion(...) as c:' o llama .abrir() primero."
            )
        return self._origen

    @property
    def destino(self) -> psycopg.Connection:
        if self._destino is None:
            raise RuntimeError(
                "Conexión de destino no abierta -- usa "
                "'with ConexionesMigracion(...) as c:' o llama .abrir() primero."
            )
        return self._destino


# ---------------------------------------------------------------------------
# Catálogo real de cada base — lectura por su propia conexión
# ---------------------------------------------------------------------------

def cargar_catalogo_origen(conn: Any, tenant_id: Any) -> List[CuentaCatalogo]:
    """Lee el catálogo REAL de cuentas del sistema de ORIGEN, vía la
    conexión de origen (de solo lectura -- ver `ConexionesMigracion`).

    Usa `codigo` (no `cuenta_id`) como `CuentaCatalogo.id`: la base de
    origen puede llevar más tiempo sin actualizarse (p.ej. nunca corrió
    la migración `0012_cuenta_id_fk` que añade la columna `cuenta_id`
    UUID) y `codigo` es único por tenant desde el esquema original
    (`uq_cuenta_tenant`, `0001_initial.py`) — una clave natural estable
    que no depende de qué tan al día esté el esquema de la base origen.
    Como origen nunca se escribe (`migrar_poliza` solo escribe en
    destino), no hace falta un UUID estable ahí: `codigo` alcanza para
    identificar la cuenta a lo largo de todo este módulo.

    `tipo_agregado` se toma de la columna `grupo` (la aproximación más
    cercana que existe hoy en el esquema real -- no hay una columna
    `tipo_agregado` propia; ver `migrations/versions/0001_initial.py`).
    `cuenta_padre_codigo` queda `None`: el esquema real tampoco modela
    jerarquía de cuentas todavía, y `matching.py::_coincide_cuenta_padre`
    ya maneja ese caso con gracia (ningún lado declara padre -> no suma
    ni resta puntos, no se inventa evidencia que no existe).
    """
    filas = _leer_todas(
        conn,
        "SELECT codigo, descripcion, nivel, naturaleza, grupo "
        "FROM cuentas_contables WHERE tenant_id = %s ORDER BY codigo",
        (tenant_id,),
    )
    return [
        CuentaCatalogo(
            id=codigo,
            codigo=codigo,
            nombre=descripcion,
            nivel=int(nivel) if nivel is not None else 0,
            naturaleza=naturaleza or "",
            tipo_agregado=grupo or "",
            cuenta_padre_codigo=None,
        )
        for codigo, descripcion, nivel, naturaleza, grupo in filas
    ]


def cargar_catalogo_destino(conn: Any, tenant_id: Any) -> List[CuentaCatalogo]:
    """Lee el catálogo REAL de cuentas del sistema de DESTINO, vía la
    conexión de destino.

    A diferencia de `cargar_catalogo_origen`, aquí `CuentaCatalogo.id`
    SÍ es `cuenta_id` (UUID, REQ-MIG-001/`0012_cuenta_id_fk`): es el
    identificador que `migrar_poliza` (REQ-MIG-009) necesita para la FK
    real de `lineas_poliza_migradas.cuenta_destino_id`, y la base de
    destino de una migración cross-database es siempre la que este
    despliegue administra por Alembic (puede exigirse al día).
    """
    filas = _leer_todas(
        conn,
        "SELECT cuenta_id, codigo, descripcion, nivel, naturaleza, grupo "
        "FROM cuentas_contables WHERE tenant_id = %s ORDER BY codigo",
        (tenant_id,),
    )
    return [
        CuentaCatalogo(
            id=str(cuenta_id),
            codigo=codigo,
            nombre=descripcion,
            nivel=int(nivel) if nivel is not None else 0,
            naturaleza=naturaleza or "",
            tipo_agregado=grupo or "",
            cuenta_padre_codigo=None,
        )
        for cuenta_id, codigo, descripcion, nivel, naturaleza, grupo in filas
    ]


def clasificar_catalogo_cross_db(
    origen_conn: Any,
    destino_conn: Any,
    tenant_origen_id: Any,
    tenant_destino_id: Any,
    umbral_sin_match: float = UMBRAL_SIN_MATCH,
) -> List[MapeoMigracionCuenta]:
    """Corre el motor de matching de 3 niveles (REQ-MIG-003..006,
    `matching.clasificar_cuenta_origen`, sin modificarlo) leyendo el
    catálogo REAL de AMBAS bases -- cada una por su propia conexión --
    en vez de asumir que ambos catálogos viven en las mismas filas de
    una sola tabla vía `tenant_id` (la limitación single-DB que
    confirmó la auditoría).

    Devuelve la propuesta CRUDA del motor de matching -- un
    `MapeoMigracionCuenta` por cada cuenta de origen. Salvo
    `tipo_match=EXACTO` (auto-aprobado por diseño, REQ-MIG-003/ADR-3),
    ninguno de estos mapeos es migrable todavía: deben pasar por
    `MigracionCatalogoService.aprobar()`/`.editar()` (REQ-MIG-007) antes
    de poder usarse en `migrar_poliza_cross_db`/`migrar_lote_cross_db`.
    """
    origen_cuentas = cargar_catalogo_origen(origen_conn, tenant_origen_id)
    destino_cuentas = cargar_catalogo_destino(destino_conn, tenant_destino_id)
    return [
        clasificar_cuenta_origen(origen, destino_cuentas, umbral_sin_match=umbral_sin_match)
        for origen in origen_cuentas
    ]


# ---------------------------------------------------------------------------
# Pólizas reales de origen — lectura de solo lectura
# ---------------------------------------------------------------------------

class PolizaOrigenNoEncontradaError(Exception):
    """No existe ninguna póliza (`asientos_contables.id`) con ese
    `poliza_id`/`tenant_id` en la base de origen."""


def cargar_poliza_origen(
    conn: Any, tenant_id: Any, poliza_id: Any
) -> Optional[PolizaOrigen]:
    """Lee UNA póliza real de origen desde `asientos_contables`, de
    SOLO LECTURA -- nunca escribe ni marca nada en origen (la conexión
    ya viene en modo `read_only`, ver `ConexionesMigracion`).

    Nota honesta sobre el esquema real disponible
    (`migrations/versions/0001_initial.py`): `asientos_contables` no
    modela una "póliza" con varias líneas en tablas separadas -- cada
    fila YA es un asiento simple de dos cuentas (`cuenta_debito`/
    `cuenta_credito`) por el mismo `monto`. `migrador.py::PolizaOrigen`
    sí modela varias líneas por póliza (para el caso general), así que
    este loader traduce cada fila real en una `PolizaOrigen` de
    exactamente 2 líneas -- una al debe (`cuenta_debito`) y otra al
    haber (`cuenta_credito`) -- que por construcción siempre cuadra
    (`debe == haber == monto`), en vez de inventar una tabla de pólizas
    multi-línea que no existe en el esquema real de este repo. El
    `poliza_id` que usa todo el motor de ahí en adelante
    (`lineas_poliza_migradas`, `polizas_bloqueadas`, idempotencia
    REQ-MIG-010) es `str(asientos_contables.id)`.

    Devuelve `None` si no existe ninguna fila con ese id/tenant -- para
    que el llamador decida qué hacer (`migrar_poliza_cross_db` lo
    traduce a `PolizaOrigenNoEncontradaError`), en vez de que este
    loader invente una póliza vacía.
    """
    fila = _leer_una(
        conn,
        "SELECT id, cuenta_debito, cuenta_credito, monto, descripcion "
        "FROM asientos_contables WHERE tenant_id = %s AND id = %s",
        (tenant_id, poliza_id),
    )
    if fila is None:
        return None
    id_, cuenta_debito, cuenta_credito, monto, descripcion = fila
    monto_dec = monto if isinstance(monto, Decimal) else Decimal(str(monto))
    return PolizaOrigen(
        id=str(id_),
        tenant_id=tenant_id,
        lineas=(
            LineaPolizaOrigen(
                cuenta_debito, debe=monto_dec, haber=Decimal("0"),
                descripcion=descripcion or "",
            ),
            LineaPolizaOrigen(
                cuenta_credito, debe=Decimal("0"), haber=monto_dec,
                descripcion=descripcion or "",
            ),
        ),
    )


def listar_ids_polizas_origen_elegibles(
    conn: Any,
    tenant_id: Any,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> List[str]:
    """Devuelve, en orden, los `poliza_id` (== `asientos_contables.id`)
    elegibles para migrar de un tenant de origen -- de solo lectura.

    Filtra por rango de fecha (`YYYY-MM-DD`, comparación lexicográfica,
    igual que el resto del código de contabilidad -- ver
    `calcular_saldo_cuenta_periodo` en `verificacion.py`) cuando se da.
    """
    sql = "SELECT id FROM asientos_contables WHERE tenant_id = %s"
    params: list = [tenant_id]
    if fecha_inicio is not None:
        sql += " AND fecha >= %s"
        params.append(fecha_inicio)
    if fecha_fin is not None:
        sql += " AND fecha <= %s"
        params.append(fecha_fin)
    sql += " ORDER BY id"
    filas = _leer_todas(conn, sql, params)
    return [str(f[0]) for f in filas]


# ---------------------------------------------------------------------------
# Migración cross-database — reutiliza migrador.migrar_poliza sin cambios
# ---------------------------------------------------------------------------

def migrar_poliza_cross_db(
    conexiones: ConexionesMigracion,
    tenant_origen_id: Any,
    tenant_destino_id: Any,
    poliza_id: Any,
    mapeos_por_cuenta_origen: Dict[str, MapeoMigracionCuenta],
) -> ResultadoMigracionPoliza:
    """Migra UNA póliza real leyéndola de origen y escribiéndola en
    destino -- dos conexiones físicamente distintas.

    Reutiliza `migrador.migrar_poliza` SIN MODIFICARLO (REQ-MIG-007/009/
    010 -- guardia de aprobación explícita e idempotencia -- se aplican
    exactamente igual que en el escenario single-DB): la lectura de
    origen (`cargar_poliza_origen`, solo lectura, conexión `read_only`)
    ocurre POR COMPLETO antes de que `migrar_poliza` toque la conexión
    de destino. Por eso:
      - Si la lectura de origen falla, nunca se abrió ninguna
        transacción de destino: no hay nada que revertir ahí, y origen
        sigue intacto (nunca se intentó escribir, y aunque se
        intentara, es `read_only` a nivel de sesión).
      - Si la escritura en destino falla por cualquier motivo (mapeo no
        aprobado, FK inválida, desbalance...), `migrar_poliza` ya
        revierte su propia transacción de destino -- origen ni
        siquiera puede participar de esa transacción porque es una
        conexión Postgres distinta: no hay forma de que un rollback en
        destino se "propague" a origen ni viceversa, porque nunca hubo
        una sola transacción compartida entre las dos bases.

    `tenant_destino_id` no se usa dentro de esta función (el filtro por
    tenant de destino ya vive en `mapeos_por_cuenta_origen` --
    construido contra el catálogo de ese tenant -- y en las tablas de
    destino que `migrar_poliza` escribe); se recibe explícito para que
    la firma documente con claridad qué tenant de cada lado participa
    en la llamada, en vez de dejarlo implícito en `conexiones`.
    """
    poliza = cargar_poliza_origen(conexiones.origen, tenant_origen_id, poliza_id)
    if poliza is None:
        raise PolizaOrigenNoEncontradaError(
            f"poliza_id={poliza_id!r} no existe en origen "
            f"(tenant_id={tenant_origen_id!r})"
        )
    return migrar_poliza(conexiones.destino, poliza, mapeos_por_cuenta_origen)


def migrar_lote_cross_db(
    conexiones: ConexionesMigracion,
    tenant_origen_id: Any,
    tenant_destino_id: Any,
    mapeos_por_cuenta_origen: Dict[str, MapeoMigracionCuenta],
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> Dict[str, ResultadoMigracionPoliza]:
    """Migra TODAS las pólizas elegibles de origen en un rango de fecha
    dado -- pensado para "cientos de pólizas" (el caso real que motiva
    este módulo).

    Reanudable de forma natural: si el proceso se interrumpe a medias y
    se vuelve a invocar esta misma función con el mismo rango, las
    pólizas que ya quedaron en `lineas_poliza_migradas` (destino) se
    reportan como `ya_migrada=True` sin duplicar nada (REQ-MIG-010,
    `migrador.py::poliza_ya_migrada`, sin cambios) -- esta función solo
    itera, la idempotencia por póliza ya la garantiza `migrar_poliza`.

    Una póliza sin mapeo completo se bloquea (queda en
    `polizas_bloqueadas`, 0 líneas escritas) SIN afectar a las demás
    pólizas del lote -- cada llamada a `migrar_poliza_cross_db` es
    independiente.

    Devuelve `{poliza_id: ResultadoMigracionPoliza}` para el lote
    completo, en el mismo orden en que se procesaron.
    """
    ids = listar_ids_polizas_origen_elegibles(
        conexiones.origen, tenant_origen_id, fecha_inicio, fecha_fin
    )
    resultados: Dict[str, ResultadoMigracionPoliza] = {}
    for poliza_id in ids:
        resultados[poliza_id] = migrar_poliza_cross_db(
            conexiones,
            tenant_origen_id,
            tenant_destino_id,
            poliza_id,
            mapeos_por_cuenta_origen,
        )
    return resultados
