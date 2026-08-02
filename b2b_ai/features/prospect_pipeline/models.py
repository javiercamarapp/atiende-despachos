# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Pipeline de Prospectos/Leads (CRM).

Modelos Pydantic para el pipeline de ventas del MVP de Likida AI:

  - LeadSource     : origen del lead (LINKEDIN / COLD_CALL / REFERRAL / WEBSITE).
  - LeadStatus     : ciclo de vida del lead (NEW → CONTACTED → QUALIFIED →
                     PROPOSAL → NEGOTIATION → WON / LOST).
  - ActivityType   : tipo de actividad (CALL / EMAIL / MEETING / NOTE).
  - ProposalStatus : estado de una propuesta (DRAFT → SENT → ACCEPTED / REJECTED).
  - Lead           : prospecto dentro del pipeline.
  - PipelineStage  : etapa configurable del pipeline por tenant.
  - Activity       : interacción registrada sobre un lead.
  - Proposal       : propuesta comercial vinculada a un lead.
  - LeadCreate / ActivityCreate / ProposalCreate: schemas de alta.

Todos los modelos llevan `tenant_id` para garantizar el aislamiento
multi-tenant. Siguen el patrón de los módulos piloto (ap_ar, nomina,
monthly_close): modelos Pydantic + almacenamiento en memoria con
`_reset_state()` para tests, y `to_dict()` para serialización JSON.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LeadSource(str, Enum):
    """Origen de un lead."""
    LINKEDIN = "LINKEDIN"
    COLD_CALL = "COLD_CALL"
    REFERRAL = "REFERRAL"
    WEBSITE = "WEBSITE"


class LeadStatus(str, Enum):
    """Ciclo de vida de un lead dentro del pipeline."""
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class ActivityType(str, Enum):
    """Tipo de actividad registrada sobre un lead."""
    CALL = "CALL"
    EMAIL = "EMAIL"
    MEETING = "MEETING"
    NOTE = "NOTE"


class ProposalStatus(str, Enum):
    """Estado de una propuesta comercial."""
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------

class Lead(BaseModel):
    """Prospecto dentro del pipeline de ventas."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: Optional[str] = Field(default=None)
    company_name: str = Field(..., description="Nombre de la empresa prospecto")
    contact_name: str = Field(default="", description="Nombre del contacto")
    contact_email: str = Field(default="", description="Email del contacto")
    contact_phone: str = Field(default="", description="Teléfono del contacto")
    source: LeadSource = Field(default=LeadSource.WEBSITE, description="Origen del lead")
    status: LeadStatus = Field(default=LeadStatus.NEW, description="Etapa actual")
    score: int = Field(default=0, ge=0, le=100, description="Score automático 0-100")

    # Señales de scoring (usadas por LeadScoring)
    company_size: str = Field(default="", description="Tamaño de la empresa (p.ej. '10-50')")
    budget: Optional[float] = Field(default=None, description="Presupuesto estimado MXN")
    timeline: str = Field(default="", description="Plazo de compra (p.ej. '0-3 meses')")

    notes: str = Field(default="", description="Notas del lead")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())

    @field_validator("company_name")
    @classmethod
    def _company_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("company_name no puede estar vacío")
        return v

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "company_name": self.company_name,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "source": self.source.value if self.source else None,
            "status": self.status.value if self.status else None,
            "score": self.score,
            "company_size": self.company_size,
            "budget": self.budget,
            "timeline": self.timeline,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LeadCreate(BaseModel):
    """Schema de alta de un lead."""
    company_name: str = Field(..., description="Nombre de la empresa prospecto")
    contact_name: str = Field(default="")
    contact_email: str = Field(default="")
    contact_phone: str = Field(default="")
    source: LeadSource = Field(default=LeadSource.WEBSITE)
    company_size: str = Field(default="")
    budget: Optional[float] = Field(default=None)
    timeline: str = Field(default="")
    notes: str = Field(default="")


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------

class PipelineStage(BaseModel):
    """Etapa configurable del pipeline de un tenant."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: Optional[str] = Field(default=None)
    name: str = Field(..., description="Nombre de la etapa")
    order: int = Field(default=0, description="Posición en el pipeline")
    color: str = Field(default="#64748b", description="Color de la etapa (hex)")
    is_won: bool = Field(default=False, description="Etapa de cierre ganado")
    is_lost: bool = Field(default=False, description="Etapa de cierre perdido")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "order": self.order,
            "color": self.color,
            "is_won": self.is_won,
            "is_lost": self.is_lost,
        }


class PipelineStageCreate(BaseModel):
    """Schema de alta de una etapa de pipeline."""
    name: str
    order: int = 0
    color: str = "#64748b"
    is_won: bool = False
    is_lost: bool = False


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class Activity(BaseModel):
    """Actividad registrada sobre un lead."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    lead_id: str = Field(..., description="Lead padre")
    tenant_id: Optional[str] = Field(default=None)
    activity_type: ActivityType = Field(default=ActivityType.NOTE)
    description: str = Field(default="", description="Descripción de la actividad")
    outcome: str = Field(default="", description="Resultado")
    next_action: str = Field(default="", description="Próximo paso")
    next_action_date: Optional[str] = Field(default=None, description="Fecha del próximo paso YYYY-MM-DD")
    created_by: str = Field(default="", description="Usuario que registró la actividad")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "tenant_id": self.tenant_id,
            "activity_type": self.activity_type.value if self.activity_type else None,
            "description": self.description,
            "outcome": self.outcome,
            "next_action": self.next_action,
            "next_action_date": self.next_action_date,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ActivityCreate(BaseModel):
    """Schema de alta de una actividad."""
    activity_type: ActivityType = ActivityType.NOTE
    description: str = ""
    outcome: str = ""
    next_action: str = ""
    next_action_date: Optional[str] = None
    created_by: str = ""


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

class Proposal(BaseModel):
    """Propuesta comercial vinculada a un lead."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    lead_id: str = Field(..., description="Lead padre")
    tenant_id: Optional[str] = Field(default=None)
    amount: float = Field(default=0.0, ge=0, description="Monto propuesto")
    currency: str = Field(default="MXN", description="Moneda")
    valid_until: Optional[str] = Field(default=None, description="Vigencia YYYY-MM-DD")
    status: ProposalStatus = Field(default=ProposalStatus.DRAFT)
    content: str = Field(default="", description="Contenido de la propuesta (markdown/texto)")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "tenant_id": self.tenant_id,
            "amount": self.amount,
            "currency": self.currency,
            "valid_until": self.valid_until,
            "status": self.status.value if self.status else None,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProposalCreate(BaseModel):
    """Schema de alta de una propuesta."""
    amount: float = Field(default=0.0, ge=0)
    currency: str = "MXN"
    valid_until: Optional[str] = None
    content: str = ""
