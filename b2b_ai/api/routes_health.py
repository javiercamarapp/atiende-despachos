# -*- coding: utf-8 -*-
"""routes_health.py — Health and metrics endpoints extracted from app.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from b2b_ai import __version__
from b2b_ai.api.metrics import metrics
from b2b_ai.monitoring.metrics import metrics as prom_metrics
from b2b_ai.monitoring.health import build_health_detailed


def build_health_router(db, require_api_key) -> APIRouter:
    """Build the health/metrics router.

    Endpoints:
        GET  /health           — public health check
        HEAD /health           — (same)
        GET  /health/detailed  — detailed health (requires API key)
        GET  /metrics          — operational metrics (requires API key)
        GET  /metrics/prometheus — Prometheus text exposition (public)
    """
    router = APIRouter(tags=["system"])

    @router.api_route("/health", methods=["GET", "HEAD"])
    def health():
        return {
            "status": "ok",
            "service": "b2b-ai",
            "version": __version__,
            "backend": "postgresql" if getattr(db, "_is_pg", False) else "sqlite",
            "schema_version": db.schema_version(),
            "invoices": db.count_invoices(),
            "tenants": len(db.list_tenants()),
            "uptime_seconds": metrics.uptime(),
            "total_requests": metrics.total_requests(),
        }

    @router.get("/metrics")
    def metrics_endpoint(auth_info: dict = Depends(require_api_key)):
        """Métricas operativas básicas (request count, latencia por ruta,
        códigos de estado). Requiere API key. Exento de rate-limit."""
        return metrics.snapshot()

    @router.get("/metrics/prometheus")
    def metrics_prometheus():
        """Métricas en formato Prometheus text exposition (operativas, de
        negocio y custom por tenant). Público, exento de rate-limit y de CORS
        para que Prometheus pueda scrapearlo sin auth."""
        prom_metrics.set_tenant_usage(db.get_all_usage())
        return PlainTextResponse(prom_metrics.render_prometheus(),
                                 media_type="text/plain; version=0.0.4; charset=utf-8")

    @router.get("/health/detailed")
    def health_detailed(auth_info: dict = Depends(require_api_key)):
        """Estado detallado del servicio: DB, Redis, disco, memoria, uptime.
        Requiere API key. `status` es "ok" o "degraded"; los
        componentes en falla se listan en `degraded_components`."""
        prom_metrics.set_tenant_usage(db.get_all_usage())
        return build_health_detailed(db, actual_backend="postgresql" if db._is_pg else "sqlite")

    return router
