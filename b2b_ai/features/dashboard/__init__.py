# -*- coding: utf-8 -*-
"""
Módulo Admin Dashboard: API para gestión de clientes, salud del sistema
y métricas de uso.

Expone:
  - ClientSummary, SystemHealth, UsageMetrics, RevenueReport, DashboardOverview
  - DashboardService — lógica de negocio
  - build_dashboard_admin_router() — FastAPI router (/admin/dashboard/*)
"""
from b2b_ai.features.dashboard.models import (
    ClientSummary,
    SystemHealth,
    UsageMetrics,
    DailyMetric,
    RevenueReport,
    DashboardOverview,
)
from b2b_ai.features.dashboard.service import DashboardService
from b2b_ai.features.dashboard.routes import build_dashboard_admin_router

__all__ = [
    "ClientSummary",
    "SystemHealth",
    "UsageMetrics",
    "DailyMetric",
    "RevenueReport",
    "DashboardOverview",
    "DashboardService",
    "build_dashboard_admin_router",
]
