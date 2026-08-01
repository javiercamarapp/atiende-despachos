# -*- coding: utf-8 -*-
"""
models.py — Modelos de Recepción de Correos.

EmailMessage      — Mensaje de correo con archivos adjuntos.
ExtractedInvoice  — Factura CFDI extraída de un correo.
ProcessingResult  — Resultado del procesamiento de correos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Attachment:
    """Archivo adjunto de un correo."""

    filename: str = ""
    content_type: str = ""
    size: int = 0
    content: bytes = b""

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }


@dataclass
class EmailMessage:
    """Mensaje de correo electrónico."""

    message_id: str = ""
    from_address: str = ""
    to_address: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    tenant_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "from": self.from_address,
            "to": self.to_address,
            "subject": self.subject,
            "date": self.date,
            "body": self.body[:200],  # Truncar para preview
            "attachment_count": len(self.attachments),
            "attachments": [a.to_dict() for a in self.attachments],
            "tenant_id": self.tenant_id,
        }


@dataclass
class ExtractedInvoice:
    """Factura CFDI extraída de un correo."""

    filename: str = ""
    message_id: str = ""
    cfdi_data: dict = field(default_factory=dict)
    status: str = "pending"  # pending, valid, invalid, error
    errors: list[str] = field(default_factory=list)
    emisor_rfc: str = ""
    receptor_rfc: str = ""
    total: float = 0.0

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "message_id": self.message_id,
            "status": self.status,
            "errors": self.errors,
            "emisor_rfc": self.emisor_rfc,
            "receptor_rfc": self.receptor_rfc,
            "total": round(self.total, 2),
        }


@dataclass
class ProcessingResult:
    """Resultado del procesamiento de correos."""

    total_emails: int = 0
    emails_with_cfdi: int = 0
    total_invoices: int = 0
    processed: int = 0
    failed: int = 0
    valid: int = 0
    invalid: int = 0
    details: list[ExtractedInvoice] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_emails": self.total_emails,
            "emails_with_cfdi": self.emails_with_cfdi,
            "total_invoices": self.total_invoices,
            "processed": self.processed,
            "failed": self.failed,
            "valid": self.valid,
            "invalid": self.invalid,
            "details": [d.to_dict() for d in self.details],
        }
