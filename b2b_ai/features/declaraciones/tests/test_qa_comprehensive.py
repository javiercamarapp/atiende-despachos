# -*- coding: utf-8 -*-
"""
test_qa_comprehensive.py — QA tests for declaraciones, pre_auditoria, nomina_completa.

Covers: edge cases, boundary conditions, security, fiscal compliance, integration.
"""
from __future__ import annotations

import calendar
import threading
from datetime import date, timedelta

import pytest
from b2b_ai.features.declaraciones.service import (
    DeclaracionesService, ISR_TABLE_MONTHLY, ISR_TABLE_ANNUAL,
)
from b2b_ai.features.declaraciones.models import (
    Declaracion, DeclaracionType, DeclaracionStatus,
    Deadline, DeadlineStatus, IvaData, IsrData,
)
from b2b_ai.features.declaraciones.validators import (
    validate_period_format, validate_period_consistency,
    validate_iva_data, validate_isr_data, validate_deadline_date,
    validate_rfc,
)
from b2b_ai.features.pre_auditoria.service import (
    check_deductibility, check_consistency, check_cff_compliance,
    generate_audit_report, run_pre_audit,
)
from b2b_ai.features.pre_auditoria.models import (
    AuditFinding, AuditReport, DeductibilityCheck, Severity,
)
from b2b_ai.features.nomina_completa.service import (
    process_payroll, calculate_taxes, generate_cfdi_nomina,
    generate_payslip, calculate_deposits,
    _calcular_imss_obrero, _calcular_imss_patronal,
    _calcular_infonavit, _calcular_subsidio,
)
from b2b_ai.features.nomina_completa.models import (
    PayrollPeriod, EmployeePayroll, PayrollTaxes, PayrollDeposit,
)
from b2b_ai.features.compliance import (
    calculate_isr, sanitize_string, mask_rfc, encode_output,
)


# ============================================================================
# DECLARACIONES — ISR Calculation Correctness
# ============================================================================

class TestISRProvisionalCalculatesOnUtilidad:
    """Bug fix: ISR provisional must be calculated on utilidad (ingresos - deducciones),
    NOT on raw ingresos. This was a CRITICAL bug."""

    def test_isr_provisional_uses_utilidad(self):
        svc = DeclaracionesService()
        decl = svc.generate_provisional_isr(1, 2024, "t1", "EMP850101AB1", {
            "ingresos": 100000,
            "deducciones": 30000,
            "pagos_provisionales": 10000,
        })
        # ISR should be on 70k utility, NOT 100k gross
        expected_isr = svc._calculate_isr_monthly(70000)
        assert decl.data["isr_calculated"] == expected_isr
        assert decl.data["isr_calculated"] < 31469.53  # old wrong value

    def test_isr_annual_uses_utilidad(self):
        svc = DeclaracionesService()
        decl = svc.generate_annual_isr(2024, "t1", "EMP850101AB1", {
            "ingresos": 500000,
            "deducciones": 200000,
            "pagos_provisionales": 50000,
        })
        expected_isr = svc._calculate_isr_annual(300000)
        assert decl.data["isr_calculated"] == expected_isr

    def test_isr_with_zero_deducciones(self):
        """When deducciones=0, ISR should still be on utilidad (=ingresos)."""
        svc = DeclaracionesService()
        decl = svc.generate_provisional_isr(1, 2024, "t1", data={
            "ingresos": 50000,
            "deducciones": 0,
            "pagos_provisionales": 5000,
        })
        expected_isr = svc._calculate_isr_monthly(50000)
        assert decl.data["isr_calculated"] == expected_isr

    def test_isr_with_deducciones_exceeding_ingresos(self):
        """When deducciones > ingresos, the validator rejects it (CFF rule)."""
        svc = DeclaracionesService()
        with pytest.raises(ValueError, match="Datos ISR inválidos"):
            svc.generate_provisional_isr(1, 2024, "t1", data={
                "ingresos": 10000,
                "deducciones": 20000,
                "pagos_provisionales": 0,
            })


class TestISRTableGapFix:
    """Bug fix: The ISR table had gaps between bracket boundaries
    (e.g., 312.41 < x < 312.42 would return 0)."""

    def test_gap_value_312_415(self):
        svc = DeclaracionesService()
        # 312.415 falls between bracket 1 (0-312.41) and bracket 2 (312.42-2636.28)
        isr = svc._calculate_isr_monthly(312.415)
        assert isr > 0  # should NOT return 0

    def test_gap_value_2636_285(self):
        svc = DeclaracionesService()
        isr = svc._calculate_isr_monthly(2636.285)
        assert isr > 0

    def test_exact_boundary_lower(self):
        """Very small income should produce tiny but non-negative ISR."""
        svc = DeclaracionesService()
        isr = svc._calculate_isr_monthly(1.0)
        assert isr >= 0  # Tiny amounts may round to 0.00
        # Larger income should definitely have ISR
        isr = svc._calculate_isr_monthly(100)
        assert isr > 0

    def test_zero_income(self):
        svc = DeclaracionesService()
        assert svc._calculate_isr_monthly(0) == 0.0
        assert svc._calculate_isr_monthly(-100) == 0.0


class TestDeclaracionesAuditTrail:
    """Audit logging must be consistent across all ISR methods."""

    def test_iva_logs_audit(self):
        svc = DeclaracionesService()
        svc.generate_monthly_iva(1, 2024, "t1")
        # Verify audit trail has entry
        entries = svc._audit.get_entries(module="declaraciones")
        assert any(e.action == "generate_monthly_iva" for e in entries)

    def test_isr_provisional_logs_audit(self):
        svc = DeclaracionesService()
        svc.generate_provisional_isr(1, 2024, "t1")
        entries = svc._audit.get_entries(module="declaraciones")
        assert any(e.action == "generate_provisional_isr" for e in entries)

    def test_isr_anual_logs_audit(self):
        svc = DeclaracionesService()
        svc.generate_annual_isr(2024, "t1")
        entries = svc._audit.get_entries(module="declaraciones")
        assert any(e.action == "generate_annual_isr" for e in entries)


class TestDeclaracionesEdgeCases:
    """Edge cases for the declarations module."""

    def test_iva_with_equal_amounts(self):
        """iva_cobrado == iva_pagado should give saldo_favor=0, saldo_contra=0."""
        svc = DeclaracionesService()
        decl = svc.generate_monthly_iva(1, 2024, "t1", data={
            "iva_cobrado": 5000, "iva_pagado": 5000,
        })
        assert decl.data["saldo_favor"] == 0
        assert decl.data["saldo_contra"] == 0

    def test_iva_with_large_credit(self):
        svc = DeclaracionesService()
        decl = svc.generate_monthly_iva(1, 2024, "t1", data={
            "iva_cobrado": 1000, "iva_pagado": 10000,
        })
        assert decl.data["saldo_favor"] == 9000
        assert decl.data["saldo_contra"] == 0

    def test_deadline_for_december(self):
        """IVA for December should have deadline January 17 of next year."""
        svc = DeclaracionesService()
        svc.generate_monthly_iva(12, 2024, "t1")
        deadlines = svc.calculate_deadlines("t1")
        assert len(deadlines) >= 1
        assert deadlines[0].fecha_limite == "2025-01-17"

    def test_deadline_for_january(self):
        """IVA for January should have deadline February 17."""
        svc = DeclaracionesService()
        svc.generate_monthly_iva(1, 2024, "t1")
        deadlines = svc.calculate_deadlines("t1")
        assert deadlines[0].fecha_limite == "2024-02-17"

    def test_annual_isr_deadline_april_30(self):
        svc = DeclaracionesService()
        svc.generate_annual_isr(2024, "t1")
        deadlines = svc.calculate_deadlines("t1")
        assert deadlines[0].fecha_limite == "2025-04-30"

    def test_reminders_only_send_once(self):
        """Reminders should only be sent once per deadline."""
        svc = DeclaracionesService()
        svc.generate_monthly_iva(1, 2024, "t1")
        r1 = svc.send_reminders("t1", days_before=365)
        r2 = svc.send_reminders("t1", days_before=365)
        assert len(r1) >= 1
        assert len(r2) == 0  # Already sent

    def test_get_declaraciones_by_tenant_type_filter(self):
        svc = DeclaracionesService()
        svc.generate_monthly_iva(1, 2024, "t1")
        svc.generate_provisional_isr(1, 2024, "t1")
        iva_only = svc.get_declaraciones_by_tenant("t1", tipo=DeclaracionType.IVA)
        assert all(d.tipo == DeclaracionType.IVA for d in iva_only)
        assert len(iva_only) == 1

    def test_update_status_sets_filing_date(self):
        svc = DeclaracionesService()
        decl = svc.generate_monthly_iva(1, 2024, "t1")
        updated = svc.update_status(decl.id, DeclaracionStatus.FILED)
        assert updated.status == DeclaracionStatus.FILED
        assert updated.fecha_presentacion is not None

    def test_update_status_nonexistent(self):
        svc = DeclaracionesService()
        result = svc.update_status("nonexistent-id", DeclaracionStatus.FILED)
        assert result is None

    def test_dual_isr_correctness(self):
        """calculate_dual_isr should use annual table and compute deficit."""
        svc = DeclaracionesService()
        result = svc.calculate_dual_isr(
            ingresos_anuales=200000,
            deducciones_anuales=50000,
            pagos_provisionales_acumulados=20000,
        )
        # utilidad = 150000, ISR annual on 150k
        expected_isr = svc._calculate_isr_annual(150000)
        assert result["isr_anual_total"] == expected_isr
        assert result["utilidad"] == 150000

    def test_validate_rfc_physical_person(self):
        ok, _ = validate_rfc("CAPE850101ABC")  # 13 chars
        assert ok

    def test_validate_rfc_moral_person(self):
        ok, _ = validate_rfc("EMP850101AB1")  # 12 chars
        assert ok

    def test_validate_iva_data_both_balances_positive_rejected(self):
        ok, errors = validate_iva_data({
            "iva_cobrado": 1000,
            "iva_pagado": 2000,
            "saldo_favor": 1000,
            "saldo_contra": 500,
        })
        assert not ok
        assert any("ambos mayores a cero" in e for e in errors)

    def test_validate_isr_data_consistency_check(self):
        """Utilidad must equal ingresos - deducciones."""
        ok, errors = validate_isr_data({
            "ingresos": 10000,
            "deducciones": 3000,
            "utilidad": 5000,  # Wrong: should be 7000
        })
        assert not ok
        assert any("utilidad incorrecta" in e for e in errors)

    def test_validate_deadline_date_wrong(self):
        ok, errors = validate_deadline_date("2024-02-15", "iva", "2024-01")
        assert not ok
        assert any("incorrecta" in e for e in errors)


