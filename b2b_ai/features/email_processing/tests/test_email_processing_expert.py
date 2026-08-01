# -*- coding: utf-8 -*-
"""test_email_processing_expert.py — Expert-level tests for Email Processing module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.email_processing.service import EmailProcessingService
from b2b_ai.features.email_processing.models import (
    EmailMessage, ExtractedInvoice, ProcessingResult, ProcessingStatus, AttachmentType,
)
from b2b_ai.features.email_processing.validators import (
    validate_email_address, validate_attachment_type, validate_cfdi_xml, validate_email_message,
)
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_service_init_idempotent(self):
        s1 = EmailProcessingService("t1")
        s2 = EmailProcessingService("t1")
        assert len(s1._emails) == len(s2._emails) == 0

    def test_monitor_inbox_returns_consistent_structure(self):
        svc = EmailProcessingService("t1")
        r1 = svc.monitor_inbox("t1")
        r2 = svc.monitor_inbox("t1")
        assert r1.total == r2.total == 0


class TestAuditTrail:
    def test_log_audit(self):
        svc = EmailProcessingService("t1")
        entry = svc.log_audit(user="u1", action="scan", module="email", result="ok")
        assert entry.action == "scan"


class TestInputSanitization:
    def test_encode_output(self):
        assert "&lt;" in encode_output("<script>test</script>")

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("normal email")
        assert safe
        safe, _ = check_sql_injection("'; DROP TABLE--")
        assert not safe


class TestErrorHandling:
    def test_validate_email_empty(self):
        ok, _ = validate_email_address("")
        assert not ok

    def test_validate_email_invalid(self):
        ok, _ = validate_email_address("not-an-email")
        assert not ok

    def test_validate_attachment_type_empty(self):
        ok, _, _ = validate_attachment_type("")
        assert not ok

    def test_validate_cfdi_xml_empty(self):
        ok, _ = validate_cfdi_xml("")
        assert not ok

    def test_validate_cfdi_xml_malformed(self):
        ok, _ = validate_cfdi_xml("<broken><xml")
        assert not ok

    def test_validate_email_message_empty(self):
        ok, _ = validate_email_message({})
        assert not ok


class TestTenantIsolation:
    def test_service_tenant(self):
        svc = EmailProcessingService("t1")
        assert svc.tenant_id == "t1"

    def test_mask_rfc(self):
        masked = mask_rfc("EMP850101AB1")
        assert "***" in masked


class TestEdgeCases:
    def test_monitor_inbox_empty(self):
        svc = EmailProcessingService("t1")
        result = svc.monitor_inbox("t1")
        assert result.total == 0

    def test_monitor_inbox_skips_processed(self):
        svc = EmailProcessingService("t1")
        emails = [EmailMessage(from_addr="test@test.com", date="2024-01-01", processed=True)]
        result = svc.monitor_inbox("t1", emails)
        assert result.skipped == 1

    def test_monitor_inbox_skips_no_attachments(self):
        svc = EmailProcessingService("t1")
        emails = [EmailMessage(from_addr="test@test.com", date="2024-01-01", attachments=[])]
        result = svc.monitor_inbox("t1", emails)
        assert result.skipped == 1

    def test_get_history_empty(self):
        svc = EmailProcessingService("t1")
        assert svc.get_history() == []

    def test_get_stats_empty(self):
        svc = EmailProcessingService("t1")
        stats = svc.get_stats()
        assert stats["total_batches"] == 0

    def test_notify_user_no_invoices(self):
        svc = EmailProcessingService("t1")
        result = ProcessingResult(total=0, processed=0, failed=0, invoices_found=0)
        notification = svc.notify_user(result)
        assert notification["severity"] == "info"

    def test_notify_user_success(self):
        svc = EmailProcessingService("t1")
        result = ProcessingResult(total=5, processed=5, failed=0, invoices_found=5)
        notification = svc.notify_user(result)
        assert notification["severity"] == "success"

    def test_notify_user_warning(self):
        svc = EmailProcessingService("t1")
        result = ProcessingResult(total=5, processed=3, failed=2, invoices_found=3)
        notification = svc.notify_user(result)
        assert notification["severity"] == "warning"


class TestConcurrentAccess:
    def test_concurrent_monitor(self):
        svc = EmailProcessingService("t1")
        results = []
        def run():
            results.append(svc.monitor_inbox("t1"))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5


class TestDataValidation:
    def test_validate_attachment_type_xml(self):
        ok, att_type, _ = validate_attachment_type("factura.xml")
        assert ok
        assert att_type == AttachmentType.XML

    def test_validate_attachment_type_pdf(self):
        ok, att_type, _ = validate_attachment_type("invoice.pdf")
        assert ok
        assert att_type == AttachmentType.PDF

    def test_validate_attachment_type_disallowed(self):
        ok, _, _ = validate_attachment_type("image.jpg", allowed_types=["xml", "pdf"])
        assert not ok

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
        ok, _ = validate_cfdi_xml(xml)
        assert ok


class TestOutputVerification:
    def test_extract_invoices_xml(self):
        svc = EmailProcessingService("t1")
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
            attachments=[{"filename": "factura.xml", "content": xml_content, "type": "xml"}],
        )
        invoices = svc.extract_invoices(email)
        assert len(invoices) == 1
        assert invoices[0].status == ProcessingStatus.COMPLETED
        assert invoices[0].uuid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert invoices[0].rfc_emisor == "EMP850101AB1"
        assert invoices[0].total == 15000.0

    def test_process_extracted_invoices(self):
        svc = EmailProcessingService("t1")
        invoices = [
            ExtractedInvoice(
                filename="ok.xml",
                cfdi_data={"uuid": "abc", "rfc_emisor": "EMP123", "rfc_receptor": "REC456", "total": 1000},
                status=ProcessingStatus.COMPLETED,
                uuid="abc", rfc_emisor="EMP123", rfc_receptor="REC456", total=1000,
            ),
        ]
        result = svc.process_extracted_invoices(invoices)
        assert result.processed == 1


class TestRetryLogic:
    def test_processing_result_structure(self):
        result = ProcessingResult(total=10, processed=8, failed=2, invoices_found=8, tenant_id="t1")
        assert result.total == 10
        assert result.processed == 8
        assert result.failed == 2
        assert result.tenant_id == "t1"
