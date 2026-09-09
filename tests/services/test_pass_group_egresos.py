# -*- coding: utf-8 -*-
"""
REQ-CONC-012 — `_pass_group()` aplicado simétricamente a EGRESOS
(`naturaleza="cargo"`): varios pagos/comprobantes pendientes (nómina
dispersada, pagos a proveedores) que el banco agrupa en UN SOLO cargo
bancario consolidado.

Mismo criterio de aceptación exacto que REQ-CONC-003/008 para depósitos
(`tests/services/test_pass_group_subset_sum.py`,
`tests/adversarial/test_pass_group_ambiguedad_nunca_autoaplica.py`), solo
que del lado `cargo` en vez de `abono`:

  - subset-sum real con N comprobantes que suman exactamente un cargo
    consolidado -> N filas de match, mismo `group_id`, mismo
    `transaction_id`, `method="grouped_n_a_1"`.
  - Criterio literal del blueprint: "un cargo agrupado de nómina
    dispersado a 5 empleados debe generar 5 filas de match con `group_id`
    compartido, igual que en cobros."
  - NO match: ningún subconjunto cuadra la suma -> nunca se inventa un
    cruce (ADR-1), igual que para depósitos.
  - Ambigüedad real (2+ combinaciones cuadran la misma suma) -> ninguna se
    auto-aplica; queda para decisión humana explícita (ADR-2), igual que
    para depósitos.
  - Único candidato con score < 85 -> nunca se auto-aplica pese a ser
    único (REQ-CONC-008), igual que para depósitos.
  - `_pass_group` sigue tratando abonos y cargos de forma independiente
    dentro del mismo statement (una transacción de cada signo no se
    confunde con la otra).
"""
from __future__ import annotations

from b2b_ai.services.bank_reconciliation import BankReconciliation
from b2b_ai.services.group_scoring import compute_group_score


def _tx(id_, monto_signed, ref="", descripcion="", fecha="2026-07-15",
        naturaleza=None):
    """Movimiento bancario normalizado. Un `monto_signed` negativo es un
    cargo (egreso); positivo es un abono (depósito) — igual convención que
    `tests/services/test_pass_group_subset_sum.py`."""
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


def _comprobante(folio, total, fecha="2026-07-10", emisor="Empleado"):
    """Comprobante/pago pendiente (nómina, proveedor). Misma forma
    genérica que una factura: el motor no distingue cobro de pago, solo
    folio + total + fecha (ver docstring de `_pass_group`)."""
    return {"folio_fiscal": folio, "fecha": fecha, "total": str(total),
            "emisor": emisor, "emisor_nombre": emisor}


# ---------------------------------------------------------------------------
# Caso real de subset-sum: nómina dispersada a 5 empleados en un solo cargo
# ---------------------------------------------------------------------------

def test_pass_group_nomina_5_empleados_en_un_cargo_consolidado():
    """Criterio literal de REQ-CONC-012: un cargo agrupado de nómina
    dispersado a 5 empleados debe generar 5 filas de match con `group_id`
    compartido, igual que en cobros."""
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("NOM-1", "8500.00", emisor="Empleado 1"),
        _comprobante("NOM-2", "9200.00", emisor="Empleado 2"),
        _comprobante("NOM-3", "7650.00", emisor="Empleado 3"),
        _comprobante("NOM-4", "10300.00", emisor="Empleado 4"),
        _comprobante("NOM-5", "6100.00", emisor="Empleado 5"),
    ]
    total = 8500.00 + 9200.00 + 7650.00 + 10300.00 + 6100.00  # 41750.00
    tx = _tx("tx_nomina_1", -total)   # cargo: monto_signed negativo

    out = svc._pass_group(comprobantes, [tx])

    assert len(out) == 5
    group_ids = {m["group_id"] for m in out}
    tx_ids = {m["transaction_id"] for m in out}
    methods = {m["method"] for m in out}
    assert len(group_ids) == 1                          # un solo group_id
    assert tx_ids == {"tx_nomina_1"}                     # un solo transaction_id
    assert methods == {"grouped_n_a_1"}
    invoice_refs = {m["invoice_ref"] for m in out}
    assert invoice_refs == {"NOM-1", "NOM-2", "NOM-3", "NOM-4", "NOM-5"}
    for m in out:
        assert m["confidence"] == "alta"
        assert m["requiere_confirmacion_humana"] is False
        assert m["score"] >= 85
    assert svc.grouped_ambiguous == []
    assert svc.grouped_suggestions == []