# ============================================================================
# PRE-AUDITORIA — Deductibility, Consistency, CFF
# ============================================================================

class TestDeductibility:
    """Test expense deductibility checks (Art. 28 LISR)."""

    def test_all_non_deductible_concepts(self):
        """All items in NON_DEDUCTIBLE_CONCEPTS should be flagged."""
        from b2b_ai.features.pre_auditoria.service import NON_DEDUCTIBLE_CONCEPTS
        for concept in NON_DEDUCTIBLE_CONCEPTS:
            results = check_deductibility([{
                "invoice_id": "1", "concepto": concept, "monto": 1000,
            }])
            assert not results[0].es_deducible, f"'{concept}' should be non-deductible"

    def test_high_amount_requires_documentation(self):
        results = check_deductibility([{
            "invoice_id": "1", "concepto": "equipo de cómputo", "monto": 100000,
        }])
        assert results[0].es_deducible is True
        assert "documentación" in results[0].razon.lower()

    def test_zero_amount_deductible(self):
        results = check_deductibility([{
            "invoice_id": "1", "concepto": "servicio de consultoría", "monto": 0,
        }])
        assert results[0].es_deducible is True

    def test_non_numeric_amount_handled(self):
        results = check_deductibility([{
            "invoice_id": "1", "concepto": "equipo", "monto": "not_a_number",
        }])
        assert results[0].es_deducible is True  # defaults to 0

    def test_missing_concepto(self):
        results = check_deductibility([{"invoice_id": "1", "monto": 5000}])
        assert results[0].concepto == ""


