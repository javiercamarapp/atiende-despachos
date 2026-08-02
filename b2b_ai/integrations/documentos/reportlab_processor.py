# -*- coding: utf-8 -*-
"""reportlab_processor.py — PDF generation via ReportLab."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from b2b_ai.integrations.documentos.adapter import DocumentProcessor
from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)

logger = logging.getLogger(__name__)


class ReportLabProcessor(DocumentProcessor):
    """PDF generation using ReportLab library."""

    def __init__(self):
        super().__init__(name="ReportLabProcessor")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        start = time.time()
        try:
            from reportlab.lib.pagesizes import letter, A4, legal
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import inch

            sizes = {"letter": letter, "A4": A4, "legal": legal}
            page_size = sizes.get(request.page_size, letter)
            output = request.output_path or "/tmp/reportlab_output.pdf"
            c = canvas.Canvas(output, pagesize=page_size)
            y = page_size[1] - inch
            for key, val in request.data.items():
                c.drawString(inch, y, f"{key}: {val}")
                y -= 14
                if y < inch:
                    c.showPage()
                    y = page_size[1] - inch
            c.save()
            size = os.path.getsize(output)
            elapsed = (time.time() - start) * 1000
            return PDFResult(success=True, file_path=output, file_size=size, num_pages=1, processing_time_ms=elapsed)
        except ImportError:
            logger.warning("ReportLabProcessor: reportlab not installed")
            return PDFResult(success=False, file_path="", processing_time_ms=(time.time() - start) * 1000)
        except Exception as e:
            logger.error(f"ReportLabProcessor: generate_pdf failed: {e}")
            return PDFResult(success=False, file_path="", processing_time_ms=(time.time() - start) * 1000)

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        raise NotImplementedError("ReportLabProcessor does not parse XML. Use LXMLProcessor.")

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError("ReportLabProcessor does not do OCR. Use TesseractProcessor.")

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("ReportLabProcessor does not export Excel. Use OpenPyxlProcessor.")
