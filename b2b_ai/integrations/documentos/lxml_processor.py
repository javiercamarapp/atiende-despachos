# -*- coding: utf-8 -*-
"""
lxml_processor.py — Adaptador mock para XML parsing (lxml).
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


class LXMLProcessor(DocumentProcessor):
    """Adaptador mock para lxml (XML parsing)."""

    def __init__(self):
        super().__init__(name="lxml")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        raise NotImplementedError("lxml no soporta generación de PDF")

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        logger.info(f"LXML: parseando XML (mock)")
        return XMLParseResult(success=True, data={"root": "mock_data", "content": request.xml_content[:100]},
                             errors=[], is_valid=True)

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError("lxml no soporta OCR")

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("lxml no soporta Excel")
