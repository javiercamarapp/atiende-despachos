# -*- coding: utf-8 -*-
"""
group_scoring.py — Score de desambiguación compuesto (0-100) para
candidatos de conciliación N-a-1 (REQ-CONC-009,
`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC).

Cuando `subset_sum.find_matching_subsets` (REQ-CONC-004/007) devuelve 1 o
más subconjuntos de facturas cuya suma cae dentro de la banda de
aceptación de un depósito, este módulo pondera qué tan "creíble" es cada
subconjunto como el que realmente originó ese depósito. El score NO
decide nada por sí mismo: `_pass_group()` en `bank_reconciliation.py`
(REQ-CONC-008) es quien usa este score para decidir si auto-confirma
(único candidato Y score >= 85) o deja el caso para revisión humana — este
módulo solo calcula el número, nunca aplica ni descarta un match.

Dos entradas públicas, un solo motor compartido (`_score_components`):

  - `score_group(...)` / `GroupScore` / `score_candidates(...)`: la API
    "rica" pensada para quien ya tiene el `net_deposit`, las facturas del
    grupo y (opcionalmente) el `SettlementProfile` — la forma natural de
    invocarlo desde pruebas y desde cualquier código que trabaje con
    montos en pesos. Expone cada dimensión por separado para trazabilidad.
  - `compute_group_score(invoices, sum_cents, target_cents, es_unico,
    perfil=None, total_candidatos=None)`: API de compatibilidad para
    `_pass_group()` (REQ-CONC-008), que ya trabaja en centavos y conoce
    `es_unico` como booleano simple. Delega en el mismo motor: con
    `total_candidatos` explícito la unicidad queda graduada (REQ-CONC-009);
    sin él, se infiere de `es_unico` (True -> 1 candidato, False -> 2,
    el caso ambiguo más simple) para no romper llamadas existentes.

Cuatro dimensiones ponderadas, cada una normalizada a una escala 0-100
antes de combinarse (los pesos suman exactamente 1.0):

  1. Comisión (`WEIGHT_COMMISSION`): qué tan cerca está la comisión
     IMPLÍCITA del subconjunto (`(bruto - neto) / bruto`) de la tasa
     NOMINAL del perfil de liquidación (punto medio de
     `tasa_comision_min`/`tasa_comision_max`). Más cerca = mejor. Sin
     perfil conocido (`_pass_group` aún no threadea un `SettlementProfile`
     real por canal, REQ-CONC-001/015), esta dimensión se abstiene de
     penalizar (score 100) en vez de inventar una cercanía que no se
     puede evaluar — no hay evidencia de mala comisión, así que no se
     castiga por ella (mismo principio que ADR-4: ausencia de dato nunca
     se traduce en un castigo automático).
  2. Fechas (`WEIGHT_DATE`): compacidad de las fechas de las facturas del
     grupo — menor dispersión (rango max-min en días) = mejor.
  3. Tamaño (`WEIGHT_SIZE`): menos facturas = mejor, salvo evidencia
     contraria — esa "evidencia contraria" es precisamente lo que las
     otras 3 dimensiones aportan: el tamaño es una señal más dentro del
     compuesto, no un veto absoluto.
  4. Unicidad (`WEIGHT_UNIQUENESS`): único candidato en la banda = score
     máximo en esta dimensión; con 2+ candidatos (ambigüedad real, ver
     ADR-2), el score de unicidad se reparte entre todos ellos por igual
     — ninguno queda "el elegido" solo por esta dimensión, porque la
     ambigüedad real la resuelve un humano (REQ-CONC-008), nunca el score.

Cada dimensión es una función CONTINUA de su entrada (no un umbral binario
ni una tabla de cubetas gruesas), así que dos subconjuntos que difieren en
cualquiera de las 4 dimensiones producen, por diseño, puntajes distintos —
nunca quedan empatados por una casualidad de redondeo grueso salvo que
sean literalmente idénticos en las 4 dimensiones.

Regla dura heredada de `subset_sum.py` (ADR-1/ADR-2): este módulo NUNCA
fabrica un subconjunto ni decide cuál aplicar — solo puntúa subconjuntos
que YA fueron encontrados por el subset-sum real. Si no hay subconjuntos,
no hay nada que puntuar (`score_group` exige al menos 1 factura).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional, Sequence

from b2b_ai.services.settlement_profiles import SettlementProfile
from b2b_ai.services.subset_sum import to_cents

# ---------------------------------------------------------------------------
# Pesos de cada dimensión. Suman exactamente 1.0.
# ---------------------------------------------------------------------------
WEIGHT_COMMISSION = Decimal("0.35")
WEIGHT_DATE = Decimal("0.30")
WEIGHT_SIZE = Decimal("0.20")
WEIGHT_UNIQUENESS = Decimal("0.15")

assert WEIGHT_COMMISSION + WEIGHT_DATE + WEIGHT_SIZE + WEIGHT_UNIQUENESS == Decimal("1.00")

# Techo de tamaño de grupo usado como referencia de la dimensión de tamaño
# (debe coincidir con `BankReconciliation.MAX_GROUP_SIZE`, REQ-CONC-005;
# se declara aquí también, sin importar `bank_reconciliation`, para no
# introducir un ciclo de imports entre ambos módulos).
DEFAULT_MAX_GROUP_SIZE = 15

# Dispersión de fechas (en días) a partir de la cual la dimensión de fecha
# toca 0 — más allá de esto, un grupo se considera "disperso" sin importar
# cuánto más disperso esté.
DEFAULT_MAX_DATE_DISPERSION_DAYS = 30

# Medio-ancho de referencia para la dimensión de comisión cuando el perfil
# no trae banda (min == max, p. ej. spei_transferencia 0%-0%): evita
# dividir entre cero sin volver el score binario 100/0 — 1 punto
# porcentual de referencia es un valor conservador para un canal que en
# teoría no debería tener comisión implícita alguna.
DEFAULT_COMMISSION_HALF_WIDTH = Decimal("0.01")


def _dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _coerce_date(v) -> date:
    """Convierte str/date/datetime a `date`. Acepta 'YYYY-MM-DD' (con o sin
    sufijo de hora) — el formato usado en todo el resto del módulo de
    conciliación bancaria. Lanza ValueError si no se puede interpretar."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    raise ValueError(f"fecha no reconocida para scoring de grupo: {v!r}")


