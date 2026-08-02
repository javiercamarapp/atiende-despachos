# -*- coding: utf-8 -*-
"""Tests del módulo de Cierre Mensual (monthly_close)."""
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.monthly_close.models import (
    ClosePeriodStatus,
    TaskCategory,
    TaskStatus,
)
from b2b_ai.features.monthly_close.routes import build_monthly_close_router
from b2b_ai.features.monthly_close.service import (
    MonthlyCloseService,
    _reset_state,
)
from b2b_ai.features.monthly_close.templates import (
    default_monthly_close_template,
)
from b2b_ai.features.roles.models import _reset_state as roles_reset


@pytest.fixture(autouse=True)
def _clean():
    _reset_state()
    roles_reset()
    yield
    _reset_state()
    roles_reset()


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


# ---------------------------------------------------------------------------
# Regresión QA 258 — P1 IDOR multi-tenant + P2 RBAC fino
# ---------------------------------------------------------------------------

def _auth_for(tenant_id: str, user_id: str = ""):
    """Dependencia de auth stub: dict con tenant (+ user opcional)."""
    ctx = {"key": "test-key", "tenant_id": tenant_id}
    if user_id:
        ctx["user_id"] = user_id
    return lambda: ctx


def _router_client(tenant_id: str, user_id: str = ""):
    """TestClient de monthly_close con auth del tenant indicado."""
    app = FastAPI()
    app.include_router(build_monthly_close_router(
        db=None, require_api_key=_auth_for(tenant_id, user_id)))
    return TestClient(app)


def _open_period(client, tenant_id: str, year=2024, month=6) -> str:
    """Abre un período y devuelve su period_id."""
    r = client.post("/api/v1/close-monthly/open",
                    json={"year": year, "month": month})
    assert r.status_code == 200, r.text
    return r.json()["period"]["id"]


class TestIDORPeriodTenantIsolation:
    """P1: un tenant no debe leer/completar/cerrar el período de otro."""

    def test_get_period_of_other_tenant_returns_404(self):
        c_a = _router_client("tenant_A")
        c_b = _router_client("tenant_B")
        period_id = _open_period(c_a, "tenant_A")

        # Dueño ve su período.
        assert c_a.get(f"/api/v1/close-monthly/{period_id}").status_code == 200
        # Otro tenant → 404 (no 403, para no filtrar existencia).
        assert c_b.get(f"/api/v1/close-monthly/{period_id}").status_code == 404

    def test_complete_task_of_other_tenant_returns_404(self):
        c_a = _router_client("tenant_A")
        c_b = _router_client("tenant_B")
        period_id = _open_period(c_a, "tenant_A")

        body = c_a.get(f"/api/v1/close-monthly/{period_id}").json()
        task_id = body["tasks"][0]["id"]

        r = c_b.post(f"/api/v1/close-monthly/{period_id}/tasks/{task_id}/complete",
                     json={"task_id": task_id, "user_id": "u_attacker"})
        assert r.status_code == 404

    def test_auto_check_of_other_tenant_returns_404(self):
        c_a = _router_client("tenant_A")
        c_b = _router_client("tenant_B")
        period_id = _open_period(c_a, "tenant_A")

        r = c_b.post(f"/api/v1/close-monthly/{period_id}/auto-check",
                     json={"module_state": {"cfdi_pending_count": 0}})
        assert r.status_code == 404

    def test_close_of_other_tenant_returns_404(self):
        c_a = _router_client("tenant_A")
        c_b = _router_client("tenant_B")
        period_id = _open_period(c_a, "tenant_A")

        r = c_b.post(f"/api/v1/close-monthly/{period_id}/close",
                     json={"user_id": "u_attacker"})
        assert r.status_code == 404

    def test_owner_still_can_complete_and_view(self):
        c_a = _router_client("tenant_A")
        period_id = _open_period(c_a, "tenant_A")
        body = c_a.get(f"/api/v1/close-monthly/{period_id}").json()
        task_id = body["tasks"][0]["id"]
        r = c_a.post(
            f"/api/v1/close-monthly/{period_id}/tasks/{task_id}/complete",
            json={"task_id": task_id, "user_id": "u_owner"})
        assert r.status_code == 200, r.text
        assert r.json()["task"]["status"] == "DONE"


class TestRBACClosePermissions:
    """P2: monthly_close exige CLOSE_VIEW / CLOSE_MANAGE (RBAC fino)."""

    def test_history_requires_close_view(self):
        from b2b_ai.features.roles.seed import seed_default_roles
        from b2b_ai.features.roles.service import RolesService

        svc = RolesService()
        seed_default_roles()
        # Usuario con rol contador (tiene CLOSE_VIEW pero NO CLOSE_MANAGE).
        contador = next(r for r in svc.list_roles() if r.name == "contador")
        svc.assign_role("user_contador", "tenant_A", contador.id)

        c = _router_client("tenant_A", user_id="user_contador")
        # CLOSE_VIEW permitido.
        r = c.get("/api/v1/close-monthly/history")
        assert r.status_code == 200, r.text

    def test_open_requires_close_manage(self):
        from b2b_ai.features.roles.seed import seed_default_roles
        from b2b_ai.features.roles.service import RolesService

        svc = RolesService()
        seed_default_roles()
        contador = next(r for r in svc.list_roles() if r.name == "contador")
        svc.assign_role("user_contador", "tenant_A", contador.id)

        c = _router_client("tenant_A", user_id="user_contador")
        r = c.post("/api/v1/close-monthly/open",
                   json={"year": 2024, "month": 6})
        # contador SÍ tiene CLOSE_MANAGE (seed actualizado) → 200.
        assert r.status_code == 200, r.text

    def test_user_without_close_permission_denied(self):
        from b2b_ai.features.roles.seed import seed_default_roles
        from b2b_ai.features.roles.service import RolesService

        svc = RolesService()
        seed_default_roles()
        readonly = next(r for r in svc.list_roles() if r.name == "readonly")
        svc.assign_role("user_readonly", "tenant_A", readonly.id)

        c = _router_client("tenant_A", user_id="user_readonly")
        # readonly no tiene CLOSE_MANAGE → 403 al abrir un período.
        r = c.post("/api/v1/close-monthly/open",
                   json={"year": 2024, "month": 6})
        assert r.status_code == 403
