# -*- coding: utf-8 -*-
"""
test_notifications_integration.py — Integration tests for notifications.

Covers:
  - Template rendering with multiple event contexts
  - WhatsApp mock does not crash
  - Email sender simulation
"""
import pytest

from b2b_ai.notifications.templates import render, TEMPLATES
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.notifications.whatsapp import MockWhatsApp


# ---------------------------------------------------------------------------
# 1. Template rendering with realistic contexts
# ---------------------------------------------------------------------------
@pytest.fixture
def invoice_ctx():
    return {
        "nombre": "Ana López",
        "folio": "F-2026-07-001",
        "emisor": "Proveedor SA de CV",
        "monto": "15,000.00",
        "categoria": "GASTO OPERATIVO",
        "razon": "Material de oficina",
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "revision": "",
    }


def test_render_invoice_processed(invoice_ctx):
    subj, body = render("invoice_processed", invoice_ctx)
    assert "F-2026-07-001" in subj
    assert "Ana López" in body
    assert "GASTO OPERATIVO" in body
    assert "El agente prepara y valida" in body


def test_render_invoice_review(invoice_ctx):
    ctx = {**invoice_ctx, "confianza": "0.65", "fuente": "llm",
           "anomalias": "Monto atípico"}
    subj, body = render("invoice_review", ctx)
    assert "requiere revisión humana" in body or "🔎" in subj
    assert "0.65" in body


def test_render_exception(invoice_ctx):
    ctx = {**invoice_ctx, "detalle": "No se pudo parsear el XML"}
    subj, body = render("exception", ctx)
    assert "excepción" in body.lower() or "⚠" in subj
    assert "No se pudo parsear" in body


def test_render_requires_approval(invoice_ctx):
    ctx = {**invoice_ctx, "ref": "RFC del emisor: AAA010101AAA"}
    subj, body = render("requires_approval", ctx)
    assert "Aprobación requerida" in subj or "supera el umbral" in body
    assert "AAA010101AAA" in body


def test_render_reconciliation_discrepancy():
    ctx = {"nombre": "Ana", "cantidad": "3", "periodo": "2026-07"}
    subj, body = render("reconciliation_discrepancy", ctx)
    assert "3" in subj
    assert "2026-07" in body


def test_render_report_ready():
    ctx = {"nombre": "Ana", "periodo": "Julio 2026", "facturas": "45", "total": "350,000"}
    subj, body = render("report_ready", ctx)
    assert "Julio 2026" in subj
    assert "45" in body
    assert "350,000" in body


def test_render_extra_subject(invoice_ctx):
    subj, body = render("invoice_processed", invoice_ctx,
                        extra_subject="[TEST]")
    assert subj.startswith("[TEST]")


def test_render_falta_contexto_lanza_error():
    with pytest.raises(ValueError):
        render("invoice_processed", {"nombre": "Solo nombre"})


def test_render_evento_desconocido_lanza_error():
    with pytest.raises(KeyError):
        render("evento_inexistente", {})


# ---------------------------------------------------------------------------
# 2. WhatsApp mock does not crash
# ---------------------------------------------------------------------------
def test_whatsapp_mock_envia_mensaje():
    wa = MockWhatsApp()
    r = wa.send_message("+5215550001111", "Notificación de prueba",
                        template_name="exception")
    assert r["status"] == "sent"
    assert r["id"].startswith("WA-")
    assert len(wa.messages) == 1


def test_whatsapp_mock_con_contactos():
    wa = MockWhatsApp()
    wa.register_phone("Cliente A", "+5215550001111")

    # Enviar a contacto existente
    r = wa.send_to_contact("Cliente A", "Su factura está lista")
    assert r["status"] == "sent"

    # Enviar a contacto inexistente
    r = wa.send_to_contact("Inexistente", "Hola")
    assert r["status"] == "error"


def test_whatsapp_mock_health():
    wa = MockWhatsApp()
    h = wa.health()
    assert h["ok"] is True
    assert "mock" in h["detail"].lower()


def test_whatsapp_mock_multiple_mensajes():
    wa = MockWhatsApp()
    for i in range(5):
        wa.send_message("+5215550000000", f"Mensaje {i}")
    assert len(wa.messages) == 5
    assert wa.messages[0]["text"] == "Mensaje 0"
    assert wa.messages[4]["text"] == "Mensaje 4"


# ---------------------------------------------------------------------------
# 3. Email sender simulation
# ---------------------------------------------------------------------------
def test_email_simulation():
    sender = EmailSender()
    assert sender.configured is False

    r = sender.send("destino@ejemplo.com", "Asunto Test", "Cuerpo del email")
    assert r["status"] == "simulado"
    assert len(sender.sent) == 1


def test_email_historial():
    sender = EmailSender()
    sender.send("a@b.com", "S1", "B1")
    sender.send("c@d.com", "S2", "B2")
    assert len(sender.sent) == 2
    assert sender.sent[0]["to"] == "a@b.com"
    assert sender.sent[1]["to"] == "c@d.com"


# ---------------------------------------------------------------------------
# 4. All required templates exist
# ---------------------------------------------------------------------------
def test_todas_las_plantillas_requeridas_existen():
    required = {
        "invoice_processed", "invoice_parse_failed", "invoice_rejected",
        "invoice_review", "exception", "requires_approval",
        "reconciliation_discrepancy", "report_ready",
    }
    missing = required - set(TEMPLATES.keys())
    assert not missing, f"Faltan plantillas: {missing}"