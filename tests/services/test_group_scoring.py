# -*- coding: utf-8 -*-
"""
REQ-CONC-009 — score de desambiguación compuesto (0-100) para candidatos
de conciliación N-a-1.

Cubre el criterio de aceptación exacto del blueprint
(`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC):

  - Dos subconjuntos con la MISMA suma pero DISTINTA dispersión de fechas
    deben producir scores distintos, nunca empatados por diseño — salvo
    que sean idénticos en las 4 dimensiones (comisión, fechas, tamaño,
    unicidad).
  - Cada dimensión (comisión, fechas, tamaño, unicidad) se verifica por
    separado, cambiando solo esa variable y confirmando que el total
    cambia en la dirección esperada.
  - Caso real de subset-sum con 3+ facturas sumando un depósito (usa
    `subset_sum.find_matching_subsets`, el algoritmo real, no un mock).
  - Caso de NO match: ningún subconjunto cae en la banda -> no hay nada
    que puntuar (`score_group` nunca fabrica un subconjunto, ADR-1).
  - Caso de ambigüedad real (2 combinaciones válidas para el mismo
    depósito, con distinta dispersión de fechas): produce 2 candidatos
    reales vía el subset-sum real, cada uno con score distinto, y ninguno
    se marca como "el elegido" solo por tener mejor score (ADR-2 lo deja
    para decisión humana explícita — este módulo solo puntúa, no decide).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from b2b_ai.services.group_scoring import (
    GroupScore,
    implied_commission_rate,
    score_candidates,
    score_group,
)
from b2b_ai.services.settlement_profiles import get_settlement_profile
from b2b_ai.services.subset_sum import find_matching_subsets, to_cents

CLIP = get_settlement_profile("clip")  # tasa_comision_min=0.036, max=0.043


def _inv(folio, total, fecha):
    return {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
            "emisor": "Cliente", "emisor_nombre": "Cliente"}


# ---------------------------------------------------------------------------
# Núcleo del requisito: misma suma, distinta dispersión de fechas ->
# scores distintos, nunca empatados por diseño.
# ---------------------------------------------------------------------------

def test_misma_suma_distinta_dispersion_fechas_scores_distintos():
    grupo_compacto = [
        _inv("A1", "3556.00", "2026-07-10"),
        _inv("A2", "6796.00", "2026-07-10"),
        _inv("A3", "9840.00", "2026-07-10"),
    ]
    grupo_disperso = [
        _inv("B1", "3556.00", "2026-06-01"),
        _inv("B2", "6796.00", "2026-06-20"),
        _inv("B3", "9840.00", "2026-07-10"),
    ]
    # Misma suma exacta ($20,192.00) en ambos grupos.
    assert sum(Decimal(i["total"]) for i in grupo_compacto) == \
        sum(Decimal(i["total"]) for i in grupo_disperso) == Decimal("20192.00")

    net = "20192.00"
    score_compacto = score_group(grupo_compacto, net, perfil=CLIP, total_candidates=1)
    score_disperso = score_group(grupo_disperso, net, perfil=CLIP, total_candidates=1)

    # Comisión, tamaño y unicidad son IDÉNTICOS entre ambos grupos (misma
    # suma, mismo tamaño, mismo total_candidates) — la única dimensión que
    # difiere es la de fechas.
    assert score_compacto.commission_score == score_disperso.commission_score
    assert score_compacto.size_score == score_disperso.size_score
    assert score_compacto.uniqueness_score == score_disperso.uniqueness_score
    assert score_compacto.date_dispersion_days == 0
    assert score_disperso.date_dispersion_days == 39
    assert score_compacto.date_score > score_disperso.date_score

    # El total, por diseño, es distinto — nunca empatado cuando difieren
    # en una dimensión real.
    assert score_compacto.total != score_disperso.total
    assert score_compacto.total > score_disperso.total


def test_grupos_identicos_en_las_4_dimensiones_producen_el_mismo_score():
    """Sanity check del enunciado inverso del requisito: solo cuando las
    4 dimensiones son idénticas el score puede (y debe) empatar."""
    grupo = [
        _inv("A1", "3556.00", "2026-07-10"),
        _inv("A2", "6796.00", "2026-07-10"),
        _inv("A3", "9840.00", "2026-07-10"),
    ]
    grupo_copia = [dict(inv) for inv in grupo]

    s1 = score_group(grupo, "20192.00", perfil=CLIP, total_candidates=1)
    s2 = score_group(grupo_copia, "20192.00", perfil=CLIP, total_candidates=1)

    assert s1.total == s2.total
    assert s1.commission_score == s2.commission_score
    assert s1.date_score == s2.date_score
    assert s1.size_score == s2.size_score
    assert s1.uniqueness_score == s2.uniqueness_score


# ---------------------------------------------------------------------------
# Dimensión 1: cercanía de la comisión implícita a la tasa nominal.
# ---------------------------------------------------------------------------

def test_comision_mas_cercana_a_la_tasa_nominal_produce_mejor_score():
    net = "20192.00"
    fecha = "2026-07-10"

    # Nominal de Clip = (0.036 + 0.043) / 2 = 0.0395. Un bruto que implica
    # comisión ~3.95% queda MUY cerca del nominal.
    bruto_cercano = (Decimal(net) / (Decimal("1") - Decimal("0.0395"))
                     ).quantize(Decimal("0.01"))
    grupo_cercano = [
        _inv("C1", bruto_cercano / 2, fecha),
        _inv("C2", bruto_cercano / 2, fecha),
    ]
    # Un bruto igual al neto (comisión implícita 0%) queda lejos del
    # nominal (0.0395) y fuera de la banda real, pero score_group no
    # valida la banda -- solo puntúa lo que le dan, así que sirve para
    # aislar la dimensión de comisión.
    grupo_lejano = [
        _inv("D1", Decimal(net) / 2, fecha),
        _inv("D2", Decimal(net) / 2, fecha),
    ]

    s_cercano = score_group(grupo_cercano, net, perfil=CLIP, total_candidates=1)
    s_lejano = score_group(grupo_lejano, net, perfil=CLIP, total_candidates=1)

    # Fechas, tamaño y unicidad son idénticos; solo cambia la comisión.
    assert s_cercano.date_score == s_lejano.date_score
    assert s_cercano.size_score == s_lejano.size_score
    assert s_cercano.uniqueness_score == s_lejano.uniqueness_score
    assert s_cercano.commission_score > s_lejano.commission_score
    assert s_cercano.total > s_lejano.total
    assert s_cercano.total != s_lejano.total


def test_score_neutral_de_comision_sin_perfil_conocido():
    """Sin `SettlementProfile`, la dimensión de comisión no inventa una
    cercanía ni castiga por un dato que no tiene: se abstiene (100),
    mismo principio que ADR-4 (ausencia de evidencia nunca es castigo)."""
    grupo = [
        _inv("E1", "1000.00", "2026-07-10"),
        _inv("E2", "500.00", "2026-07-10"),
    ]
    score = score_group(grupo, "1500.00", perfil=None, total_candidates=1)
    assert score.commission_score == Decimal("100")


# ---------------------------------------------------------------------------
# Dimensión 2: tamaño del grupo (menos facturas = mejor, salvo evidencia
# contraria de las otras 3 dimensiones).
# ---------------------------------------------------------------------------

def test_grupo_mas_chico_produce_mejor_score_de_tamano():
    fecha = "2026-07-10"
    net = "1000.00"
    grupo_chico = [
        _inv("F1", "500.00", fecha),
        _inv("F2", "500.00", fecha),
    ]
    grupo_grande = [
        _inv("G1", "250.00", fecha),
        _inv("G2", "250.00", fecha),
        _inv("G3", "250.00", fecha),
        _inv("G4", "250.00", fecha),
    ]
    s_chico = score_group(grupo_chico, net, perfil=CLIP, total_candidates=1)
    s_grande = score_group(grupo_grande, net, perfil=CLIP, total_candidates=1)

    # Misma suma, misma fecha (dispersión 0 en ambos), misma unicidad —
    # solo cambia el tamaño del grupo.
    assert s_chico.date_score == s_grande.date_score
    assert s_chico.commission_score == s_grande.commission_score
    assert s_chico.uniqueness_score == s_grande.uniqueness_score
    assert s_chico.size_score > s_grande.size_score
    assert s_chico.total > s_grande.total
    assert s_chico.total != s_grande.total


def test_tamano_no_es_veto_evidencia_contraria_de_otras_dimensiones_puede_ganar():
    """'Menos facturas = mejor, salvo evidencia contraria' — un grupo más
    grande con MEJOR comisión y MEJOR compacidad de fechas puede seguir
    ganando el score compuesto sobre uno más chico peor en esas otras 2
    dimensiones; el tamaño es una señal más, no un veto absoluto."""
    net = "20192.00"
    nominal_rate = Decimal("0.0395")   # nominal exacto de Clip

    # Grupo grande (4 facturas) con comisión implícita EXACTA al nominal
    # y fechas perfectamente compactas.
    bruto_grande = (Decimal(net) / (Decimal("1") - nominal_rate)
                    ).quantize(Decimal("0.01"))
    grupo_grande_bueno = [
        _inv("H1", bruto_grande / 4, "2026-07-10"),
        _inv("H2", bruto_grande / 4, "2026-07-10"),
        _inv("H3", bruto_grande / 4, "2026-07-10"),
        _inv("H4", bruto_grande / 4, "2026-07-10"),
    ]
    # Grupo chico (2 facturas) con comisión implícita 0% (lejos del
    # nominal) y fechas dispersas 30 días.
    grupo_chico_malo = [
        _inv("I1", Decimal(net) / 2, "2026-06-10"),
        _inv("I2", Decimal(net) / 2, "2026-07-10"),
    ]

    s_grande_bueno = score_group(grupo_grande_bueno, net, perfil=CLIP,
                                  total_candidates=1)
    s_chico_malo = score_group(grupo_chico_malo, net, perfil=CLIP,
                                total_candidates=1)

    assert s_grande_bueno.size_score < s_chico_malo.size_score  # tamaño solo
    assert s_grande_bueno.commission_score > s_chico_malo.commission_score
    assert s_grande_bueno.date_score > s_chico_malo.date_score
    # El compuesto favorece al grupo grande pese a ser peor en tamaño.
    assert s_grande_bueno.total > s_chico_malo.total


# ---------------------------------------------------------------------------
# Dimensión 3: unicidad (único candidato en la banda = score más alto).
# ---------------------------------------------------------------------------

def test_candidato_unico_produce_mejor_score_que_candidato_ambiguo():
    grupo = [
        _inv("J1", "500.00", "2026-07-10"),
        _inv("J2", "500.00", "2026-07-10"),
    ]
    s_unico = score_group(grupo, "1000.00", perfil=CLIP, total_candidates=1)
    s_ambiguo_de_2 = score_group(grupo, "1000.00", perfil=CLIP,
                                  total_candidates=2)
    s_ambiguo_de_3 = score_group(grupo, "1000.00", perfil=CLIP,
                                  total_candidates=3)

    assert s_unico.uniqueness_score == Decimal("100")
    assert s_unico.uniqueness_score > s_ambiguo_de_2.uniqueness_score
    assert s_ambiguo_de_2.uniqueness_score > s_ambiguo_de_3.uniqueness_score
    assert s_unico.total > s_ambiguo_de_2.total > s_ambiguo_de_3.total


# ---------------------------------------------------------------------------
# Caso real de subset-sum: 3+ facturas suman exactamente un depósito
# (candidato único -> score alto, uniqueness_score=100).
# ---------------------------------------------------------------------------

def test_subset_sum_real_3_facturas_candidato_unico_score_alto():
    facturas = [
        _inv("K1", "3556.00", "2026-07-10"),
        _inv("K2", "6796.00", "2026-07-10"),
        _inv("K3", "9840.00", "2026-07-10"),
        # Ruido: no participa en ninguna combinación que cuadre.
        _inv("K4", "1234.56", "2026-07-01"),
    ]
    montos = [Decimal(f["total"]) for f in facturas]
    net_deposit = "20192.00"

    candidatos = find_matching_subsets(montos, net_deposit, CLIP.tasa_comision_min)
    assert len(candidatos) == 1   # candidato único real, no fabricado
    grupo_facturas = candidatos[0].items(facturas)
    assert {f["folio_fiscal"] for f in grupo_facturas} == {"K1", "K2", "K3"}

    score = score_group(grupo_facturas, net_deposit, perfil=CLIP,
                         total_candidates=len(candidatos))
    assert score.uniqueness_score == Decimal("100")
    assert score.date_dispersion_days == 0
    assert 0 <= score.total <= 100

    # El mismo candidato, pero puntuado como si compitiera con otro
    # (ambigüedad) debe salir peor calificado: la unicidad real (single
    # candidate) es una ventaja que el score compuesto sí refleja.
    score_si_fuera_ambiguo = score_group(grupo_facturas, net_deposit,
                                          perfil=CLIP, total_candidates=2)
    assert score.total > score_si_fuera_ambiguo.total


# ---------------------------------------------------------------------------
# Caso de NO match: ningún subconjunto cae en la banda -> nada que
# puntuar. `score_group` nunca fabrica un subconjunto (ADR-1).
# ---------------------------------------------------------------------------

def test_sin_candidatos_en_la_banda_no_hay_nada_que_puntuar():
    facturas = [
        _inv("L1", "100.00", "2026-07-10"),
        _inv("L2", "200.00", "2026-07-10"),
        _inv("L3", "50.00", "2026-07-10"),
    ]
    montos = [Decimal(f["total"]) for f in facturas]
    # Ningún subconjunto de {100, 200, 50} puede sumar (ni acercarse a)
    # $999,999.00 dentro de la banda de comisión de Clip.
    candidatos = find_matching_subsets(montos, "999999.00", CLIP.tasa_comision_min)
    assert candidatos == []   # nunca se inventa un candidato (ADR-1)

    # score_candidates sobre una lista vacía de grupos no puntúa nada —
    # nunca fabrica un score para "el más parecido".
    assert score_candidates([], "999999.00", perfil=CLIP) == []


def test_score_group_rechaza_lista_vacia_de_facturas():
    """No existe 'el score del subconjunto vacío' — quien llama nunca
    debe invocar esto sin un subconjunto real ya encontrado por el
    subset-sum (ADR-1)."""
    with pytest.raises(ValueError):
        score_group([], "1000.00", perfil=CLIP, total_candidates=1)


# ---------------------------------------------------------------------------
# Caso de ambigüedad real: 2 combinaciones válidas para el MISMO depósito,
# con distinta dispersión de fechas -> subset-sum real las encuentra
# ambas (nunca trunca a 1), y el score de cada una es distinto (aunque
# ninguna se marca como "la elegida" solo por el score: eso lo decide un
# humano, ADR-2/REQ-CONC-008 — este test solo cubre el scoring).
# ---------------------------------------------------------------------------

def test_ambiguedad_real_2_candidatos_scores_distintos_ninguno_autoresuelto():
    facturas = [
        _inv("M1", "500.00", "2026-07-01"),   # + M2 = $1,000.00, dispersión 0
        _inv("M2", "500.00", "2026-07-01"),
        _inv("M3", "300.00", "2026-06-01"),   # + M4 = $1,000.00, dispersión 34d
        _inv("M4", "700.00", "2026-07-05"),
    ]
    montos = [Decimal(f["total"]) for f in facturas]
    net_deposit = "1000.00"

    candidatos = find_matching_subsets(montos, net_deposit, CLIP.tasa_comision_min)
    # Ambigüedad real: 2 combinaciones distintas cuadran la misma banda.
    assert len(candidatos) == 2

    grupos = [c.items(facturas) for c in candidatos]
    scores = score_candidates(grupos, net_deposit, perfil=CLIP)
    assert len(scores) == 2

    # Todos comparten el mismo total_candidates (=2) -> mismo
    # uniqueness_score para ambos; ninguno queda "premiado" solo por
    # unicidad, porque ninguno es único.
    assert scores[0].total_candidates == scores[1].total_candidates == 2
    assert scores[0].uniqueness_score == scores[1].uniqueness_score

    # La suma es idéntica en ambos ($1,000.00 exactos) -> misma comisión
    # implícita (0%) y mismo tamaño (2 facturas cada uno); la ÚNICA
    # dimensión que distingue a los 2 candidatos es la dispersión de
    # fechas, y por eso sus scores totales son distintos.
    assert scores[0].commission_score == scores[1].commission_score
    assert scores[0].size_score == scores[1].size_score
    dispersiones = sorted(s.date_dispersion_days for s in scores)
    assert dispersiones == [0, 34]
    assert scores[0].total != scores[1].total

    # El score, por sí solo, NUNCA resuelve la ambigüedad: eso es
    # responsabilidad exclusiva de `_pass_group`/un humano (ADR-2). Este
    # módulo solo expone el número — no marca ningún candidato como
    # aplicado ni descarta al otro.
    for s in scores:
        assert isinstance(s, GroupScore)
        assert 0 <= s.total <= 100


# ---------------------------------------------------------------------------
# Cobertura de rango y de la función auxiliar de comisión implícita.
# ---------------------------------------------------------------------------

def test_implied_commission_rate_basico():
    net_cents = to_cents("1000.00")
    sum_cents = to_cents("1050.00")
    rate = implied_commission_rate(sum_cents, net_cents)
    assert rate == Decimal("50") / Decimal("1050")


def test_implied_commission_rate_nunca_negativa():
    # sum < net no debería ocurrir viniendo de la banda real, pero el
    # cálculo se blinda igual: nunca produce una tasa negativa sin sentido.
    rate = implied_commission_rate(sum_cents=900, net_cents=1000)
    assert rate == Decimal("0")


@pytest.mark.parametrize("total_candidates", [1, 2, 5, 10])
def test_score_siempre_en_rango_0_100(total_candidates):
    grupo = [
        _inv("N1", "111.11", "2026-01-01"),
        _inv("N2", "222.22", "2026-03-15"),
        _inv("N3", "333.33", "2026-06-30"),
    ]
    net = str(sum(Decimal(i["total"]) for i in grupo))
    score = score_group(grupo, net, perfil=CLIP,
                         total_candidates=total_candidates)
    assert 0 <= score.total <= 100
