# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the DIOT API.

Endpoints:
    POST /api/v1/diot/generate       — Generate DIOT from invoice data
    POST /api/v1/diot/validate       — Validate invoice data for DIOT
    GET  /api/v1/diot/download/{id}  — Download DIOT XML
    GET  /api/v1/diot/history        — List DIOT history

The router is built with `build_diot_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.diot.models import DiotEntry, DiotReport
from b2b_ai.features.diot.service import DiotService
from b2b_ai.features.diot.validators import validate_diot_entries


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateDiotRequest(BaseModel):
    """Request to generate a DIOT report."""
    month: int = Field(
        ...,
        ge=1,
        le=12,
        description="Mes de la DIOT (1-12)",
    )
    year: int = Field(
        ...,
        ge=2014,
        le=2099,
        description="Año de la DIOT",
    )
    invoices: List[dict] = Field(
        default_factory=list,
        description="Lista de facturas/CFDI (rfc_tercero, nombre, tipo_operacion, monto_neto, iva_trasladado, iva_acreditable)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ValidateDiotRequest(BaseModel):
    """Request to validate invoice data for DIOT."""
    invoices: List[dict] = Field(
        ...,
        description="Lista de facturas/CFDI a validar",
    )


class DiotResponse(BaseModel):
    """Standard response for DIOT operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_diot_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the DIOT API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory service
    service = DiotService()

    router = APIRouter(prefix="/api/v1/diot", tags=["diot"])

    # -----------------------------------------------------------------------
    # POST /generate — Generate DIOT from invoice data
    # -----------------------------------------------------------------------
    @router.post(
        "/generate",
        summary="Generate DIOT report from invoice data.",
        response_model=None,
    )
    def generate_diot(
        req: GenerateDiotRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Generate a DIOT report for the given period from invoice data."""
        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        report = service.generate_diot(
            month=req.month,
            year=req.year,
            tenant_id=tenant_id,
            invoices=req.invoices,
        )

        return {
            "ok": True,
            "message": f"DIOT generada para {req.month:02d}/{req.year}.",
            "report_id": report.id,
            "report": report.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /validate — Validate invoice data for DIOT
    # -----------------------------------------------------------------------
    @router.post(
        "/validate",
        summary="Validate invoice data before DIOT generation.",
        response_model=None,
    )
    def validate_diot(
        req: ValidateDiotRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Validate invoice data for DIOT compliance."""
        result = service.validate_diot_data(req.invoices)

        return {
            "ok": result.valid,
            "message": "Datos válidos." if result.valid else "Se encontraron errores.",
            "errors": result.errors,
            "warnings": result.warnings,
            "valid_entries": result.valid_entries,
            "total_entries": result.total_entries,
        }

    # -----------------------------------------------------------------------
    # GET /download/{id} — Download DIOT XML
    # -----------------------------------------------------------------------
    @router.get(
        "/download/{report_id}",
        summary="Download DIOT as XML file.",
        response_class=PlainTextResponse,
    )
    def download_diot(
        report_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> str:
        """Download the DIOT report as SAT XML."""
        report = service.get_report(report_id)
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"DIOT report '{report_id}' not found.",
            )
        # Multi-tenant: verify the report belongs to the requesting tenant
        auth_tenant = auth_info.get("tenant_id") if auth_info else None
        if auth_tenant and hasattr(report, "tenant_id") and report.tenant_id:
            if report.tenant_id != auth_tenant:
                raise HTTPException(status_code=403, detail="Acceso denegado: el reporte pertenece a otro tenant.")

        xml_content = service.export_diot_xml(report)
        return xml_content

    # -----------------------------------------------------------------------
    # GET /history — List DIOT history
    # -----------------------------------------------------------------------
    @router.get(
        "/history",
        summary="List DIOT generation history.",
        response_model=None,
    )
    def diot_history(
        tenant_id: Optional[str] = Query(default=None, description="Filter by tenant"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Get list of all DIOT reports for the authenticated tenant."""
        # Multi-tenant: ALWAYS use auth tenant, ignore query param override
        tid = auth_info.get("tenant_id") if auth_info else tenant_id
        reports = service.get_history(tenant_id=tid)

        return {
            "ok": True,
            "total": len(reports),
            "reports": [
                {
                    "id": r.id,
                    "month": r.month,
                    "year": r.year,
                    "estatus": r.estatus.value,
                    "total_operaciones": r.summary.total_operaciones,
                    "total_iva_trasladado": r.summary.total_iva_trasladado,
                    "created_at": r.created_at,
                }
                for r in reports
            ],
        }

    return router
