# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Vencimientos module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent fiscal deadlines, escalations, and summaries used by
contadores in Mexico to manage tax filing deadlines and compliance.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PrioridadVencimiento(str, Enum):
    """Prioridad de un vencimiento fiscal."""
    CRITICA = "critica"     # Vence hoy o venció
    ALTA = "alta"           # Vence en 1-3 días
    MEDIA = "media"         # Vence en 4-7 días
    BAJA = "baja"           # Vence en 8+ días


class EstadoVencimiento(str, Enum):
    """Estado de un vencimiento fiscal."""
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    COMPLETADO = "completado"
    VENCIDO = "vencido"
    ESCALADO = "escalado"


class NivelEscalamiento(str, Enum):
    """Nivel de escalamiento de un vencimiento."""
    NIVEL_1 = "nivel_1"    # Recordatorio interno
    NIVEL_2 = "nivel_2"    # Notificación a supervisor
    NIVEL_3 = "nivel_3"    # Alerta a dirección
    NIVEL_4 = "nivel_4"    # Escalamiento gerencial


# ---------------------------------------------------------------------------
# Deadline schema
# ---------------------------------------------------------------------------

class Deadline(BaseModel):
    """Un vencimiento fiscal."""
    id: str = Field(default="", description="Identificador único del vencimiento")
    tipo: str = Field(
        ...,
        description="Tipo de obligación fiscal (ISR, IVA, DIOT, SAT, nómina, etc.)",
    )
    fecha_limite: str = Field(
        ...,
        description="Fecha límite YYYY-MM-DD",
    )
    fecha_presentacion: Optional[str] = Field(
        default=None,
        description="Fecha de presentación real (si ya se presentó)",
    )
    prioridad: PrioridadVencimiento = Field(
        default=PrioridadVencimiento.MEDIA,
        description="Prioridad del vencimiento",
    )
    estado: EstadoVencimiento = Field(
        default=EstadoVencimiento.PENDIENTE,
        description="Estado actual del vencimiento",
    )
    descripcion: str = Field(
        default="",
        description="Descripción de la obligación fiscal",
    )
    periodo: Optional[str] = Field(
        default=None,
        description="Período fiscal relacionado (YYYY-MM)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )
    responsable: Optional[str] = Field(
        default=None,
        description="Persona responsable de cumplir el vencimiento",
    )
    comprobante_url: Optional[str] = Field(
        default=None,
        description="URL del comprobante de presentación",
    )

    @field_validator("fecha_limite")
    @classmethod
    def _fecha_limite_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Formato de fecha inválido: '{v}'. Se esperaba YYYY-MM-DD.")
        return v


# ---------------------------------------------------------------------------
# Escalation schema
# ---------------------------------------------------------------------------

class Escalation(BaseModel):
    """Un evento de escalamiento de un vencimiento."""
    id: str = Field(default="", description="Identificador único del escalamiento")
    deadline_id: str = Field(
        ...,
        description="ID del vencimiento relacionado",
    )
    level: NivelEscalamiento = Field(
        ...,
        description="Nivel de escalamiento",
    )
    sent_at: str = Field(
        ...,
        description="Fecha/hora de envío ISO format",
    )
    response: Optional[str] = Field(
        default=None,
        description="Respuesta del destinatario (si se recibió)",
    )
    responded_at: Optional[str] = Field(
        default=None,
        description="Fecha/hora de respuesta ISO format",
    )
    notes: str = Field(
        default="",
        description="Notas adicionales del escalamiento",
    )


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------

class VencimientoSummary(BaseModel):
    """Resumen de vencimientos para un tenant/período."""
    total: int = Field(default=0, description="Total de vencimientos")
    pendientes: int = Field(default=0, description="Vencimientos pendientes")
    completados: int = Field(default=0, description="Vencimientos completados")
    vencidos: int = Field(default=0, description="Vencimientos vencidos")
    escalados: int = Field(default=0, description="Vencimientos escalados")
    proximos_7_dias: int = Field(
        default=0,
        description="Vencimientos que vencen en los próximos 7 días",
    )
