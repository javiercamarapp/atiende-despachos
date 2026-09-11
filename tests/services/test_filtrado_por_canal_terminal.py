# -*- coding: utf-8 -*-
"""
REQ-CONC-015 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1).

Criterio de aceptación exacto:
  "El filtrado de candidatos debe acotarse por `canal_cobro`
  (terminal/SPEI/cheque/efectivo) e `id_terminal`/cuenta destino cuando el
  dato exista en la factura/cobro pendiente, antes de correr el
  subset-sum, para mantener el universo de candidatos en un tamaño
  tratable (<= 50 típico); prueba: con facturas de 2 terminales distintas
  mezcladas, el subset-sum para el depósito de la terminal A nunca debe
  considerar facturas marcadas de la terminal B."

Ejercita `bank_reconciliation._filtrar_por_canal` (unidad) y
`BankReconciliation._pass_group` end-to-end (comportamiento real, sin
mocks):
  1. Criterio literal: facturas de 2 terminales mezcladas -> el depósito
     de la terminal A solo concilia contra las facturas de la terminal A,
     nunca contra las de la terminal B (aunque una combinación de ambas
     también sumara el depósito).
  2. Sin `canal_cobro`/`id_terminal` en el movimiento (dato faltante,
     histórico previo a REQ-CONC-016): el filtro se abstiene, universo de
     candidatos intacto -- no rompe el comportamiento existente.
  3. Una factura SIN canal/terminal propio es candidata universal (no se
     excluye por default) -- ausencia de dato nunca es un veto.
  4. Filtrado por `canal_cobro` solo (sin `id_terminal`) también excluye
     facturas de un canal distinto.
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import (
    BankReconciliation,
    _filtrar_por_canal,
)


def _inv(folio, total, canal_cobro=None, id_terminal=None,
        fecha="2026-07-10", emisor="Cliente"):
    d = {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
        "emisor": emisor, "emisor_nombre": emisor}
    if canal_cobro is not None:
        d["canal_cobro"] = canal_cobro
    if id_terminal is not None:
        d["id_terminal"] = id_terminal
    return d


def _tx(id_, monto_signed, canal_cobro=None, id_terminal=None,
       fecha="2026-08-05", naturaleza=None):
    monto = str(abs(float(monto_signed)))
    d = {
        "id": id_,
        "fecha": fecha,
        "monto": monto,
        "monto_signed": str(monto_signed),
        "naturaleza": naturaleza or ("abono" if float(monto_signed) >= 0
                                     else "cargo"),
        "descripcion": "",
        "ref": "",
        "banco": "generico",
    }
    if canal_cobro is not None:
        d["canal_cobro"] = canal_cobro
    if id_terminal is not None:
        d["id_terminal"] = id_terminal
    return d


# ---------------------------------------------------------------------------
# Unidad: `_filtrar_por_canal`
# ---------------------------------------------------------------------------

def test_filtrar_por_canal_excluye_id_terminal_distinto():
    candidatos = [
        _inv("F-A1", "100.00", id_terminal="TERM-A"),
        _inv("F-B1", "100.00", id_terminal="TERM-B"),
    ]
    tx = _tx("tx1", 100.00, id_terminal="TERM-A")
    filtrados = _filtrar_por_canal(candidatos, tx)
    assert [i["folio_fiscal"] for i in filtrados] == ["F-A1"]


def test_filtrar_por_canal_excluye_canal_cobro_distinto():
    candidatos = [
        _inv("F-1", "100.00", canal_cobro="terminal"),
        _inv("F-2", "100.00", canal_cobro="spei"),
    ]
    tx = _tx("tx1", 100.00, canal_cobro="terminal")
    filtrados = _filtrar_por_canal(candidatos, tx)
    assert [i["folio_fiscal"] for i in filtrados] == ["F-1"]


def test_filtrar_por_canal_sin_dato_en_tx_no_filtra_nada():
    candidatos = [
        _inv("F-A1", "100.00", id_terminal="TERM-A"),
        _inv("F-B1", "100.00", id_terminal="TERM-B"),
        _inv("F-C1", "100.00"),
    ]
    tx = _tx("tx1", 100.00)   # sin canal_cobro ni id_terminal
    filtrados = _filtrar_por_canal(candidatos, tx)
    assert len(filtrados) == 3, (
        "sin canal_cobro/id_terminal en el movimiento, el filtro debe "
        "abstenerse (comportamiento existente intacto)")


def test_filtrar_por_canal_factura_sin_canal_propio_es_candidata_universal():
    candidatos = [
        _inv("F-A1", "100.00", id_terminal="TERM-A"),
        _inv("F-generica", "100.00"),   # sin id_terminal propio
    ]
    tx = _tx("tx1", 100.00, id_terminal="TERM-A")
    filtrados = _filtrar_por_canal(candidatos, tx)
    refs = {i["folio_fiscal"] for i in filtrados}
    assert refs == {"F-A1", "F-generica"}, (
        "una factura sin canal/terminal propio no debe excluirse por "
        "default -- ausencia de dato nunca es un veto")


# ---------------------------------------------------------------------------
# End-to-end: `_pass_group` con 2 terminales mezcladas (criterio literal)
# ---------------------------------------------------------------------------

def test_deposito_terminal_a_nunca_considera_facturas_terminal_b():
    """Criterio literal de REQ-CONC-015: con facturas de 2 terminales
    distintas mezcladas, el subset-sum para el depósito de la terminal A
    nunca debe considerar facturas marcadas de la terminal B -- incluso
    cuando una combinación CRUZADA (A+B) también sumaría el depósito, lo
    que sin el filtro sería una ambigüedad falsa."""
    svc = BankReconciliation()
    invoices = [
        # Terminal A: 2 facturas que suman EXACTO el depósito de A.
        _inv("A-1", "3000.00", id_terminal="TERM-A"),
        _inv("A-2", "2000.00", id_terminal="TERM-A"),
        # Terminal B: 2 facturas que TAMBIÉN suman 5000.00 -- si el filtro
        # no funcionara, esto sería una ambigüedad real (2 combinaciones
        # válidas) y el pase nunca auto-confirmaría nada (ADR-2). Con el
        # filtro activo, el pool de B ni siquiera se considera para el
        # depósito de A: 1 solo candidato real, se auto-confirma.
        _inv("B-1", "3500.00", id_terminal="TERM-B"),
        _inv("B-2", "1500.00", id_terminal="TERM-B"),
    ]
    tx_a = _tx("tx_a", 5000.00, id_terminal="TERM-A")

    out = svc._pass_group(invoices, [tx_a])

    refs_en_match = {m["invoice_ref"] for m in out}
    assert refs_en_match == {"A-1", "A-2"}, (
        f"el grupo debe usar solo las facturas de TERM-A, obtuvo "
        f"{refs_en_match}")
    assert svc.grouped_ambiguous == [], (
        "sin el cruce entre terminales, este caso NO debe verse como "
        "ambigüedad real -- el filtrado por canal ya descartó el pool de "
        "la otra terminal antes del subset-sum")


def test_deposito_terminal_b_simetrico_nunca_ve_facturas_terminal_a():
    svc = BankReconciliation()
    invoices = [
        _inv("A-1", "3000.00", id_terminal="TERM-A"),
        _inv("A-2", "2000.00", id_terminal="TERM-A"),
        _inv("B-1", "3500.00", id_terminal="TERM-B"),
        _inv("B-2", "1500.00", id_terminal="TERM-B"),
    ]
    tx_b = _tx("tx_b", 5000.00, id_terminal="TERM-B")

    out = svc._pass_group(invoices, [tx_b])

    refs_en_match = {m["invoice_ref"] for m in out}
    assert refs_en_match == {"B-1", "B-2"}


def test_pipeline_completo_dos_terminales_cada_deposito_concilia_su_propia_terminal():
    """Mismo escenario pero vía `match_transactions` (pipeline completo:
    exact+group+partial+ai) con AMBOS depósitos en el mismo statement."""
    svc = BankReconciliation()
    invoices = [
        _inv("A-1", "3000.00", id_terminal="TERM-A"),
        _inv("A-2", "2000.00", id_terminal="TERM-A"),
        _inv("B-1", "3500.00", id_terminal="TERM-B"),
        _inv("B-2", "1500.00", id_terminal="TERM-B"),
    ]
    stmt = [
        _tx("tx_a", 5000.00, id_terminal="TERM-A"),
        _tx("tx_b", 5000.00, id_terminal="TERM-B"),
    ]

    matches = svc.match_transactions(invoices, stmt)

    por_tx = {}
    for m in matches:
        por_tx.setdefault(m["transaction_id"], set()).add(m["invoice_ref"])
    assert por_tx.get("tx_a") == {"A-1", "A-2"}
    assert por_tx.get("tx_b") == {"B-1", "B-2"}
