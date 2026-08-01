# -*- coding: utf-8 -*-
"""
aws_ses_adapter.py — Adaptador mock para AWS SES (email).
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


class AWSSesAdapter(CommunicationAdapter):
    """Adaptador mock para AWS SES (email)."""

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(provider="aws_ses", api_key="mock_aws_key")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("AWSSesAdapter: conexión exitosa (mock)")
        return True

    def send_email(self, request: EmailRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(id=f"ses_{_uuid.uuid4().hex[:12]}", to=request.to,
                       from_addr=request.metadata.get("from", "noreply@likida.ai"),
                       subject=request.subject, body=request.body, channel=MessageChannel.EMAIL,
                       status=MessageStatus.SENT, metadata=request.metadata, created_at=now, sent_at=now)

    def send_sms(self, request: SMSRequest) -> Message:
        self._ensure_connected()
        raise NotImplementedError("AWS SES no soporta SMS")

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        self._ensure_connected()
        raise NotImplementedError("AWS SES no soporta WhatsApp")

    def send_notification(self, request: NotificationRequest) -> Message:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return Message(id=f"ses_n_{_uuid.uuid4().hex[:12]}", to=request.user_id,
                       from_addr="notify@likida.ai", subject=request.title,
                       body=request.body, channel=MessageChannel.EMAIL,
                       status=MessageStatus.SENT, created_at=now, sent_at=now)
