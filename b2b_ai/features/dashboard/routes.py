# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Admin Dashboard API.

Endpoints:
    GET /admin/dashboard/overview   — Top-level admin overview
    GET /admin/dashboard/clients    — Paginated client list with filters
    GET /admin/dashboard/clients/{id} — Detailed client view
    GET /admin/dashboard/health     — System health check
    GET /admin/dashboard/usage      — Usage metrics (last 30d)
    GET /admin/dashboard/revenue    — Revenue report

All endpoints require admin auth (API key with admin privileges).
The router is built with `build_dashboard_admin_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from b2b_ai.features.dashboard.service import DashboardService


def build_dashboard_admin_router(
    db: Any,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the admin dashboard API router.

    Parameters
    ----------
    db : Database instance
    require_api_key : FastAPI dependency for auth (injected from app.py)
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key
    router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])

    @router.get(
        "/overview",
        summary="Admin dashboard overview: clients, revenue, CFDI counts.",
        response_model=None,
    )
    def dashboard_overview(auth_info: dict = Depends(auth_dep)) -> dict:
        """Returns top-level admin metrics:
        total clients, active clients, MRR, CFDIs this month.
        """
        svc = DashboardService(db)
        overview = svc.get_dashboard_overview()
        return overview.model_dump()

    @router.get(
        "/clients",
        summary="Paginated list of clients with sorting and filtering.",
        response_model=None,
    )
    def dashboard_clients(
        page: int = Query(default=1, ge=1, description="Page number"),
        page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
        sort_by: str = Query(
            default="name",
            description="Sort field: name, id, invoice_count, monto_total, api_calls",
        ),
        sort_order: str = Query(default="asc", description="Sort order: asc or desc"),
        search: Optional[str] = Query(default=None, description="Search by name or RFC"),
        active_only: bool = Query(default=False, description="Only active clients"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Returns a paginated, sortable, filterable list of clients."""
        svc = DashboardService(db)
        return svc.get_client_list(
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            active_only=active_only,
        )

    @router.get(
        "/clients/{client_id}",
        summary="Detailed view of a single client.",
        response_model=None,
    )
    def dashboard_client_detail(
        client_id: int,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Returns detailed metrics for a specific client."""
        svc = DashboardService(db)
        detail = svc.get_client_detail(client_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Client not found.")
        return detail

    @router.get(
        "/health",
        summary="System health check.",
        response_model=None,
    )
    def dashboard_health(auth_info: dict = Depends(auth_dep)) -> dict:
        """Returns system health: uptime, DB size, error rate."""
        svc = DashboardService(db)
        health = svc.get_system_health()
        return health.model_dump()

    @router.get(
        "/usage",
        summary="Usage metrics for the last N days.",
        response_model=None,
    )
    def dashboard_usage(
        days: int = Query(default=30, ge=1, le=365, description="Number of days"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Returns usage metrics: daily CFDIs, avg processing time, error rate."""
        svc = DashboardService(db)
        metrics = svc.get_usage_metrics(days=days)
        return metrics.model_dump()

    @router.get(
        "/revenue",
        summary="Revenue report: MRR, ARR, churn, per-client average.",
        response_model=None,
    )
    def dashboard_revenue(auth_info: dict = Depends(auth_dep)) -> dict:
        """Returns revenue metrics for the admin."""
        svc = DashboardService(db)
        report = svc.get_revenue_report()
        return report.model_dump()

    return router
