# -*- coding: utf-8 -*-
"""
messagebird_adapter.py — Stub adapter for MessageBird SMS/WhatsApp.

Provides MessageBirdAdapter with mock mode. Real implementation pending.
"""
from __future__ import annotations

import logging
import os
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


class MessageBirdAdapter(CommunicationAdapter):
    """Stub adapter for MessageBird. Falls back to mock mode."""

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="messagebird",
            api_key=os.environ.get("MESSAGEBIRD_API_KEY", ""),
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        return True

    def send_email(self, request: EmailRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(
            id=f"mb_msg_{_uuid.uuid4().hex[:16]}", to=request.to,
            from_addr=self.config.from_email or "noreply@likida.ai",
            subject=request.subject, body=request.body,
            channel=MessageChannel.EMAIL, status=MessageStatus.SENT,
            metadata=request.metadata, created_at=now, sent_at=now,
        )

    def send_sms(self, request: SMSRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(
            id=f"mb_sms_{_uuid.uuid4().hex[:16]}", to=request.to,
            from_addr=self.config.from_phone or "+525****5678",
            body=request.message, channel=MessageChannel.SMS,
            status=MessageStatus.SENT, metadata=request.metadata,
            created_at=now, sent_at=now,
        )

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(
            id=f"mb_wa_{_uuid.uuid4().hex[:16]}", to=request.to,
            from_addr=self.config.from_phone or "+525****5678",
            body=request.message, channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT, metadata=request.metadata,
            created_at=now, sent_at=now,
        )

    def send_notification(self, request: NotificationRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(
            id=f"mb_notif_{_uuid.uuid4().hex[:16]}", to=request.user_id,
            from_addr=self.config.from_email or "noreply@likida.ai",
            subject=request.title, body=f"{request.title}: {request.body}",
            channel=MessageChannel.SMS, status=MessageStatus.SENT,
            metadata=request.metadata, created_at=now, sent_at=now,
        )
