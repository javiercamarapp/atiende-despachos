# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Cierre Mensual (monthly_close).

Modelos:
  - ClosePeriodStatus : estado de un período de cierre.
  - TaskCategory      : categoría contable de una tarea de cierre.
  - TaskStatus        : ciclo de vida de una tarea del checklist.
  - ClosePeriod       : período de cierre (year/month) de un tenant.
  - CloseTask         : tarea individual del checklist con dependencias.
  - CloseTemplate     : plantilla reutilizable de workflow de cierre.
  - CloseTemplateTask : definición de tarea dentro de una plantilla.

El módulo orquesta el proceso de cierre mensual de un despacho contable
conectando bank_feeds (conciliación), procesamiento CFDI, nóminas,
declaraciones y contabilidad electrónica.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClosePeriodStatus(str, Enum):
    """Estado de un período de cierre mensual."""
    OPEN = "OPEN"            # período abierto, tareas en curso
    CLOSED = "CLOSED"        # período cerrado (todas las tareas requeridas hechas)
    OVERDUE = "OVERDUE"      # período atrasado (tareas vencidas pendientes)


class TaskCategory(str, Enum):
    """Categoría contable de una tarea de cierre."""
    CFDI = "CFDI"
    BANK = "BANK"
    NOMINA = "NOMINA"
    DECLARACION = "DECLARACION"
    ELECTRONICA = "ELECTRONICA"
    CUSTOM = "CUSTOM"


class TaskStatus(str, Enum):
    """Ciclo de vida de una tarea del checklist de cierre."""
    PENDING = "PENDING"          # lista para trabajar (dependencias satisfechas)
    IN_PROGRESS = "IN_PROGRESS"  # en curso
    BLOCKED = "BLOCKED"          # esperando dependencias sin resolver
    DONE = "DONE"                # completada
    SKIPPED = "SKIPPED"          # omitida (opcional / no aplica)


# ---------------------------------------------------------------------------
# ClosePeriod
# ---------------------------------------------------------------------------


class ClosePeriod(BaseModel):
    """Un período de cierre mensual para un tenant."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant dueño del período")
    year: int = Field(..., ge=2014, le=2099)
    month: int = Field(..., ge=1, le=12)
    status: ClosePeriodStatus = Field(default=ClosePeriodStatus.OPEN)
    opened_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    closed_at: Optional[datetime] = Field(default=None)
    closed_by: Optional[str] = Field(default=None)

    @field_validator("month")
    @classmethod
    def _month_range(cls, v: int) -> int:
        if not (1 <= v <= 12):
            raise ValueError("month debe estar entre 1 y 12")
        return v

    @property
    def period_label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "year": self.year,
            "month": self.month,
            "period": self.period_label,
            "status": self.status.value,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
        }


# ---------------------------------------------------------------------------
# CloseTask
# ---------------------------------------------------------------------------


class CloseTask(BaseModel):
    """Tarea individual del checklist de cierre mensual."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    period_id: str = Field(..., description="ClosePeriod padre")
    title: str = Field(..., description="Nombre corto de la tarea")
    description: str = Field(default="", description="Detalle / instrucciones")
    category: TaskCategory = Field(default=TaskCategory.CUSTOM)
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    assigned_to: Optional[str] = Field(default=None, description="Usuario responsable")
    depends_on: List[str] = Field(
        default_factory=list, description="IDs de tareas que deben completarse antes")
    due_date: Optional[str] = Field(
        default=None, description="Fecha límite opcional YYYY-MM-DD")
    completed_at: Optional[datetime] = Field(default=None)
    completed_by: Optional[str] = Field(default=None)
    auto_check_query: Optional[str] = Field(
        default=None,
        description="Consulta SQL/nombre de verificación para auto-completar",
    )
    required: bool = Field(
        default=True, description="False = tarea opcional (puede cerrarse sin ella)")

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title no puede estar vacío")
        return v

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "period_id": self.period_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "depends_on": list(self.depends_on),
            "due_date": self.due_date,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "completed_by": self.completed_by,
            "auto_check_query": self.auto_check_query,
            "required": self.required,
        }


# ---------------------------------------------------------------------------
# CloseTemplate / CloseTemplateTask
# ---------------------------------------------------------------------------


class CloseTemplateTask(BaseModel):
    """Definición declarativa de una tarea dentro de una plantilla."""
    key: Optional[str] = Field(
        default=None, description="Key estable para referenciarla en depends_on")
    title: str = Field(..., description="Nombre corto de la tarea")
    description: str = Field(default="")
    category: TaskCategory = Field(default=TaskCategory.CUSTOM)
    depends_on: List[str] = Field(
        default_factory=list, description="Keys de tareas precedentes de la plantilla")
    due_offset_days: int = Field(
        default=0, description="Días relativos a la apertura para la fecha límite")
    auto_check_query: Optional[str] = Field(default=None)
    required: bool = Field(default=True)


class CloseTemplate(BaseModel):
    """Plantilla reutilizable de workflow de cierre mensual."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str = Field(..., description="Nombre de la plantilla")
    description: str = Field(default="")
    tasks: List[CloseTemplateTask] = Field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tasks": [t.model_dump() for t in self.tasks],
        }
