# -*- coding: utf-8 -*-
"""
whatsapp_business_adapter.py — Adaptador mock para WhatsApp Business API.

Implementa la interfaz CommunicationAdapter con respuestas simuladas.
En producción, se conectaría a la WhatsApp Business API (https://developers.facebook.com/docs/whatsapp/api/).
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


class WhatsAppBusinessAdapter(CommunicationAdapter):
    """Adaptador mock para WhatsApp Business API.

    En producción, se conectaría a la WhatsApp Cloud API
    (https://developers.facebook.com/docs/whatsapp/cloud-api/).
    Usa access_token de Meta Business Suite.
    """

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="whatsapp_business",
            api_key="MockWhatsAppAccessToken123456",
            whatsapp_business_id="1234567890",
            from_phone="+525512345678",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a WhatsApp Business.

        En producción: validar token con GET /v17.0/{phone_number_id}
        """
        logger.info("WhatsAppBusinessAdapter: conectando a WhatsApp Business (mock)...")
        self._connected = True
        logger.info("WhatsAppBusinessAdapter: conexión exitosa (mock)")
        return True

    def send_email(self, request: EmailRequest) -> Message:
        """WhatsApp Business no soporta email."""
        raise NotImplementedError(
            "WhatsAppBusinessAdapter no soporta email. Use SendGridAdapter."
        )

    def send_sms(self, request: SMSRequest) -> Message:
        """WhatsApp Business no soporta SMS directamente."""
        raise NotImplementedError(
            "WhatsAppBusinessAdapter no soporta SMS. Use TwilioAdapter."
        )

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """Envía un mensaje de WhatsApp mock.

        En producción: POST /v17.0/{phone_number_id}/messages
        """
        self._ensure_connected()
        logger.info(f"WhatsAppBusinessAdapter: enviando WhatsApp a {request.to}")

        now = datetime.now().isoformat()
        return Message(
            id=f"wamid_{_uuid.uuid4().hex[:32]}",
            to=request.to,
            from_addr=self.config.from_phone or "+525512345678",
            body=request.message,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_notification(self, request: NotificationRequest) -> Message:
        """Envía notificación por WhatsApp."""
        self._ensure_connected()
        logger.info(f"WhatsAppBusinessAdapter: enviando notificación a user {request.user_id}")

        now = datetime.now().isoformat()
        return Message(
            id=f"wa_notif_{_uuid.uuid4().hex[:16]}",
            to=request.user_id,
            from_addr=self.config.from_phone or "+525512345678",
            body=f"*{request.title}*\n\n{request.body}",
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )
