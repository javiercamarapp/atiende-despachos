# -*- coding: utf-8 -*-
"""
whatsapp.py — Integración con la WhatsApp Business Cloud API (Meta) + mock.

Clases:
  * MockWhatsApp      — mock en memoria para tests / demos (sin red).
  * WhatsAppBusiness  — cliente de producción. Llama a la Cloud API de Meta:

        POST https://graph.facebook.com/v19.0/<phone_number_id>/messages
        Authorization: Bearer <token>

    Modo seguro por defecto: si no hay credenciales configuradas
    (B2B_WHATSAPP_TOKEN + B2B_WHATSAPP_PHONE_NUMBER_ID), NO se envía nada real; el
    mensaje se registra como "simulado" y se devuelve al llamador. Cuando haya
    credenciales se hace la llamada HTTP real.

    El transporte HTTP es inyectable (`post=`), de modo que los tests pueden
    mockear la llamada a Meta sin tocar la red.

Nota fiscal (de 04-leyes-fiscales.md): las notificaciones informan; la decisión
fiscal es humana y las plantillas lo recuerdan explícitamente.
"""
from __future__ import annotations

import os
import uuid
from typing import Callable, Optional

from b2b_ai.notifications.templates import render

_WHATSAPP_API_URL = "https://graph.facebook.com/v19.0"
# Límites de la Cloud API (por defecto) — se pueden sobreescribir por env.
_DEFAULT_MSG_PER_SECOND = 80
_DEFAULT_MAX_ATTEMPTS = 3


def _recipient_from(data: dict) -> str:
    """Extrae el destinatario (teléfono E.164) de un dict de datos.

    Acepta las claves `phone`, `to` o `telefono`. Lanza ValueError si falta.
    """
    for key in ("phone", "to", "telefono"):
        value = data.get(key)
        if value:
            return str(value)
    raise ValueError(
        "Falta el destinatario en los datos. Use 'phone' o 'to' (E.164, "
        "p. ej. +5215512345678).")


class MockWhatsApp:
    """Mock de WhatsApp para testing / demos: registra en memoria."""

    backend = "WhatsApp (mock)"

    def __init__(self):
        self.messages = []
        self.phones = {}  # contacto -> número

    def register_phone(self, contact, number):
        self.phones[contact] = number

    def send_message(self, to_number, text, template=None,
                     template_name=None):
        # `template_name` se mantiene por compatibilidad con código previo;
        # la interfaz canónica es `template=` (igual que WhatsAppBusiness).
        if template is None:
            template = template_name
        msg_id = "WA-" + uuid.uuid4().hex[:12]
        record = {
            "id": msg_id,
            "to": to_number,
            "text": text,
            "template": template,
            "status": "sent",
        }
        self.messages.append(record)
        return record

    def send_to_contact(self, contact, text, template=None,
                        template_name=None):
        number = self.phones.get(contact)
        if not number:
            return {"status": "error", "message": f"Sin número para {contact}"}
        if template is None:
            template = template_name
        return self.send_message(number, text, template)

    def health(self):
        return {"ok": True, "backend": self.backend,
                "detail": "Mock WhatsApp operativo (sin conexión Meta)."}


