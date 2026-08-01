# -*- coding: utf-8 -*-
"""
vonage_adapter.py — Adaptador mock para Vonage (SMS).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.comunicacion.adapter import CommunicationAdapter
from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig, EmailRequest, Message, MessageChannel, MessageStatus,
    NotificationRequest, SMSRequest, WhatsAppRequest,
)

logger = logging.getLogger(__name__)


class VonageAdapter(CommunicationAdapter):
    """Adaptador mock para Vonage (SMS)."""

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(provider="vonage", api_key="mock_vonage_key")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("VonageAdapter: conexión exitosa (mock)")
        return True

    def send_email(self, request: EmailRequest) -> Message:
        self._ensure_connected()
        raise NotImplementedError("Vonage no soporta email")

    def send_sms(self, request: SMSRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(id=f"vng_{_uuid.uuid4().hex[:12]}", to=request.to,
                       from_addr=self.config.from_phone or "+525512345678",
                       body=request.message, channel=MessageChannel.SMS,
                       status=MessageStatus.SENT, metadata=request.metadata,
                       created_at=now, sent_at=now)

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        self._ensure_connected()
        raise NotImplementedError("Vonage no soporta WhatsApp")

    def send_notification(self, request: NotificationRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(id=f"vng_n_{_uuid.uuid4().hex[:12]}", to=request.user_id,
                       from_addr=self.config.from_phone or "+525512345678",
                       body=request.body, channel=MessageChannel.SMS,
                       status=MessageStatus.SENT, created_at=now, sent_at=now)
