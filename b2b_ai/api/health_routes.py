# -*- coding: utf-8 -*-
"""health_routes.py — Endpoints de health check del MVP (readiness).

    GET /api/v1/health       — status básico (app up + versión).
    GET /api/v1/health/deep  — readiness completo: import / rutas / modelos
                               por cada feature module + DB.

Ambos son PÚBLICOS (no requieren API key): son endpoints de monitoreo que el
orquestador (K8s / ECS / cron) debe poder consultar sin credenciales.

Montado en `create_app` vía `app.include_router(build_health_routes(db))`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from b2b_ai.api.health import basic_health_payload, deep_health_payload


def build_health_routes(db: Any = None) -> APIRouter:
    """Construye el router de health check del MVP.

    `db` (Database opcional) se inyecta para que /health/deep verifique
    conectividad real a la base de datos.
    """
    router = APIRouter(prefix="/api/v1/health", tags=["system", "health"])

    @router.get("", summary="Health check básico (app up).")
    def health_basic():
        return basic_health_payload()

    @router.get("/deep", summary="Readiness profundo por módulo.")
    def health_deep():
        return deep_health_payload(db=db)

    return router