def _parse_fecha_opcional(v) -> Optional[date]:
    """Como `_coerce_date`, pero nunca lanza — usada por la API de
    compatibilidad (`compute_group_score`), que no puede darse el lujo de
    romper `_pass_group()` por una fecha faltante o mal formada en un
    movimiento real; simplemente excluye esa fecha del cálculo de
    dispersión en vez de fallar toda la puntuación."""
    try:
        return _coerce_date(v)
    except (ValueError, TypeError):
        return None


def implied_commission_rate(sum_cents: int, net_cents: int) -> Decimal:
    """Tasa de comisión implícita de un subconjunto: qué fracción del
    bruto facturado (`sum_cents`) se "pierde" hasta llegar al neto
    depositado (`net_cents`). Nunca negativa — un `sum_cents < net_cents`
    (que no debería ocurrir si el subconjunto de verdad viene de la banda
    de aceptación de `subset_sum.find_matching_subsets`) se trata como
    comisión 0 en vez de producir un valor negativo sin sentido de
    negocio."""
    if sum_cents <= 0:
        return Decimal("0")
    rate = (Decimal(sum_cents) - Decimal(net_cents)) / Decimal(sum_cents)
    return rate if rate > 0 else Decimal("0")


def _date_dispersion_days(fechas: Sequence[date]) -> int:
    """Dispersión de fechas del grupo: rango en días entre la fecha más
    antigua y la más reciente. Un grupo de 0 o 1 fecha (o todas iguales)
    tiene dispersión 0."""
    fechas = [f for f in fechas if f is not None]
    if len(fechas) <= 1:
        return 0
    return (max(fechas) - min(fechas)).days