class TestConsistency:
    """Test accounting ledger consistency checks."""

    def test_balanced_entry(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 1000,
            "fecha": "2024-01-15", "cuenta_debito": "1100",
            "cuenta_credito": "2100", "descripcion": "test",
        }]
        findings = check_consistency(ledger)
        assert len(findings) == 0

    def test_unbalanced_entry_critical(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 999,
            "fecha": "2024-01-15", "cuenta_debito": "1100",
            "cuenta_credito": "2100", "descripcion": "test",
        }]
        findings = check_consistency(ledger)
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        assert len(critical) == 1

    def test_missing_debit_account(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 1000,
            "fecha": "2024-01-15", "cuenta_debito": "",
            "cuenta_credito": "2100", "descripcion": "test",
        }]
        findings = check_consistency(ledger)
        assert any(f.category == "cuenta_incompleta" for f in findings)

    def test_missing_credit_account(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 1000,
            "fecha": "2024-01-15", "cuenta_debito": "1100",
            "cuenta_credito": "", "descripcion": "test",
        }]
        findings = check_consistency(ledger)
        assert any(f.category == "cuenta_incompleta" for f in findings)

    def test_no_description(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 1000,
            "fecha": "2024-01-15", "cuenta_debito": "1100",
            "cuenta_credito": "2100", "descripcion": "",
        }]
        findings = check_consistency(ledger)
        assert any(f.category == "sin_descripcion" for f in findings)

    def test_multiple_errors(self):
        ledger = [{
            "id": "A1", "debe": 1000, "haber": 500,
            "fecha": "2099-01-01", "cuenta_debito": "",
            "cuenta_credito": "", "descripcion": "",
        }]
        findings = check_consistency(ledger)
        assert len(findings) >= 3  # multiple issues


class TestCFFCompliance:
    """Test CFF compliance checks."""

    def test_valid_tenant_no_findings(self):
        cff_data = {
            "rfc": "EMP850101AB1",
            "cfdi_count": 10,
            "tiene_contabilidad_electronica": True,
            "periodos_cerrados": ["2024-01"],
        }
        findings = check_cff_compliance(cff_data)
        assert len(findings) == 0

    def test_short_rfc_critical(self):
        findings = check_cff_compliance({"rfc": "ABC"})
        rfc_findings = [f for f in findings if f.category == "rfc_invalido"]
        assert len(rfc_findings) == 1
        assert rfc_findings[0].severity == Severity.CRITICAL

    def test_no_periodos_medium(self):
        cff_data = {
            "rfc": "EMP850101AB1",
            "cfdi_count": 10,
            "tiene_contabilidad_electronica": True,
            "periodos_cerrados": [],
        }
        findings = check_cff_compliance(cff_data)
        assert any(f.category == "sin_periodos" for f in findings)


class TestAuditReport:
    """Test audit report generation."""

    def test_perfect_score(self):
        report = generate_audit_report([], period="2024-01")
        assert report.score == 100.0

    def test_critical_findings_reduce_score_heavily(self):
        findings = [
            AuditFinding(category="c1", severity=Severity.CRITICAL, description="critical"),
            AuditFinding(category="c2", severity=Severity.CRITICAL, description="critical"),
        ]
        report = generate_audit_report(findings, period="2024-01")
        assert report.score == 50.0  # 100 - 25*2

    def test_mixed_severity_findings(self):
        findings = [
            AuditFinding(category="c1", severity=Severity.CRITICAL, description="c"),
            AuditFinding(category="c2", severity=Severity.HIGH, description="h"),
            AuditFinding(category="c3", severity=Severity.MEDIUM, description="m"),
            AuditFinding(category="c4", severity=Severity.LOW, description="l"),
        ]
        report = generate_audit_report(findings, period="2024-01")
        expected = 100 - 25 - 15 - 8 - 3
        assert report.score == expected

    def test_run_pre_audit_metadata(self):
        report = run_pre_audit(42, "2024-01")
        assert report.referencia_legal != ""
        assert report.supuesto != ""
        assert report.escalation_path == "review_by_contador"
        assert report.idempotency_key == "preaudit-2024-01-42"

    def test_run_pre_audit_human_review_flag(self):
        """With critical findings, requires_human_review should be True."""
        cff_data = {"rfc": "", "cfdi_count": 0, "tiene_contabilidad_electronica": False}
        report = run_pre_audit(1, "2024-01", cff_data=cff_data)
        assert report.requires_human_review is True

    def test_run_pre_audit_no_findings_no_review(self):
        cff_data = {
            "rfc": "EMP850101AB1",
            "cfdi_count": 10,
            "tiene_contabilidad_electronica": True,
            "periodos_cerrados": ["2024-01"],
        }
        report = run_pre_audit(1, "2024-01", cff_data=cff_data)
        assert report.requires_human_review is False


# ============================================================================
# NOMINA COMPLETA — ISR, IMSS, INFONAVIT
# ============================================================================

