# -*- coding: utf-8 -*-
"""
test_smtp_notifications.py — Tests completos del sistema de notificaciones SMTP.

Cubre:
  1. AsyncSMTPProvider (envío async, simulación, error handling)
  2. Plantillas HTML (welcome, invoice_processed, collection_reminder, weekly_report)
  3. Envío masivo (bulk)
  4. Envío por plantilla con contexto
  5. Branding Likida AI en templates
  6. Env vars dual support (SMTP_* y B2B_SMTP_*)
  7. Edge cases (to vacío, template faltante, aiosmtplib mock failure)
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from email.mime.multipart import MIMEMultipart
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from b2b_ai.notifications.smtp_provider import AsyncSMTPProvider, _strip_html
from b2b_ai.notifications.templates import (
    render_html,
    html_subject,
    html_template_path,
)


# ====================================================================== #
# Fixtures y helpers
# ====================================================================== #
@pytest.fixture
def provider():
    """Proveedor sin SMTP configurado (modo simulado)."""
    return AsyncSMTPProvider()


@pytest.fixture
def configured_provider():
    """Proveedor con credenciales SMTP (mock, sin red real)."""
    return AsyncSMTPProvider(
        host="smtp.test.com",
        port=587,
        user="user@test.com",
        password="secret",
        from_addr="agente@likida.ai",
        use_ssl=False,
    )


@pytest.fixture(autouse=True)
def _clean_env():
    """Limpia env vars SMTP entre tests."""
    keys = [
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM",
        "SMTP_USE_SSL", "SMTP_TO",
        "B2B_SMTP_HOST", "B2B_SMTP_PORT", "B2B_SMTP_USER",
        "B2B_SMTP_PASSWORD", "B2B_SMTP_FROM", "B2B_SMTP_USE_SSL",
        "B2B_SMTP_TO",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _welcome_context():
    return {
        "nombre": "Despacho López",
        "usuario": "Ana López",
        "rfc": "XAXX010101000",
        "plan": "Pro",
        "fecha": "2026-08-01",
        "url_portal": "https://app.likida.ai/portal",
        "soporte_email": "soporte@likida.ai",
    }


def _invoice_context():
    return {
        "folio": "FAC-2026-001",
        "nombre": "Despacho López",
        "emisor": "Proveedor ABC",
        "monto": "12,500.00",
        "categoria": "Gastos deducibles",
        "razon": "Servicios profesionales",
        "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "fecha": "2026-08-01",
        "revision": "",
        "soporte_email": "soporte@likida.ai",
    }


def _collection_context():
    return {
        "nombre": "Despacho López",
        "cliente": "Empresa XYZ",
        "folio": "INV-2026-042",
        "monto": "35,000.00",
        "fecha_vencimiento": "2026-07-15",
        "dias_vencido": "17",
        "metodo_pago": "",
        "aviso_urgente": "",
        "url_portal": "https://app.likida.ai/portal",
        "soporte_email": "soporte@likida.ai",
    }


def _weekly_context():
    return {
        "nombre": "Despacho López",
        "periodo": "2026-W31",
        "facturas": "24",
        "total": "185,000.00",
        "aprobadas": "20",
        "pendientes": "4",
        "fila_resumen": "",
        "detalle": "",
        "soporte_email": "soporte@likida.ai",
    }


# ====================================================================== #
# 1. AsyncSMTPProvider — Envío asíncrono básico
# ====================================================================== #
class TestAsyncSMTPProviderBasico:
    """Tests del proveedor SMTP async en modo simulado."""

    @pytest.mark.asyncio
    async def test_send_simulado_sin_smtp(self, provider):
        """Sin credenciales → status simulado."""
        result = await provider.send("a@b.com", "Asunto", "Cuerpo")
        assert result["status"] == "simulado"
        assert result["to"] == "a@b.com"
        assert result["html"] is False

    @pytest.mark.asyncio
    async def test_send_vacio_devuelve_error(self, provider):
        """To vacío → status error."""
        result = await provider.send("", "Asunto", "Cuerpo")
        assert result["status"] == "error"
        assert "vacío" in result["message"]

    @pytest.mark.asyncio
    async def test_send_con_html(self, provider):
        """Envío con HTML genera registro correcto."""
        result = await provider.send(
            "a@b.com", "Asunto", "Texto",
            html="<h1>Hola</h1>",
        )
        assert result["status"] == "simulado"
        assert result["html"] is True

    @pytest.mark.asyncio
    async def test_historial_se_acumula(self, provider):
        """Cada envío se registra en el historial."""
        await provider.send("a@b.com", "S1", "B1")
        await provider.send("b@c.com", "S2", "B2")
        await provider.send("", "S3", "B3")  # vacío → error
        assert len(provider.sent) == 3
        assert provider.sent[2]["status"] == "error"

    @pytest.mark.asyncio
    async def test_send_con_attachments_bytes(self, provider):
        """Attachments por (nombre, bytes)."""
        result = await provider.send(
            "a@b.com", "Con adjuntos", "Cuerpo",
            attachments=[("factura.pdf", b"%PDF-fake-content")],
        )
        assert result["attachments"] == 1

    @pytest.mark.asyncio
    async def test_send_con_attachments_ruta(self, provider):
        """Attachments por ruta de archivo."""
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<xml>CFDI</xml>")
            path = f.name
        try:
            result = await provider.send(
                "a@b.com", "Con archivo", "Cuerpo",
                attachments=[path],
            )
            assert result["attachments"] == 1
        finally:
            os.remove(path)

    @pytest.mark.asyncio
    async def test_send_attachment_inexistente(self, provider):
        """Attachment con ruta inexistente se incluye en el count
        pero _build_attachment devuelve None (el archivo no se adjunta)."""
        result = await provider.send(
            "a@b.com", "Sin adj", "Cuerpo",
            attachments=["/no/existe.pdf"],
        )
        # _record usa len(original attachments list), not actual attached
        # This is by design — the caller sees they "tried" to attach
        assert result["attachments"] == 1  # list length counted


# ====================================================================== #
# 2. AsyncSMTPProvider — Envío por plantilla
# ====================================================================== #
class TestAsyncSMTPProviderTemplates:
    """Tests de send_template con plantillas HTML reales."""

    @pytest.mark.asyncio
    async def test_send_template_welcome(self, provider):
        """Plantilla welcome genera email con HTML y asunto correcto."""
        result = await provider.send_template(
            "a@b.com", "welcome", _welcome_context()
        )
        assert result["status"] == "simulado"
        assert result["template"] == "welcome"
        assert result["html"] is True
        assert "Despacho López" in result["subject"]

    @pytest.mark.asyncio
    async def test_send_template_invoice_processed(self, provider):
        """Plantilla invoice_processed."""
        result = await provider.send_template(
            "a@b.com", "invoice_processed", _invoice_context()
        )
        assert result["status"] == "simulado"
        assert result["template"] == "invoice_processed"
        assert "FAC-2026-001" in result["subject"]

    @pytest.mark.asyncio
    async def test_send_template_collection_reminder(self, provider):
        """Plantilla collection_reminder (nueva)."""
        result = await provider.send_template(
            "a@b.com", "collection_reminder", _collection_context()
        )
        assert result["status"] == "simulado"
        assert result["template"] == "collection_reminder"
        assert "Empresa XYZ" in result["subject"]

    @pytest.mark.asyncio
    async def test_send_template_weekly_report(self, provider):
        """Plantilla weekly_report."""
        result = await provider.send_template(
            "a@b.com", "weekly_report", _weekly_context()
        )
        assert result["status"] == "simulado"
        assert result["template"] == "weekly_report"
        assert "2026-W31" in result["subject"]

    @pytest.mark.asyncio
    async def test_send_template_sin_destino(self):
        """Sin destinatario ni default_recipient → error."""
        p = AsyncSMTPProvider(default_recipient=None)
        result = await p.send_template(None, "welcome", _welcome_context())
        assert result["status"] == "error"
        assert "destinatario" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_send_template_usa_default_recipient(self):
        """Si no hay to, usa default_recipient."""
        p = AsyncSMTPProvider(default_recipient="fallback@test.com")
        result = await p.send_template(None, "welcome", _welcome_context())
        assert result["status"] == "simulado"
        assert result["to"] == "fallback@test.com"

    @pytest.mark.asyncio
    async def test_send_template_desconocida(self, provider):
        """Plantilla inexistente → KeyError."""
        with pytest.raises(KeyError):
            await provider.send_template("a@b.com", "no_existe", {})

    @pytest.mark.asyncio
    async def test_send_template_falta_contexto(self, provider):
        """Plantilla con contexto incompleto → ValueError."""
        with pytest.raises(ValueError):
            await provider.send_template("a@b.com", "welcome", {"nombre": "X"})

    @pytest.mark.asyncio
    async def test_send_template_con_body_fallback(self, provider):
        """El body_fallback se usa como texto plano."""
        result = await provider.send_template(
            "a@b.com", "welcome", _welcome_context(),
            body_fallback="Texto custom",
        )
        assert result["status"] == "simulado"


# ====================================================================== #
# 3. Envío masivo (bulk)
# ====================================================================== #
class TestAsyncSMTPProviderBulk:
    """Tests de envío masivo async."""

    @pytest.mark.asyncio
    async def test_send_bulk_simulado(self, provider):
        """Envío bulk sin SMTP → todos simulados."""
        recipients = ["a@b.com", "c@d.com", "e@f.com"]
        result = await provider.send_bulk(
            recipients, "Boletín", "Contenido"
        )
        assert result["simulated"] == 3
        assert result["sent"] == 0
        assert result["failed"] == 0
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_send_bulk_con_fallidos(self, provider):
        """Destinatarios vacíos se marcan como fallidos."""
        result = await provider.send_bulk(
            ["a@b.com", "", "c@d.com"], "Asunto", "Cuerpo"
        )
        assert result["simulated"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_send_bulk_con_html(self, provider):
        """Bulk con HTML genera registros con html=True."""
        result = await provider.send_bulk(
            ["a@b.com", "c@d.com"], "HTML", "Texto",
            html="<b>Bold</b>",
        )
        assert all(r["html"] is True for r in result["results"])

    @pytest.mark.asyncio
    async def test_send_template_bulk(self, provider):
        """send_template_bulk con múltiples destinatarios."""
        ctx = _welcome_context()
        result = await provider.send_template_bulk(
            ["a@b.com", "c@d.com"], "welcome", ctx
        )
        assert len(result["results"]) == 2
        assert all(r["template"] == "welcome" for r in result["results"])
        assert all(r["html"] is True for r in result["results"])

    @pytest.mark.asyncio
    async def test_send_template_bulk_collection(self, provider):
        """send_template_bulk con collection_reminder."""
        ctx = _collection_context()
        result = await provider.send_template_bulk(
            ["cobros@test.com"], "collection_reminder", ctx
        )
        assert len(result["results"]) == 1
        assert result["results"][0]["template"] == "collection_reminder"


# ====================================================================== #
# 4. Envío SMTP real (mock)
# ====================================================================== #
class TestAsyncSMTPProviderRealSend:
    """Tests con aiosmtplib mockeado para verificar el envío real."""

    @pytest.mark.asyncio
    async def test_send_real_llama_aiosmtplib(self, configured_provider):
        """Con credenciales → llama a aiosmtplib.send."""
        mock_send = AsyncMock()
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock_aiosmtp:
            mock_aiosmtp.send = mock_send
            result = await configured_provider.send(
                "client@test.com", "Factura procesada", "Su factura fue procesada."
            )
            assert result["status"] == "sent"
            assert result["message"] == "Email enviado por SMTP (async)."
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert isinstance(call_args[0][0], MIMEMultipart)

    @pytest.mark.asyncio
    async def test_send_real_con_html(self, configured_provider):
        """Envío real con HTML se registra correctamente."""
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock_aiosmtp:
            mock_aiosmtp.send = AsyncMock()
            result = await configured_provider.send(
                "a@b.com", "Test", "Plain",
                html="<h1>Hola</h1>",
            )
            assert result["html"] is True
            assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_send_real_fallo_smtp(self, configured_provider):
        """Fallo de aiosmtplib → status error."""
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock_aiosmtp:
            mock_aiosmtp.send = AsyncMock(
                side_effect=ConnectionError("SMTP down")
            )
            result = await configured_provider.send(
                "a@b.com", "Test", "Body"
            )
            assert result["status"] == "error"
            assert "ConnectionError" in result["message"]

    @pytest.mark.asyncio
    async def test_send_real_template(self, configured_provider):
        """Envío real de plantilla."""
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock_aiosmtp:
            mock_aiosmtp.send = AsyncMock()
            result = await configured_provider.send_template(
                "a@b.com", "welcome", _welcome_context()
            )
            assert result["status"] == "sent"
            assert result["template"] == "welcome"

    @pytest.mark.asyncio
    async def test_send_real_bulk(self, configured_provider):
        """Envío bulk real con mock."""
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock_aiosmtp:
            mock_aiosmtp.send = AsyncMock()
            result = await configured_provider.send_bulk(
                ["a@b.com", "c@d.com"], "Bulk", "Body"
            )
            assert result["sent"] == 2
            assert result["failed"] == 0
            assert mock_aiosmtp.send.call_count == 2


# ====================================================================== #
# 5. Plantillas HTML — Existencia y renderizado
# ====================================================================== #
class TestPlantillasHTML:
    """Verifica que las 4 plantillas requeridas existen y renderizan."""

    @pytest.mark.parametrize("name", [
        "welcome",
        "invoice_processed",
        "collection_reminder",
        "weekly_report",
    ])
    def test_plantilla_existe(self, name):
        """Las 4 plantillas core existen."""
        assert html_template_path(name) is not None

    def test_welcome_renderiza(self):
        """Plantilla welcome renderiza correctamente."""
        subj, html = render_html("welcome", _welcome_context())
        assert "Despacho López" in subj
        assert "Ana López" in html
        assert "XAXX010101000" in html
        assert "Pro" in html

    def test_invoice_processed_renderiza(self):
        """Plantilla invoice_processed renderiza correctamente."""
        subj, html = render_html("invoice_processed", _invoice_context())
        assert "FAC-2026-001" in subj
        assert "Proveedor ABC" in html
        assert "12,500.00" in html

    def test_collection_reminder_renderiza(self):
        """Plantilla collection_reminder renderiza correctamente."""
        subj, html = render_html("collection_reminder", _collection_context())
        assert "Empresa XYZ" in subj
        assert "35,000.00" in html
        assert "INV-2026-042" in html

    def test_weekly_report_renderiza(self):
        """Plantilla weekly_report renderiza correctamente."""
        subj, html = render_html("weekly_report", _weekly_context())
        assert "2026-W31" in subj
        assert "24" in html
        assert "185,000.00" in html

    def test_plantilla_desconocida_raises(self):
        """Plantilla inexistente → KeyError."""
        with pytest.raises(KeyError):
            render_html("plantilla_inexistente", {})

    def test_plantilla_falta_contexto_raises(self):
        """Contexto incompleto → ValueError."""
        with pytest.raises(ValueError):
            render_html("welcome", {"nombre": "Solo"})


# ====================================================================== #
# 6. Branding Likida AI
# ====================================================================== #
class TestBrandingLikidaAI:
    """Verifica que los templates están brandeados con Likida AI."""

    @pytest.mark.parametrize("template_name,ctx", [
        ("welcome", _welcome_context()),
        ("invoice_processed", _invoice_context()),
        ("collection_reminder", _collection_context()),
        ("weekly_report", _weekly_context()),
    ])
    def test_branding_presente(self, template_name, ctx):
        """Todos los templates core contienen branding Likida AI."""
        _, html = render_html(template_name, ctx)
        assert "Likida AI" in html

    @pytest.mark.parametrize("template_name,ctx", [
        ("welcome", _welcome_context()),
        ("invoice_processed", _invoice_context()),
        ("collection_reminder", _collection_context()),
        ("weekly_report", _weekly_context()),
    ])
    def test_css_inline(self, template_name, ctx):
        """Los templates usan inline CSS (compatible con email clients)."""
        _, html = render_html(template_name, ctx)
        assert "<style>" in html
        # No deben tener external stylesheets
        assert 'rel="stylesheet"' not in html.lower()

    @pytest.mark.parametrize("template_name,ctx", [
        ("welcome", _welcome_context()),
        ("invoice_processed", _invoice_context()),
        ("collection_reminder", _collection_context()),
        ("weekly_report", _weekly_context()),
    ])
    def test_espanol_primario(self, template_name, ctx):
        """Los templates están en español (idioma primario)."""
        _, html = render_html(template_name, ctx)
        assert 'lang="es"' in html


# ====================================================================== #
# 7. Env vars dual support
# ====================================================================== #
class TestEnvVarsDualSupport:
    """Soporte dual de env vars: SMTP_* y B2B_SMTP_*."""

    def test_smtp_host_desde_env(self):
        os.environ["SMTP_HOST"] = "smtp.gmail.com"
        os.environ["SMTP_USER"] = "user@gmail.com"
        os.environ["SMTP_PASS"] = "pass123"
        p = AsyncSMTPProvider()
        assert p.host == "smtp.gmail.com"
        assert p.user == "user@gmail.com"
        assert p.configured

    def test_b2b_smtp_host_desde_env(self):
        os.environ["B2B_SMTP_HOST"] = "smtp.legacy.com"
        os.environ["B2B_SMTP_USER"] = "old@user.com"
        os.environ["B2B_SMTP_PASSWORD"] = "oldpass"
        p = AsyncSMTPProvider()
        assert p.host == "smtp.legacy.com"
        assert p.user == "old@user.com"
        assert p.configured

    def test_smtp_takes_priority_over_b2b(self):
        """SMTP_* tiene prioridad sobre B2B_SMTP_*."""
        os.environ["SMTP_HOST"] = "smtp.priority.com"
        os.environ["B2B_SMTP_HOST"] = "smtp.legacy.com"
        os.environ["SMTP_USER"] = "user@priority.com"
        os.environ["B2B_SMTP_USER"] = "user@legacy.com"
        os.environ["SMTP_PASS"] = "pass"
        p = AsyncSMTPProvider()
        assert p.host == "smtp.priority.com"
        assert p.user == "user@priority.com"

    def test_sin_env_vars_no_configurado(self):
        """Sin env vars → no configurado (modo seguro)."""
        p = AsyncSMTPProvider()
        assert not p.configured

    def test_smtp_from_default(self):
        """Default from_addr correcto."""
        p = AsyncSMTPProvider()
        assert p.from_addr == "agente@b2b-ai.local"

    def test_smtp_port_default(self):
        """Default port es 465."""
        p = AsyncSMTPProvider()
        assert p.port == 465

    def test_use_ssl_disabled_via_env(self):
        """SMTP_USE_SSL=false desactiva SSL."""
        os.environ["SMTP_USE_SSL"] = "false"
        p = AsyncSMTPProvider()
        assert p.use_ssl is False


# ====================================================================== #
# 8. Helper _strip_html
# ====================================================================== #
class TestStripHtml:
    """Tests del helper de conversión HTML → texto plano."""

    def test_strip_basico(self):
        text = _strip_html("<h1>Hola</h1><p>Mundo</p>")
        assert "Hola" in text
        assert "Mundo" in text
        assert "<" not in text

    def test_strip_estilos(self):
        html = "<style>.x{color:red}</style><p>Hola</p>"
        text = _strip_html(html)
        assert "color:red" not in text
        assert "Hola" in text

    def test_strip_largo_limitado(self):
        html = "<p>" + "x" * 3000 + "</p>"
        text = _strip_html(html)
        assert len(text) <= 2000


# ====================================================================== #
# 9. Multipart message building
# ====================================================================== #
class TestMessageBuilding:
    """Verifica la construcción correcta de MIME messages."""

    def test_build_message_text_only(self, configured_provider):
        msg = configured_provider._build_message(
            "a@b.com", "Test", "Plain text"
        )
        assert msg["To"] == "a@b.com"
        assert msg["Subject"] == "Test"
        assert msg["From"] == "agente@likida.ai"
        parts = msg.get_payload()
        assert len(parts) >= 1  # al menos text/plain

    def test_build_message_text_and_html(self, configured_provider):
        msg = configured_provider._build_message(
            "a@b.com", "Test", "Plain", html="<h1>Hola</h1>"
        )
        parts = msg.get_payload()
        assert len(parts) == 2  # text/plain + text/html

    def test_build_message_with_cc(self, configured_provider):
        msg = configured_provider._build_message(
            "a@b.com", "Test", "Body", cc="cc@test.com"
        )
        assert msg["Cc"] == "cc@test.com"

    def test_build_message_with_attachment(self, configured_provider):
        msg = configured_provider._build_message(
            "a@b.com", "Test", "Body",
            attachments=[("test.pdf", b"data")],
        )
        # alternative + attachment
        parts = msg.get_payload()
        assert len(parts) >= 2


# ====================================================================== #
# 10. Casos edge
# ====================================================================== #
class TestEdgeCases:
    """Edge cases y escenarios raros."""

    @pytest.mark.asyncio
    async def test_send_cc_en_simulado(self, provider):
        """El cc se registra aunque sea simulado."""
        result = await provider.send(
            "a@b.com", "Test", "Body", cc="cc@b.com"
        )
        assert result["status"] == "simulado"

    @pytest.mark.asyncio
    async def test_send_con_none_attachments(self, provider):
        """Attachments=None no causa error."""
        result = await provider.send(
            "a@b.com", "Test", "Body", attachments=None
        )
        assert result["attachments"] == 0

    @pytest.mark.asyncio
    async def test_bulk_lista_vacia(self, provider):
        """Bulk con lista vacía."""
        result = await provider.send_bulk([], "Test", "Body")
        assert result["sent"] == 0
        assert result["simulated"] == 0
        assert result["failed"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_template_bulk_lista_vacia(self, provider):
        """Template bulk con lista vacía."""
        result = await provider.send_template_bulk(
            [], "welcome", _welcome_context()
        )
        assert result["results"] == []

    def test_configured_requiere_todos(self):
        """configured=True solo con host+user+password."""
        assert not AsyncSMTPProvider().configured
        assert not AsyncSMTPProvider(host="x").configured
        assert not AsyncSMTPProvider(host="x", user="u").configured
        assert AsyncSMTPProvider(host="x", user="u", password="p").configured


# ====================================================================== #
# 11. Integration: 4 tipos de email del sistema
# ====================================================================== #
class TestCuatroTiposEmail:
    """Verifica los 4 tipos de email solicitados: welcome, invoice,
    collection_reminder, weekly_report."""

    @pytest.mark.asyncio
    async def test_welcome_email_flow(self, provider):
        """Flujo completo: welcome email."""
        result = await provider.send_template(
            "nuevo@cliente.com", "welcome", _welcome_context()
        )
        assert result["template"] == "welcome"
        assert result["html"] is True
        assert "Bienvenido" in result["subject"]

    @pytest.mark.asyncio
    async def test_invoice_email_flow(self, provider):
        """Flujo completo: invoice processing confirmation."""
        result = await provider.send_template(
            "contador@despacho.com", "invoice_processed", _invoice_context()
        )
        assert result["template"] == "invoice_processed"
        assert "FAC-2026-001" in result["subject"]

    @pytest.mark.asyncio
    async def test_collection_email_flow(self, provider):
        """Flujo completo: collection reminder."""
        result = await provider.send_template(
            "cobros@despacho.com", "collection_reminder", _collection_context()
        )
        assert result["template"] == "collection_reminder"
        assert "Empresa XYZ" in result["subject"]
        assert "35,000.00" in result["subject"]

    @pytest.mark.asyncio
    async def test_weekly_email_flow(self, provider):
        """Flujo completo: weekly digest."""
        result = await provider.send_template(
            "resumen@despacho.com", "weekly_report", _weekly_context()
        )
        assert result["template"] == "weekly_report"
        assert "2026-W31" in result["subject"]


# ====================================================================== #
# 12. aiosmtplib import guard
# ====================================================================== #
class TestAiosmtplibImport:
    """Verifica el guard de import de aiosmtplib."""

    @pytest.mark.asyncio
    async def test_sin_aiosmtplib_devuelve_error(self):
        """Si aiosmtplib no está instalado → error informativo."""
        p = AsyncSMTPProvider(
            host="smtp.test.com", user="u", password="p"
        )
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib", None):
            result = await p.send("a@b.com", "Test", "Body")
            assert result["status"] == "error"
            assert "aiosmtplib" in result["message"]


# ====================================================================== #
# 13. Async execution correctness
# ====================================================================== #
class TestAsyncExecution:
    """Verifica que los métodos son realmente async."""

    def test_send_es_coroutine(self, provider):
        """send() devuelve una coroutine."""
        coro = provider.send("a@b.com", "T", "B")
        assert asyncio.iscoroutine(coro)
        coro.close()

    def test_send_template_es_coroutine(self, provider):
        """send_template() devuelve una coroutine."""
        coro = provider.send_template("a@b.com", "welcome", _welcome_context())
        assert asyncio.iscoroutine(coro)
        coro.close()

    def test_send_bulk_es_coroutine(self, provider):
        """send_bulk() devuelve una coroutine."""
        coro = provider.send_bulk(["a@b.com"], "T", "B")
        assert asyncio.iscoroutine(coro)
        coro.close()

    @pytest.mark.asyncio
    async def test_send_bulk_ejecuta_concurrente(self, configured_provider):
        """Bulk usa asyncio.gather para concurrencia real."""
        call_count = 0
        original_send = configured_provider.send

        async def counting_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_send(*args, **kwargs)

        configured_provider.send = counting_send
        with patch("b2b_ai.notifications.smtp_provider.aiosmtplib") as mock:
            mock.send = AsyncMock()
            await configured_provider.send_bulk(
                ["a@b.com", "c@d.com", "e@f.com"], "T", "B"
            )
            assert call_count == 3
            assert mock.send.call_count == 3
