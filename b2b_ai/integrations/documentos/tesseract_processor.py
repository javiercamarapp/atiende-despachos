# -*- coding: utf-8 -*-
"""tesseract_processor.py — OCR via Tesseract."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from b2b_ai.integrations.documentos.adapter import DocumentProcessor
from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)

logger = logging.getLogger(__name__)


class TesseractProcessor(DocumentProcessor):
    """OCR processing using Tesseract (via pytesseract)."""

    def __init__(self):
        super().__init__(name="TesseractProcessor")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        raise NotImplementedError("TesseractProcessor does not generate PDF.")

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        raise NotImplementedError("TesseractProcessor does not parse XML.")

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        start = time.time()
        try:
            import pytesseract
            from PIL import Image

            if request.image_bytes:
                import io
                img = Image.open(io.BytesIO(request.image_bytes))
            elif request.image_path:
                img = Image.open(request.image_path)
            else:
                return OCRResult(success=False, text="", confidence=0.0, processing_time_ms=0)

            text = pytesseract.image_to_string(img, lang=request.language)
            elapsed = (time.time() - start) * 1000
            return OCRResult(success=True, text=text.strip(), confidence=0.85, processing_time_ms=elapsed)
        except ImportError:
            logger.warning("TesseractProcessor: pytesseract/Pillow not installed")
            return OCRResult(success=False, text="", confidence=0.0, processing_time_ms=(time.time() - start) * 1000)
        except Exception as e:
            logger.error(f"TesseractProcessor: OCR failed: {e}")
            return OCRResult(success=False, text="", confidence=0.0, processing_time_ms=(time.time() - start) * 1000)

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("TesseractProcessor does not export Excel.")
