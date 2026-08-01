# -*- coding: utf-8 -*-
"""Tests de notificaciones (plantillas, email, whatsapp mock)."""
import pytest

from b2b_ai.notifications.templates import render, TEMPLATES
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.notifications.whatsapp import MockWhatsApp


def test_render_plantilla():
    subj, body = render("invoice_processed", {
        "nombre": "Ana", "folio": "F1", "emisor": "Em", "monto": "100",
        "categoria": "gasto", "razon": "r", "uuid": "u", "revision": ""})
    assert "F1" in subj
    assert "Ana" in body


def test_render_falta_contexto():
    with pytest.raises(ValueError):
        render("invoice_processed", {"nombre": "Ana"})


def test_render_evento_desconocido():
    with pytest.raises(KeyError):
        render("no_existe", {})


def test_plantillas_requeridas():
    for t in ("invoice_processed", "exception", "requires_approval",
              "reconciliation_discrepancy", "report_ready"):
        assert t in TEMPLATES


def test_email_sin_smtp_simula():
    s = EmailSender()
    r = s.send("a@b.com", "Asunto", "Cuerpo")
    assert r["status"] == "simulado"
    assert not s.configured


def test_email_en_historial():
    s = EmailSender()
    s.send("a@b.com", "S1", "B1")
    s.send("b@c.com", "S2", "B2")
    assert len(s.sent) == 2


def test_whatsapp_mock_envia():
    wa = MockWhatsApp()
    r = wa.send_message("+5215500000000", "Hola", template_name="exception")
    assert r["status"] == "sent"
    assert len(wa.messages) == 1


def test_whatsapp_contactos():
    wa = MockWhatsApp()
    wa.register_phone("cliente", "+5215500000000")
    r = wa.send_to_contact("cliente", "Aviso")
    assert r["status"] == "sent"
    r2 = wa.send_to_contact("inexistente", "Aviso")
    assert r2["status"] == "error"
