# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Recepción de Correos.

Endpoints:
    POST /email/scan     — Escanea la bandeja de entrada (simulada).
    POST /email/process  — Procesa CFDI extraídos de correos.
    GET  /email/history  — Historial de correos procesados.
    GET  /email/stats    — Estadísticas de procesamiento.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.email_processing.service import (
    extract_invoices,
    monitor_inbox,
    notify_user,
    process_extracted_invoices,
)
from b2b_ai.features.email_processing.models import ProcessingResult


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class ScanInboxRequest(BaseModel):
    """Request para escanear la bandeja de entrada."""
    tenant_id: int
    emails: list[dict] = Field(
        default_factory=list,
        description="Lista de emails simulados con adjuntos",
    )


class ProcessInvoicesRequest(BaseModel):
    """Request para procesar CFDI extraídos."""
    invoices: list[dict] = Field(
        ..., description="Lista de facturas extraídas (ExtractedInvoice.to_dict())",
    )
    tenant_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_email_processing_router() -> APIRouter:
    """Devuelve un APIRouter con endpoints /email/*.

    Almacena resultados de escaneo y procesamiento en memoria (MVP).
    """
    router = APIRouter(prefix="/email", tags=["email-processing"])

    # Almacén de historial
    _history: list[dict] = []
    _last_results: Optional[dict] = None

    @router.post(
        "/scan",
        summary="Escanea la bandeja de entrada para correos con CFDI.",
        response_model=None,
    )
    def escanear_bandeja(req: ScanInboxRequest):
        """Analiza los correos recibidos buscando adjuntos CFDI.

        Retorna los correos encontrados con sus archivos adjuntos.
        """
        messages = monitor_inbox(tenant_id=req.tenant_id, emails=req.emails)
        invoices = extract_invoices(messages)

        result_data = {
            "tenant_id": req.tenant_id,
            "total_messages": len(messages),
            "total_invoices_found": len(invoices),
            "invoices": [inv.to_dict() for inv in invoices],
            "messages": [m.to_dict() for m in messages],
        }
        _history.append(result_data)
        return {"ok": True, **result_data}

    @router.post(
        "/process",
        summary="Procesa CFDI extraídos de correos.",
        response_model=None,
    )
    def procesar_facturas(req: ProcessInvoicesRequest):
        """Valida y clasifica las facturas CFDI de los correos.

        Retorna estadísticas de procesamiento y notificación.
        """
        from b2b_ai.features.email_processing.models import ExtractedInvoice

        invoices = []
        for inv_data in req.invoices:
            inv = ExtractedInvoice(
                filename=inv_data.get("filename", ""),
                message_id=inv_data.get("message_id", ""),
                cfdi_data=inv_data.get("cfdi_data", {}),
                status=inv_data.get("status", "pending"),
                errors=inv_data.get("errors", []),
                emisor_rfc=inv_data.get("emisor_rfc", ""),
                receptor_rfc=inv_data.get("receptor_rfc", ""),
                total=inv_data.get("total", 0),
            )
            invoices.append(inv)

        result = process_extracted_invoices(invoices)
        notification = notify_user(result, tenant_id=req.tenant_id)

        global _last_results
        _last_results = notification
        _history.append({"type": "processing", **notification})

        return {"ok": True, "result": result.to_dict(), "notification": notification}

    @router.get(
        "/history",
        summary="Historial de correos procesados.",
        response_model=None,
    )
    def historial_correos(
        tenant_id: Optional[int] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        """Lista los escaneos y procesamientos previos."""
        filtered = _history
        if tenant_id is not None:
            filtered = [h for h in _history if h.get("tenant_id") == tenant_id]
        return {
            "ok": True,
            "count": len(filtered[:limit]),
            "history": filtered[:limit],
        }

    @router.get(
        "/stats",
        summary="Estadísticas de procesamiento de correos.",
        response_model=None,
    )
    def estadisticas(
        tenant_id: Optional[int] = Query(default=None),
    ):
        """Retorna métricas agregadas de procesamiento."""
        total_scans = len(_history)
        total_invoices = sum(h.get("total_invoices_found", h.get("total", 0)) for h in _history)
        total_valid = sum(h.get("valid", 0) for h in _history)
        total_invalid = sum(h.get("invalid", 0) for h in _history)

        return {
            "ok": True,
            "total_scans": total_scans,
            "total_invoices": total_invoices,
            "total_valid": total_valid,
            "total_invalid": total_invalid,
        }

    return router
