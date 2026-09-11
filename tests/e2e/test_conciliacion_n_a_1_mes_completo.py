# -*- coding: utf-8 -*-
"""
REQ-CONC-018 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-CONC —
Conciliación bancaria N-a-1). Dataset sintético, sin ninguna credencial
real de Clip/Banorte ni de ningún proveedor de pagos.

Criterio de aceptación exacto:
  "Debe existir un test end-to-end con datos sintéticos de un mes completo
  de liquidaciones Clip (>=30 depósitos agrupados, >=150 facturas
  candidatas, incluyendo al menos 3 casos de ambigüedad real de 2
  subconjuntos válidos) que corra el pipeline completo
  (`match_transactions` con `_pass_group` activo) y confirme: 0 facturas
  contadas dos veces, 100% de los casos ambiguos en `estado="sugerido"`,
  y el resto por encima del umbral en `confidence="alta"`."

Construcción del dataset (determinista, sin `random`):
  - 35 depósitos "limpios", cada uno en su PROPIA terminal Clip exclusiva
    (`id_terminal` único, REQ-CONC-015/016: canal_cobro="terminal") con un
    grupo de 2-6 facturas cuyos montos son una secuencia
    SUPERINCREASING (cada monto > la suma de todos los anteriores del
    mismo grupo) -- propiedad clásica de subset-sum que garantiza
    matemáticamente que el ÚNICO subconjunto de ese grupo cuya suma
    iguala el depósito es el conjunto COMPLETO (cualquier subconjunto
    propio suma estrictamente menos que el monto del elemento más grande
    que le falta). Como además cada depósito vive en su propia terminal
    exclusiva, `_filtrar_por_canal` (REQ-CONC-015) aísla su pool de
    facturas del resto -- cero interferencia entre depósitos.
  - 3 depósitos AMBIGUOS, cada uno en su propia terminal exclusiva, con
    exactamente 4 facturas construidas como DOS PARES disjuntos que
    cuadran la misma suma (p. ej. $1,000+$3,000 == $1,500+$2,500 ==
    $4,000). Verificado exhaustivamente en este archivo (fuerza bruta
    sobre las 11 combinaciones de tamaño >=2 de 4 elementos) que
    ÚNICAMENTE esos 2 pares llegan a la suma exacta -- ninguna otra
    combinación de esas 4 facturas coincide por accidente.

Total: 38 depósitos (>=30), >=150 facturas candidatas (verificado con un
assert explícito sobre el propio dataset generado, nunca un número
supuesto), 3 casos de ambigüedad real de 2 subconjuntos.

Datos 100% sintéticos y deterministas (sin `random`, sin red): ninguna
credencial real de Clip ni de ningún proveedor de pagos.
"""
from __future__ import annotations

from itertools import combinations

import pytest

from b2b_ai.services.bank_reconciliation import BankReconciliation

pytestmark = pytest.mark.e2e

FECHA_BASE = "2026-07"   # mes completo de liquidaciones


def _fecha(dia: int) -> str:
    dia = 1 + (dia % 28)   # todos los días válidos en cualquier mes
    return f"{FECHA_BASE}-{dia:02d}"


def _inv(folio, total_cents, fecha, terminal, emisor="Cliente Clip"):
    return {
        "folio_fiscal": folio,
        "fecha": fecha,
        "total": str(total_cents / 100),
        "emisor": emisor,
        "emisor_nombre": emisor,
        "canal_cobro": "terminal",
        "id_terminal": terminal,
    }


def _tx(id_, total_cents, fecha, terminal):
    monto = str(total_cents / 100)
    return {
        "id": id_,
        "fecha": fecha,
        "monto": monto,
        "monto_signed": monto,
        "naturaleza": "abono",
        "descripcion": f"LIQUIDACION CLIP {terminal}",
        "ref": terminal,
        "banco": "clip",
        "canal_cobro": "terminal",
        "id_terminal": terminal,
    }


def _grupo_superincreasing(n: int, folio_prefix: str, terminal: str,
                           dia: int, step_base_cents: int):
    """`n` facturas cuyos montos (centavos enteros) forman una secuencia
    superincreasing: cada monto > suma de todos los anteriores del mismo
    grupo. Propiedad: el ÚNICO subconjunto (tamaño >= 1) de este grupo
    cuya suma iguala la suma TOTAL del grupo es el grupo completo --
    cualquier subconjunto que excluya el elemento más grande suma, como
    máximo, la suma de "todos los demás" (que por construcción es MENOR
    que ese elemento más grande), así que nunca alcanza el total sin
    incluirlo; el mismo argumento aplica recursivamente hacia abajo.
    """
    montos = []
    running = 0
    for k in range(n):
        step = step_base_cents + k * 97 + 401   # siempre > 0
        monto = running + step
        montos.append(monto)
        running += monto
    invoices = [
        _inv(f"{folio_prefix}-{k+1}", montos[k], _fecha(dia), terminal)
        for k in range(n)
    ]
    return invoices, running   # running == suma total == monto del depósito


