# -*- coding: utf-8 -*-
"""Tests de la integración WhatsApp Business (mock de la API, sin red)."""
import pytest

from b2b_ai.notifications.whatsapp import (WhatsAppBusiness, MockWhatsApp)
from b2b_ai.notifications.templates import TEMPLATES, render


def _fake_post_ok(url, json, headers):
    """Transport fake que responde 200 como Meta (con id de mensaje)."""
    return type("R", (), {"json": lambda self: {
        "messaging_product": "whatsapp",
        "contacts": [{"input": json["to"], "wa_id": json["to"].replace("+", "")}],
        "messages": [{"id": "wamid.TEST123"}]}})()


def _fake_post_error(url, json, headers):
    """Transport fake que responde un error de la API de Meta."""
    return type("R", (), {"json": lambda self: {
        "error": {"code": 131030, "message": "Rate limit hit"}}})()


def _fake_post_raise(url, json, headers):
    """Transport fake que lanza excepción de red."""
    raise ConnectionError("simulated network failure")


# ---- configuración / simulación (sin credenciales) ----------------------- #
def test_no_config_simula():
    wa = WhatsAppBusiness(token="", phone_number_id="")
    assert wa.configured is False
    r = wa.send_message("+5215512345678", "Hola")
    assert r["status"] == "simulado"
    assert r["template"] is None
    assert len(wa.sent) == 1


def test_health_no_config():
    wa = WhatsAppBusiness()
    h = wa.health()
    assert h["configured"] is False
    assert "simulado" in h["detail"]


# ---- envío real mockeado (transport inyectado) --------------------------- #
def test_send_message_ok():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123", post=_fake_post_ok)
    assert wa.configured is True
    r = wa.send_message("+5215512345678", "Factura lista", template="exception")
    assert r["status"] == "sent"
    assert r["id"] == "wamid.TEST123"
    assert len(wa.sent) == 1


def test_send_error_api():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123",
                          post=_fake_post_error, max_attempts=2)
    r = wa.send_message("+5215512345678", "x")
    assert r["status"] == "error"
    assert "Rate limit" in r["message"]
    # solo se registra el resultado final (tras los 2 intentos)
    assert len(wa.sent) == 1


def test_send_network_exception_retries_then_fails():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123",
                          post=_fake_post_raise, max_attempts=3)
    r = wa.send_message("+5215512345678", "x")
    assert r["status"] == "error"
    assert "simulated network failure" in r["message"]
    assert len(wa.sent) == 1  # 3 intentos, 1 registro final


# ---- métodos de alto nivel (plantillas) ---------------------------------- #
def test_send_invoice_notification():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123", post=_fake_post_ok)
    r = wa.send_invoice_notification({
        "phone": "+5215512345678", "nombre": "Ana", "folio": "F-2026-001",
        "emisor": "Prov SA", "monto": "1,000.00", "categoria": "GASTO",
        "razon": "Papelería", "uuid": "uuid-x", "revision": ""})
    assert r["status"] == "sent"
    assert r["template"] == "invoice_processed"
    assert "F-2026-001" in r["text"]


def test_send_approval_request():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123", post=_fake_post_ok)
    r = wa.send_approval_request({
        "phone": "+5215512345678", "nombre": "Ana", "folio": "F2",
        "emisor": "Em", "monto": "50,000.00", "ref": "RFC: AAA010101AAA"})
    assert r["status"] == "sent"
    assert r["template"] == "requires_approval"
    assert "AAA010101AAA" in r["text"]


def test_send_daily_summary():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123", post=_fake_post_ok)
    r = wa.send_daily_summary({
        "phone": "+5215512345678", "nombre": "Ana", "fecha": "2026-07-31",
        "facturas": "12", "monto_total": "350,000", "pendientes": "2",
        "anomalias": "1"})
    assert r["status"] == "sent"
    assert r["template"] == "daily_summary"
    assert "2026-07-31" in r["text"]
    assert "12" in r["text"]


def test_send_anomaly_alert():
    wa = WhatsAppBusiness(token="tok", phone_number_id="123", post=_fake_post_ok)
    r = wa.send_anomaly_alert({
        "phone": "+5215512345678", "nombre": "Ana",
        "documento": "factura F9", "tipo": "monto atípico",
        "detalle": "supera 3x el promedio"})
    assert r["status"] == "sent"
    assert r["template"] == "anomaly_alert"
    assert "monto atípico" in r["text"]


def test_high_level_sin_recipiente_llama_error():
    wa = WhatsAppBusiness()
    with pytest.raises(ValueError):
        wa.send_invoice_notification({"folio": "F1"})


# ---- plantillas requeridas por la tarea ---------------------------------- #
def test_plantillas_notificaciones_existen():
    for t in ("invoice_processed", "requires_approval", "daily_summary",
              "anomaly_alert"):
        assert t in TEMPLATES, f"falta plantilla {t}"


def test_daily_summary_render():
    subj, body = render("daily_summary", {
        "nombre": "Ana", "fecha": "2026-07-31", "facturas": "5",
        "monto_total": "1,000", "pendientes": "1", "anomalias": "0"})
    assert "2026-07-31" in subj
    assert "5" in body


def test_anomaly_alert_render():
    subj, body = render("anomaly_alert", {
        "nombre": "Ana", "documento": "F1", "tipo": "duplicada",
        "detalle": "ya existe folio"})
    assert "duplicada" in subj
    assert "ya existe folio" in body


# ---- mock conserva compatibilidad ---------------------------------------- #
def test_mock_sigue_funcionando():
    wa = MockWhatsApp()
    r = wa.send_message("+5215512345678", "Hola", template_name="exception")
    assert r["status"] == "sent"
    assert len(wa.messages) == 1
