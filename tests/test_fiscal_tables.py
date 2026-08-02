# -*- coding: utf-8 -*-
"""Tests for b2b_ai.fiscal_tables — centralized ISR/IVA/UMA tables."""
import pytest


class TestISRTables2025:
    """Verify 2025 ISR tables match fiscal_tables.py values."""

    def test_monthly_table_has_10_brackets(self):
        from b2b_ai.fiscal_tables import ISR_MENSUAL_2025
        assert len(ISR_MENSUAL_2025) == 10

    def test_annual_table_has_10_brackets(self):
        from b2b_ai.fiscal_tables import ISR_ANUAL_2025
        assert len(ISR_ANUAL_2025) == 10

    def test_monthly_2025_first_bracket(self):
        """First bracket: 0-416.34, cuota_fija=0, tasa=1.92%."""
        from b2b_ai.fiscal_tables import ISR_MENSUAL_2025
        li, ls, cf, tasa = ISR_MENSUAL_2025[0]
        assert li == 0.00
        assert ls == 416.34
        assert cf == 0.00
        assert tasa == 0.0192

    def test_monthly_2025_last_bracket(self):
        """Last bracket: 91351.49+, cuota_fija=27285.41, tasa=35%."""
        from b2b_ai.fiscal_tables import ISR_MENSUAL_2025
        li, ls, cf, tasa = ISR_MENSUAL_2025[-1]
        assert li == 91351.49
        assert ls == float("inf")
        assert cf == 27285.41
        assert tasa == 0.3500

    def test_annual_2025_first_bracket(self):
        """First bracket: 0-4996.07, cuota_fija=0, tasa=1.92%."""
        from b2b_ai.fiscal_tables import ISR_ANUAL_2025
        li, ls, cf, tasa = ISR_ANUAL_2025[0]
        assert li == 0.00
        assert ls == 4996.07
        assert cf == 0.00
        assert tasa == 0.0192

    def test_quincenal_table_exists(self):
        from b2b_ai.fiscal_tables import ISR_QUINCENAL_2025
        assert len(ISR_QUINCENAL_2025) == 10

    def test_tables_are_2025_not_2024(self):
        """Verify we're using 2025 tables (416.34) not 2024 (312.41)."""
        from b2b_ai.fiscal_tables import ISR_MENSUAL_2025, ISR_MENSUAL_2024
        assert ISR_MENSUAL_2025[0][1] == 416.34  # 2025
        assert ISR_MENSUAL_2024[0][1] == 312.41  # 2024 (different)
        assert ISR_MENSUAL_2025[0][1] != ISR_MENSUAL_2024[0][1]


class TestSubsidioEmpleo:
    """Verify subsidio tables."""

    def test_subsidio_mensual_2025_exists(self):
        from b2b_ai.fiscal_tables import SUBSIDIO_EMPLEO_MENSUAL_2025
        assert len(SUBSIDIO_EMPLEO_MENSUAL_2025) == 11

    def test_subsidio_quincenal_2025_exists(self):
        from b2b_ai.fiscal_tables import SUBSIDIO_EMPLEO_QUINCENAL_2025
        assert len(SUBSIDIO_EMPLEO_QUINCENAL_2025) == 11

    def test_subsidio_first_range(self):
        """First range: 0.01-2169.53, subsidio=407.02."""
        from b2b_ai.fiscal_tables import SUBSIDIO_EMPLEO_MENSUAL_2025
        li, ls, sub = SUBSIDIO_EMPLEO_MENSUAL_2025[0]
        assert li == "0.01"
        assert ls == "2169.53"
        assert sub == "407.02"


class TestUMA:
    """Verify UMA 2025 values."""

    def test_uma_diario(self):
        from b2b_ai.fiscal_tables import UMA_DIARIO_2025
        assert UMA_DIARIO_2025 == "113.15"

    def test_uma_mensual(self):
        from b2b_ai.fiscal_tables import UMA_MENSUAL_2025
        assert UMA_MENSUAL_2025 == "3439.54"

    def test_uma_anual(self):
        from b2b_ai.fiscal_tables import UMA_ANUAL_2025
        assert UMA_ANUAL_2025 == "41274.48"


class TestGetISRTable:
    """Verify get_isr_table() function."""

    def test_get_monthly_2025(self):
        from b2b_ai.fiscal_tables import get_isr_table, ISR_MENSUAL_2025
        assert get_isr_table(2025, "monthly") is ISR_MENSUAL_2025

    def test_get_annual_2025(self):
        from b2b_ai.fiscal_tables import get_isr_table, ISR_ANUAL_2025
        assert get_isr_table(2025, "annual") is ISR_ANUAL_2025

    def test_get_quincenal_2025(self):
        from b2b_ai.fiscal_tables import get_isr_table, ISR_QUINCENAL_2025
        assert get_isr_table(2025, "quincenal") is ISR_QUINCENAL_2025

    def test_get_2024_legacy(self):
        from b2b_ai.fiscal_tables import get_isr_table, ISR_MENSUAL_2024
        assert get_isr_table(2024, "monthly") is ISR_MENSUAL_2024

    def test_invalid_year_raises(self):
        from b2b_ai.fiscal_tables import get_isr_table
        with pytest.raises(ValueError, match="No hay tabla"):
            get_isr_table(2020, "monthly")

    def test_invalid_period_raises(self):
        from b2b_ai.fiscal_tables import get_isr_table
        with pytest.raises(ValueError, match="No hay tabla"):
            get_isr_table(2025, "weekly")

    def test_default_year_is_2025(self):
        from b2b_ai.fiscal_tables import get_isr_table, FISCAL_YEAR, ISR_MENSUAL_2025
        assert FISCAL_YEAR == 2025
        assert get_isr_table() is ISR_MENSUAL_2025


class TestGetSubsidioTable:
    """Verify get_subsidio_table() function."""

    def test_get_monthly_subsidio(self):
        from b2b_ai.fiscal_tables import get_subsidio_table, SUBSIDIO_EMPLEO_MENSUAL_2025
        assert get_subsidio_table(2025, "monthly") is SUBSIDIO_EMPLEO_MENSUAL_2025

    def test_invalid_year_raises(self):
        from b2b_ai.fiscal_tables import get_subsidio_table
        with pytest.raises(ValueError):
            get_subsidio_table(2020, "monthly")
