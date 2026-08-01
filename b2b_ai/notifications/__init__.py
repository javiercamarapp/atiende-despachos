# -*- coding: utf-8 -*-
"""Notificaciones: email (SMTP), WhatsApp (mock + Business Cloud API),
plantillas y scheduler con cola/reintentos/rate limiting."""
from b2b_ai.notifications.templates import (render, TEMPLATES, render_html,
                                            html_subject, html_template_path)
from b2b_ai.notifications.sender import EmailSender
from b2b_ai.notifications.email_provider import EmailProvider
from b2b_ai.notifications.smtp_provider import AsyncSMTPProvider
from b2b_ai.notifications.whatsapp import (MockWhatsApp, WhatsAppBusiness)
from b2b_ai.notifications.scheduler import (NotificationScheduler, EmailScheduler,
                                            RateLimiter, Message, EmailMessage)

__all__ = [
    "render", "TEMPLATES", "render_html", "html_subject", "html_template_path",
    "EmailSender", "EmailProvider", "AsyncSMTPProvider",
    "MockWhatsApp", "WhatsAppBusiness",
    "NotificationScheduler", "EmailScheduler", "RateLimiter", "Message",
    "EmailMessage",
]
