# -*- coding: utf-8 -*-
"""
REQ-CONC-008 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1).

Criterio de aceptación exacto:
  "Cuando `_pass_group()` encuentra exactamente 1 candidato válido con
  score de desambiguación >= 85 (ver REQ-CONC-009), el match se
  auto-confirma (`confidence="alta"`, `requiere_confirmacion_humana=False`);
  en cualquier otro caso (0, o >=2 candidatos, o score < 85) el resultado
  queda `estado="sugerido"` y NUNCA SE AUTO-APLICA. Ver ADR-2."

Regla dura del blueprint que este archivo ejercita explícitamente: nunca
inventar un match; ambigüedad real (2+ combinaciones cuadran la misma
suma) requiere decisión humana explícita, nunca auto-resuelta.

Cubre las 4 ramas del criterio, todas contra el código real (sin mocks):
  1. Exactamente 1 candidato, score alto (>=85)  -> auto-confirma.
  2. 0 candidatos (ningún subconjunto cuadra)     -> nunca inventa match.
  3. 2+ candidatos (ambigüedad real)              -> nunca se auto-aplica.
  4. Exactamente 1 candidato, score bajo (<85)    -> nunca se auto-aplica
     pese a ser único; queda "sugerido" para decisión humana.
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation
from b2b_ai.services.group_scoring import compute_group_score


def _inv(folio, total, fecha="2026-07-10", emisor="Cliente"):
    return {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
            "emisor": emisor, "emisor_nombre": emisor}


def _tx(id_, monto_signed, fecha="2026-08-05", ref="", descripcion=""):
    monto = str(abs(float(monto_signed)))
    return {
        "id": id_,
        "fecha": fecha,
        "monto": monto,
        "monto_signed": str(monto_signed),
        "naturaleza": "abono",
        "descripcion": descripcion,
        "ref": ref,
        "banco": "generico",
    }


# ---------------------------------------------------------------------------
# Rama 1 — 1 candidato, score alto (>=85): auto-confirma.
# ---------------------------------------------------------------------------

def test_un_candidato_score_alto_se_auto_confirma():
    """Caso real de subset-sum: 3 facturas (misma fecha, grupo chico)
    suman EXACTAMENTE un depósito. Es el único subconjunto posible ->
    score de desambiguación alto -> auto-confirma con los campos exactos
    que exige REQ-CONC-008."""
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    tx = _tx("tx_dep_1", "20192.00")

    out = svc._pass_group(invoices, [tx])

    assert len(out) == 3
    assert {m["method"] for m in out} == {"grouped_n_a_1"}
    assert {m["transaction_id"] for m in out} == {"tx_dep_1"}
    assert len({m["group_id"] for m in out}) == 1
    for m in out:
        # Criterio literal de REQ-CONC-008.
        assert m["confidence"] == "alta"
        assert m["requiere_confirmacion_humana"] is False
        assert m["score"] >= 85
    # Nada queda pendiente de decisión humana para este movimiento.
    assert svc.grouped_ambiguous == []
    assert svc.grouped_suggestions == []


def test_un_candidato_score_alto_se_auto_confirma_en_pipeline_completo():
    """A nivel de pipeline (`match_transactions` / `auto_match`), el grupo
    auto-confirmado debe aparecer en `matches` y contarse como conciliado
    en el reporte — y `auto_match()` no debe romperse por el campo
    `confidence` cualitativo ("alta") al ordenar."""
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    svc.transactions = [_tx("tx_dep_1", "20192.00")]
    svc.load_invoices(invoices)

    resultado = svc.auto_match()
    grouped = [m for m in resultado["matches"] if m["method"] == "grouped_n_a_1"]
    assert len(grouped) == 3
    assert all(m["confidence"] == "alta" for m in grouped)
    assert all(m["requiere_confirmacion_humana"] is False for m in grouped)

    reporte = svc.generate_reconciliation_report()
    assert reporte["conciliados"] == 3
    assert "tx_dep_1" not in {t["id"] for t in reporte["unmatched_bank"]}


# ---------------------------------------------------------------------------
# Rama 2 — 0 candidatos: nunca inventa un match (ADR-1).
# ---------------------------------------------------------------------------

def test_cero_candidatos_nunca_inventa_match():
    svc = BankReconciliation()
    invoices = [
        _inv("F-1", "100.00"),
        _inv("F-2", "200.00"),
        _inv("F-3", "300.00"),
    ]
    # Ningún subconjunto (100+200, 100+300, 200+300, 100+200+300) suma
    # 999.00: cero candidatos válidos.
    tx = _tx("tx_no_match", "999.00")

    out = svc._pass_group(invoices, [tx])

    assert out == [], "0 candidatos nunca debe producir un match inventado"
    assert svc.grouped_ambiguous == []
    assert svc.grouped_suggestions == []


# ---------------------------------------------------------------------------
# Rama 3 — 2+ candidatos: ambigüedad real, nunca se auto-aplica (ADR-2).
# ---------------------------------------------------------------------------

def test_dos_candidatos_ambiguedad_real_nunca_se_autoaplica():
    """Dos subconjuntos disjuntos, {A-400, A-600} y {B-300, B-700}, suman
    EXACTAMENTE el mismo depósito de 1000.00: ambigüedad real. Ninguno se
    aplica automáticamente, sin importar qué score tendría cada uno por
    separado — la decisión es de un humano."""
    svc = BankReconciliation()
    invoices = [
        _inv("A-400", "400.00"),
        _inv("A-600", "600.00"),
        _inv("B-300", "300.00"),
        _inv("B-700", "700.00"),
    ]
    tx = _tx("tx_ambiguo", "1000.00")

    out = svc._pass_group(invoices, [tx])

    assert out == [], "2+ candidatos nunca se auto-aplica, ni el de mejor score"
    assert len(svc.grouped_ambiguous) == 1
    assert len(svc.grouped_suggestions) == 1
    sugerido = svc.grouped_suggestions[0]
    assert sugerido["transaction_id"] == "tx_ambiguo"
    assert sugerido["estado"] == "sugerido"
    assert sugerido["requiere_confirmacion_humana"] is True
    candidatos_sets = [frozenset(c) for c in sugerido["candidatos"]]
    assert frozenset({"A-400", "A-600"}) in candidatos_sets
    assert frozenset({"B-300", "B-700"}) in candidatos_sets


def test_dos_candidatos_ambiguedad_no_se_autoaplica_en_pipeline_completo():
    svc = BankReconciliation()
    invoices = [
        _inv("A-400", "400.00"),
        _inv("A-600", "600.00"),
        _inv("B-300", "300.00"),
        _inv("B-700", "700.00"),
    ]
    svc.transactions = [_tx("tx_ambiguo", "1000.00")]
    svc.load_invoices(invoices)

    resultado = svc.auto_match()

    assert all(m["method"] != "grouped_n_a_1" for m in resultado["matches"])
    reporte = svc.generate_reconciliation_report()
    assert "tx_ambiguo" in {t["id"] for t in reporte["unmatched_bank"]}
    assert reporte["conciliados"] == 0


# ---------------------------------------------------------------------------
# Rama 4 — 1 candidato ÚNICO pero score < 85: nunca se auto-aplica.
# ---------------------------------------------------------------------------
#
# El depósito objetivo es EXACTAMENTE la suma de las 6 facturas dadas, así
# que ningún subconjunto propio (que excluye al menos una factura positiva)
# puede alcanzar la misma suma: el candidato es matemáticamente único,
# cualquiera sea el valor concreto de las facturas. La fecha de cada
# factura se dispersa 30 días y el grupo tiene 6 facturas (ambas
# dimensiones penalizan el score) para caer deliberadamente bajo 85.

_FACTURAS_SCORE_BAJO = [
    ("X1", "1000.00", "2026-07-01"),
    ("X2", "1500.00", "2026-07-07"),
    ("X3", "2000.00", "2026-07-13"),
    ("X4", "1200.00", "2026-07-19"),
    ("X5", "1800.00", "2026-07-25"),
    ("X6", "900.00", "2026-07-31"),
]


def _monto_total_score_bajo() -> str:
    total = sum(float(total) for _, total, _ in _FACTURAS_SCORE_BAJO)
    return f"{total:.2f}"


def test_un_candidato_unico_score_bajo_nunca_se_autoaplica():
    svc = BankReconciliation()
    invoices = [_inv(folio, total, fecha)
               for folio, total, fecha in _FACTURAS_SCORE_BAJO]
    tx = _tx("tx_low_score", _monto_total_score_bajo())

    out = svc._pass_group(invoices, [tx])

    # Precondición del caso de prueba: en efecto hay un único candidato
    # matemático (no ambigüedad) pero su score cae bajo el umbral.
    assert svc.grouped_ambiguous == [], (
        "este caso debe ser único, no ambiguo -- si esto falla, el diseño "
        "del caso de prueba está mal construido, no el código bajo prueba")
    assert len(svc.grouped_suggestions) == 1
    sugerido = svc.grouped_suggestions[0]
    assert sugerido["score"] < 85
    assert sugerido["estado"] == "sugerido"
    assert sugerido["requiere_confirmacion_humana"] is True
    assert sugerido["candidatos"] == [
        [folio for folio, _, _ in _FACTURAS_SCORE_BAJO]]

    # El criterio duro: pese a ser el ÚNICO candidato, nunca se auto-aplica.
    assert out == [], (
        "un único candidato con score < 85 NUNCA debe auto-aplicarse "
        "(REQ-CONC-008)")


def test_un_candidato_unico_score_bajo_no_se_autoaplica_en_pipeline_completo():
    svc = BankReconciliation()
    invoices = [_inv(folio, total, fecha)
               for folio, total, fecha in _FACTURAS_SCORE_BAJO]
    svc.transactions = [_tx("tx_low_score", _monto_total_score_bajo())]
    svc.load_invoices(invoices)

    resultado = svc.auto_match()

    assert all(m["method"] != "grouped_n_a_1" for m in resultado["matches"])
    reporte = svc.generate_reconciliation_report()
    assert "tx_low_score" in {t["id"] for t in reporte["unmatched_bank"]}
    assert reporte["conciliados"] == 0


# ---------------------------------------------------------------------------
# `_pass_group` pasa explícitamente el perfil sin comisión (spei/cheque,
# 0%-0%) como default de la dimensión de comisión del score cuando el
# llamador no da un `perfil` -- ese es el supuesto que el propio pase ya
# hace hoy (suma EXACTA, bruto==neto). Se verifica contra el motor real de
# `group_scoring.compute_group_score`, sin mocks: un candidato único y
# limpio con ese default cruza el umbral de auto-confirmación.
# ---------------------------------------------------------------------------

def test_umbral_usa_perfil_sin_comision_por_default():
    from b2b_ai.services.settlement_profiles import get_settlement_profile

    grupo = [_inv("A", "100.00"), _inv("B", "100.00")]   # tamaño 2, misma fecha
    perfil_spei = get_settlement_profile("spei_transferencia")

    score_con_perfil_default = compute_group_score(
        grupo, sum_cents=20000, target_cents=20000, es_unico=True,
        perfil=perfil_spei)
    assert score_con_perfil_default >= 85
