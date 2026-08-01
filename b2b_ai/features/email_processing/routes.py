# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Email Processing API.

Endpoints:
    POST /api/v1/email/scan     — Scan inbox for invoice emails
    POST /api/v1/email/process  — Process extracted invoices
    GET  /api/v1/email/history  — Get processing history
    GET  /api/v1/email/stats    — Get processing statistics

The router is built with `build_email_processing_router(db, require_api_key)`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.email_processing.models import (
    AttachmentType,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
    ProcessingStatus,
)
from b2b_ai.features.email_processing.service import EmailProcessingService
from b2b_ai.features.email_processing.validators import (
    validate_attachment_type,
    validate_cfdi_xml,
    validate_email_address,
    validate_email_message,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AttachmentData(BaseModel):
    """Attachment data within an email."""
    filename: str = Field(..., description="Attachment filename")
    content_type: str = Field(default="application/octet-stream", description="MIME type")
    size_bytes: int = Field(default=0, ge=0, description="File size in bytes")
    content: Optional[str] = Field(default=None, description="File content (base64 or raw for XML)")
    type: Optional[str] = Field(default=None, description="Attachment type (xml, pdf, etc.)")


class ScanRequest(BaseModel):
    """Request to scan inbox for invoice emails."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    emails: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of email dicts: {from_addr, subject, date, attachments}"
    )


class ProcessRequest(BaseModel):
    """Request to process extracted invoices."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    invoices: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of extracted invoice dicts"
    )


