# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/payroll.py — payroll calculations."""
import pytest
from decimal import Decimal
from b2b_ai.services.payroll import (
    calc_isr, calc_imss, calc_infonavit, calc_ptu,
    calc_aguinaldo, dias_vacaciones, calc_vacaciones,
    calc_prima_vacacional, calculate_payroll,
    TARIFA_ISR_2024_MENSUAL, RATES,
)


class TestCalcISR:
    def test_zero_income(self):
        r = calc_isr(0)
        assert r["impuesto"] == "0.00"
        assert r["rango_aplicado"] is None

    def test_first_bracket(self):
        r = calc_isr(500)
        assert float(r["impuesto"]) > 0
        # FIS-08: calc_isr uses the 2026 tariff by default (AÑO_FISCAL=2026)
        # 1st bracket: 0.00-435.08 (0%), 2nd bracket: 435.09-3666.30 (6.40%)
        # ingreso 500 falls in bracket 2 with limite_inferior=435.09
        assert r["rango_aplicado"]["limite_inferior"] == "435.09"

    def test_high_income(self):
        r = calc_isr(400000)
        imp = float(r["impuesto"])
        assert imp > 100000
        assert r["rango_aplicado"]["porcentaje_excedente"] == "0.35"

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
        # FIS-08: 2025 tariff — bracket 6 (8564.68-17128.42, cuota 952.82, 23.52%)
        # impuesto = 952.82 + (10000-8564.68)*0.2352 = 1290.33
        assert 1200 < imp < 1400


class TestCalcIMSS:
    def test_basic(self):
        r = calc_imss(10000)
        assert float(r["total"]) > 0
        assert float(r["eym"]) > 0
        assert float(r["rcva"]) > 0

    def test_zero_sbc(self):
        with pytest.raises(ValueError, match="SBC.*mayor a 0"):
            calc_imss(0)

    def test_references(self):
        r = calc_imss(5000)
        assert "LSS" in r["referencia"]

    def test_known_value_sbc_1000(self):
        """[36] Anchor to legal rate: SBC=1000, UMA=117.31 (2026).

        With 2026 IMSS worker rates (30 dias) and UMA diaria 117.31:
          EYM base:      0.0025 × 1000 × 30 =  75.00
          prest_din:     0.0075 × 1000 × 30 = 225.00
          prest_esp:     0.00375 × 1000 × 30 = 112.50
          excedente:     (1000 - 3×117.31) × 0.004 × 30 = 77.70
          Subtotal EYM = 490.20
          IV:            0.00625 × 1000 × 30 = 187.50
          RCVA:          0.01125 × 1000 × 30 = 337.50
          GMP:           0.00375 × 1000 × 30 = 112.50
          Total = 1127.70
        """
        r = calc_imss(1000)
        total = Decimal(r["total"])
        # FIS-10: With UMA 2026=117.31, the correct total is 1127.70
        # (rounding accumulated from daily components × 30 days)
        assert total == Decimal("1127.70"), (
            f"IMSS total for SBC=1000, 30d should be 1127.70, got {total}. "
            "Check RATES constants against LSS arts. 105-109."
        )


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
        assert "aguinaldo" in r["provisiones_patron"]
        assert "prima_vacacional" in r["provisiones_patron"]

    def test_negative_gravado_clamped(self):
        """If exento > sueldo, gravado should be 0."""
        emp = {"salario_diario": 500}
        r = calculate_payroll(emp, 1000, percepciones_exentas=5000)
        assert float(r["percepciones"]["total_gravado"]) == 0.0