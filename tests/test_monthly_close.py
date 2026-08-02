# -*- coding: utf-8 -*-
"""Tests del módulo de Cierre Mensual (monthly_close)."""
import pytest

from b2b_ai.features.monthly_close.models import (
    ClosePeriodStatus,
    TaskCategory,
    TaskStatus,
)
from b2b_ai.features.monthly_close.service import (
    MonthlyCloseService,
    _reset_state,
)
from b2b_ai.features.monthly_close.templates import (
    default_monthly_close_template,
)


@pytest.fixture(autouse=True)
def _clean():
    _reset_state()
    yield
    _reset_state()


class TestOpenPeriodCreatesTasks:
    def test_creates_period_and_tasks(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        assert period.year == 2024
        assert period.month == 6
        assert period.status == ClosePeriodStatus.OPEN
        tasks = svc.get_tasks(period.id)
        assert len(tasks) >= 15
        # El template por defecto tiene categorías variadas.
        cats = {t.category for t in tasks}
        assert TaskCategory.CFDI in cats
        assert TaskCategory.BANK in cats
        assert TaskCategory.NOMINA in cats

    def test_rejects_duplicate_open_period(self):
        svc = MonthlyCloseService()
        svc.open_period(year=2024, month=6, tenant_id="t1")
        with pytest.raises(ValueError):
            svc.open_period(year=2024, month=6, tenant_id="t1")

    def test_default_template_has_required_core_tasks(self):
        tpl = default_monthly_close_template()
        titles = [t.title for t in tpl.tasks]
        assert any("CFDI" in t for t in titles)
        assert any("conciliación" in t.lower() for t in titles)
        assert any("DIOT" in t for t in titles)
        assert any("gerenciales" in t.lower() for t in titles)


class TestCompleteTaskUnblocksDependents:
    def test_blocked_dependent_gets_unblocked(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        tasks = svc.get_tasks(period.id)
        # La 2ª tarea depende de la 1ª (cfdi_verificado -> cfdi_validacion).
        root = tasks[0]
        dependent = next(t for t in tasks if root.id in t.depends_on)
        assert dependent.status == TaskStatus.BLOCKED

        svc.complete_task(period.id, root.id, user_id="u1")
        dependent = next(t for t in svc.get_tasks(period.id)
                         if root.id in t.depends_on)
        assert root.status == TaskStatus.DONE
        assert dependent.status == TaskStatus.PENDING

    def test_cannot_complete_blocked_task(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        tasks = svc.get_tasks(period.id)
        dependent = next(t for t in tasks if t.depends_on)
        with pytest.raises(ValueError):
            svc.complete_task(period.id, dependent.id, user_id="u1")


class TestAutoCheckVerifiesCfdiCount:
    def test_cfdi_task_auto_completes_when_pending_zero(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        completed = svc.auto_check_tasks(
            period.id,
            module_state={
                "cfdi_pending_count": 0,
                "bank_feeds_sync_status": "ok",
                "nomina_status": "ok",
            },
        )
        titles = [t.title for t in completed]
        assert any("CFDI" in t for t in titles)

    def test_cfdi_not_auto_completed_when_pending_gt_zero(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        svc.auto_check_tasks(
            period.id, module_state={"cfdi_pending_count": 5})
        cfdi = next(t for t in svc.get_tasks(period.id)
                    if t.auto_check_query == "cfdi_pending_count")
        assert cfdi.status == TaskStatus.PENDING


class TestClosePeriodRejectsIfIncomplete:
    def test_close_rejects_with_pending_required_tasks(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        with pytest.raises(ValueError):
            svc.close_period(period.id, user_id="u1")

    def test_close_succeeds_when_all_done(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        # Auto-completa lo verificable y completa el resto en cascada.
        # Estrategia: repetir auto-check + completar manualmente las que
        # queden (sin dependencias pendientes).
        state = {
            "cfdi_pending_count": 0, "cfdi_validacion": True,
            "bank_feeds_sync_status": "ok", "nomina_status": "ok",
            "diot_generada": True, "declaraciones_revisadas": True,
            "contabilidad_electronica": True, "auxiliares_actualizados": True,
            "reportes_gerenciales": True,
        }
        # Ciclo: auto-check y completar manualmente hasta que todo sea DONE.
        for _ in range(20):
            svc.auto_check_tasks(period.id, module_state=state, user_id="u1")
            tasks = svc.get_tasks(period.id)
            progressed = False
            for t in tasks:
                if t.status == TaskStatus.PENDING:
                    try:
                        svc.complete_task(period.id, t.id, user_id="u1")
                        progressed = True
                    except ValueError:
                        continue
            if not progressed and all(
                    t.status in (TaskStatus.DONE, TaskStatus.SKIPPED)
                    for t in svc.get_tasks(period.id)):
                break

        period = svc.close_period(period.id, user_id="u1")
        assert period.status == ClosePeriodStatus.CLOSED
        assert period.closed_at is not None
        assert period.closed_by == "u1"


class TestPeriodStatusProgress:
    def test_progress_percentage(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        status0 = svc.get_period_status(period.id)
        assert status0["progress_percent"] == 0.0
        tasks = svc.get_tasks(period.id)
        svc.complete_task(period.id, tasks[0].id, user_id="u1")
        status1 = svc.get_period_status(period.id)
        assert status1["done"] == 1
        assert status1["progress_percent"] > 0

    def test_status_reports_blocked_and_overdue(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        status = svc.get_period_status(period.id)
        assert "blocked" in status
        assert "overdue" in status
        assert status["total_tasks"] >= 15


class TestOverdueTasksDetected:
    def test_overdue_tasks_detected(self):
        svc = MonthlyCloseService()
        # Abrir período y forzar una tarea con due_date en el pasado.
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        tasks = svc.get_tasks(period.id)
        target = next(t for t in tasks if t.depends_on)
        target.due_date = "2020-01-01"  # pasado
        status = svc.get_period_status(period.id)
        assert any(t["id"] == target.id for t in status["overdue"])
        # El período debe quedar marcado OVERDUE.
        assert status["period"]["status"] == ClosePeriodStatus.OVERDUE.value


class TestGenerateCloseReport:
    def test_report_shape(self):
        svc = MonthlyCloseService()
        period = svc.open_period(year=2024, month=6, tenant_id="t1")
        report = svc.generate_close_report(period.id)
        assert report["total_tasks"] >= 15
        assert "done_by_category" in report
        assert "issues" in report
        assert "estimated_hours" in report
