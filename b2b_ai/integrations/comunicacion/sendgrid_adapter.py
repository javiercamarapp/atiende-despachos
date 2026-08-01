# -*- coding: utf-8 -*-
"""
sendgrid_adapter.py — Real adapter for SendGrid Email.

Provides SendGridAdapter with actual API calls to SendGrid v3.
Falls back to mock if SENDGRID_API_KEY is not set.
"""
from __future__ import annotations

import json
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


class SendGridAdapter(CommunicationAdapter):
    """Real adapter for SendGrid Email.

    Connects to SendGrid API v3 using the official sendgrid-python library.
    Requires SENDGRID_API_KEY environment variable.
    """

    def __init__(self, config: Optional[CommunicationConfig] = None):
        config = config or CommunicationConfig(
            provider="sendgrid",
            api_key=os.environ.get("SENDGRID_API_KEY", ""),
            from_email=os.environ.get("B2B_SMTP_FROM", "noreply@likida.ai"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to SendGrid API.

        Uses SENDGRID_API_KEY from environment or config.
        """
        api_key = (
            (credentials or {}).get("api_key")
            or self.config.api_key
            or os.environ.get("SENDGRID_API_KEY", "")
        )

        if not api_key:
            logger.warning("SendGridAdapter: no API key — running in MOCK mode")
            self._connected = True
            self._client = None
            return True

        try:
            from sendgrid import SendGridAPIClient
            self._client = SendGridAPIClient(api_key=api_key)
            self._connected = True
            logger.info("SendGridAdapter: connected to SendGrid API")
            return True
        except ImportError:
            logger.warning("SendGridAdapter: sendgrid package not installed — MOCK mode")
            self._connected = True
            self._client = None
            return True
        except Exception as e:
            logger.error(f"SendGridAdapter: connection failed: {e}")
            self._connected = True
            self._client = None
            return True

    def send_email(self, request: EmailRequest) -> Message:
        """Send email via SendGrid API."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        from_email = self.config.from_email or "noreply@likida.ai"

        if self._client:
            try:
                from sendgrid.helpers.mail import Mail, To

                mail = Mail(
                    from_email=from_email,
                    to_emails=request.to,
                    subject=request.subject,
                    html_content=request.body if request.is_html else None,
                    plain_text_content=request.body if not request.is_html else None,
                )
                response = self._client.send(mail)
                status_code = response.status_code

                return Message(
                    id=f"sg_msg_{_uuid.uuid4().hex[:16]}",
                    to=request.to,
                    from_addr=from_email,
                    subject=request.subject,
                    body=request.body,
                    channel=MessageChannel.EMAIL,
                    status=MessageStatus.SENT if 200 <= status_code < 300 else MessageStatus.FAILED,
                    metadata={**request.metadata, "status_code": status_code},
                    created_at=now,
                    sent_at=now,
                )
            except Exception as e:
                logger.error(f"SendGridAdapter: send_email failed: {e}")
                return Message(
                    id=f"sg_msg_{_uuid.uuid4().hex[:16]}",
                    to=request.to,
                    from_addr=from_email,
                    subject=request.subject,
                    body=request.body,
                    channel=MessageChannel.EMAIL,
                    status=MessageStatus.FAILED,
                    metadata={**request.metadata, "error": str(e)},
                    created_at=now,
                )

        # Mock fallback
        return Message(
            id=f"sg_msg_{_uuid.uuid4().hex[:16]}",
            to=request.to,
            from_addr=from_email,
            subject=request.subject,
            body=request.body,
            channel=MessageChannel.EMAIL,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )

    def send_sms(self, request: SMSRequest) -> Message:
        """SendGrid does not support SMS directly."""
        raise NotImplementedError("SendGridAdapter no soporta SMS. Use TwilioAdapter.")

    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """SendGrid does not support WhatsApp."""
        raise NotImplementedError("SendGridAdapter no soporta WhatsApp. Use WhatsAppBusinessAdapter.")

    def send_notification(self, request: NotificationRequest) -> Message:
        """Send notification via email through SendGrid."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        from_email = self.config.from_email or "noreply@likida.ai"

        if self._client:
            try:
                from sendgrid.helpers.mail import Mail

                body = f"{request.title}\n\n{request.body}"
                mail = Mail(
                    from_email=from_email,
                    to_emails=request.user_id,
                    subject=request.title,
                    plain_text_content=body,
                )
                response = self._client.send(mail)
                status_code = response.status_code

                return Message(
                    id=f"sg_notif_{_uuid.uuid4().hex[:16]}",
                    to=request.user_id,
                    from_addr=from_email,
                    subject=request.title,
                    body=body,
                    channel=MessageChannel.EMAIL,
                    status=MessageStatus.SENT if 200 <= status_code < 300 else MessageStatus.FAILED,
                    metadata={**request.metadata, "status_code": status_code},
                    created_at=now,
                    sent_at=now,
                )
            except Exception as e:
                logger.error(f"SendGridAdapter: send_notification failed: {e}")

        return Message(
            id=f"sg_notif_{_uuid.uuid4().hex[:16]}",
            to=request.user_id,
            from_addr=from_email,
            subject=request.title,
            body=f"{request.title}: {request.body}",
            channel=MessageChannel.EMAIL,
            status=MessageStatus.SENT,
            metadata=request.metadata,
            created_at=now,
            sent_at=now,
        )