def _commission_closeness_score(
    sum_cents: int, net_cents: int, perfil: Optional[SettlementProfile]
) -> Decimal:
    """Score 0-100: qué tan cerca está la comisión implícita del
    subconjunto de la tasa NOMINAL del perfil (punto medio de
    `tasa_comision_min`/`tasa_comision_max`).

    Sin perfil (nunca se declaró un `SettlementProfile` para este canal),
    no hay tasa nominal contra la cual comparar: se devuelve 100 — la
    dimensión se ABSTIENE de evaluar en vez de inventar una cercanía o
    penalizar por un dato que no tiene (mismo principio de ADR-4: la
    ausencia de evidencia nunca se traduce en un castigo automático)."""
    implied = implied_commission_rate(sum_cents, net_cents)
    if perfil is None:
        return Decimal("100")

    r_min = perfil.get("tasa_comision_min") if isinstance(perfil, dict) \
        else getattr(perfil, "tasa_comision_min", None)
    r_max = perfil.get("tasa_comision_max") if isinstance(perfil, dict) \
        else getattr(perfil, "tasa_comision_max", None)
    if r_min is None and r_max is None:
        return Decimal("100")
    r_min = _dec(r_min if r_min is not None else r_max)
    r_max = _dec(r_max if r_max is not None else r_min)

    nominal = (r_min + r_max) / 2
    half_width = max(nominal - r_min, r_max - nominal)
    if half_width <= 0:
        half_width = DEFAULT_COMMISSION_HALF_WIDTH

    dist = abs(implied - nominal)
    # Referencia: al doble del medio-ancho declarado del perfil, el score
    # ya tocó 0 — dentro del medio-ancho, cae linealmente de 100 a 50.
    ref = half_width * 2
    if ref <= 0:
        frac = Decimal("1") if dist > 0 else Decimal("0")
    else:
        frac = dist / ref
        if frac > 1:
            frac = Decimal("1")
    return Decimal("100") * (Decimal("1") - frac)


def _date_compactness_score(
    fechas: Sequence[date],
    max_dispersion_days: int = DEFAULT_MAX_DATE_DISPERSION_DAYS,
) -> Decimal:
    """Score 0-100: menor dispersión de fechas dentro del grupo = mejor.
    Función lineal continua de la dispersión en días — dos grupos con
    dispersiones distintas producen, por diseño, scores distintos."""
    dispersion = _date_dispersion_days(fechas)
    if max_dispersion_days <= 0:
        return Decimal("100") if dispersion == 0 else Decimal("0")
    frac = Decimal(dispersion) / Decimal(max_dispersion_days)
    if frac > 1:
        frac = Decimal("1")
    return Decimal("100") * (Decimal("1") - frac)


def _size_score(n: int, max_group_size: int = DEFAULT_MAX_GROUP_SIZE) -> Decimal:
    """Score 0-100: menos facturas en el grupo = mejor. Lineal entre
    tamaño 2 (score 100) y `max_group_size` (score 0)."""
    n = max(2, int(n))
    max_group_size = max(n, int(max_group_size))
    if max_group_size <= 2:
        return Decimal("100")
    frac = Decimal(n - 2) / Decimal(max_group_size - 2)
    if frac > 1:
        frac = Decimal("1")
    return Decimal("100") * (Decimal("1") - frac)


def _uniqueness_score(total_candidates: int) -> Decimal:
    """Score 0-100: único candidato en la banda = 100 (máxima confianza
    de que este es el subconjunto correcto). Con 2+ candidatos dentro de
    la banda (ambigüedad real, ADR-2), el score de unicidad se reparte
    entre todos ellos por igual — ninguno queda "elegido" por esta
    dimensión sola, precisamente porque la elección entre ambiguos reales
    la debe hacer un humano (REQ-CONC-008), nunca el score."""
    total_candidates = max(1, int(total_candidates))
    if total_candidates == 1:
        return Decimal("100")
    return (Decimal("100") / Decimal(total_candidates)).quantize(Decimal("0.01"))


