# -*- coding: utf-8 -*-
"""Módulo de integración de Comunicación — Email, SMS, WhatsApp."""

from b2b_ai.integrations.comunicacion.adapter import CommunicationAdapter, CommunicationAdapterError
from b2b_ai.integrations.comunicacion.sendgrid_adapter import SendGridAdapter
from b2b_ai.integrations.comunicacion.twilio_adapter import TwilioAdapter
from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig,
    EmailAttachment,
    EmailRequest,
    Message,
    MessageChannel,
    MessageStatus,
    NotificationPriority,
    NotificationRequest,
    SMSRequest,
    WhatsAppRequest,
)

__all__ = [
    "CommunicationAdapter",
    "CommunicationAdapterError",
    "SendGridAdapter",
    "TwilioAdapter",
    "CommunicationConfig",
    "EmailAttachment",
    "EmailRequest",
    "Message",
    "MessageChannel",
    "MessageStatus",
    "NotificationPriority",
    "NotificationRequest",
    "SMSRequest",
    "WhatsAppRequest",
]
