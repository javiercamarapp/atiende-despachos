# -*- coding: utf-8 -*-
"""test_close_management.py — Comprehensive tests for Close Management Agent.

Covers:
  1. Models (ChecklistStep, ClosePeriod, AdjustmentPolicy)
  2. Adjustment policies (13 types)
  3. ValidationEngine (5 validations)
  4. ERPWriter (post, batch, rollback)
  5. CloseManager (start, approve, run, finalize)
  6. API endpoints (start, status, approve-step, finalize)
  7. Scheduler (period calculation)
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.models import (
    AdjustmentPolicy,
    AdjustmentType,
    ChecklistStep,
    CloseApproveStepRequest,
    CloseFinalizeRequest,
    ClosePeriod,
    ClosePeriodStatus,
    CloseStartRequest,
    CloseStepStatus,
    ValidationResult,
    ValidationType,
)


class TestChecklistStep:
    """Test ChecklistStep lifecycle."""

    def test_default_status_is_pending(self):
        step = ChecklistStep(step=1, name="Test")
        assert step.status == CloseStepStatus.PENDING

    def test_mark_started(self):
        step = ChecklistStep(step=1, name="Test")
        step.mark_started()
        assert step.status == CloseStepStatus.IN_PROGRESS
        assert step.started_at is not None

    def test_mark_completed_automatic(self):
        step = ChecklistStep(step=1, name="Test", is_automatic=True)
        step.mark_completed({"key": "value"})
        assert step.status == CloseStepStatus.APPROVED
        assert step.detail == {"key": "value"}
        assert step.completed_at is not None

    def test_mark_completed_requires_approval(self):
        step = ChecklistStep(step=1, name="Test", requires_approval=True)
        step.mark_completed()
        assert step.status == CloseStepStatus.REVIEW

    def test_mark_failed(self):
        step = ChecklistStep(step=1, name="Test")
        step.mark_failed("error msg")
        assert step.status == CloseStepStatus.FAILED
        assert step.error == "error msg"

    def test_approve(self):
        step = ChecklistStep(step=1, name="Test", requires_approval=True)
        step.mark_completed()
        step.approve(by="contador", notes="Looks good")
        assert step.status == CloseStepStatus.APPROVED
        assert step.approved_by == "contador"
        assert step.approval_notes == "Looks good"

    def test_skip(self):
        step = ChecklistStep(step=1, name="Test")
        step.skip("N/A this month")
        assert step.status == CloseStepStatus.SKIPPED
        assert step.detail["skip_reason"] == "N/A this month"


class TestClosePeriod:
    """Test ClosePeriod aggregate."""

    def test_progress_empty(self):
        close = ClosePeriod(periodo="2026-07")
        assert close.progress_pct == 0.0
        assert close.total_steps == 0

    def test_progress_partial(self):
        steps = [
            ChecklistStep(step=1, name="A", status=CloseStepStatus.APPROVED),
            ChecklistStep(step=2, name="B", status=CloseStepStatus.PENDING),
            ChecklistStep(step=3, name="C", status=CloseStepStatus.CLOSED),
        ]
        close = ClosePeriod(periodo="2026-07", steps=steps)
        assert close.completed_steps == 2
        assert close.total_steps == 3
        assert abs(close.progress_pct - 66.7) < 0.1

    def test_update_summary(self):
        steps = [
            ChecklistStep(step=1, name="A", status=CloseStepStatus.APPROVED),
            ChecklistStep(step=2, name="B", status=CloseStepStatus.PENDING),
        ]
        close = ClosePeriod(periodo="2026-07", steps=steps)
        close.update_summary()
        assert close.summary["total_steps"] == 2
        assert close.summary["completed"] == 1
        assert close.summary["pending"] == 1

    def test_all_validations_passed_empty(self):
        close = ClosePeriod(periodo="2026-07")
        assert close.all_validations_passed is True

    def test_all_validations_passed_true(self):
        close = ClosePeriod(
            periodo="2026-07",
            validations=[
                ValidationResult(type=ValidationType.BALANCE_CUADRADA, passed=True),
            ],
        )
        assert close.all_validations_passed is True

    def test_all_validations_passed_false(self):
        close = ClosePeriod(
            periodo="2026-07",
            validations=[
                ValidationResult(type=ValidationType.BALANCE_CUADRADA, passed=True),
                ValidationResult(type=ValidationType.IVA_CONCILIADO, passed=False),
            ],
        )
        assert close.all_validations_passed is False


# ---------------------------------------------------------------------------
# Adjustment policy tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.adjustment_policies import (
    calculate_depreciacion,
    calculate_amortizacion,
    calculate_provision_aguinaldo,
    calculate_provision_vacaciones,
    calculate_provision_ptu,
    calculate_provision_isr,
    calculate_provision_imss,
    calculate_ajuste_inflacion,
    calculate_ajuste_prepagos,
    calculate_ajuste_inventarios,
    calculate_diferencias_cambiarias,
    calculate_provision_incobrables,
    calculate_valuacion_inversiones,
    _vacation_days_for_years,
)


class TestDepreciacion:
    def test_basic_depreciation(self):
        activos = [
            {"costo": 100_000, "tipo": "maquinaria", "cuenta_gasto": "612", "cuenta_activo": "150"},
        ]
        policy = calculate_depreciacion(activos, "2026-07")
        assert policy.type == AdjustmentType.DEPRECIACION
        assert policy.is_balanced
        assert policy.total_debe == round(100_000 * 0.10 / 12, 2)
        assert len(policy.entries) == 2

    def test_multiple_assets(self):
        activos = [
            {"costo": 100_000, "tipo": "maquinaria"},
            {"costo": 50_000, "tipo": "equipo_computo"},
        ]
        policy = calculate_depreciacion(activos, "2026-07")
        assert policy.is_balanced
        expected = round(100_000 * 0.10 / 12, 2) + round(50_000 * 0.30 / 12, 2)
        assert policy.total_debe == expected


class TestProvisionAguinaldo:
    def test_basic_aguinaldo(self):
        empleados = [{"salario_diario": 500.0}]
        policy = calculate_provision_aguinaldo(empleados, "2026-07")
        expected = round(500 * 15 / 12, 2)
        assert policy.total_debe == expected
        assert policy.is_balanced


class TestProvisionVacaciones:
    def test_vacation_days_lookup(self):
        assert _vacation_days_for_years(1) == 12
        assert _vacation_days_for_years(5) == 20
        assert _vacation_days_for_years(15) == 40

    def test_basic_vacation_provision(self):
        empleados = [{"salario_diario": 500.0, "antiguedad_anos": 1}]
        policy = calculate_provision_vacaciones(empleados, "2026-07")
        assert policy.is_balanced
        assert policy.total_debe > 0


class TestProvisionPTU:
    def test_ptu_with_utility(self):
        policy = calculate_provision_ptu(1_000_000, "2026-07")
        expected = round(1_000_000 * 0.10 / 12, 2)
        assert policy.total_debe == expected

    def test_ptu_no_utility(self):
        policy = calculate_provision_ptu(0, "2026-07")
        assert policy.total_debe == 0.0
        assert len(policy.entries) == 0

    def test_ptu_negative_utility(self):
        policy = calculate_provision_ptu(-500_000, "2026-07")
        assert policy.total_debe == 0.0


class TestProvisionISR:
    def test_isr_basic(self):
        policy = calculate_provision_isr(100_000, "2026-07")
        assert policy.total_debe == 30_000.0
        assert policy.is_balanced

    def test_isr_zero_utility(self):
        policy = calculate_provision_isr(0, "2026-07")
        assert policy.total_debe == 0.0


class TestDiferenciasCambiarias:
    def test_fx_gain(self):
        cuentas = [{"saldo_fx": 10_000, "tc_registro": 17.0, "cuenta": "110"}]
        policy = calculate_diferencias_cambiarias(cuentas, 17.50, "2026-07")
        assert policy.is_balanced
        assert policy.total_debe > 0

    def test_fx_loss(self):
        cuentas = [{"saldo_fx": 10_000, "tc_registro": 17.50, "cuenta": "110"}]
        policy = calculate_diferencias_cambiarias(cuentas, 17.00, "2026-07")
        assert policy.is_balanced
        assert policy.total_debe > 0

    def test_fx_no_change(self):
        cuentas = [{"saldo_fx": 10_000, "tc_registro": 17.0, "cuenta": "110"}]
        policy = calculate_diferencias_cambiarias(cuentas, 17.0, "2026-07")
        assert policy.total_debe == 0.0


class TestAjusteInflacion:
    def test_inflation_positive(self):
        policy = calculate_ajuste_inflacion(1_000_000, 0.04, "2026-07")
        assert policy.total_debe == 40_000.0
        assert policy.is_balanced

    def test_inflation_zero(self):
        policy = calculate_ajuste_inflacion(1_000_000, 0.0, "2026-07")
        assert policy.total_debe == 0.0


class TestProvisionIncobrables:
    def test_aging_buckets(self):
        cartera = [
            {"monto": 10_000, "dias_vencido": 100},  # 5%
            {"monto": 20_000, "dias_vencido": 200},  # 15%
        ]
        policy = calculate_provision_incobrables(cartera, "2026-07")
        expected = round(10_000 * 0.05, 2) + round(20_000 * 0.15, 2)
        assert policy.total_debe == expected
        assert policy.is_balanced


# ---------------------------------------------------------------------------
# ValidationEngine tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.validation_engine import ValidationEngine


class TestValidationEngine:
    def setup_method(self):
        self.engine = ValidationEngine()

    def test_balance_cuadrada_pass(self):
        r = self.engine.validate_balance_cuadrada(1000, 1000)
        assert r.passed is True

    def test_balance_cuadrada_fail(self):
        r = self.engine.validate_balance_cuadrada(1000, 1500)
        assert r.passed is False
        assert "NO cuadrada" in r.message

    def test_iva_conciliado_pass(self):
        r = self.engine.validate_iva_conciliado(
            iva_trasladado=10_000,
            iva_acreditable=6_000,
            iva_provisionado=4_000,
        )
        assert r.passed is True

    def test_isr_provisionado_pass(self):
        r = self.engine.validate_isr_provisionado(
            isr_provision=30_000,
            utilidad_fiscal=100_000,
        )
        assert r.passed is True

    def test_isr_no_utility(self):
        r = self.engine.validate_isr_provisionado(
            isr_provision=0,
            utilidad_fiscal=0,
        )
        assert r.passed is True

    def test_nomina_cuadrada_pass(self):
        r = self.engine.validate_nomina_cuadrada([
            {"sueldo_bruto": 10_000, "total_deducciones": 2_000, "sueldo_neto": 8_000},
        ])
        assert r.passed is True

    def test_nomina_cuadrada_fail(self):
        r = self.engine.validate_nomina_cuadrada([
            {"sueldo_bruto": 10_000, "total_deducciones": 2_000, "sueldo_neto": 9_000},
        ])
        assert r.passed is False

    def test_bancos_conciliados_pass(self):
        r = self.engine.validate_bancos_conciliados(match_rate=0.95)
        assert r.passed is True

    def test_bancos_conciliados_fail(self):
        r = self.engine.validate_bancos_conciliados(match_rate=0.50)
        assert r.passed is False

    def test_polizas_cuadradas_pass(self):
        r = self.engine.validate_polizas_cuadradas([
            {"id": "P1", "total_debe": 1000, "total_haber": 1000},
        ])
        assert r.passed is True

    def test_run_all(self):
        results = self.engine.run_all(
            balance_data={"total_debe": 1000, "total_haber": 1000},
            nominas=[{"sueldo_bruto": 1000, "total_deducciones": 200, "sueldo_neto": 800}],
        )
        assert len(results) == 2
        assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# ERPWriter tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.erp_writer import ERPWriter, ERPWriterError


class TestERPWriter:
    def test_post_adjustment(self):
        writer = ERPWriter()
        policy = calculate_provision_isr(100_000, "2026-07")
        result = writer.post_adjustment(policy)
        assert result["status"] == "simulated"
        assert result["reference"] is not None

    def test_post_unbalanced_raises(self):
        writer = ERPWriter()
        policy = AdjustmentPolicy(
            type=AdjustmentType.DEPRECIACION,
            periodo="2026-07",
            entries=[{"cuenta": "100", "debe": 100, "haber": 50, "concepto": "test"}],
            total_debe=100,
            total_haber=50,
            is_balanced=False,
        )
        with pytest.raises(ERPWriterError, match="unbalanced"):
            writer.post_adjustment(policy)

    def test_post_empty_entries_skips(self):
        writer = ERPWriter()
        policy = AdjustmentPolicy(
            type=AdjustmentType.PROVISION_PTU,
            periodo="2026-07",
            entries=[],
        )
        result = writer.post_adjustment(policy)
        assert result["status"] == "skipped"

    def test_post_batch(self):
        writer = ERPWriter()
        policies = [
            calculate_provision_isr(100_000, "2026-07"),
            calculate_provision_aguinaldo([{"salario_diario": 500}], "2026-07"),
        ]
        results = writer.post_batch(policies)
        assert len(results) == 2
        assert writer.posted_count == 2

    def test_erp_type_conpaqi(self):
        writer = ERPWriter(erp_type=__import__("b2b_ai.features.close_management.models", fromlist=["ERPType"]).ERPType.CONTPAQi)
        policy = calculate_provision_isr(100_000, "2026-07")
        payload = writer._map_to_erp_format(policy)
        assert "movimientos" in payload

    def test_erp_type_sap(self):
        from b2b_ai.features.close_management.models import ERPType
        writer = ERPWriter(erp_type=ERPType.SAP_B1)
        policy = calculate_provision_isr(100_000, "2026-07")
        payload = writer._map_to_erp_format(policy)
        assert "JournalEntryLines" in payload

    def test_erp_type_quickbooks(self):
        from b2b_ai.features.close_management.models import ERPType
        writer = ERPWriter(erp_type=ERPType.QUICKBOOKS)
        policy = calculate_provision_isr(100_000, "2026-07")
        payload = writer._map_to_erp_format(policy)
        assert "Line" in payload


# ---------------------------------------------------------------------------
# CloseManager tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.close_manager import CloseManager


class TestCloseManager:
    def test_start_close(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07", tenant_id=1)
        close = manager.start_close(req)
        assert close.id is not None
        assert close.status == ClosePeriodStatus.IN_PROGRESS
        assert close.total_steps == 17
        assert close.periodo == "2026-07"

    def test_get_close(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        assert manager.get_close(close.id) is not None
        assert manager.get_close("nonexistent") is None

    def test_approve_step(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        # Step 15 requires approval — mark it completed first (goes to REVIEW)
        step15 = next(s for s in close.steps if s.step == 15)
        step15.mark_completed()
        assert step15.status == CloseStepStatus.REVIEW
        # Now approve
        close = manager.approve_step(close.id, 15, approved=True, by="contador")
        step15 = next(s for s in close.steps if s.step == 15)
        assert step15.status == CloseStepStatus.APPROVED

    def test_run_automatic_steps(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        data = {
            "periodo": "2026-07",
            "total_cfdis": 100,
            "cfdis_procesados": 100,
            "activos": [{"costo": 100_000, "tipo": "maquinaria"}],
            "empleados": [{"salario_diario": 500}],
            "utilidad_fiscal": 500_000,
            "balance_data": {"total_debe": 1_000_000, "total_haber": 1_000_000},
        }
        close = manager.run_automatic_steps(close.id, data)
        assert close.progress_pct > 0
        assert len(close.validations) > 0

    def test_finalize_success(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        # Approve all steps
        for step in close.steps:
            if step.requires_approval:
                step.mark_completed()
                step.approve(by="test")
            else:
                step.mark_completed()
        close.update_summary()
        # Add passing validations
        close.validations = [
            ValidationResult(type=ValidationType.BALANCE_CUADRADA, passed=True),
        ]
        close = manager.finalize(close.id, closed_by="contador")
        assert close.status == ClosePeriodStatus.CLOSED
        assert close.closed_at is not None

    def test_finalize_fails_with_pending(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        with pytest.raises(ValueError, match="pending"):
            manager.finalize(close.id)

    def test_finalize_force(self):
        manager = CloseManager()
        req = CloseStartRequest(periodo="2026-07")
        close = manager.start_close(req)
        close = manager.finalize(close.id, force=True)
        assert close.status == ClosePeriodStatus.CLOSED

    def test_list_closes(self):
        manager = CloseManager()
        manager.start_close(CloseStartRequest(periodo="2026-06", tenant_id=1))
        manager.start_close(CloseStartRequest(periodo="2026-07", tenant_id=1))
        closes = manager.list_closes(tenant_id=1)
        assert len(closes) == 2

    def test_list_closes_filtered(self):
        manager = CloseManager()
        manager.start_close(CloseStartRequest(periodo="2026-06", tenant_id=1))
        manager.start_close(CloseStartRequest(periodo="2026-07", tenant_id=2))
        closes = manager.list_closes(tenant_id=1)
        assert len(closes) == 1


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------
from b2b_ai.features.close_management.scheduler import (
    get_close_period,
    get_cron_schedule,
)


class TestScheduler:
    def test_get_cron_schedule(self):
        sched = get_cron_schedule()
        assert sched["task"] == "close_management.monthly_close"
        assert sched["schedule"]["day_of_month"] == 1

    def test_get_close_period(self):
        period = get_close_period()
        # Should return a valid YYYY-MM string
        assert len(period) == 7
        assert period[4] == "-"
        year, month = period.split("-")
        assert int(year) >= 2024
        assert 1 <= int(month) <= 12


# ---------------------------------------------------------------------------
# API request/response model tests
# ---------------------------------------------------------------------------

class TestAPISchemas:
    def test_close_start_request(self):
        req = CloseStartRequest(periodo="2026-07")
        assert req.periodo == "2026-07"
        assert req.auto_approve is False

    def test_close_approve_step_request(self):
        req = CloseApproveStepRequest(close_id="abc", step=1, approved=True)
        assert req.approved_by == "contador"

    def test_close_finalize_request(self):
        req = CloseFinalizeRequest(close_id="abc")
        assert req.force is False
