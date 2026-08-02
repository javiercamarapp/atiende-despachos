# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas del módulo Reportes PDF para clientes del despacho.

Estos modelos representan los reportes que el contador entrega a sus propios
clientes (empresas): resumen fiscal mensual, DIOT, conciliación, nómina y balanza.

Estructura:
  - ReportType        : tipo de reporte soportado (enum)
  - ReportStatus      : ciclo de vida de un reporte (enum)
  - ClientReport      : registro de un reporte generado (con metadata + ruta PDF)
  - ReportSchedule    : programación de reportes automáticos
  - GenerateReportResponse / ScheduleRequest : schemas de API

Los registros viven en un store en memoria (como el resto de módulos del piloto)
y siguen el patrón pydantic v2 (BaseModel + Field) del proyecto.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ReportType(str, Enum):
    """Tipo de reporte PDF que el despacho genera para sus clientes."""
    MONTHLY_TAX = "monthly_tax"
    DIOT_SUMMARY = "diot_summary"
    CONCILIACION = "conciliacion"
    NOMINA_SUMMARY = "nomina_summary"
    BALANZA = "balanza"

    @property
    def label(self) -> str:
        return {
            ReportType.MONTHLY_TAX: "Resumen Fiscal Mensual",
            ReportType.DIOT_SUMMARY: "Resumen DIOT",
            ReportType.CONCILIACION: "Conciliación Bancaria",
            ReportType.NOMINA_SUMMARY: "Resumen de Nómina",
            ReportType.BALANZA: "Balanza de Comprobación",
        }[self]

    @classmethod
    def from_value(cls, value: str) -> "ReportType":
        """Resuelve un string al enum, lanzando ValueError si no es válido."""
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Tipo de reporte inválido: '{value}'. Válidos: {valid}")


class ReportStatus(str, Enum):
    """Ciclo de vida de un reporte generado."""
    GENERATED = "generated"
    SCHEDULED = "scheduled"
    FAILED = "failed"


class ScheduleFrequency(str, Enum):
    """Frecuencia de los reportes programados automáticamente."""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


# ---------------------------------------------------------------------------
# Schemas de núcleo
# ---------------------------------------------------------------------------

class ClientReport(BaseModel):
    """Registro persistido de un reporte PDF generado.

    Attributes:
        id: Identificador único del reporte.
        report_type: Tipo de reporte (ReportType).
        tenant_id: Identificador del tenant (empresa cliente del despacho).
        period: Período cubierto (YYYY-MM).
        account_id: Cuenta contable (solo para conciliación, opcional).
        title: Título legible del reporte.
        file_name: Nombre del archivo PDF generado.
        file_path: Ruta absoluta del PDF en disco (para descarga).
        status: Estado del reporte.
        metadata: Metadata adicional (totales, RFC, empresa, etc.).
        generated_at: Timestamp de generación (ISO).
        created_by: Usuario/contador que lo generó.
    """
    id: str = Field(default_factory=lambda: f"crp-{_uuid.uuid4().hex[:12]}")
    report_type: ReportType = Field(..., description="Tipo de reporte")
    tenant_id: str = Field(default="default", description="Tenant (empresa cliente)")
    period: str = Field(..., description="Período cubierto (YYYY-MM)")
    account_id: Optional[str] = Field(
        default=None, description="Cuenta contable (solo conciliación)"
    )
    title: str = Field(default="", description="Título legible del reporte")
    file_name: str = Field(default="", description="Nombre del archivo PDF")
    file_path: str = Field(default="", description="Ruta del PDF en disco")
    status: ReportStatus = Field(default=ReportStatus.GENERATED)
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Metadata del reporte"
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    created_by: str = Field(default="system", description="Usuario generador")

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: str) -> str:
        if len(v) != 7 or v[4] != "-":
            raise ValueError("period debe tener formato YYYY-MM")
        try:
            year, month = int(v[:4]), int(v[5:7])
        except ValueError:
            raise ValueError("period debe tener formato YYYY-MM")
        if not (1 <= month <= 12):
            raise ValueError("Mes inválido en period (1-12)")
        return v

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "report_type": self.report_type.value,
            "report_type_label": self.report_type.label,
            "tenant_id": self.tenant_id,
            "period": self.period,
            "account_id": self.account_id,
            "title": self.title,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "status": self.status.value,
            "metadata": self.metadata,
            "generated_at": self.generated_at,
            "created_by": self.created_by,
        }


class ReportSchedule(BaseModel):
    """Programación de generación automática de reportes.

    Attributes:
        id: Identificador único de la programación.
        report_type: Tipo de reporte a programar.
        tenant_id: Tenant destino.
        frequency: Frecuencia (mensual/trimestral).
        recipients: Emails a los que se notificará (opcional).
        active: Si la programación está activa.
    """
    id: str = Field(default_factory=lambda: f"rsch-{_uuid.uuid4().hex[:12]}")
    report_type: ReportType = Field(..., description="Tipo de reporte")
    tenant_id: str = Field(default="default")
    frequency: ScheduleFrequency = Field(default=ScheduleFrequency.MONTHLY)
    recipients: List[str] = Field(default_factory=list)
    active: bool = Field(default=True)
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "report_type": self.report_type.value,
            "tenant_id": self.tenant_id,
            "frequency": self.frequency.value,
            "recipients": self.recipients,
            "active": self.active,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Schemas de API
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    """Request para programar reportes automáticos."""
    report_type: ReportType = Field(..., description="Tipo de reporte a programar")
    tenant_id: str = Field(default="default", description="Tenant destino")
    frequency: ScheduleFrequency = Field(
        default=ScheduleFrequency.MONTHLY,
        description="Frecuencia: monthly o quarterly",
    )
    recipients: List[str] = Field(
        default_factory=list, description="Emails para notificación"
    )


class GenerateReportResponse(BaseModel):
    """Respuesta al generar (o recuperar) un reporte."""
    ok: bool = True
    report: Optional[dict] = None
    message: str = ""
