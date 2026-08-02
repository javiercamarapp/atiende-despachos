# -*- coding: utf-8 -*-
"""
models.py — Esquemas Pydantic del módulo de Webhooks.

Notificación de eventos clave vía HTTP callbacks con firma HMAC-SHA256.

Modelos:
  - WebhookEventType        : eventos que el sistema publica
  - WebhookDeliveryStatus   : ciclo de vida de una entrega
  - WebhookSubscription     : endpoint que un cliente registra para recibir eventos
  - WebhookEvent            : evento publicado con su payload
  - WebhookDelivery         : intento(s) de entrega de un evento a una suscripción
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Eventos soportados
# ---------------------------------------------------------------------------

class WebhookEventType(str, Enum):
    """Eventos que el sistema notifica a los suscriptores."""
    CFDI_PROCESSED = "cfdi.processed"
    CFDI_BATCH_COMPLETED = "cfdi.batch.completed"
    DECLARATION_READY = "declaration.ready"
    ALERT_EXPIRING = "alert.expiring"
    RECONCILIATION_COMPLETED = "reconciliation.completed"


class WebhookDeliveryStatus(str, Enum):
    """Ciclo de vida de una entrega de webhook."""
    PENDING = "pending"          # esperando primer intento
    DELIVERED = "delivered"      # el endpoint respondió 2xx
    FAILED = "failed"            # agotó los reintentos
    RATE_LIMITED = "rate_limited"  # no se envió por límite de tasa


# ---------------------------------------------------------------------------
# WebhookSubscription — suscripción a eventos
# ---------------------------------------------------------------------------

class WebhookSubscription(BaseModel):
    """Endpoint registrado por un cliente para recibir eventos.

    Campos:
      - id          : UUID de la suscripción
      - url         : endpoint HTTPS que recibe los POST
      - secret      : secreto para firmar el payload (HMAC-SHA256)
      - event_types : tipos de evento que se desea recibir (vacío = todos)
      - active      : si está habilitada
      - created_at  : fecha de alta
    """
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    url: str = Field(..., description="Endpoint HTTPS del cliente")
    secret: str = Field(..., description="Secreto compartido para HMAC-SHA256")
    event_types: List[WebhookEventType] = Field(
        default_factory=list, description="Eventos a recibir (vacío = todos)"
    )
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("url")
    @classmethod
    def _url_validate(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("url no puede estar vacía")
        if not (v.startswith(("https://", "http://"))):
            raise ValueError("url debe ser http(s)://")
        return v

    @field_validator("secret")
    @classmethod
    def _secret_validate(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 8:
            raise ValueError("secret debe tener al menos 8 caracteres")
        return v

    @field_validator("event_types")
    @classmethod
    def _event_types_validate(cls, v: List[WebhookEventType]) -> List[WebhookEventType]:
        if not v:
            return []
        seen: set = set()
        out: List[WebhookEventType] = []
        for e in v:
            val = WebhookEventType(e) if isinstance(e, str) else e
            if val.value not in seen:
                seen.add(val.value)
                out.append(val)
        return out

    def accepts(self, event_type: WebhookEventType) -> bool:
        """¿Esta suscripción quiere recibir este evento?"""
        if not self.active:
            return False
        return not self.event_types or event_type in self.event_types

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "url": self.url,
            "event_types": [e.value for e in self.event_types],
            "active": self.active,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# WebhookEvent — evento publicado
# ---------------------------------------------------------------------------

class WebhookEvent(BaseModel):
    """Evento con su payload tal como se publica."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    event_type: WebhookEventType = Field(...)
    tenant_id: Optional[str] = Field(default=None, description="Tenant relacionado")
    payload: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("event_type")
    @classmethod
    def _event_type_validate(cls, v: WebhookEventType) -> WebhookEventType:
        return WebhookEventType(v) if isinstance(v, str) else v

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "tenant_id": self.tenant_id,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# WebhookDelivery — entrega de un evento a una suscripción
# ---------------------------------------------------------------------------

class WebhookDelivery(BaseModel):
    """Intentos de entrega de un evento a una suscripción."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    subscription_id: str = Field(...)
    event_id: str = Field(...)
    event_type: WebhookEventType = Field(...)
    status: WebhookDeliveryStatus = Field(default=WebhookDeliveryStatus.PENDING)
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, description="Intentos máximos (retry backoff)")
    next_retry_at: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    last_status_code: Optional[int] = Field(default=None)
    signature: Optional[str] = Field(default=None, description="Firma HMAC del último intento")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def exhausted(self) -> bool:
        """¿Agotó los reintentos?"""
        return self.attempts >= self.max_attempts

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "subscription_id": self.subscription_id,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "last_error": self.last_error,
            "last_status_code": self.last_status_code,
        }
