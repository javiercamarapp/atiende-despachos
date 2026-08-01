# -*- coding: utf-8 -*-
"""
service.py — EmailProcessingService: inbox scanning, CFDI extraction, processing pipeline.

Scans email inboxes for messages with XML/PDF attachments, extracts CFDI data
from XML files, validates the structure, and reports results.
"""
from __future__ import annotations

import re
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from b2b_ai.features.email_processing.models import (
    AttachmentType,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
    ProcessingStatus,
)


# ---------------------------------------------------------------------------
# CFDI XML namespace
# ---------------------------------------------------------------------------

_CFDI_NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


# ---------------------------------------------------------------------------
# EmailProcessingService
# ---------------------------------------------------------------------------

class EmailProcessingService:
    """Core service for email-based invoice processing."""

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        # In-memory stores
        self._emails: Dict[str, EmailMessage] = {}
        self._invoices: Dict[str, ExtractedInvoice] = {}
        self._history: List[ProcessingResult] = []

    # -------------------------------------------------------------------
    # Inbox monitoring
    # -------------------------------------------------------------------

    def monitor_inbox(
        self,
        tenant_id: str,
        emails: Optional[List[EmailMessage]] = None,
    ) -> ProcessingResult:
        """Scan inbox for emails with relevant attachments.

        Parameters
        ----------
        tenant_id : str
            Tenant identifier.
        emails : Optional[List[EmailMessage]]
            List of emails to scan (simulated inbox).

        Returns
        -------
        ProcessingResult with scan summary.
        """
        result = ProcessingResult(
            id=str(_uuid.uuid4()),
            tenant_id=tenant_id,
            scan_period=datetime.now().strftime("%Y-%m"),
            created_at=datetime.now().isoformat(),
        )

        if not emails:
            emails = []

        for email in emails:
            email.tenant_id = tenant_id
            if email.id is None:
                email.id = str(_uuid.uuid4())

            # Store email
            self._emails[email.id] = email

            # Check if already processed
            if email.processed:
                result.skipped += 1
                result.details.append({
                    "email_id": email.id,
                    "status": "skipped",
                    "reason": "already_processed",
                })
                continue

            # Check for relevant attachments
            relevant_attachments = self._find_relevant_attachments(email)
            if not relevant_attachments:
                result.skipped += 1
                result.details.append({
                    "email_id": email.id,
                    "status": "skipped",
                    "reason": "no_relevant_attachments",
                })
                continue

            result.total += 1
            result.invoices_found += len(relevant_attachments)
            result.details.append({
                "email_id": email.id,
                "status": "found",
                "attachments": [a.get("filename", "") for a in relevant_attachments],
            })

        self._history.append(result)
        return result

    def _find_relevant_attachments(self, email: EmailMessage) -> List[Dict[str, Any]]:
        """Find XML and PDF attachments in an email."""
        relevant = []
        for att in email.attachments:
            filename = att.get("filename", "").lower()
            content_type = att.get("content_type", "").lower()

            if filename.endswith(".xml") or "xml" in content_type:
                att["type"] = AttachmentType.XML.value
                relevant.append(att)
            elif filename.endswith(".pdf") or "pdf" in content_type:
                att["type"] = AttachmentType.PDF.value
                relevant.append(att)

        return relevant

    # -------------------------------------------------------------------
    # Invoice extraction
    # -------------------------------------------------------------------

    def extract_invoices(
        self,
        email: EmailMessage,
    ) -> List[ExtractedInvoice]:
        """Extract CFDI data from email attachments.

        Parameters
        ----------
        email : EmailMessage
            Email with attachments to process.

        Returns
        -------
        List of ExtractedInvoice with extracted data.
        """
        invoices: List[ExtractedInvoice] = []

        if not email.id:
            email.id = str(_uuid.uuid4())

        for att in email.attachments:
            filename = att.get("filename", "")
            file_type = AttachmentType(att.get("type", "other"))
            xml_content = att.get("content", "")

            if file_type == AttachmentType.XML and xml_content:
                # Parse XML
                try:
                    cfdi_data = self._parse_cfdi_xml(xml_content)
                    invoice = ExtractedInvoice(
                        filename=filename,
                        cfdi_data=cfdi_data,
                        status=ProcessingStatus.COMPLETED,
                        email_id=email.id,
                        attachment_type=AttachmentType.XML,
                        uuid=cfdi_data.get("uuid"),
                        rfc_emisor=cfdi_data.get("rfc_emisor"),
                        rfc_receptor=cfdi_data.get("rfc_receptor"),
                        total=cfdi_data.get("total"),
                        fecha=cfdi_data.get("fecha"),
                    )
                except Exception as e:
                    invoice = ExtractedInvoice(
                        filename=filename,
                        cfdi_data={},
                        status=ProcessingStatus.FAILED,
                        errors=[f"Error parseando XML: {type(e).__name__}: {str(e)}"],
                        email_id=email.id,
                        attachment_type=AttachmentType.XML,
                    )

                self._invoices[invoice.filename] = invoice
                invoices.append(invoice)

            elif file_type == AttachmentType.PDF:
                # PDF extraction is simulated (would need OCR in production)
                invoice = ExtractedInvoice(
                    filename=filename,
                    cfdi_data={"note": "PDF extraction requires OCR — not implemented yet"},
                    status=ProcessingStatus.SKIPPED,
                    errors=["Extracción de PDF no implementada. Se requiere OCR."],
                    email_id=email.id,
                    attachment_type=AttachmentType.PDF,
                )
                invoices.append(invoice)

            else:
                invoice = ExtractedInvoice(
                    filename=filename,
                    cfdi_data={},
                    status=ProcessingStatus.SKIPPED,
                    errors=[f"Tipo de archivo no soportado: {file_type.value}"],
                    email_id=email.id,
                    attachment_type=file_type,
                )
                invoices.append(invoice)

        return invoices

    def _parse_cfdi_xml(self, xml_content: str) -> Dict[str, Any]:
        """Parse CFDI 4.0 XML and extract key fields.

        Parameters
        ----------
        xml_content : str
            Raw XML string content.

        Returns
        -------
        Dict with CFDI data: uuid, rfc_emisor, rfc_receptor, total, fecha, etc.
        """
        root = ET.fromstring(xml_content)

        # Determine namespace from root tag
        data: Dict[str, Any] = {}
        cfdi_ns = ""
        if "}" in root.tag:
            cfdi_ns = root.tag.split("}")[0].lstrip("{")

        # Extract root attributes directly (works with or without namespace)
        for attr in ["Total", "SubTotal", "Fecha", "Version", "TipoDeComprobante",
                     "Moneda", "MetodoPago", "Metodo", "FormaPago", "LugarExpedicion"]:
            val = root.get(attr)
            if val is not None:
                key = attr.lower()
                if key == "total":
                    data["total"] = float(val or "0")
                elif key == "subtotal":
                    data["subtotal"] = float(val or "0")
                elif key == "metodo":
                    data["metodo_pago"] = val
                else:
                    data[key] = val

        # Helper to find element with or without namespace
        def _find(parent, local_name):
            if cfdi_ns:
                result = parent.find(f".//{{{cfdi_ns}}}{local_name}")
                if result is not None:
                    return result
            return parent.find(f".//{local_name}")

        # Extract Emisor (issuer)
        emisor = _find(root, "Emisor")
        if emisor is not None:
            data["rfc_emisor"] = emisor.get("Rfc", "")
            data["nombre_emisor"] = emisor.get("Nombre", "")
            data["regimen_fiscal"] = emisor.get("RegimenFiscal", "")

        # Extract Receptor (recipient)
        receptor = _find(root, "Receptor")
        if receptor is not None:
            data["rfc_receptor"] = receptor.get("Rfc", "")
            data["nombre_receptor"] = receptor.get("Nombre", "")
            data["uso_cfdi"] = receptor.get("UsoCFDI", "")

        # Extract TimbreFiscalDigital (UUID) — try both with TFD namespace and without
        tfd = None
        for ns_uri in ["http://www.sat.gob.mx/TimbreFiscalDigital", cfdi_ns, ""]:
            if ns_uri:
                tfd = root.find(f".//{{{ns_uri}}}TimbreFiscalDigital")
            else:
                tfd = root.find(".//TimbreFiscalDigital")
            if tfd is not None:
                break
        if tfd is not None:
            data["uuid"] = tfd.get("UUID", "")
            data["fecha_timbrado"] = tfd.get("FechaTimbrado", "")
            data["no_certificado"] = tfd.get("NoCertificadoSAT", "")
            data["rfc_prov"] = tfd.get("RfcProvCertif", "")

        # Extract conceptos (line items)
        conceptos = _find(root, "Concepto")
        if conceptos is None:
            conceptos = ET.Element("dummy")  # empty
        # If _find returns a list-like result, iterate
        data["conceptos"] = []
        for conc in ([conceptos] if conceptos.tag.endswith("Concepto") else conceptos.findall(f"{{{cfdi_ns}}}Concepto") if cfdi_ns else conceptos.findall("Concepto")):
            data["conceptos"].append({
                "clave_prod_serv": conc.get("ClaveProdServ", ""),
                "no_identificacion": conc.get("NoIdentificacion", ""),
                "cantidad": conc.get("Cantidad", ""),
                "clave_unidad": conc.get("ClaveUnidad", ""),
                "descripcion": conc.get("Descripcion", ""),
                "valor_unitario": conc.get("ValorUnitario", ""),
                "importe": conc.get("Importe", ""),
            })

        return data

    # -------------------------------------------------------------------
    # Processing pipeline
    # -------------------------------------------------------------------

    def process_extracted_invoices(
        self,
        invoices: List[ExtractedInvoice],
    ) -> ProcessingResult:
        """Process a batch of extracted invoices: validate, store, and report.

        Parameters
        ----------
        invoices : List[ExtractedInvoice]
            Invoices to process.

        Returns
        -------
        ProcessingResult with processing summary.
        """
        result = ProcessingResult(
            id=str(_uuid.uuid4()),
            tenant_id=self.tenant_id,
            created_at=datetime.now().isoformat(),
        )

        for inv in invoices:
            result.total += 1

            if inv.status == ProcessingStatus.FAILED:
                result.failed += 1
                result.details.append({
                    "filename": inv.filename,
                    "status": "failed",
                    "errors": inv.errors,
                })
                continue

            if inv.status == ProcessingStatus.SKIPPED:
                result.skipped += 1
                result.details.append({
                    "filename": inv.filename,
                    "status": "skipped",
                    "reason": inv.errors[0] if inv.errors else "unknown",
                })
                continue

            # Validate CFDI data
            is_valid, validation_errors = self._validate_extracted_cfdi(inv)

            if is_valid:
                inv.status = ProcessingStatus.COMPLETED
                result.processed += 1
                result.details.append({
                    "filename": inv.filename,
                    "status": "completed",
                    "uuid": inv.uuid,
                    "total": inv.total,
                })
            else:
                inv.status = ProcessingStatus.FAILED
                inv.errors = validation_errors
                result.failed += 1
                result.details.append({
                    "filename": inv.filename,
                    "status": "failed",
                    "errors": validation_errors,
                })

            # Store
            self._invoices[inv.filename] = inv

        self._history.append(result)
        return result

    def _validate_extracted_cfdi(self, invoice: ExtractedInvoice) -> tuple:
        """Validate extracted CFDI data.

        Returns (is_valid, list_of_errors).
        """
        errors: List[str] = []
        data = invoice.cfdi_data

        # Check UUID
        if not invoice.uuid:
            uuid_val = data.get("uuid", "")
            if uuid_val:
                invoice.uuid = uuid_val
            else:
                errors.append("No se encontró UUID en el CFDI.")

        # Check RFCs
        if not invoice.rfc_emisor:
            invoice.rfc_emisor = data.get("rfc_emisor", "")
        if not invoice.rfc_receptor:
            invoice.rfc_receptor = data.get("rfc_receptor", "")

        if not invoice.rfc_emisor:
            errors.append("No se encontró RFC del emisor.")
        elif len(invoice.rfc_emisor) < 3:
            errors.append(f"RFC emisor inválido: '{invoice.rfc_emisor}'.")

        if not invoice.rfc_receptor:
            errors.append("No se encontró RFC del receptor.")
        elif len(invoice.rfc_receptor) < 3:
            errors.append(f"RFC receptor inválido: '{invoice.rfc_receptor}'.")

        # Check total
        if invoice.total is None:
            total_val = data.get("total", 0)
            if isinstance(total_val, (int, float)):
                invoice.total = total_val
            else:
                errors.append("No se encontró el total del CFDI.")

        # Check fecha
        if not invoice.fecha:
            invoice.fecha = data.get("fecha", "")

        return len(errors) == 0, errors

    # -------------------------------------------------------------------
    # Notification
    # -------------------------------------------------------------------

    def notify_user(self, results: ProcessingResult) -> Dict[str, Any]:
        """Generate a user notification summary from processing results.

        Parameters
        ----------
        results : ProcessingResult
            The processing results to notify about.

        Returns
        -------
        Notification dict with summary and details.
        """
        # Build notification message
        if results.failed > 0:
            severity = "warning"
            status_msg = f"{results.processed} facturas procesadas, {results.failed} fallidas."
        elif results.processed > 0:
            severity = "success"
            status_msg = f"{results.processed} facturas procesadas exitosamente."
        else:
            severity = "info"
            status_msg = "No se encontraron facturas nuevas para procesar."

        return {
            "severity": severity,
            "title": "Resultado de procesamiento de facturas",
            "message": status_msg,
            "summary": {
                "total_scanned": results.total,
                "processed": results.processed,
                "failed": results.failed,
                "skipped": results.skipped,
                "invoices_found": results.invoices_found,
            },
            "details": results.details[:10],  # Limit details for notification
            "tenant_id": results.tenant_id,
            "timestamp": results.created_at or datetime.now().isoformat(),
        }

    # -------------------------------------------------------------------
    # History & stats
    # -------------------------------------------------------------------

    def get_history(self, limit: int = 10) -> List[ProcessingResult]:
        """Get processing history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics across all batches."""
        total_processed = sum(r.processed for r in self._history)
        total_failed = sum(r.failed for r in self._history)
        total_scanned = sum(r.total for r in self._history)
        total_invoices = sum(r.invoices_found for r in self._history)

        return {
            "total_batches": len(self._history),
            "total_emails_scanned": total_scanned,
            "total_invoices_found": total_invoices,
            "total_processed": total_processed,
            "total_failed": total_failed,
            "success_rate": round(
                (total_processed / max(total_processed + total_failed, 1)) * 100, 2
            ),
            "invoices_in_store": len(self._invoices),
        }