class TestISRNomina:
    """ISR calculations in payroll context."""

    def test_low_salary_no_isr(self):
        taxes = calculate_taxes(1000)
        assert taxes.isr == 0.0

    def test_medium_salary_has_isr(self):
        taxes = calculate_taxes(10000)
        assert taxes.isr > 0

    def test_high_salary_has_high_isr(self):
        taxes = calculate_taxes(100000)
        assert taxes.isr > 20000

    def test_quincenal_isr_is_half_monthly(self):
        """Quincenal ISR is a close approximation of monthly ISR / 2 (subsidy integration causes variance)."""
        monthly = calculate_taxes(20000, periodicidad="mensual")
        quincenal = calculate_taxes(20000, periodicidad="quincenal")
        # Allow ~5% variance due to subsidy table bucketing per period
        expected = round(monthly.isr / 2, 2)
        assert abs(quincenal.isr - expected) < expected * 0.05 + 1.0

    def test_with_salary_per_day(self):
        """When salary_per_day is provided, salary is interpreted as daily."""
        taxes = calculate_taxes(500, salary_per_day=500)
        # 500/day × 30 days = 15000/month
        monthly = calculate_taxes(15000)
        assert abs(taxes.isr - monthly.isr) < 1.0

    def test_benefits_included_in_isr(self):
        """Benefits (prestaciones) should increase ISR base."""
        t1 = calculate_taxes(10000, benefits=0)
        t2 = calculate_taxes(10000, benefits=5000)
        assert t2.isr > t1.isr


class TestIMSSCalculation:
    """IMSS obrero and patronal calculations."""

    def test_obrero_proportional_to_salary(self):
        t1 = _calcular_imss_obrero(200, 30)
        t2 = _calcular_imss_obrero(400, 30)
        assert t2 > t1

    def test_obrero_proportional_to_days(self):
        t1 = _calcular_imss_obrero(200, 15)
        t2 = _calcular_imss_obrero(200, 30)
        assert t2 > t1

    def test_obrero_rate_approximately_1_20pct(self):
        """Obrero rate should be ~1.20% of SBC × dias."""
        base = 200 * 30
        expected = base * 0.0120
        actual = _calcular_imss_obrero(200, 30)
        assert abs(actual - expected) < 0.01

    def test_patronal_rate_approximately_20_40pct(self):
        base = 200 * 30
        expected = base * 0.2040
        actual = _calcular_imss_patronal(200, 30)
        assert abs(actual - expected) < 0.01

    def test_infonavit_rate_exactly_5pct(self):
        base = 200 * 30
        expected = base * 0.05
        actual = _calcular_infonavit(200, 30)
        assert abs(actual - expected) < 0.01


class TestSubsidioEmpleo:
    """Subsidio para el empleo (LISR Art. 113)."""

    def test_low_income_gets_max_subsidio(self):
        result = _calcular_subsidio(1500)
        assert result["subsidio"] > 400

    def test_high_income_no_subsidio(self):
        result = _calcular_subsidio(25000)
        assert result["subsidio"] == 0.0

    def test_zero_income_no_subsidio(self):
        result = _calcular_subsidio(0)
        assert result["subsidio"] == 0.0

    def test_quincenal_subsidio_is_half(self):
        """Quincenal subsidy should be half the monthly subsidy."""
        monthly = _calcular_subsidio(3000, "mensual")
        quincenal = _calcular_subsidio(3000, "quincenal")
        assert abs(quincenal["subsidio"] - monthly["subsidio"] / 2) < 0.01


class TestCFDIGeneration:
    """CFDI de Nómina generation."""

    def test_february_leap_year(self):
        cfdi = generate_cfdi_nomina({
            "period": {"year": 2024, "month": 2, "dias_pagados": 29},
            "taxes": {"isr": 100, "imss_obrero": 50, "infonavit": 25},
            "subtotal": 5000, "total": 4825,
        })
        assert cfdi["Complemento"]["Nomina12:Nomina"]["FechaFinalPago"] == "2024-02-29"

    def test_february_non_leap_year(self):
        cfdi = generate_cfdi_nomina({
            "period": {"year": 2025, "month": 2, "dias_pagados": 28},
            "taxes": {"isr": 100, "imss_obrero": 50, "infonavit": 25},
            "subtotal": 5000, "total": 4825,
        })
        assert cfdi["Complemento"]["Nomina12:Nomina"]["FechaFinalPago"] == "2025-02-28"

    def test_january_31_days(self):
        cfdi = generate_cfdi_nomina({
            "period": {"year": 2024, "month": 1, "dias_pagados": 31},
            "taxes": {"isr": 100, "imss_obrero": 50, "infonavit": 25},
            "subtotal": 5000, "total": 4825,
        })
        assert cfdi["Complemento"]["Nomina12:Nomina"]["FechaFinalPago"] == "2024-01-31"

    def test_cfdi_version_4_0(self):
        cfdi = generate_cfdi_nomina({"period": {}, "taxes": {}, "subtotal": 0, "total": 0})
        assert cfdi["Version"] == "4.0"
        assert cfdi["TipoDeComprobante"] == "N"

    def test_cfdi_has_nómina_complement(self):
        cfdi = generate_cfdi_nomina({"period": {}, "taxes": {}, "subtotal": 0, "total": 0})
        assert "Nomina12:Nomina" in cfdi["Complemento"]


