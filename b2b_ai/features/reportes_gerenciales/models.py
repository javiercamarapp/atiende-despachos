# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Management Reports module.

Handles monthly financial reports, KPI dashboards, cash flow analysis,
and profit & loss statements for Mexican enterprise accounting.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


class ReportPeriod(str, Enum):
    """Reporting period granularity."""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class TrendDirection(str, Enum):
    """Trend direction for KPIs."""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class ExportFormat(str, Enum):
    """Export format for reports."""
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    XLSX = "xlsx"


class KPI(BaseModel):
    """Key Performance Indicator for management dashboards."""
    name: str = Field(..., description="KPI name (e.g. 'Ingresos Mensuales', 'Margen Bruto')")
    value: float = Field(..., description="Current KPI value")
    unit: Optional[str] = Field(default=None, description="Unit: MXN, %, days, count")
    trend: TrendDirection = Field(default=TrendDirection.STABLE, description="Trend direction")
    change_pct: Optional[float] = Field(default=None, description="Percentage change vs previous period")
    target: Optional[float] = Field(default=None, description="Target value")
    category: Optional[str] = Field(default=None, description="KPI category: financial, operational, compliance")

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name no puede estar vacío")
        return v.strip()


class MonthlyReport(BaseModel):
    """Monthly financial summary report."""
    id: Optional[str] = Field(default=None, description="Report ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    tenant_id: str = Field(default="default", description="Tenant ID")
    revenue: float = Field(default=0.0, description="Total revenue (ingresos)")
    expenses: float = Field(default=0.0, description="Total expenses (egresos)")
    profit: float = Field(default=0.0, description="Net profit (utilidad)")
    taxes_paid: float = Field(default=0.0, description="Taxes paid (impuestos pagados)")
    invoices_count: int = Field(default=0, description="Number of invoices processed")
    kpis: List[KPI] = Field(default_factory=list, description="List of KPIs for this period")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp")

    @field_validator("period")
    @classmethod
    def _period_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Formato de período inválido '{v}'. Se esperaba YYYY-MM.")
        return v


class CashFlow(BaseModel):
    """Cash flow analysis for a period."""
    id: Optional[str] = Field(default=None, description="Cash flow ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    tenant_id: str = Field(default="default", description="Tenant ID")
    opening_balance: float = Field(default=0.0, description="Opening balance")
    inflows: float = Field(default=0.0, description="Total cash inflows")
    outflows: float = Field(default=0.0, description="Total cash outflows")
    net: float = Field(default=0.0, description="Net cash flow (inflows - outflows)")
    closing_balance: float = Field(default=0.0, description="Closing balance")
    projection: Optional[Dict[str, Any]] = Field(default=None, description="Cash flow projection for next period")
    categories: Dict[str, float] = Field(default_factory=dict, description="Breakdown by category")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp")

    @field_validator("period")
    @classmethod
    def _period_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Formato de período inválido '{v}'. Se esperaba YYYY-MM.")
        return v


class ProfitLoss(BaseModel):
    """Profit & Loss (Estado de Resultados) statement."""
    id: Optional[str] = Field(default=None, description="P&L ID")
    period: str = Field(..., description="Period in YYYY-MM format")
    tenant_id: str = Field(default="default", description="Tenant ID")
    income: float = Field(default=0.0, description="Total income (ingresos)")
    cost_of_goods_sold: float = Field(default=0.0, description="Cost of goods sold (costo de ventas)")
    gross_profit: float = Field(default=0.0, description="Gross profit (utilidad bruta)")
    operating_expenses: float = Field(default=0.0, description="Operating expenses (gastos operativos)")
    operating_profit: float = Field(default=0.0, description="Operating profit (utilidad operativa)")
    other_income: float = Field(default=0.0, description="Other income (otros ingresos)")
    other_expenses: float = Field(default=0.0, description="Other expenses (otros gastos)")
    pre_tax_profit: float = Field(default=0.0, description="Pre-tax profit (utilidad antes de impuestos)")
    taxes: float = Field(default=0.0, description="Taxes (impuestos)")
    net_profit: float = Field(default=0.0, description="Net profit (utilidad neta)")
    margin_pct: Optional[float] = Field(default=None, description="Net profit margin as %")
    cost_breakdown: Dict[str, float] = Field(default_factory=dict, description="Cost breakdown by category")
    expense_breakdown: Dict[str, float] = Field(default_factory=dict, description="Expense breakdown by category")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp")

    @field_validator("period")
    @classmethod
    def _period_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Formato de período inválido '{v}'. Se esperaba YYYY-MM.")
        return v
