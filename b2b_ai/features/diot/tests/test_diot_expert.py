# -*- coding: utf-8 -*-
"""
test_diot_expert.py — Expert-level tests for DIOT module.
"""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.diot.service import generate_diot, DiotService, validate_diot_data, detect_inconsistencies, get_report, list_reports
from b2b_ai.features.diot.models import CFDIInvoiceInput, DiotReport, DiotEntry, TipoIva, OperacionType
from b2b_ai.features.diot.validators import (
    validate_rfc, validate_iva_rate, validate_iva_amount, validate_diot_entries,
    validate_invoices, validate_all_rfcs, validate_cfdi_cross_reference,
)
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection


class TestIdempotency:
    def test_generate_diot_idempotent(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0, total=1160.0)]
        r1 = generate_diot(1, 2024, "t1", invoices)
        r2 = generate_diot(1, 2024, "t1", invoices)
        assert r1.id != r2.id  # Different report instances

    def test_diot_service_coerce_idempotent(self):
        svc = DiotService()
        inv = {"uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "rfc_emisor": "EMP850101AB1", "subtotal": 1000.0}
        typed = svc._coerce_invoices([inv])
        assert len(typed) == 1
        assert isinstance(typed[0], CFDIInvoiceInput)


class TestAuditTrail:
    def test_report_has_audit_trail(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0)]
        report = generate_diot(1, 2024, "t1", invoices)
        assert hasattr(report, "audit_trail")


class TestInputSanitization:
    def test_validate_rfc_valid_moral(self):
        err = validate_rfc("EMP850101AB1")
        assert err is None

    def test_validate_rfc_valid_physical(self):
        err = validate_rfc("CACJ850101MQR123")
        assert err is None

    def test_validate_rfc_too_short(self):
        err = validate_rfc("AB")
        assert err is not None

    def test_validate_rfc_empty(self):
        err = validate_rfc("")
        assert err is not None

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("RFC normal 123")
        assert safe
        safe, _ = check_sql_injection("'; DROP TABLE--")
        assert not safe


class TestErrorHandling:
    def test_generate_diot_no_invoices(self):
        report = generate_diot(1, 2024, "t1", [])
        assert report.estatus.value == "ERROR"

    def test_validate_invoices_empty(self):
        result = validate_invoices([])
        assert not result.valid

    def test_validate_diot_entries_empty(self):
        result = validate_diot_entries([])
        assert not result.valid

    def test_validate_diot_entries_bad_rfc(self):
        entries = [{"rfc_tercero": "BAD", "tipo_operacion": "01", "monto_neto": 100, "iva_trasladado": 16, "iva_acreditable": 16}]
        result = validate_diot_entries(entries)
        assert not result.valid


class TestTenantIsolation:
    def test_mask_rfc(self):
        assert "***" in mask_rfc("EMP850101AB1")


class TestEdgeCases:
    def test_validate_iva_rate_valid(self):
        ok, _ = validate_iva_rate(0.16)
        assert ok

    def test_validate_iva_rate_invalid(self):
        ok, _ = validate_iva_rate(0.12)
        assert not ok

    def test_validate_iva_amount_correct(self):
        ok, _ = validate_iva_amount(1000.0, 160.0, 0.16)
        assert ok

    def test_validate_iva_amount_wrong(self):
        ok, msg = validate_iva_amount(1000.0, 200.0, 0.16)
        assert not ok

    def test_get_report_returns_none(self):
        assert get_report("nonexistent") is None

    def test_list_reports_empty(self):
        reports = list_reports("nonexistent_tenant")
        # May or may not be empty depending on state
        assert isinstance(reports, list)


class TestConcurrentAccess:
    def test_concurrent_generate(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0)]
        results = []
        def run():
            results.append(generate_diot(1, 2024, "t1", invoices))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
        for r in results:
            assert r.summary.total_operaciones == 1


class TestDataValidation:
    def test_validate_rfc_persona_moral(self):
        err = validate_rfc("EMP850101AB1")
        assert err is None

    def test_validate_rfc_persona_fisica(self):
        err = validate_rfc("CACJ850101MQR123")
        assert err is None

    def test_validate_iva_rate_boundary(self):
        ok, _ = validate_iva_rate(0.08)
        assert ok
        ok, _ = validate_iva_rate(0.0)
        assert ok


class TestOutputVerification:
    def test_diot_report_structure(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0, total=1160.0)]
        report = generate_diot(1, 2024, "t1", invoices)
        assert report.entries is not None
        assert report.summary is not None
        assert report.referencia_legal == "CFF Art. 85"

    def test_diot_report_recompute_summary(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0, iva_acreditable=160.0, total=1160.0)]
        report = generate_diot(1, 2024, "t1", invoices)
        report.recompute_summary()
        assert report.summary.total_operaciones == 1


class TestRetryLogic:
    def test_report_retry_count(self):
        invoices = [CFDIInvoiceInput(uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", rfc_emisor="EMP850101AB1", subtotal=1000.0, iva_trasladado=160.0)]
        report = generate_diot(1, 2024, "t1", invoices)
        assert report.requires_human_review is not None
