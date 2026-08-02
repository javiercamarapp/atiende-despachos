# -*- coding: utf-8 -*-
"""
smtp_provider.py — AsyncSMTPProvider, proveedor SMTP asíncrono con aiosmtplib.

Complementa a `EmailProvider` (email_provider.py) con:
  * send()            — envío asíncrono simple con attachments opcionales.
  * send_template()   — envío asíncrono renderizando plantilla HTML + asunto.
  * send_bulk()       — envío masivo concurrente a varios destinatarios.
  * send_template_bulk() — envío masivo por plantilla.

Diseño:
  * Usa aiosmtplib para envío no bloqueante (ideal para workers async).
  * Soporta SMTP_SSL y STARTTLS según configuración.
  * Modo seguro: sin credenciales → simula (status='simulado').
  * Histórico de envíos en memoria (para tests / métricas).
  * Configuración desde env vars: SMTP_HOST, SMTP_PORT, SMTP_USER,
    SMTP_PASS, SMTP_FROM (también soporta B2B_SMTP_* por compatibilidad).
"""
from __future__ import annotations

import asyncio
import os
import re
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import List, Optional, Sequence, Tuple, Union

try:
    import aiosmtplib
except ImportError:  # pragma: no cover
    aiosmtplib = None  # type: ignore[assignment]

from b2b_ai.notifications.templates import render_html

Attachment = Union[Tuple[str, bytes], str]  # (nombre, contenido) o ruta


