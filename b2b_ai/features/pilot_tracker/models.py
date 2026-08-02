# -*- coding: utf-8 -*-
"""
models.py — Esquemas del módulo de Tracking de Piloto (pilot_tracker).

Modelos:
  - PilotMetricType : tipos de métrica de uso / ahorro del piloto.
  - PilotMetric     : un registro de métrica (procesos CFDI, conciliaciones,
                      nóminas, horas ahorradas, costo ahorrado, tasa de
                      automatización) para un tenant en un período.
  - PilotHealth     : health score (0-100) calculado por tenant con el detalle
                      de sus factores (JSON).
  - PilotReport     : reporte agregado de un período (metrics_summary JSON).

Mide el valor real que Likida genera para el cliente — crítico para convertir
pilotos en clientes que pagan.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PilotMetricType(str, Enum):
    """Tipos de métrica que se registran para un tenant piloto."""

    CFDI_PROCESSED = "CFDI_PROCESSED"          # facturas CFDI procesadas (count)
    BANK_RECONCILED = "BANK_RECONCILED"        # movimientos conciliados (count)
    NOMINA_TIMBRED = "NOMINA_TIMBRED"          # nóminas timbradas (count)
    HOURS_SAVED = "HOURS_SAVED"                # horas ahorradas por automatización
    COST_SAVED = "COST_SAVED"                  # costo ahorrado (MXN)
    AUTOMATION_RATE = "AUTOMATION_RATE"        # % de procesos automatizados (0-100)


# ---------------------------------------------------------------------------
# PilotMetric
# ---------------------------------------------------------------------------


class PilotMetric(BaseModel):
    """Un registro de métrica de uso / ahorro para un tenant en un período."""

    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant (cliente) dueño de la métrica")
    metric_type: PilotMetricType = Field(
        ..., description="Tipo de métrica (CFDI_PROCESSED, HOURS_SAVED, ...)")
    value: float = Field(..., ge=0.0, description="Valor de la métrica (≥0)")
    period_start: date = Field(..., description="Inicio del período contable")
    period_end: date = Field(..., description="Fin del período contable")
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="Momento en que se registró la métrica")

    @field_validator("period_end")
    @classmethod
    def _period_end_ge_start(cls, v: date, info) -> date:
        start = info.data.get("period_start")
        if start is not None and v < start:
            raise ValueError("period_end no puede ser anterior a period_start")
        return v

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# PilotHealth
# ---------------------------------------------------------------------------


class PilotHealth(BaseModel):
    """Health score (0-100) de un tenant piloto con el desglose de factores."""

    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant evaluado")
    health_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Puntaje global 0-100 (mayor = cliente más saludable)")
    factors: Dict[str, Any] = Field(
        default_factory=dict,
        description="Desglose por factor: usage_frequency, data_quality, "
                    "automation_adoption, response_time + pesos")
    calculated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="Momento del cálculo")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "health_score": round(self.health_score, 1),
            "factors": self.factors,
            "calculated_at": self.calculated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# PilotReport
# ---------------------------------------------------------------------------


class PilotReport(BaseModel):
    """Reporte agregado de métricas de un período para un tenant."""

    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: str = Field(..., description="Tenant del reporte")
    period: str = Field(..., description="Etiqueta de período (ej. 2025-06)")
    metrics_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resumen de métricas del período (totales por tipo + ROI)")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="Momento de generación")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "period": self.period,
            "metrics_summary": self.metrics_summary,
            "generated_at": self.generated_at.isoformat(),
        }
