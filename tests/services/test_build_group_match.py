# -*- coding: utf-8 -*-
"""
REQ-CONC-010 — `_build_group_match()`: esquema de las filas de match N-a-1.

Criterio de aceptación exacto del blueprint
(`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC, fila REQ-CONC-010):

  `_build_group_match()` debe generar N filas de match (una por factura del
  subconjunto) compartiendo el mismo `transaction_id` y `group_id`, cada una
  con el `method="grouped_n_a_1"`; prueba de esquema: para un grupo de 3
  facturas, el resultado debe tener 3 filas con `transaction_id` idéntico y
  `group_id` idéntico, y `invoice_ref` distinto en cada una.

Este archivo prueba la función directamente (unidad/esquema), además de
verificarla en el contexto de `_pass_group()` con:
  - un caso real de subset-sum con 3+ facturas que suman exactamente un
    depósito (la función SÍ debe invocarse y producir el esquema exigido),
  - un caso de NO match (ningún subconjunto cuadra la suma) donde
    `_build_group_match` nunca debe invocarse — nunca se inventa un match
    (ADR-1),
  - un caso de ambigüedad real (2 combinaciones distintas cuadran la misma
    suma) donde tampoco debe invocarse — la decisión queda para un humano,
    nunca se auto-resuelve (ADR-2).
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation, _build_group_match


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
# Prueba de esquema directa sobre `_build_group_match()` (el criterio literal
# de REQ-CONC-010): para un grupo de 3 facturas, 3 filas, mismo
# transaction_id, mismo group_id, invoice_ref distinto por fila.
# ---------------------------------------------------------------------------

def test_build_group_match_esquema_3_facturas():
    grupo = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    tx = _tx("tx_dep_1", "20192.00")
    group_id = "grp_tx_dep_1"

    rows = _build_group_match(grupo, tx, group_id)

    # N filas, una por factura del subconjunto.
    assert len(rows) == 3

    # Mismo transaction_id en las 3 filas.
    tx_ids = {r["transaction_id"] for r in rows}
    assert tx_ids == {"tx_dep_1"}

    # Mismo group_id en las 3 filas.
    group_ids = {r["group_id"] for r in rows}
    assert group_ids == {"grp_tx_dep_1"}

    # method="grouped_n_a_1" en cada fila.
    methods = {r["method"] for r in rows}
    assert methods == {"grouped_n_a_1"}

    # invoice_ref distinto en cada fila (3 refs únicas para 3 facturas).
    invoice_refs = [r["invoice_ref"] for r in rows]
    assert len(invoice_refs) == len(set(invoice_refs)) == 3
    assert set(invoice_refs) == {"COB-1", "COB-2", "COB-3"}


def test_build_group_match_una_fila_por_factura_no_una_fila_agregada():
    """No debe colapsar el grupo en una sola fila 'resumen': el número de
    filas debe ser exactamente igual al número de facturas del subconjunto,
    también para un grupo de tamaño distinto de 3."""
    grupo = [_inv("A", "100.00"), _inv("B", "200.00"),
             _inv("C", "300.00"), _inv("D", "400.00")]
    tx = _tx("tx_4", "1000.00")

    rows = _build_group_match(grupo, tx, "grp_tx_4")

    assert len(rows) == len(grupo) == 4
    assert {r["invoice_ref"] for r in rows} == {"A", "B", "C", "D"}


def test_build_group_match_cada_fila_conserva_su_propio_monto_de_factura():
    """Cada fila referencia el monto de SU factura (no el total del
    depósito repetido 3 veces) — la agregación del depósito vive en el
    reporte (REQ-CONC-011), no en cada fila individual del grupo."""
    grupo = [_inv("COB-1", "3556.00"), _inv("COB-2", "6796.00"),
             _inv("COB-3", "9840.00")]
    tx = _tx("tx_dep_1", "20192.00")

    rows = _build_group_match(grupo, tx, "grp_tx_dep_1")

    montos_por_ref = {r["invoice_ref"]: r["monto"] for r in rows}
    assert montos_por_ref["COB-1"] == "3556.00"
    assert montos_por_ref["COB-2"] == "6796.00"
    assert montos_por_ref["COB-3"] == "9840.00"


# ---------------------------------------------------------------------------
# Caso real de subset-sum (3+ facturas suman exactamente el depósito) visto
# a través de `_pass_group()`: `_build_group_match` sí debe invocarse y
# producir el esquema exigido.
# ---------------------------------------------------------------------------

def test_pass_group_invoca_build_group_match_con_esquema_correcto():
    svc = BankReconciliation()
    invoices = [
        _inv("COB-1", "3556.00"),
        _inv("COB-2", "6796.00"),
        _inv("COB-3", "9840.00"),
    ]
    tx = _tx("tx_dep_1", "20192.00")

    out = svc._pass_group(invoices, [tx])

    assert len(out) == 3
    assert len({r["transaction_id"] for r in out}) == 1
    assert len({r["group_id"] for r in out}) == 1
    assert {r["method"] for r in out} == {"grouped_n_a_1"}
    assert len({r["invoice_ref"] for r in out}) == 3


# ---------------------------------------------------------------------------
# Caso de NO match: ningún subconjunto cuadra la suma -> `_build_group_match`
# nunca debe invocarse, nunca se inventa un cruce (ADR-1).
# ---------------------------------------------------------------------------

def test_pass_group_sin_combinacion_valida_nunca_llama_build_group_match():
    svc = BankReconciliation()
    invoices = [
        _inv("F-1", "100.00"),
        _inv("F-2", "200.00"),
        _inv("F-3", "300.00"),
    ]
    # Ningún subconjunto (100+200=300, 100+300=400, 200+300=500,
    # 100+200+300=600) suma 999.00: no debe generarse ninguna fila
    # grouped_n_a_1.
    tx = _tx("tx_no_match", "999.00")

    out = svc._pass_group(invoices, [tx])

    assert out == []
    assert svc.grouped_ambiguous == []


# ---------------------------------------------------------------------------
# Caso de ambigüedad real: 2 combinaciones distintas cuadran la misma suma
# -> `_build_group_match` nunca debe invocarse; la decisión queda marcada
# explícitamente para un humano (ADR-2), nunca auto-resuelta.
# ---------------------------------------------------------------------------

def test_pass_group_ambiguedad_real_nunca_llama_build_group_match():
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

    # Ninguna fila grouped_n_a_1 se generó: la ambigüedad nunca se
    # auto-resuelve eligiendo una de las 2 combinaciones válidas.
    assert out == []

    # Pero la ambigüedad queda registrada explícitamente para decisión
    # humana, con AMBOS candidatos (nunca se trunca a 1 en silencio).
    assert len(svc.grouped_ambiguous) == 1
    caso = svc.grouped_ambiguous[0]
    assert caso["transaction_id"] == "tx_ambiguo"
    assert len(caso["candidatos"]) == 2
    candidatos_sets = [frozenset(c) for c in caso["candidatos"]]
    assert frozenset({"A-400", "A-600"}) in candidatos_sets
    assert frozenset({"B-300", "B-700"}) in candidatos_sets