class WhatsAppBusiness:
    """Cliente de producción de la WhatsApp Business Cloud API (Meta).

    Uso:
        wa = WhatsAppBusiness(token="...", phone_number_id="1234567890")
        wa.send_message("+5215512345678", "Hola")

    Sin credenciales, `send_message` devuelve un registro con status
    "simulado" (patrón idéntico al de EmailSender). Inyecta `post=` para
    probar sin red.
    """

    backend = "WhatsApp Business Cloud API (Meta)"

    def __init__(
        self,
        token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        base_url: str = _WHATSAPP_API_URL,
        post: Optional[Callable] = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ):
        self.token = token or os.environ.get("B2B_WHATSAPP_TOKEN") or ""
        self.phone_number_id = (
            phone_number_id or os.environ.get("B2B_WHATSAPP_PHONE_NUMBER_ID") or ""
        )
        self.base_url = (base_url or os.environ.get("B2B_WHATSAPP_API_URL")
                         or _WHATSAPP_API_URL)
        self._post = post  # transporte inyectable (tests)
        self.max_attempts = int(max_attempts)
        self.sent = []  # historial en memoria (para tests / modo simulado)

    # ------------------------------------------------------------------ #
    # Estado de configuración
    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        """True si hay token y phone_number_id (posible envío real)."""
        return bool(self.token and self.phone_number_id)

    def health(self) -> dict:
        return {
            "ok": True,
            "backend": self.backend,
            "configured": self.configured,
            "detail": ("WhatsApp operativo (conexión Meta)."
                       if self.configured
                       else "WhatsApp sin credenciales; modo simulado."),
        }

    # ------------------------------------------------------------------ #
    # Envío de nivel bajo
    # ------------------------------------------------------------------ #
    def _http_post(self, url: str, payload: dict) -> dict:
        """Hace la llamada HTTP (transport real o inyectado)."""
        headers = {"Authorization": f"Bearer {self.token}",
                   "Content-Type": "application/json"}
        if self._post is not None:
            resp = self._post(url, json=payload, headers=headers)
        else:
            import requests
            resp = requests.post(url, json=payload, headers=headers,
                                 timeout=15)
        if hasattr(resp, "json"):
            return resp.json()
        return {"status_code": getattr(resp, "status_code", None)}

    def send_message(self, phone: str, message: str,
                     template: Optional[str] = None) -> dict:
        """Envía un mensaje de texto (o simula si no hay credenciales).

        Args:
            phone:     teléfono destino en formato E.164 (p. ej. +521...).
            message:   cuerpo del mensaje.
            template:  nombre de plantilla (referencia informativa; el body
                       ya viene renderizado por el llamador).

        Returns:
            dict con {status, to, text, template, id, message}.
            status ∈ {"sent", "simulado", "error"}.
        """
        if not self.configured:
            record = {
                "status": "simulado",
                "to": phone,
                "text": message,
                "template": template,
                "id": None,
                "message": ("WhatsApp no configurado; mensaje simulado. "
                            "Configurar B2B_WHATSAPP_TOKEN y "
                            "B2B_WHATSAPP_PHONE_NUMBER_ID para envío real."),
            }
            self.sent.append(record)
            return record

        url = f"{self.base_url}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"body": message, "preview_url": False},
        }
        attempt = 0
        last_error = None
        while attempt < self.max_attempts:
            attempt += 1
            try:
                body = self._http_post(url, payload)
                # Meta responde 200 con un JSON {"messages":[{"id": ...}]}.
                if body and body.get("messages"):
                    msg_id = body["messages"][0].get("id")
                    record = {"status": "sent", "to": phone, "text": message,
                              "template": template, "id": msg_id,
                              "message": "Enviado por WhatsApp Cloud API."}
                    self.sent.append(record)
                    return record
                # Respuesta de error de la API (HTTP 4xx/5xx con error body).
                err = (body or {}).get("error", {})
                last_error = err.get("message", body)
                if attempt >= self.max_attempts:
                    break
            except Exception as e:  # noqa: BLE001 — red / transporte
                last_error = f"{type(e).__name__}: {e}"
                if attempt >= self.max_attempts:
                    break

        record = {"status": "error", "to": phone, "text": message,
                  "template": template, "id": None,
                  "message": f"Fallo WhatsApp tras {attempt} intento(s): "
                             f"{last_error}"}
        self.sent.append(record)
        return record

    # ------------------------------------------------------------------ #
    # Envíos de alto nivel (plantillas del negocio)
    # ------------------------------------------------------------------ #
    def send_invoice_notification(self, invoice_data: dict) -> dict:
        """Notifica una factura procesada (template invoice_processed)."""
        phone = _recipient_from(invoice_data)
        ctx = {
            "nombre": invoice_data.get("nombre", "Cliente"),
            "folio": invoice_data.get("folio", ""),
            "emisor": invoice_data.get("emisor", ""),
            "monto": invoice_data.get("monto", ""),
            "categoria": invoice_data.get("categoria", ""),
            "razon": invoice_data.get("razon", ""),
            "uuid": invoice_data.get("uuid", ""),
            "revision": invoice_data.get("revision", ""),
        }
        _, body = render("invoice_processed", ctx)
        return self.send_message(phone, body, template="invoice_processed")

    def send_approval_request(self, approval_data: dict) -> dict:
        """Pide aprobación para una factura sobre el umbral (requires_approval)."""
        phone = _recipient_from(approval_data)
        ctx = {
            "nombre": approval_data.get("nombre", "Cliente"),
            "folio": approval_data.get("folio", ""),
            "emisor": approval_data.get("emisor", ""),
            "monto": approval_data.get("monto", ""),
            "ref": approval_data.get("ref", ""),
        }
        _, body = render("requires_approval", ctx)
        return self.send_message(phone, body, template="requires_approval")

    def send_daily_summary(self, summary_data: dict) -> dict:
        """Envía el resumen diario de actividad (template daily_summary)."""
        phone = _recipient_from(summary_data)
        ctx = {
            "nombre": summary_data.get("nombre", "Cliente"),
            "fecha": summary_data.get("fecha", ""),
            "facturas": summary_data.get("facturas", "0"),
            "monto_total": summary_data.get("monto_total", "0"),
            "pendientes": summary_data.get("pendientes", "0"),
            "anomalias": summary_data.get("anomalias", "0"),
        }
        _, body = render("daily_summary", ctx)
        return self.send_message(phone, body, template="daily_summary")

    def send_anomaly_alert(self, anomaly_data: dict) -> dict:
        """Alerta de anomalía detectada (template anomaly_alert)."""
        phone = _recipient_from(anomaly_data)
        ctx = {
            "nombre": anomaly_data.get("nombre", "Cliente"),
            "documento": anomaly_data.get("documento", ""),
            "tipo": anomaly_data.get("tipo", "anomalía"),
            "detalle": anomaly_data.get("detalle", ""),
        }
        _, body = render("anomaly_alert", ctx)
        return self.send_message(phone, body, template="anomaly_alert")