def _construir_dataset():
    deposits = []
    invoices = []

    # -- 35 depósitos "limpios": único subconjunto válido por diseño ------
    tamanos = [2, 3, 4, 5, 6]   # ciclo de tamaños pequeños (score alto)
    for i in range(35):
        n = tamanos[i % len(tamanos)]
        terminal = f"CLIP-TERM-LIMPIO-{i:03d}"
        dia = i
        grupo, total_cents = _grupo_superincreasing(
            n, f"INV-L{i:03d}", terminal, dia,
            step_base_cents=50_00 + i * 13)
        invoices.extend(grupo)
        deposits.append(_tx(f"tx_limpio_{i:03d}", total_cents,
                            _fecha(dia), terminal))

    # -- 3 depósitos AMBIGUOS: 2 pares disjuntos que cuadran la misma suma
    for j in range(3):
        escala = j + 1   # 1x, 2x, 3x -- montos distintos por depósito
        a, b = 1000_00 * escala, 3000_00 * escala   # par 1: suma 4000*escala
        c, d = 1500_00 * escala, 2500_00 * escala   # par 2: misma suma
        terminal = f"CLIP-TERM-AMBIGUO-{j:03d}"
        dia = 35 + j
        fecha = _fecha(dia)
        grupo = [
            _inv(f"INV-A{j}-1", a, fecha, terminal),
            _inv(f"INV-A{j}-2", b, fecha, terminal),
            _inv(f"INV-A{j}-3", c, fecha, terminal),
            _inv(f"INV-A{j}-4", d, fecha, terminal),
        ]
        # Verificación exhaustiva (fuerza bruta, nunca supuesta): de las 11
        # combinaciones de tamaño >=2 posibles entre estas 4 facturas,
        # EXACTAMENTE 2 (el par 1 y el par 2) suman el target -- ninguna
        # otra coincide por accidente.
        target = a + b
        assert c + d == target
        montos = [a, b, c, d]
        validas = [
            combo for r in range(2, 5)
            for combo in combinations(range(4), r)
            if sum(montos[k] for k in combo) == target
        ]
        assert len(validas) == 2, (
            f"dataset mal construido: se esperaban exactamente 2 "
            f"subconjuntos válidos, se encontraron {len(validas)}")
        invoices.extend(grupo)
        deposits.append(_tx(f"tx_ambiguo_{j:03d}", target, fecha, terminal))

    return invoices, deposits


def test_dataset_cumple_el_piso_del_criterio():
    """Sanity check del propio generador -- nunca un número supuesto."""
    invoices, deposits = _construir_dataset()
    assert len(deposits) >= 30, f"solo {len(deposits)} depósitos"
    assert len(invoices) >= 150, f"solo {len(invoices)} facturas"
    assert len(deposits) == 38   # 35 limpios + 3 ambiguos
    # 35 limpios: tamaños [2,3,4,5,6] x 7 ciclos completos = 140 facturas.
    # 3 ambiguos: 4 facturas cada uno = 12 facturas. Total 152.
    assert len(invoices) == 152
    refs = [i["folio_fiscal"] for i in invoices]
    assert len(refs) == len(set(refs)), "folios de factura duplicados"


