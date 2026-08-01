# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for email processing.

Validates:
  - Email address format
  - Attachment types (XML, PDF)
  - CFDI XML structure
  - Email message completeness
"""
from __future__ import annotations

import re
from typing import List, Tuple
from xml.etree import ElementTree as ET

from b2b_ai.features.email_processing.models import AttachmentType


# Email pattern (simplified RFC 5322)
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


def validate_email_address(email: str) -> Tuple[bool, List[str]]:
    """Validate an email address format.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if not email or not email.strip():
        errors.append("La dirección de email es obligatoria.")
    elif not _EMAIL_PATTERN.match(email.strip()):
        errors.append(f"Formato de email inválido: '{email}'.")

    return len(errors) == 0, errors


def validate_attachment_type(
    filename: str,
    allowed_types: List[str] = None,
) -> Tuple[bool, AttachmentType, List[str]]:
    """Validate an attachment filename and determine its type.

    Parameters
    ----------
    filename : str
        The attachment filename.
    allowed_types : List[str]
        List of allowed extensions (default: ["xml", "pdf"]).

    Returns
    -------
    (is_valid, attachment_type, list_of_errors).
    """
    if allowed_types is None:
        allowed_types = ["xml", "pdf"]

    errors: List[str] = []

    if not filename or not filename.strip():
        errors.append("El nombre del archivo es obligatorio.")
        return False, AttachmentType.OTHER, errors

    filename = filename.strip().lower()

    # Determine type
    if filename.endswith(".xml"):
        att_type = AttachmentType.XML
    elif filename.endswith(".pdf"):
        att_type = AttachmentType.PDF
    elif any(filename.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif"]):
        att_type = AttachmentType.IMAGE
    else:
        att_type = AttachmentType.OTHER

    # Check if allowed
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in allowed_types:
        errors.append(
            f"Tipo de archivo no permitido: '{ext}'. "
            f"Tipos permitidos: {', '.join(allowed_types)}."
        )
        return False, att_type, errors

    return True, att_type, errors


def validate_cfdi_xml(xml_content: str) -> Tuple[bool, List[str]]:
    """Validate that XML content is a valid CFDI structure.

    Returns (is_valid, list_of_errors).

    Checks:
      - Valid XML syntax
      - Root element is Comprobante
      - Has Version attribute
      - Has Total attribute
      - Contains Emisor element
      - Contains Receptor element
      - Contains TimbreFiscalDigital (UUID)
    """
    errors: List[str] = []

    if not xml_content or not xml_content.strip():
        errors.append("El contenido XML está vacío.")
        return False, errors

    # Parse XML
    try:
        root = ET.fromstring(xml_content.strip())
    except ET.ParseError as e:
        errors.append(f"XML malformado: {str(e)}")
        return False, errors

    # Detect CFDI namespace from root tag
    cfdi_ns = ""
    if "}" in root.tag:
        cfdi_ns = root.tag.split("}")[0].lstrip("{")

    def _find(parent, local_name):
        """Find element with or without namespace."""
        if cfdi_ns:
            result = parent.find(f".//{{{cfdi_ns}}}{local_name}")
            if result is not None:
                return result
        return parent.find(f".//{local_name}")

    # Check root element
    root_tag = root.tag
    # Remove namespace for checking
    if "}" in root_tag:
        root_tag = root_tag.split("}", 1)[1]

    if root_tag != "Comprobante":
        errors.append(
            f"Elemento raíz inválido: '{root_tag}'. "
            "Se esperaba 'Comprobante' (CFDI)."
        )

    # Check required attributes
    for attr in ["Version", "Total", "Fecha"]:
        val = root.get(attr)
        if not val:
            errors.append(f"Falta atributo '{attr}' en el elemento Comprobante.")

    # Check Emisor
    emisor = _find(root, "Emisor")
    if emisor is None:
        errors.append("No se encontró el elemento 'Emisor' en el CFDI.")
    else:
        if not emisor.get("Rfc"):
            errors.append("Falta atributo 'Rfc' en Emisor.")

    # Check Receptor
    receptor = _find(root, "Receptor")
    if receptor is None:
        errors.append("No se encontró el elemento 'Receptor' en el CFDI.")
    else:
        if not receptor.get("Rfc"):
            errors.append("Falta atributo 'Rfc' en Receptor.")

    # Check TimbreFiscalDigital
    tfd = None
    for ns_uri in ["http://www.sat.gob.mx/TimbreFiscalDigital", cfdi_ns, ""]:
        if ns_uri:
            tfd = root.find(f".//{{{ns_uri}}}TimbreFiscalDigital")
        else:
            tfd = root.find(".//TimbreFiscalDigital")
        if tfd is not None:
            break
    if tfd is None:
        errors.append("No se encontró el elemento 'TimbreFiscalDigital' (stamped).")
    else:
        if not tfd.get("UUID"):
            errors.append("Falta atributo 'UUID' en TimbreFiscalDigital.")

    return len(errors) == 0, errors


def validate_email_message(data: dict) -> Tuple[bool, List[str]]:
    """Validate raw email message data dict.

    Returns (is_valid, combined_list_of_errors).
    """
    all_errors: List[str] = []

    # Check from_addr
    from_addr = data.get("from_addr", "")
    is_valid_email, email_errors = validate_email_address(from_addr)
    if not is_valid_email:
        all_errors.extend([f"[Remitente] {e}" for e in email_errors])

    # Check date
    date = data.get("date", "")
    if not date or not str(date).strip():
        all_errors.append("[Fecha] La fecha del email es obligatoria.")

    # Check attachments
    attachments = data.get("attachments", [])
    if not attachments:
        all_errors.append("[Adjuntos] No se encontraron archivos adjuntos.")

    return len(all_errors) == 0, all_errors
