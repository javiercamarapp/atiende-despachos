# -*- coding: utf-8 -*-
"""b2b_ai.reports — Generación de reportes PDF profesionales (FASE reportes).

Incluye:
  - pdf_generator.PDFGenerator : motor PDF (reportlab) + exportación HTML.
  - templates/                 : plantillas HTML (Chart.js, moneda MXN,
                                 fechas MX, logo del tenant).
  - router.build_reports_router: endpoints /api/v1/reports/*.

Uso directo (sin API):
    from b2b_ai.reports.pdf_generator import PDFGenerator
    pdf_bytes = PDFGenerator().monthly_summary(tenant_id=1, month="2026-07")
"""
from b2b_ai.reports.pdf_generator import PDFGenerator  # noqa: F401

__all__ = ["PDFGenerator"]