class AsyncSMTPProvider:
    """Proveedor SMTP asíncrono con plantillas HTML y envío masivo.

    Configuración (env vars, en orden de prioridad):
      SMTP_HOST / B2B_SMTP_HOST   — servidor SMTP
      SMTP_PORT / B2B_SMTP_PORT   — puerto (default 465)
      SMTP_USER / B2B_SMTP_USER   — usuario
      SMTP_PASS / B2B_SMTP_PASSWORD — contraseña
      SMTP_FROM / B2B_SMTP_FROM   — remitente (default: from B2B_DEFAULT_EMAIL env)

    Uso:
        provider = AsyncSMTPProvider()
        result = await provider.send("a@b.com", "Asunto", "Cuerpo")
        result = await provider.send_template("a@b.com", "welcome", ctx)
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        use_ssl: bool = True,
        default_recipient: Optional[str] = None,
        timeout: float = 15.0,
        max_concurrent: int = 5,
    ):
        env = os.environ
        # Env vars con soporte dual (SMTP_* y B2B_SMTP_*)
        self.host = host or env.get("SMTP_HOST") or env.get("B2B_SMTP_HOST")
        self.port = int(
            port
            or env.get("SMTP_PORT")
            or env.get("B2B_SMTP_PORT", "465")
        )
        self.user = user or env.get("SMTP_USER") or env.get("B2B_SMTP_USER")
        self.password = (
            password
            or env.get("SMTP_PASS")
            or env.get("B2B_SMTP_PASSWORD")
        )
        self.from_addr = (
            from_addr
            or env.get("SMTP_FROM")
            or env.get("B2B_SMTP_FROM", os.environ.get("B2B_DEFAULT_EMAIL", ""))
        )
        self.use_ssl = bool(use_ssl)
        if env.get("SMTP_USE_SSL", env.get("B2B_SMTP_USE_SSL", "")).lower() in (
            "0",
            "false",
            "no",
        ):
            self.use_ssl = False
        self.default_recipient = (
            default_recipient or env.get("SMTP_TO") or env.get("B2B_SMTP_TO")
        )
        self.timeout = float(timeout)
        self.max_concurrent = int(max_concurrent)
        self.sent: List[dict] = []  # historial en memoria

    # ------------------------------------------------------------------ #
    # Propiedades
    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        """True si hay credenciales suficientes para envío SMTP real."""
        return bool(self.host and self.user and self.password)

    # ------------------------------------------------------------------ #
    # Construcción de mensajes
    # ------------------------------------------------------------------ #
    def _build_message(
        self,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        attachments: Optional[Sequence[Attachment]] = None,
        cc: Optional[str] = None,
    ) -> MIMEMultipart:
        """Construye el MIMEMultipart con cuerpo texto/HTML y attachments."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        if cc:
            msg["Cc"] = cc

        text_part = MIMEText(body, "plain", "utf-8")
        msg.attach(text_part)
        if html:
            html_part = MIMEText(html, "html", "utf-8")
            msg.attach(html_part)

        for att in attachments or []:
            part = self._build_attachment(att)
            if part is not None:
                msg.attach(part)
        return msg

    @staticmethod
    def _build_attachment(att: Attachment) -> Optional[MIMEBase]:
        """Convierte (nombre, bytes) o ruta en un MIMEBase."""
        if isinstance(att, tuple):
            name, data = att
        else:
            path = os.fspath(att)
            if not os.path.isfile(path):
                return None
            name = os.path.basename(path)
            with open(path, "rb") as f:
                data = f.read()
        part = MIMEBase("application", "octet-stream")
        part.set_payload(data)
        part.add_header("Content-Disposition", "attachment", filename=name)
        return part

    # ------------------------------------------------------------------ #
    # Registro de envíos
    # ------------------------------------------------------------------ #
    def _record(
        self,
        to: str,
        subject: str,
        status: str,
        message: str,
        attachments: Optional[Sequence[Attachment]] = None,
        template: Optional[str] = None,
        html: Optional[bool] = None,
    ) -> dict:
        rec = {
            "to": to,
            "subject": subject,
            "status": status,
            "message": message,
            "attachments": len(attachments or []),
            "template": template,
            "html": bool(html),
        }
        self.sent.append(rec)
        return rec

    # ------------------------------------------------------------------ #
    # Envío asíncrono
    # ------------------------------------------------------------------ #
    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        attachments: Optional[Sequence[Attachment]] = None,
        template: Optional[str] = None,
        cc: Optional[str] = None,
    ) -> dict:
        """Envía un email de forma asíncrona. Devuelve dict resultado.

        Si no hay SMTP configurado, simula (status='simulado').
        Si aiosmtplib no está instalado, cae a modo síncrono simulado.
        """
        if not to:
            return self._record(
                to, subject, "error",
                "Destinatario vacío.",
                attachments, template=template, html=bool(html),
            )

        if aiosmtplib is None:  # pragma: no cover
            return self._record(
                to, subject, "error",
                "aiosmtplib no está instalado. Ejecuta: pip install aiosmtplib",
                attachments, template=template, html=bool(html),
            )

        msg = self._build_message(
            to, subject, body, html=html, attachments=attachments, cc=cc
        )

        if not self.configured:
            return self._record(
                to, subject, "simulado",
                "SMTP no configurado; email simulado. "
                "Configurar SMTP_HOST/SMTP_USER/SMTP_PASS para envío real.",
                attachments, template=template, html=bool(html),
            )

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                use_tls=self.use_ssl,
                timeout=self.timeout,
            )
            return self._record(
                to, subject, "sent",
                "Email enviado por SMTP (async).",
                attachments, template=template, html=bool(html),
            )
        except Exception as e:  # noqa: BLE001
            return self._record(
                to, subject, "error",
                f"Fallo SMTP: {type(e).__name__}: {e}",
                attachments, template=template, html=bool(html),
            )

    # ------------------------------------------------------------------ #
    # Envío por plantilla
    # ------------------------------------------------------------------ #
    async def send_template(
        self,
        to: str,
        template_name: str,
        context: dict,
        attachments: Optional[Sequence[Attachment]] = None,
        body_fallback: Optional[str] = None,
    ) -> dict:
        """Envía email renderizando una plantilla HTML (async).

        Si el destinatario no se pasa, usa `default_recipient`.
        """
        recipient = to or self.default_recipient
        if not recipient:
            return self._record(
                recipient or "(sin destino)", template_name, "error",
                "No hay destinatario (pasarlo o configurar SMTP_TO).",
                attachments, template=template_name, html=True,
            )
        subject, html = render_html(template_name, context)
        text = body_fallback or _strip_html(html)
        return await self.send(
            recipient, subject, text,
            html=html, attachments=attachments, template=template_name,
        )

    # ------------------------------------------------------------------ #
    # Envío masivo
    # ------------------------------------------------------------------ #
    async def send_bulk(
        self,
        recipients: Sequence[str],
        subject: str,
        body: str,
        html: Optional[str] = None,
        attachments: Optional[Sequence[Attachment]] = None,
    ) -> dict:
        """Envía el mismo email a varios destinatarios (async concurrente).

        Controla conciencia con un Semaphore para no saturar el servidor.
        Devuelve {sent, simulated, failed, results:[...]}.
        """
        sem = asyncio.Semaphore(self.max_concurrent)
        results = []

        async def _send_one(r: str):
            async with sem:
                return await self.send(
                    r, subject, body, html=html, attachments=attachments
                )

        tasks = [_send_one(r) for r in recipients]
        results = list(await asyncio.gather(*tasks))

        sent = sum(1 for r in results if r["status"] == "sent")
        simulated = sum(1 for r in results if r["status"] == "simulado")
        failed = sum(1 for r in results if r["status"] == "error")
        return {"sent": sent, "simulated": simulated, "failed": failed, "results": results}

    async def send_template_bulk(
        self,
        recipients: Sequence[str],
        template_name: str,
        context: dict,
        attachments: Optional[Sequence[Attachment]] = None,
    ) -> dict:
        """send_template para una lista de destinatarios (async concurrente)."""
        sem = asyncio.Semaphore(self.max_concurrent)
        results = []

        async def _send_one(r: str):
            async with sem:
                return await self.send_template(
                    r, template_name, dict(context), attachments=attachments
                )

        tasks = [_send_one(r) for r in recipients]
        results = list(await asyncio.gather(*tasks))
        return {"results": results}


# ------------------------------------------------------------------ #
# Helper: strip HTML → plain text
# ------------------------------------------------------------------ #
def _strip_html(html: str) -> str:
    """Convierte HTML simple a texto plano (para el body plain-text)."""
    text = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]
