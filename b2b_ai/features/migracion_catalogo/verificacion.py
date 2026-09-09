# -*- coding: utf-8 -*-
"""
verificacion.py — Verificaciones de integridad post-migración: cuadre de
saldos por cuenta (REQ-MIG-012), conteo de pólizas (REQ-MIG-013),
balance por póliza (REQ-MIG-014) y referencias huérfanas (REQ-MIG-015).

Contexto común (docs/BLUEPRINT-AGENTES-FISCALES.md §3, ADR-3): antes de
dar por cerrada una migración/fusión de catálogo, varias verificaciones
independientes deben pasar. Este archivo implementa tres de ellas:

  - REQ-MIG-012 (cuadre de saldos por cuenta migrada): para cada cuenta
    efectivamente migrada (`estado=aprobado`/`editado`), el saldo real
    de esa cuenta en el periodo dado debe coincidir entre origen y
    destino con tolerancia `<= 0.01` MXN (a diferencia de REQ-MIG-014,
    que exige `0.00` exacto porque compara la MISMA póliza remapeada;
    aquí se compara el saldo agregado de dos sistemas contables
    potencialmente distintos, con reglas de redondeo/consolidación
    propias, de ahí la tolerancia de un centavo). Ver
    `calcular_saldo_cuenta_periodo`/`verificar_cuadre_saldos`/
    `cerrar_migracion`/`CuadreSaldosNoPermiteCierreError`. Sección
    añadida en el mismo commit que REQ-MIG-013/014 pero sin tests hasta
    `tests/features/migracion_catalogo/test_verificacion_cuadre_saldos.py`
    (ver ese archivo para el detalle de por qué se cerró como deuda de
    verificación, no como código faltante).

  - REQ-MIG-013 (conteo de pólizas): el número de pólizas que existían
    en origen y eran elegibles para migrar debe coincidir EXACTO (0 de
    diferencia, sin tolerancia) con el número de pólizas que terminaron
    existiendo en destino como resultado de esa migración. Cualquier
    discrepancia — en cualquier dirección, incluida una en destino de
    MÁS pólizas que en origen, señal de una migración duplicada —
    bloquea el cierre. Ver `verificar_conteo_polizas`/
    `verificar_conteo_polizas_en_bd`/`DiscrepanciaConteoPolizasError`.

  - REQ-MIG-014 (balance por póliza): el 100% de las pólizas migradas a
    destino debe cumplir `sum(debe) == sum(haber)` con tolerancia
    `0.00` -- a diferencia de REQ-MIG-012 (cuadre de saldos por cuenta),
    que sí tolera hasta 0.01 MXN porque compara dos agregados
    calculados de formas distintas. Aquí no hay tolerancia: una póliza
    migrada es, línea por línea, la misma póliza con las cuentas
    remapeadas -- remapear una cuenta cambia el `cuenta_id` de una
    línea, nunca su `debe`/`haber`. Cualquier diferencia, por mínima
    que sea, indica que el remapeo alteró un monto y debe bloquear el
    cierre. Ver `calcular_balance_polizas`/
    `verificar_balance_polizas_en_bd`/`BalancePolizaDesbalanceadaError`.

Alcance de este archivo (REQ-MIG-012, REQ-MIG-013, REQ-MIG-014 y
REQ-MIG-015): la lógica de verificación en sí y la decisión de bloquear
el cierre cuando algo no cuadra. Ninguna decide qué cuenta como
"elegible"/"migrada" en origen/destino más allá de leer el esquema real
que ya define el motor de migración de pólizas transaccional
(REQ-MIG-009/010, `migrador.py`: `lineas_poliza_migradas`,
`polizas_bloqueadas`). `verificar_conteo_polizas_en_bd`/
`verificar_balance_polizas_en_bd` reciben la(s) consulta(s) SQL como
parámetro (para no atarse a nombres de tabla/columna en el momento en
que se escribieron, antes de que ese esquema existiera); REQ-MIG-012 y
REQ-MIG-015, añadidos después de que `migrador.py` ya definía el
esquema real, sí consultan `lineas_poliza_migradas`/`cuentas_contables`
directamente.

La otra verificación de integridad de la misma sección del blueprint
(REQ-MIG-016 log de auditoría) es un requisito separado y no se toca en
este archivo.

Las cuatro verificaciones son de solo lectura: ejecutan únicamente
consultas suministradas por el llamador (o, en REQ-MIG-012/015, un
`LEFT JOIN`/agregado fijo contra el esquema real) y nunca escriben,
migran ni reclasifican nada (regla dura del blueprint sobre aprobación
humana explícita).

Compatibilidad de conexión: `verificar_conteo_polizas_en_bd` usa el
mismo wrapper `?`-parametrizado que el resto del repo
(`b2b_ai.db.db.Database().conn` — compatible con SQLite y, vía
`PGConnection`/`PGCursor` en `b2b_ai/db/postgres_adapter.py`, con
PostgreSQL real), con `conn.execute(sql, params)` devolviendo un cursor
con `.fetchone()`. `verificar_balance_polizas_en_bd` usa la misma forma
de `conn.execute(sql, params)` pero con `.fetchall()` (varias filas,
una por línea de póliza) -- compatible con ese mismo wrapper y, al
implementar psycopg3 `Connection.execute(...)` la misma firma
`(sql, params) -> cursor`, también con una conexión psycopg3 real sin
pasar por el wrapper del repo (útil para pruebas de integración
aisladas contra Postgres, como las de este requisito).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from b2b_ai.features.contabilidad.models import NaturalezaCuenta
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
)


class DiscrepanciaConteoPolizasError(Exception):
    """`count(polizas_destino_migradas) != count(polizas_origen_elegibles)`.

    Bloquea el cierre de la migración (REQ-MIG-013) sin excepción: el
    criterio exige 0 de diferencia exacto, nunca una tolerancia como la
    de REQ-MIG-012 (que sí acepta 0.01 MXN en saldos) ni una decisión de
    "es una diferencia pequeña, se puede cerrar de todos modos".
    """

    def __init__(self, count_origen_elegibles: int, count_destino_migradas: int):
        self.count_origen_elegibles = count_origen_elegibles
        self.count_destino_migradas = count_destino_migradas
        self.diferencia = abs(count_origen_elegibles - count_destino_migradas)
        super().__init__(
            "Conteo de pólizas no cuadra -- cierre de la migración "
            f"BLOQUEADO (REQ-MIG-013): count(polizas_origen_elegibles)="
            f"{count_origen_elegibles}, count(polizas_destino_migradas)="
            f"{count_destino_migradas}, diferencia={self.diferencia}. El "
            "criterio exige exactamente 0 de diferencia; cualquier "
            "discrepancia, en cualquier dirección, bloquea el cierre."
        )


@dataclass(frozen=True)
class ResultadoConteoPolizas:
    """Resultado de una verificación de conteo que SÍ cuadró (si no
    cuadrara, `verificar_conteo_polizas`/`verificar_conteo_polizas_en_bd`
    lanzan `DiscrepanciaConteoPolizasError` en su lugar y este objeto
    nunca se construye)."""

    count_origen_elegibles: int
    count_destino_migradas: int

    @property
    def diferencia(self) -> int:
        return abs(self.count_origen_elegibles - self.count_destino_migradas)

    @property
    def cuadra(self) -> bool:
        return self.diferencia == 0


def verificar_conteo_polizas(
    count_origen_elegibles: int, count_destino_migradas: int
) -> ResultadoConteoPolizas:
    """Aplica el criterio de cierre de REQ-MIG-013 sobre dos conteos ya
    calculados: deben ser exactamente iguales.

    Lanza `DiscrepanciaConteoPolizasError` si no cuadran (en cualquier
    dirección: faltan pólizas en destino, o sobran -- señal de una
    migración duplicada por una falla de idempotencia de REQ-MIG-010).
    Lanza `ValueError` si algún conteo es negativo (un `COUNT(*)` real
    nunca lo es; esto solo puede pasar si el llamador construyó mal el
    número, y es preferible fallar aquí que cerrar una migración sobre
    un conteo que no tiene sentido).

    Devuelve `ResultadoConteoPolizas` únicamente cuando cuadran.
    """
    if count_origen_elegibles < 0 or count_destino_migradas < 0:
        raise ValueError(
            "Los conteos de pólizas no pueden ser negativos: "
            f"count_origen_elegibles={count_origen_elegibles}, "
            f"count_destino_migradas={count_destino_migradas}"
        )
    if count_origen_elegibles != count_destino_migradas:
        raise DiscrepanciaConteoPolizasError(
            count_origen_elegibles, count_destino_migradas
        )
    return ResultadoConteoPolizas(count_origen_elegibles, count_destino_migradas)


def _contar(conn, query: str, params: Sequence = ()) -> int:
    """Ejecuta `query` -- debe ser un `SELECT COUNT(*) ...` o equivalente
    que devuelva una sola fila con un solo valor entero -- sobre `conn` y
    devuelve ese entero. No interpreta ni valida el contenido de `query`
    más allá de eso: quién define el universo de "elegibles"/"migradas"
    es quien la construye (REQ-MIG-009), no este módulo.
    """
    row = conn.execute(query, tuple(params)).fetchone()
    if row is None or row[0] is None:
        raise ValueError(
            f"La consulta de conteo no devolvió resultado utilizable: {query!r}"
        )
    return int(row[0])


def verificar_conteo_polizas_en_bd(
    conn,
    query_origen_elegibles: str,
    query_destino_migradas: str,
    params_origen: Sequence = (),
    params_destino: Sequence = (),
) -> ResultadoConteoPolizas:
    """Ejecuta las dos consultas de conteo suministradas por el llamador
    contra `conn` (real, sin mocks) y aplica `verificar_conteo_polizas`
    sobre los dos enteros resultantes.

    `query_origen_elegibles` y `query_destino_migradas` son responsabilidad
    del llamador (el motor de migración de pólizas, REQ-MIG-009, define
    qué es "elegible" y qué es "migrada"); esta función solo las ejecuta
    y compara. Operación de solo lectura -- no escribe, no migra, no
    reclasifica nada.
    """
    count_origen = _contar(conn, query_origen_elegibles, params_origen)
    count_destino = _contar(conn, query_destino_migradas, params_destino)
    return verificar_conteo_polizas(count_origen, count_destino)


# ---------------------------------------------------------------------------
# REQ-MIG-014 — Balance por póliza
# ---------------------------------------------------------------------------

# Tolerancia exacta exigida por REQ-MIG-014: cero, no 0.01 (a diferencia
# de REQ-MIG-012). Se deja como constante nombrada -- nunca un literal
# suelto -- para que quede claro en el código que la elección de "0" es
# deliberada y no un valor por defecto olvidado.
TOLERANCIA_BALANCE_POLIZA = Decimal("0")


class LineaPolizaMigrada(BaseModel):
    """Una línea (debe o haber) de una póliza ya migrada al destino.

    `poliza_id` identifica la póliza destino a la que pertenece la línea
    (varias líneas comparten el mismo `poliza_id`). `debe`/`haber` son
    los montos de esa línea tal como quedaron en destino -- típicamente
    uno de los dos es cero, como en cualquier línea de un libro diario.
    `cuenta_id` es opcional y solo informativo (útil para el reporte de
    discrepancias); esta verificación no depende de ella.
    """

    poliza_id: str = Field(
        ..., description="ID de la póliza destino a la que pertenece esta línea"
    )
    cuenta_id: Optional[str] = Field(
        default=None,
        description="cuenta_id destino de esta línea (informativo, no se valida aquí)",
    )
    debe: Decimal = Field(default=Decimal("0"), description="Monto al debe de la línea")
    haber: Decimal = Field(
        default=Decimal("0"), description="Monto al haber de la línea"
    )

    model_config = {"arbitrary_types_allowed": True}


class DiscrepanciaBalancePoliza(BaseModel):
    """Una póliza migrada cuyo `sum(debe)` y `sum(haber)` no coinciden
    exactamente. `diferencia` es siempre positiva (valor absoluto)."""

    poliza_id: str
    suma_debe: Decimal
    suma_haber: Decimal
    diferencia: Decimal

    model_config = {"arbitrary_types_allowed": True}


class ReporteBalancePolizas(BaseModel):
    """Resultado de correr REQ-MIG-014 sobre un conjunto de pólizas
    migradas. `cuadra` es `True` únicamente cuando `discrepancias` está
    vacío -- el 100% del criterio, no "casi todas"."""

    total_polizas: int = Field(
        ..., description="Número de pólizas destino distintas evaluadas"
    )
    discrepancias: List[DiscrepanciaBalancePoliza] = Field(default_factory=list)

    @property
    def cuadra(self) -> bool:
        return len(self.discrepancias) == 0

    @property
    def polizas_ok(self) -> int:
        return self.total_polizas - len(self.discrepancias)

    model_config = {"arbitrary_types_allowed": True}


class BalancePolizaDesbalanceadaError(Exception):
    """Se intentó cerrar la verificación de balance por póliza
    (REQ-MIG-014) habiendo al menos una póliza migrada con
    `sum(debe) != sum(haber)`. Lleva el reporte completo adjunto
    (`reporte`) para que quien la capture pueda listar exactamente qué
    pólizas no cuadraron -- nunca solo "algo falló"."""

    def __init__(self, reporte: "ReporteBalancePolizas") -> None:
        self.reporte = reporte
        ids = ", ".join(d.poliza_id for d in reporte.discrepancias)
        super().__init__(
            "Verificación de balance por póliza (REQ-MIG-014) falló: "
            f"{len(reporte.discrepancias)} de {reporte.total_polizas} "
            f"pólizas migradas no cumplen sum(debe) == sum(haber) con "
            f"tolerancia {TOLERANCIA_BALANCE_POLIZA}: [{ids}]. El cierre "
            "de la migración queda bloqueado hasta resolver estas "
            "pólizas -- ninguna migración parcial se considera cerrada."
        )


def calcular_balance_polizas(
    lineas: Iterable[LineaPolizaMigrada],
) -> ReporteBalancePolizas:
    """Agrupa `lineas` por `poliza_id` y verifica, para cada póliza,
    `sum(debe) == sum(haber)` con tolerancia exacta 0 (REQ-MIG-014).

    Pura: no toca ninguna base de datos. Usa `Decimal` en todo el
    cálculo -- nunca `float` -- precisamente para que "tolerancia 0.00"
    signifique cero de verdad y no quede sujeto a error de redondeo
    binario (0.1 + 0.2 != 0.3 en float).

    Una póliza sin ninguna línea nunca ocurre en la práctica (no hay
    `poliza_id` sin al menos una fila que lo produzca), pero si
    `lineas` está vacío del todo el reporte resultante tiene
    `total_polizas=0` y `cuadra=True` (el 100% de un conjunto vacío se
    cumple vacuamente; no hay ninguna póliza que reprobar).
    """
    sumas: "dict[str, list[Decimal]]" = {}
    orden: List[str] = []
    for linea in lineas:
        if linea.poliza_id not in sumas:
            sumas[linea.poliza_id] = [Decimal("0"), Decimal("0")]
            orden.append(linea.poliza_id)
        acumulado = sumas[linea.poliza_id]
        acumulado[0] += linea.debe
        acumulado[1] += linea.haber

    discrepancias: List[DiscrepanciaBalancePoliza] = []
    for poliza_id in orden:
        suma_debe, suma_haber = sumas[poliza_id]
        diferencia = abs(suma_debe - suma_haber)
        if diferencia > TOLERANCIA_BALANCE_POLIZA:
            discrepancias.append(
                DiscrepanciaBalancePoliza(
                    poliza_id=poliza_id,
                    suma_debe=suma_debe,
                    suma_haber=suma_haber,
                    diferencia=diferencia,
                )
            )

    return ReporteBalancePolizas(total_polizas=len(orden), discrepancias=discrepancias)


def _decimal_o_cero(valor: Any) -> Decimal:
    """Convierte el valor devuelto por el driver de BD (Decimal para
    columnas NUMERIC de Postgres, pero se acepta también str/int/None
    por robustez) a `Decimal` sin pasar nunca por `float`."""
    if valor is None:
        return Decimal("0")
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def verificar_balance_polizas_en_bd(
    conn: Any,
    query: str,
    params: Optional[Sequence[Any]] = None,
) -> ReporteBalancePolizas:
    """Ejecuta `query` contra `conn` y corre `calcular_balance_polizas`
    sobre el resultado (REQ-MIG-014).

    `query` debe devolver exactamente 3 columnas, en este orden:
    `(poliza_id, debe, haber)` -- una fila por línea de póliza migrada,
    no un agregado ya sumado (la suma la hace esta función, no la
    consulta, para no depender de que quien la escriba use `SUM()`
    correctamente). Usa `conn.execute(query, params).fetchall()`, la
    misma forma que `_contar()` arriba -- compatible con el wrapper
    `?`-parametrizado del repo (`Database().conn`) y con una conexión
    psycopg3 real (`Connection.execute` tiene la misma firma).

    Este módulo no asume ningún nombre de tabla/columna de destino --
    esa decisión es de REQ-MIG-009/010 (el motor de migración de
    pólizas y su esquema), que aún no existen. Quien los implemente
    pasa aquí la consulta contra su propio esquema; esta función solo
    garantiza que la verificación de balance se aplique sin mocks sobre
    datos reales.
    """
    filas = conn.execute(query, params or ()).fetchall()
    lineas = [
        LineaPolizaMigrada(
            poliza_id=str(fila[0]),
            debe=_decimal_o_cero(fila[1]),
            haber=_decimal_o_cero(fila[2]),
        )
        for fila in filas
    ]
    return calcular_balance_polizas(lineas)


def cerrar_verificacion_balance_polizas(
    reporte: ReporteBalancePolizas,
) -> ReporteBalancePolizas:
    """Guardia de cierre: devuelve `reporte` sin tocar si
    `reporte.cuadra` es `True`; lanza `BalancePolizaDesbalanceadaError`
    (con el reporte completo adjunto) en cualquier otro caso.

    Es el único punto que debería invocar el flujo de cierre de
    migración para esta verificación -- nunca se debe interpretar
    "algunas pólizas cuadran" como suficiente (REQ-MIG-014 exige el
    100%, sin excepción).
    """
    if not reporte.cuadra:
        raise BalancePolizaDesbalanceadaError(reporte)
    return reporte


# ---------------------------------------------------------------------------
# REQ-MIG-012 — Cuadre de saldos por cuenta migrada
# ---------------------------------------------------------------------------
#
# Modelo de datos asumido (el único que existe hoy en el esquema -- ver
# `migrations/versions/0001_initial.py` y `0012_cuenta_id_fk.py`): origen
# y destino son dos catálogos de cuentas que conviven en las mismas
# tablas `cuentas_contables`/`asientos_contables`, cada uno bajo su
# propio `tenant_id` (dos "sistemas contables" == dos tenants).
# `origen_cuenta_id`/`destino_cuenta_id` de `MapeoMigracionCuenta` son
# valores de `cuentas_contables.cuenta_id` (el PK UUID de REQ-MIG-001),
# uno en el tenant origen y otro en el tenant destino. El saldo de una
# cuenta en un periodo se calcula igual que en
# `b2b_ai/features/contabilidad/service.py` (naturaleza acreedora:
# créditos − débitos; deudora: débitos − créditos), sumando
# `asientos_contables.monto` de ese tenant cuyo `cuenta_debito`/
# `cuenta_credito` (texto) coincide con el `codigo` de la cuenta, con
# `fecha` dentro de `[periodo_inicio, periodo_fin]`.
#
# Solo se verifican cuentas efectivamente MIGRADAS: mapeos en
# `estado=aprobado`/`editado` (las únicas dos decisiones humanas
# explícitas que ADR-3 permite migrar -- ver
# `migrador.py::_ESTADOS_MIGRABLES`). Un mapeo `pendiente`/`rechazado`
# nunca movió ninguna cuenta, así que no tiene sentido -- y sería
# engañoso -- incluirlo en un reporte de cuadre "post-migración".

# Tolerancia dura del criterio REQ-MIG-012: una diferencia MAYOR a esto
# bloquea el cierre.
TOLERANCIA_CUADRE_MXN_DEFAULT = Decimal("0.01")

# Únicos dos estados que ADR-3 permite considerar "migrados" (idéntico a
# `migrador.py::_ESTADOS_MIGRABLES`; no se importa de ahí para no crear
# una dependencia entre módulos hermanos por una constante de dos
# valores -- ambos se prueban explícitamente en los tests de este
# archivo y del de `migrador.py`).
_ESTADOS_MIGRADOS_SALDOS = frozenset(
    {EstadoMapeoMigracion.APROBADO, EstadoMapeoMigracion.EDITADO}
)


class CuentaContableNoEncontradaError(Exception):
    """Un `origen_cuenta_id`/`destino_cuenta_id` de un mapeo migrado no
    existe en `cuentas_contables`. Nunca se asume un saldo de $0 para
    una cuenta que no se pudo encontrar -- eso escondería el problema
    real detrás de un falso "sí cuadra"."""


class CuadreSaldosNoPermiteCierreError(Exception):
    """Bloquea el cierre de la migración (REQ-MIG-012): al menos una
    cuenta migrada no cuadró dentro de la tolerancia, o quedó un mapeo
    migrado sin `destino_cuenta_id` (estado inconsistente). El reporte
    completo -- incluidas las cuentas que sí cuadraron -- queda adjunto
    en `.reporte` para que quien atienda el bloqueo vea exactamente qué
    cuentas fallaron y por cuánto."""

    def __init__(self, reporte: "ReporteCuadreSaldos") -> None:
        self.reporte = reporte
        cuentas = ", ".join(
            f"{d.origen_cuenta_id}->{d.destino_cuenta_id} "
            f"(diferencia={d.diferencia})"
            for d in reporte.discrepancias
        )
        sin_destino = ", ".join(reporte.mapeos_sin_destino)
        detalle = []
        if reporte.discrepancias:
            detalle.append(
                f"{len(reporte.discrepancias)} cuenta(s) fuera de tolerancia "
                f"(${reporte.tolerancia} MXN): [{cuentas}]"
            )
        if reporte.mapeos_sin_destino:
            detalle.append(
                f"{len(reporte.mapeos_sin_destino)} mapeo(s) migrado(s) sin "
                f"destino_cuenta_id: [{sin_destino}]"
            )
        super().__init__(
            "Cierre de migración bloqueado (REQ-MIG-012) en el periodo "
            f"[{reporte.periodo_inicio}, {reporte.periodo_fin}]: "
            + "; ".join(detalle)
        )


class DiscrepanciaSaldoCuenta(BaseModel):
    """Una cuenta migrada cuyo saldo origen y destino difieren más de la
    tolerancia permitida en el periodo verificado."""

    mapeo_id: str
    origen_cuenta_id: str
    destino_cuenta_id: str
    saldo_origen_periodo: Decimal
    saldo_destino_periodo: Decimal
    diferencia: Decimal = Field(
        description="abs(saldo_destino_periodo - saldo_origen_periodo)"
    )

    model_config = {"arbitrary_types_allowed": True}


class CuentaCuadrada(BaseModel):
    """Una cuenta migrada cuyo saldo origen y destino cuadraron dentro
    de la tolerancia."""

    mapeo_id: str
    origen_cuenta_id: str
    destino_cuenta_id: str
    saldo_origen_periodo: Decimal
    saldo_destino_periodo: Decimal
    diferencia: Decimal

    model_config = {"arbitrary_types_allowed": True}


class ParSaldoCuenta(BaseModel):
    """Saldo origen/destino ya calculados para una cuenta migrada,
    listos para que `construir_reporte_cuadre` los compare. Separar este
    tipo de `MapeoMigracionCuenta` permite construirlo a mano en pruebas
    unitarias sin tocar Postgres."""

    mapeo_id: str
    origen_cuenta_id: str
    destino_cuenta_id: str
    saldo_origen_periodo: Decimal
    saldo_destino_periodo: Decimal

    model_config = {"arbitrary_types_allowed": True}


class ReporteCuadreSaldos(BaseModel):
    """Resultado de la verificación de integridad de REQ-MIG-012 para un
    periodo dado. `cierre_permitido` es la única señal que un flujo de
    cierre de migración debe consultar antes de darse por concluido."""

    periodo_inicio: str
    periodo_fin: str
    tolerancia: Decimal
    cuentas_cuadradas: List[CuentaCuadrada] = Field(default_factory=list)
    discrepancias: List[DiscrepanciaSaldoCuenta] = Field(default_factory=list)
    mapeos_sin_destino: List[str] = Field(
        default_factory=list,
        description=(
            "IDs de mapeos migrados (aprobado/editado) sin "
            "destino_cuenta_id -- estado inconsistente."
        ),
    )

    model_config = {"arbitrary_types_allowed": True}

    @property
    def cuentas_verificadas(self) -> int:
        return len(self.cuentas_cuadradas) + len(self.discrepancias)

    @property
    def cierre_permitido(self) -> bool:
        """`True` únicamente si NINGUNA cuenta migrada quedó fuera de
        tolerancia y ningún mapeo migrado quedó sin destino. Con cero
        cuentas verificadas (nada migrado todavía) también es `True` --
        no hay nada que bloquee un cierre vacío."""
        return not self.discrepancias and not self.mapeos_sin_destino


def construir_reporte_cuadre(
    pares: Iterable[ParSaldoCuenta],
    periodo_inicio: str,
    periodo_fin: str,
    tolerancia: Decimal = TOLERANCIA_CUADRE_MXN_DEFAULT,
    mapeos_sin_destino: Optional[Sequence[str]] = None,
) -> ReporteCuadreSaldos:
    """Arma el `ReporteCuadreSaldos` a partir de saldos YA calculados por
    cuenta migrada (`ParSaldoCuenta`). No toca ninguna base de datos --
    es la pieza que se puede probar sin Postgres.

    Una diferencia se clasifica como discrepancia cuando es
    ESTRICTAMENTE mayor a la tolerancia (`> tolerancia`), tal como
    exige el criterio ("una diferencia mayor debe bloquear"): una
    diferencia igual a la tolerancia SÍ cuadra.
    """
    cuadradas: List[CuentaCuadrada] = []
    discrepancias: List[DiscrepanciaSaldoCuenta] = []

    for par in pares:
        diferencia = abs(par.saldo_destino_periodo - par.saldo_origen_periodo)
        if diferencia > tolerancia:
            discrepancias.append(
                DiscrepanciaSaldoCuenta(
                    mapeo_id=par.mapeo_id,
                    origen_cuenta_id=par.origen_cuenta_id,
                    destino_cuenta_id=par.destino_cuenta_id,
                    saldo_origen_periodo=par.saldo_origen_periodo,
                    saldo_destino_periodo=par.saldo_destino_periodo,
                    diferencia=diferencia,
                )
            )
        else:
            cuadradas.append(
                CuentaCuadrada(
                    mapeo_id=par.mapeo_id,
                    origen_cuenta_id=par.origen_cuenta_id,
                    destino_cuenta_id=par.destino_cuenta_id,
                    saldo_origen_periodo=par.saldo_origen_periodo,
                    saldo_destino_periodo=par.saldo_destino_periodo,
                    diferencia=diferencia,
                )
            )

    return ReporteCuadreSaldos(
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        tolerancia=tolerancia,
        cuentas_cuadradas=cuadradas,
        discrepancias=discrepancias,
        mapeos_sin_destino=list(mapeos_sin_destino or []),
    )


def mapeos_migrados(
    mapeos: Iterable[MapeoMigracionCuenta],
) -> List[MapeoMigracionCuenta]:
    """Filtra `mapeos` a solo los que ADR-3 considera efectivamente
    migrados (`estado=aprobado` o `estado=editado`; ver
    `migrador.py::_ESTADOS_MIGRABLES`). `pendiente`/`rechazado` nunca
    migraron ninguna cuenta y no tiene sentido "verificar su cuadre"."""
    return [m for m in mapeos if m.estado in _ESTADOS_MIGRADOS_SALDOS]


def _obtener_cuenta(conn: Any, cuenta_id: str) -> dict:
    """Lee `(tenant_id, codigo, naturaleza)` de `cuentas_contables` para
    `cuenta_id` (el PK UUID de REQ-MIG-001) vía `conn.execute(sql,
    params)` -- el mismo wrapper `?`-parametrizado que el resto de este
    archivo. Lanza `CuentaContableNoEncontradaError` si no existe."""
    row = conn.execute(
        "SELECT tenant_id, codigo, naturaleza FROM cuentas_contables "
        "WHERE cuenta_id = ?",
        (cuenta_id,),
    ).fetchone()
    if row is None:
        raise CuentaContableNoEncontradaError(
            f"cuenta_id={cuenta_id!r} no existe en cuentas_contables; no "
            "se puede calcular su saldo para el cuadre de REQ-MIG-012."
        )
    return {"tenant_id": row[0], "codigo": row[1], "naturaleza": row[2]}


def calcular_saldo_cuenta_periodo(
    conn: Any,
    tenant_id: Any,
    codigo: str,
    naturaleza: str,
    periodo_inicio: str,
    periodo_fin: str,
) -> Decimal:
    """Saldo real de una cuenta en `[periodo_inicio, periodo_fin]`
    (comparación lexicográfica de `fecha`, formato `YYYY-MM-DD`, igual
    que el resto del código de contabilidad -- ver
    `idx_asientos_fecha`/`0001_initial.py`), sumando
    `asientos_contables.monto` real de ese `tenant_id` cuyo
    `cuenta_debito`/`cuenta_credito` coincide con `codigo`.

    Misma fórmula que `ContabilidadService` (naturaleza acreedora:
    créditos − débitos; deudora: débitos − créditos) -- ver
    `b2b_ai/features/contabilidad/service.py`. Usa `Decimal` en todo el
    cálculo (reutilizando `_decimal_o_cero` de REQ-MIG-014 arriba en
    este mismo archivo), nunca `float`, para no introducir error de
    redondeo binario en un cálculo cuya tolerancia es de $0.01.
    """
    filas = conn.execute(
        "SELECT cuenta_debito, cuenta_credito, monto FROM asientos_contables "
        "WHERE tenant_id = ? AND fecha >= ? AND fecha <= ? "
        "AND (cuenta_debito = ? OR cuenta_credito = ?)",
        (tenant_id, periodo_inicio, periodo_fin, codigo, codigo),
    ).fetchall()

    total_debito = Decimal("0")
    total_credito = Decimal("0")
    for fila in filas:
        cuenta_debito, cuenta_credito, monto = fila[0], fila[1], fila[2]
        monto_dec = _decimal_o_cero(monto)
        if cuenta_debito == codigo:
            total_debito += monto_dec
        if cuenta_credito == codigo:
            total_credito += monto_dec

    if naturaleza == NaturalezaCuenta.ACREEDORA.value:
        return total_credito - total_debito
    return total_debito - total_credito


def verificar_cuadre_saldos(
    conn: Any,
    mapeos: Iterable[MapeoMigracionCuenta],
    periodo_inicio: str,
    periodo_fin: str,
    tolerancia: Decimal = TOLERANCIA_CUADRE_MXN_DEFAULT,
) -> ReporteCuadreSaldos:
    """Punto de entrada de integración de REQ-MIG-012: para cada cuenta
    efectivamente migrada (`estado=aprobado`/`editado`) en `mapeos`,
    calcula su saldo real en origen y en destino para el periodo (contra
    `conn`, real, sin mocks) y arma el reporte de cuadre. Nunca lanza
    por sí sola -- quien necesite bloquear el cierre debe usar
    `cerrar_migracion`, que sí lanza."""
    pares: List[ParSaldoCuenta] = []
    mapeos_sin_destino: List[str] = []

    for mapeo in mapeos_migrados(mapeos):
        if not mapeo.destino_cuenta_id:
            mapeos_sin_destino.append(mapeo.id)
            continue

        cuenta_origen = _obtener_cuenta(conn, mapeo.origen_cuenta_id)
        cuenta_destino = _obtener_cuenta(conn, mapeo.destino_cuenta_id)

        saldo_origen = calcular_saldo_cuenta_periodo(
            conn,
            cuenta_origen["tenant_id"],
            cuenta_origen["codigo"],
            cuenta_origen["naturaleza"],
            periodo_inicio,
            periodo_fin,
        )
        saldo_destino = calcular_saldo_cuenta_periodo(
            conn,
            cuenta_destino["tenant_id"],
            cuenta_destino["codigo"],
            cuenta_destino["naturaleza"],
            periodo_inicio,
            periodo_fin,
        )

        pares.append(
            ParSaldoCuenta(
                mapeo_id=mapeo.id,
                origen_cuenta_id=mapeo.origen_cuenta_id,
                destino_cuenta_id=mapeo.destino_cuenta_id,
                saldo_origen_periodo=saldo_origen,
                saldo_destino_periodo=saldo_destino,
            )
        )

    return construir_reporte_cuadre(
        pares,
        periodo_inicio,
        periodo_fin,
        tolerancia=tolerancia,
        mapeos_sin_destino=mapeos_sin_destino,
    )


def cerrar_migracion(
    conn: Any,
    mapeos: Iterable[MapeoMigracionCuenta],
    periodo_inicio: str,
    periodo_fin: str,
    tolerancia: Decimal = TOLERANCIA_CUADRE_MXN_DEFAULT,
) -> ReporteCuadreSaldos:
    """El único camino que un flujo de cierre de migración debe usar
    para el cuadre de saldos: corre `verificar_cuadre_saldos` y, si
    `reporte.cierre_permitido` es falso, BLOQUEA el cierre lanzando
    `CuadreSaldosNoPermiteCierreError` con el reporte completo
    (incluidas las cuentas que sí cuadraron) adjunto -- nunca cierra
    parcialmente ni deja pasar unas cuentas mientras otras siguen sin
    cuadrar."""
    reporte = verificar_cuadre_saldos(
        conn, mapeos, periodo_inicio, periodo_fin, tolerancia=tolerancia
    )
    if not reporte.cierre_permitido:
        raise CuadreSaldosNoPermiteCierreError(reporte)
    return reporte


# ---------------------------------------------------------------------------
# REQ-MIG-015 — Referencias huérfanas: 0 líneas de póliza en destino deben
# apuntar a un cuenta_id inexistente en el catálogo destino.
# ---------------------------------------------------------------------------
#
# Nota honesta sobre el mecanismo real que da esta garantía: la FK activa
# `lineas_poliza_migradas.cuenta_destino_id -> cuentas_contables(cuenta_id)`
# (migración `0013_polizas_bloqueadas`, REQ-MIG-001/009) ya hace
# ESTRUCTURALMENTE imposible insertar una línea huérfana en operación
# normal -- Postgres rechaza el INSERT antes de que exista, y por default
# (sin ON DELETE CASCADE/SET NULL) también rechaza borrar una cuenta
# destino que todavía tenga líneas migradas apuntándole. Por eso
# `migrar_poliza()` (REQ-MIG-009) puede confiar en que un
# `destino_cuenta_id` inválido revierte la transacción completa por sí
# solo. Esta verificación es una segunda capa, a nivel de aplicación, útil
# para el reporte de cierre de migración (visibilidad explícita para quien
# cierra, sin tener que interpretar un código de error de Postgres) y como
# defensa si algún día una carga masiva u otra vía de escritura evita la
# FK (p. ej. `ALTER TABLE ... DISABLE TRIGGER ALL` durante una carga
# masiva, o una migración de esquema que temporalmente la quite) -- nunca
# se asume que "la FK ya lo cubre" como excusa para no verificar en el
# cierre.

class ReferenciaHuerfanaLineaPoliza(BaseModel):
    """Una línea de `lineas_poliza_migradas` cuyo `cuenta_destino_id` no
    existe (ya no existe, o nunca existió) en `cuentas_contables`."""

    linea_id: int
    tenant_id: int
    poliza_origen_id: str
    cuenta_destino_id: str

    model_config = {"arbitrary_types_allowed": True}


class ReporteReferenciasHuerfanas(BaseModel):
    """Resultado de la verificación de REQ-MIG-015 para un tenant (y,
    opcionalmente, una póliza) dados."""

    tenant_id: int
    huerfanas: List[ReferenciaHuerfanaLineaPoliza] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def count_huerfanas(self) -> int:
        return len(self.huerfanas)

    @property
    def cierre_permitido(self) -> bool:
        """`True` únicamente si `count(huerfanas) == 0` -- el criterio
        exacto del requisito. Con 0 líneas verificadas también es
        `True` (nada que migrar todavía no bloquea un cierre vacío)."""
        return self.count_huerfanas == 0


class ReferenciasHuerfanasNoPermiteCierreError(Exception):
    """Bloquea el cierre de la migración (REQ-MIG-015): al menos una
    línea migrada en destino apunta a una cuenta que ya no existe (o
    nunca existió) en el catálogo destino. El reporte completo -- con
    cada línea huérfana identificada -- queda adjunto en `.reporte`."""

    def __init__(self, reporte: ReporteReferenciasHuerfanas) -> None:
        self.reporte = reporte
        detalle = ", ".join(
            f"linea_id={h.linea_id} poliza={h.poliza_origen_id} "
            f"cuenta_destino_id={h.cuenta_destino_id}"
            for h in reporte.huerfanas
        )
        super().__init__(
            "Cierre de migración bloqueado (REQ-MIG-015): "
            f"{reporte.count_huerfanas} línea(s) en lineas_poliza_migradas "
            f"apuntan a un cuenta_id inexistente en el catálogo destino "
            f"(tenant_id={reporte.tenant_id}): [{detalle}]"
        )


def verificar_referencias_huerfanas_en_bd(
    conn: Any, tenant_id: int
) -> ReporteReferenciasHuerfanas:
    """Consulta de solo lectura (REQ-MIG-015): un `LEFT JOIN` real de
    `lineas_poliza_migradas` contra `cuentas_contables` por
    `cuenta_destino_id = cuenta_id`, filtrando las filas donde el lado
    derecho no encontró coincidencia (`cc.cuenta_id IS NULL`) -- la
    definición literal de "referencia huérfana". Nunca lanza por sí
    sola; quien necesite bloquear el cierre debe usar
    `cerrar_verificacion_referencias_huerfanas`, que sí lanza.

    Usa el wrapper `?`-parametrizado del repo (`Database().conn`,
    compatible con SQLite y, vía `postgres_adapter.py`, con PostgreSQL
    real) -- mismo patrón que `verificar_conteo_polizas_en_bd`."""
    filas = conn.execute(
        "SELECT lpm.id, lpm.tenant_id, lpm.poliza_origen_id, "
        "lpm.cuenta_destino_id "
        "FROM lineas_poliza_migradas lpm "
        "LEFT JOIN cuentas_contables cc ON cc.cuenta_id = lpm.cuenta_destino_id "
        "WHERE lpm.tenant_id = ? AND cc.cuenta_id IS NULL",
        (tenant_id,),
    ).fetchall()

    huerfanas = [
        ReferenciaHuerfanaLineaPoliza(
            linea_id=fila[0],
            tenant_id=fila[1],
            poliza_origen_id=fila[2],
            cuenta_destino_id=str(fila[3]),
        )
        for fila in filas
    ]
    return ReporteReferenciasHuerfanas(tenant_id=tenant_id, huerfanas=huerfanas)


def cerrar_verificacion_referencias_huerfanas(
    conn: Any, tenant_id: int
) -> ReporteReferenciasHuerfanas:
    """El único camino que un flujo de cierre de migración debe usar para
    la verificación de referencias huérfanas: corre
    `verificar_referencias_huerfanas_en_bd` y, si
    `reporte.cierre_permitido` es falso, BLOQUEA el cierre lanzando
    `ReferenciasHuerfanasNoPermiteCierreError` con el reporte completo
    adjunto."""
    reporte = verificar_referencias_huerfanas_en_bd(conn, tenant_id)
    if not reporte.cierre_permitido:
        raise ReferenciasHuerfanasNoPermiteCierreError(reporte)
    return reporte
