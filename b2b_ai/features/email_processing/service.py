# -*- coding: utf-8 -*-
"""
service.py — Servicio de Recepción de Correos.

Monitorea la bandeja de entrada, extrae CFDI de adjuntos XML,
valida y clasifica las facturas procesadas.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

from b2b_ai.features.email_processing.models import (
    Attachment,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
)

# ---------------------------------------------------------------------------
# Extensiones válidas para CFDI
# ---------------------------------------------------------------------------
CFDI_EXTENSIONS = {".xml", ".pdf"}
CFDI_CONTENT_TYPES = {
    "application/xml", "text/xml",
    "application/pdf",
}

# Patrones de subject que sugieren facturas
INVOICE_SUBJECT_PATTERNS = [
    r"factura",
    r"cfdi",
    r"comprobante fiscal",
    r"nota de crédito",
    r"recibo de pago",
    r"invoice",
    r"comprobante de pago",
    r"xml.*sat",
    r"timbrad",
]

# Namespaces CFDI 4.0
CFDI_NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}


def _is_cfdi_attachment(att: Attachment) -> bool:
    """Determina si un adjunto es probablemente un CFDI."""
    filename = (att.filename or "").lower()
    # Por extensión
    for ext in CFDI_EXTENSIONS:
        if filename.endswith(ext):
            return True
    # Por content-type
    if att.content_type in CFDI_CONTENT_TYPES:
        return True
    return False


def _looks_like_invoice(subject: str) -> bool:
    """Verifica si el subject parece relacionado con facturas."""
    subject_lower = (subject or "").lower()
    for pattern in INVOICE_SUBJECT_PATTERNS:
        if re.search(pattern, subject_lower):
            return True
    return False


def _parse_cfdi_xml(xml_content: str) -> dict:
    """Parsea un XML CFDI 4.0 y extrae información clave.

    Retorna un dict con emisor, receptor, total, serie, folio, fecha, UUID.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return {"error": "XML inválido"}

    # Quitar namespaces para encontrar atributos
    result = {}

    # Atributos del comprobante
    for attr in ("Serie", "Folio", "Fecha", "Total", "Moneda", "TipoDeComprobante",
                 "MetodoPago", "FormaPago"):
        val = root.get(attr)
        if val:
            result[attr.lower()] = val

    # Emisor
    ns = {"cfdi": "http://www.sat.gob.mx/cfd/4"}
    emisor = root.find(".//cfdi:Emisor", ns)
    if emisor is not None:
        result["emisor_rfc"] = emisor.get("Rfc", "")
        result["emisor_nombre"] = emisor.get("Nombre", "")
        result["emisor_regimen"] = emisor.get("RegimenFiscal", "")

    # Receptor
    receptor = root.find(".//cfdi:Receptor", ns)
    if receptor is not None:
        result["receptor_rfc"] = receptor.get("Rfc", "")
        result["receptor_nombre"] = receptor.get("Nombre", "")

    # UUID del TimbreFiscalDigital
    tfd = root.find(".//tfd:TimbreFiscalDigital", {
        "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital"})
    if tfd is not None:
        result["uuid"] = tfd.get("UUID", "")
        result["fecha_timbrado"] = tfd.get("FechaTimbrado", "")

    return result


def _validate_cfdi(cfdi_data: dict) -> list[str]:
    """Valida los datos básicos de un CFDI.

    Retorna lista de errores (vacía si es válido).
    """
    errors = []

    if not cfdi_data.get("emisor_rfc"):
        errors.append("RFC del emisor ausente")

    if not cfdi_data.get("receptor_rfc"):
        errors.append("RFC del receptor ausente")

    if not cfdi_data.get("total"):
        errors.append("Total ausente o cero")

    if not cfdi_data.get("uuid"):
        errors.append("UUID de timbrado ausente")

    # Validar formato RFC (12 o 13 caracteres)
    for field_name in ("emisor_rfc", "receptor_rfc"):
        rfc = cfdi_data.get(field_name, "")
        if rfc and len(rfc) < 12:
            errors.append(f"{field_name} inválido: '{rfc}' ({len(rfc)} caracteres)")

    # Total debe ser numérico
    total = cfdi_data.get("total", "0")
    try:
        t = float(total)
        if t < 0:
            errors.append("Total negativo")
    except (TypeError, ValueError):
        errors.append(f"Total no numérico: {total}")

    return errors


