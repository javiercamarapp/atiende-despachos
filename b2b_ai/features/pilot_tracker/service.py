# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del Tracking de Piloto (pilot_tracker).

PilotTrackerService:
  - record_metric            : registra una métrica de uso / ahorro.
  - get_tenant_metrics       : métricas de un tenant en un rango de períodos.
  - calculate_health_score   : health score 0-100 por factores ponderados.
  - generate_pilot_report    : reporte agregado de un período.
  - get_roi_summary          : horas ahorradas, costo ahorrado y tasa de
                               automatización (ROI del piloto).

ROI (parametrizable, defaults del proyecto):
  - Accountant hourly cost  : 50–500 MXN/h → default 250 MXN/h.
  - CFDI savings            : ~14 min por factura procesada.
  - Bank recon savings      : ~25 min por movimiento conciliado.
  - Nomina savings          : ~1.75 h por nómina timbrada.

Almacenamiento en memoria (dict) con `_reset_state()` para tests, coherente
con el patrón bank_feeds / monthly_close / roles.
"""
from __future__ import annotations

import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.pilot_tracker.models import (
    PilotHealth,
    PilotMetric,
    PilotMetricType,
    PilotReport,
)

# ---------------------------------------------------------------------------
# Parámetros de ROI (configurables)
# ---------------------------------------------------------------------------

DEFAULT_ACCOUNTANT_HOURLY_COST_MXN = 250.0
CFDI_SAVINGS_MINUTES = 14.0
BANK_RECON_SAVINGS_MINUTES = 25.0
NOMINA_SAVINGS_HOURS = 1.75

# Ponderación de factores del health score (suman 1.0)
HEALTH_WEIGHTS = {
    "usage_frequency": 0.30,        # frecuencia de uso
    "data_quality": 0.25,           # calidad / volumen de datos
    "automation_adoption": 0.25,    # adopción de automatización
    "response_time": 0.20,          # tiempo de respuesta / puntualidad
}

# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / monthly_close / roles)
# ---------------------------------------------------------------------------

_metrics: Dict[str, PilotMetric] = {}
_health: Dict[str, PilotHealth] = {}
_reports: Dict[str, PilotReport] = {}
# tenant_id -> [metric_ids]
_tenant_metrics: Dict[str, List[str]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _metrics.clear()
    _health.clear()
    _reports.clear()
    _tenant_metrics.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _today() -> date:
    return date.today()


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class PilotTrackerService:
    """Servicio de tracking de piloto: métricas, health score y ROI."""

    def __init__(self, db: Any = None,
                 accountant_hourly_cost_mxn: float = DEFAULT_ACCOUNTANT_HOURLY_COST_MXN):
        self.db = db
        self.hourly_cost = accountant_hourly_cost_mxn

    # ------------------------------------------------------------------
    # Registro / lectura de métricas
    # ------------------------------------------------------------------
    def record_metric(
        self,
        tenant_id: str,
        metric_type: PilotMetricType,
        value: float,
        period_start: date,
        period_end: date,
    ) -> PilotMetric:
        """Registra una métrica de uso / ahorro para un tenant."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        metric = PilotMetric(
            tenant_id=tenant_id,
            metric_type=metric_type,
            value=float(value),
            period_start=period_start,
            period_end=period_end,
            recorded_at=_utcnow(),
        )
        _metrics[metric.id] = metric
        _tenant_metrics.setdefault(tenant_id, []).append(metric.id)
        return metric

    def get_metric(self, metric_id: str) -> PilotMetric:
        metric = _metrics.get(metric_id)
        if metric is None:
            raise KeyError(f"Métrica no encontrada: {metric_id}")
        return metric

    def get_tenant_metrics(
        self,
        tenant_id: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> List[PilotMetric]:
        """Métricas del tenant, opcionalmente filtradas por rango de períodos."""
        ids = _tenant_metrics.get(tenant_id, [])
        out: List[PilotMetric] = [_metrics[i] for i in ids if i in _metrics]
        if period_start is not None:
            out = [m for m in out if m.period_end >= period_start]
        if period_end is not None:
            out = [m for m in out if m.period_start <= period_end]
        return sorted(out, key=lambda m: (m.period_start, m.metric_type.value))

    # ------------------------------------------------------------------
    # Health score
    # ------------------------------------------------------------------
    def _factor_usage_frequency(self, tenant_id: str) -> float:
        """Frecuencia de uso: proporción de días del piloto con actividad
        reciente. Si no hay métricas → 0."""
        metrics = self.get_tenant_metrics(tenant_id)
        if not metrics:
            return 0.0
        # Actividad en los últimos 30 días.
        cutoff = _today() - timedelta(days=30)
        recent = [m for m in metrics if m.recorded_at.date() >= cutoff]
        if not recent:
            return 0.0
        # Puntaje por volumen de uso: 1 registro→30, hasta 100 con 30+.
        return min(100.0, 30.0 + len(recent) * 2.5)

    def _factor_data_quality(self, tenant_id: str) -> float:
        """Calidad / volumen de datos: presencia de las 3 categorías core
        (CFDI, bank, nómina)."""
        metrics = self.get_tenant_metrics(tenant_id)
        if not metrics:
            return 0.0
        types = {m.metric_type for m in metrics}
        core_present = 0
        for t in (PilotMetricType.CFDI_PROCESSED,
                  PilotMetricType.BANK_RECONCILED,
                  PilotMetricType.NOMINA_TIMBRED):
            if t in types:
                core_present += 1
        # Base 40 + 20 por categoría core presente → hasta 100.
        return min(100.0, 40.0 + core_present * 20.0)

    def _factor_automation_adoption(self, tenant_id: str) -> float:
        """Adopción de automatización: último AUTOMATION_RATE registrado
        (0-100). Si no hay registro → 0."""
        metrics = self.get_tenant_metrics(tenant_id)
        rates = [m.value for m in metrics
                 if m.metric_type == PilotMetricType.AUTOMATION_RATE]
        if not rates:
            return 0.0
        return min(100.0, max(0.0, rates[-1]))

    def _factor_response_time(self, tenant_id: str) -> float:
        """Tiempo de respuesta / puntualidad: 100 si hay actividad en los
        últimos 7 días; decae con la antigüedad del último registro."""
        metrics = self.get_tenant_metrics(tenant_id)
        if not metrics:
            return 0.0
        latest = max(m.recorded_at for m in metrics)
        age_days = (_today() - latest.date()).days
        if age_days <= 7:
            return 100.0
        return max(0.0, 100.0 - (age_days - 7) * 5.0)

    def calculate_health_score(self, tenant_id: str) -> PilotHealth:
        """Calcula el health score (0-100) ponderando los 4 factores."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")

        factors = {
            "usage_frequency": self._factor_usage_frequency(tenant_id),
            "data_quality": self._factor_data_quality(tenant_id),
            "automation_adoption": self._factor_automation_adoption(tenant_id),
            "response_time": self._factor_response_time(tenant_id),
        }
        score = sum(
            factors[k] * HEALTH_WEIGHTS[k] for k in HEALTH_WEIGHTS
        )
        health = PilotHealth(
            tenant_id=tenant_id,
            health_score=round(score, 1),
            factors={
                **factors,
                "weights": HEALTH_WEIGHTS,
            },
            calculated_at=_utcnow(),
        )
        _health[health.id] = health
        return health

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------
    def _roi_from_metrics(self, metrics: List[PilotMetric]) -> Dict[str, Any]:
        """Cálculo de ROI (horas/costo) a partir de métricas procesadas."""
        counts: Dict[str, float] = defaultdict(float)
        for m in metrics:
            if m.metric_type in (PilotMetricType.CFDI_PROCESSED,
                                 PilotMetricType.BANK_RECONCILED,
                                 PilotMetricType.NOMINA_TIMBRED):
                counts[m.metric_type.value] += m.value

        cfdi_count = counts.get(PilotMetricType.CFDI_PROCESSED.value, 0.0)
        bank_count = counts.get(PilotMetricType.BANK_RECONCILED.value, 0.0)
        nomina_count = counts.get(PilotMetricType.NOMINA_TIMBRED.value, 0.0)

        cfdi_hours = cfdi_count * (CFDI_SAVINGS_MINUTES / 60.0)
        bank_hours = bank_count * (BANK_RECON_SAVINGS_MINUTES / 60.0)
        nomina_hours = nomina_count * NOMINA_SAVINGS_HOURS
        total_hours = cfdi_hours + bank_hours + nomina_hours
        total_cost = total_hours * self.hourly_cost

        # Tasa de automatización global (último registro).
        rates = [m.value for m in metrics
                 if m.metric_type == PilotMetricType.AUTOMATION_RATE]
        automation_rate = rates[-1] if rates else None

        return {
            "hours_saved": round(total_hours, 2),
            "cost_saved_mxn": round(total_cost, 2),
            "breakdown": {
                "cfdi": {"count": cfdi_count, "hours": round(cfdi_hours, 2)},
                "bank_recon": {"count": bank_count, "hours": round(bank_hours, 2)},
                "nomina": {"count": nomina_count, "hours": round(nomina_hours, 2)},
            },
            "automation_rate": automation_rate,
            "accountant_hourly_cost_mxn": self.hourly_cost,
        }

    def get_roi_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Totales de horas ahorradas, costo ahorrado y tasa de automatización."""
        metrics = self.get_tenant_metrics(tenant_id)
        roi = self._roi_from_metrics(metrics)
        return {
            "tenant_id": tenant_id,
            "total_hours_saved": roi["hours_saved"],
            "total_cost_saved_mxn": roi["cost_saved_mxn"],
            "automation_rate_percent": roi["automation_rate"],
            "breakdown": roi["breakdown"],
            "accountant_hourly_cost_mxn": roi["accountant_hourly_cost_mxn"],
        }

    # ------------------------------------------------------------------
    # Reporte
    # ------------------------------------------------------------------
    def generate_pilot_report(self, tenant_id: str, period: str) -> PilotReport:
        """Genera un reporte agregado de métricas + ROI para un período."""
        if not tenant_id or not period:
            raise ValueError("tenant_id y period son obligatorios")
        # Rango de período: acepta "YYYY-MM" (mes completo).
        try:
            y, m = period.split("-")
            start = date(int(y), int(m), 1)
            nxt = date(int(y) + 1, 1, 1) if m == "12" else date(int(y), int(m) + 1, 1)
            end = nxt - timedelta(days=1)
        except (ValueError, IndexError):
            raise ValueError(f"Formato de periodo inválido: {period!r} "
                             "(esperado YYYY-MM)")

        metrics = self.get_tenant_metrics(tenant_id, start, end)
        roi = self._roi_from_metrics(metrics)

        totals: Dict[str, float] = defaultdict(float)
        for m in metrics:
            totals[m.metric_type.value] += m.value

        summary = {
            "period": period,
            "metric_totals": dict(totals),
            "metric_count": len(metrics),
            "roi": roi,
        }
        report = PilotReport(
            tenant_id=tenant_id,
            period=period,
            metrics_summary=summary,
            generated_at=_utcnow(),
        )
        _reports[report.id] = report
        return report
