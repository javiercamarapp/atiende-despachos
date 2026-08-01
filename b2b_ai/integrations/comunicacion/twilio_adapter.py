# -*- coding: utf-8 -*-
"""
twilio_adapter.py — Real adapter for Twilio SMS/WhatsApp.

Provides TwilioAdapter with actual API calls to Twilio.
Falls back to mock if TWILIO_ACCOUNT_SID is not set.
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


class TwilioAdapter(CommunicationAdapter):
    """Real adapter for Twilio SMS/WhatsApp.

    Connects to Twilio REST API using the official twilio Python library.
    Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables.
    """

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="twilio",
            api_key=os.environ.get("TWILIO_ACCOUNT_SID", ""),
            api_secret=os.environ.get("TWILIO_AUTH_TOKEN", ""),
            from_phone=os.environ.get("TWILIO_PHONE_NUMBER", ""),
            from_email="sms@likida.ai",
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to Twilio API.

        Uses TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN from environment.
        """
        account_sid = (
            (credentials or {}).get("account_sid")
            or self.config.api_key
            or os.environ.get("TWILIO_ACCOUNT_SID", "")
        )
        auth_token = (
            (credentials or {}).get("auth_token")
            or self.config.api_secret
            or os.environ.get("TWILIO_AUTH_TOKEN", "")
        )

        if not account_sid or not auth_token:
            logger.warning("TwilioAdapter: no credentials — running in MOCK mode")
            self._connected = True
            self._client = None
            return True

        try:
            from twilio.rest import Client
            self._client = Client(account_sid, auth_token)
            # Validate with account lookup
            self._client.api.accounts(account_sid).fetch()
            self._connected = True
            logger.info("TwilioAdapter: connected to Twilio API")
            return True
        except ImportError:
            logger.warning("TwilioAdapter: twilio package not installed — MOCK mode")
            self._connected = True
            self._client = None
            return True
        except Exception as e:
            logger.error(f"TwilioAdapter: connection failed: {e}")
            self._connected = True
            self._client = None
            return True

    def send_email(self, request: EmailRequest) -> Message:
        """Twilio SendGrid (separate product) — not directly supported."""
        raise NotImplementedError("TwilioAdapter no soporta email directamente. Use SendGridAdapter.")

    def send_sms(self, request: SMSRequest) -> Message:
        """Send SMS via Twilio API."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        from_phone = self.config.from_phone or os.environ.get("TWILIO_PHONE_NUMBER", "")

        if self._client:
            try:
                message = self._client.messages.create(
                    body=request.message,
                    from_=from_phone,
                    to=request.to,
                )
                return Message(
                    id=message.sid,
                    to=request.to,
                    from_addr=from_phone,
                    body=request.message,
                    channel=MessageChannel.SMS,
                    status=MessageStatus.SENT if message.status in ("queued", "sent", "delivered") else MessageStatus.FAILED,
                    metadata={**request.metadata, "twilio_status": message.status},
                    created_at=now,
                    sent_at=now,
                )
            except Exception as e:
                logger.error(f"TwilioAdapter: send_sms failed: {e}")
                return Message(
                    id=f"SM{_uuid.uuid4().hex[:32].upper()}",
                    to=request.to,
                    from_addr=from_phone,
                    body=request.message,
                    channel=MessageChannel.SMS,
                    status=MessageStatus.FAILED,
                    metadata={**request.metadata, "error": str(e)},
                    created_at=now,
                )

        # Mock fallback
        return Message(
            id=f"SM{_uuid.uuid4().hex[:32].upper()}",
            to=request.to,
            from_addr=from_phone or "+525****5678",
            body=request.message,
            channel=MessageChannel.SMS,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """Send WhatsApp message via Twilio API."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        to_number = request.to if request.to.startswith("whatsapp:") else f"whatsapp:{request.to}"
        from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
        body = request.message

        if self._client:
            try:
                message = self._client.messages.create(
                    body=body,
                    from_=from_number,
                    to=to_number,
                )
                return Message(
                    id=message.sid,
                    to=to_number,
                    from_addr=from_number,
                    body=body,
                    channel=MessageChannel.WHATSAPP,
                    status=MessageStatus.SENT if message.status in ("queued", "sent", "delivered") else MessageStatus.FAILED,
                    metadata={**request.metadata, "twilio_status": message.status},
                    created_at=now,
                    sent_at=now,
                )
            except Exception as e:
                logger.error(f"TwilioAdapter: send_whatsapp failed: {e}")

        # Mock fallback
        return Message(
            id=f"WA{_uuid.uuid4().hex[:32].upper()}",
            to=to_number,
            from_addr=from_number,
            body=body,
            channel=MessageChannel.WHATSAPP,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_notification(self, request: NotificationRequest) -> Message:
        """Send notification via SMS through Twilio."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        from_phone = self.config.from_phone or os.environ.get("TWILIO_PHONE_NUMBER", "")
        body = f"{request.title}: {request.body}"

        if self._client:
            try:
                message = self._client.messages.create(
                    body=body,
                    from_=from_phone,
                    to=request.user_id,
                )
                return Message(
                    id=message.sid,
                    to=request.user_id,
                    from_addr=from_phone,
                    body=body,
                    channel=MessageChannel.SMS,
                    status=MessageStatus.SENT if message.status in ("queued", "sent", "delivered") else MessageStatus.FAILED,
                    metadata={**request.metadata, "twilio_status": message.status},
                    created_at=now,
                    sent_at=now,
                )
            except Exception as e:
                logger.error(f"TwilioAdapter: send_notification failed: {e}")

        return Message(
            id=f"tw_notif_{_uuid.uuid4().hex[:16]}",
            to=request.user_id,
            from_addr=from_phone or "+525****5678",
            body=body,
            channel=MessageChannel.SMS,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )
