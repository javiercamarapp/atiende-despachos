# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Periodic Declarations module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent IVA declarations, ISR provisional/annual declarations,
and deadline tracking used by Mexican fiscal compliance.

CFF (Código Fiscal de la Federación) rules:
  - IVA: Monthly, due by the 17th of the following month
  - ISR Provisional: Monthly, due by the 17th of the following month
  - ISR Anual: Annual, due by April 30th
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DeclaracionType(str, Enum):
    """Type of periodic declaration."""
    IVA = "iva"
    ISR_PROVISIONAL = "isr_provisional"
    ISR_ANUAL = "isr_anual"


class DeclaracionStatus(str, Enum):
    """Status of a declaration."""
    DRAFT = "draft"
    PENDING = "pending"
    FILED = "filed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DeadlineStatus(str, Enum):
    """Status of a deadline."""
    PENDING = "pending"
    URGENT = "urgent"
    OVERDUE = "overdue"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------

class IvaData(BaseModel):
    """IVA declaration data for a given period.

    IVA calculation:
      - iva_cobrado: IVA collected from sales (charged to customers)
      - iva_pagado: IVA paid on purchases (paid to suppliers)
      - saldo_favor: If iva_pagado > iva_cobrado (credit balance)
      - saldo_contra: If iva_cobrado > iva_pagado (debit balance)

    Mexican IVA rates (2024):
      - General rate: 16%
      - Border zone: 8%
      - Zero rate: 0% (exports, basic food, medicine)
    """
    iva_cobrado: float = Field(
        ...,
        description="IVA collected from sales (charged to customers)",
        ge=0,
    )
    iva_pagado: float = Field(
        ...,
        description="IVA paid on purchases (paid to suppliers)",
        ge=0,
    )
    saldo_favor: float = Field(
        default=0.0,
        description="IVA credit balance (iva_pagado > iva_cobrado)",
        ge=0,
    )
    saldo_contra: float = Field(
        default=0.0,
        description="IVA debit balance (iva_cobrado > iva_pagado)",
        ge=0,
    )
    requires_human_review: bool = Field(
        default=False,
        description="Requiere revisión humana",
    )
    human_review_reason: Optional[str] = Field(
        default=None,
        description="Razón de revisión humana",
    )

    @field_validator("saldo_favor", "saldo_contra", mode="before")
    @classmethod
    def _round_amounts(cls, v: float) -> float:
        return round(v, 2)


class IsrData(BaseModel):
    """ISR declaration data for a given period.

    ISR calculation (CFF Art. 113):
      - ingresos: Total gross income
      - deducciones: Allowable deductions (expenses, depreciation, etc.)
      - utilidad: Taxable income (ingresos - deducciones)
      - isr_calculated: ISR calculated using progressive table
      - pagos_provisionales: Sum of provisional ISR payments made

    ISR rates (2024, progressive table):
      - Up to $312.41: 1.92%
      - $312.42 - $2,636.28: 6.40%
      - $2,636.29 - $4,623.01: 10.88%
      - $4,623.02 - $5,409.82: 16.00%
      - $5,409.83 - $6,447.11: 21.36%
      - $6,447.12 - $12,904.06: 23.52%
      - $12,904.07 - $25,808.11: 30.00%
      - $25,808.12 - $34,410.81: 32.00%
      - $34,410.82 - $68,821.62: 34.00%
      - Over $68,821.62: 35% + $12,532.53 fixed
    """
    ingresos: float = Field(
        ...,
        description="Total gross income",
        ge=0,
    )
    deducciones: float = Field(
        default=0.0,
        description="Allowable deductions",
        ge=0,
    )
    utilidad: float = Field(
        default=0.0,
        description="Taxable income (ingresos - deducciones)",
    )
    isr_calculated: float = Field(
        default=0.0,
        description="ISR calculated using progressive table",
        ge=0,
    )
    pagos_provisionales: float = Field(
        default=0.0,
        description="Sum of provisional ISR payments made",
        ge=0,
    )


class Declaracion(BaseModel):
    """A periodic tax declaration.

    Represents either an IVA, ISR Provisional, or ISR Annual declaration
    for a specific period (month/year or year).
    """
    id: Optional[str] = Field(default=None, description="Unique declaration ID")
    tenant_id: str = Field(..., description="Tenant identifier")
    tipo: DeclaracionType = Field(..., description="Declaration type")
    periodo: str = Field(
        ...,
        description="Period (YYYY-MM for monthly, YYYY for annual)",
    )
    referencia_legal: Optional[str] = Field(
        default=None,
        description="Referencia legal",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Requiere revisión humana",
    )
    human_review_reason: Optional[str] = Field(
        default=None,
        description="Razón de revisión humana",
    )
    supuesto: Optional[str] = Field(
        default=None,
        description="Supuesto de aplicación",
    )
    audit_trail: List[str] = Field(
        default_factory=list,
        description="Bitácora de acciones",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Clave de idempotencia",
    )
    escalation_path: Optional[str] = Field(
        default=None,
        description="Ruta de escalación",
    )
    status: DeclaracionStatus = Field(
        default=DeclaracionStatus.DRAFT,
        description="Current declaration status",
    )
    rfc: str = Field(..., description="RFC of the taxpayer")
    fecha_creacion: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"),
        description="Creation date (YYYY-MM-DD)",
    )
    fecha_presentacion: Optional[str] = Field(
        default=None,
        description="Filing date (YYYY-MM-DD, null if not yet filed)",
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Declaration-specific data (IvaData or IsrData)",
    )
    observaciones: Optional[str] = Field(
        default=None,
        description="Notes or observations",
    )


class Deadline(BaseModel):
    """A fiscal deadline for a tenant.

    Tracks upcoming due dates for IVA, ISR, and other tax obligations.
    """
    id: Optional[str] = Field(default=None, description="Unique deadline ID")
    tenant_id: str = Field(..., description="Tenant identifier")
    tipo: DeclaracionType = Field(..., description="Declaration type")
    periodo: str = Field(..., description="Period (YYYY-MM or YYYY)")
    fecha_limite: str = Field(..., description="Due date (YYYY-MM-DD)")
    dias_restantes: int = Field(
        default=0,
        description="Days remaining until deadline",
    )
    estado: DeadlineStatus = Field(
        default=DeadlineStatus.PENDING,
        description="Deadline status",
    )
    declaracion_id: Optional[str] = Field(
        default=None,
        description="ID of the filed declaration (null if not yet created)",
    )
    recordatorio_enviado: bool = Field(
        default=False,
        description="Whether reminder has been sent",
    )


class ReminderResult(BaseModel):
    """Result of sending reminders for upcoming deadlines."""
    tenant_id: str = Field(..., description="Tenant identifier")
    deadline_id: str = Field(..., description="Deadline ID")
    tipo: DeclaracionType = Field(..., description="Declaration type")
    periodo: str = Field(..., description="Period")
    fecha_limite: str = Field(..., description="Due date")
    dias_restantes: int = Field(..., description="Days remaining")
    reminder_sent: bool = Field(default=True, description="Whether reminder was sent")


class DeclaracionSummary(BaseModel):
    """Summary of declarations for a tenant."""
    tenant_id: str = Field(..., description="Tenant identifier")
    total_declaraciones: int = Field(default=0, description="Total declarations")
    borradores: int = Field(default=0, description="Draft declarations")
    presentadas: int = Field(default=0, description="Filed declarations")
    aceptadas: int = Field(default=0, description="Accepted declarations")
    rechazadas: int = Field(default=0, description="Rejected declarations")
    proximo_vencimiento: Optional[str] = Field(
        default=None,
        description="Next upcoming deadline (YYYY-MM-DD)",
    )
