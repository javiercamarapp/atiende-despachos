# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/subset_sum.py — REQ-CONC-004.

Criterio de aceptación (docs/BLUEPRINT-AGENTES-FISCALES.md, REQ-CONC-004):
el subset-sum debe trabajar en CENTAVOS (enteros, nunca floats) usando DP
de sumas alcanzables con backpointers, aceptando un subconjunto como
candidato si `A <= sum(S) <= A / (1 - r_min)` (grossing-up desde el neto
del depósito hasta el bruto máximo según `r_min` del perfil).

Caso literal del blueprint: depósito neto $20,192.00 con perfil Clip
(`r_min=0.036`) debe aceptar un subconjunto con suma bruta hasta
`$20,192.00 / (1-0.036)`, y rechazar uno de $21,500.00.

Nota de precisión: `$20,192.00 / (1 - 0.036)` calculado exactamente da
`$20,946.058...`, que redondeado hacia arriba al centavo (la regla dura
de este módulo para el límite superior de la banda, ver docstring de
`grossed_up_ceiling_cents`) es `$20,946.06` — no `$20,946.60` como
aparece escrito en el texto del blueprint (transposición de dígitos:
"06" vs "60"). Este archivo verifica la aritmética exacta con
`grossed_up_ceiling_cents` en vez de fijar el número tal cual aparece en
el texto, y confirma que el rechazo de $21,500.00 exigido por el
criterio se cumple bajo cualquiera de las dos lecturas (ambas quedan por
debajo de $21,500.00).
"""
from decimal import Decimal

import pytest

from b2b_ai.services.subset_sum import (
    SubsetCandidate,
    find_matching_subsets,
    grossed_up_ceiling_cents,
    is_within_band,
    to_cents,
)

R_MIN_CLIP = Decimal("0.036")


# ---------------------------------------------------------------------------
# to_cents — nunca floats en la aritmética monetaria
# ---------------------------------------------------------------------------

class TestToCents:
    def test_string_amount(self):
        assert to_cents("20192.00") == 2019200

    def test_decimal_amount(self):
        assert to_cents(Decimal("3556.00")) == 355600

    def test_float_amount_no_binary_drift(self):
        # 0.1 + 0.2 != 0.3 en binario; to_cents debe pasar por str() antes
        # de construir el Decimal para no heredar ese error.
        assert to_cents(0.1) == 10
        assert to_cents(20946.06) == 2094606

    def test_int_amount(self):
        assert to_cents(1000) == 100000

    def test_rounds_half_up_to_nearest_cent(self):
        assert to_cents("10.005") == 1001  # redondeo half-up


# ---------------------------------------------------------------------------
# grossed_up_ceiling_cents — banda de aceptación (grossing-up)
# ---------------------------------------------------------------------------

class TestGrossedUpCeiling:
    def test_caso_exacto_del_blueprint_clip(self):
        net_cents = to_cents("20192.00")
        ceiling = grossed_up_ceiling_cents(net_cents, R_MIN_CLIP)
        # 20192.00 / (1 - 0.036) = 20946.0581... -> ceil a 20946.06.
        assert ceiling == to_cents("20946.06")

    def test_ceiling_is_always_greater_or_equal_than_net(self):
        net_cents = to_cents("1000.00")
        ceiling = grossed_up_ceiling_cents(net_cents, Decimal("0.02"))
        assert ceiling >= net_cents

    def test_zero_commission_rate_means_ceiling_equals_net(self):
        net_cents = to_cents("500.00")
        assert grossed_up_ceiling_cents(net_cents, Decimal("0.0")) == net_cents

    def test_rejects_rate_out_of_range(self):
        with pytest.raises(ValueError):
            grossed_up_ceiling_cents(100000, Decimal("1.0"))
        with pytest.raises(ValueError):
            grossed_up_ceiling_cents(100000, Decimal("-0.01"))

    def test_rejects_negative_net(self):
        with pytest.raises(ValueError):
            grossed_up_ceiling_cents(-1, Decimal("0.036"))


class TestIsWithinBand:
    def test_floor_inclusive(self):
        net_cents = to_cents("20192.00")
        assert is_within_band(net_cents, net_cents, R_MIN_CLIP) is True

    def test_ceiling_inclusive(self):
        net_cents = to_cents("20192.00")
        ceiling = grossed_up_ceiling_cents(net_cents, R_MIN_CLIP)
        assert is_within_band(ceiling, net_cents, R_MIN_CLIP) is True

    def test_one_cent_above_ceiling_rejected(self):
        net_cents = to_cents("20192.00")
        ceiling = grossed_up_ceiling_cents(net_cents, R_MIN_CLIP)
        assert is_within_band(ceiling + 1, net_cents, R_MIN_CLIP) is False

    def test_one_cent_below_floor_rejected(self):
        net_cents = to_cents("20192.00")
        assert is_within_band(net_cents - 1, net_cents, R_MIN_CLIP) is False

    def test_21500_rejected_under_clip_profile(self):
        # El caso explícito del blueprint: $21,500.00 debe rechazarse.
        net_cents = to_cents("20192.00")
        assert is_within_band(to_cents("21500.00"), net_cents, R_MIN_CLIP) is False


# ---------------------------------------------------------------------------
# find_matching_subsets — caso real: 3+ facturas suman un depósito
# ---------------------------------------------------------------------------

class TestSubsetSumRealTresFacturas:
    """El caso literal del blueprint: 3 facturas cuya suma exacta es el
    neto del depósito (banda floor), bajo el perfil Clip."""

    INVOICES = ["3556.00", "6796.00", "9840.00"]
    NET_DEPOSIT = "20192.00"

    def test_accepts_the_three_invoice_subset_at_the_exact_net(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.sum_cents == to_cents(self.NET_DEPOSIT)
        assert candidate.indices == (0, 1, 2)
        assert candidate.items(self.INVOICES) == self.INVOICES

    def test_never_invents_a_match_when_nothing_fits(self):
        # Ningún subconjunto de facturas mucho más chicas puede alcanzar
        # ni el piso de la banda: debe devolver [] explícitamente, nunca
        # forzar el candidato "más parecido".
        candidates = find_matching_subsets(
            ["100.00", "100.00", "100.00"], "500.00", R_MIN_CLIP)
        assert candidates == []

    def test_never_invents_a_match_when_total_reaches_but_no_subset_lands_in_band(self):
        # El total de las facturas SÍ pasa del piso, pero ningún
        # subconjunto individual cae dentro de la banda (hay un hueco
        # entre lo que se puede sumar por debajo y por encima de ella).
        candidates = find_matching_subsets(
            ["900.00", "200.00"], "1000.00", R_MIN_CLIP)
        assert candidates == []


class TestSubsetSumRechazaFueraDeBanda:
    """Verifica el rechazo explícito de $21,500.00 exigido por el
    criterio, incluso cuando esa suma SÍ es alcanzable combinando
    facturas reales (para probar que el rechazo es por la banda, no
    porque la combinación no exista)."""

    # 3556.00 + 6796.00 + 9840.00 + 1308.00 == 21500.00 (alcanzable),
    # pero 21500.00 > techo de la banda (~20946.06) para un depósito neto
    # de 20192.00 con r_min=0.036 de Clip.
    INVOICES = ["3556.00", "6796.00", "9840.00", "1308.00"]
    NET_DEPOSIT = "20192.00"

    def test_21500_subset_is_reachable_but_excluded_from_candidates(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        sums = {c.sum_cents for c in candidates}
        assert to_cents("21500.00") not in sums
        # El único candidato dentro de banda sigue siendo el de 3 facturas
        # que suma exactamente el neto.
        assert sums == {to_cents(self.NET_DEPOSIT)}


class TestSubsetSumAceptaBrutoConComisionReal:
    """Caso de comisión real (no exacto): el bruto facturado es MAYOR al
    neto depositado, dentro de la banda — el escenario típico donde
    Clip sí cobró una comisión distinta de cero."""

    def test_accepts_gross_sum_between_net_and_ceiling(self):
        # 3 facturas que suman 20900.00 (> neto 20192.00, < techo
        # ~20946.06): representa el caso real de una comisión efectiva
        # de ~3.38%, dentro de la banda [r_min=3.6%, r_max no aplica aquí
        # porque el techo se calcula solo con r_min].
        invoices = ["7000.00", "7000.00", "6900.00"]  # suma 20900.00
        candidates = find_matching_subsets(invoices, "20192.00", R_MIN_CLIP)
        sums = {c.sum_cents for c in candidates}
        assert to_cents("20900.00") in sums

    def test_accepts_exactly_at_the_ceiling_boundary(self):
        net_cents = to_cents("1000.00")
        ceiling_cents = grossed_up_ceiling_cents(net_cents, R_MIN_CLIP)
        # Construye una factura única cuyo monto es exactamente el techo.
        invoices = [str(Decimal(ceiling_cents) / 100)]
        candidates = find_matching_subsets(invoices, "1000.00", R_MIN_CLIP)
        assert len(candidates) == 1
        assert candidates[0].sum_cents == ceiling_cents

    def test_rejects_one_cent_above_the_ceiling(self):
        net_cents = to_cents("1000.00")
        ceiling_cents = grossed_up_ceiling_cents(net_cents, R_MIN_CLIP)
        invoices = [str(Decimal(ceiling_cents + 1) / 100)]
        candidates = find_matching_subsets(invoices, "1000.00", R_MIN_CLIP)
        assert candidates == []


# ---------------------------------------------------------------------------
# Ambigüedad real (ADR-2): 2+ combinaciones cuadran -> nunca auto-resolver
# ---------------------------------------------------------------------------

class TestAmbiguedadRealNuncaAutoResuelta:
    """5 facturas, depósito neto $1,000.00 (perfil Clip, banda
    [$1,000.00, $1,037.35]): dos subconjuntos DISJUNTOS distintos caen
    dentro de la banda -> el algoritmo debe devolver AMBOS, nunca elegir
    uno por su cuenta."""

    # Grupo A: 300 + 400 + 320 = 1020.00 (dentro de banda).
    # Grupo B: 500 + 530 = 1030.00 (dentro de banda, disjunto de A).
    # Ninguna otra combinación de estos 5 montos cae dentro de la banda
    # (verificado exhaustivamente al diseñar el caso).
    INVOICES = ["300.00", "400.00", "320.00", "500.00", "530.00"]
    NET_DEPOSIT = "1000.00"

    def test_returns_both_disjoint_candidates(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        assert len(candidates) == 2

        sums = sorted(c.sum_cents for c in candidates)
        assert sums == [to_cents("1020.00"), to_cents("1030.00")]

    def test_candidates_are_disjoint_invoice_sets(self):
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        index_sets = [set(c.indices) for c in candidates]
        assert index_sets[0].isdisjoint(index_sets[1])

    def test_ambiguity_is_never_collapsed_to_a_single_answer(self):
        # Regla dura repetida explícitamente: la función NUNCA debe
        # devolver una lista de longitud 1 (u ordenar y quedarse con "el
        # mejor") cuando existe más de una combinación válida real.
        candidates = find_matching_subsets(
            self.INVOICES, self.NET_DEPOSIT, R_MIN_CLIP)
        assert len(candidates) != 1
        assert len(candidates) >= 2


# ---------------------------------------------------------------------------
# DP con backpointers: reconstrucción correcta de índices
# ---------------------------------------------------------------------------

class TestReconstruccionDeBackpointers:
    def test_indices_map_back_to_the_declared_sum(self):
        invoices = ["100.00", "250.00", "75.00", "1000.00"]
        candidates = find_matching_subsets(invoices, "425.00", Decimal("0.0"))
        assert len(candidates) == 1
        c = candidates[0]
        recomputed = sum(to_cents(invoices[i]) for i in c.indices)
        assert recomputed == c.sum_cents
        assert c.sum_cents == to_cents("425.00")

    def test_indices_are_sorted_and_unique(self):
        invoices = ["100.00", "250.00", "75.00"]
        candidates = find_matching_subsets(invoices, "425.00", Decimal("0.0"))
        c = candidates[0]
        assert list(c.indices) == sorted(set(c.indices))


# ---------------------------------------------------------------------------
# Validaciones defensivas
# ---------------------------------------------------------------------------

class TestValidaciones:
    def test_negative_net_deposit_raises(self):
        with pytest.raises(ValueError):
            find_matching_subsets(["100.00"], "-1.00", R_MIN_CLIP)

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError):
            find_matching_subsets(["100.00"], "100.00", Decimal("1.5"))

    def test_empty_amounts_never_invents(self):
        assert find_matching_subsets([], "100.00", R_MIN_CLIP) == []

    def test_subset_candidate_is_immutable(self):
        c = SubsetCandidate(indices=(0, 1), sum_cents=100)
        with pytest.raises(Exception):
            c.sum_cents = 200
