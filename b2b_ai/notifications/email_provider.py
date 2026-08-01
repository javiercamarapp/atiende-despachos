# -*- coding: utf-8 -*-
"""
email_provider.py — EmailProvider, proveedor SMTP de alto nivel.

Reemplaza/complementa a `EmailSender` (sender.py) añadiendo:
  * send()            — envío simple con attachments opcionales.
  * send_template()   — envío renderizando una plantilla HTML + asunto.
  * send_bulk()       — envío masivo a varios destinatarios.

Modo seguro por defecto: si no hay credenciales SMTP configuradas (ni
argumentos host/user/password) NO se envía nada real; cada mensaje se registra
como "simulado" y se devuelve el dict de resultado. Así los tests y entornos
sin SMTP no dependen de red.

Cuando hay credenciales, envía por SMTP_SSL o SMTP+STARTTLS según `use_ssl`.
Attachments: lista de (nombre_archivo, bytes) o de rutas absolutas.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import List, Optional, Sequence, Tuple, Union

from b2b_ai.notifications.templates import render_html

Attachment = Union[Tuple[str, bytes], str]  # (nombre, contenido) o ruta


class EmailProvider:
    """Proveedor SMTP con plantillas HTML y envío masivo."""

    def __init__(self, host: Optional[str] = None, port: int = 465,
                 user: Optional[str] = None, password: Optional[str] = None,
                 from_addr: Optional[str] = None, use_ssl: bool = True,
                 default_recipient: Optional[str] = None):
        env = os.environ
        self.host = host or env.get("SMTP_HOST")
        self.port = int(port or env.get("SMTP_PORT", "465"))
        self.user = user or env.get("SMTP_USER")
        self.password = password or env.get("SMTP_PASSWORD")
        self.from_addr = from_addr or env.get(
            "SMTP_FROM", "agente@b2b-ai.local")
        self.use_ssl = bool(use_ssl)
        if env.get("SMTP_USE_SSL", "").lower() in ("0", "false", "no"):
            self.use_ssl = False
        self.default_recipient = default_recipient or env.get("SMTP_TO")
        self.sent: List[dict] = []  # historial en memoria

    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        """True si hay credenciales suficientes para envío SMTP real."""
        return bool(self.host and self.user and self.password)

    # ------------------------------------------------------------------ #
    def _build_message(self, to: str, subject: str, body: str,
                       html: Optional[str] = None,
                       attachments: Optional[Sequence[Attachment]] = None,
                       cc: Optional[str] = None):
        """Construye el MIMEMultipart con cuerpo texto/HTML y attachments."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        if cc:
            msg["Cc"] = cc

        text = MIMEText(body, "plain", "utf-8")
        msg.attach(text)
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        for att in attachments or []:
            part = self._build_attachment(att)
            if part is not None:
                msg.attach(part)
        return msg

    @staticmethod
    def _build_attachment(att: Attachment) -> Optional[MIMEBase]:
        """Convierte (nombre, bytes) o ruta en un MIMEBase con Content-Disposition."""
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
        part.add_header("Content-Disposition", "attachment",
                        filename=name)
        return part

    # ------------------------------------------------------------------ #
    def _record(self, to, subject, status, message, attachments=None,
                template=None, html=None):
        rec = {"to": to, "subject": subject, "status": status,
               "message": message, "attachments": len(attachments or []),
               "template": template, "html": bool(html)}
        self.sent.append(rec)
        return rec

    # ------------------------------------------------------------------ #
    def send(self, to: str, subject: str, body: str,
             html: Optional[str] = None,
             attachments: Optional[Sequence[Attachment]] = None):
        """Envía un email. Devuelve dict {to, subject, status, message}.

        Si no hay SMTP configurado, simula (status='simulado') y devuelve.
        """
        if not to:
            return self._record(to, subject, "error",
                                "Destinatario vacío.", attachments)
        msg = self._build_message(to, subject, body, html=html,
                                  attachments=attachments)
        if not self.configured:
            return self._record(
                to, subject, "simulado",
                "SMTP no configurado; email simulado. Configurar "
                "SMTP_HOST/SMTP_USER/SMTP_PASSWORD para envío real.",
                attachments)
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=15,
                    context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=15)
                server.starttls(context=ssl.create_default_context())
            server.login(self.user, self.password)
            server.sendmail(self.from_addr, [to], msg.as_string())
            server.quit()
            return self._record(to, subject, "sent",
                                "Email enviado por SMTP.", attachments)
        except Exception as e:  # noqa: BLE001
            return self._record(to, subject, "error",
                                f"Fallo SMTP: {type(e).__name__}: {e}",
                                attachments)

    # ------------------------------------------------------------------ #
    def send_template(self, to: str, template_name: str, context: dict,
                      attachments: Optional[Sequence[Attachment]] = None,
                      body_fallback: Optional[str] = None):
        """Envía un email renderizando una plantilla HTML.

        Devuelve dict de resultado. Si el destinatario no se pasa, usa
        `default_recipient` (config). Requiere que la plantilla exista.
        """
        recipient = to or self.default_recipient
        if not recipient:
            return self._record(
                recipient or "(sin destino)", template_name, "error",
                "No hay destinatario (pasarlo o configurar SMTP_TO).",
                attachments, template=template_name)
        subject, html = render_html(template_name, context)
        text = body_fallback or _strip_html(html)
        return self.send(recipient, subject, text, html=html,
                         attachments=attachments)

    # ------------------------------------------------------------------ #
    def send_bulk(self, recipients: Sequence[str], subject: str, body: str,
                  html: Optional[str] = None,
                  attachments: Optional[Sequence[Attachment]] = None):
        """Envía el mismo email a varios destinatarios.

        Devuelve {sent, simulated, failed, results:[...]}.
        """
        results = []
        sent = simulated = failed = 0
        for r in recipients:
            res = self.send(r, subject, body, html=html,
                            attachments=attachments)
            results.append(res)
            st = res.get("status")
            if st == "sent":
                sent += 1
            elif st == "simulado":
                simulated += 1
            else:
                failed += 1
        return {"sent": sent, "simulated": simulated, "failed": failed,
                "results": results}

    # ------------------------------------------------------------------ #
    def send_template_bulk(self, recipients: Sequence[str],
                           template_name: str, context: dict,
                           attachments: Optional[Sequence[Attachment]] = None):
        """send_template para una lista de destinatarios."""
        results = []
        for r in recipients:
            results.append(self.send_template(
                r, template_name, dict(context), attachments=attachments))
        return {"results": results}


def _strip_html(html: str) -> str:
    """Convierte un HTML simple a texto plano para el cuerpo plain-text."""
    import re
    text = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]
