# -*- coding: utf-8 -*-
"""
ocr_integration.py — Integración de OCR / extracción de datos de documentos.

Expone:
  - extract_text_from_pdf(pdf_bytes) -> str
      Extrae texto plano de un PDF (usa pymupdf si está instalado; fallback a
      pdfplumber). Devuelve "" si no hay texto.
  - extract_cfdi_data_from_xml(xml_bytes) -> dict
      Extrae datos estructurados de un CFDI XML (reusa el parser del proyecto).
  - extract_document_metadata(name, content_type, data) -> dict
      Auto-metadata según categoría (pdf -> texto, xml cfdi -> campos CFDI).
  - vision_ocr_placeholder() -> str
      Placeholder documentado para futura integración de visión por computadora.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# --- PDF -------------------------------------------------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto plano de un PDF.

    Intenta pymupdf (fitz) primero; si no está disponible, usa pdfplumber.
    Devuelve "" si no se pudo extraer texto.
    """
    if not pdf_bytes:
        return ""
    text = _extract_pymupdf(pdf_bytes)
    if text is None:
        text = _extract_pdfplumber(pdf_bytes)
    return (text or "").strip()


def _extract_pymupdf(pdf_bytes: bytes) -> Optional[str]:
    """Extracción con PyMuPDF; None si el módulo no está instalado."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(parts)
    except Exception:
        return ""


def _extract_pdfplumber(pdf_bytes: bytes) -> str:
    """Extracción con pdfplumber (fallback)."""
    try:
        import io
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        return ""


# --- CFDI XML --------------------------------------------------------------

def extract_cfdi_data_from_xml(xml_bytes: bytes) -> Dict[str, Any]:
    """Extrae datos estructurados de un CFDI XML.

    Reusa el parser canónico del proyecto (b2b_ai.cfdi.parser). Si el XML no
    es un CFDI válido, devuelve un dict con error.
    """
    import tempfile
    import os
    from b2b_ai.cfdi.parser import CFDIError, parse_cfdi

    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        os.write(fd, xml_bytes)
        os.close(fd)
        try:
            return parse_cfdi(path)
        except (CFDIError, Exception) as e:
            return {"error": str(e), "es_cfdi": False}
    finally:
        if os.path.exists(path):
            os.remove(path)


# --- Auto-metadata ---------------------------------------------------------

def extract_document_metadata(
    name: str,
    content_type: str,
    data: bytes,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Auto-extrae metadata de un documento según su tipo.

    - PDF  -> extrae texto (primeros N chars) y detecta si parece CFDI.
    - XML  -> intenta parsear CFDI y devuelve campos relevantes.
    """
    name = (name or "").lower()
    metadata: Dict[str, Any] = {}

    if name.endswith(".xml") or (content_type or "").startswith("application/xml"):
        cfdi = extract_cfdi_data_from_xml(data)
        if not cfdi.get("es_cfdi") is False and not cfdi.get("error"):
            metadata["es_cfdi"] = True
            metadata["emisor_rfc"] = cfdi.get("emisor_rfc", "")
            metadata["emisor_nombre"] = cfdi.get("emisor_nombre", "")
            metadata["receptor_rfc"] = cfdi.get("receptor_rfc", "")
            metadata["folio_fiscal"] = cfdi.get("folio_fiscal", "")
            metadata["total"] = str(cfdi.get("total", ""))
            metadata["fecha"] = cfdi.get("fecha", "")
        else:
            metadata["es_cfdi"] = False
            metadata["parse_error"] = cfdi.get("error", "")

    elif name.endswith(".pdf") or (content_type or "") == "application/pdf":
        text = extract_text_from_pdf(data)
        metadata["es_pdf"] = True
        metadata["texto_preview"] = text[:2000]
        metadata["texto_chars"] = len(text)

    else:
        metadata["es_binario"] = True

    if category:
        metadata["categoria_detectada"] = category
    return metadata


def vision_ocr_placeholder() -> str:
    """Placeholder para futura integración de visión por computadora.

    En una iteración futura, escaneos de facturas en papel, constancias e
    identificaciones se procesarán con un modelo de visión que normalice a los
    mismos campos de metadata que `extract_document_metadata`.
    """
    return "vision_ocr_not_implemented"
