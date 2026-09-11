# -*- coding: utf-8 -*-
"""
REQ-CONC-014 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1). Ver ADR-1.

Criterio de aceptación exacto:
  "Cuando ningún subconjunto de facturas cae dentro de la banda [A,
  A_grossed_up] para un movimiento bancario, el sistema debe dejarlo
  explícitamente en `estado="sin_conciliar"` con el detalle de los
  candidatos más cercanos evaluados (para trazabilidad); el sistema NUNCA
  debe asignar automáticamente el candidato de menor diferencia si ese
  candidato está fuera de la banda de tolerancia."

Este archivo ejercita, contra el código real (sin mocks) de
`BankReconciliation._pass_group`:
  1. 0 subconjuntos válidos -> el movimiento aterriza en
     `svc.sin_conciliar` con `estado="sin_conciliar"` explícito.
  2. El candidato individual de menor diferencia (aunque esté MUY cerca
     del monto del depósito) jamás se auto-aplica como match -- ni en
     `_pass_group` en aislado ni en el pipeline completo
     (`match_transactions`): la factura sigue en
     `unmatched_invoices`/`unmatched_bank` del reporte.
  3. El detalle de trazabilidad (`candidatos_mas_cercanos`) SÍ lista los
     candidatos más próximos (para que un humano entienda por qué no hubo
     match), ordenados por cercanía, acotado a un techo -- pero esa lista
     nunca se usa como fuente de un match.
  4. `sin_conciliar` se recalcula desde cero en cada llamada a
     `match_transactions` (no acumula entradas de una corrida anterior),
     igual que `grouped_ambiguous`/`grouped_suggestions`.
  5. Un movimiento CON match válido (subconjunto exacto) nunca aparece en
     `sin_conciliar` -- el estado explícito es solo para el caso 0.
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation


def _inv(folio, total, fecha="2026-07-10", emisor="Cliente"):
    return {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
            "emisor": emisor, "emisor_nombre": emisor}


def _tx(id_, monto_signed, fecha="2026-08-05", ref="", descripcion="",
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


# ---------------------------------------------------------------------------
# 1) 0 subconjuntos válidos -> estado explícito "sin_conciliar"
# ---------------------------------------------------------------------------

def test_cero_subconjuntos_valido_queda_sin_conciliar_explicito():
    svc = BankReconciliation()
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00"),
               _inv("F-3", "3000.00")]
    # Ninguna combinación de 2+ facturas suma exactamente 9999.00.
    tx = _tx("tx1", 9999.00)

    out = svc._pass_group(invoices, [tx])

    assert out == [], "0 candidatos nunca debe producir un match inventado"
    assert len(svc.sin_conciliar) == 1
    entrada = svc.sin_conciliar[0]
    assert entrada["transaction_id"] == "tx1"
    assert entrada["estado"] == "sin_conciliar"
    assert entrada["naturaleza"] == "abono"
    assert float(entrada["monto"]) == 9999.00
    assert "candidatos_mas_cercanos" in entrada
    assert len(entrada["candidatos_mas_cercanos"]) > 0


# ---------------------------------------------------------------------------
# 2) El candidato más cercano NUNCA se auto-aplica, ni siquiera si está a
#    centavos del monto (fuera de la banda porque _pass_group busca suma
#    EXACTA, ADR-1).
# ---------------------------------------------------------------------------

def test_candidato_mas_cercano_fuera_de_banda_nunca_se_autoaplica():
    svc = BankReconciliation()
    # F-2+F-3 suman 5000.00 -- a solo $0.01 del depósito de 5000.01, pero
    # NO exacto: fuera de la banda de tolerancia de este pase.
    invoices = [_inv("F-1", "100.00"), _inv("F-2", "2000.00"),
               _inv("F-3", "3000.00")]
    tx = _tx("tx1", 5000.01)

    out = svc._pass_group(invoices, [tx])

    assert out == [], (
        "el candidato de menor diferencia (F-2+F-3, a 1 centavo) nunca "
        "debe asignarse automáticamente por estar 'tan cerca'")
    assert len(svc.sin_conciliar) == 1
    cercanos = svc.sin_conciliar[0]["candidatos_mas_cercanos"]
    refs_cercanos = {c["invoice_ref"] for c in cercanos}
    # F-2/F-3 (individualmente) deben aparecer en la traza de cercanía,
    # pero repetimos: nunca como un match real en `out`.
    assert "F-2" in refs_cercanos or "F-3" in refs_cercanos


def test_candidato_mas_cercano_nunca_aparece_como_match_en_pipeline_completo():
    """Mismo escenario pero corriendo el pipeline COMPLETO
    (`match_transactions`, exact+group+partial+ai): ninguna de las 3
    facturas termina conciliada contra este movimiento por 'parecido'."""
    svc = BankReconciliation()
    invoices = [_inv("F-1", "100.00"), _inv("F-2", "2000.00"),
               _inv("F-3", "3000.00")]
    tx = _tx("tx1", 5000.01)

    matches = svc.match_transactions(invoices, [tx])

    assert matches == [], (
        "ningún pase (exact/group/partial/ai) debe inventar un match "
        "contra el candidato más cercano fuera de banda")
    svc.load_invoices(invoices)
    svc.transactions = [tx]
    svc.matches = matches
    reporte = svc.generate_reconciliation_report()
    assert reporte["conciliados"] == 0
    assert len(reporte["unmatched_bank"]) == 1
    assert len(reporte["unmatched_invoices"]) == 3


# ---------------------------------------------------------------------------
# 3) Trazabilidad: ordenado por cercanía, acotado a un techo.
# ---------------------------------------------------------------------------

def test_candidatos_mas_cercanos_ordenados_y_acotados():
    svc = BankReconciliation()
    # 8 facturas de montos muy distintos entre sí y del depósito: ninguna
    # combinación de 2+ cuadra exactamente 50000.00.
    invoices = [_inv(f"F-{i}", str(1000 * i)) for i in range(1, 9)]
    tx = _tx("tx1", 50000.00)

    out = svc._pass_group(invoices, [tx])

    assert out == []
    assert len(svc.sin_conciliar) == 1
    cercanos = svc.sin_conciliar[0]["candidatos_mas_cercanos"]
    assert len(cercanos) <= 5, "la traza debe acotarse a un techo razonable"
    diffs = [float(c["diferencia"]) for c in cercanos]
    assert diffs == sorted(diffs), (
        "los candidatos más cercanos deben venir ordenados por cercanía "
        "ascendente")


# ---------------------------------------------------------------------------
# 4) `sin_conciliar` se recalcula desde cero en cada match_transactions.
# ---------------------------------------------------------------------------

def test_sin_conciliar_no_acumula_entre_corridas():
    svc = BankReconciliation()
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00")]
    tx_sin_match = _tx("tx1", 9999.00)

    svc.match_transactions(invoices, [tx_sin_match])
    assert len(svc.sin_conciliar) == 1

    # Segunda corrida con un movimiento distinto que SÍ concilia exacto:
    # la entrada anterior no debe seguir viva.
    tx_exacto = _tx("tx2", 3000.00)
    matches = svc.match_transactions(invoices, [tx_exacto])
    assert len(matches) == 2   # F-1 + F-2 = 3000.00 exacto, grupo válido
    assert svc.sin_conciliar == [], (
        "sin_conciliar debe recalcularse desde cero, no acumular la "
        "entrada de la corrida anterior")


# ---------------------------------------------------------------------------
# 5) Un movimiento con match válido nunca aparece en sin_conciliar.
# ---------------------------------------------------------------------------

def test_movimiento_con_match_valido_no_aparece_en_sin_conciliar():
    svc = BankReconciliation()
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00")]
    tx = _tx("tx1", 3000.00)

    out = svc._pass_group(invoices, [tx])

    assert len(out) == 2
    assert svc.sin_conciliar == []
