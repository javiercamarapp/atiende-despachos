# -*- coding: utf-8 -*-
"""test_pre_auditoria_expert.py — Expert-level tests for Pre-Auditoria module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.pre_auditoria.service import (
    check_deductibility, check_consistency, check_cff_compliance,
    generate_audit_report, run_pre_audit,
)
from b2b_ai.features.pre_auditoria.models import AuditFinding, AuditReport, DeductibilityCheck, Severity
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_run_pre_audit_deterministic(self):
        invoices = [{"invoice_id": "1", "concepto": "salario", "monto": 50000}]
        ledger = [{"id": "A1", "debe": 1000, "haber": 1000, "fecha": "2024-01-15", "cuenta_debito": "1100", "cuenta_credito": "2100", "descripcion": "test"}]
        cff_data = {"rfc": "EMP850101AB1", "cfdi_count": 10, "tiene_contabilidad_electronica": True, "periodos_cerrados": ["2024-01"]}
        r1 = run_pre_audit(1, "2024-01", invoices, ledger, cff_data)
        r2 = run_pre_audit(1, "2024-01", invoices, ledger, cff_data)
        assert r1.score == r2.score


class TestAuditTrail:
    def test_report_has_compliance_fields(self):
        report = run_pre_audit(1, "2024-01")
        assert hasattr(report, "referencia_legal")
        assert hasattr(report, "supuesto")


class TestInputSanitization:
    def test_encode_output(self):
        assert "&lt;" in encode_output("<script>test</script>")

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("normal text")
        assert safe
        safe, _ = check_sql_injection("SELECT * FROM--")
        assert not safe


class TestErrorHandling:
    def test_check_deductibility_empty(self):
        results = check_deductibility([])
        assert len(results) == 0

    def test_check_consistency_empty(self):
        findings = check_consistency([])
        assert len(findings) == 0

    def test_check_cff_compliance_empty(self):
        findings = check_cff_compliance({})
        assert len(findings) > 0  # RFC missing

    def test_check_deductibility_non_deductible(self):
        results = check_deductibility([{"invoice_id": "1", "concepto": "multas por infracción", "monto": 5000}])
        assert results[0].es_deducible is False


class TestTenantIsolation:
    def test_report_tenant(self):
        report = run_pre_audit(42, "2024-01")
        assert report.tenant_id == 42


class TestEdgeCases:
    def test_consistency_bad_debe_haber(self):
        ledger = [{"id": "A1", "debe": 1000, "haber": 500, "fecha": "2024-01-15", "cuenta_debito": "1100", "cuenta_credito": "2100", "descripcion": "test"}]
        findings = check_consistency(ledger)
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) > 0

    def test_consistency_future_date(self):
        ledger = [{"id": "A1", "debe": 1000, "haber": 1000, "fecha": "2099-01-01", "cuenta_debito": "1100", "cuenta_credito": "2100", "descripcion": "test"}]
        findings = check_consistency(ledger)
        high = [f for f in findings if f.severity == Severity.HIGH]
        assert len(high) > 0

    def test_cff_compliance_no_rfc(self):
        findings = check_cff_compliance({})
        rfc_findings = [f for f in findings if f.category == "rfc_invalido"]
        assert len(rfc_findings) > 0

    def test_cff_compliance_no_cfdi(self):
        findings = check_cff_compliance({"rfc": "EMP850101AB1", "cfdi_count": 0})
        cfdi_findings = [f for f in findings if f.category == "sin_cfdi"]
        assert len(cfdi_findings) > 0

    def test_report_score_100(self):
        report = generate_audit_report([], period="2024-01")
        assert report.score == 100.0

    def test_report_score_reduced(self):
        findings = [
            AuditFinding(category="test", severity=Severity.CRITICAL, description="critical issue"),
            AuditFinding(category="test", severity=Severity.HIGH, description="high issue"),
        ]
        report = generate_audit_report(findings, period="2024-01")
        assert report.score < 100.0


class TestConcurrentAccess:
    def test_concurrent_run_pre_audit(self):
        results = []
        def run():
            results.append(run_pre_audit(1, "2024-01"))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5


class TestDataValidation:
    def test_deductibility_high_amount(self):
        results = check_deductibility([{"invoice_id": "1", "concepto": "equipo", "monto": 100000}])
        assert "documentación" in results[0].razon.lower() or results[0].es_deducible is True

    def test_audit_finding_to_dict(self):
        f = AuditFinding(category="test", severity=Severity.MEDIUM, description="desc", recommendation="rec")
        d = f.to_dict()
        assert d["category"] == "test"
        assert d["severity"] == "medium"


class TestOutputVerification:
    def test_run_pre_audit_structure(self):
        report = run_pre_audit(1, "2024-01")
        assert report.period == "2024-01"
        assert report.score >= 0
        assert isinstance(report.findings, list)

    def test_deductibility_check_to_dict(self):
        dc = DeductibilityCheck(invoice_id="1", concepto="test", es_deducible=True)
        d = dc.to_dict()
        assert d["invoice_id"] == "1"


class TestRetryLogic:
    def test_report_escalation_path(self):
        report = run_pre_audit(1, "2024-01")
        assert report.escalation_path == "review_by_contador"
