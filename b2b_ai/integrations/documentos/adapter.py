# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base para procesamiento de documentos.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)

logger = logging.getLogger(__name__)


class DocumentProcessorError(Exception):
    """Error genérico de procesamiento de documentos."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class DocumentProcessor(ABC):
    """Clase base abstracta para procesamiento de documentos."""

    def __init__(self, name: str = "DocumentProcessor"):
        self.name = name
        logger.info(f"DocumentProcessor '{name}' inicializado")

    @abstractmethod
    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        """Genera un PDF."""
        ...

    @abstractmethod
    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        """Parsea un XML."""
        ...

    @abstractmethod
    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        """Extrae texto de una imagen (OCR)."""
        ...

    @abstractmethod
    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        """Exporta datos a Excel."""
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba que el procesador esté disponible."""
        return {
            "adapter": self.name, "status": "connected",
            "message": f"Procesador '{self.name}' disponible",
        }