def test_pass_group_egresos_via_match_transactions_pipeline_completo():
    """Prueba de integración: el pase corre dentro de match_transactions()
    y produce el grupo completo de egresos cuando se invoca por la
    fachada pública, igual que el caso de depósitos."""
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("PROV-1", "12000.00"),
        _comprobante("PROV-2", "8500.00"),
        _comprobante("PROV-3", "4300.00"),
    ]
    stmt = [_tx("tx_cargo_1", "-24800.00")]

    matches = svc.match_transactions(comprobantes, stmt)

    grouped = [m for m in matches if m["method"] == "grouped_n_a_1"]
    assert len(grouped) == 3
    assert len({m["group_id"] for m in grouped}) == 1
    assert len({m["transaction_id"] for m in grouped}) == 1
    assert {m["invoice_ref"] for m in grouped} == {"PROV-1", "PROV-2", "PROV-3"}


def test_pass_group_egresos_insertado_antes_de_partial():
    """Mismo criterio que para depósitos: el pase de grupo debe consumir
    el cargo consolidado ANTES que `_pass_partial` pueda "robarlo" para
    un cruce 1-a-1 con tolerancia laxa."""
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("PROV-1", "12000.00"),
        _comprobante("PROV-2", "8500.00"),
        _comprobante("PROV-3", "4300.00"),
    ]
    stmt = [_tx("tx_cargo_1", "-24800.00",
                ref="PROV-1 PROV-2 PROV-3 PAGO PROVEEDORES",
                descripcion="Pago consolidado a proveedores")]

    matches = svc.match_transactions(
        comprobantes, stmt, date_tolerance_days=3, monto_tolerance_pct=500)

    grouped = [m for m in matches if m["method"] == "grouped_n_a_1"]
    partial = [m for m in matches if m["method"] == "parcial"]
    assert len(grouped) == 3, (
        "el pase de grupo debe consumir el cargo consolidado antes de que "
        "_pass_partial pueda inventar un cruce 1-a-1 con tolerancia laxa")
    assert len(partial) == 0


# ---------------------------------------------------------------------------
# Caso de NO match: nunca inventar un cruce (ADR-1), también para egresos
# ---------------------------------------------------------------------------

def test_pass_group_egresos_sin_combinacion_valida_no_inventa_match():
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("P-1", "100.00"),
        _comprobante("P-2", "200.00"),
        _comprobante("P-3", "300.00"),
    ]
    # Ningún subconjunto (100+200=300, 100+300=400, 200+300=500,
    # 100+200+300=600) suma 999.00.
    tx = _tx("tx_cargo_no_match", "-999.00")

    out = svc._pass_group(comprobantes, [tx])

    assert out == []
    assert svc.grouped_ambiguous == []


def test_pass_group_egresos_sin_match_end_to_end_deja_pendiente():
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("P-1", "100.00"),
        _comprobante("P-2", "200.00"),
        _comprobante("P-3", "300.00"),
    ]
    stmt = [_tx("tx_cargo_no_match", "-999.00", ref="SIN-RELACION",
                descripcion="cargo sin relación")]

    matches = svc.match_transactions(comprobantes, stmt)

    assert all(m["transaction_id"] != "tx_cargo_no_match" for m in matches)


# ---------------------------------------------------------------------------
# Ambigüedad real: 2+ combinaciones cuadran la misma suma (ADR-2),
# exactamente el mismo patrón que para depósitos.
# ---------------------------------------------------------------------------