def _score_components(
    fechas: Sequence[Optional[date]],
    sum_cents: int,
    net_cents: int,
    group_size: int,
    perfil: Optional[SettlementProfile],
    total_candidates: int,
    max_group_size: int,
    max_date_dispersion_days: int,
) -> dict:
    """Motor compartido: calcula las 4 dimensiones y el total ponderado.
    Usado tanto por `score_group` (API rica) como por
    `compute_group_score` (API de compatibilidad en centavos) para que
    ambas entradas públicas produzcan EXACTAMENTE el mismo número ante
    los mismos datos — un solo lugar donde vive la fórmula."""
    commission = _commission_closeness_score(sum_cents, net_cents, perfil)
    date_s = _date_compactness_score(fechas, max_date_dispersion_days)
    size_s = _size_score(group_size, max_group_size)
    uniq_s = _uniqueness_score(total_candidates)

    weighted = (
        WEIGHT_COMMISSION * commission
        + WEIGHT_DATE * date_s
        + WEIGHT_SIZE * size_s
        + WEIGHT_UNIQUENESS * uniq_s
    )
    weighted = weighted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if weighted > 100:
        weighted = Decimal("100")
    if weighted < 0:
        weighted = Decimal("0")

    return {
        "total": weighted,
        "commission_score": commission,
        "date_score": date_s,
        "size_score": size_s,
        "uniqueness_score": uniq_s,
        "implied_rate": implied_commission_rate(sum_cents, net_cents),
        "date_dispersion_days": _date_dispersion_days(fechas),
    }


@dataclass(frozen=True)
class GroupScore:
    """Resultado del score de desambiguación compuesto de un subconjunto
    candidato (REQ-CONC-009). `total` es el número 0-100 que consume
    `_pass_group()`/REQ-CONC-008 para decidir auto-confirmación; los demás
    campos quedan expuestos para trazabilidad (por qué se calificó así) y
    para que las pruebas puedan verificar cada dimensión por separado."""

    total: float
    commission_score: Decimal
    date_score: Decimal
    size_score: Decimal
    uniqueness_score: Decimal
    implied_rate: Decimal
    date_dispersion_days: int
    group_size: int
    total_candidates: int

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "commission_score": float(self.commission_score),
            "date_score": float(self.date_score),
            "size_score": float(self.size_score),
            "uniqueness_score": float(self.uniqueness_score),
            "implied_rate": str(self.implied_rate),
            "date_dispersion_days": self.date_dispersion_days,
            "group_size": self.group_size,
            "total_candidates": self.total_candidates,
        }


def score_group(
    invoices: Sequence[dict],
    net_deposit: Any,
    perfil: Optional[SettlementProfile] = None,
    total_candidates: int = 1,
    max_group_size: int = DEFAULT_MAX_GROUP_SIZE,
    max_date_dispersion_days: int = DEFAULT_MAX_DATE_DISPERSION_DAYS,
    fecha_field: str = "fecha",
    monto_field: str = "total",
) -> GroupScore:
    """Calcula el score de desambiguación compuesto (0-100) para UN
    subconjunto candidato de facturas que ya fue encontrado por
    `subset_sum.find_matching_subsets` (o por `_pass_group`) como una
    suma dentro de la banda de aceptación de `net_deposit`.

    Este módulo nunca decide si el subconjunto es válido o no — eso ya lo
    resolvió el subset-sum (ADR-1: 0 candidatos nunca llegan aquí, porque
    no hay nada que puntuar). Aquí solo se pondera qué tan creíble es este
    subconjunto FRENTE A los demás candidatos del mismo depósito
    (`total_candidates`).

    Args:
        invoices: las facturas del subconjunto candidato (2+; tamaño 1 ya
            lo cubre el cruce exacto 1-a-1 y no pasa por este pase).
        net_deposit: el monto NETO del depósito bancario contra el que se
            evalúa este subconjunto.
        perfil: el `SettlementProfile` del canal de cobro, si se conoce
            (para la dimensión de comisión). `None` produce un score
            neutral en esa dimensión, nunca un valor inventado.
        total_candidates: cuántos subconjuntos distintos cayeron en la
            banda de aceptación para este MISMO depósito (1 = único
            candidato; 2+ = ambigüedad real, ver ADR-2). Debe ser el
            mismo valor para todos los candidatos de un mismo depósito.
        max_group_size: techo de tamaño de grupo usado como referencia de
            la dimensión de tamaño (debe coincidir con el techo real
            aplicado por el pase de conciliación que generó el grupo).
        max_date_dispersion_days: dispersión de fechas (días) a partir de
            la cual la dimensión de fecha ya tocó 0.
        fecha_field / monto_field: nombres de los campos de fecha/monto en
            cada dict de `invoices` (default: los usados en todo
            `bank_reconciliation.py` — `"fecha"` y `"total"`).

    Raises:
        ValueError: si `invoices` está vacío — no existe "el score del
            subconjunto vacío"; quien llama nunca debe invocar esto sin
            un subconjunto real ya encontrado.
    """
    if not invoices:
        raise ValueError(
            "score_group requiere al menos 1 factura en el subconjunto "
            "candidato; no existe un score para 'ningún candidato' — eso "
            "es 'sin_conciliar' (ADR-1), no un score bajo.")

    net_cents = to_cents(net_deposit)
    sum_cents = sum(to_cents(_dec(inv[monto_field])) for inv in invoices)
    fechas = [_coerce_date(inv[fecha_field]) for inv in invoices]

    comp = _score_components(
        fechas, sum_cents, net_cents, len(invoices), perfil,
        total_candidates, max_group_size, max_date_dispersion_days)

    return GroupScore(
        total=float(comp["total"]),
        commission_score=comp["commission_score"],
        date_score=comp["date_score"],
        size_score=comp["size_score"],
        uniqueness_score=comp["uniqueness_score"],
        implied_rate=comp["implied_rate"],
        date_dispersion_days=comp["date_dispersion_days"],
        group_size=len(invoices),
        total_candidates=max(1, int(total_candidates)),
    )


