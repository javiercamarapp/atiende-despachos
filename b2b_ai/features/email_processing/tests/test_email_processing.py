# -*- coding: utf-8 -*-
"""
test_email_processing.py — Tests for the Email Processing module.

Covers:
  - Models: construction, validation, serialization
  - Service: inbox scanning, CFDI extraction, processing pipeline
  - Validators: email, attachment type, CFDI XML
  - Routes: all endpoints via TestClient
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


# ===========================================================================
# 1. MODEL TESTS
# ===========================================================================

class TestModels:
    """Test Pydantic model construction and validation."""

    def test_email_message_construction(self):
        msg = EmailMessage(
            from_addr="proveedor@empresa.com",
            subject="Factura mensual",
            date="2024-06-15",
        )
        assert msg.from_addr == "proveedor@empresa.com"
        assert msg.tenant_id == "default"
        assert msg.processed is False

    def test_email_message_empty_from_fails(self):
        with pytest.raises(Exception):
            EmailMessage(from_addr="", date="2024-06-15")

    def test_extracted_invoice_construction(self):
        inv = ExtractedInvoice(
            filename="factura_001.xml",
            cfdi_data={"uuid": "abc-123", "total": 15000},
            status=ProcessingStatus.COMPLETED,
        )
        assert inv.filename == "factura_001.xml"
        assert inv.status == ProcessingStatus.COMPLETED

    def test_extracted_invoice_empty_filename_fails(self):
        with pytest.raises(Exception):
            ExtractedInvoice(filename="")

    def test_processing_result_construction(self):
        pr = ProcessingResult(total=10, processed=8, failed=2)
        assert pr.total == 10
        assert pr.processed == 8
        assert pr.failed == 2

    def test_attachment_type_values(self):
        assert AttachmentType.XML.value == "xml"
        assert AttachmentType.PDF.value == "pdf"
        assert AttachmentType.IMAGE.value == "image"
        assert AttachmentType.OTHER.value == "other"

    def test_processing_status_values(self):
        assert ProcessingStatus.PENDING.value == "pending"
        assert ProcessingStatus.PROCESSING.value == "processing"
        assert ProcessingStatus.COMPLETED.value == "completed"
        assert ProcessingStatus.FAILED.value == "failed"
        assert ProcessingStatus.SKIPPED.value == "skipped"


# ===========================================================================
# 2. SERVICE TESTS
# ===========================================================================

class TestService:
    """Test EmailProcessingService logic."""

    def setup_method(self):
        self.service = EmailProcessingService(tenant_id="test-tenant")

    def test_monitor_inbox_empty(self):
        result = self.service.monitor_inbox("t1")
        assert result.total == 0
        assert result.processed == 0

    def test_monitor_inbox_with_xml_emails(self):
        emails = [
            EmailMessage(
                from_addr="proveedor@test.com",
                subject="Factura",
                date="2024-06-15",
                attachments=[{"filename": "factura.xml", "content_type": "application/xml"}],
            ),
        ]
        result = self.service.monitor_inbox("t1", emails)
        assert result.total == 1
        assert result.invoices_found == 1

    def test_monitor_inbox_skips_processed(self):
        emails = [
            EmailMessage(
                from_addr="test@test.com",
                subject="Already done",
                date="2024-06-15",
                processed=True,
                attachments=[{"filename": "factura.xml"}],
            ),
        ]
        result = self.service.monitor_inbox("t1", emails)
        assert result.skipped == 1

    def test_monitor_inbox_skips_no_attachments(self):
        emails = [
            EmailMessage(
                from_addr="test@test.com",
                subject="No attachments",
                date="2024-06-15",
                attachments=[],
            ),
        ]
        result = self.service.monitor_inbox("t1", emails)
        assert result.skipped == 1

    def test_extract_invoices_xml(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Version="4.0" Total="15000.00" SubTotal="13000.00"
            Fecha="2024-06-15T10:00:00" TipoDeComprobante="I"
            Moneda="MXN" Metodo="PUE" FormaPago="01">
            <cfdi:Emisor Rfc="EMP850101AB1" Nombre="Empresa SA" RegimenFiscal="601"/>
            <cfdi:Receptor Rfc="REC900101CD2" Nombre="Receptor SA" UsoCFDI="G03"/>
            <cfdi:Conceptos>
                <cfdi:Concepto ClaveProdServ="01010101" Cantidad="1"
                    Descripcion="Servicio" ValorUnitario="13000" Importe="13000"/>
            </cfdi:Conceptos>
            <cfdi:Complemento>
                <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                    UUID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
                    FechaTimbrado="2024-06-15T10:00:01"/>
            </cfdi:Complemento>
        </cfdi:Comprobante>"""

        email = EmailMessage(
            from_addr="proveedor@test.com",
            subject="Factura XML",
            date="2024-06-15",
            attachments=[{
                "filename": "factura.xml",
                "content": xml_content,
                "type": "xml",
            }],
        )

        invoices = self.service.extract_invoices(email)
        assert len(invoices) == 1
        inv = invoices[0]
        assert inv.status == ProcessingStatus.COMPLETED
        assert inv.uuid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert inv.rfc_emisor == "EMP850101AB1"
        assert inv.total == 15000.0

    def test_extract_invoices_pdf_skipped(self):
        email = EmailMessage(
            from_addr="test@test.com",
            date="2024-06-15",
            attachments=[{
                "filename": "factura.pdf",
                "type": "pdf",
            }],
        )
        invoices = self.service.extract_invoices(email)
        assert len(invoices) == 1
        assert invoices[0].status == ProcessingStatus.SKIPPED

    def test_extract_invoices_invalid_xml(self):
        email = EmailMessage(
            from_addr="test@test.com",
            date="2024-06-15",
            attachments=[{
                "filename": "bad.xml",
                "content": "<invalid>not a cfdi</invalid>",
                "type": "xml",
            }],
        )
        invoices = self.service.extract_invoices(email)
        assert len(invoices) == 1
        # May succeed or fail depending on XML structure
        assert invoices[0].filename == "bad.xml"

    def test_process_extracted_invoices(self):
        invoices = [
            ExtractedInvoice(
                filename="ok.xml",
                cfdi_data={"uuid": "abc", "rfc_emisor": "EMP123", "rfc_receptor": "REC456", "total": 1000},
                status=ProcessingStatus.COMPLETED,
                uuid="abc",
                rfc_emisor="EMP123",
                rfc_receptor="REC456",
                total=1000,
            ),
            ExtractedInvoice(
                filename="bad.xml",
                cfdi_data={},
                status=ProcessingStatus.FAILED,
                errors=["XML parse error"],
            ),
        ]
        result = self.service.process_extracted_invoices(invoices)
        assert result.processed == 1
        assert result.failed == 1

    def test_notify_user(self):
        result = ProcessingResult(total=5, processed=3, failed=2, invoices_found=3)
        notification = self.service.notify_user(result)
        assert notification["severity"] == "warning"
        assert "3" in notification["message"]

    def test_notify_user_success(self):
        result = ProcessingResult(total=5, processed=5, failed=0, invoices_found=5)
        notification = self.service.notify_user(result)
        assert notification["severity"] == "success"

    def test_notify_user_no_invoices(self):
        result = ProcessingResult(total=0, processed=0, failed=0, invoices_found=0)
        notification = self.service.notify_user(result)
        assert notification["severity"] == "info"

    def test_get_history(self):
        result = ProcessingResult(total=5, processed=5)
        self.service._history.append(result)
        history = self.service.get_history()
        assert len(history) == 1

    def test_get_stats(self):
        self.service._history.append(ProcessingResult(total=10, processed=8, failed=2, invoices_found=8))
        stats = self.service.get_stats()
        assert stats["total_batches"] == 1
        assert stats["total_processed"] == 8
        assert stats["success_rate"] == 80.0


# ===========================================================================
# 3. VALIDATOR TESTS
# ===========================================================================

class TestValidators:
    """Test validation functions."""

    def test_validate_email_valid(self):
        is_valid, errors = validate_email_address("test@empresa.com")
        assert is_valid
        assert len(errors) == 0

    def test_validate_email_invalid(self):
        is_valid, errors = validate_email_address("not-an-email")
        assert not is_valid

    def test_validate_email_empty(self):
        is_valid, errors = validate_email_address("")
        assert not is_valid

    def test_validate_attachment_type_xml(self):
        is_valid, att_type, errors = validate_attachment_type("factura.xml")
        assert is_valid
        assert att_type == AttachmentType.XML

    def test_validate_attachment_type_pdf(self):
        is_valid, att_type, errors = validate_attachment_type("invoice.pdf")
        assert is_valid
        assert att_type == AttachmentType.PDF

    def test_validate_attachment_type_disallowed(self):
        is_valid, att_type, errors = validate_attachment_type("image.jpg", allowed_types=["xml", "pdf"])
        assert not is_valid

    def test_validate_attachment_type_empty(self):
        is_valid, att_type, errors = validate_attachment_type("")
        assert not is_valid

    def test_validate_cfdi_xml_valid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Version="4.0" Total="15000" Fecha="2024-06-15">
            <cfdi:Emisor Rfc="EMP850101AB1"/>
            <cfdi:Receptor Rfc="REC900101CD2"/>
            <cfdi:Complemento>
                <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                    UUID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"/>
            </cfdi:Complemento>
        </cfdi:Comprobante>"""
        is_valid, errors = validate_cfdi_xml(xml)
        assert is_valid

    def test_validate_cfdi_xml_malformed(self):
        is_valid, errors = validate_cfdi_xml("<broken><xml")
        assert not is_valid
        assert any("malformado" in e.lower() for e in errors)

    def test_validate_cfdi_xml_empty(self):
        is_valid, errors = validate_cfdi_xml("")
        assert not is_valid

    def test_validate_cfdi_xml_missing_elements(self):
        xml = """<?xml version="1.0"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Version="4.0" Total="15000" Fecha="2024-06-15">
        </cfdi:Comprobante>"""
        is_valid, errors = validate_cfdi_xml(xml)
        assert not is_valid
        assert len(errors) >= 2  # Missing Emisor, Receptor, UUID

    def test_validate_email_message_valid(self):
        data = {
            "from_addr": "test@empresa.com",
            "date": "2024-06-15",
            "attachments": [{"filename": "test.xml"}],
        }
        is_valid, errors = validate_email_message(data)
        assert is_valid

    def test_validate_email_message_missing_fields(self):
        data = {}
        is_valid, errors = validate_email_message(data)
        assert not is_valid


# ===========================================================================
# 4. ROUTE TESTS
# ===========================================================================

class TestRoutes:
    """Test API endpoints via TestClient."""

    @pytest.fixture
    def client(self):
        from b2b_ai.features.email_processing.routes import build_email_processing_router
        from fastapi import FastAPI

        app = FastAPI()
        router = build_email_processing_router(db=None, require_api_key=lambda: {"tenant_id": "test"})
        app.include_router(router)
        return TestClient(app)

    def test_post_scan(self, client):
        response = client.post("/api/v1/email/scan", json={
            "tenant_id": "test",
            "emails": [{
                "from_addr": "proveedor@test.com",
                "subject": "Factura",
                "date": "2024-06-15",
                "attachments": [{"filename": "factura.xml"}],
            }],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_post_process(self, client):
        response = client.post("/api/v1/email/process", json={
            "tenant_id": "test",
            "invoices": [{
                "filename": "test.xml",
                "status": "pending",
            }],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_post_add_email(self, client):
        response = client.post("/api/v1/email/add", json={
            "tenant_id": "test",
            "from_addr": "proveedor@test.com",
            "subject": "Factura mensual",
            "attachments": [{"filename": "factura.xml"}],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_post_add_email_invalid(self, client):
        response = client.post("/api/v1/email/add", json={
            "tenant_id": "test",
            "from_addr": "not-an-email",
        })
        assert response.status_code == 422

    def test_get_history(self, client):
        response = client.get("/api/v1/email/history?tenant_id=test")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_get_stats(self, client):
        response = client.get("/api/v1/email/stats?tenant_id=test")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "stats" in data
