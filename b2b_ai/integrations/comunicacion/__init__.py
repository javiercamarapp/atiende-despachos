"""Módulo de integración de Comunicación — Email, SMS, WhatsApp."""
from b2b_ai.integrations.comunicacion.adapter import CommunicationAdapter, CommunicationAdapterError
from b2b_ai.integrations.comunicacion.sendgrid_adapter import SendGridAdapter
from b2b_ai.integrations.comunicacion.twilio_adapter import TwilioAdapter
from b2b_ai.integrations.comunicacion.mailgun_adapter import MailgunAdapter
from b2b_ai.integrations.comunicacion.aws_ses_adapter import AWSSesAdapter
from b2b_ai.integrations.comunicacion.vonage_adapter import VonageAdapter
from b2b_ai.integrations.comunicacion.messagebird_adapter import MessageBirdAdapter
from b2b_ai.integrations.comunicacion.whatsapp_business_adapter import WhatsAppBusinessAdapter
from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig, EmailAttachment, EmailRequest, Message, MessageChannel,
    MessageStatus, NotificationPriority, NotificationRequest, SMSRequest, WhatsAppRequest,
)

__all__ = [
    "CommunicationAdapter", "CommunicationAdapterError",
    "SendGridAdapter", "TwilioAdapter", "MailgunAdapter", "AWSSesAdapter",
    "VonageAdapter", "MessageBirdAdapter", "WhatsAppBusinessAdapter",
    "CommunicationConfig", "EmailAttachment", "EmailRequest", "Message",
    "MessageChannel", "MessageStatus", "NotificationPriority",
    "NotificationRequest", "SMSRequest", "WhatsAppRequest",
]
