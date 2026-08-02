# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Email Processing module.

Handles email inbox monitoring, attachment classification, CFDI extraction
from XML/PDF files, and processing result tracking.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


class AttachmentType(str, Enum):
    """Type of email attachment."""
    XML = "xml"
    PDF = "pdf"
    IMAGE = "image"
    OTHER = "other"


class ProcessingStatus(str, Enum):
    """Status of invoice processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EmailMessage(BaseModel):
    """An email message from the inbox."""
    id: Optional[str] = Field(default=None, description="Unique email ID")
    from_addr: str = Field(..., description="Sender email address")
    subject: str = Field(default="", description="Email subject line")
    date: str = Field(..., description="Email date in ISO format or YYYY-MM-DD")
    body: Optional[str] = Field(default=None, description="Email body text")
    attachments: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of attachments: [{filename, content_type, size_bytes}]"
    )
    tenant_id: str = Field(default="default", description="Tenant ID")
    processed: bool = Field(default=False, description="Whether already processed")

    @field_validator("from_addr")
    @classmethod
    def _from_addr_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("from_addr no puede estar vacío")
        return v.strip()


class ExtractedInvoice(BaseModel):
    """An invoice extracted from an email attachment."""
    filename: str = Field(..., description="Source filename")
    cfdi_data: Dict[str, Any] = Field(default_factory=dict, description="Extracted CFDI data")
    status: ProcessingStatus = Field(default=ProcessingStatus.PENDING, description="Processing status")
    errors: List[str] = Field(default_factory=list, description="Processing errors")
    requires_human_review: bool = Field(default=False, description="Requires human review")
    referencia_legal: Optional[str] = Field(default=None, description="Legal reference (CFF Art)")
    email_id: Optional[str] = Field(default=None, description="Source email ID")
    attachment_type: AttachmentType = Field(default=AttachmentType.XML, description="Source attachment type")
    uuid: Optional[str] = Field(default=None, description="CFDI UUID if extracted")
    rfc_emisor: Optional[str] = Field(default=None, description="RFC emisor if extracted")
    rfc_receptor: Optional[str] = Field(default=None, description="RFC receptor if extracted")
    total: Optional[float] = Field(default=None, description="Invoice total if extracted")
    fecha: Optional[str] = Field(default=None, description="Invoice date if extracted")

    @field_validator("filename")
    @classmethod
    def _filename_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("filename no puede estar vacío")
        return v.strip()


class ProcessingResult(BaseModel):
    """Result of processing a batch of emails/invoices."""
    id: Optional[str] = Field(default=None, description="Batch result ID")
    total: int = Field(default=0, description="Total emails scanned")
    processed: int = Field(default=0, description="Successfully processed")
    failed: int = Field(default=0, description="Failed to process")
    skipped: int = Field(default=0, description="Skipped (no attachments, already processed)")
    invoices_found: int = Field(default=0, description="CFDI invoices found in attachments")
    details: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed results per email"
    )
    errors: List[str] = Field(default_factory=list, description="Batch-level errors")
    tenant_id: str = Field(default="default", description="Tenant ID")
    scan_period: Optional[str] = Field(default=None, description="Scan period (YYYY-MM)")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp")


class Attachment(BaseModel):
    """Un archivo adjunto en un email."""
    filename: str = Field(..., description="Nombre del archivo")
    content_type: str = Field(..., description="MIME type del archivo")
    size: int = Field(default=0, description="Tamaño en bytes")
    content: Optional[bytes] = Field(default=None, description="Contenido del archivo")
