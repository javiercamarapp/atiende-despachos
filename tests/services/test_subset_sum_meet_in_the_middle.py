# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/subset_sum.py — REQ-CONC-006.

Criterio de aceptación (docs/BLUEPRINT-AGENTES-FISCALES.md, REQ-CONC-006):
cuando el número de candidatos filtrados por ventana supere 40, el
algoritmo debe usar meet-in-the-middle (partir en dos mitades, generar
sumas de cada mitad, ordenar una y buscar en la otra por rango) en vez de
DP de fuerza bruta; prueba de rendimiento: con 60 candidatos sintéticos,
el cálculo debe completarse en menos de 5 segundos en CI.

Este archivo NO repite la cobertura funcional de REQ-CONC-004 (ya cubierta
exhaustivamente en `test_subset_sum_banda_comision.py` con universos
pequeños, que corren por el camino de fuerza bruta ya que
`len(amounts) <= MITM_THRESHOLD`). Su objetivo específico es probar que
el camino meet-in-the-middle (activado con > `MITM_THRESHOLD` == 40
candidatos) preserva exactamente las mismas garantías — nunca inventa,
nunca trunca una ambigüedad real — y que además es rápido.

Regla dura del blueprint aplicada aquí: una ambigüedad real (2+
combinaciones distintas cuadran la misma suma) exige decisión humana
explícita y NUNCA se auto-resuelve arbitrariamente (ADR-2). Un caso sin
combinación válida nunca se fuerza a un candidato "parecido" (ADR-1).
"""
import time
from decimal import Decimal

import pytest

from b2b_ai.services.subset_sum import (
    MITM_THRESHOLD,
    SubsetSumBudgetExceeded,
    _brute_force,
    _meet_in_the_middle,
    find_matching_subsets,
    to_cents,
)

R_MIN_EXACTO = Decimal("0")   # banda colapsada a un único valor: suma EXACTA


def _decoys(cantidad: int, desde: str) -> list:
    """Genera `cantidad` montos "señuelo" ESTRICTAMENTE mayores que
    cualquier depósito objetivo usado en estos tests (cada uno por sí solo
    ya excede el techo de la banda), para inflar el universo de candidatos
    por encima de `MITM_THRESHOLD` sin poder participar en ninguna
    combinación válida — así el resultado esperado queda determinista y
    verificable a mano."""
    base = int(desde)
    return [f"{base + i}.00" for i in range(cantidad)]


# ---------------------------------------------------------------------------
# El umbral existe y el dispatch ocurre exactamente donde dice el criterio
# ---------------------------------------------------------------------------

class TestUmbralYDispatch:
    def test_threshold_is_40(self):
        assert MITM_THRESHOLD == 40

    def test_at_or_below_threshold_uses_brute_force_path(self, monkeypatch):
        llamado = {"mitm": False, "brute": False}
        import b2b_ai.services.subset_sum as ss

        real_bf = ss._brute_force
        real_mitm = ss._meet_in_the_middle

        def _spy_bf(*a, **kw):
            llamado["brute"] = True
            return real_bf(*a, **kw)

        def _spy_mitm(*a, **kw):
            llamado["mitm"] = True
            return real_mitm(*a, **kw)

        monkeypatch.setattr(ss, "_brute_force", _spy_bf)
        monkeypatch.setattr(ss, "_meet_in_the_middle", _spy_mitm)

        amounts = [f"{10 + i}.00" for i in range(MITM_THRESHOLD)]  # == 40
        ss.find_matching_subsets(amounts, "10.00", R_MIN_EXACTO, max_size=5)

        assert llamado["brute"] is True
        assert llamado["mitm"] is False

    def test_above_threshold_uses_meet_in_the_middle_path(self, monkeypatch):
        llamado = {"mitm": False, "brute": False}
        import b2b_ai.services.subset_sum as ss

        real_bf = ss._brute_force
        real_mitm = ss._meet_in_the_middle

        def _spy_bf(*a, **kw):
            llamado["brute"] = True
            return real_bf(*a, **kw)

        def _spy_mitm(*a, **kw):
            llamado["mitm"] = True
            return real_mitm(*a, **kw)

        monkeypatch.setattr(ss, "_brute_force", _spy_bf)
        monkeypatch.setattr(ss, "_meet_in_the_middle", _spy_mitm)

        amounts = [f"{10 + i}.00" for i in range(MITM_THRESHOLD + 1)]  # 41
        ss.find_matching_subsets(amounts, "10.00", R_MIN_EXACTO, max_size=5)

        assert llamado["mitm"] is True
        assert llamado["brute"] is False


# ---------------------------------------------------------------------------
# Equivalencia: meet-in-the-middle y fuerza bruta dan EL MISMO resultado
# ---------------------------------------------------------------------------

class TestEquivalenciaConFuerzaBruta:
    """Prueba directamente los dos caminos internos (`_brute_force` y
    `_meet_in_the_middle`) sobre EL MISMO universo — sin pasar por el
    umbral de dispatch — para demostrar que la optimización no cambia el
    resultado, solo el tiempo. Usa n=18 (no 60) para que la fuerza bruta
    de referencia siga siendo rápida de correr en CI."""

    def test_same_candidate_sets_and_much_faster(self):
        import random
        rnd = random.Random(7)
        n = 18
        amounts_cents = [rnd.randint(1000, 50000) for _ in range(n)]
        items = [(f"inv{i}", amounts_cents[i]) for i in range(n)]
        objetivo_idx = rnd.sample(range(n), 4)
        target = sum(amounts_cents[i] for i in objetivo_idx)

        t0 = time.perf_counter()
        resultado_bruto = _brute_force(items, target, target, 2, 15)
        t_bruto = time.perf_counter() - t0

        t0 = time.perf_counter()
        resultado_mitm = _meet_in_the_middle(items, target, target, 2, 15)
        t_mitm = time.perf_counter() - t0

        normaliza = lambda r: sorted(tuple(sorted(c)) for c in r)
        assert normaliza(resultado_bruto) == normaliza(resultado_mitm)
        assert len(resultado_mitm) >= 1   # el objetivo real debe aparecer
        truth = sorted(f"inv{i}" for i in objetivo_idx)
        assert truth in [sorted(c) for c in resultado_mitm]
        # meet-in-the-middle debe ser considerablemente más rápido —
        # documenta la razón de ser de REQ-CONC-006, no solo que "pase".
        assert t_mitm < t_bruto


# ---------------------------------------------------------------------------
# Caso real: 3+ facturas suman un depósito, resuelto por el camino MITM
# ---------------------------------------------------------------------------

class TestCasoRealTresFacturasViaMITM:
    """Mismo caso literal del blueprint (3556.00 + 6796.00 + 9840.00 =
    20192.00), pero acompañado de 40 facturas señuelo (cada una por sí
    sola ya excede el depósito, así que ninguna puede formar parte de un
    subconjunto válido) para que el universo total supere
    `MITM_THRESHOLD` y el cálculo corra por meet-in-the-middle."""

    REALES = ["3556.00", "6796.00", "9840.00"]
    DEPOSITO = "20192.00"

    def _amounts(self):
        return self.REALES + _decoys(40, "25000")   # 43 candidatos totales

    def test_uses_mitm_path_and_finds_the_real_triple(self):
        amounts = self._amounts()
        assert len(amounts) > MITM_THRESHOLD

        candidates = find_matching_subsets(
            amounts, self.DEPOSITO, R_MIN_EXACTO, max_size=15)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.indices == (0, 1, 2)
        assert c.sum_cents == to_cents(self.DEPOSITO)
        assert c.items(amounts) == self.REALES

    def test_never_invents_when_no_subset_reaches_the_target(self):
        """Ningún subconjunto de las señuelo (todas > depósito) ni de las
        reales (que suman exactamente el depósito, no menos ni un
        múltiplo) alcanza un depósito fuera de rango: la búsqueda nunca
        inventa un candidato aproximado (ADR-1)."""
        amounts = self._amounts()
        candidates = find_matching_subsets(
            amounts, "999999999.00", R_MIN_EXACTO, max_size=15)
        assert candidates == []


# ---------------------------------------------------------------------------
# Caso de ambigüedad real: 2 combinaciones disjuntas -> nunca auto-resolver
# ---------------------------------------------------------------------------

class TestAmbiguedadRealViaMITM:
    """5 facturas reales + 38 señuelo (universo > MITM_THRESHOLD): dos
    subconjuntos DISJUNTOS distintos suman exactamente el mismo depósito.
    El camino meet-in-the-middle debe devolver AMBOS — nunca elegir uno,
    nunca truncar a 1 en silencio (ADR-2/REQ-CONC-007), exactamente igual
    que exige el mismo caso cuando corre por fuerza bruta."""

    # Grupo A: 137 + 263 + 100 = 500.00 (verificado exhaustivamente: entre
    # estos 5 montos, {137,263,100} y {199,301} son los ÚNICOS 2
    # subconjuntos cuya suma da exactamente 500.00 — ningún otro tamaño ni
    # combinación de estos 5 números lo logra).
    GRUPO_A = ["137.00", "263.00", "100.00"]
    GRUPO_B = ["199.00", "301.00"]
    DEPOSITO = "500.00"

    def _amounts(self):
        return self.GRUPO_A + self.GRUPO_B + _decoys(38, "600")  # 43 total

    def test_universe_exceeds_mitm_threshold(self):
        assert len(self._amounts()) > MITM_THRESHOLD

    def test_returns_both_disjoint_candidates_never_one(self):
        amounts = self._amounts()
        candidates = find_matching_subsets(
            amounts, self.DEPOSITO, R_MIN_EXACTO, max_size=15)

        assert len(candidates) == 2
        sums = {c.sum_cents for c in candidates}
        assert sums == {to_cents(self.DEPOSITO)}

        index_sets = [set(c.indices) for c in candidates]
        assert index_sets[0].isdisjoint(index_sets[1])
        assert {frozenset(s) for s in index_sets} == {
            frozenset({0, 1, 2}), frozenset({3, 4})}

    def test_ambiguity_is_never_collapsed_to_a_single_answer(self):
        candidates = find_matching_subsets(
            self._amounts(), self.DEPOSITO, R_MIN_EXACTO, max_size=15)
        assert len(candidates) != 1
        assert len(candidates) >= 2


# ---------------------------------------------------------------------------
# Rendimiento: 60 candidatos sintéticos, < 5 segundos (REQ-CONC-006)
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestRendimiento60Candidatos:
    """60 candidatos sintéticos con montos de factura realistas ($500 -
    $5,000 MXN) y un depósito alcanzado por una combinación real de 5 de
    ellos — el escenario que motiva REQ-CONC-006 (una liquidación de
    terminal con muchos cobros del día). Marcado `@pytest.mark.slow` como
    salvaguarda (ver criterio de aceptación); el propio test hace cumplir
    el límite de 5s con una aserción explícita, y el runner de CI ya
    aplica un timeout duro por test (`pytest --timeout=120`) que evita
    bloquear el pipeline sin límite incluso si esta aserción cambiara."""

    def test_completes_in_under_5_seconds(self):
        import random
        rnd = random.Random(42)
        n = 60
        amounts = [round(rnd.uniform(500, 5000), 2) for _ in range(n)]
        objetivo_idx = rnd.sample(range(n), 5)
        deposito = round(sum(amounts[i] for i in objetivo_idx), 2)
        amounts_str = [f"{a:.2f}" for a in amounts]

        assert n > MITM_THRESHOLD   # confirma que este caso SÍ usa MITM

        t0 = time.perf_counter()
        candidates = find_matching_subsets(
            amounts_str, f"{deposito:.2f}", R_MIN_EXACTO, max_size=8)
        elapsed = time.perf_counter() - t0

        assert elapsed < 5.0, (
            f"meet-in-the-middle tardó {elapsed:.2f}s con 60 candidatos "
            "(límite REQ-CONC-006: 5s)")

        encontrados = [sorted(c.indices) for c in candidates]
        assert sorted(objetivo_idx) in encontrados


# ---------------------------------------------------------------------------
# El presupuesto de exploración nunca deja el cálculo colgado sin límite
# ---------------------------------------------------------------------------

class TestPresupuestoDeExploracionAcotaElPeorCaso:
    """Un universo adversarial (muchos montos pequeños de magnitud
    similar y un objetivo cercano a la mitad de la suma total) puede
    hacer que la poda por suma casi no corte nada — ni fuerza bruta ni
    meet-in-the-middle terminan en un tiempo razonable si se les deja
    enumerar sin límite. En vez de colgar el pipeline, la búsqueda debe
    abortar de forma acotada y explícita (nunca en silencio como `[]`,
    que significaría "no hay match" cuando en realidad es "no se terminó
    de buscar")."""

    def test_pathological_input_raises_instead_of_hanging(self):
        rnd_amounts = [str((i % 50) + 1) + ".00" for i in range(60)]
        total = sum(int(float(a)) for a in rnd_amounts)
        objetivo = str(total // 2) + ".00"

        t0 = time.perf_counter()
        with pytest.raises(SubsetSumBudgetExceeded):
            find_matching_subsets(
                rnd_amounts, objetivo, R_MIN_EXACTO, max_size=15)
        elapsed = time.perf_counter() - t0

        # Se aborta de forma acotada (muy por debajo del timeout duro de
        # CI de 120s) en vez de agotar el timeout del runner.
        assert elapsed < 30.0
