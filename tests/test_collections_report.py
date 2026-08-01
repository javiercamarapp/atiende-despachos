# -*- coding: utf-8 -*-
"""Tests FASE 3 — Reportes de cobranza: aging, proyección y resumen."""
import datetime as dt

from b2b_ai.services.collections_report import (aging_report, projection,
                                                summary)


TODAY = dt.date(2026, 7, 31)


def _d(days_from_today):
    return TODAY + dt.timedelta(days=days_from_today)


# Cartera: 1 factura por bucket de antigüedad, con score ya calculado.
INVOICES = [
    {"factura_id": "F1", "nombre_empresa": "A", "monto": "1000",
     "fecha_vencimiento": _d(-10).isoformat(), "score": 0.75},   # 0-30
    {"factura_id": "F2", "nombre_empresa": "B", "monto": "2000",
     "fecha_vencimiento": _d(-40).isoformat(), "score": 0.55},   # 31-60
    {"factura_id": "F3", "nombre_empresa": "C", "monto": "3000",
     "fecha_vencimiento": _d(-75).isoformat(), "score": 0.38},   # 61-90
    {"factura_id": "F4", "nombre_empresa": "D", "monto": "4000",
     "fecha_vencimiento": _d(-120).isoformat(), "score": 0.22},  # 90+
]


# --------------------------------------------------------------------------- #
# aging_report
# --------------------------------------------------------------------------- #
def test_aging_report_agrupa_por_bucket():
    rep = aging_report(INVOICES, today=TODAY)
    assert rep["total_count"] == 4
    assert rep["buckets"]["0-30"]["count"] == 1
    assert rep["buckets"]["31-60"]["count"] == 1
    assert rep["buckets"]["61-90"]["count"] == 1
    assert rep["buckets"]["90+"]["count"] == 1
    assert rep["buckets"]["0-30"]["monto"] == "1000"
    assert rep["total_monto"] == "10000"


def test_aging_report_recalcula_dias_si_no_vienen():
    # Sin score/días precalculados, los recalcula desde la fecha de vencimiento.
    rep = aging_report([{"factura_id": "F1", "monto": "500",
                         "fecha_vencimiento": _d(-20).isoformat()}], today=TODAY)
    inv = rep["invoices"][0]
    assert inv["dias_vencido"] == 20
    assert inv["bucket"] == "0-30"
    assert inv["score"] == 0.0


def test_aging_report_vacio():
    rep = aging_report([], today=TODAY)
    assert rep["total_count"] == 0
    assert rep["total_monto"] == "0"
    assert rep["buckets"]["90+"]["count"] == 0


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def test_projection_esperado_por_score():
    proj = projection(INVOICES, today=TODAY)
    # total esperado = 1000*0.75 + 2000*0.55 + 3000*0.38 + 4000*0.22
    #                = 750 + 1100 + 1140 + 880 = 3870
    assert proj["total_cartera"] == "10000"
    assert proj["total_esperado"] == "3870.00"
    assert proj["tasa_recuperacion_esperada"] == 38.7
    # Por bucket: solo 90+ tiene monto 4000, esperado 880.
    assert proj["por_bucket"]["90+"]["monto_total"] == "4000"
    assert proj["por_bucket"]["90+"]["esperado"] == "880.00"


def test_projection_por_rango_de_score():
    proj = projection(INVOICES, today=TODAY)
    # F1 (0.75) alta; F2 (0.55) media; F3 (0.38) y F4 (0.22) baja.
    assert proj["por_score"]["alta"]["count"] == 1
    assert proj["por_score"]["media"]["count"] == 1
    assert proj["por_score"]["baja"]["count"] == 2
    # F3 (0.38) y F4 (0.22) en baja: 3000*0.38 + 4000*0.22 = 1140 + 880 = 2020
    assert proj["por_score"]["baja"]["esperado"] == "2020.00"


def test_projection_cartera_vacia():
    proj = projection([], today=TODAY)
    assert proj["total_esperado"] == "0"
    assert proj["tasa_recuperacion_esperada"] == 0.0


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def test_summary_resumen_ejecutivo():
    s = summary(INVOICES, today=TODAY)
    assert s["total_count"] == 4
    assert s["total_cartera"] == "10000"
    assert s["total_esperado"] == "3870.00"
    # 90+ = 40% de la cartera.
    assert s["por_antiguedad"]["90+"]["porcentaje"] == 40.0
    assert s["por_antiguedad"]["90+"]["count"] == 1


def test_summary_alertas_por_cartera_riesgosa():
    s = summary(INVOICES, today=TODAY)
    assert any("90 días" in a for a in s["alertas"])
    assert any("score de cobrabilidad bajo" in a for a in s["alertas"])


def test_summary_top_montos_ordenados():
    s = summary(INVOICES, today=TODAY)
    montos = [float(m["monto"]) for m in s["top_montos"]]
    assert montos == sorted(montos, reverse=True)
    assert montos[0] == 4000.0  # F4 es la más alta


def test_summary_sin_alertas_si_todo_sano():
    sanas = [
        {"factura_id": "S1", "monto": "500",
         "fecha_vencimiento": _d(-5).isoformat(), "score": 0.9},
    ]
    s = summary(sanas, today=TODAY)
    assert s["alertas"] == []