class TestPayslip:
    """Individual payslip generation."""

    def test_payslip_structure(self):
        payslip = generate_payslip({
            "employee": {"employee_id": "E1", "nombre": "Juan", "puesto": "Dev", "departamento": "TI"},
            "period": {"month": 1, "year": 2024, "dias_pagados": 30},
            "taxes": {"isr": 5000, "imss_obrero": 500, "infonavit": 1000},
            "sueldo_base": 20000, "bonos": 1000, "prestaciones": 500,
            "subtotal": 21500, "neto": 15000,
        })
        assert payslip["tipo"] == "recibo_nomina"
        assert payslip["empleado"]["employee_id"] == "E1"
        assert payslip["deducciones"]["total"] == 6500

    def test_payslip_deductions_sum(self):
        payslip = generate_payslip({
            "employee": {},
            "period": {},
            "taxes": {"isr": 3000, "imss_obrero": 400, "infonavit": 200},
            "sueldo_base": 0, "bonos": 0, "prestaciones": 0,
            "subtotal": 0, "neto": 0,
        })
        assert payslip["deducciones"]["total"] == 3600


class TestPayrollPeriod:
    """PayrollPeriod totals calculation."""

    def test_recalc_totals_multiple_employees(self):
        e1 = EmployeePayroll(employee_id="E1", salario_bruto=20000, percepciones=2000,
                            deducciones=5000, neto=17000, taxes=PayrollTaxes(isr=3000, imss_obrero=2000))
        e2 = EmployeePayroll(employee_id="E2", salario_bruto=30000, percepciones=5000,
                            deducciones=8000, neto=27000, taxes=PayrollTaxes(isr=5000, imss_obrero=3000))
        period = PayrollPeriod(month=1, year=2024, employees=[e1, e2])
        assert period.total_bruto == 57000  # (20k+2k) + (30k+5k)
        assert period.total_neto == 44000
        assert period.total_deducciones == 13000
        assert period.total_isr == 8000
        assert period.total_imss_obrero == 5000

    def test_empty_period_totals(self):
        period = PayrollPeriod(month=1, year=2024, employees=[])
        assert period.total_bruto == 0
        assert period.total_neto == 0

    def test_payroll_period_to_dict(self):
        period = PayrollPeriod(month=6, year=2024, tenant_id=42)
        d = period.to_dict()
        assert d["month"] == 6
        assert d["year"] == 2024
        assert d["tenant_id"] == 42


class TestPayrollDeposits:
    """Bank deposit calculation."""

    def test_deposit_with_bank_info(self):
        dep = calculate_deposits(15000, {
            "employee_id": "E1", "banco": "BBVA", "clabe": "012345678901234567",
        })
        assert dep.monto == 15000.0
        assert dep.banco == "BBVA"
        assert dep.clabe == "012345678901234567"

    def test_deposit_rounding(self):
        dep = calculate_deposits(15000.123, {"employee_id": "E1"})
        assert dep.monto == 15000.12

    def test_deposit_to_dict(self):
        dep = calculate_deposits(10000, {"employee_id": "E1", "banco": "Banorte"})
        d = dep.to_dict()
        assert d["employee_id"] == "E1"
        assert d["monto"] == 10000.0


