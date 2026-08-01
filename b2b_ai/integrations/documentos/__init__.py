# -*- coding: utf-8 -*-
"""Módulo de procesamiento de documentos — PDF, XML, OCR, Excel."""

from b2b_ai.integrations.documentos.adapter import DocumentProcessor, DocumentProcessorError
from b2b_ai.integrations.documentos.reportlab_processor import ReportLabProcessor
from b2b_ai.integrations.documentos.lxml_processor import LXMLProcessor
from b2b_ai.integrations.documentos.tesseract_processor import TesseractProcessor
from b2b_ai.integrations.documentos.openpyxl_processor import OpenPyxlProcessor
from b2b_ai.integrations.documentos.models import (
    DocumentType, ExcelExportRequest, ExcelExportResult,
    OCRRequest, OCRResult, PDFRequest, PDFResult,
    ProcessingStatus, XMLParseRequest, XMLParseResult,
)

__all__ = [
    "DocumentProcessor", "DocumentProcessorError",
    "ReportLabProcessor", "LXMLProcessor", "TesseractProcessor", "OpenPyxlProcessor",
    "DocumentType", "ExcelExportRequest", "ExcelExportResult",
    "OCRRequest", "OCRResult", "PDFRequest", "PDFResult",
    "ProcessingStatus", "XMLParseRequest", "XMLParseResult",
]
