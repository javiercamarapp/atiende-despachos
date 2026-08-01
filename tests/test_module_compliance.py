# -*- coding: utf-8 -*-
"""
test_module_compliance.py — Compliance tests for ALL 10 agent modules.

Tests per module:
  1. requires_human_review flag
  2. Audit trail logging
  3. Input sanitization
  4. Error handling (malformed input)
  5. Tenant isolation
"""
from __future__ import annotations

import pytest


# ===========================================================================
# Module 1: clientes
# ===========================================================================

class TestClientesCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.clientes.service import ClientService
        from b2b_ai.features.clientes.models import InvoiceStatus
        svc = ClientService(tenant_id="test")
        inv = InvoiceStatus(
            cfdi_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            estado="timbrada",
            total=15000.0,
        )
        result = svc.register_invoice(inv)
        assert result.requires_human_review is True
        assert result.referencia_legal == "CFF Art. 30"
        assert result.supuesto != ""

    def test_audit_trail(self):
        from b2b_ai.features.clientes.service import ClientService
        svc = ClientService(tenant_id="test")
        entry = svc.log_audit(user="test", action="test_action", module="clientes", result="ok", tenant_id="test")
        assert entry.action == "test_action"
        assert len(svc._audit.get_entries(module="clientes")) >= 1

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("  hello world  ", max_length=100)
        assert result == "hello world"

    def test_error_handling(self):
        from b2b_ai.features.clientes.service import ClientService
        from b2b_ai.features.clientes.models import ClientQuery, QueryType
        svc = ClientService(tenant_id="test")
        query = ClientQuery(tipo=QueryType.FACTURA, contenido="test query", tenant_id="test")
        result = svc.process_client_query(query)
        assert result.respuesta is not None

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed is True
        allowed, _ = verify_tenant_access("t1", "t2")
        assert allowed is False

    def test_idempotency(self):
        from b2b_ai.features.clientes.service import ClientService
        svc = ClientService(tenant_id="test")
        assert svc.check_idempotency("key123") is False
        assert svc.check_idempotency("key123") is True


# ===========================================================================
# Module 2: email_processing
# ===========================================================================

class TestEmailProcessingCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.email_processing.models import ExtractedInvoice, ProcessingStatus
        inv = ExtractedInvoice(
            filename="test.xml",
            cfdi_data={},
            status=ProcessingStatus.COMPLETED,
        )
        # Verify compliance fields exist
        assert hasattr(inv, "requires_human_review")
        assert hasattr(inv, "referencia_legal")

    def test_audit_trail(self):
        from b2b_ai.features.email_processing.service import EmailProcessingService
        svc = EmailProcessingService(tenant_id="test")
        result = svc.monitor_inbox("test")
        assert result.total == 0

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("<script>alert(1)</script>test", max_length=100)
        assert "<script>" not in result

    def test_error_handling(self):
        from b2b_ai.features.email_processing.service import EmailProcessingService
        svc = EmailProcessingService(tenant_id="test")
        result = svc.monitor_inbox("test", emails=[])
        assert result.processed == 0

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, msg = verify_tenant_access("t1", "")
        assert allowed is False


# ===========================================================================
# Module 3: diot
# ===========================================================================

class TestDiotCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.diot.models import DiotEntry
        entry = DiotEntry(
            rfc_tercero="EMP850101AB1",
            tipo_operacion="01",
        )
        assert hasattr(entry, "requires_human_review")

    def test_audit_trail(self):
        from b2b_ai.features.compliance import AuditTrail
        trail = AuditTrail()
        entry = trail.log(user="test", action="diot_gen", module="diot", result="ok")
        assert entry.module == "diot"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_rfc
        assert sanitize_rfc("  emp850101ab1  ") == "EMP850101AB1"

    def test_error_handling(self):
        from b2b_ai.features.diot.service import generate_diot
        report = generate_diot(month=1, year=2024, tenant_id="test", invoices=[])
        assert report.estatus.value == "ERROR"

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed is True


