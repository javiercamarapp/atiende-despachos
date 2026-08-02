# -*- coding: utf-8 -*-
"""
sender.py — Envío de email por SMTP.

Modo seguro por defecto: si no hay credenciales SMTP configuradas, NO se envía
nada real; el mensaje se registra como "simulado" y se devuelve al llamador
(para persistir en la tabla notifications). Cuando haya credenciales, se
configura `host/port/user/password` y se envía por SMTP_SSL/SMTP.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailSender:
    def __init__(self, host=None, port=465, user=None, password=None,
                 from_addr=os.environ.get("B2B_DEFAULT_EMAIL", ""), use_ssl=True):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.use_ssl = use_ssl
        self.sent = []  # historial en memoria (para tests / modo simulado)

    @property
    def configured(self):
        return bool(self.host and self.user and self.password)

    def send(self, to_addr, subject, body):
        """Envía (o simula si no hay credenciales). Devuelve dict de resultado."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to_addr
        msg.attach(MIMEText(body, "plain", "utf-8"))

        record = {"to": to_addr, "subject": subject, "status": "sent"}
        if not self.configured:
            record["status"] = "simulado"
            record["message"] = ("SMTP no configurado; email simulado. "
                                 "Configurar host/user/password para envío real.")
            self.sent.append(record)
            return record

        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port,
                                          context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(self.host, self.port)
                server.starttls(context=ssl.create_default_context())
            server.login(self.user, self.password)
            server.sendmail(self.from_addr, [to_addr], msg.as_string())
            server.quit()
            record["message"] = "Email enviado por SMTP."
            self.sent.append(record)
            return record
        except Exception as e:
            record["status"] = "error"
            record["message"] = f"Fallo SMTP: {e}"
            self.sent.append(record)
            return record
