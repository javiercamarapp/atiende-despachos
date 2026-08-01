# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for Deadline Management (Vencimientos).

Manages Mexican fiscal deadlines including DIOT, IVA, ISR, provisional
payments, electronic accounting, and SAT filings with escalation.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DeadlineTipo(str, Enum):
    """Types of fiscal deadlines."""
    DIOT = "diot"
    IVA = "iva"
    ISR = "isr"
    PROVISIONAL = "provisional"
    CONTABILIDAD_ELECTRONICA = "contabilidad_electronica"
    SAT = "sat"


class DeadlineEstado(str, Enum):
    """Status of a deadline."""
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    COMPLETADO = "completado"
    VENCIDO = "vencido"
    ESCALADO = "escalado"


class Prioridad(str, Enum):
    """Deadline priority levels."""
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class EscalationLevel(int, Enum):
    """Escalation channel levels."""
    EMAIL = 1
    WHATSAPP = 2
    CALL = 3


class EscalationEstado(str, Enum):
    """Escalation notification status."""
    PENDIENTE = "pendiente"
    ENVIADO = "enviado"
    ENTREGADO = "entregado"
    RESPONDIDO = "respondido"
    FALLIDO = "fallido"


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------

class Deadline(BaseModel):
    """A fiscal deadline to track and manage."""
    id: str = Field(
        default="",
        description="Unique deadline identifier",
    )
    tenant_id: str = Field(
        ...,
        description="Company/tenant identifier",
    )
    tipo: DeadlineTipo = Field(
        ...,
        description="Type of deadline (diot, iva, isr, provisional, contabilidad_electronica, sat)",
    )
    fecha_limite: str = Field(
        ...,
        description="Deadline date in YYYY-MM-DD format",
    )
    prioridad: Prioridad = Field(
        default=Prioridad.MEDIA,
        description="Priority level (baja, media, alta, critica)",
    )
    estado: DeadlineEstado = Field(
        default=DeadlineEstado.PENDIENTE,
        description="Current status (pendiente, en_proceso, completado, vencido, escalado)",
    )
    descripcion: str = Field(
        default="",
        description="Additional details about the deadline",
    )
    responsable: str = Field(
        default="",
        description="Person responsible for meeting this deadline",
    )
    proof_url: Optional[str] = Field(
        default=None,
        description="URL or reference to completion proof",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Escalation(BaseModel):
    """An escalation notification sent for a deadline."""
    id: str = Field(
        default="",
        description="Unique escalation identifier",
    )
    deadline_id: str = Field(
        ...,
        description="Reference to the deadline being escalated",
    )
    level: EscalationLevel = Field(
        ...,
        description="Channel: 1=email, 2=whatsapp, 3=phone call",
    )
    sent_at: Optional[datetime] = Field(
        default=None,
        description="When the notification was sent",
    )
    response: Optional[str] = Field(
        default=None,
        description="Response received from the recipient",
    )
    estado: EscalationEstado = Field(
        default=EscalationEstado.PENDIENTE,
        description="Notification status",
    )


class DeadlineWithEscalations(BaseModel):
    """Deadline with its escalation history."""
    deadline: Deadline
    escalations: List[Escalation] = Field(
        default_factory=list,
        description="Escalation history for this deadline",
    )


class UpcomingSummary(BaseModel):
    """Summary of upcoming deadlines."""
    tenant_id: str
    total: int = Field(default=0)
    criticas: int = Field(default=0)
    altas: int = Field(default=0)
    medias: int = Field(default=0)
    bajas: int = Field(default=0)
    deadlines: List[Deadline] = Field(default_factory=list)
