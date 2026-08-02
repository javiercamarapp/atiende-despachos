# -*- coding: utf-8 -*-
"""api.py — Endpoints FastAPI de auditoría.

Endpoints:
    GET /api/v1/audit/logs        lista con paginación
    GET /api/v1/audit/logs/{id}   detalle de una entrada
    GET /api/v1/audit/export      exporta como CSV/JSON
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.audit.trail import AuditTrail


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AuditLogResponse(BaseModel):
    total: int = 0
    entries: list = []


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_audit_router(db, require_api_key):
    """Devuelve un APIRouter /api/v1/audit/*."""
    router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

    @router.get("/logs", summary="Lista de entradas de auditoría (paginado).")
    def list_audit_logs(
        page: int = Query(1, ge=1),
        limit: int = Query(50, ge=1, le=500),
        action: Optional[str] = None,
        resource: Optional[str] = None,
        user_id: Optional[str] = None,
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = auth_info.get("tenant_id")
        trail = AuditTrail(db)
        filters: dict = {
            "limit": limit,
        }
        if action:
            filters["action"] = action
        if resource:
            filters["resource"] = resource
        if user_id:
            filters["user_id"] = user_id
        entries = trail.get_audit_log(tenant_id, filters)
        # Paginación manual (offset simple con slice)
        offset = (page - 1) * limit
        page_entries = entries[offset: offset + limit]
        return {
            "total": len(entries),
            "page": page,
            "limit": limit,
            "entries": [e.to_dict() for e in page_entries],
        }

    @router.get("/logs/{entry_id}", summary="Detalle de una entrada de auditoría.")
    def get_audit_entry(
        entry_id: int,
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = auth_info.get("tenant_id")
        trail = AuditTrail(db)
        entries = trail.get_audit_log(tenant_id, {"limit": 100000})
        for e in entries:
            if e.id == entry_id:
                return e.to_dict()
        raise HTTPException(404, "Entrada de auditoría no encontrada.")

    @router.get("/export", summary="Exporta audit log como CSV o JSON.")
    def export_audit_logs(
        format: str = Query("json", regex="^(json|csv)$"),
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = auth_info.get("tenant_id")
        trail = AuditTrail(db)
        content = trail.export_audit_log(tenant_id, format=format)
        media = "text/csv" if format == "csv" else "application/json"
        from fastapi.responses import Response
        return Response(content=content, media_type=media)

    return router