def test_pass_group_egresos_ambiguedad_real_nunca_auto_resuelve():
    svc = BankReconciliation()
    # Dos subconjuntos disjuntos, ambos suman exactamente 1000.00 en pagos
    # a proveedores: {P-400, P-600} y {P-300, P-700}.
    comprobantes = [
        _comprobante("P-400", "400.00"),
        _comprobante("P-600", "600.00"),
        _comprobante("P-300", "300.00"),
        _comprobante("P-700", "700.00"),
    ]
    tx = _tx("tx_cargo_ambiguo", "-1000.00")

    out = svc._pass_group(comprobantes, [tx])

    # Ninguna combinación se aplica automáticamente, aunque una tuviera
    # mejor score que la otra.
    assert out == []
    assert len(svc.grouped_ambiguous) == 1
    caso = svc.grouped_ambiguous[0]
    assert caso["transaction_id"] == "tx_cargo_ambiguo"
    assert caso["naturaleza"] == "cargo"
    assert len(caso["candidatos"]) == 2
    candidatos_sets = [frozenset(c) for c in caso["candidatos"]]
    assert frozenset({"P-400", "P-600"}) in candidatos_sets
    assert frozenset({"P-300", "P-700"}) in candidatos_sets
    assert len(svc.grouped_suggestions) == 1
    sugerido = svc.grouped_suggestions[0]
    assert sugerido["estado"] == "sugerido"
    assert sugerido["requiere_confirmacion_humana"] is True


def test_pass_group_egresos_ambiguedad_no_se_autoaplica_en_pipeline_completo():
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("P-400", "400.00"),
        _comprobante("P-600", "600.00"),
        _comprobante("P-300", "300.00"),
        _comprobante("P-700", "700.00"),
    ]
    svc.transactions = [_tx("tx_cargo_ambiguo", "-1000.00")]
    svc.load_invoices(comprobantes)

    resultado = svc.auto_match()

    assert all(m["method"] != "grouped_n_a_1" for m in resultado["matches"])
    assert len(svc.grouped_ambiguous) == 1

    reporte = svc.generate_reconciliation_report()
    assert "tx_cargo_ambiguo" in {t["id"] for t in reporte["unmatched_bank"]}
    assert reporte["conciliados"] == 0


# ---------------------------------------------------------------------------
# Único candidato con score bajo (< 85): nunca se auto-aplica, ni en
# egresos. Mismo diseño de caso que
# `tests/adversarial/test_pass_group_ambiguedad_nunca_autoaplica.py`: el
# cargo objetivo es EXACTAMENTE la suma de todos los comprobantes dados,
# así que el candidato es matemáticamente único; fechas dispersas + grupo
# grande empujan el score bajo el umbral a propósito.
# ---------------------------------------------------------------------------

_COMPROBANTES_SCORE_BAJO = [
    ("N1", "1000.00", "2026-07-01"),
    ("N2", "1500.00", "2026-07-07"),
    ("N3", "2000.00", "2026-07-13"),
    ("N4", "1200.00", "2026-07-19"),
    ("N5", "1800.00", "2026-07-25"),
    ("N6", "900.00", "2026-07-31"),
]


def _monto_total_score_bajo() -> str:
    total = sum(float(total) for _, total, _ in _COMPROBANTES_SCORE_BAJO)
    return f"{total:.2f}"


def test_pass_group_egresos_un_candidato_unico_score_bajo_nunca_se_autoaplica():
    svc = BankReconciliation()
    comprobantes = [_comprobante(folio, total, fecha)
                    for folio, total, fecha in _COMPROBANTES_SCORE_BAJO]
    tx = _tx("tx_cargo_low_score", "-" + _monto_total_score_bajo())

    out = svc._pass_group(comprobantes, [tx])

    assert svc.grouped_ambiguous == [], (
        "este caso debe ser único, no ambiguo -- si esto falla, el diseño "
        "del caso de prueba está mal construido, no el código bajo prueba")
    assert len(svc.grouped_suggestions) == 1
    sugerido = svc.grouped_suggestions[0]
    assert sugerido["score"] < 85
    assert sugerido["estado"] == "sugerido"
    assert sugerido["requiere_confirmacion_humana"] is True

    assert out == [], (
        "un único candidato con score < 85 NUNCA debe auto-aplicarse "
        "(REQ-CONC-008), tampoco en egresos")


