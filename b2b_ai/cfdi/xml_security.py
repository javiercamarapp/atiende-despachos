# -*- coding: utf-8 -*-
"""
xml_security.py — Safe XML parsing utilities for CFDI/contabilidad.

Provides secure wrappers that prevent:
- XXE (XML External Entity) attacks — CWE-611
- XML bomb / billion laughs — entity expansion DoS
- SSRF via external DTD loading

All XML parsing in the project MUST go through these helpers.
"""
from __future__ import annotations

import os
from lxml import etree

# Maximum XML file size: 10 MB (prevents OOM from huge/malicious files)
MAX_XML_BYTES = 10 * 1024 * 1024


def safe_parser() -> etree.XMLParser:
    """Return an lxml XMLParser hardened against XXE and XML bombs.

    Disables:
    - resolve_entities: prevents &xxe; entity expansion
    - no_network: blocks HTTP/FTP fetching of external DTDs
    - dtd_validation / load_dtd: prevents DTD-based attacks
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
    )


def safe_parse(xml_path: str) -> etree._ElementTree:
    """Parse an XML file safely, with size limit and XXE protection.

    Raises:
        OSError: If file not found.
        ValueError: If file exceeds MAX_XML_BYTES.
        etree.XMLSyntaxError: If XML is malformed.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")
    size = os.path.getsize(xml_path)
    if size > MAX_XML_BYTES:
        raise ValueError(
            f"XML excede el límite de {MAX_XML_BYTES // (1024*1024)} MB "
            f"({size} bytes). Posible XML bomb o archivo demasiado grande."
        )
    return etree.parse(xml_path, parser=safe_parser())


def safe_fromstring(xml_bytes: bytes) -> etree._Element:
    """Parse XML from bytes safely, with size limit and XXE protection.

    Raises:
        ValueError: If bytes exceed MAX_XML_BYTES.
        etree.XMLSyntaxError: If XML is malformed.
    """
    if len(xml_bytes) > MAX_XML_BYTES:
        raise ValueError(
            f"XML excede el límite de {MAX_XML_BYTES // (1024*1024)} MB "
            f"({len(xml_bytes)} bytes). Posible XML bomb."
        )
    return etree.fromstring(xml_bytes, parser=safe_parser())
