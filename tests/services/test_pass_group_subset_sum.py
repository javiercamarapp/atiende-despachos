# -*- coding: utf-8 -*-
"""
REQ-CONC-003 — `_pass_group()`: conciliación N-a-1 (varias facturas suman
UN solo movimiento bancario).

Cubre el criterio de aceptación exacto del blueprint
(`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC):

  - subset-sum real con 3+ facturas que suman exactamente un depósito
    -> 3 filas de match, mismo `group_id`, mismo `transaction_id`,
    `method="grouped_n_a_1"`.
  - NO match: ningún subconjunto cuadra la suma -> nunca se inventa un
    cruce (ADR-1).
  - Ambigüedad real (2+ combinaciones cuadran la misma suma) -> ninguna
    se auto-aplica; queda para decisión humana explícita (ADR-2).
  - El pase está insertado DESPUÉS de `_pass_exact` y ANTES de
    `_pass_partial` en `match_transactions()`.
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation


def _tx(id_, monto_signed, ref="", descripcion="", fecha="2026-07-15",
        naturaleza=None):
    monto = str(abs(float(monto_signed)))
    return {
        "id": id_,
        "fecha": fecha,
        "monto": monto,
        "monto_signed": str(monto_signed),
        "naturaleza": naturaleza or ("abono" if float(monto_signed) >= 0
                                     else "cargo"),
        "descripcion": descripcion,
        "ref": ref,
        "banco": "generico",
    }


def _inv(folio, total, fecha="2026-07-10", emisor="Cliente"):
    return {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
            "emisor": emisor, "emisor_nombre": emisor}


# ---------------------------------------------------------------------------
# Caso real de subset-sum: 3 facturas suman exactamente el depósito
# ---------------------------------------------------------------------------

def test_pass_group_3_facturas_suman_deposito():
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    tx = _tx("tx_dep_1", "20192.00")

    out = svc._pass_group(invoices, [tx])

    assert len(out) == 3
    group_ids = {m["group_id"] for m in out}
    tx_ids = {m["transaction_id"] for m in out}
    methods = {m["method"] for m in out}
    assert group_ids == {out[0]["group_id"]}          # un solo group_id
    assert tx_ids == {"tx_dep_1"}                      # un solo transaction_id
    assert methods == {"grouped_n_a_1"}
    invoice_refs = {m["invoice_ref"] for m in out}
    assert invoice_refs == {"COB-1", "COB-2", "COB-3"}  # 3 refs distintas


def test_pass_group_via_match_transactions_pipeline_completo():
    """Prueba de integración: el pase corre dentro de match_transactions()
    y produce el grupo completo cuando se invoca por la fachada pública."""
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    stmt = [_tx("tx_dep_1", "20192.00")]

    matches = svc.match_transactions(invoices, stmt)

    grouped = [m for m in matches if m["method"] == "grouped_n_a_1"]
    assert len(grouped) == 3
    assert len({m["group_id"] for m in grouped}) == 1
    assert len({m["transaction_id"] for m in grouped}) == 1


def test_pass_group_insertado_antes_de_partial():
    """El pase de grupo debe correr ANTES que `_pass_partial`: si un
    umbral de tolerancia de monto muy laxo permitiera que `_pass_partial`
    "robara" el depósito para una sola factura (por solapamiento de
    referencia), el pase de grupo debe haberlo consumido primero y dejar
    el N-a-1 correcto — nunca un cruce 1-a-1 inventado sobre un depósito
    que en realidad es la suma de 3 facturas."""
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    # La referencia del banco menciona los 3 folios: si `_pass_partial`
    # corriera primero, con una tolerancia de monto absurdamente amplia
    # podría "cuadrar" el depósito completo contra una sola factura por
    # puro solape de tokens en la referencia.
    stmt = [_tx("tx_dep_1", "20192.00",
                ref="COB-1 COB-2 COB-3 LIQUIDACION TERMINAL",
                descripcion="Liquidacion terminal")]

    matches = svc.match_transactions(
        invoices, stmt, date_tolerance_days=3, monto_tolerance_pct=500)

    grouped = [m for m in matches if m["method"] == "grouped_n_a_1"]
    partial = [m for m in matches if m["method"] == "parcial"]
    assert len(grouped) == 3, (
        "el pase de grupo debe consumir el depósito antes de que "
        "_pass_partial pueda inventar un cruce 1-a-1 con tolerancia laxa")
    assert len(partial) == 0
    assert len({m["transaction_id"] for m in grouped}) == 1


# ---------------------------------------------------------------------------
# Caso de NO match: nunca inventar un cruce (ADR-1)
# ---------------------------------------------------------------------------

def test_pass_group_sin_combinacion_valida_no_inventa_match():
    svc = BankReconciliation()
    invoices = [
        _inv("F-1", "100.00"),
        _inv("F-2", "200.00"),
        _inv("F-3", "300.00"),
    ]
    # Ningún subconjunto (100+200=300, 100+300=400, 200+300=500,
    # 100+200+300=600) suma 999.00.
    tx = _tx("tx_no_match", "999.00")

    out = svc._pass_group(invoices, [tx])

    assert out == []
    assert svc.grouped_ambiguous == []


def test_pass_group_sin_match_end_to_end_deja_pendiente():
    """El movimiento sin combinación válida debe quedar sin conciliar en
    el pipeline completo, no forzado a ningún método."""
    svc = BankReconciliation()
    invoices = [
        _inv("F-1", "100.00"),
        _inv("F-2", "200.00"),
        _inv("F-3", "300.00"),
    ]
    stmt = [_tx("tx_no_match", "999.00", ref="SIN-RELACION",
                descripcion="movimiento sin relación textual")]

    matches = svc.match_transactions(invoices, stmt)

    assert all(m["transaction_id"] != "tx_no_match" for m in matches)


# ---------------------------------------------------------------------------
# Ambigüedad real: 2+ combinaciones cuadran la misma suma (ADR-2)
# ---------------------------------------------------------------------------

def test_pass_group_ambiguedad_real_nunca_auto_resuelve():
    svc = BankReconciliation()
    # Dos subconjuntos disjuntos, ambos suman exactamente 1000.00:
    #   {400, 600} y {300, 700}
    invoices = [
        _inv("A-400", "400.00"),
        _inv("A-600", "600.00"),
        _inv("B-300", "300.00"),
        _inv("B-700", "700.00"),
    ]
    tx = _tx("tx_ambiguo", "1000.00")

    out = svc._pass_group(invoices, [tx])

    # Ninguna combinación se aplica automáticamente.
    assert out == []
    # Pero la ambigüedad queda registrada explícitamente para revisión
    # humana, listando AMBOS candidatos (nunca se trunca a 1 en silencio).
    assert len(svc.grouped_ambiguous) == 1
    caso = svc.grouped_ambiguous[0]
    assert caso["transaction_id"] == "tx_ambiguo"
    assert len(caso["candidatos"]) == 2
    candidatos_sets = [frozenset(c) for c in caso["candidatos"]]
    assert frozenset({"A-400", "A-600"}) in candidatos_sets
    assert frozenset({"B-300", "B-700"}) in candidatos_sets


def test_pass_group_ambiguedad_no_se_autoaplica_en_pipeline_completo():
    svc = BankReconciliation()
    invoices = [
        _inv("A-400", "400.00"),
        _inv("A-600", "600.00"),
        _inv("B-300", "300.00"),
        _inv("B-700", "700.00"),
    ]
    stmt = [_tx("tx_ambiguo", "1000.00")]

    matches = svc.match_transactions(invoices, stmt)

    # Nunca debe existir un cruce grouped_n_a_1 para un caso ambiguo.
    assert all(m["method"] != "grouped_n_a_1" for m in matches
               if m["transaction_id"] == "tx_ambiguo")
    assert len(svc.grouped_ambiguous) == 1


# ---------------------------------------------------------------------------
# Consumo de free_inv/stmt vía el mismo `_consumed()` que los demás pases
# ---------------------------------------------------------------------------

def test_pass_group_consume_facturas_y_movimiento():
    """Tras agrupar, las 3 facturas y el movimiento deben quedar
    consumidos: `_pass_partial`/`_pass_ai` no deben volver a tocarlos."""
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    stmt = [_tx("tx_dep_1", "20192.00")]

    matches = svc.match_transactions(invoices, stmt)
    invoice_refs_matched, tx_ids_matched = BankReconciliation._consumed(matches)

    assert invoice_refs_matched == {"COB-1", "COB-2", "COB-3"}
    assert tx_ids_matched == {"tx_dep_1"}
    # Ningún método adicional (parcial/ai) tocó estos ids.
    assert all(m["method"] == "grouped_n_a_1" for m in matches)
