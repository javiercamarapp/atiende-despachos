# -*- coding: utf-8 -*-
"""
tesseract_processor.py — Adaptador mock para OCR (Tesseract).
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


class TesseractProcessor(DocumentProcessor):
    """Adaptador mock para Tesseract (OCR)."""

    def __init__(self):
        super().__init__(name="tesseract")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        raise NotImplementedError("Tesseract no soporta generación de PDF")

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        raise NotImplementedError("Tesseract no soporta XML parsing")

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        logger.info(f"Tesseract: extrayendo texto OCR (mock) lang={request.language}")
        return OCRResult(success=True, text="Texto extraído de la imagen (mock OCR)",
                        confidence=0.92, words=[
                            {"text": "Mock", "confidence": 0.95, "bbox": [0, 0, 100, 30]},
                            {"text": "OCR", "confidence": 0.90, "bbox": [110, 0, 200, 30]},
                        ])

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("Tesseract no soporta Excel")
