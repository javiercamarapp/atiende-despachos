# -*- coding: utf-8 -*-
"""Tests de REQ-CONC-005 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz
REQ-CONC — Conciliación bancaria N-a-1).

Criterio de aceptación de REQ-CONC-005:
  "El algoritmo debe excluir subconjuntos de tamaño 1 (ya cubiertos por
  `_pass_exact`) y limitar el tamaño máximo de subconjunto a un techo
  configurable (default 15); prueba: con 20 facturas candidatas en la
  ventana, ningún subconjunto propuesto debe tener más de 15 elementos ni
  exactamente 1."

Nota sobre el estado real del código (releído antes de escribir esta
prueba, como exige la tarea): el blueprint prevé este algoritmo en un
módulo nuevo `b2b_ai/services/subset_sum.py` (columna "Código previsto"
de REQ-CONC-004/005). Al releer el repo se encontró que una sesión previa
—sin commitear todavía— ya había implementado el subset-sum N-a-1
directamente dentro de `b2b_ai/services/bank_reconciliation.py`
(`_subset_sums_exact`, `_pass_group`, `_build_group_match`), cubriendo de
paso partes de REQ-CONC-003/004/007/008/010 (todos también "pendiente" en
la tabla). Esta tarea NO reubica ese código a un módulo separado — eso
tocaría decisiones de organización de otros requisitos fuera de alcance.
Este archivo se limita a verificar, con pruebas reales sobre el código
que existe hoy, que la función que hace el subset-sum
(`_subset_sums_exact`) cumple específicamente el criterio de
REQ-CONC-005, y además ejercita la regla dura del blueprint ("nunca
inventar un match; ambigüedad real -> decisión humana explícita") pedida
para este lote de trabajo.
"""
from decimal import Decimal

from b2b_ai.services.bank_reconciliation import (
    BankReconciliation,
    _subset_sums_exact,
    _to_cents,
)

# `b2b_ai/services/subset_sum.py` es el módulo que el blueprint prevé
# literalmente como "Código previsto" de REQ-CONC-005. Al momento de
# escribir este archivo apareció en el repo (trabajo en curso, sin
# commitear, de otro requisito de la misma matriz — REQ-CONC-003/004/006/
# 007 — que aún no está conectado a `_pass_group`). Su función general
# `find_subset_sums` ya impone, por diseño propio, exactamente la misma
# regla de REQ-CONC-005 (`min_size = max(2, ...)`, `max_size` default 15)
# — así que se verifica aquí también, como la unidad canónica que el
# blueprint señala, además de la que hoy corre de verdad en
# `_pass_group` (`_subset_sums_exact`, probada arriba).
from b2b_ai.services.subset_sum import find_subset_sums, to_cents


def _inv(folio, total):
    return {
        "folio_fiscal": folio,
        "fecha": "2026-08-01",
        "total": total,
        "emisor_nombre": "Cliente de prueba",
    }


def _tx_abono(tx_id_seed, fecha, monto, descripcion="", ref=""):
    """Movimiento bancario normalizado (mismo shape que produce
    `_normalize_transaction`) representando un abono (depósito)."""
    return {
        "id": f"tx_{tx_id_seed}",
        "fecha": fecha,
        "monto": str(monto),
        "monto_signed": str(monto),
        "naturaleza": "abono",
        "descripcion": descripcion,
        "ref": ref,
        "banco": "generico",
    }


# ---------------------------------------------------------------------------
# REQ-CONC-005 — unidad: `_subset_sums_exact`
# ---------------------------------------------------------------------------