class EmailAddRequest(BaseModel):
    """Request to add an email for processing."""
    tenant_id: str = Field(default="default", description="Tenant ID")
    from_addr: str = Field(..., description="Sender email address")
    subject: str = Field(default="", description="Email subject")
    date: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Email date")
    attachments: List[AttachmentData] = Field(default_factory=list, description="Attachments")


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_email_processing_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the email processing API router.

    Parameters
    ----------
    db : Database instance.
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory stores
    _services: Dict[str, EmailProcessingService] = {}
    _pending_emails: Dict[str, List[EmailMessage]] = {}

    def _get_service(tenant_id: str) -> EmailProcessingService:
        if tenant_id not in _services:
            _services[tenant_id] = EmailProcessingService(tenant_id=tenant_id)
        return _services[tenant_id]

    router = APIRouter(prefix="/api/v1/email", tags=["email_processing"])

    # -----------------------------------------------------------------------
    # POST /scan — Scan inbox for invoice emails
    # -----------------------------------------------------------------------
    @router.post(
        "/scan",
        summary="Scan inbox for emails with XML/PDF attachments.",
        response_model=None,
    )
    def scan_inbox(
        req: ScanRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Scan a list of emails for attachments that could be CFDI invoices."""
        service = _get_service(req.tenant_id)

        # Convert dicts to EmailMessage objects
        emails: List[EmailMessage] = []
        for email_data in req.emails:
            try:
                # Validate email
                is_valid, errors = validate_email_message(email_data)
                if not is_valid:
                    continue

                email = EmailMessage(
                    from_addr=email_data.get("from_addr", ""),
                    subject=email_data.get("subject", ""),
                    date=email_data.get("date", datetime.now().isoformat()),
                    attachments=email_data.get("attachments", []),
                    tenant_id=req.tenant_id,
                )
                emails.append(email)
            except Exception:
                continue

        # Scan
        result = service.monitor_inbox(req.tenant_id, emails)

        # Also extract invoices from found emails
        all_invoices: List[ExtractedInvoice] = []
        for email in emails:
            relevant = service._find_relevant_attachments(email)
            if relevant:
                invoices = service.extract_invoices(email)
                all_invoices.extend(invoices)

        return {
            "ok": True,
            "scan_result": result.model_dump(),
            "invoices_extracted": len(all_invoices),
            "invoices": [inv.model_dump() for inv in all_invoices],
        }

    # -----------------------------------------------------------------------
    # POST /process — Process extracted invoices
    # -----------------------------------------------------------------------
    @router.post(
        "/process",
        summary="Process a batch of extracted invoices.",
        response_model=None,
    )
    def process_invoices(
        req: ProcessRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Validate and process extracted CFDI invoices."""
        service = _get_service(req.tenant_id)

        # Convert dicts to ExtractedInvoice objects
        invoices: List[ExtractedInvoice] = []
        for inv_data in req.invoices:
            try:
                invoice = ExtractedInvoice(
                    filename=inv_data.get("filename", "unknown.xml"),
                    cfdi_data=inv_data.get("cfdi_data", {}),
                    status=ProcessingStatus(inv_data.get("status", "pending")),
                    email_id=inv_data.get("email_id"),
                    uuid=inv_data.get("uuid"),
                    rfc_emisor=inv_data.get("rfc_emisor"),
                    rfc_receptor=inv_data.get("rfc_receptor"),
                    total=inv_data.get("total"),
                    fecha=inv_data.get("fecha"),
                )
                invoices.append(invoice)
            except Exception as e:
                # Add as failed
                invoices.append(ExtractedInvoice(
                    filename=inv_data.get("filename", "unknown.xml"),
                    status=ProcessingStatus.FAILED,
                    errors=[f"Error creando invoice: {str(e)}"],
                ))

        # Process
        result = service.process_extracted_invoices(invoices)

        # Generate notification
        notification = service.notify_user(result)

        return {
            "ok": True,
            "result": result.model_dump(),
            "notification": notification,
        }

    # -----------------------------------------------------------------------
    # POST /add — Add an email for processing
    # -----------------------------------------------------------------------
    @router.post(
        "/add",
        summary="Add an email to the processing queue.",
        response_model=None,
    )
    def add_email(
        req: EmailAddRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Add an email with attachments for processing."""
        # Validate
        is_valid_email, email_errors = validate_email_address(req.from_addr)
        if not is_valid_email:
            raise HTTPException(
                status_code=422,
                detail=f"Email inválido: {'; '.join(email_errors)}",
            )

        service = _get_service(req.tenant_id)

        # Process attachments
        attachments = []
        for att in req.attachments:
            is_valid, att_type, att_errors = validate_attachment_type(att.filename)
            att_dict = att.model_dump()
            att_dict["type"] = att_type.value
            if not is_valid:
                att_dict["warning"] = att_errors
            attachments.append(att_dict)

        email = EmailMessage(
            from_addr=req.from_addr,
            subject=req.subject,
            date=req.date,
            attachments=attachments,
            tenant_id=req.tenant_id,
        )

        # Store in pending
        if req.tenant_id not in _pending_emails:
            _pending_emails[req.tenant_id] = []
        _pending_emails[req.tenant_id].append(email)

        # Extract invoices immediately
        invoices = service.extract_invoices(email)

        return {
            "ok": True,
            "email_id": email.id,
            "attachments_count": len(attachments),
            "invoices_extracted": len(invoices),
            "invoices": [inv.model_dump() for inv in invoices],
        }

    # -----------------------------------------------------------------------
    # GET /history — Get processing history
    # -----------------------------------------------------------------------
    @router.get(
        "/history",
        summary="Get processing history for a tenant.",
        response_model=None,
    )
    def get_history(
        tenant_id: str = Query(default="default", description="Tenant ID"),
        limit: int = Query(default=10, ge=1, le=100, description="Max results"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Return recent processing results."""
        service = _get_service(tenant_id)
        history = service.get_history(limit=limit)

        return {
            "ok": True,
            "total": len(history),
            "results": [r.model_dump() for r in history],
        }

    # -----------------------------------------------------------------------
    # GET /stats — Get processing statistics
    # -----------------------------------------------------------------------
    @router.get(
        "/stats",
        summary="Get processing statistics across all batches.",
        response_model=None,
    )
    def get_stats(
        tenant_id: str = Query(default="default", description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Return aggregate processing statistics."""
        service = _get_service(tenant_id)
        stats = service.get_stats()

        return {
            "ok": True,
            "stats": stats,
        }

    return router