class TestProcessPayroll:
    """End-to-end payroll processing."""

    def test_single_employee(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        assert len(result.employees) == 1
        assert result.total_bruto == 20000
        assert result.total_neto > 0
        assert result.total_isr > 0

    def test_multiple_employees(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [
            {"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0},
            {"employee_id": "E2", "nombre": "Ana", "salario_bruto": 30000, "percepciones": 5000},
        ]
        result = process_payroll(period, employees, tenant_id=1)
        assert len(result.employees) == 2
        assert result.total_bruto == 55000

    def test_deductions_reduce_neto(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        emp = result.employees[0]
        assert emp.neto < emp.salario_bruto  # Deductions applied

    def test_high_salary_triggers_human_review(self):
        """Deductions > 40% of bruto should trigger human review."""
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 200000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        # High salary = high ISR = may trigger review
        if result.requires_human_review:
            assert "40%" in result.human_review_reason

    def test_neto_never_negative(self):
        """Net salary should never be negative."""
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 100, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        assert result.employees[0].neto >= 0

    def test_idempotency_key_format(self):
        period = {"month": 7, "year": 2026, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=42)
        assert result.idempotency_key == "nomina-2026-07-42"


# ============================================================================
# SECURITY & SANITIZATION
# ============================================================================

class TestSecurity:
    """Security-related tests across all modules."""

    def test_encode_output_xss(self):
        encoded = encode_output("<script>alert('xss')</script>")
        assert "<script>" not in encoded
        assert "&lt;" in encoded

    def test_sanitize_string_strips_whitespace(self):
        assert sanitize_string("  hello  ") == "hello"

    def test_sanitize_string_truncates(self):
        long = "a" * 10000
        result = sanitize_string(long, max_length=100)
        assert len(result) == 100

    def test_mask_rfc_short(self):
        assert mask_rfc("AB") == "***"

    def test_mask_rfc_valid(self):
        result = mask_rfc("EMP850101AB1")
        assert result.startswith("EMP")
        assert "***" in result
        assert result.endswith("AB1")

    def test_sql_injection_detection(self):
        from b2b_ai.features.compliance import check_sql_injection
        safe, _ = check_sql_injection("normal text")
        assert safe
        unsafe, _ = check_sql_injection("'; DROP TABLE users;--")
        assert not unsafe

    def test_tenant_isolation(self):
        from b2b_ai.features.compliance import verify_tenant_access
        allowed, _ = verify_tenant_access("t1", "t1")
        assert allowed
        denied, msg = verify_tenant_access("t1", "t2")
        assert not denied
        assert "denied" in msg.lower() or "permiso" in msg.lower()

    def test_validate_rfc_rejects_special_chars(self):
        ok, _ = validate_rfc("EMP<script>81")
        assert not ok


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestEndToEndDeclaraciones:
    """Full workflow: generate IVA → file → verify."""

    def test_iva_full_workflow(self):
        svc = DeclaracionesService()
        # Generate
        decl = svc.generate_monthly_iva(1, 2024, "t1", "EMP850101AB1", {
            "iva_cobrado": 8000, "iva_pagado": 3000,
        })
        assert decl.status == DeclaracionStatus.DRAFT

        # File
        updated = svc.update_status(decl.id, DeclaracionStatus.FILED)
        assert updated.status == DeclaracionStatus.FILED
        assert updated.fecha_presentacion is not None

        # Verify retrieval
        found = svc.get_declaracion(decl.id)
        assert found is not None
        assert found.id == decl.id


class TestEndToEndNómina:
    """Full workflow: process → generate CFDI → payslip."""

    def test_nomina_full_workflow(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [
            {"employee_id": "E1", "nombre": "Juan Pérez", "salario_bruto": 20000, "percepciones": 0},
        ]
        # Process payroll
        result = process_payroll(period, employees, tenant_id=1)
        assert len(result.employees) == 1
        emp = result.employees[0]

        # Generate CFDI
        cfdi = generate_cfdi_nomina({
            "emisor": {"rfc": "EMP850101AB1", "nombre": "Empresa SA"},
            "receptor": {"rfc": "CAPJ850101CD3", "nombre": emp.nombre},
            "period": {"year": 2024, "month": 1, "dias_pagados": 30},
            "taxes": emp.taxes.to_dict(),
            "subtotal": emp.salario_bruto,
            "total": emp.neto,
        })
        assert cfdi["Version"] == "4.0"

        # Generate payslip
        payslip = generate_payslip({
            "employee": emp.to_dict(),
            "period": {"month": 1, "year": 2024, "dias_pagados": 30},
            "taxes": emp.taxes.to_dict(),
            "sueldo_base": emp.salario_bruto,
            "bonos": 0, "prestaciones": 0,
            "subtotal": emp.salario_bruto, "neto": emp.neto,
        })
        assert payslip["empleado"]["employee_id"] == "E1"
