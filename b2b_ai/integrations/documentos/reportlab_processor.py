# -*- coding: utf-8 -*-
"""
reportlab_processor.py — Adaptador mock para generación de PDF (ReportLab).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.documentos.adapter import DocumentProcessor
from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)

logger = logging.getLogger(__name__)


class ReportLabProcessor(DocumentProcessor):
    """Adaptador mock para ReportLab (PDF generation)."""

    def __init__(self):
        super().__init__(name="reportlab")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        logger.info(f"ReportLab: generando PDF (mock) template={request.template_name}")
        mock_pdf = b"%PDF-1.4 MOCK_PDF_CONTENT"
        return PDFResult(success=True, file_path=request.output_path or "/tmp/output.pdf",
                        file_size=len(mock_pdf), num_pages=1, content=mock_pdf)

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        raise NotImplementedError("ReportLab no soporta XML parsing")

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError("ReportLab no soporta OCR")

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("ReportLab no soporta Excel")
