# -*- coding: utf-8 -*-
"""
REQ-CONC-017 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1).

Criterio de aceptación exacto:
  "El umbral de auto-confirmación del pase de grupo (`score >= 85` Y
  subconjunto único, REQ-CONC-008) debe ser estrictamente más alto y más
  estricto que el umbral de auto-confirmación del pase 1-a-1 existente
  (`_pass_partial`, que hoy no tiene un score explícito comparable pero
  opera con tolerancia de monto del 5% sin desambiguación); documentar y
  verificar con un test de regresión que el pase de grupo nunca
  auto-confirme un caso que el pase 1-a-1 dejaría en revisión manual bajo
  el mismo dato de entrada."

Por qué la comparación no es "mismo número, dos algoritmos" (documentado
aquí porque el criterio lo pide explícitamente):

  `_pass_partial` NO tiene ningún gate de auto-confirmación -- CUALQUIER
  cruce que pase sus dos filtros (monto dentro de `tolerance_pct`,
  overlap de tokens >= 0.25) se aplica automáticamente, sin importar qué
  tan bajo quede el `confidence` resultante (60-89) y sin ningún concepto
  de "candidato único vs. ambiguo" -- toma el de mayor overlap y ya. Es,
  en ese sentido literal, MENOS estricto que `_pass_group`: no existe
  ningún caso que `_pass_partial` "deje en revisión manual" por baja
  confianza, porque no tiene ese concepto en absoluto.

  `_pass_group` sí tiene un gate real de dos capas (REQ-CONC-008/ADR-2):
  (a) el subconjunto debe ser el ÚNICO candidato válido (2+ nunca se
  auto-aplican, sin importar el score) y (b) su score de desambiguación
  debe alcanzar `UMBRAL_AUTO_CONFIRMA_GRUPO=85` -- un umbral
  DELIBERADAMENTE por encima del techo de confidence que `_pass_partial`
  ya acepta sin cuestionar (89, ver `_pass_partial`, "nunca exacto").

Este archivo verifica el regresión concreta y medible que sí es comparable
entre los dos pases: un valor de "confianza" (80, dentro del rango 60-89
que `_pass_partial` auto-aplica SIEMPRE sin gate) que, llevado al score de
desambiguación de `_pass_group` (mismo rango 0-100), NUNCA basta para
auto-confirmar un grupo -- incluso siendo el único candidato -- porque
85 > 80. El pase de grupo exige más evidencia que la que el pase 1-a-1
exige para su propio techo de confianza.
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation
import b2b_ai.services.bank_reconciliation as br


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
# 1) El umbral existe, es explícito y es 85 -- documentado como contrato.
# ---------------------------------------------------------------------------

def test_umbral_auto_confirma_grupo_es_85_explicito():
    assert BankReconciliation.UMBRAL_AUTO_CONFIRMA_GRUPO == 85


# ---------------------------------------------------------------------------
# 2) `_pass_partial` NO tiene gate: un cruce débil (confidence ~= 80,
#    dentro de 60-89) se auto-aplica SIEMPRE, sin ningún concepto de
#    "revisión manual" ni de unicidad de candidato.
# ---------------------------------------------------------------------------

def test_pass_partial_autoaplica_sin_gate_con_confianza_moderada():
    svc = BankReconciliation()
    # Monto a 3% de diferencia (dentro del 5% de tolerancia) + referencia
    # con overlap de tokens moderado (> 0.25, no perfecto): exactamente el
    # tipo de señal "no soy un match exacto pero paso el filtro" que
    # `_pass_partial` acepta sin cuestionar.
    inv = _inv("FOLIO-ABC-123", "1000.00")
    tx = _tx("tx1", 1030.00, ref="pago folio ABC 123 parcial")

    out = svc._pass_partial([inv], [tx], tolerance_pct=5)

    assert len(out) == 1, (
        "_pass_partial debe auto-aplicar este cruce débil sin pedir "
        "ninguna confirmación -- no tiene gate de auto-confirmación")
    match = out[0]
    assert 60 <= match["confidence"] <= 89, (
        f"confidence esperado en el rango 60-89 de _pass_partial, "
        f"obtuvo {match['confidence']}")
    # Nunca existe un campo de "requiere confirmación humana" en un match
    # 1-a-1: se aplicó, punto. Contraste directo con `_pass_group`, que sí
    # lo declara explícitamente (True) cuando no auto-confirma.
    assert "requiere_confirmacion_humana" not in match


# ---------------------------------------------------------------------------
# 3) El MISMO valor de "confianza" (80, dentro del rango que _pass_partial
#    ya acepta sin gate) NUNCA basta para que _pass_group auto-confirme,
#    aunque sea el único candidato -- 85 > 80 (REQ-CONC-008/ADR-2).
# ---------------------------------------------------------------------------

def test_pass_group_nunca_autoconfirma_con_score_que_1a1_ya_aceptaria(monkeypatch):
    svc = BankReconciliation()
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00")]
    tx = _tx("tx1", 3000.00)   # suma exacta -> único candidato real

    # Fuerza el score de desambiguación a 80 -- dentro del rango 60-89 que
    # `_pass_partial` acepta SIEMPRE sin gate, pero por debajo del umbral
    # 85 de `_pass_group` (REQ-CONC-009: el score real se calcula aparte;
    # aquí se aísla la garantía del umbral, mismo patrón que
    # REQ-MIG-005/`calcular_score_compuesto` monkeypatcheado en
    # `test_matching_fuzzy_score.py` para cubrir cualquier score literal).
    monkeypatch.setattr(br, "compute_group_score", lambda *a, **k: 80)

    out = svc._pass_group(invoices, [tx])

    assert out == [], (
        "score=80 (que _pass_partial YA auto-aplicaría sin cuestionar) "
        "nunca debe auto-confirmar un grupo -- el umbral de _pass_group "
        "(85) es estrictamente más exigente")
    assert len(svc.grouped_suggestions) == 1
    sugerido = svc.grouped_suggestions[0]
    assert sugerido["estado"] == "sugerido"
    assert sugerido["requiere_confirmacion_humana"] is True
    assert sugerido["score"] == 80


def test_pass_group_si_autoconfirma_justo_en_el_umbral_85(monkeypatch):
    """Contraparte del test anterior: en el límite exacto (85), si SÍ
    auto-confirma -- el umbral es inclusive (`score >= 85`, REQ-CONC-008
    literal)."""
    svc = BankReconciliation()
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00")]
    tx = _tx("tx1", 3000.00)

    monkeypatch.setattr(br, "compute_group_score", lambda *a, **k: 85)

    out = svc._pass_group(invoices, [tx])

    assert len(out) == 2
    assert all(m["confidence"] == "alta" for m in out)
    assert svc.grouped_suggestions == []


def test_pass_group_84_no_autoconfirma_85_si_frontera_exacta(monkeypatch):
    """Frontera fina: 84 (un punto por debajo) nunca auto-confirma; 85 sí
    -- refuerza que el umbral es un número exacto, no una zona difusa."""
    invoices = [_inv("F-1", "1000.00"), _inv("F-2", "2000.00")]
    tx = _tx("tx1", 3000.00)

    svc_84 = BankReconciliation()
    monkeypatch.setattr(br, "compute_group_score", lambda *a, **k: 84)
    assert svc_84._pass_group(invoices, [tx]) == []

    svc_85 = BankReconciliation()
    monkeypatch.setattr(br, "compute_group_score", lambda *a, **k: 85)
    assert len(svc_85._pass_group(invoices, [tx])) == 2
