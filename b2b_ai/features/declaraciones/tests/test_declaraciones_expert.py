# -*- coding: utf-8 -*-
"""test_declaraciones_expert.py — Expert-level tests for Declaraciones module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.declaraciones.service import DeclaracionesService, ISR_TABLE_MONTHLY, ISR_TABLE_ANNUAL
from b2b_ai.features.declaraciones.models import Declaracion, DeclaracionType, DeclaracionStatus, DeadlineStatus
from b2b_ai.features.declaraciones.validators import (
    validate_period_format, validate_period_consistency, validate_iva_data,
    validate_isr_data, validate_deadline_date, validate_rfc,
)
from b2b_ai.features.compliance import sanitize_string, mask_rfc, calculate_isr


class TestIdempotency:
    def test_service_init_idempotent(self):
        s1 = DeclaracionesService()
        s2 = DeclaracionesService()
        assert len(s1._declaraciones) == len(s2._declaraciones) == 0

    def test_isr_table_length(self):
        assert len(ISR_TABLE_MONTHLY) == 10
        assert len(ISR_TABLE_ANNUAL) == 10


class TestAuditTrail:
    def test_log_audit(self):
        svc = DeclaracionesService()
        entry = svc.log_audit(user="u1", action="generate", module="declaraciones", result="ok")
        assert entry.user == "u1"
        assert entry.result == "ok"


class TestInputSanitization:
    def test_validate_period_format_valid(self):
        ok, _ = validate_period_format("2024-01")
        assert ok

    def test_validate_period_format_invalid(self):
        ok, _ = validate_period_format("bad")
        assert not ok

    def test_validate_rfc_valid(self):
        ok, _ = validate_rfc("EMP850101AB1")
        assert ok

    def test_validate_rfc_invalid(self):
        ok, _ = validate_rfc("short")
        assert not ok


class TestErrorHandling:
    def test_generate_iva_invalid_period(self):
        svc = DeclaracionesService()
        with pytest.raises(ValueError):
            svc.generate_monthly_iva(13, 2024, "t1")

    def test_generate_isr_invalid_data(self):
        svc = DeclaracionesService()
        with pytest.raises(ValueError):
            svc.generate_provisional_isr(1, 2024, "t1", data={"ingresos": -100})

    def test_validate_iva_data_missing_fields(self):
        ok, errors = validate_iva_data({})
        assert not ok

    def test_validate_isr_data_missing_ingresos(self):
        ok, errors = validate_isr_data({})
        assert not ok

    def test_validate_iva_data_negative(self):
        ok, errors = validate_iva_data({"iva_cobrado": -100, "iva_pagado": 0})
        assert not ok


class TestTenantIsolation:
    def test_mask_rfc(self):
        assert "***" in mask_rfc("EMP850101AB1")


class TestEdgeCases:
    def test_isr_calculation_zero(self):
        assert calculate_isr(0) == 0.0

    def test_isr_calculation_negative(self):
        assert calculate_isr(-1000) == 0.0

    def test_isr_calculation_high_income(self):
        isr = calculate_isr(100000, annual=True)
        assert isr > 0

    def test_validate_deadline_date_iva(self):
        ok, _ = validate_deadline_date("2024-02-17", "iva", "2024-01")
        assert ok

    def test_validate_deadline_date_isr_anual(self):
        ok, _ = validate_deadline_date("2025-04-30", "isr_anual", "2024")
        assert ok

    def test_validate_period_consistency_iva_monthly(self):
        ok, _ = validate_period_consistency("iva", "2024-01")
        assert ok

    def test_validate_period_consistency_isr_anual_yearly(self):
        ok, _ = validate_period_consistency("isr_anual", "2024")
        assert ok


class TestConcurrentAccess:
    def test_concurrent_generate(self):
        svc = DeclaracionesService()
        results = []
        def run():
            results.append(svc.generate_monthly_iva(1, 2024, "t1"))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5


class TestDataValidation:
    def test_validate_isr_data_annual_needs_provisional(self):
        ok, errors = validate_isr_data({"ingresos": 100000, "pagos_provisionales": 0}, is_annual=True)
        assert not ok

    def test_validate_isr_data_deducciones_exceed_ingresos(self):
        ok, errors = validate_isr_data({"ingresos": 10000, "deducciones": 20000})
        assert not ok


class TestOutputVerification:
    def test_iva_declaration_structure(self):
        svc = DeclaracionesService()
        decl = svc.generate_monthly_iva(1, 2024, "t1", "EMP850101AB1", {"iva_cobrado": 5000, "iva_pagado": 3000})
        assert decl.tipo == DeclaracionType.IVA
        assert decl.status == DeclaracionStatus.DRAFT
        assert decl.rfc == "EMP850101AB1"

    def test_isr_declaration_structure(self):
        svc = DeclaracionesService()
        decl = svc.generate_provisional_isr(1, 2024, "t1", "EMP850101AB1", {"ingresos": 50000, "deducciones": 10000})
        assert decl.tipo == DeclaracionType.ISR_PROVISIONAL
        assert decl.data is not None

    def test_deadline_calculation(self):
        svc = DeclaracionesService()
        svc.generate_monthly_iva(1, 2024, "t1")
        deadlines = svc.calculate_deadlines("t1")
        assert len(deadlines) >= 1
