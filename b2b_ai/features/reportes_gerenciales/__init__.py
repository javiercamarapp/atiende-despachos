# -*- coding: utf-8 -*-
"""
Módulo Reportes Gerenciales: KPIs, cash flow, P&L y exportación.

Expone:
  - ReportPeriod, TrendDirection, ExportFormat — enums
  - KPI, MonthlyReport, CashFlow, ProfitLoss — core schemas
  - ReportesService — lógica de generación, KPIs, exportación
  - validate_period, validate_amount_range, validate_kpi_threshold — validators
  - build_reportes_gerenciales_router — FastAPI router (/api/v1/reportes/*)
"""
from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    ExportFormat,
    KPI,
    MonthlyReport,
    ProfitLoss,
    ReportPeriod,
    TrendDirection,
)
from b2b_ai.features.reportes_gerenciales.service import ReportesService
from b2b_ai.features.reportes_gerenciales.validators import (
    validate_amount_range,
    validate_kpi_threshold,
    validate_period,
)
from b2b_ai.features.reportes_gerenciales.routes import build_reportes_gerenciales_router

__all__ = [
    # Enums
    "ReportPeriod",
    "TrendDirection",
    "ExportFormat",
    # Schemas
    "KPI",
    "MonthlyReport",
    "CashFlow",
    "ProfitLoss",
    # Service
    "ReportesService",
    # Validators
    "validate_period",
    "validate_amount_range",
    "validate_kpi_threshold",
    # Router
    "build_reportes_gerenciales_router",
]