class TestSubsetSumsExcluyeTamano1YLimitaTecho:
    """REQ-CONC-005: excluir tamaño 1, limitar tamaño máximo a un techo
    configurable (default 15)."""

    def test_20_facturas_candidatas_ningun_subconjunto_excede_15_ni_es_1(self):
        target = Decimal("5000.00")
        target_cents = _to_cents(target)

        # Tentación de tamaño 1: esta factura SOLA ya cuadra con el
        # depósito. `_pass_exact` (1-a-1) ya la cubre — el subset-sum
        # NUNCA debe proponerla como "grupo" de tamaño 1.
        solo = _inv("SOLO-5000", "5000.00")

        # Grupo válido de 3 facturas (tamaño permitido, dentro del techo).
        grupo_3 = [
            _inv("G3-A", "1234.56"),
            _inv("G3-B", "2345.67"),
            _inv("G3-C", "1419.77"),
        ]
        assert sum(Decimal(i["total"]) for i in grupo_3) == target

        # Tentación de tamaño 16: matemáticamente válida (16 x 312.50 =
        # 5000.00) pero excede el techo configurable (default 15) — con
        # la configuración default nunca debe proponerse.
        grupo_16 = [_inv(f"G16-{i}", "312.50") for i in range(16)]
        assert sum(Decimal(i["total"]) for i in grupo_16) == target

        candidatos = [solo] + grupo_3 + grupo_16
        assert len(candidatos) == 20  # "20 facturas candidatas en la ventana"

        resultados = _subset_sums_exact(candidatos, target_cents)

        # Ningún subconjunto propuesto viola los límites de tamaño.
        for grupo in resultados:
            assert len(grupo) != 1, f"subconjunto de tamaño 1 propuesto: {grupo}"
            assert len(grupo) <= 15, f"subconjunto excede el techo de 15: {grupo}"

        # El algoritmo sí funciona de verdad: el grupo de 3 se encuentra.
        folios_g3 = {i["folio_fiscal"] for i in grupo_3}
        assert any({i["folio_fiscal"] for i in g} == folios_g3 for g in resultados)

        # El grupo de 16 NUNCA aparece completo (excede el techo default).
        folios_g16 = {i["folio_fiscal"] for i in grupo_16}
        assert not any({i["folio_fiscal"] for i in g} == folios_g16
                       for g in resultados)

        # La factura sola nunca aparece como subconjunto de tamaño 1.
        assert not any(len(g) == 1 and g[0]["folio_fiscal"] == "SOLO-5000"
                       for g in resultados)

    def test_techo_es_configurable_subir_a_16_si_revela_el_grupo_de_16(self):
        """Prueba de control: si el techo default ocultara el grupo de 16
        porque el algoritmo está roto (y no porque respeta el límite),
        subir `max_size` a 16 debería revelarlo — confirma que es el
        techo, y no un bug, lo que lo excluye por default."""
        target = Decimal("5000.00")
        grupo_16 = [_inv(f"G16-{i}", "312.50") for i in range(16)]

        resultados = _subset_sums_exact(grupo_16, _to_cents(target), max_size=16)

        folios_g16 = {i["folio_fiscal"] for i in grupo_16}
        assert any({i["folio_fiscal"] for i in g} == folios_g16 for g in resultados)

    def test_min_size_nunca_baja_de_2_aunque_se_pida_explicitamente(self):
        """El criterio excluye tamaño 1 de forma absoluta (no es un
        parámetro configurable como el techo máximo). Pedir
        `min_size=1` explícitamente no debe colar subconjuntos de
        tamaño 1."""
        target = Decimal("100.00")
        candidatos = [_inv("A", "100.00"), _inv("B", "40.00"), _inv("C", "60.00")]

        resultados = _subset_sums_exact(candidatos, _to_cents(target), min_size=1)

        assert all(len(g) != 1 for g in resultados)
        # El grupo B+C (100.00) sí debe encontrarse.
        assert any({i["folio_fiscal"] for i in g} == {"B", "C"} for g in resultados)

    def test_techo_configurable_a_un_valor_mas_bajo_tambien_se_respeta(self):
        """El techo es configurable en ambas direcciones: bajarlo a 2
        debe excluir el grupo de 3 (tamaño 3 > techo 2)."""
        target = Decimal("5000.00")
        grupo_3 = [
            _inv("G3-A", "1234.56"),
            _inv("G3-B", "2345.67"),
            _inv("G3-C", "1419.77"),
        ]
        resultados = _subset_sums_exact(grupo_3, _to_cents(target), max_size=2)
        assert resultados == []


# ---------------------------------------------------------------------------
# REQ-CONC-005 — unidad canónica del blueprint: `find_subset_sums` en
# `b2b_ai/services/subset_sum.py`.
# ---------------------------------------------------------------------------

class TestFindSubsetSumsModuloCanonicoExcluyeTamano1YLimitaTecho:
    """Mismo criterio de REQ-CONC-005, verificado contra la función que el
    blueprint señala explícitamente como código previsto para este
    requisito (`find_subset_sums`), independiente de que hoy `_pass_group`
    todavía use la implementación inline de `bank_reconciliation.py`."""

    def test_20_facturas_candidatas_ningun_subconjunto_excede_15_ni_es_1(self):
        target_cents = to_cents("5000.00")

        solo = ("SOLO-5000", to_cents("5000.00"))
        grupo_3 = [
            ("G3-A", to_cents("1234.56")),
            ("G3-B", to_cents("2345.67")),
            ("G3-C", to_cents("1419.77")),
        ]
        grupo_16 = [(f"G16-{i}", to_cents("312.50")) for i in range(16)]

        items = [solo] + grupo_3 + grupo_16
        assert len(items) == 20

        resultados = find_subset_sums(items, target_cents)

        for grupo in resultados:
            assert len(grupo) != 1, f"subconjunto de tamaño 1 propuesto: {grupo}"
            assert len(grupo) <= 15, f"subconjunto excede el techo de 15: {grupo}"

        ids_g3 = {payload for payload, _ in grupo_3}
        assert any(set(g) == ids_g3 for g in resultados)

        ids_g16 = {payload for payload, _ in grupo_16}
        assert not any(set(g) == ids_g16 for g in resultados)
        assert not any(g == ["SOLO-5000"] for g in resultados)

    def test_techo_configurable_subir_a_16_revela_el_grupo_de_16(self):
        target_cents = to_cents("5000.00")
        grupo_16 = [(f"G16-{i}", to_cents("312.50")) for i in range(16)]

        resultados = find_subset_sums(grupo_16, target_cents, max_size=16)

        ids_g16 = {payload for payload, _ in grupo_16}
        assert any(set(g) == ids_g16 for g in resultados)

    def test_min_size_nunca_baja_de_2_aunque_se_pida_explicitamente(self):
        target_cents = to_cents("100.00")
        candidatos = [("A", to_cents("100.00")), ("B", to_cents("40.00")),
                      ("C", to_cents("60.00"))]

        resultados = find_subset_sums(candidatos, target_cents, min_size=1)

        assert all(len(g) != 1 for g in resultados)
        assert any(set(g) == {"B", "C"} for g in resultados)

    def test_techo_configurable_a_un_valor_mas_bajo_tambien_se_respeta(self):
        grupo_3 = [
            ("G3-A", to_cents("1234.56")),
            ("G3-B", to_cents("2345.67")),
            ("G3-C", to_cents("1419.77")),
        ]
        resultados = find_subset_sums(grupo_3, to_cents("5000.00"), max_size=2)
        assert resultados == []