def monitor_inbox(tenant_id: int,
                  emails: Optional[list[dict]] = None) -> list[EmailMessage]:
    """Monitorea la bandeja de entrada para nuevos correos con CFDI.

    En MVP, recibe una lista de emails simulados. En producción,
    se conectaría a IMAP/Exchange/Gmail API.
    """
    messages = []
    for em in emails or []:
        msg = EmailMessage(
            message_id=em.get("message_id", ""),
            from_address=em.get("from", ""),
            to_address=em.get("to", ""),
            subject=em.get("subject", ""),
            date=em.get("date", ""),
            body=em.get("body", ""),
            tenant_id=tenant_id,
        )
        # Procesar adjuntos
        for att_data in em.get("attachments", []):
            att = Attachment(
                filename=att_data.get("filename", ""),
                content_type=att_data.get("content_type", ""),
                size=att_data.get("size", 0),
            )
            msg.attachments.append(att)
        messages.append(msg)
    return messages


def extract_invoices(emails: list[EmailMessage]) -> list[ExtractedInvoice]:
    """Busca y extrae CFDI de los adjuntos de los correos.

    Filtra por extensión y subject, parsea XML CFDI 4.0.
    """
    invoices = []
    for email in emails:
        # Filtrar por subject
        has_invoice_subject = _looks_like_invoice(email.subject)

        for att in email.attachments:
            if _is_cfdi_attachment(att):
                # Si el subject no parece de factura pero tiene XML,
                # aún lo procesamos (puede ser un CFDI sin subject claro)
                ext_inv = ExtractedInvoice(
                    filename=att.filename,
                    message_id=email.message_id,
                )

                # Intentar parsear si hay contenido XML
                if att.content:
                    try:
                        xml_str = att.content.decode("utf-8") if isinstance(att.content, bytes) else att.content
                        cfdi_data = _parse_cfdi_xml(xml_str)
                        if "error" not in cfdi_data:
                            ext_inv.cfdi_data = cfdi_data
                            ext_inv.emisor_rfc = cfdi_data.get("emisor_rfc", "")
                            ext_inv.receptor_rfc = cfdi_data.get("receptor_rfc", "")
                            try:
                                ext_inv.total = float(cfdi_data.get("total", 0))
                            except (TypeError, ValueError):
                                pass
                            ext_inv.status = "pending"
                        else:
                            ext_inv.status = "error"
                            ext_inv.errors.append(cfdi_data["error"])
                    except (UnicodeDecodeError, ValueError) as e:
                        ext_inv.status = "error"
                        ext_inv.errors.append(f"Error leyendo XML: {e}")
                else:
                    # Sin contenido, marcar como pendiente
                    ext_inv.status = "pending"

                invoices.append(ext_inv)

    return invoices


def process_extracted_invoices(
    invoices: list[ExtractedInvoice],
) -> ProcessingResult:
    """Valida y clasifica las facturas extraídas."""
    result = ProcessingResult(
        total_invoices=len(invoices),
    )

    for inv in invoices:
        if inv.cfdi_data:
            errors = _validate_cfdi(inv.cfdi_data)
            if errors:
                inv.status = "invalid"
                inv.errors = errors
                result.invalid += 1
            else:
                inv.status = "valid"
                result.valid += 1
            result.processed += 1
        elif inv.status == "error":
            result.failed += 1
        else:
            # Sin datos CFDI, marcar como pendiente
            inv.status = "pending"

        result.details.append(inv)

    return result


def notify_user(results: ProcessingResult,
                tenant_id: Optional[int] = None) -> dict:
    """Genera una notificación para el usuario con los resultados.

    En producción, esto enviaría email/WhatsApp/webhook.
    """
    summary_lines = []
    if results.valid > 0:
        summary_lines.append(f"✅ {results.valid} factura(s) válida(s)")
    if results.invalid > 0:
        summary_lines.append(f"❌ {results.invalid} factura(s) inválida(s)")
    if results.failed > 0:
        summary_lines.append(f"⚠️ {results.failed} archivo(s) con error")
    if results.total_invoices == 0:
        summary_lines.append("📭 No se encontraron CFDI en los correos")

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "summary": " | ".join(summary_lines) if summary_lines else "Sin cambios",
        "processed": results.processed,
        "valid": results.valid,
        "invalid": results.invalid,
        "failed": results.failed,
        "total": results.total_invoices,
        "details": [d.to_dict() for d in results.details],
    }
