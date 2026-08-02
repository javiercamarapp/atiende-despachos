# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Tracking de Obligaciones SAT
(compliance_tracker).

Modelos:
  - ObligationType : tipos de obligación fiscal ante el SAT.
  - ObligationStatus : ciclo de vida de una obligación.
  - AlertType      : tipos de alerta de vencimiento.
  - Obligation     : una obligación fiscal (DIOT, ISR mensual, IVA mensual,
                     contabilidad electrónica, nómina bimestral, anual) para
                     un tenant en una fecha de vencimiento.
  - ComplianceAlert: alerta generada por el despacho (UPDUE / OVERDUE /
                     CRITICAL) asociada a una obligación.

Complementa a monthly_close (que orquesta el cierre mensual) trackeando de
forma específica las obligaciones SAT y sus vencimientos, comparable al
calendario de obligaciones que ya ofrecen competidores (CONTPAQi Optimiza).
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ObligationType(str, Enum):
    """Tipos de obligación fiscal que debe cumplir un despacho ante el SAT."""

    DIOT = "DIOT"                        # Declaración Informativa de Operaciones con Terceros
    ISR_MENSUAL = "ISR_MENSUAL"          # Declaración mensual ISR
    IVA_MENSUAL = "IVA_MENSUAL"          # Declaración mensual IVA
    CONTAB_ELECTRONICA = "CONTAB_ELECTRONICA"  # Envío contabilidad electrónica
    NOMINA_BIMESTRAL = "NOMINA_BIMESTRAL"      # Declaración de nómina bimestral
    ANUAL = "ANUAL"                      # Declaración anual ISR


class ObligationStatus(str, Enum):
    """Ciclo de vida de una obligación fiscal."""

    PENDING = "PENDING"          # pendiente por cumplir
    OVERDUE = "OVERDUE"          # vencida (fecha límite pasada sin completar)
    COMPLETED = "COMPLETED"      # cumplida


class AlertType(str, Enum):
    """Tipos de alerta de vencimiento de obligaciones."""

    UPDUE = "UPDUE"              # próxima a vencer (ventana configurable)
    OVERDUE = "OVERDUE"          # vencida
    CRITICAL = "CRITICAL"        # vencida hace mucho / riesgo alto


# ---------------------------------------------------------------------------
# Obligation
# ---------------------------------------------------------------------------


class Obligation(BaseModel):
    """Una obligación fiscal de un tenant con su fecha de vencimiento."""

    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant (despacho) dueño de la obligación")
    obligation_type: ObligationType = Field(
        ..., description="Tipo de obligación (DIOT, ISR_MENSUAL, ...)")
    due_date: date = Field(..., description="Fecha de vencimiento (YYYY-MM-DD)")
    status: ObligationStatus = Field(
        default=ObligationStatus.PENDING,
        description="PENDING / OVERDUE / COMPLETED")
    completed_at: Optional[datetime] = Field(
        default=None, description="Momento en que se completó")
    completed_by: Optional[str] = Field(
        default=None, description="Usuario que marcó la obligación como cumplida")
    notes: str = Field(default="", description="Notas / seguimiento del contador")

    @field_validator("due_date")
    @classmethod
    def _valid_due_date(cls, v: date) -> date:
        # Evita fechas absurdamente antiguas; validación ligera de rango.
        if v.year < 2000 or v.year > 2100:
            raise ValueError("due_date fuera de rango (2000-2100)")
        return v

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "obligation_type": self.obligation_type.value,
            "due_date": self.due_date.isoformat(),
            "status": self.status.value,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "completed_by": self.completed_by,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ComplianceAlert
# ---------------------------------------------------------------------------


class ComplianceAlert(BaseModel):
    """Una alerta de vencimiento asociada a una obligación."""

    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant dueño de la alerta")
    obligation_id: str = Field(..., description="Obligación que dispara la alerta")
    alert_type: AlertType = Field(
        ..., description="UPDUE / OVERDUE / CRITICAL")
    sent_at: Optional[datetime] = Field(
        default=None, description="Momento en que se envió la alerta")
    acknowledged: bool = Field(
        default=False, description="True si el despacho la reconoció")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "obligation_id": self.obligation_id,
            "alert_type": self.alert_type.value,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "acknowledged": self.acknowledged,
        }