def test_pipeline_completo_mes_de_liquidaciones_clip():
    invoices, deposits = _construir_dataset()
    assert len(deposits) >= 30
    assert len(invoices) >= 150

    svc = BankReconciliation()
    matches = svc.match_transactions(invoices, deposits)

    # ------------------------------------------------------------------
    # 1) 0 facturas contadas dos veces: ningún folio de factura aparece
    #    conciliado contra más de un movimiento/transacción.
    # ------------------------------------------------------------------
    refs = [m["invoice_ref"] for m in matches]
    assert len(refs) == len(set(refs)), (
        "hay facturas contadas dos veces entre distintos matches")

    # ------------------------------------------------------------------
    # 2) 100% de los 3 casos ambiguos quedan en estado="sugerido", NUNCA
    #    generan una fila de match (ADR-2) -- ninguna de sus 4 facturas
    #    aparece conciliada.
    # ------------------------------------------------------------------
    tx_ambiguos = {f"tx_ambiguo_{j:03d}" for j in range(3)}
    tx_con_match = {m["transaction_id"] for m in matches}
    assert tx_ambiguos.isdisjoint(tx_con_match), (
        "un depósito ambiguo generó un match -- nunca debe auto-aplicarse "
        "(ADR-2)")

    sugeridos_ambiguos = [
        s for s in svc.grouped_suggestions
        if s["transaction_id"] in tx_ambiguos
    ]
    assert len(sugeridos_ambiguos) == len(tx_ambiguos), (
        f"se esperaban los 3 depósitos ambiguos en grouped_suggestions, "
        f"aparecieron {len(sugeridos_ambiguos)}")
    assert all(s["estado"] == "sugerido" for s in sugeridos_ambiguos)
    assert all(s["requiere_confirmacion_humana"] is True
              for s in sugeridos_ambiguos)

    # También deben aparecer en grouped_ambiguous (2+ combinaciones
    # reales, REQ-CONC-007) con exactamente 2 candidatos cada uno.
    ambiguos_detalle = {a["transaction_id"]: a
                        for a in svc.grouped_ambiguous}
    assert set(ambiguos_detalle.keys()) == tx_ambiguos
    for tx_id, detalle in ambiguos_detalle.items():
        assert len(detalle["candidatos"]) == 2, (
            f"{tx_id} debía tener exactamente 2 combinaciones válidas, "
            f"tiene {len(detalle['candidatos'])}")

    # Ninguna de las 12 facturas de los depósitos ambiguos quedó
    # conciliada (siguen libres para revisión humana).
    refs_ambiguos = {f"INV-A{j}-{k}" for j in range(3) for k in (1, 2, 3, 4)}
    assert refs_ambiguos.isdisjoint(set(refs))

    # ------------------------------------------------------------------
    # 3) El resto (35 depósitos "limpios") queda por encima del umbral,
    #    confidence="alta", auto-confirmado -- ninguno se queda sin
    #    conciliar ni sugerido.
    # ------------------------------------------------------------------
    tx_limpios = {f"tx_limpio_{i:03d}" for i in range(35)}
    assert tx_limpios.issubset(tx_con_match), (
        f"faltan depósitos limpios sin conciliar: "
        f"{tx_limpios - tx_con_match}")

    matches_por_tx = {}
    for m in matches:
        matches_por_tx.setdefault(m["transaction_id"], []).append(m)

    for tx_id in tx_limpios:
        filas = matches_por_tx[tx_id]
        assert all(f["confidence"] == "alta" for f in filas), (
            f"{tx_id} tiene filas sin confidence='alta': {filas}")
        assert all(f["method"] == "grouped_n_a_1" for f in filas)
        assert all(f["estado"] == "confirmado" for f in filas)
        assert all(f["score"] >= BankReconciliation.UMBRAL_AUTO_CONFIRMA_GRUPO
                  for f in filas)
        # Todas las filas de un mismo grupo comparten group_id.
        group_ids = {f["group_id"] for f in filas}
        assert len(group_ids) == 1

    # Ningún depósito limpio aparece en sin_conciliar ni en sugeridos.
    assert tx_limpios.isdisjoint(
        {s["transaction_id"] for s in svc.sin_conciliar})
    assert tx_limpios.isdisjoint(
        {s["transaction_id"] for s in svc.grouped_suggestions})

    # ------------------------------------------------------------------
    # 4) Cobertura total: cada factura de un depósito limpio aparece en
    #    matches exactamente una vez, ninguna falta y ninguna sobra.
    # ------------------------------------------------------------------
    refs_limpios_esperados = {
        i["folio_fiscal"] for i in invoices
        if i["id_terminal"].startswith("CLIP-TERM-LIMPIO-")
    }
    refs_limpios_en_matches = {
        m["invoice_ref"] for m in matches
        if m["transaction_id"] in tx_limpios
    }
    assert refs_limpios_en_matches == refs_limpios_esperados


def test_reporte_no_duplica_monto_de_depositos_agrupados():
    """REQ-CONC-011 aplicado a escala: el monto conciliado del reporte no
    debe contar un mismo depósito varias veces por tener N filas de match
    (una por factura del grupo)."""
    invoices, deposits = _construir_dataset()
    svc = BankReconciliation()
    svc.load_invoices(invoices)
    svc.transactions = deposits
    svc.matches = svc.match_transactions(invoices, deposits)

    reporte = svc.generate_reconciliation_report()

    tx_limpios = {f"tx_limpio_{i:03d}" for i in range(35)}
    monto_esperado = sum(_dec_local(t["monto"]) for t in deposits
                         if t["id"] in tx_limpios)
    assert _dec_local(reporte["monto_conciliado"]) == monto_esperado
    assert reporte["conciliados"] == 35
    # 3 depósitos ambiguos + 0 sin_conciliar entre los limpios (todos
    # matchean) -> pendientes_banco == 3.
    assert reporte["pendientes_banco"] == 3


def _dec_local(v):
    from decimal import Decimal
    return Decimal(str(v))