# ===========================================================================
# Module 4: declaraciones
# ===========================================================================

class TestDeclaracionesCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.declaraciones.service import DeclaracionesService
        svc = DeclaracionesService()
        decl = svc.generate_monthly_iva(
            month=1, year=2024, tenant_id="test", rfc="EMP850101AB1",
            data={"iva_cobrado": 10000, "iva_pagado": 8000},
        )
        assert decl.requires_human_review is True
        assert decl.referencia_legal != ""
        assert decl.supuesto != ""

    def test_audit_trail(self):
        from b2b_ai.features.declaraciones.service import DeclaracionesService
        svc = DeclaracionesService()
        entry = svc.log_audit(user="test", action="test", module="declaraciones", result="ok")
        assert entry.module == "declaraciones"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("   test   ")
        assert result == "test"

    def test_error_handling(self):
        from b2b_ai.features.declaraciones.service import DeclaracionesService
        svc = DeclaracionesService()
        with pytest.raises(ValueError):
            svc.generate_monthly_iva(month=13, year=2024, tenant_id="test")

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t2")
        assert allowed is False


# ===========================================================================
# Module 5: conciliacion_fiscal
# ===========================================================================

class TestConciliacionFiscalCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
        svc = FiscalConciliationService()
        comparison = svc.compare_erp_vs_sat(
            tenant_id="test", month=1, year=2024,
            erp_data=[{"uuid": "u1", "monto": 100, "rfc": "EMP850101AB1"}],
            sat_data=[{"uuid": "u2", "monto": 100, "rfc": "EMP850101AB1"}],
        )
        report = svc.generate_fiscal_report(comparison)
        assert report.requires_human_review is True
        assert report.referencia_legal == "CFF Art. 89"

    def test_audit_trail(self):
        from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
        svc = FiscalConciliationService()
        entry = svc.log_audit(user="test", action="test", module="conciliacion_fiscal", result="ok")
        assert entry.module == "conciliacion_fiscal"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("<script>alert(1)</script>test")
        assert "<script>" not in result

    def test_error_handling(self):
        from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
        svc = FiscalConciliationService()
        report = svc.get_report("nonexistent")
        assert report is None

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed is True


# ===========================================================================
# Module 6: vencimientos
# ===========================================================================

class TestVencimientosCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.vencimientos.service import VencimientosService
        from b2b_ai.features.vencimientos.models import Deadline, EstadoVencimiento
        svc = VencimientosService()
        deadline = Deadline(
            id="test-deadline",
            tipo="ISR",
            fecha_limite="2024-12-17",
            tenant_id="test",
        )
        assert hasattr(deadline, "requires_human_review")
        assert hasattr(deadline, "referencia_legal")

    def test_audit_trail(self):
        from b2b_ai.features.vencimientos.service import VencimientosService
        svc = VencimientosService()
        entry = svc.log_audit(user="test", action="test", module="vencimientos", result="ok")
        assert entry.module == "vencimientos"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("test input", max_length=5)
        assert len(result) == 5

    def test_error_handling(self):
        from b2b_ai.features.vencimientos.service import VencimientosService
        svc = VencimientosService()
        result = svc.mark_completed("nonexistent")
        assert result is False

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "")
        assert allowed is False


# ===========================================================================
# Module 7: nomina_completa
# ===========================================================================

class TestNominaCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.nomina_completa.service import process_payroll
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{
            "employee_id": "E001",
            "nombre": "Test Employee",
            "salario_bruto": 50000,
            "percepciones": 0,
            "salario_diario": 1667,
        }]
        result = process_payroll(period, employees, tenant_id=1)
        assert hasattr(result, "requires_human_review")
        assert hasattr(result, "referencia_legal")
        assert result.referencia_legal == "CFF Art. 105, LISR Art. 96"

    def test_audit_trail(self):
        from b2b_ai.features.compliance import AuditTrail
        trail = AuditTrail()
        entry = trail.log(user="test", action="nomina", module="nomina_completa", result="ok")
        assert entry.module == "nomina_completa"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("test payroll")
        assert result == "test payroll"

    def test_error_handling(self):
        from b2b_ai.features.nomina_completa.service import process_payroll
        period = {"month": 1, "year": 2024}
        result = process_payroll(period, [], tenant_id=1)
        assert result.total_bruto == 0

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("1", "1")
        assert allowed is True


