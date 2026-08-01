# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de comunicación (Email, SMS, WhatsApp).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageChannel(str, Enum):
    """Canales de comunicación."""
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"


class MessageStatus(str, Enum):
    """Estado de un mensaje."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class NotificationPriority(str, Enum):
    """Prioridad de notificación."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class CommunicationConfig(BaseModel):
    """Configuración del adaptador de comunicación."""
    provider: str = Field(..., description="Proveedor (sendgrid, twilio, whatsapp_business)")
    api_key: str = Field(default="", description="API key del proveedor")
    api_secret: str = Field(default="", description="API secret (si aplica)")
    from_email: Optional[str] = Field(default=None, description="Email remitente")
    from_phone: Optional[str] = Field(default=None, description="Teléfono remitente")
    whatsapp_business_id: Optional[str] = Field(default=None, description="WhatsApp Business ID")
    timeout: int = Field(default=30, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class EmailAttachment(BaseModel):
    """Adjunto de email."""
    filename: str = Field(..., description="Nombre del archivo")
    content_type: str = Field(default="application/octet-stream", description="MIME type")
    size: int = Field(default=0, description="Tamaño en bytes")
    content: Optional[str] = Field(default=None, description="Contenido base64")


class Message(BaseModel):
    """Mensaje enviado."""
    id: str = Field(default="", description="ID del mensaje")
    to: str = Field(..., description="Destinatario")
    from_addr: str = Field(default="", alias="from", description="Remitente")
    subject: Optional[str] = Field(default=None, description="Asunto (email)")
    body: str = Field(default="", description="Cuerpo del mensaje")
    channel: MessageChannel = Field(default=MessageChannel.EMAIL, description="Canal")
    status: MessageStatus = Field(default=MessageStatus.PENDING, description="Estado")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")
    created_at: str = Field(default="", description="Fecha de creación")
    sent_at: Optional[str] = Field(default=None, description="Fecha de envío")

    model_config = {"populate_by_name": True}


class EmailRequest(BaseModel):
    """Solicitud de envío de email."""
    to: str = Field(..., description="Destinatario")
    subject: str = Field(..., description="Asunto")
    body: str = Field(..., description="Cuerpo (HTML o plain text)")
    is_html: bool = Field(default=True, description="Si el body es HTML")
    attachments: List[EmailAttachment] = Field(default_factory=list, description="Adjuntos")
    cc: Optional[str] = Field(default=None, description="CC")
    bcc: Optional[str] = Field(default=None, description="BCC")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class SMSRequest(BaseModel):
    """Solicitud de envío de SMS."""
    to: str = Field(..., description="Teléfono destino (+52...)")
    message: str = Field(..., description="Mensaje (max 1600 chars)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class WhatsAppRequest(BaseModel):
    """Solicitud de envío de WhatsApp."""
    to: str = Field(..., description="Teléfono destino (+52...)")
    message: str = Field(..., description="Mensaje")
    template_name: Optional[str] = Field(default=None, description="Template name (para plantillas)")
    template_params: Optional[Dict[str, str]] = Field(default=None, description="Parámetros del template")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class NotificationRequest(BaseModel):
    """Solicitud de notificación multi-canal."""
    user_id: str = Field(..., description="ID del usuario destino")
    title: str = Field(..., description="Título de la notificación")
    body: str = Field(..., description="Cuerpo de la notificación")
    channel: MessageChannel = Field(default=MessageChannel.EMAIL, description="Canal")
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL, description="Prioridad")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")
