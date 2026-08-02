# -*- coding: utf-8 -*-
"""
models.py — Modelos para procesamiento de documentos (PDF, XML, OCR, Excel).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Tipos de documentos soportados."""
    PDF = "pdf"
    XML = "xml"
    XLSX = "xlsx"
    CSV = "csv"
    IMAGE = "image"
    TEXT = "text"


class ProcessingStatus(str, Enum):
    """Estado del procesamiento."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PDFRequest(BaseModel):
    """Solicitud de generación de PDF."""
    template_name: Optional[str] = Field(default=None, description="Nombre de la plantilla")
    data: Dict[str, Any] = Field(default_factory=dict, description="Datos para la plantilla")
    output_path: Optional[str] = Field(default=None, description="Ruta de salida")
    page_size: str = Field(default="letter", description="Tamaño de hoja (letter, A4, legal)")
    orientation: str = Field(default="portrait", description="Orientación (portrait, landscape)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class PDFResult(BaseModel):
    """Resultado de generación de PDF."""
    success: bool = Field(default=True, description="Si fue exitoso")
    file_path: str = Field(default="", description="Ruta del archivo generado")
    file_size: int = Field(default=0, description="Tamaño en bytes")
    num_pages: int = Field(default=0, description="Número de páginas")
    content: Optional[bytes] = Field(default=None, description="Contenido del PDF")
    processing_time_ms: float = Field(default=0.0, description="Tiempo de procesamiento")


class XMLParseRequest(BaseModel):
    """Solicitud de parsing XML."""
    xml_content: str = Field(..., description="Contenido XML")
    xsd_schema: Optional[str] = Field(default=None, description="Schema XSD para validación")
    namespace: Optional[str] = Field(default=None, description="Namespace XML")
    extract_tags: Optional[List[str]] = Field(default=None, description="Tags específicos a extraer")


class XMLParseResult(BaseModel):
    """Resultado de parsing XML."""
    success: bool = Field(default=True, description="Si fue exitoso")
    data: Dict[str, Any] = Field(default_factory=dict, description="Datos extraídos")
    errors: List[str] = Field(default_factory=list, description="Errores de parsing")
    warnings: List[str] = Field(default_factory=list, description="Advertencias")
    is_valid: bool = Field(default=True, description="Si es válido contra schema")


class OCRRequest(BaseModel):
    """Solicitud de OCR."""
    image_path: Optional[str] = Field(default=None, description="Ruta de la imagen")
    image_bytes: Optional[bytes] = Field(default=None, description="Bytes de la imagen")
    language: str = Field(default="spa", description="Idioma (spa=español, eng=inglés)")
    dpi: int = Field(default=300, description="Resolución DPI")
    preprocess: bool = Field(default=True, description="Aplicar preprocesamiento")


class OCRResult(BaseModel):
    """Resultado de OCR."""
    success: bool = Field(default=True, description="Si fue exitoso")
    text: str = Field(default="", description="Texto extraído")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confianza promedio")
    words: List[Dict[str, Any]] = Field(default_factory=list, description="Palabras con bounding box")
    processing_time_ms: float = Field(default=0.0, description="Tiempo de procesamiento")


class ExcelExportRequest(BaseModel):
    """Solicitud de exportación a Excel."""
    data: List[Dict[str, Any]] = Field(..., description="Datos a exportar")
    sheet_name: str = Field(default="Hoja1", description="Nombre de la hoja")
    headers: Optional[List[str]] = Field(default=None, description="Encabezados personalizados")
    column_widths: Optional[Dict[str, int]] = Field(default=None, description="Anchos de columna")
    output_path: Optional[str] = Field(default=None, description="Ruta de salida")


class ExcelExportResult(BaseModel):
    """Resultado de exportación a Excel."""
    success: bool = Field(default=True, description="Si fue exitoso")
    file_path: str = Field(default="", description="Ruta del archivo generado")
    file_size: int = Field(default=0, description="Tamaño en bytes")
    num_rows: int = Field(default=0, description="Filas exportadas")
    num_columns: int = Field(default=0, description="Columnas exportadas")
    content: Optional[bytes] = Field(default=None, description="Contenido del XLSX")