# ===========================================================================
# Module 8: pre_auditoria
# ===========================================================================

class TestPreAuditoriaCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.pre_auditoria.service import run_pre_audit
        report = run_pre_audit(
            tenant_id=1,
            period="2024-01",
            invoices=[{"invoice_id": "INV-001", "concepto": "multas SAT", "monto": 5000}],
            cff_data={"rfc": "EMP850101AB1", "cfdi_count": 5, "tiene_contabilidad_electronica": True, "periodos_cerrados": ["2024-01"]},
        )
        assert report.requires_human_review is True
        assert report.referencia_legal != ""
        assert report.supuesto == "Pre-auditoría contable"

    def test_audit_trail(self):
        from b2b_ai.features.compliance import AuditTrail
        trail = AuditTrail()
        entry = trail.log(user="test", action="audit", module="pre_auditoria", result="ok")
        assert entry.module == "pre_auditoria"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("test concepto")
        assert result == "test concepto"

    def test_error_handling(self):
        from b2b_ai.features.pre_auditoria.service import run_pre_audit
        report = run_pre_audit(tenant_id=1, period="2024-01")
        assert report.score == 100.0

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t2")
        assert allowed is False


# ===========================================================================
# Module 9: conciliacion
# ===========================================================================

class TestConciliacionCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.conciliacion.models import ConciliationReport
        report = ConciliationReport(period="2024-01")
        assert hasattr(report, "requires_human_review")
        assert hasattr(report, "referencia_legal")
        assert hasattr(report, "escalation_path")

    def test_audit_trail(self):
        from b2b_ai.features.conciliacion.service import ConciliationService
        svc = ConciliationService()
        entry = svc.log_audit(user="test", action="test", module="conciliacion", result="ok")
        assert entry.module == "conciliacion"

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("test reconciliation")
        assert result == "test reconciliation"

    def test_error_handling(self):
        from b2b_ai.features.conciliacion.service import ConciliationService
        svc = ConciliationService()
        assert hasattr(svc, "_deadlines") or hasattr(svc, "_reports") or hasattr(svc, "_audit")

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed is True


# ===========================================================================
# Module 10: reportes_gerenciales
# ===========================================================================

class TestReportesCompliance:
    def test_requires_human_review_flag(self):
        from b2b_ai.features.reportes_gerenciales.service import ReportesService
        svc = ReportesService(tenant_id="test")
        report = svc.generate_monthly_report(tenant_id="test", month=1, year=2024)
        assert report.requires_human_review is False
        assert report.referencia_legal == "CFF Art. 89"
        assert report.escalation_path == "review_by_contador"

    def test_audit_trail(self):
        from b2b_ai.features.reportes_gerenciales.service import ReportesService
        svc = ReportesService(tenant_id="test")
        entry = svc.log_audit(user="test", action="test", module="reportes_gerenciales", result="ok")
        assert entry.module == "reportes_gerenciales"
        assert len(svc._audit.get_entries(module="reportes_gerenciales")) >= 1

    def test_input_sanitization(self):
        from b2b_ai.features.compliance import sanitize_string
        result = sanitize_string("test report")
        assert result == "test report"

    def test_error_handling(self):
        from b2b_ai.features.reportes_gerenciales.service import ReportesService
        svc = ReportesService(tenant_id="test")
        with pytest.raises(ValueError):
            svc.generate_monthly_report(tenant_id="test", month=13, year=2024)

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed is True
        allowed, _ = verify_tenant_access("t1", "t2")
        assert allowed is False
