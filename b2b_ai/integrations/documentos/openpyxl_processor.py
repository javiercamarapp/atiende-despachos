# -*- coding: utf-8 -*-
"""
openpyxl_processor.py — Adaptador mock para exportación Excel (openpyxl).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from b2b_ai.integrations.documentos.adapter import DocumentProcessor
from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)

logger = logging.getLogger(__name__)


class OpenPyxlProcessor(DocumentProcessor):
    """Adaptador mock para openpyxl (Excel export)."""

    def __init__(self):
        super().__init__(name="openpyxl")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        raise NotImplementedError("openpyxl no soporta generación de PDF")

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        raise NotImplementedError("openpyxl no soporta XML parsing")

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError("openpyxl no soporta OCR")

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        logger.info(f"OpenPyxl: exportando Excel (mock) sheet={request.sheet_name}")
        mock_xlsx = b"MOCK_XLSX_CONTENT"
        return ExcelExportResult(success=True, file_path=request.output_path or "/tmp/output.xlsx",
                                file_size=len(mock_xlsx), num_rows=len(request.data),
                                num_columns=len(request.headers or (request.data[0].keys() if request.data else [])),
                                content=mock_xlsx)