# ---------------------------------------------------------------------------
# Independencia de signo: un abono y un cargo del mismo monto absoluto en
# el mismo statement no se confunden entre sí.
# ---------------------------------------------------------------------------

def test_pass_group_no_confunde_abono_y_cargo_del_mismo_statement():
    """Un depósito y un cargo consolidado conviven en el mismo statement,
    cada uno con su propio grupo de comprobantes cuya suma es única (sin
    otra combinación posible del pool completo que también alcance ese
    monto) -- el pase debe resolver ambos, cada uno con su propio
    `group_id`, sin que uno consuma facturas del otro.

    (Montos elegidos deliberadamente para que ninguna combinación cruzada
    del pool completo de 4 comprobantes sume por casualidad el monto del
    otro movimiento -- de lo contrario el caso sería ambigüedad real
    genuina bajo ADR-2, no un bug de "confundir" signos.)
    """
    svc = BankReconciliation()
    comprobantes = [
        # Grupo que cuadra para el depósito (abono): 1200 + 1300 = 2500.
        _comprobante("COB-A", "1200.00"),
        _comprobante("COB-B", "1300.00"),
        # Grupo que cuadra para el cargo (egreso): 475 + 525 = 1000.
        _comprobante("PAG-A", "475.00"),
        _comprobante("PAG-B", "525.00"),
    ]
    stmt = [
        _tx("tx_dep", "2500.00"),     # abono: debe agrupar COB-A + COB-B
        _tx("tx_cargo", "-1000.00"),  # cargo: debe agrupar PAG-A + PAG-B
    ]

    matches = svc.match_transactions(comprobantes, stmt)
    grouped = [m for m in matches if m["method"] == "grouped_n_a_1"]

    dep_refs = {m["invoice_ref"] for m in grouped
                if m["transaction_id"] == "tx_dep"}
    cargo_refs = {m["invoice_ref"] for m in grouped
                  if m["transaction_id"] == "tx_cargo"}
    assert dep_refs == {"COB-A", "COB-B"}
    assert cargo_refs == {"PAG-A", "PAG-B"}
    assert svc.grouped_ambiguous == []


def test_pass_group_pool_compartido_entre_signos_es_ambiguedad_real():
    """Caso adverso deliberado: si el pool de comprobantes NO distingue
    dirección (no hay campo `tipo`/`canal` en la factura, REQ-CONC-015/016
    siguen pendientes) y dos subconjuntos disjuntos del MISMO pool cuadran
    la suma de dos movimientos de signo distinto, eso es ambigüedad real
    -- el motor no tiene forma de saber que un comprobante de nómina no
    debería explicar un depósito. Documenta el límite conocido: nunca se
    auto-aplica ninguno de los dos (ADR-2), consistente con el resto del
    módulo."""
    svc = BankReconciliation()
    comprobantes = [
        _comprobante("COB-A", "400.00"),
        _comprobante("COB-B", "600.00"),
        _comprobante("PAG-A", "250.00"),
        _comprobante("PAG-B", "750.00"),
    ]
    stmt = [
        _tx("tx_dep", "1000.00"),
        _tx("tx_cargo", "-1000.00"),
    ]

    matches = svc.match_transactions(comprobantes, stmt)

    assert all(m["method"] != "grouped_n_a_1" for m in matches)
    # Ambos movimientos generan su propio caso de ambigüedad registrado.
    tx_ids_ambiguos = {c["transaction_id"] for c in svc.grouped_ambiguous}
    assert tx_ids_ambiguos == {"tx_dep", "tx_cargo"}


# ---------------------------------------------------------------------------
# El score de desambiguación (REQ-CONC-009) es el mismo motor para ambos
# signos: verificado contra el motor real, sin mocks.
# ---------------------------------------------------------------------------

def test_umbral_grupo_egresos_usa_perfil_sin_comision_por_default():
    from b2b_ai.services.settlement_profiles import get_settlement_profile

    grupo = [_comprobante("A", "100.00"), _comprobante("B", "100.00")]
    perfil_spei = get_settlement_profile("spei_transferencia")

    score = compute_group_score(
        grupo, sum_cents=20000, target_cents=20000, es_unico=True,
        perfil=perfil_spei)
    assert score >= 85