# ---------------------------------------------------------------------------
# Regla dura del blueprint pedida para este lote: nunca inventar un match;
# ambigüedad real (2+ combinaciones cuadran) -> decisión humana explícita.
# Se ejercita a nivel de integración real (BankReconciliation.auto_match),
# sin mocks, sobre el pase `_pass_group` ya presente en el código.
# ---------------------------------------------------------------------------

class TestReglaDuraNuncaInventarUnMatch:
    def test_3_facturas_reales_suman_un_deposito_se_concilian_agrupadas(self):
        """Caso real de subset-sum con 3+ facturas: deben conciliarse
        agrupadas contra el único depósito que las explica."""
        recon = BankReconciliation(tenant_id="t1")
        invoices = [
            _inv("F-100", "3556.00"),
            _inv("F-101", "6796.00"),
            _inv("F-102", "9840.00"),
        ]
        recon.load_invoices(invoices)
        recon.transactions = [
            _tx_abono("dep1", "2026-08-05", "20192.00",
                      descripcion="LIQUIDACION TERMINAL"),
        ]

        resultado = recon.auto_match()

        grouped = [m for m in resultado["matches"] if m["method"] == "grouped_n_a_1"]
        assert len(grouped) == 3
        assert len({m["transaction_id"] for m in grouped}) == 1
        assert len({m["group_id"] for m in grouped}) == 1
        assert {m["invoice_ref"] for m in grouped} == {"F-100", "F-101", "F-102"}
        assert recon.grouped_ambiguous == []

    def test_deposito_sin_combinacion_valida_nunca_inventa_match(self):
        """Ninguna combinación de las facturas cargadas suma el depósito:
        el sistema debe dejarlo sin conciliar, nunca inventar el
        candidato "más parecido"."""
        recon = BankReconciliation(tenant_id="t1")
        invoices = [
            _inv("F-200", "1000.00"),
            _inv("F-201", "2000.00"),
            _inv("F-202", "3000.00"),
        ]
        recon.load_invoices(invoices)
        recon.transactions = [
            _tx_abono("dep2", "2026-08-05", "12345.67"),
        ]

        recon.auto_match()
        reporte = recon.generate_reconciliation_report()

        assert reporte["conciliados"] == 0
        assert [t["id"] for t in reporte["unmatched_bank"]] == ["tx_dep2"]
        assert recon.grouped_ambiguous == []

    def test_ambiguedad_real_2_combinaciones_validas_nunca_se_auto_resuelve(self):
        """2 combinaciones distintas de facturas suman EXACTAMENTE el
        mismo depósito (ADR-2 del blueprint): nunca se elige una
        arbitrariamente. Debe quedar marcado para decisión humana y el
        depósito debe permanecer sin conciliar."""
        recon = BankReconciliation(tenant_id="t1")
        invoices = [
            _inv("A1", "1000.00"), _inv("A2", "2000.00"),  # combinación A: 3000.00
            _inv("B1", "1500.00"), _inv("B2", "1500.00"),  # combinación B: 3000.00
        ]
        recon.load_invoices(invoices)
        recon.transactions = [
            _tx_abono("dep3", "2026-08-05", "3000.00"),
        ]

        resultado = recon.auto_match()

        grouped = [m for m in resultado["matches"] if m["method"] == "grouped_n_a_1"]
        assert grouped == [], "no debe auto-aplicar ninguna combinación ambigua"

        assert len(recon.grouped_ambiguous) == 1
        caso = recon.grouped_ambiguous[0]
        assert caso["transaction_id"] == "tx_dep3"
        candidatos_folios = {frozenset(c) for c in caso["candidatos"]}
        assert frozenset({"A1", "A2"}) in candidatos_folios
        assert frozenset({"B1", "B2"}) in candidatos_folios
        assert len(candidatos_folios) == 2

        # El depósito ambiguo sigue sin conciliar — ningún otro pase
        # (parcial/AI) debe haberlo "resuelto" por su cuenta.
        reporte = recon.generate_reconciliation_report()
        assert "tx_dep3" in {t["id"] for t in reporte["unmatched_bank"]}
