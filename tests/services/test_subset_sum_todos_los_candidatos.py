# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/subset_sum.py — REQ-CONC-007.

Criterio de aceptación (docs/BLUEPRINT-AGENTES-FISCALES.md, REQ-CONC-007):
el sistema debe reportar TODOS los subconjuntos cuya suma cae dentro de la
banda `[A, A_grossed_up]`, no solo el primero encontrado; prueba: un caso
sintético con 2 subconjuntos disjuntos válidos para el mismo depósito debe
devolver una lista de longitud 2, nunca truncar a 1 en silencio.

Bug real encontrado y corregido en `find_matching_subsets`: la primera
versión reconstruía cada subconjunto con un DP de sumas alcanzables que
guardaba UN solo backpointer por suma (`back[s] = (idx, suma_previa)`, con
`if reachable[s]: continue` saltándose una suma ya marcada alcanzable). Si
dos subconjuntos DISJUNTOS —usando facturas distintas— sumaban EXACTAMENTE
lo mismo, ese diseño reportaba solo 1 de los 2 (el primero encontrado por
el orden de iteración), descartando el segundo en silencio. Este archivo
fija ese caso como regresión explícita, además del caso (ya cubierto por
`test_subset_sum_banda_comision.py::TestAmbiguedadRealNuncaAutoResuelta`)
de 2 subconjuntos disjuntos con sumas DISTINTAS pero ambas dentro de la
banda.
"""
from decimal import Decimal

from b2b_ai.services.subset_sum import (
    SubsetCandidate,
    find_matching_subsets,
    find_subset_sums,
    to_cents,
)

R_MIN_CLIP = Decimal("0.036")
R_MIN_CERO = Decimal("0.0")


# ---------------------------------------------------------------------------
# El caso central de REQ-CONC-007: 2 subconjuntos disjuntos, MISMA suma,
# ambos dentro de la banda -> deben reportarse los 2, nunca truncar a 1.
# ---------------------------------------------------------------------------

class TestDosSubconjuntosDisjuntosMismaSumaEnLaBanda:
    """4 facturas, 2 pares disjuntos que suman exactamente lo mismo
    ($300.00): {100.00, 200.00} y {150.00, 150.00}. El depósito neto es
    $300.00 (banda floor exacta con r_min=0, sin espacio para ambigüedad
    de redondeo) -> ambos pares caen en la banda y son válidos."""

    INVOICES = ["100.00", "200.00", "150.00", "150.00"]
    NET_DEPOSIT = "300.00"

    def test_returns_a_list_of_length_2_never_truncated_to_1(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CERO)
        assert len(candidates) == 2

    def test_both_candidates_sum_to_the_net_deposit(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CERO)
        target = to_cents(self.NET_DEPOSIT)
        assert all(c.sum_cents == target for c in candidates)

    def test_the_two_candidates_use_disjoint_invoice_sets(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CERO)
        index_sets = [set(c.indices) for c in candidates]
        assert index_sets[0].isdisjoint(index_sets[1])
        # Entre los dos, cubren las 4 facturas del universo (no se pierde
        # ninguna combinación real por comparar índices en el orden
        # equivocado).
        assert index_sets[0] | index_sets[1] == {0, 1, 2, 3}

    def test_candidates_are_actual_subset_candidate_instances(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CERO)
        assert all(isinstance(c, SubsetCandidate) for c in candidates)
        # Cada candidato reconstruye realmente sus propias facturas.
        pares_de_montos = sorted(
            tuple(sorted(c.items(self.INVOICES))) for c in candidates)
        assert pares_de_montos == [
            ("100.00", "200.00"),
            ("150.00", "150.00"),
        ]


class TestTresSubconjuntosDisjuntosMismaSumaEnLaBanda:
    """Generaliza a 3 pares disjuntos con la misma suma ($500.00), para
    confirmar que el corte no es específico de 'exactamente 2' sino que
    escala a cualquier número de combinaciones reales."""

    # 100+400, 150+350, 200+300 -> tres pares disjuntos, cada uno suma 500.
    INVOICES = ["100.00", "400.00", "150.00", "350.00", "200.00", "300.00"]
    NET_DEPOSIT = "500.00"

    def test_returns_all_three_never_fewer(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CERO)
        pares = [set(c.indices) for c in candidates
                 if c.sum_cents == to_cents(self.NET_DEPOSIT)]
        assert len(pares) == 3
        # Los 3 pares deben ser mutuamente disjuntos entre sí.
        for a in range(len(pares)):
            for b in range(a + 1, len(pares)):
                assert pares[a].isdisjoint(pares[b])


# ---------------------------------------------------------------------------
# Ambigüedad con sumas DISTINTAS (regresión de la ya cubierta en
# test_subset_sum_banda_comision.py) — se repite aquí porque es el mismo
# criterio literal de REQ-CONC-007 y este archivo es el punto de referencia
# canónico del requisito en la matriz del blueprint.
# ---------------------------------------------------------------------------

class TestDosSubconjuntosDisjuntosSumasDistintasEnLaBanda:
    # Banda para depósito neto $1,000.00, perfil Clip (r_min=0.036):
    # [1000.00, ~1037.35]. Grupo A: 300+400+320=1020.00. Grupo B:
    # 500+530=1030.00. Ambos caen en la banda y son disjuntos.
    INVOICES = ["300.00", "400.00", "320.00", "500.00", "530.00"]
    NET_DEPOSIT = "1000.00"

    def test_returns_a_list_of_length_2(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        assert len(candidates) == 2
        sums = sorted(c.sum_cents for c in candidates)
        assert sums == [to_cents("1020.00"), to_cents("1030.00")]


# ---------------------------------------------------------------------------
# `find_subset_sums` (la otra función pública de enumeración del módulo)
# ya enumeraba correctamente todas las combinaciones antes de este fix
# (usa `_brute_force`/`_meet_in_the_middle`, sin el defecto del backpointer
# único) — se fija aquí como regresión explícita para que ambas funciones
# públicas del módulo queden cubiertas por el mismo criterio.
# ---------------------------------------------------------------------------

class TestFindSubsetSumsNuncaTruncaSumasRepetidas:
    def test_two_disjoint_subsets_same_sum_both_reported(self):
        items = [("a", to_cents("100.00")), ("b", to_cents("200.00")),
                  ("c", to_cents("150.00")), ("d", to_cents("150.00"))]
        resultados = find_subset_sums(items, to_cents("300.00"))
        assert len(resultados) == 2
        payload_sets = [frozenset(r) for r in resultados]
        assert frozenset({"a", "b"}) in payload_sets
        assert frozenset({"c", "d"}) in payload_sets


# ---------------------------------------------------------------------------
# Caso de control: sigue sin inventar nada si ninguna combinación cae en
# la banda (ADR-1) — REQ-CONC-007 exige reportar TODOS los candidatos
# válidos, no relajar la regla de nunca inventar uno cuando no hay ninguno.
# ---------------------------------------------------------------------------

class TestSigueSinInventarCuandoNoHayNinguno:
    def test_no_match_returns_empty_list_not_a_guess(self):
        candidates = find_matching_subsets(
            ["100.00", "100.00", "100.00"], "500.00", R_MIN_CLIP)
        assert candidates == []
