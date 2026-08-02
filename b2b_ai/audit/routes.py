# -*- coding: utf-8 -*-
"""routes.py — Endpoints FastAPI de trazabilidad (AuditLogger).

Endpoints:
    GET /api/v1/audit/logs   lista entradas de auditoría con filtros
                             (user, action/event, date range, tenant).

El router exige autenticación por API key (`require_api_key`). La consulta
va sobre la tabla `audit_entries` a través de `AuditLogger.query`.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from b2b_ai.audit.logger import AuditLogger
from b2b_ai.audit.models import AuditEvent


def build_audit_logger_router(db: Any = None, require_api_key: Any = None,
                              auth: Any = None) -> APIRouter:
    """Construye el router de trazabilidad (/api/v1/audit/logs).

    `auth` (opcional) es la instancia de APIKeyAuth: si se provee, se resuelve
    el `tenant_id` de la key autenticada para aislar la consulta por tenant
    (una key de servicio sin tenant ve todo).
    """
    if require_api_key is None:
        raise ValueError("require_api_key es obligatorio. Nunca construir el router sin auth.")
    router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
    _audit_events = {e.value for e in AuditEvent}

    @router.get("/logs", summary="Lista entradas de auditoría (con filtros).")
    def list_audit_logs(
        user: Optional[str] = Query(None, description="Actor (who)"),
        action: Optional[str] = Query(None, description="Evento/acción (what)"),
        event: Optional[str] = Query(None, description="Alias de `action`"),
        from_ts: Optional[str] = Query(None, alias="from",
                                       description="Inicio rango temporal (ISO)"),
        to_ts: Optional[str] = Query(None, alias="to",
                                     description="Fin rango temporal (ISO)"),
        tenant_id: Optional[int] = Query(None, description="Tenant (where)"),
        limit: int = Query(100, ge=1, le=1000),
        auth_info: dict = Depends(require_api_key),
    ):
        # Aislamiento multi-tenant: si hay una key de tenant, SIEMPRE filtra
        # por ese tenant (salvo key de servicio sin tenant, que ve todo).
        effective_tenant = tenant_id
        if auth is not None:
            key = auth_info if isinstance(auth_info, str) else auth_info.get("key")
            try:
                resolved = auth.get_tenant_id(key) if key else None
                if resolved is not None:
                    effective_tenant = int(resolved)
            except Exception:  # noqa: BLE001 — best-effort, no romper
                pass

        event_filter = event or action
        if event_filter is not None and event_filter not in _audit_events:
            event_filter = event_filter.upper()

        logger = AuditLogger(db, auto_start=False)
        entries = logger.query(
            tenant_id=effective_tenant,
            actor=user,
            event=event_filter,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
        return {
            "total": len(entries),
            "limit": limit,
            "entries": [e.to_dict() for e in entries],
        }

    return router
