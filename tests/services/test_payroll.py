# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/payroll.py — payroll calculations."""
import pytest
from decimal import Decimal
from b2b_ai.services.payroll import (
    calc_isr, calc_imss, calc_infonavit, calc_ptu,
    calc_aguinaldo, dias_vacaciones, calc_vacaciones,
    calc_prima_vacacional, calculate_payroll,
    TARIFA_ISR_2025_MENSUAL, RATES,
)


class TestCalcISR:
    def test_zero_income(self):
        r = calc_isr(0)
        assert r["impuesto"] == "0.00"
        assert r["rango_aplicado"] is None

    def test_first_bracket(self):
        r = calc_isr(500)
        assert float(r["impuesto"]) > 0
        assert r["rango_aplicado"]["limite_inferior"] == "0.01"

    def test_high_income(self):
        r = calc_isr(400000)
        imp = float(r["impuesto"])
        assert imp > 100000
        assert r["rango_aplicado"]["porcentaje_excedente"] == "0.3500"

    def test_negative_income(self):
        r = calc_isr(-100)
        assert r["impuesto"] == "0.00"

    def test_reference_always_present(self):
        r = calc_isr(10000)
        assert "LISR" in r["referencia"]

    def test_mid_bracket(self):
        r = calc_isr(10000)
        assert r["rango_aplicado"] is not None
        imp = float(r["impuesto"])
        assert 500 < imp < 1500


class TestCalcIMSS:
    def test_basic(self):
        r = calc_imss(10000)
        assert float(r["total"]) > 0
        assert float(r["eym"]) > 0
        assert float(r["rcva"]) > 0

    def test_zero_sbc(self):
        r = calc_imss(0)
        assert r["total"] == "0.00"

    def test_references(self):
        r = calc_imss(5000)
        assert "LSS" in r["referencia"]


class TestCalcINFONAVIT:
    def test_basic(self):
        r = calc_infonavit(10000)
        assert r["cuota"] == "500.00"

    def test_custom_tasa(self):
        r = calc_infonavit(10000, tasa=Decimal("0.03"))
        assert r["cuota"] == "300.00"

    def test_zero(self):
        r = calc_infonavit(0)
        assert r["cuota"] == "0.00"


class TestCalcPTU:
    def test_basic(self):
        r = calc_ptu(100000)
        assert r["ptu"] == "10000.00"

    def test_custom_tasa(self):
        r = calc_ptu(100000, tasa=Decimal("0.05"))
        assert r["ptu"] == "5000.00"

    def test_reference(self):
        r = calc_ptu(50000)
        assert "PTU" in r["referencia"]


class TestCalcAguinaldo:
    def test_full_year(self):
        r = calc_aguinaldo(500)
        assert r["aguinaldo"] == "7500.00"
        assert r["proporcional"] is False
        assert r["dias"] == 15

    def test_proportional(self):
        r = calc_aguinaldo(500, dias_trabajados=180)
        assert r["proporcional"] is True
        val = float(r["aguinaldo"])
        assert 3000 < val < 4000

    def test_custom_dias_ley(self):
        r = calc_aguinaldo(500, dias_ley=20)
        assert r["aguinaldo"] == "10000.00"


class TestDiasVacaciones:
    def test_first_year(self):
        assert dias_vacaciones(1) == 12

    def test_year_4(self):
        assert dias_vacaciones(4) == 18

    def test_year_5(self):
        assert dias_vacaciones(5) == 20

    def test_year_10(self):
        assert dias_vacaciones(10) == 22

    def test_year_0(self):
        assert dias_vacaciones(0) == 12


class TestCalcVacaciones:
    def test_basic(self):
        r = calc_vacaciones(500, 1)
        assert r["dias"] == 12
        assert r["pago"] == "6000.00"

    def test_year_5(self):
        r = calc_vacaciones(1000, 5)
        assert r["dias"] == 20
        assert r["pago"] == "20000.00"


class TestCalcPrimaVacacional:
    def test_basic(self):
        r = calc_prima_vacacional(500, 1)
        assert float(r["prima"]) > 0
        assert r["tasa"] == "0.2500"

    def test_custom_tasa(self):
        r = calc_prima_vacacional(500, 1, tasa=Decimal("0.30"))
        assert float(r["tasa"]) == 0.30


class TestCalculatePayroll:
    def test_basic_payroll(self):
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 15000)
        assert float(r["neto_a_pagar"]) > 0
        assert float(r["total_deducciones"]) >= 0
        assert r["requires_human_review"] is True

    def test_with_exento(self):
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 15000, percepciones_exentas=3000)
        assert float(r["percepciones"]["percepciones_exentas"]) == 3000.0

    def test_with_bono(self):
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 15000, bono=5000)
        assert float(r["percepciones"]["bono"]) == 5000.0

    def test_sbc_derived(self):
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 15000)
        sbc = float(r["sbc"])
        assert sbc > 500

    def test_provisions_included(self):
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 15000)
        assert "aguinaldo" in r["provisiones"]
        assert "prima_vacacional" in r["provisiones"]

    def test_negative_gravado_clamped(self):
        """If exento > sueldo, gravado should be 0."""
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 1000, percepciones_exentas=5000)
        assert float(r["percepciones"]["total_gravado"]) == 0.0
