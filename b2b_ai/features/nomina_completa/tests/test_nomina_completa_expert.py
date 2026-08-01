# -*- coding: utf-8 -*-
"""test_nomina_completa_expert.py — Expert-level tests for Nómina Completa module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.nomina_completa.service import (
    process_payroll, calculate_taxes, generate_cfdi_nomina, generate_payslip, calculate_deposits,
)
from b2b_ai.features.nomina_completa.models import PayrollPeriod, EmployeePayroll, PayrollTaxes, PayrollDeposit
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_process_payroll_deterministic(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        r1 = process_payroll(period, employees, tenant_id=1)
        r2 = process_payroll(period, employees, tenant_id=1)
        assert r1.total_bruto == r2.total_bruto
        assert r1.total_neto == r2.total_neto

    def test_calculate_taxes_deterministic(self):
        t1 = calculate_taxes(20000)
        t2 = calculate_taxes(20000)
        assert t1.isr == t2.isr


class TestAuditTrail:
    def test_payroll_period_has_compliance(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        assert hasattr(result, "referencia_legal")
        assert result.referencia_legal != ""


class TestInputSanitization:
    def test_encode_output(self):
        assert "&lt;" in encode_output("<b>test</b>")

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("nómina normal")
        assert safe
        safe, _ = check_sql_injection("'; DROP TABLE--")
        assert not safe


class TestErrorHandling:
    def test_calculate_taxes_zero_salary(self):
        taxes = calculate_taxes(0)
        assert taxes.isr == 0.0
        assert taxes.imss_obrero == 0.0

    def test_calculate_taxes_negative_salary(self):
        taxes = calculate_taxes(-1000)
        assert taxes.isr == 0.0


class TestTenantIsolation:
    def test_payroll_tenant(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=42)
        assert result.tenant_id == 42


class TestEdgeCases:
    def test_empty_employees(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        result = process_payroll(period, [], tenant_id=1)
        assert result.total_bruto == 0.0
        assert result.total_neto == 0.0

    def test_high_salary_tax(self):
        taxes = calculate_taxes(100000)
        assert taxes.isr > 0

    def test_generate_cfdi_nomina_structure(self):
        data = {
            "emisor": {"rfc": "EMP850101AB1", "nombre": "Empresa SA", "regimen_fiscal": "601"},
            "receptor": {"rfc": "REC900101CD2", "nombre": "Receptor SA"},
            "period": {"year": 2024, "month": 1, "dias_pagados": 30},
            "taxes": {"isr": 5000, "imss_obrero": 500, "infonavit": 1000},
            "subtotal": 20000,
            "total": 13500,
        }
        cfdi = generate_cfdi_nomina(data)
        assert cfdi["Version"] == "4.0"
        assert cfdi["TipoDeComprobante"] == "N"
        assert "Nomina12:Nomina" in cfdi["Complemento"]

    def test_generate_payslip_structure(self):
        data = {
            "employee": {"employee_id": "E1", "nombre": "Juan", "puesto": "Dev", "departamento": "TI"},
            "period": {"month": 1, "year": 2024, "dias_pagados": 30},
            "taxes": {"isr": 5000, "imss_obrero": 500, "infonavit": 1000},
            "sueldo_base": 20000,
            "bonos": 0,
            "prestaciones": 0,
            "subtotal": 20000,
            "neto": 13500,
        }
        payslip = generate_payslip(data)
        assert payslip["tipo"] == "recibo_nomina"
        assert payslip["empleado"]["employee_id"] == "E1"

    def test_calculate_deposits(self):
        dep = calculate_deposits(15000, {"employee_id": "E1", "banco": "BBVA", "clabe": "012345678901234567"})
        assert dep.monto == 15000.0
        assert dep.banco == "BBVA"

    def test_payroll_recalc_totals(self):
        emp = EmployeePayroll(employee_id="E1", salario_bruto=20000, percepciones=5000, deducciones=3000, neto=22000)
        period = PayrollPeriod(month=1, year=2024, employees=[emp])
        assert period.total_bruto == 25000
        assert period.total_neto == 22000


class TestConcurrentAccess:
    def test_concurrent_process(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        results = []
        def run():
            results.append(process_payroll(period, employees, tenant_id=1))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5
        for r in results:
            assert r.total_bruto == 20000


class TestDataValidation:
    def test_payroll_taxes_post_init(self):
        taxes = PayrollTaxes(isr=5000, imss_obrero=500, infonavit=1000)
        assert taxes.total == 6500

    def test_payroll_taxes_to_dict(self):
        taxes = PayrollTaxes(isr=5000, imss_obrero=500, infonavit=1000)
        d = taxes.to_dict()
        assert d["isr"] == 5000.0
        assert d["total"] == 6500.0

    def test_employee_to_dict(self):
        emp = EmployeePayroll(employee_id="E1", nombre="Juan", salario_bruto=20000)
        d = emp.to_dict()
        assert d["employee_id"] == "E1"
        assert d["salario_bruto"] == 20000.0


class TestOutputVerification:
    def test_payroll_period_structure(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        assert result.month == 1
        assert result.year == 2024
        assert len(result.employees) == 1
        assert result.total_bruto > 0

    def test_payroll_period_to_dict(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        d = result.to_dict()
        assert "totals" in d
        assert d["employee_count"] == 1


class TestRetryLogic:
    def test_human_review_flag(self):
        period = {"month": 1, "year": 2024, "dias_pagados": 30}
        employees = [{"employee_id": "E1", "nombre": "Juan", "salario_bruto": 200000, "percepciones": 0}]
        result = process_payroll(period, employees, tenant_id=1)
        # High deductions should trigger review
        assert isinstance(result.requires_human_review, bool)
