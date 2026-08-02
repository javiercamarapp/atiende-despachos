# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del Cierre Mensual (monthly_close).

MonthlyCloseService:
  - open_period          : abre un período + genera tareas desde plantilla
  - get_period_status    : progreso %, tareas bloqueadas y vencidas
  - complete_task        : marca DONE y desbloquea dependientes
  - auto_check_tasks     : auto-completa tareas verificadas contra otros módulos
  - close_period         : valida tareas requeridas y cierra el período
  - generate_close_report: resumen de lo hecho, issues y tiempo
  - list_history         : histórico de períodos del tenant
  - get_period / get_task : lecturas por id

Almacenamiento: en memoria (dict) con `_reset_state()` para tests, coherente
con el patrón de bank_feeds / vencimientos. La firma permite inyectar una capa
de persistencia (db) sin romper la interfaz.

Las `auto_check_query` son nombres simbólicos; `auto_check_tasks()` recibe un
dict `module_state` con las señales de otros módulos (cfdi_pending_count,
bank_feeds_sync_status, nomina_status, diot_generada, ...) y marca DONE las
tareas cuya verificación pasa.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.monthly_close.models import (
    ClosePeriod,
    ClosePeriodStatus,
    CloseTask,
    CloseTemplate,
    TaskStatus,
)
from b2b_ai.features.monthly_close.templates import get_template

# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / vencimientos)
# ---------------------------------------------------------------------------
_periods: Dict[str, ClosePeriod] = {}
_tasks: Dict[str, CloseTask] = {}
# period_id -> task_ids (índice de pertenencia)
_period_tasks: Dict[str, List[str]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _periods.clear()
    _tasks.clear()
    _period_tasks.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class MonthlyCloseService:
    """Servicio de orquestación del cierre mensual."""

    def __init__(self, db: Any = None):
        self.db = db

    # ------------------------------------------------------------------
    # Apertura de período
    # ------------------------------------------------------------------
    def open_period(
        self,
        year: int,
        month: int,
        tenant_id: str = "",
        template_name: Optional[str] = None,
        template: Optional[CloseTemplate] = None,
    ) -> ClosePeriod:
        """Abre un período de cierre y genera sus tareas desde la plantilla."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        # Evita duplicar un período ya abierto para el mismo mes/año.
        for p in _periods.values():
            if (p.tenant_id == tenant_id and p.year == year and p.month == month
                    and p.status == ClosePeriodStatus.OPEN):
                raise ValueError(
                    f"Ya existe un período abierto para {year:04d}-{month:02d}"
                )

        tpl = template or get_template(template_name)
        period = ClosePeriod(
            tenant_id=tenant_id,
            year=year,
            month=month,
            status=ClosePeriodStatus.OPEN,
            opened_at=_utcnow(),
        )
        _periods[period.id] = period

        # key -> task id (resuelve depends_on de la plantilla)
        key_to_id: Dict[str, str] = {}
        tasks: List[CloseTask] = []
        for idx, tt in enumerate(tpl.tasks):
            tid = str(_uuid.uuid4())
            if tt.key:
                key_to_id[tt.key] = tid
            due = None
            if tt.due_offset_days:
                due = (date(year, month, 1) + timedelta(days=tt.due_offset_days)
                       ).isoformat()
            tasks.append(CloseTask(
                id=tid,
                period_id=period.id,
                title=tt.title,
                description=tt.description,
                category=tt.category,
                status=TaskStatus.PENDING,
                depends_on=[],
                due_date=due,
                auto_check_query=tt.auto_check_query,
                required=tt.required,
            ))

        # Resolver depends_on de la plantilla a IDs concretos y setear BLOCKED
        for tt, task in zip(tpl.tasks, tasks):
            deps = [key_to_id[k] for k in tt.depends_on if k in key_to_id]
            task.depends_on = deps
            if deps:
                task.status = TaskStatus.BLOCKED
            _tasks[task.id] = task
            _period_tasks.setdefault(period.id, []).append(task.id)

        return period

    # ------------------------------------------------------------------
    # Lectura de período
    # ------------------------------------------------------------------
    def get_period(self, period_id: str) -> ClosePeriod:
        period = _periods.get(period_id)
        if period is None:
            raise KeyError(f"Período no encontrado: {period_id}")
        return period

    def get_tasks(self, period_id: str) -> List[CloseTask]:
        self.get_period(period_id)
        ids = _period_tasks.get(period_id, [])
        return [_tasks[i] for i in ids if i in _tasks]

    def get_task(self, period_id: str, task_id: str) -> CloseTask:
        task = _tasks.get(task_id)
        if task is None or task.period_id != period_id:
            raise KeyError(f"Tarea no encontrada: {task_id}")
        return task

    def list_history(self, tenant_id: str = "") -> List[ClosePeriod]:
        periods = list(_periods.values())
        if tenant_id:
            periods = [p for p in periods if p.tenant_id == tenant_id]
        return sorted(periods, key=lambda p: (p.year, p.month), reverse=True)

    # ------------------------------------------------------------------
    # Estado del período
    # ------------------------------------------------------------------
    def _recompute_overdue(self, period: ClosePeriod, tasks: List[CloseTask]) -> None:
        """Marca el período OVERDUE si hay tareas requeridas vencidas."""
        today = date.today().isoformat()
        overdue_pending = False
        for t in tasks:
            if t.required and t.due_date and t.due_date < today and \
                    t.status in (TaskStatus.PENDING, TaskStatus.BLOCKED,
                                 TaskStatus.IN_PROGRESS):
                overdue_pending = True
                break
        if period.status == ClosePeriodStatus.OPEN and overdue_pending:
            period.status = ClosePeriodStatus.OVERDUE

    def get_period_status(self, period_id: str) -> Dict:
        """Progreso %, tareas bloqueadas y vencidas del período."""
        period = self.get_period(period_id)
        tasks = self.get_tasks(period_id)

        total = len(tasks)
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        skipped = sum(1 for t in tasks if t.status == TaskStatus.SKIPPED)
        blocked = [t.to_dict() for t in tasks if t.status == TaskStatus.BLOCKED]
        today = date.today().isoformat()
        overdue = [
            t.to_dict() for t in tasks
            if t.due_date and t.due_date < today and t.status in (
                TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS)
        ]

        progress = 0
        if total:
            progress = round((done + skipped) / total * 100, 1)

        self._recompute_overdue(period, tasks)

        return {
            "period": period.to_dict(),
            "total_tasks": total,
            "done": done,
            "skipped": skipped,
            "pending": sum(1 for t in tasks if t.status == TaskStatus.PENDING),
            "in_progress": sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS),
            "progress_percent": progress,
            "blocked": blocked,
            "overdue": overdue,
            "tasks": [t.to_dict() for t in tasks],
        }

    # ------------------------------------------------------------------
    # Completar tarea
    # ------------------------------------------------------------------
    def complete_task(self, period_id: str, task_id: str, user_id: str = "") -> CloseTask:
        """Marca una tarea DONE y desbloquea sus dependientes."""
        task = self.get_task(period_id, task_id)
        if task.status in (TaskStatus.DONE, TaskStatus.SKIPPED):
            raise ValueError(f"Tarea ya terminada: {task_id}")

        # Bloqueo por dependencias sin resolver.
        for dep_id in task.depends_on:
            dep = _tasks.get(dep_id)
            if dep and dep.status != TaskStatus.DONE:
                raise ValueError(
                    f"Tarea bloqueada: depende de '{dep.title}' sin completar"
                )

        task.status = TaskStatus.DONE
        task.completed_at = _utcnow()
        task.completed_by = user_id or None

        # Desbloquea dependientes cuyas dependencias ya estén todas DONE.
        for t in self.get_tasks(period_id):
            if t.status == TaskStatus.BLOCKED:
                deps_done = all(
                    (_tasks.get(d) is not None and _tasks[d].status == TaskStatus.DONE)
                    for d in t.depends_on
                ) if t.depends_on else True
                if deps_done:
                    t.status = TaskStatus.PENDING

        return task

    # ------------------------------------------------------------------
    # Auto-check
    # ------------------------------------------------------------------
    _AUTO_CHECK_PASS = {
        # señales en las que 0 / vacío / sync ok = verificación pasa
        "cfdi_pending_count": lambda v: int(v or 0) == 0,
        "cfdi_validacion": lambda v: bool(v) is True,
        "bank_feeds_sync_status": lambda v: str(v).lower() in ("ok", "synced", "completed"),
        "nomina_status": lambda v: str(v).lower() in ("ok", "timbrada", "completed"),
        "diot_generada": lambda v: bool(v) is True,
        "declaraciones_revisadas": lambda v: bool(v) is True,
        "contabilidad_electronica": lambda v: bool(v) is True,
        "auxiliares_actualizados": lambda v: bool(v) is True,
        "reportes_gerenciales": lambda v: bool(v) is True,
    }

    def auto_check_tasks(
        self,
        period_id: str,
        module_state: Optional[Dict[str, Any]] = None,
        user_id: str = "system",
    ) -> List[CloseTask]:
        """Auto-completa las tareas cuya verificación pasa contra module_state.

        `module_state` debe contener señales clave-valor (ej.
        {"cfdi_pending_count": 0, "bank_feeds_sync_status": "ok"}). Para cada
        tarea con `auto_check_query`, si la señal correspondiente satisface el
        check (y sus dependencias están DONE), se marca DONE automáticamente.
        """
        state = module_state or {}
        period = self.get_period(period_id)
        completed: List[CloseTask] = []

        # Primero verificamos dependencias; auto-check solo para tareas cuyo
        # auto_check_query exista en el estado.
        for t in self.get_tasks(period_id):
            if t.status in (TaskStatus.DONE, TaskStatus.SKIPPED):
                continue
            if not t.auto_check_query:
                continue
            # Solo auto-completa si las dependencias ya están DONE.
            deps_done = all(
                (_tasks.get(d) is not None and _tasks[d].status == TaskStatus.DONE)
                for d in t.depends_on
            ) if t.depends_on else True
            if not deps_done:
                continue
            check = self._AUTO_CHECK_PASS.get(t.auto_check_query)
            if check is None:
                continue
            value = state.get(t.auto_check_query)
            try:
                if check(value):
                    t.status = TaskStatus.DONE
                    t.completed_at = _utcnow()
                    t.completed_by = user_id
                    completed.append(t)
                    # desbloquear dependientes
                    for dep in self.get_tasks(period_id):
                        if dep.status == TaskStatus.BLOCKED:
                            d_all = all(
                                (_tasks.get(d) is not None
                                 and _tasks[d].status == TaskStatus.DONE)
                                for d in dep.depends_on
                            ) if dep.depends_on else True
                            if d_all:
                                dep.status = TaskStatus.PENDING
            except Exception:
                continue

        self._recompute_overdue(period, self.get_tasks(period_id))
        return completed

    # ------------------------------------------------------------------
    # Cierre de período
    # ------------------------------------------------------------------
    def close_period(self, period_id: str, user_id: str = "") -> ClosePeriod:
        """Valida todas las tareas requeridas y cierra el período."""
        period = self.get_period(period_id)
        tasks = self.get_tasks(period_id)

        missing = [
            t.to_dict() for t in tasks
            if t.required and t.status not in (TaskStatus.DONE, TaskStatus.SKIPPED)
        ]
        if missing:
            raise ValueError(
                f"No se puede cerrar: {len(missing)} tarea(s) requerida(s) "
                f"sin completar. Ej: '{missing[0]['title']}'"
            )

        period.status = ClosePeriodStatus.CLOSED
        period.closed_at = _utcnow()
        period.closed_by = user_id or None
        return period

    # ------------------------------------------------------------------
    # Reporte de cierre
    # ------------------------------------------------------------------
    def generate_close_report(self, period_id: str) -> Dict:
        """Resumen de lo hecho, issues y tiempo de ejecución."""
        period = self.get_period(period_id)
        tasks = self.get_tasks(period_id)

        done = [t for t in tasks if t.status == TaskStatus.DONE]
        skipped = [t for t in tasks if t.status == TaskStatus.SKIPPED]
        pending = [t for t in tasks if t.status in (
            TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS)]

        total_duration_hours = 0.0
        for t in done:
            if t.completed_at and t.period_id:
                # Estimación: usamos opened_at del período como inicio base.
                opened = period.opened_at
                total_duration_hours += max(
                    0.0, (t.completed_at - opened).total_seconds() / 3600)

        issues = []
        for t in pending:
            if t.due_date and t.due_date < date.today().isoformat():
                issues.append({
                    "task_id": t.id,
                    "title": t.title,
                    "reason": "vencida",
                })

        by_category: Dict[str, int] = {}
        for t in done:
            by_category[t.category.value] = by_category.get(t.category.value, 0) + 1

        return {
            "period": period.to_dict(),
            "total_tasks": len(tasks),
            "done": len(done),
            "skipped": len(skipped),
            "pending": len(pending),
            "progress_percent": round((len(done) + len(skipped)) / len(tasks) * 100, 1)
            if tasks else 0,
            "done_by_category": by_category,
            "issues": issues,
            "estimated_hours": round(total_duration_hours, 2),
            "closed": period.status == ClosePeriodStatus.CLOSED,
        }
