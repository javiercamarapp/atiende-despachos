# -*- coding: utf-8 -*-
"""
Módulo Reportes PDF para clientes del despacho.

Genera documentos PDF profesionales (resumen fiscal mensual, DIOT, conciliación,
nómina y balanza) que el contador entrega a sus propios clientes (empresas).

Expone:
  - ReportType, ReportStatus, ScheduleFrequency — enums
  - ClientReport, ReportSchedule — schemas de núcleo
  - PDFReportGenerator — generador de PDFs (reportlab)
  - ClientReportService — lógica de negocio
  - build_client_reports_router — router FastAPI (/api/v1/client-reports/*)
"""
from b2b_ai.features.client_reports.generator import (
    PDFReportGenerator,
    DEFAULT_DESPACHO,
    LEGAL_DISCLAIMER,
)
from b2b_ai.features.client_reports.models import (
    ClientReport,
    ReportSchedule,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
)
from b2b_ai.features.client_reports.service import ClientReportService
from b2b_ai.features.client_reports.routes import build_client_reports_router

__all__ = [
    # Enums
    "ReportType",
    "ReportStatus",
    "ScheduleFrequency",
    # Schemas
    "ClientReport",
    "ReportSchedule",
    # Generator
    "PDFReportGenerator",
    "DEFAULT_DESPACHO",
    "LEGAL_DISCLAIMER",
    # Service
    "ClientReportService",
    # Router
    "build_client_reports_router",
]
