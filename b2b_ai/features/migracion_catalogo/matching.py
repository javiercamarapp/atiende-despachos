# -*- coding: utf-8 -*-
"""
matching.py — Motor de matching para migración/fusión de catálogo de
cuentas (REQ-MIG-003, REQ-MIG-004, REQ-MIG-005).

Este módulo implementa:

  - REQ-MIG-003 (`es_match_exacto` / `evaluar_match_exacto`): único camino
    de auto-aprobación — código Y nombre normalizados idénticos entre
    origen y destino. Usa su propio par mínimo (`CuentaCatalogoPar`)
    porque el match exacto no necesita jerarquía/naturaleza.
  - REQ-MIG-004 (`es_alerta_riesgo` / `evaluar_alerta_riesgo`): marca un
    par origen/destino como `tipo_match="alerta_riesgo"` cuando EXACTAMENTE
    uno de (código normalizado, nombre normalizado) coincide — nunca
    cuando ambos coinciden (eso sería match exacto, arriba) ni cuando
    ninguno coincide (fuera de alcance: fuzzy/sin_match, REQ-MIG-005/006).
    ADR-3: un `alerta_riesgo` NUNCA nace `estado=aprobado`, sin excepción.
  - REQ-MIG-005 (`construir_match_fuzzy` y soporte): el cálculo de
    `tipo_match="fuzzy"` con un score compuesto (similitud de nombre +
    nivel jerárquico + naturaleza D/A + tipo agregado + cuenta padre) para
    un par origen/destino que ya se determinó — vía REQ-MIG-003/004
    arriba — que NO es match exacto ni alerta de riesgo. La selección del
    mejor candidato entre varios y el umbral de "sin_match" (score < 60)
    son REQ-MIG-006, tampoco implementado aquí.

Nota sobre `CuentaCatalogoPar` vs `CuentaCatalogo`: REQ-MIG-003 solo
necesita id+código+nombre para decidir igualdad exacta, mientras que
REQ-MIG-004/005 necesitan además nivel/naturaleza/tipo/padre. Son dos
formas de entrada distintas para necesidades distintas, no una jerarquía
de herencia — cada función de este módulo declara con cuál trabaja.

Regla dura (ADR-3, docs/BLUEPRINT-AGENTES-FISCALES.md §3 y §7): ningún
resultado fuzzy puede nacer con `estado` distinto de `pendiente`, sin
importar qué tan alto sea el score. Un score de 99 — o incluso 100, si
todos los factores coincidieran por casualidad — NUNCA autoriza saltarse
la revisión humana; esa es justamente la diferencia entre "fuzzy" y
"exacto". `construir_match_fuzzy` hard-codea `estado=PENDIENTE` sin leer
el score para decidirlo, precisamente para que esa regla no dependa de
que nadie "se acuerde" de respetarla en el siguiente cambio.

Adaptado de `b2b_ai/features/reconciliation_agent/matching_engine.py`
(normalización de texto + rapidfuzz `fuzz`), pero para cuentas contables
en vez de movimientos bancarios: aquí se compara nombre + jerarquía +
naturaleza contable en vez de monto + fecha + descripción.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

from rapidfuzz import fuzz

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)


def normalizar_texto(valor: Optional[str]) -> str:
    """Quita acentos, colapsa espacios y sube a mayúsculas.

    Transformación compartida por `normalizar_nombre` y `normalizar_codigo`
    (REQ-MIG-003: "código normalizado (sin acentos/mayúsculas/espacios
    colapsados) Y nombre normalizado").
    """
    s = valor or ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def normalizar_nombre(valor: Optional[str]) -> str:
    """Nombre normalizado para comparación de igualdad exacta (REQ-MIG-003)."""
    return normalizar_texto(valor)


def normalizar_codigo(valor: Optional[str]) -> str:
    """Código normalizado para comparación de igualdad exacta (REQ-MIG-003).

    Solo colapsa espacios y quita acentos/mayúsculas — a propósito NO
    quita guiones ni otra puntuación del código, para no volver "iguales"
    dos códigos que un contador consideraría distintos (p.ej. "102-001"
    vs "1020 01"). Distinto del `_normalizar_codigo` interno de más abajo,
    que sí quita guiones/espacios porque lo usan REQ-MIG-004/005/006 para
    comparar el código de una cuenta PADRE de forma más laxa (ahí solo
    importa si dos catálogos usan el mismo identificador con formato
    distinto).
    """
    return normalizar_texto(valor)


@dataclass(frozen=True)
class CuentaCatalogoPar:
    """Cuenta mínima (id + código + nombre) para evaluar match exacto
    (REQ-MIG-003). No lleva jerarquía/naturaleza porque el match exacto no
    las necesita — eso es lo que distingue "exacto" de "fuzzy"
    (`CuentaCatalogo`, REQ-MIG-005/006).
    """

    cuenta_id: str
    codigo: str
    nombre: str


def es_match_exacto(origen: CuentaCatalogoPar, destino: CuentaCatalogoPar) -> bool:
    """True únicamente si código normalizado Y nombre normalizado son
    idénticos entre origen y destino, y ninguno de los dos está vacío.

    Dos códigos (o nombres) vacíos "coinciden" como cadenas, pero un campo
    vacío no es evidencia real de que dos cuentas sean la misma cuenta —
    por eso se exige explícitamente que no estén vacíos.
    """
    codigo_o = normalizar_codigo(origen.codigo)
    codigo_d = normalizar_codigo(destino.codigo)
    nombre_o = normalizar_nombre(origen.nombre)
    nombre_d = normalizar_nombre(destino.nombre)

    if not codigo_o or not nombre_o or not codigo_d or not nombre_d:
        return False

    return codigo_o == codigo_d and nombre_o == nombre_d


def evaluar_match_exacto(
    origen: CuentaCatalogoPar, destino: CuentaCatalogoPar
) -> Optional[MapeoMigracionCuenta]:
    """Único camino de auto-aprobación (REQ-MIG-003 / ADR-3): produce un
    `MapeoMigracionCuenta` con `tipo_match=EXACTO` y `estado=APROBADO`
    (sin `aprobado_por`/`aprobado_en` porque no hubo intervención humana)
    cuando `es_match_exacto` es `True`; en cualquier otro caso devuelve
    `None` — nunca un mapeo a medio aprobar.
    """
    if not es_match_exacto(origen, destino):
        return None

    return MapeoMigracionCuenta(
        origen_cuenta_id=origen.cuenta_id,
        destino_cuenta_id=destino.cuenta_id,
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
        nota="código y nombre normalizados idénticos: auto-aprobado (REQ-MIG-003 / ADR-3)",
    )


# ---------------------------------------------------------------------------
# Ponderaciones del score compuesto (deben sumar 1.0)
# ---------------------------------------------------------------------------
# El nombre pesa más porque es la señal más informativa de si dos cuentas
# son "la misma" cuenta contable; los otros cuatro factores son señales de
# consistencia estructural que refuerzan (o restan confianza a) esa
# similitud de nombre — nunca la reemplazan ni, por sí solas, producen un
# match.
PESO_NOMBRE = 0.50
PESO_NIVEL = 0.15
PESO_NATURALEZA = 0.15
PESO_TIPO_AGREGADO = 0.10
PESO_CUENTA_PADRE = 0.10

_SUMA_PESOS = (
    PESO_NOMBRE + PESO_NIVEL + PESO_NATURALEZA + PESO_TIPO_AGREGADO + PESO_CUENTA_PADRE
)
assert abs(_SUMA_PESOS - 1.0) < 1e-9, "las ponderaciones del score compuesto deben sumar 1.0"


@dataclass(frozen=True)
class CuentaCatalogo:
    """Representación mínima de una cuenta del catálogo contable para
    efectos de matching de migración.

    No es el modelo de persistencia de `cuentas_contables` (eso es
    REQ-MIG-001); son solo los campos que el score compuesto de
    REQ-MIG-005 necesita comparar entre una cuenta de origen y una de
    destino.
    """

    id: str
    codigo: str
    nombre: str
    nivel: int
    naturaleza: str  # "D" (deudora) o "A" (acreedora)
    tipo_agregado: str  # p.ej. "Activo", "Pasivo", "Capital", "Ingreso", "Gasto"
    cuenta_padre_codigo: Optional[str] = None


def _normalizar_texto(valor: Optional[str]) -> str:
    """Quita acentos, colapsa espacios y sube a mayúsculas."""
    s = valor or ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _normalizar_codigo(valor: Optional[str]) -> str:
    return _normalizar_texto(valor).replace(" ", "").replace("-", "")


def similitud_nombre(nombre_origen: str, nombre_destino: str) -> float:
    """Similitud de nombre (0-100) vía rapidfuzz `token_sort_ratio`,
    insensible a acentos, mayúsculas y al orden de las palabras."""
    a = _normalizar_texto(nombre_origen)
    b = _normalizar_texto(nombre_destino)
    return float(fuzz.token_sort_ratio(a, b))


# ---------------------------------------------------------------------------
# REQ-MIG-004 — alerta de riesgo (código XOR nombre coincide)
# ---------------------------------------------------------------------------

def _codigo_coincide(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    a = _normalizar_codigo(origen.codigo)
    b = _normalizar_codigo(destino.codigo)
    return bool(a) and a == b


def _nombre_coincide(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    a = _normalizar_texto(origen.nombre)
    b = _normalizar_texto(destino.nombre)
    return bool(a) and a == b


def es_alerta_riesgo(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    """True cuando EXACTAMENTE uno de (código, nombre) normalizados
    coincide entre origen y destino (REQ-MIG-004).

    False cuando ambos coinciden (match exacto, REQ-MIG-003) y False
    cuando ninguno coincide (fuera de alcance de este módulo: fuzzy/
    sin_match, REQ-MIG-005/006). Un código o nombre que normalice a
    cadena vacía en cualquiera de los dos lados nunca cuenta como
    "coincidencia": datos faltantes no son evidencia de riesgo de
    reclasificación, son datos faltantes.
    """
    return _codigo_coincide(origen, destino) != _nombre_coincide(origen, destino)


def evaluar_alerta_riesgo(
    origen: CuentaCatalogo,
    destino: CuentaCatalogo,
) -> Optional[MapeoMigracionCuenta]:
    """REQ-MIG-004: marca un par como `tipo_match=ALERTA_RIESGO` cuando el
    código coincide pero el nombre difiere, o el nombre coincide pero el
    código difiere — NUNCA auto-aprobado, sin excepción.

    Devuelve `None` cuando el par es (o sería) un match exacto —
    REQ-MIG-003, no implementado en este módulo — o cuando ni código ni
    nombre coinciden (fuera de alcance: REQ-MIG-005/006).

    ADR-3: esta función jamás produce `estado=APROBADO`. La línea
    `estado=EstadoMapeoMigracion.PENDIENTE` está explícita (no depende
    del default del modelo) y el `assert` final es una segunda barrera
    contra que un cambio futuro la vuelva a colar por accidente.
    """
    if not es_alerta_riesgo(origen, destino):
        return None

    codigo_coincide = _codigo_coincide(origen, destino)
    campo_coincide = "código" if codigo_coincide else "nombre"
    campo_difiere = "nombre" if codigo_coincide else "código"

    mapeo = MapeoMigracionCuenta(
        origen_cuenta_id=origen.id,
        destino_cuenta_id=destino.id,
        tipo_match=TipoMatchMigracion.ALERTA_RIESGO,
        score=50.0,
        estado=EstadoMapeoMigracion.PENDIENTE,
        nota=(
            f"alerta de riesgo: coincide el {campo_coincide} pero difiere el "
            f"{campo_difiere} (origen: codigo={origen.codigo!r} nombre={origen.nombre!r}; "
            f"destino: codigo={destino.codigo!r} nombre={destino.nombre!r}). "
            "Requiere aprobación humana explícita antes de usarse para migrar "
            "pólizas (ADR-3, REQ-MIG-004; ver REQ-MIG-007 para el único camino "
            "de aprobación válido)."
        ),
    )
    assert mapeo.estado == EstadoMapeoMigracion.PENDIENTE, (
        "invariante ADR-3/REQ-MIG-004 violada: un alerta_riesgo nunca puede "
        "nacer aprobado"
    )
    return mapeo


def _coincide_nivel(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    return origen.nivel == destino.nivel


def _coincide_naturaleza(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    return _normalizar_texto(origen.naturaleza) == _normalizar_texto(destino.naturaleza)


def _coincide_tipo_agregado(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    return _normalizar_texto(origen.tipo_agregado) == _normalizar_texto(destino.tipo_agregado)


def _coincide_cuenta_padre(origen: CuentaCatalogo, destino: CuentaCatalogo) -> bool:
    padre_o = _normalizar_codigo(origen.cuenta_padre_codigo)
    padre_d = _normalizar_codigo(destino.cuenta_padre_codigo)
    if not padre_o or not padre_d:
        # Ninguno de los dos declara padre (p.ej. ambas de nivel 1, o el
        # dato simplemente no vino en el catálogo): no es evidencia a
        # favor ni en contra, así que no suma puntos.
        return False
    return padre_o == padre_d


def calcular_score_compuesto(origen: CuentaCatalogo, destino: CuentaCatalogo) -> float:
    """Score compuesto (0-100) para un par origen/destino sin match
    exacto ni alerta de riesgo (REQ-MIG-005).

        score = similitud_nombre(origen, destino)   * PESO_NOMBRE
              + (100 si coincide el nivel)           * PESO_NIVEL
              + (100 si coincide la naturaleza D/A)  * PESO_NATURALEZA
              + (100 si coincide el tipo agregado)   * PESO_TIPO_AGREGADO
              + (100 si coincide la cuenta padre)    * PESO_CUENTA_PADRE

    Devuelve siempre un valor en [0, 100] (ver `MapeoMigracionCuenta.score`).
    """
    nombre_score = similitud_nombre(origen.nombre, destino.nombre)
    nivel_score = 100.0 if _coincide_nivel(origen, destino) else 0.0
    naturaleza_score = 100.0 if _coincide_naturaleza(origen, destino) else 0.0
    tipo_score = 100.0 if _coincide_tipo_agregado(origen, destino) else 0.0
    padre_score = 100.0 if _coincide_cuenta_padre(origen, destino) else 0.0

    score = (
        nombre_score * PESO_NOMBRE
        + nivel_score * PESO_NIVEL
        + naturaleza_score * PESO_NATURALEZA
        + tipo_score * PESO_TIPO_AGREGADO
        + padre_score * PESO_CUENTA_PADRE
    )
    # Clamp defensivo: con las ponderaciones de arriba (suman 1.0, cada
    # factor topa en 100) el resultado matemáticamente nunca debería
    # salirse de [0, 100], pero `MapeoMigracionCuenta.score` lo exige
    # (`ge=0, le=100`) y preferimos no dejar que un futuro ajuste de
    # pesos rompa esa garantía en silencio con un ValidationError río
    # abajo.
    return round(min(100.0, max(0.0, score)), 2)


def construir_match_fuzzy(
    origen: CuentaCatalogo,
    destino: CuentaCatalogo,
) -> MapeoMigracionCuenta:
    """Construye el `MapeoMigracionCuenta` fuzzy para un par origen/destino
    que ya se determinó (fuera de esta función — REQ-MIG-003/004) que no
    es match exacto ni alerta de riesgo.

    ADR-3 / REQ-MIG-005: el resultado SIEMPRE nace con
    `estado=EstadoMapeoMigracion.PENDIENTE`, sin excepción — incluso si
    `calcular_score_compuesto` devuelve 99 o 100. El score es una señal
    para el humano que revisa el mapeo, nunca una autorización para
    saltarse esa revisión.
    """
    score = calcular_score_compuesto(origen, destino)
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen.id,
        destino_cuenta_id=destino.id,
        tipo_match=TipoMatchMigracion.FUZZY,
        score=score,
        # No condicionar esta línea al valor de `score` bajo ninguna
        # circunstancia: ver ADR-3 en el docstring del módulo.
        estado=EstadoMapeoMigracion.PENDIENTE,
        nota=(
            f"match fuzzy score={score:.2f} "
            f"('{origen.codigo} {origen.nombre}' -> "
            f"'{destino.codigo} {destino.nombre}'); requiere revisión humana"
        ),
    )


# ---------------------------------------------------------------------------
# REQ-MIG-006 — sin_match: ningún candidato alcanza el umbral de score
# ---------------------------------------------------------------------------

UMBRAL_SIN_MATCH = 60.0
"""Score mínimo (0-100, `calcular_score_compuesto`) para que un candidato
deje de considerarse "sin_match" (REQ-MIG-006). Por debajo de este umbral
ningún candidato "cuenta" como correspondencia posible."""

NOTA_SIN_MATCH = "cuenta nueva a crear en destino"
"""Nota fija exigida por REQ-MIG-006 para toda cuenta origen sin match."""


def clasificar_cuenta_origen(
    origen: CuentaCatalogo,
    candidatos: Sequence[CuentaCatalogo],
    umbral_sin_match: float = UMBRAL_SIN_MATCH,
) -> MapeoMigracionCuenta:
    """Clasifica una cuenta ORIGEN contra TODOS los candidatos de un
    catálogo DESTINO (REQ-MIG-006), combinando los niveles ya implementados
    en este módulo (alerta_riesgo, fuzzy) más el caso "ningún candidato es
    suficientemente parecido":

      1. Exacto: código Y nombre normalizados idénticos -> auto-aprobado,
         score=100 (REQ-MIG-003; reevaluado aquí de forma inline con los
         mismos helpers `_codigo_coincide`/`_nombre_coincide` de este
         módulo, porque `evaluar_match_exacto` vive en un módulo separado
         que el desarrollo paralelo de este blueprint todavía no expone
         aquí — ver nota abajo).
      2. Alerta de riesgo: código XOR nombre coincide
         (`evaluar_alerta_riesgo`, REQ-MIG-004) -> pendiente, nunca
         auto-aprobado.
      3. Fuzzy: mejor `calcular_score_compuesto` (REQ-MIG-005) entre los
         candidatos restantes, SI alcanza `umbral_sin_match`
         (`construir_match_fuzzy`).
      4. Sin match (REQ-MIG-006, este requisito): si no hay candidatos, o
         ninguno de los candidatos restantes alcanza `umbral_sin_match` de
         score compuesto -> `tipo_match=SIN_MATCH`,
         `destino_cuenta_id=None` (NUNCA se inventa un destino) y
         `nota=NOTA_SIN_MATCH`.

    El umbral se compara con `>=`: un candidato con score exactamente igual
    a `umbral_sin_match` SÍ cuenta como match (deja de ser "sin_match");
    solo por debajo del umbral se considera insuficiente.
    """
    for destino in candidatos:
        if _codigo_coincide(origen, destino) and _nombre_coincide(origen, destino):
            return MapeoMigracionCuenta(
                origen_cuenta_id=origen.id,
                destino_cuenta_id=destino.id,
                tipo_match=TipoMatchMigracion.EXACTO,
                score=100.0,
                estado=EstadoMapeoMigracion.APROBADO,
                nota="match exacto: código y nombre normalizados idénticos entre origen y destino",
            )

    for destino in candidatos:
        alerta = evaluar_alerta_riesgo(origen, destino)
        if alerta is not None:
            return alerta

    mejor_destino: Optional[CuentaCatalogo] = None
    mejor_score = -1.0
    for destino in candidatos:
        if _codigo_coincide(origen, destino) or _nombre_coincide(origen, destino):
            # Ya se resolvió arriba (exacto o alerta_riesgo); un candidato
            # con una sola coincidencia estructural no debe además competir
            # por el mejor score fuzzy. El bucle de alerta_riesgo ya habría
            # retornado antes de llegar aquí — esta guarda es defensiva.
            continue
        score = calcular_score_compuesto(origen, destino)
        if score > mejor_score:
            mejor_score = score
            mejor_destino = destino

    if mejor_destino is None or mejor_score < umbral_sin_match:
        return MapeoMigracionCuenta(
            origen_cuenta_id=origen.id,
            destino_cuenta_id=None,
            tipo_match=TipoMatchMigracion.SIN_MATCH,
            score=round(max(mejor_score, 0.0), 2),
            estado=EstadoMapeoMigracion.PENDIENTE,
            nota=NOTA_SIN_MATCH,
        )

    return construir_match_fuzzy(origen, mejor_destino)
