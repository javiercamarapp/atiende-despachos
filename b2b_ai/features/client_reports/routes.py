# -*- coding: utf-8 -*-
"""
routes.py — Endpoints REST del módulo Reportes PDF para clientes del despacho.

Endpoints:
    GET  /api/v1/client-reports/{type}            Generar y descargar el PDF.
    GET  /api/v1/client-reports/history           Historial de reportes generados.
    POST /api/v1/client-reports/schedule          Programar reportes automáticos.

El router se construye con `build_client_reports_router(db, require_api_key)`
siguiendo el patrón del proyecto (auth obligatoria).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from b2b_ai.features.client_reports.generator import PDFReportGenerator
from b2b_ai.features.client_reports.models import (
    GenerateReportResponse,
    ReportSchedule,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
    ScheduleRequest,
)
from b2b_ai.features.client_reports.service import ClientReportService


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_client_reports_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router de reportes PDF para clientes (/api/v1/client-reports/*).

    Parameters
    ----------
    db : Database instance (no usado por ahora; el servicio es in-memory).
    require_api_key : dependencia FastAPI de autenticación (obligatoria).
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key
    service = ClientReportService()
    router = APIRouter(prefix="/api/v1/client-reports", tags=["client_reports"])

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _resolve_type(value: str) -> ReportType:
        try:
            return ReportType.from_value(value)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def _validate_period(year: int, month: int) -> None:
        if not (1 <= month <= 12):
            raise HTTPException(
                status_code=400, detail="month debe estar entre 1 y 12."
            )

    def _dispatch(
        report_type: ReportType,
        tenant_id: str,
        year: int,
        month: int,
        account_id: Optional[str] = None,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ):
        """Delega la generación al método correspondiente del servicio."""
        _validate_period(year, month)
        if report_type == ReportType.MONTHLY_TAX:
            return service.generate_monthly_tax_summary(
                tenant_id, year, month, tenant_name, tenant_rfc
            )
        if report_type == ReportType.DIOT_SUMMARY:
            return service.generate_diot_report(
                tenant_id, year, month, tenant_name, tenant_rfc
            )
        if report_type == ReportType.CONCILIACION:
            if not account_id:
                raise HTTPException(
                    status_code=400,
                    detail="account_id es obligatorio para reportes de conciliación.",
                )
            return service.generate_conciliacion_report(
                tenant_id, account_id, year, month, tenant_name, tenant_rfc
            )
        if report_type == ReportType.NOMINA_SUMMARY:
            return service.generate_nomina_summary(
                tenant_id, year, month, tenant_name, tenant_rfc
            )
        if report_type == ReportType.BALANZA:
            return service.generate_balanza(
                tenant_id, year, month, tenant_name, tenant_rfc
            )
        raise HTTPException(status_code=400, detail="Tipo de reporte no soportado.")

    # -----------------------------------------------------------------------
    # GET /history — historial (DEFINIDO ANTES de /{type} para evitar colisión)
    # -----------------------------------------------------------------------
    @router.get(
        "/history",
        summary="Historial de reportes PDF generados.",
        response_model=None,
    )
    def get_history(
        tenant_id: Optional[str] = Query(default=None, description="Filtrar por tenant"),
        report_type: Optional[str] = Query(default=None, description="Filtrar por tipo de reporte"),
        limit: int = Query(default=50, ge=1, le=200),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        rtype = None
        if report_type:
            rtype = _resolve_type(report_type)
        reports = service.list_history(
            tenant_id=tenant_id, report_type=rtype, limit=limit
        )
        return {
            "ok": True,
            "count": len(reports),
            "reports": [r.to_dict() for r in reports],
        }

    # -----------------------------------------------------------------------
    # GET /{type} — generar y descargar PDF
    # -----------------------------------------------------------------------
    @router.get(
        "/{report_type}",
        summary="Genera y descarga el reporte PDF solicitado.",
        response_class=Response,
    )
    def generate_pdf(
        report_type: str,
        tenant_id: str = Query(default="default", description="Tenant (empresa cliente)"),
        year: int = Query(default=..., description="Año del período (ej. 2024)"),
        month: int = Query(default=..., description="Mes del período (1-12)"),
        account_id: Optional[str] = Query(default=None, description="Cuenta contable (solo conciliación)"),
        tenant_name: str = Query(default="", description="Nombre del cliente"),
        tenant_rfc: str = Query(default="", description="RFC del cliente"),
        auth_info: dict = Depends(auth_dep),
    ) -> Response:
        rtype = _resolve_type(report_type)
        report = _dispatch(
            rtype, tenant_id, year, month,
            account_id=account_id, tenant_name=tenant_name, tenant_rfc=tenant_rfc,
        )
        try:
            pdf_bytes = Path(report.file_path).read_bytes()
        except OSError as e:
            raise HTTPException(
                status_code=500, detail=f"No se pudo leer el PDF: {e}"
            )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{report.file_name}"',
                "X-Report-Id": report.id,
            },
        )

    # -----------------------------------------------------------------------
    # POST /schedule — programar reportes automáticos
    # -----------------------------------------------------------------------
    @router.post(
        "/schedule",
        summary="Programa la generación automática de reportes.",
        response_model=None,
    )
    def schedule_report(
        req: ScheduleRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        schedule = service.schedule_report(
            report_type=req.report_type,
            tenant_id=req.tenant_id,
            frequency=req.frequency,
            recipients=req.recipients,
        )
        return {
            "ok": True,
            "message": f"Reporte {req.report_type.label} programado "
                       f"({req.frequency.value}).",
            "schedule": schedule.to_dict(),
        }

    return router
