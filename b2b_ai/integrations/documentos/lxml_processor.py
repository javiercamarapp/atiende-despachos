# -*- coding: utf-8 -*-
"""lxml_processor.py — XML parsing and CFDI validation via lxml."""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional
from b2b_ai.integrations.documentos.adapter import DocumentProcessor
from b2b_ai.integrations.documentos.models import (
    ExcelExportRequest, ExcelExportResult, OCRRequest, OCRResult,
    PDFRequest, PDFResult, XMLParseRequest, XMLParseResult,
)
logger = logging.getLogger(__name__)


class LXMLProcessor(DocumentProcessor):
    """XML processing using lxml library."""

    def __init__(self):
        super().__init__(name="LXMLProcessor")

    def generate_pdf(self, request: PDFRequest) -> PDFResult:
        raise NotImplementedError("LXMLProcessor does not generate PDF. Use ReportLabProcessor.")

    def parse_xml(self, request: XMLParseRequest) -> XMLParseResult:
        start = time.time()
        try:
            from lxml import etree
            root = etree.fromstring(request.xml_content.encode("utf-8"))
            data = {}
            tags = request.extract_tags
            if tags:
                ns = {"cfdi": request.namespace} if request.namespace else {}
                for tag in tags:
                    elements = root.findall(f".//{tag}", ns) if ns else root.findall(f".//{tag}")
                    data[tag] = [el.text or el.attrib for el in elements]
            else:
                data = {el.tag: el.text or el.attrib for el in root.iter()}
            if request.xsd_schema:
                try:
                    schema = etree.XMLSchema(etree.fromstring(request.xsd_schema.encode("utf-8")))
                    is_valid = schema.validate(root)
                except Exception:
                    is_valid = False
            else:
                is_valid = True
            elapsed = (time.time() - start) * 1000
            return XMLParseResult(success=True, data=data, is_valid=is_valid)
        except ImportError:
            logger.warning("LXMLProcessor: lxml not installed")
            return XMLParseResult(success=False, errors=["lxml not installed"])
        except Exception as e:
            logger.error(f"LXMLProcessor: parse_xml failed: {e}")
            return XMLParseResult(success=False, errors=[str(e)])

    def extract_text_ocr(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError("LXMLProcessor does not do OCR.")

    def export_excel(self, request: ExcelExportRequest) -> ExcelExportResult:
        raise NotImplementedError("LXMLProcessor does not export Excel.")
