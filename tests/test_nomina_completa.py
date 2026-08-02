# -*- coding: utf-8 -*-
"""
test_nomina_completa.py — Tests del módulo de Nómina Completa.

Cobertura:
  Taxes: ISR progresivo, IMSS patronal/obrero, INFONAVIT, salario cero.
  Process: 1 empleado, varios empleados, percepciones, neto positivo.
  CFDI:    genera UUID, campos requeridos, complemento nómina.
  Payslip: campos, neto correcto, deducciones.
  Routes:  POST /process, POST /cfdi, GET /payslip, GET /summary, POST /taxes,
           empleado no encontrado.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.nomina_completa.models import (
    EmployeePayroll,
    PayrollPeriod,
    PayrollTaxes,
)
from b2b_ai.features.nomina_completa.service import (
    calculate_taxes,
    calculate_deposits,
    generate_cfdi_nomina,
    generate_payslip,
    process_payroll,
)
from b2b_ai.features.nomina_completa.routes import build_nomina_completa_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_nomina_completa_router())
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _empleado(**overrides) -> dict:
    base = {
        "employee_id": "E001",
        "nombre": "Juan Pérez",
        "salario_bruto": 25000.0,
        "percepciones": 2000.0,
        "salario_diario": 833.33,
        "banco": "BBVA",
        "clabe": "012345678901234567",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Tests: Cálculo de Impuestos
# ===========================================================================
class TestTaxes:
    def test_isr_bajo(self):
        taxes = calculate_taxes(salary=10000)
        # $10,000 cae en el tramo 2026 (6936.24, 13074.34] a 10.88%
        # ISR puro = 406.08 + (10000 - 6936.24) * 0.1088 = 739.42
        # Subsidio 2026 para $10,000 = 209.13
        # ISR neto = 739.42 - 209.13 = 530.29
        assert taxes.isr > 0, "ISR must be > 0 for $10,000 (LISR Art. 96)"
        assert abs(taxes.isr - 530.29) < 1.0

    def test_isr_medio(self):
        taxes = calculate_taxes(salary=50000)
        assert taxes.isr > 0

    def test_isr_alto(self):
        taxes = calculate_taxes(salary=150000)
        assert taxes.isr > 10000

    def test_imss_patronal(self):
        taxes = calculate_taxes(salary=25000, salary_per_day=833.33)
        assert taxes.imss_patronal > 0

    def test_imss_obrero(self):
        taxes = calculate_taxes(salary=25000, salary_per_day=833.33)
        assert taxes.imss_obrero > 0

    def test_infonavit(self):
        taxes = calculate_taxes(salary=25000, salary_per_day=833.33)
        assert taxes.infonavit > 0

    def test_total_deducciones(self):
        taxes = calculate_taxes(salary=25000, salary_per_day=833.33)
        expected = taxes.isr + taxes.imss_obrero + taxes.infonavit
        assert abs(taxes.total - expected) < 0.01

    def test_salario_cero(self):
        taxes = calculate_taxes(salary=0)
        assert taxes.total == 0.0

    def test_subsidio_reduces_isr(self):
        """[11] Subsidio para el empleo reduces ISR for low-income workers."""
        # $8,000 monthly: subsidio should apply
        taxes = calculate_taxes(salary=8000)
        # ISR before subsidio for $8,000 (tabla 2026, tramo 10.88%) = 521.82
        # Subsidio 2026 para $8,000 = 253.54
        # ISR neto = 521.82 - 253.54 = 268.28
        assert taxes.isr > 0, "ISR should be positive after subsidio"
        # Verify subsidio was applied (ISR neto < ISR before subsidio)
        isr_before_subsidio = 521.82
        assert taxes.isr < isr_before_subsidio, "Subsidio should reduce ISR"

    def test_quincenal_isr(self):
        """[12] Quincenal ISR uses monthly table divided by 2."""
        # $15,000 monthly equivalent → $7,500 quincenal
        taxes_quincenal = calculate_taxes(salary=15000, periodicidad="quincenal")
        taxes_mensual = calculate_taxes(salary=15000, periodicidad="mensual")
        # Quincenal ISR should be approximately half of monthly ISR
        assert taxes_quincenal.isr < taxes_mensual.isr

    def test_imss_uses_dias_pagados(self):
        """[10] IMSS should scale with dias_pagados."""
        taxes_15 = calculate_taxes(salary=25000, salary_per_day=833.33, dias_pagados=15)
        taxes_30 = calculate_taxes(salary=25000, salary_per_day=833.33, dias_pagados=30)
        # IMSS for 15 days should be less than for 30 days
        assert taxes_15.imss_obrero < taxes_30.imss_obrero
        assert taxes_15.imss_patronal < taxes_30.imss_patronal

    def test_to_dict(self):
        taxes = calculate_taxes(salary=25000)
        d = taxes.to_dict()
        assert "isr" in d
        assert "imss_patronal" in d
        assert "total" in d


# ===========================================================================
# Tests: Procesamiento de Nómina
# ===========================================================================
class TestProcessPayroll:
    def test_un_empleado(self):
        period = process_payroll(
            period={"month": 7, "year": 2026, "dias_pagados": 30},
            employees=[_empleado()],
        )
        assert period.month == 7
        assert len(period.employees) == 1
        assert period.total_neto > 0

    def test_varios_empleados(self):
        emps = [
            _empleado(employee_id="E001", salario_bruto=25000),
            _empleado(employee_id="E002", nombre="Ana García", salario_bruto=35000),
        ]
        period = process_payroll(
            period={"month": 7, "year": 2026},
            employees=emps,
        )
        assert len(period.employees) == 2
        assert period.total_bruto == 60000 + 4000  # 25k+2k + 35k+2k

    def test_neto_mayor_cero(self):
        period = process_payroll(
            period={"month": 7, "year": 2026},
            employees=[_empleado(salario_bruto=50000)],
        )
        for emp in period.employees:
            assert emp.neto > 0

    def test_to_dict(self):
        period = process_payroll(
            period={"month": 7, "year": 2026},
            employees=[_empleado()],
        )
        d = period.to_dict()
        assert "totals" in d
        assert d["employee_count"] == 1


# ===========================================================================
# Tests: CFDI
# ===========================================================================
class TestCFDINomina:
    def test_genera_cfdi(self):
        cfdi = generate_cfdi_nomina({
            "emisor": {"rfc": "DESP820101AB1", "nombre": "Despacho Likida"},
            "receptor": {"rfc": "PEPJ800101ABC", "nombre": "Juan Pérez"},
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "subtotal": 25000,
            "total": 20000,
            "taxes": {"isr": 3000, "imss_obrero": 500, "infonavit": 1500},
        })
        assert "Version" in cfdi
        assert cfdi["Version"] == "4.0"
        assert cfdi["TipoDeComprobante"] == "N"

    def test_complemento_nomina(self):
        cfdi = generate_cfdi_nomina({
            "emisor": {"rfc": "XAXX010101000"},
            "receptor": {"rfc": "PEPJ800101ABC"},
            "period": {"month": 7, "year": 2026},
            "subtotal": 15000,
            "total": 12000,
            "taxes": {"isr": 2000, "imss_obrero": 400, "infonavit": 600},
        })
        assert "Complemento" in cfdi
        assert "Nomina12:Nomina" in cfdi["Complemento"]
        nomina = cfdi["Complemento"]["Nomina12:Nomina"]
        assert nomina["Version"] == "1.2"


# ===========================================================================
# Tests: Payslip
# ===========================================================================
class TestPayslip:
    def test_genera_payslip(self):
        payslip = generate_payslip({
            "employee": {"employee_id": "E001", "nombre": "Juan Pérez"},
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "taxes": {"isr": 3000, "imss_obrero": 500, "infonavit": 1500},
            "sueldo_base": 25000,
            "bonos": 0,
            "prestaciones": 2000,
            "subtotal": 27000,
            "neto": 22000,
        })
        assert payslip["tipo"] == "recibo_nomina"
        assert payslip["empleado"]["employee_id"] == "E001"
        assert payslip["neto"] == 22000

    def test_deducciones_en_payslip(self):
        payslip = generate_payslip({
            "employee": {"employee_id": "E002"},
            "period": {"month": 7, "year": 2026},
            "taxes": {"isr": 5000, "imss_obrero": 800, "infonavit": 2000},
            "sueldo_base": 35000,
            "bonos": 0,
            "prestaciones": 0,
            "subtotal": 35000,
            "neto": 27200,
        })
        ded = payslip["deducciones"]
        assert ded["isr"] == 5000
        # P1-1: el INFONAVIT es aportación patronal, NO se descuenta del
        # trabajador. El total de deducciones = isr + imss_obrero (5000+800).
        assert ded["total"] == 5800
        assert ded["es_patronal"]["infonavit"] is True


# ===========================================================================
# Tests: Routes
# ===========================================================================
class TestNominaCompletaRoutes:
    def test_process(self):
        resp = _client().post("/nomina-completa/process", json={
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "employees": [_empleado()],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "payroll" in data

    def test_cfdi(self):
        resp = _client().post("/nomina-completa/cfdi", json={
            "payroll_data": {
                "emisor": {"rfc": "DESP820101AB1"},
                "receptor": {"rfc": "PEPJ800101ABC"},
                "period": {"month": 7, "year": 2026},
                "subtotal": 25000,
                "total": 20000,
                "taxes": {"isr": 3000, "imss_obrero": 500, "infonavit": 1500},
            },
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_payslip(self):
        client = _client()
        client.post("/nomina-completa/process", json={
            "period": {"month": 7, "year": 2026},
            "employees": [_empleado()],
            "tenant_id": 1,
        })
        resp = client.get(
            "/nomina-completa/payslip/E001",
            params={"month": 7, "year": 2026, "tenant_id": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_payslip_not_found(self):
        resp = _client().get(
            "/nomina-completa/payslip/E999",
            params={"month": 7, "year": 2099, "tenant_id": 99},
        )
        assert resp.status_code == 404

    def test_summary(self):
        client = _client()
        client.post("/nomina-completa/process", json={
            "period": {"month": 7, "year": 2026},
            "employees": [_empleado()],
            "tenant_id": 2,
        })
        resp = client.get(
            "/nomina-completa/summary",
            params={"month": 7, "year": 2026, "tenant_id": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["employee_count"] == 1

    def test_taxes_individual(self):
        resp = _client().post("/nomina-completa/taxes", json={
            "salary": 25000,
            "benefits": 2000,
            "salary_per_day": 833.33,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "taxes" in data
        assert data["taxes"]["total"] > 0
