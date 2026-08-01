# -*- coding: utf-8 -*-
"""
sendgrid_adapter.py — Adaptador mock para SendGrid Email.

Implementa la interfaz CommunicationAdapter con respuestas simuladas.
En producción, se conectaría a la SendGrid API (https://docs.sendgrid.com/api-reference/).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.comunicacion.adapter import CommunicationAdapter
from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig,
    EmailRequest,
    Message,
    MessageChannel,
    MessageStatus,
    NotificationRequest,
    SMSRequest,
    WhatsAppRequest,
)

logger = logging.getLogger(__name__)


class SendGridAdapter(CommunicationAdapter):
    """Adaptador mock para SendGrid Email.

    En producción, se conectaría a la SendGrid API v3
    (https://docs.sendgrid.com/api-reference/mail-send/mail-send).
    Usa api_key para autenticación.
    """

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="sendgrid",
            api_key="faker_sendgrid_api_key_DO_NOT_USE",
            from_email="noreply@b2b-ai.com",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a SendGrid.

        En producción: validar API key con GET /v3/user/account
        """
        logger.info("SendGridAdapter: conectando a SendGrid (mock)...")
        self._connected = True
        logger.info("SendGridAdapter: conexión exitosa (mock)")
        return True

    def send_email(self, request: EmailRequest) -> Message:
        """Envía un email mock por SendGrid.

        En producción: POST /v3/mail/send
        """
        self._ensure_connected()
        logger.info(f"SendGridAdapter: enviando email a {request.to}")

        now = datetime.now().isoformat()
        return Message(
            id=f"sg_msg_{_uuid.uuid4().hex[:16]}",
            to=request.to,
            from_addr=self.config.from_email or "noreply@b2b-ai.com",
            subject=request.subject,
            body=request.body,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_sms(self, request: SMSRequest) -> Message:
        """SendGrid no soporta SMS directamente. Delega a Twilio."""
        raise NotImplementedError("SendGridAdapter no soporta SMS. Use TwilioAdapter.")

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """SendGrid no soporta WhatsApp. Delega a WhatsAppBusinessAdapter."""
        raise NotImplementedError("SendGridAdapter no soporta WhatsApp. Use WhatsAppBusinessAdapter.")

    def send_notification(self, request: NotificationRequest) -> Message:
        """Envía una notificación por email via SendGrid.

        En producción: puede usar SendGrid Templates o Dynamic Templates.
        """
        self._ensure_connected()
        logger.info(f"SendGridAdapter: enviando notificación a user {request.user_id}")

        now = datetime.now().isoformat()
        return Message(
            id=f"sg_notif_{_uuid.uuid4().hex[:16]}",
            to=request.user_id,
            from_addr=self.config.from_email or "noreply@b2b-ai.com",
            subject=request.title,
            body=request.body,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )
