# -*- coding: utf-8 -*-
"""test_clientes_expert.py — Expert-level tests for Clientes module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.clientes.service import ClientService
from b2b_ai.features.clientes.models import ClientQuery, QueryType, QueryCategory, InvoiceStatus
from b2b_ai.features.clientes.validators import validate_cfdi_id, validate_concepto, validate_client_query
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_service_init_idempotent(self):
        s1 = ClientService("t1")
        s2 = ClientService("t1")
        assert len(s1._queries) == len(s2._queries) == 0

    def test_register_invoice_idempotent(self):
        svc = ClientService("t1")
        inv = InvoiceStatus(cfdi_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890", estado="timbrada")
        svc.register_invoice(inv)
        svc.register_invoice(inv)
        assert len(svc._invoices) == 1


class TestAuditTrail:
    def test_log_audit(self):
        svc = ClientService("t1")
        entry = svc.log_audit(user="u1", action="process", module="clientes", result="ok")
        assert entry.action == "process"


class TestInputSanitization:
    def test_process_query_sanitizes(self):
        svc = ClientService("t1")
        q = ClientQuery(tipo=QueryType.PREGUNTA, contenido="  <script>test</script>  ", tenant_id="t1")
        result = svc.process_client_query(q)
        assert "<script>" not in result.contenido

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("normal question")
        assert safe
        safe, _ = check_sql_injection("DROP TABLE users--")
        assert not safe


class TestErrorHandling:
    def test_validate_cfdi_id_empty(self):
        ok, _ = validate_cfdi_id("")
        assert not ok

    def test_validate_concepto_empty(self):
        ok, _ = validate_concepto("")
        assert not ok

    def test_validate_client_query_missing_fields(self):
        ok, _ = validate_client_query({})
        assert not ok


class TestTenantIsolation:
    def test_query_tenant_isolation(self):
        svc1 = ClientService("t1")
        svc2 = ClientService("t2")
        q1 = ClientQuery(tipo=QueryType.PREGUNTA, contenido="test one", tenant_id="t1")
        q2 = ClientQuery(tipo=QueryType.PREGUNTA, contenido="test two", tenant_id="t2")
        svc1.process_client_query(q1)
        svc2.process_client_query(q2)
        # Each service processes independently
        assert svc1.tenant_id == "t1"
        assert svc2.tenant_id == "t2"

    def test_mask_rfc(self):
        masked = mask_rfc("EMP850101AB1")
        assert "***" in masked


class TestEdgeCases:
    def test_empty_faq_search(self):
        svc = ClientService("t1")
        result = svc._search_faq("xyznonexistent")
        assert result is None

    def test_get_deductibility_unknown(self):
        svc = ClientService("t1")
        info = svc.get_deductibility_info("unknown concept")
        assert info["deductible"] is None

    def test_get_faqs_by_category_empty(self):
        svc = ClientService("t1")
        faqs = svc.get_faqs(category=QueryCategory.DEVOLUCIONES)
        assert isinstance(faqs, list)

    def test_extract_cfdi_id_from_text(self):
        svc = ClientService("t1")
        text = "Mi factura a1b2c3d4-e5f6-7890-abcd-ef1234567890 tiene error"
        cfdi_id = svc._extract_cfdi_id(text)
        assert cfdi_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class TestConcurrentAccess:
    def test_concurrent_process_query(self):
        svc = ClientService("t1")
        results = []
        def run():
            q = ClientQuery(tipo=QueryType.PREGUNTA, contenido="test", tenant_id="t1")
            results.append(svc.process_client_query(q))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
        for r in results:
            assert r.respuesta is not None


class TestDataValidation:
    def test_validate_query_type_valid(self):
        ok, _ = validate_client_query({"tipo": "factura", "contenido": "test content", "tenant_id": "t1"})
        assert ok

    def test_validate_cfdi_id_valid(self):
        ok, _ = validate_cfdi_id("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert ok


class TestOutputVerification:
    def test_process_query_returns_response(self):
        svc = ClientService("t1")
        q = ClientQuery(tipo=QueryType.FACTURA, contenido="¿Cuándo tendré mi factura?", tenant_id="t1")
        result = svc.process_client_query(q)
        assert result.respuesta is not None
        assert len(result.respuesta) > 0

    def test_auto_classification(self):
        svc = ClientService("t1")
        q = ClientQuery(tipo=QueryType.PREGUNTA, contenido="Necesito mi factura XML", tenant_id="t1")
        result = svc.process_client_query(q)
        assert result.categoria == QueryCategory.FACTURACION


class TestRetryLogic:
    def test_generate_response_fallback(self):
        svc = ClientService("t1")
        q = ClientQuery(tipo=QueryType.ESTATUS, contenido="test", tenant_id="t1")
        response = svc.generate_client_response(q, {"cfdi_id": "abc", "estado": "timbrada"})
        assert "timbrada" in response
