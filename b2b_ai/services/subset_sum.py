# -*- coding: utf-8 -*-
"""
subset_sum.py — Búsqueda de subconjuntos cuya suma cae dentro de una banda,
en CENTAVOS (enteros, nunca floats).

Usado por `BankReconciliation._pass_group` (REQ-CONC-003) para el cruce
N-a-1 de conciliación bancaria: varias facturas suman UN solo depósito.

REQ-CONC-006 (este módulo): cuando el número de candidatos supera
`MITM_THRESHOLD` (40), el algoritmo debe usar "meet-in-the-middle" —
partir el universo en dos mitades, generar las sumas alcanzables de cada
mitad y buscar por rango en la otra (ordenada) — en vez de la enumeración
de fuerza bruta (`itertools.combinations` sobre TODO el universo, que es
O(2^n) en la práctica y se vuelve intratable pasado ese tamaño). Con
<= 40 candidatos, la fuerza bruta ya es tratable en el tiempo de una
request y se usa tal cual: mismo resultado, camino más simple.

Regla dura del blueprint (nunca aplicable aquí de forma distinta a como ya
lo hace `bank_reconciliation.py`):
  - Si NINGÚN subconjunto cae en la banda, se devuelve lista vacía. Nunca
    se inventa el candidato "más parecido" (ADR-1).
  - Si 2 o más subconjuntos DISTINTOS caen en la banda (ambigüedad real),
    se devuelven TODOS — nunca se trunca a 1 en silencio ni se elige uno
    arbitrariamente. Quien llama decide qué hacer (ADR-2): en
    `bank_reconciliation.py` eso significa dejar el caso para revisión
    humana explícita, nunca auto-resolverlo.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from itertools import combinations
from typing import Any, List, Sequence, Tuple, Union

# Umbral de candidatos a partir del cual se usa meet-in-the-middle en vez de
# fuerza bruta. Ver REQ-CONC-006.
MITM_THRESHOLD = 40

Number = Union[int, float, str, Decimal]


def find_subset_sums(
    items: Sequence[Tuple[Any, int]],
    target_cents: int,
    min_size: int = 2,
    max_size: int = 15,
    tolerance_cents: int = 0,
) -> List[List[Any]]:
    """Encuentra TODOS los subconjuntos de `items` cuya suma cae en la banda
    `[target_cents - tolerance_cents, target_cents + tolerance_cents]`.

    `items` es una secuencia de pares `(payload, monto_centavos)` — el
    payload es opaco (típicamente la factura/dict original); solo el monto
    en centavos (int) participa en la suma. Los montos deben ser positivos
    y enteros (centavos); valores <= 0 o None se descartan silenciosamente
    (no son candidatos válidos de un cobro/factura).

    Con `tolerance_cents=0` (default) equivale a una suma EXACTA — el uso
    actual de `bank_reconciliation.py`. Un `tolerance_cents > 0` permite
    reutilizar el mismo algoritmo para una banda simétrica alrededor del
    monto objetivo (p. ej. una futura banda de comisión de terminal,
    REQ-CONC-004, que no forma parte de este cambio).

    Nunca inventa: si ningún subconjunto cae en la banda, devuelve `[]`.
    Nunca trunca en silencio: si 2+ subconjuntos distintos caen en la
    banda, devuelve TODOS (REQ-CONC-007) — la decisión de qué hacer con
    una ambigüedad real es de quien llama (ADR-2), no de este módulo.

    Dispatcha a `_meet_in_the_middle` cuando `len(items) > MITM_THRESHOLD`
    (REQ-CONC-006); si no, usa `_brute_force` (equivalente, más simple).
    """
    limpio = [(payload, monto) for payload, monto in items
              if monto is not None and monto > 0]
    n = len(limpio)
    min_size = max(2, int(min_size))   # tamaño 1 ya lo cubre el match 1-a-1
    max_size = max(min_size, int(max_size))
    if n < min_size:
        return []

    tol = max(0, int(tolerance_cents))
    low = int(target_cents) - tol
    high = int(target_cents) + tol
    if high < 0:
        return []
    low = max(low, 0)

    if n > MITM_THRESHOLD:
        return _meet_in_the_middle(limpio, low, high, min_size, max_size)
    return _brute_force(limpio, low, high, min_size, max_size)


class SubsetSumBudgetExceeded(RuntimeError):
    """Se agotó el presupuesto de exploración (`_MAX_NODES`) antes de poder
    enumerar TODOS los subconjuntos candidatos.

    Enumerar (no solo decidir si existe) cada subconjunto que cae en la
    banda es, en el peor caso, combinatoriamente costoso — incluso con
    meet-in-the-middle — cuando la banda es ancha en relación a los
    montos (p. ej. muchas facturas de monto similar y una banda que cae
    cerca de la mitad de su suma total): ahí la poda por `high` casi no
    corta nada y ni la fuerza bruta ni MITM terminan en un tiempo
    razonable. En vez de colgar el pipeline sin límite, la búsqueda se
    aborta a este techo y levanta esta excepción explícita — quien llama
    (`_pass_group`) debe tratarlo como "no se pudo evaluar
    automáticamente este movimiento", NUNCA como una lista vacía
    silenciosa (una lista vacía real significa "se buscó exhaustivamente
    y no hay match"; esto significa "no se terminó de buscar" — son
    señales distintas y no deben confundirse, ver ADR-1).
    """


# Techo de nodos de DFS explorados por búsqueda (fuerza bruta o cada mitad
# de meet-in-the-middle) antes de abortar con `SubsetSumBudgetExceeded`.
# Un nodo ~ una llamada a la función interna de recursión/combinación;
# 2,000,000 nodos toma del orden de 1-2s en Python puro, dejando margen
# bajo el límite de 5s de REQ-CONC-006 incluso sumando ambas mitades.
_MAX_NODES = 2_000_000


# ---------------------------------------------------------------------------
# Fuerza bruta (universo pequeño, <= MITM_THRESHOLD candidatos)
# ---------------------------------------------------------------------------

def _brute_force(items, low, high, min_size, max_size) -> List[List[Any]]:
    """Enumera TODAS las combinaciones de tamaño `min_size..max_size` y
    conserva las que caen en `[low, high]`. Correcto y simple; su costo es
    combinatorio (`sum_k C(n, k)`), tratable solo para universos pequeños —
    de ahí el dispatch a `_meet_in_the_middle` pasado `MITM_THRESHOLD`.

    Levanta `SubsetSumBudgetExceeded` si supera `_MAX_NODES` combinaciones
    visitadas sin terminar — nunca se queda colgado sin límite (ver
    docstring de `SubsetSumBudgetExceeded`)."""
    n = len(items)
    limite = min(max_size, n)
    out = []
    visitados = 0
    for size in range(min_size, limite + 1):
        for combo in combinations(items, size):
            visitados += 1
            if visitados > _MAX_NODES:
                raise SubsetSumBudgetExceeded(
                    f"_brute_force excedió {_MAX_NODES} combinaciones "
                    f"visitadas (n={n}, tamaños {min_size}..{limite}).")
            s = sum(monto for _, monto in combo)
            if low <= s <= high:
                out.append([payload for payload, _ in combo])
    return out


# ---------------------------------------------------------------------------
# Meet-in-the-middle (universo grande, > MITM_THRESHOLD candidatos)
# ---------------------------------------------------------------------------

def _enumerate_half(
    items: Sequence[Tuple[Any, int]], high: int, max_size: int
) -> List[Tuple[int, int, Tuple[int, ...]]]:
    """Enumera todos los subconjuntos NO vacíos de `items` (0..max_size
    elementos) cuya suma no excede `high`, vía DFS con poda.

    Los montos se ordenan ascendente antes del DFS: en cuanto sumar el
    siguiente monto (el más chico de los que quedan) excede `high`, TODOS
    los montos restantes también lo excederían (son >= el actual), así que
    la exploración corta ahí — no solo se descarta ese elemento, se corta
    el resto de ese nivel. Es la poda que hace tratable cada mitad EN EL
    CASO TÍPICO; en el peor caso (banda ancha relativa a los montos) esa
    poda apenas corta nada, así que además se acota a `_MAX_NODES` nodos
    visitados, levantando `SubsetSumBudgetExceeded` si se excede — nunca
    se explora sin límite (ver docstring de `SubsetSumBudgetExceeded`).

    Devuelve una lista de `(suma, tamaño, índices_en_items)` — los índices
    son posiciones dentro de `items` (0-based, local a esa mitad).
    """
    orden = sorted(range(len(items)), key=lambda i: items[i][1])
    montos = [items[i][1] for i in orden]
    n = len(montos)
    out: List[Tuple[int, int, Tuple[int, ...]]] = []
    elegidos: List[int] = []
    visitados = 0

    def dfs(start: int, suma_actual: int) -> None:
        nonlocal visitados
        visitados += 1
        if visitados > _MAX_NODES:
            raise SubsetSumBudgetExceeded(
                f"_enumerate_half excedió {_MAX_NODES} nodos visitados "
                f"(n={n}, max_size={max_size}).")
        if elegidos:
            out.append((suma_actual, len(elegidos), tuple(elegidos)))
        if len(elegidos) == max_size:
            return
        for i in range(start, n):
            nueva_suma = suma_actual + montos[i]
            if nueva_suma > high:
                break   # ascendente: ningún elemento posterior servirá
            elegidos.append(orden[i])
            dfs(i + 1, nueva_suma)
            elegidos.pop()

    dfs(0, 0)
    return out


def _meet_in_the_middle(
    items: List[Tuple[Any, int]], low: int, high: int,
    min_size: int, max_size: int,
) -> List[List[Any]]:
    """Meet-in-the-middle: parte `items` en dos mitades, genera las sumas
    alcanzables de cada una (`_enumerate_half`), ordena las sumas de la
    mitad izquierda y busca por rango (`bisect`) el complemento de cada
    suma de la mitad derecha que caiga en `[low, high]` combinada.

    Reduce la exploración de `O(2^n)` (fuerza bruta sobre el universo
    completo) a `O(2^(n/2))` por mitad más `O(m log m)` para combinar —
    la mejora que REQ-CONC-006 exige a partir de `MITM_THRESHOLD`
    candidatos.

    Reporta TODAS las combinaciones válidas (izquierda × derecha) dentro
    de la banda y del tamaño combinado permitido — nunca solo la primera.

    Incluye explícitamente el subconjunto VACÍO (suma 0, 0 elementos) como
    contribución válida de cada mitad: un subconjunto solución puede vivir
    ENTERO dentro de una sola mitad (0 elementos tomados de la otra) — sin
    esta entrada, `_enumerate_half` (que solo enumera subconjuntos NO
    vacíos) haría que esos casos se perdieran en silencio, violando la
    regla de nunca reportar de menos.
    """
    n = len(items)
    mid = n // 2
    left_items = items[:mid]
    right_items = items[mid:]

    vacio = (0, 0, ())
    left = _enumerate_half(left_items, high, max_size) + [vacio]
    right = _enumerate_half(right_items, high, max_size) + [vacio]

    left.sort(key=lambda x: x[0])
    left_sums = [s for s, _, _ in left]

    out: List[List[Any]] = []
    for r_sum, r_size, r_idx in right:
        needed_low = low - r_sum
        needed_high = high - r_sum
        if needed_high < 0:
            continue
        lo = bisect_left(left_sums, needed_low)
        hi = bisect_right(left_sums, needed_high)
        for j in range(lo, hi):
            _, l_size, l_idx = left[j]
            total_size = l_size + r_size
            if total_size < min_size or total_size > max_size:
                continue
            combo_indices = list(l_idx) + [mid + k for k in r_idx]
            out.append([items[i][0] for i in combo_indices])
    return out


# ---------------------------------------------------------------------------
# REQ-CONC-004 — banda de aceptación por grossing-up de comisión
# ---------------------------------------------------------------------------
#
# `find_subset_sums` (arriba) resuelve una banda SIMÉTRICA alrededor de un
# monto objetivo (`target ± tolerance`), suficiente para el cruce exacto de
# REQ-CONC-003 y para la optimización de tamaño de REQ-CONC-006/007. La
# banda real que exige REQ-CONC-004 para conciliar un depósito NETO contra
# facturas en BRUTO es ASIMÉTRICA y nace de un "grossing-up": dado el neto
# depositado `A` y la tasa de comisión mínima `r_min` del perfil de
# liquidación (Clip, TPV, etc.), un subconjunto de facturas `S` es un
# candidato válido si
#
#     A <= sum(S) <= A / (1 - r_min)
#
# El bruto facturado nunca puede ser menor que el neto ya depositado (un
# banco no "regala" el excedente de su propia comisión), y el techo es el
# grossing-up de `A` asumiendo la comisión mínima posible del perfil.
#
# Esta sección añade esa banda específica sin duplicar la lógica de
# búsqueda: `find_matching_subsets` calcula `[A, A/(1-r_min)]` en centavos
# y reutiliza los mismos enumeradores exhaustivos de arriba (`_brute_force`
# / `_meet_in_the_middle`) para reportar TODOS los subconjuntos que caen en
# esa banda.
#
# Historial (REQ-CONC-007): la primera versión de `find_matching_subsets`
# usaba un DP de sumas alcanzables con UN backpointer por suma
# (`_build_reachable_dp`/`_reconstruct`, ya eliminados de este módulo).
# Esa forma de backpointer solo reconstruye UN camino por cada suma
# alcanzable — si 2 subconjuntos DISJUNTOS distintos suman exactamente lo
# mismo (p. ej. 100+200 y 150+150, ambos 300), el DP de un solo backpointer
# descarta en silencio el segundo camino al marcar esa suma como ya
# alcanzable (`if reachable[s]: continue`), violando la regla dura de
# nunca truncar una ambigüedad real a 1 resultado (ADR-2). Reutilizar los
# enumeradores exhaustivos de `find_subset_sums` — que sí recorren cada
# combinación por separado, sin colapsar las que comparten suma — corrige
# ese hueco sin reintroducir una segunda implementación paralela.
#
# Mismas reglas duras que el resto del módulo (ADR-1/ADR-2): 0 candidatos
# dentro de la banda -> `[]`, nunca se inventa uno; 2+ subconjuntos DISTINTOS
# dentro de la banda -> se devuelven TODOS (misma suma o no), nunca se
# auto-resuelve la ambigüedad ni se trunca en silencio (REQ-CONC-007).


def to_cents(value: Number) -> int:
    """Convierte un monto monetario (pesos) a centavos ENTEROS.

    Nunca opera directamente sobre `float`: si `value` llega como float
    (p. ej. `20192.0`), se convierte primero a texto (`str(value)`) antes
    de construir el `Decimal`, para no arrastrar el error de
    representación binaria del float hacia el `Decimal` (construir
    `Decimal(20192.0)` directamente sí heredaría ese error; `Decimal(str(
    20192.0))` no). El redondeo es HALF_UP al centavo más cercano, para
    tolerar entradas con más de 2 decimales; el uso esperado normal es
    siempre con exactamente 2 decimales.
    """
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    cents = (d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _to_rate(value: Number) -> Decimal:
    r = value if isinstance(value, Decimal) else Decimal(str(value))
    if r < 0 or r >= 1:
        raise ValueError(
            f"Tasa de comisión fuera de rango válido [0, 1): {r}")
    return r


def grossed_up_ceiling_cents(net_cents: int, r_min: Number) -> int:
    """Bruto máximo aceptable, en centavos, a partir del neto depositado.

    Fórmula: `net_cents / (1 - r_min)`, redondeada hacia ARRIBA
    (ROUND_CEILING) para no rechazar por redondeo un candidato que cae
    justo en el borde superior de la banda.
    """
    if net_cents < 0:
        raise ValueError("net_cents no puede ser negativo.")
    r = _to_rate(r_min)
    gross = Decimal(net_cents) / (Decimal(1) - r)
    return int(gross.to_integral_value(rounding=ROUND_CEILING))


def is_within_band(sum_cents: int, net_cents: int, r_min: Number) -> bool:
    """Chequeo directo de la banda de aceptación para una suma ya
    calculada: `net_cents <= sum_cents <= net_cents / (1 - r_min)`.

    Útil para validar un subconjunto puntual (p. ej. propuesto por otra
    parte del pipeline) sin correr la búsqueda completa del DP.
    """
    if net_cents < 0 or sum_cents < 0:
        raise ValueError("Los montos en centavos no pueden ser negativos.")
    max_cents = grossed_up_ceiling_cents(net_cents, r_min)
    return net_cents <= sum_cents <= max_cents


@dataclass(frozen=True)
class SubsetCandidate:
    """Un subconjunto candidato de facturas cuya suma bruta cae dentro de
    la banda de aceptación de un depósito neto (REQ-CONC-004)."""
    indices: tuple
    sum_cents: int

    def items(self, amounts: Sequence) -> list:
        """Devuelve los elementos originales de `amounts` que componen
        este subconjunto (usando los índices guardados)."""
        return [amounts[i] for i in self.indices]


def find_matching_subsets(amounts: Sequence[Number], net_deposit: Number,
                          r_min: Number, max_size: int = None,
                          ) -> List[SubsetCandidate]:
    """Busca los subconjuntos de `amounts` cuya suma bruta cae dentro de
    la banda `[A, A / (1 - r_min)]`, donde `A` es el depósito NETO
    observado en el banco y `r_min` la tasa de comisión mínima del
    perfil de liquidación aplicable (p. ej. `0.036` para Clip).

    Nunca inventa un match (ADR-1): si ningún subconjunto cae en la
    banda, devuelve `[]`.

    Nunca auto-resuelve ambigüedad (ADR-2), y nunca trunca en silencio
    (REQ-CONC-007): se devuelven TODOS los subconjuntos DISTINTOS —de
    conjuntos de facturas, no solo de sumas— cuya suma cae en la banda,
    incluyendo el caso en que 2 (o más) subconjuntos DISJUNTOS distintos
    caen exactamente en la misma suma. La decisión de cuál aplicar, si
    alguna, es de un humano; este módulo nunca elige "el más probable"
    por su cuenta.

    Se excluye únicamente el subconjunto vacío (suma 0). Por defecto
    (`max_size=None`) tampoco se impone un tamaño máximo de subconjunto ni
    se excluyen subconjuntos de 1 solo elemento — esas restricciones
    (REQ-CONC-005) son responsabilidad de la capa que orquesta los pases
    de conciliación (`_pass_group` en `bank_reconciliation.py`), que puede
    pasar `max_size` explícitamente (así lo hace `_pass_group`, con su
    propio techo `MAX_GROUP_SIZE`).

    `max_size` importa también para el rendimiento (REQ-CONC-006): sin
    techo de tamaño, ENUMERAR (no solo decidir si existe) cada subconjunto
    que cae en la banda es combinatoriamente costoso incluso con
    meet-in-the-middle cuando la banda es ancha relativa a los montos
    (p. ej. muchas facturas pequeñas y un depósito grande) — la poda por
    `high` sola no basta. Pasar el `max_size` real del negocio (facturas
    agrupadas manualmente rara vez pasan de 15) acota esa exploración sin
    cambiar el resultado para el uso real.
    """
    amounts_cents = [to_cents(a) for a in amounts]
    net_cents = to_cents(net_deposit)
    if net_cents < 0:
        raise ValueError("net_deposit no puede ser negativo.")

    max_cents = grossed_up_ceiling_cents(net_cents, r_min)
    if max_cents < net_cents:
        # No debería ocurrir con r_min en [0, 1), pero se blinda: la banda
        # nunca puede quedar invertida.
        raise ValueError(
            "La banda de aceptación quedó invertida "
            f"(net_cents={net_cents}, max_cents={max_cents}, r_min={r_min}).")

    # `indexed` conserva el índice ORIGINAL de cada monto (payload de los
    # enumeradores) — se descartan montos <= 0 (nunca son candidatos de un
    # cobro/factura real), igual que en `find_subset_sums`.
    indexed = [(i, c) for i, c in enumerate(amounts_cents) if c > 0]
    if not indexed:
        return []

    total_positivo = sum(c for _, c in indexed)
    if total_positivo < net_cents:
        # Ni sumando TODAS las facturas positivas se alcanza el piso de
        # la banda: no hay ningún candidato posible. Nunca se inventa uno.
        return []

    n = len(indexed)
    # Sin `max_size` explícito, sin techo propio (ver docstring):
    # min_size=1 permite singletons, max_size=n no impone techo —
    # REQ-CONC-005 es responsabilidad del llamador quien, si lo pasa,
    # obtiene también la protección de rendimiento de REQ-CONC-006.
    tope = n if max_size is None else max(1, min(int(max_size), n))
    if n > MITM_THRESHOLD:
        raw = _meet_in_the_middle(indexed, net_cents, max_cents, 1, tope)
    else:
        raw = _brute_force(indexed, net_cents, max_cents, 1, tope)

    candidates: List[SubsetCandidate] = []
    for combo_indices in raw:
        idx_tuple = tuple(sorted(combo_indices))
        s = sum(amounts_cents[i] for i in idx_tuple)
        candidates.append(SubsetCandidate(indices=idx_tuple, sum_cents=s))
    return candidates