def score_candidates(
    candidate_groups: Sequence[Sequence[dict]],
    net_deposit: Any,
    perfil: Optional[SettlementProfile] = None,
    **kwargs: Any,
) -> list:
    """Puntúa TODOS los subconjuntos candidatos de un mismo depósito de
    una sola vez, fijando `total_candidates = len(candidate_groups)` para
    cada uno (todos compiten por el mismo depósito, así que todos deben
    usar el mismo valor de unicidad — REQ-CONC-009).

    Con 0 candidatos, devuelve `[]` sin error: no hay nada que puntuar
    (ADR-1 ya se resolvió antes de llegar aquí, en el subset-sum)."""
    total = len(candidate_groups)
    if total == 0:
        return []
    return [
        score_group(grupo, net_deposit, perfil=perfil,
                    total_candidates=total, **kwargs)
        for grupo in candidate_groups
    ]


# ---------------------------------------------------------------------------
# API de compatibilidad para `_pass_group()` (REQ-CONC-008), que trabaja
# en centavos (enteros) y conoce `es_unico` como booleano simple en vez
# del conteo graduado de candidatos. Delega en el mismo motor que
# `score_group` — mismos pesos, mismas 4 dimensiones — para que ambas
# APIs sean consistentes entre sí ante los mismos datos.
# ---------------------------------------------------------------------------

def compute_group_score(invoices: Sequence[dict], sum_cents: int,
                        target_cents: int, es_unico: bool,
                        perfil=None,
                        total_candidatos: Optional[int] = None) -> int:
    """Score de desambiguación 0-100 (REQ-CONC-009) de un candidato de
    grupo N-a-1, usado por `_pass_group` para decidir auto-confirmación
    (REQ-CONC-008): cercanía de comisión, compacidad de fechas, tamaño
    del grupo y unicidad. Redondeado a entero, siempre en `[0, 100]`.

    `total_candidatos` (opcional) gradúa la dimensión de unicidad cuando
    quien llama ya sabe cuántos subconjuntos distintos cayeron en la
    banda para este depósito (2, 3, ... — ambigüedad real, ADR-2): más
    candidatos compitiendo, menor la unicidad de CADA UNO. Sin él, se
    infiere de `es_unico` (`True` -> 1 candidato -> unicidad 100;
    `False` -> se asume el caso ambiguo más simple, 2 candidatos) para
    no romper llamadas existentes que solo conocen el booleano.
    """
    if total_candidatos is None:
        total_candidatos = 1 if es_unico else 2
    fechas = [_parse_fecha_opcional(i.get("fecha")) for i in invoices]
    comp = _score_components(
        fechas, sum_cents, target_cents, len(invoices), perfil,
        total_candidatos, DEFAULT_MAX_GROUP_SIZE,
        DEFAULT_MAX_DATE_DISPERSION_DAYS)
    return int(comp["total"].to_integral_value(rounding=ROUND_HALF_UP))
