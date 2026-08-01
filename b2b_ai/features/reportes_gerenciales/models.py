# -*- coding: utf-8 -*-
"""
models.py — Modelos de Reportes Gerenciales.

KPI            — Indicador clave de desempeño.
CashFlow       — Análisis de flujo de efectivo.
MonthlyReport  — Reporte financiero mensual con KPIs y métricas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class KPI:
    """Indicador clave de desempeño."""

    name: str = ""
    value: float = 0.0
    unit: str = ""
    trend: str = "stable"  # up, down, stable
    target: Optional[float] = None
    delta_pct: float = 0.0  # cambio porcentual vs anterior

    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "value": round(self.value, 2),
            "unit": self.unit,
            "trend": self.trend,
            "delta_pct": round(self.delta_pct, 2),
        }
        if self.target is not None:
            result["target"] = round(self.target, 2)
        return result


@dataclass
class CashFlow:
    """Análisis de flujo de efectivo."""

    period: str = ""
    inflows: float = 0.0
    outflows: float = 0.0
    net: float = 0.0
    beginning_balance: float = 0.0
    ending_balance: float = 0.0
    projection_next_month: float = 0.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "inflows": round(self.inflows, 2),
            "outflows": round(self.outflows, 2),
            "net": round(self.net, 2),
            "beginning_balance": round(self.beginning_balance, 2),
            "ending_balance": round(self.ending_balance, 2),
            "projection_next_month": round(self.projection_next_month, 2),
            "details": self.details,
        }


@dataclass
class MonthlyReport:
    """Reporte financiero mensual."""

    period: str = ""
    tenant_id: Optional[int] = None
    revenue: float = 0.0
    cost_of_goods: float = 0.0
    gross_profit: float = 0.0
    operating_expenses: float = 0.0
    ebitda: float = 0.0
    taxes: float = 0.0
    net_profit: float = 0.0
    kpis: list[KPI] = field(default_factory=list)
    cash_flow: Optional[CashFlow] = None
    summary: str = ""

    def to_dict(self) -> dict:
        result = {
            "period": self.period,
            "tenant_id": self.tenant_id,
            "revenue": round(self.revenue, 2),
            "cost_of_goods": round(self.cost_of_goods, 2),
            "gross_profit": round(self.gross_profit, 2),
            "operating_expenses": round(self.operating_expenses, 2),
            "ebitda": round(self.ebitda, 2),
            "taxes": round(self.taxes, 2),
            "net_profit": round(self.net_profit, 2),
            "kpis": [k.to_dict() for k in self.kpis],
            "summary": self.summary,
        }
        if self.cash_flow:
            result["cash_flow"] = self.cash_flow.to_dict()
        return result
