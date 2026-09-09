# -*- coding: utf-8 -*-
"""routes_health.py — Health and metrics endpoints extracted from app.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

from b2b_ai import __version__
from b2b_ai.api.metrics import metrics
from b2b_ai.infrastructure.graceful_shutdown import get_shutdown_state
from b2b_ai.infrastructure.health import database_health_check
from b2b_ai.monitoring.metrics import metrics as prom_metrics
from b2b_ai.monitoring.health import build_health_detailed


def build_health_router(db, require_api_key) -> APIRouter:
    """Build the health/metrics router.

    Endpoints:
        GET  /health           — public health check (reports draining state)
        HEAD /health           — (same)
        GET  /health/live      — liveness probe (public, process alive)
        GET  /health/ready     — readiness probe (public, fails while
                                  draining or if the DB is unreachable)
        GET  /health/detailed  — detailed health (requires API key)
        GET  /metrics          — operational metrics (requires API key)
        GET  /metrics/prometheus — Prometheus text exposition (requires API
                                  key — antes era público sin auth alguna)
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
            "draining": get_shutdown_state()["is_draining"],
        }

    @router.get("/health/live")
    def health_live():
        """Liveness: ¿el proceso está vivo y puede ejecutar código Python?

        NO toca la DB ni ninguna dependencia externa — a propósito. Es para
        el `livenessProbe` del orquestador (k8s/ECS/Railway): si esto falla,
        la respuesta correcta es MATAR y reiniciar el proceso. Nunca falla
        por drenado: un proceso drenando sigue vivo, solo no acepta tráfico
        nuevo (eso lo reporta /health/ready).
        """
        return {
            "status": "alive",
            "service": "b2b-ai",
            "version": __version__,
            "uptime_seconds": metrics.uptime(),
        }

    @router.get("/health/ready")
    def health_ready():
        """Readiness: ¿puede el servicio aceptar tráfico nuevo AHORA MISMO?

        Responde 503 mientras el proceso está drenando (SIGTERM/SIGINT
        recibido — ver `_graceful_shutdown` en api/app.py e
        `infrastructure/graceful_shutdown.py`) o si la base de datos no
        responde. Úsalo para el `readinessProbe`: a diferencia de
        /health/live, esto SÍ debe sacar al pod del balanceo (sin matarlo).
        """
        state = get_shutdown_state()
        if state["is_draining"]:
            return JSONResponse(status_code=503, content={
                "status": "draining",
                "detail": "Service is shutting down, not accepting new traffic.",
                **state,
            })
        comp = database_health_check(db)
        if comp.status == "error":
            return JSONResponse(status_code=503, content={
                "status": "unhealthy", "database": comp.to_dict(),
            })
        return {"status": "ready", "database": comp.to_dict()}

    @router.get("/metrics")
    def metrics_endpoint(auth_info: dict = Depends(require_api_key)):
        """Métricas operativas básicas (request count, latencia por ruta,
        códigos de estado). Requiere API key. Exento de rate-limit."""
        return metrics.snapshot()

    @router.get("/metrics/prometheus")
    def metrics_prometheus(auth_info: dict = Depends(require_api_key)):
        """Métricas en formato Prometheus text exposition (operativas, de
        negocio y custom por tenant). Requiere API key (X-API-Key): antes
        era público, exponiendo conteos de requests, latencias y uso por
        tenant a cualquiera sin credencial. Configura el scraper de
        Prometheus para mandar el header `X-API-Key` (p.ej. vía
        `authorization` + un relay, o un scrape_config con `headers` si tu
        versión de Prometheus lo soporta)."""
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
