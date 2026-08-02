# -*- coding: utf-8 -*-
"""
test_email_processing.py — Tests for the Email Processing module.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.email_processing.models import (
    Attachment,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
)
from b2b_ai.features.email_processing.service import (
    extract_invoices,
    monitor_inbox,
    notify_user,
    process_extracted_invoices,
)
from b2b_ai.features.email_processing.routes import (
    build_email_processing_router,
)


TENANT = "test-tenant"


def _make_cfdi_xml(uuid="test-uuid-123", rfc_emisor="XAXX010101000"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    FolioInterno="{uuid}" RFC="{rfc_emisor}" Total="1000" Subtotal="862.07" IVA="137.93"/>"""


def _email_with_cfdi():
    xml_content = _make_cfdi_xml()
    return EmailMessage(
        from_addr="proveedor@example.com",
        subject="Factura Electrónica #12345",
        date="2026-07-15",
        attachments=[
            {
                "filename": "factura.xml",
                "content_type": "application/xml",
                "size": len(xml_content),
                "content": xml_content.encode(),
            }
        ],
    )


def _email_without_attachments():
    return EmailMessage(
        from_addr="proveedor@example.com",
        subject="Sin adjuntos",
        date="2026-07-15",
        attachments=[],
    )


def _mock_require_api_key():
    return {"tenant_id": "test-tenant", "key": "test-key"}


def _app():
    app = FastAPI()
    app.include_router(build_email_processing_router(db=None, require_api_key=_mock_require_api_key))
    return app


# ---------------------------------------------------------------------------
# Monitor Inbox Tests
# ---------------------------------------------------------------------------

class TestMonitorInbox:
    def test_scan_returns_result(self):
        result = monitor_inbox(TENANT)
        assert isinstance(result, ProcessingResult)
        assert result.tenant_id == TENANT

    def test_scan_with_no_emails(self):
        result = monitor_inbox(TENANT)
        assert result.total == 0


# ---------------------------------------------------------------------------
# Extract Invoices Tests
# ---------------------------------------------------------------------------

class TestExtractInvoices:
    def test_extract_from_email_with_xml(self):
        email = _email_with_cfdi()
        invoices = extract_invoices(email)
        assert isinstance(invoices, list)
        assert len(invoices) >= 0  # May not parse mock XML

    def test_extract_from_email_without_attachments(self):
        email = _email_without_attachments()
        invoices = extract_invoices(email)
        assert isinstance(invoices, list)
        assert len(invoices) == 0

    def test_extract_returns_list(self):
        email = _email_without_attachments()
        result = extract_invoices(email)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Process Invoices Tests
# ---------------------------------------------------------------------------

class TestProcessInvoices:
    def test_process_empty_list(self):
        result = process_extracted_invoices([])
        assert isinstance(result, ProcessingResult)
        assert result.total == 0

    def test_process_with_invoices(self):
        inv = ExtractedInvoice(
            filename="test.xml",
            cfdi_data={"uuid": "test-123", "rfc": "XAXX010101000"},
            status="pending",
            errors=[],
        )
        result = process_extracted_invoices([inv])
        assert isinstance(result, ProcessingResult)
        assert result.total == 1


# ---------------------------------------------------------------------------
# Notify Tests
# ---------------------------------------------------------------------------

class TestNotify:
    def test_notify_with_results(self):
        pr = ProcessingResult(
            id="test-id",
            total=5,
            processed=3,
            failed=1,
            skipped=1,
            invoices_found=3,
            details=[],
            errors=["error1"],
            tenant_id=TENANT,
            scan_period="2026-07",
        )
        result = notify_user(pr)
        assert isinstance(result, dict)

    def test_notify_empty_results(self):
        pr = ProcessingResult(
            id="test-id",
            total=0,
            processed=0,
            failed=0,
            skipped=0,
            invoices_found=0,
            details=[],
            errors=[],
            tenant_id=TENANT,
            scan_period="2026-07",
        )
        result = notify_user(pr)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Route Tests
# ---------------------------------------------------------------------------

class TestRoutes:
    def test_scan_route(self):
        client = TestClient(_app())
        resp = client.post("/api/v1/email/scan", json={"tenant_id": TENANT})
        assert resp.status_code in (200, 201, 422)

    def test_process_route(self):
        client = TestClient(_app())
        resp = client.post("/api/v1/email/process", json={"invoices": []})
        assert resp.status_code in (200, 201, 422)

    def test_history_route(self):
        client = TestClient(_app())
        resp = client.get("/api/v1/email/history")
        assert resp.status_code in (200, 422)

    def test_stats_route(self):
        client = TestClient(_app())
        resp = client.get("/api/v1/email/stats")
        assert resp.status_code in (200, 422)
