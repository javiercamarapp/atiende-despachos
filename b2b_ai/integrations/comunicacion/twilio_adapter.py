# -*- coding: utf-8 -*-
"""
twilio_adapter.py — Adaptador mock para Twilio SMS/WhatsApp.

Implementa la interfaz CommunicationAdapter con respuestas simuladas.
En producción, se conectaría a la Twilio API (https://www.twilio.com/docs/sms/api).
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


class TwilioAdapter(CommunicationAdapter):
    """Adaptador mock para Twilio SMS/WhatsApp.

    En producción, se conectaría a la Twilio REST API
    (https://www.twilio.com/docs/messaging/api/message-resource).
    Usa account_sid + auth_token para autenticación.
    """

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="twilio",
            api_key="AC_faker_twilio_sid_DO_NOT_USE",
            api_secret="faker_twilio_auth_token_DO_NOT_USE",
            from_phone="+525512345678",
            from_email="sms@b2b-ai.com",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Twilio.

        En producción: validar con GET /v2010-04-01/Accounts/{sid}.json
        """
        logger.info("TwilioAdapter: conectando a Twilio (mock)...")
        self._connected = True
        logger.info("TwilioAdapter: conexión exitosa (mock)")
        return True

    def send_email(self, request: EmailRequest) -> Message:
        """Twilio SendGrid (separate product) o error."""
        raise NotImplementedError(
            "TwilioAdapter no soporta email directamente. Use SendGridAdapter."
        )

    def send_sms(self, request: SMSRequest) -> Message:
        """Envía un SMS mock por Twilio.

        En producción: POST /v2010-04-01/Accounts/{sid}/Messages.json
        """
        self._ensure_connected()
        logger.info(f"TwilioAdapter: enviando SMS a {request.to}")

        now = datetime.now().isoformat()
        return Message(
            id=f"SM{_uuid.uuid4().hex[:32].upper()}",
            to=request.to,
            from_addr=self.config.from_phone or "+525512345678",
            body=request.message,
            channel=MessageChannel.SMS,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """Envía un mensaje de WhatsApp mock por Twilio.

        En producción: POST /v2010-04-01/Accounts/{sid}/Messages.json
        con From: whatsapp:+14155238886
        """
        self._ensure_connected()
        logger.info(f"TwilioAdapter: enviando WhatsApp a {request.to}")

        now = datetime.now().isoformat()
        return Message(
            id=f"WA{_uuid.uuid4().hex[:32].upper()}",
            to=request.to,
            from_addr="whatsapp:+14155238886",
            body=request.body if hasattr(request, 'body') else request.message,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_notification(self, request: NotificationRequest) -> Message:
        """Envía notificación por SMS via Twilio."""
        self._ensure_connected()
        logger.info(f"TwilioAdapter: enviando notificación a user {request.user_id}")

        now = datetime.now().isoformat()
        return Message(
            id=f"tw_notif_{_uuid.uuid4().hex[:16]}",
            to=request.user_id,
            from_addr=self.config.from_phone or "+525512345678",
            body=f"{request.title}: {request.body}",
            channel=MessageChannel.SMS,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )
