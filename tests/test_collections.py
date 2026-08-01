# -*- coding: utf-8 -*-
"""Tests FASE 3 — Agente de cobranza: clasificación, templates, score."""
import datetime as dt

import pytest

from b2b_ai.services.collections import (CollectionsManager, age_bucket,
                                         reminder_stage, days_overdue)
from b2b_ai.services.collections_templates import (render, render_subject,
                                                   format_monto, TEMPLATES,
                                                   SEQUENCE)


TODAY = dt.date(2026, 7, 31)


def _d(days_from_today):
    return TODAY + dt.timedelta(days=days_from_today)


# --------------------------------------------------------------------------- #
# Clasificación por antigüedad
# --------------------------------------------------------------------------- #
def test_age_bucket_los_cuatro_rangos():
    assert age_bucket(0) == "0-30"
    assert age_bucket(15) == "0-30"
    assert age_bucket(30) == "0-30"
    assert age_bucket(31) == "31-60"
    assert age_bucket(60) == "31-60"
    assert age_bucket(61) == "61-90"
    assert age_bucket(90) == "61-90"
    assert age_bucket(91) == "90+"
    assert age_bucket(200) == "90+"


def test_age_bucket_no_vencido_y_raro():
    # Negativo (aún no vence) y valores inválidos caen en 0-30.
    assert age_bucket(-5) == "0-30"
    assert age_bucket("N/A") == "0-30"
    assert age_bucket(None) == "0-30"


def test_days_overdue_negativo_antes_de_vencer():
    due = _d(5)  # vence en 5 días
    assert days_overdue(due, TODAY) == -5


# --------------------------------------------------------------------------- #
# Secuencia de recordatorios
# --------------------------------------------------------------------------- #
def test_reminder_stage_cada_etapa():
    assert reminder_stage(_d(7), TODAY) == "pre_vencimiento"      # 7 días antes
    assert reminder_stage(_d(0), TODAY) == "vencimiento"          # día 0
    assert reminder_stage(_d(-7), TODAY) == "recordatorio_formal"  # +7 vencido
    assert reminder_stage(_d(-30), TODAY) == "segundo_recordatorio"
    assert reminder_stage(_d(-60), TODAY) == "escalamiento"


def test_reminder_stage_fuera_de_gatillo():
    # En fechas que no coinciden con ningún offset no toca enviar.
    assert reminder_stage(_d(-8), TODAY) is None
    assert reminder_stage(_d(6), TODAY) is None


def test_secuencia_tiene_las_cinco_etapas():
    assert SEQUENCE == ["pre_vencimiento", "vencimiento",
                        "recordatorio_formal", "segundo_recordatorio",
                        "escalamiento"]


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def test_templates_existen_para_todas_las_etapas():
    assert set(TEMPLATES) == set(SEQUENCE)
    for stage in SEQUENCE:
        assert "email" in TEMPLATES[stage]
        assert "whatsapp" in TEMPLATES[stage]


def test_render_email_sustituye_variables():
    body = render("recordatorio_formal", "email",
                  nombre_empresa="Papelería El Águila", monto="$12,500.00 MXN",
                  dias_vencido="7", factura_id="FAC-1001")
    assert "Papelería El Águila" in body
    assert "$12,500.00 MXN" in body
    assert "7" in body
    assert "FAC-1001" in body


def test_render_email_tiene_asunto():
    subject = render_subject("recordatorio_formal",
                             factura_id="FAC-1001", dias_vencido="7")
    assert "FAC-1001" in subject
    assert "vencida" in subject.lower()


def test_render_whatsapp():
    text = render("escalamiento", "whatsapp",
                  nombre_empresa="Comercial MX", monto="$9,000.00 MXN",
                  dias_vencido="60", factura_id="FAC-9")
    assert "Comercial MX" in text
    assert "escalado a gerencia" in text.lower()


def test_render_etapa_desconocida_y_canal_invalido():
    with pytest.raises(KeyError):
        render("no_existe", "email")
    with pytest.raises(ValueError):
        render("vencimiento", "sms")


def test_format_monto_mexicano():
    assert format_monto("12500") == "$12,500.00 MXN"
    assert format_monto(1000.5) == "$1,000.50 MXN"


# --------------------------------------------------------------------------- #
# CollectionsManager — analyze
# --------------------------------------------------------------------------- #
INVOICES = [
    {"factura_id": "F1", "nombre_empresa": "A", "monto": "1000",
     "fecha_vencimiento": _d(-10).isoformat()},   # 10 días vencido -> 0-30
    {"factura_id": "F2", "nombre_empresa": "B", "monto": "2000",
     "fecha_vencimiento": _d(-40).isoformat()},   # 40 días -> 31-60
    {"factura_id": "F3", "nombre_empresa": "C", "monto": "3000",
     "fecha_vencimiento": _d(-75).isoformat()},   # 75 días -> 61-90
    {"factura_id": "F4", "nombre_empresa": "D", "monto": "4000",
     "fecha_vencimiento": _d(-120).isoformat()},  # 120 días -> 90+
]


def test_analyze_clasifica_buckets():
    mgr = CollectionsManager()
    res = mgr.analyze(INVOICES, today=TODAY)
    assert res["total_invoices"] == 4
    assert res["buckets"]["0-30"]["count"] == 1
    assert res["buckets"]["31-60"]["count"] == 1
    assert res["buckets"]["61-90"]["count"] == 1
    assert res["buckets"]["90+"]["count"] == 1
    assert res["buckets"]["90+"]["monto"] == "4000"
    # Cada factura enriquecida
    f4 = next(i for i in res["invoices"] if i["factura_id"] == "F4")
    assert f4["dias_vencido"] == 120
    assert f4["bucket"] == "90+"
    assert 0.0 <= f4["score"] <= 1.0


def test_score_baja_con_antiguedad():
    mgr = CollectionsManager()
    # Sin historial, el score se deriva solo de la antigüedad.
    s_reciente = mgr.collectability_score({"factura_id": "F1"},
                                          dias_vencido=5)
    s_vieja = mgr.collectability_score({"factura_id": "F4"},
                                       dias_vencido=200)
    assert s_reciente > s_vieja
    assert s_reciente == 0.75
    assert s_vieja == 0.22


def test_score_pagado_devuelve_uno():
    mgr = CollectionsManager()
    history = [{"respuesta": "pagado", "tipo_recordatorio": "vencimiento"}]
    assert mgr.collectability_score({}, dias_vencido=200,
                                    history=history) == 1.0


def test_score_promesa_de_pago_mejora():
    mgr = CollectionsManager()
    base = mgr.collectability_score({}, dias_vencido=40)
    con_promesa = mgr.collectability_score(
        {}, dias_vencido=40,
        history=[{"respuesta": "promesa_pago", "tipo_recordatorio": "formal"}])
    assert con_promesa > base


# --------------------------------------------------------------------------- #
# Generación de recordatorios + registro
# --------------------------------------------------------------------------- #
def test_build_reminder_email_personaliza():
    mgr = CollectionsManager()
    msg = mgr.build_reminder(
        {"factura_id": "F2", "nombre_empresa": "Comercial MX", "monto": "2000",
         "fecha_vencimiento": _d(-40).isoformat()},
        stage="segundo_recordatorio", channel="email", today=TODAY)
    assert msg["stage"] == "segundo_recordatorio"
    assert "Comercial MX" in msg["body"]
    assert "40" in msg["body"]  # dias_vencido
    assert "F2" in msg["subject"]


def test_build_reminder_whatsapp():
    mgr = CollectionsManager()
    msg = mgr.build_reminder(
        {"factura_id": "F2", "nombre_empresa": "Comercial MX", "monto": "2000",
         "fecha_vencimiento": _d(-40).isoformat()},
        stage="segundo_recordatorio", channel="whatsapp", today=TODAY)
    assert "whatsapp" in msg
    assert "40 días" in msg["whatsapp"]


def test_send_reminder_registra_evento_con_db(tmp_db):
    mgr = CollectionsManager(db=tmp_db, tenant_id=1)
    msg = mgr.send_reminder(
        {"factura_id": "F2", "nombre_empresa": "X", "monto": "2000",
         "fecha_vencimiento": _d(-40).isoformat()},
        stage="segundo_recordatorio", channel="email", today=TODAY)
    assert msg["sent"] is False
    assert "event_id" in msg  # se registró en collection_events
    events = tmp_db.list_collection_events(factura_id="F2")
    assert len(events) == 1
    assert events[0]["tipo_recordatorio"] == "segundo_recordatorio"
    assert events[0]["canal"] == "email"


def test_register_response(tmp_db):
    mgr = CollectionsManager(db=tmp_db, tenant_id=1)
    mgr.register_response("F9", "pagado", channel="whatsapp",
                          tipo_recordatorio="vencimiento")
    events = tmp_db.list_collection_events(factura_id="F9")
    assert events[0]["respuesta"] == "pagado"


# --------------------------------------------------------------------------- #
# Persistencia de cartera
# --------------------------------------------------------------------------- #
def test_sync_outstanding_upsert(tmp_db):
    mgr = CollectionsManager(db=tmp_db, tenant_id=1)
    n = mgr.sync_outstanding(INVOICES, today=TODAY)
    assert n == 4
    rows = tmp_db.list_outstanding_invoices(tenant_id=1)
    assert len(rows) == 4
    f4 = next(r for r in rows if r["factura_id"] == "F4")
    assert f4["dias_vencido"] == 120
    assert f4["score"] == 0.22


def test_sync_delete_paid(tmp_db):
    mgr = CollectionsManager(db=tmp_db, tenant_id=1)
    mgr.sync_outstanding(INVOICES, today=TODAY)
    # Nueva cartera sin F4 (como si se hubiera cobrado) y delete_paid=True.
    nueva = [i for i in INVOICES if i["factura_id"] != "F4"]
    mgr.sync_outstanding(nueva, today=TODAY, delete_paid=True)
    ids = {r["factura_id"] for r in tmp_db.list_outstanding_invoices(tenant_id=1)}
    assert "F4" not in ids
    assert len(ids) == 3
