# -*- coding: utf-8 -*-
"""
internal_scheduler.py — Scheduler interno (asyncio) que corre DENTRO del
mismo proceso uvicorn, enganchado al lifespan de FastAPI
(`b2b_ai/api/app.py`).

Por qué existe este módulo
--------------------------
Antes de esto, NADA disparaba el pipeline de declaraciones/CONTPAQi de forma
automática: `SATScheduler.run_daily`/`run_weekly` (`b2b_ai/sat/api.py`) y el
registro de CFDIs en ERP vía `EndToEndOrchestrator.upload_cfdis`
(`b2b_ai/features/pipeline/routes.py`) solo se ejecutaban si un humano (o un
cron externo) llamaba el endpoint HTTP correspondiente. No había
APScheduler/Celery en las dependencias del repo (ver `pyproject.toml`), así
que en vez de añadir una dependencia nueva para un caso de uso que un loop
`asyncio` cubre perfectamente, `InternalScheduler.run_forever()` es ese loop:
se lanza como `asyncio.Task` en el `lifespan` de `create_app()` y se cancela
limpiamente en el shutdown.

Qué hace cada tick (`InternalScheduler.tick()`, síncrono y sin sleep — lo
que corre `run_forever()` periódicamente vía `asyncio.to_thread`):

  1. Por cada tenant no bloqueado (`db.list_tenants()`):
       a. Genera (idempotente) el calendario anual de obligaciones en
          `compliance_tracker` y consulta `get_overdue`/`get_upcoming`. Si
          hay obligaciones vencidas o por vencer, dispara
          `SATScheduler(tenant).process()` — el mismo método que ya existía
          pensado para cron (decide internamente si toca correr
          `run_daily`/`run_weekly` según cuándo corrieron por última vez;
          ver `b2b_ai/sat/scheduler.py`). Si el tenant no tiene RFC
          configurado, o no hay obligaciones pendientes, NO se dispara nada
          y queda registrado el motivo.
       b. Revisa un inbox de CFDIs pendientes de registrar en CONTPAQi
          (`B2B_CFDI_INBOX_DIR/<tenant_id>/*.xml`, ver `_pending_cfdi_files`)
          y, SOLO si los flags de escritura real ya lo permiten
          (`_real_erp_write_allowed`, que reutiliza — no reinventa — los
          gates existentes en `b2b_ai.computer_use.security` y
          `b2b_ai.features.declaraciones.sat_rpa_bridge`), los registra por
          el MISMO camino que usa hoy `/api/v1/pipeline/run`:
          `EndToEndOrchestrator().upload_cfdis(..., auto_register_erp=True)`.
          Los archivos que se registraron con éxito se archivan a
          `.../<tenant_id>/procesados/` (nunca se borran) para no
          reprocesarlos en el siguiente tick.

Alcance honesto: si los flags de escritura real (`B2B_COMPUTER_USE_MODE`,
`B2B_COMPUTER_USE_ALLOW_WRITES`, `B2B_SAT_SUBMIT_MODE`) están en su default
seguro (`disabled`/`False`/`stub`), el scheduler NUNCA intenta el registro
real en CONTPAQi aunque haya archivos pendientes: lo deja constancia en el
log y en el resultado del tick (`attempted: False` + motivo), nunca finge
que se registró. `B2B_SCHEDULER_ENABLED=false` apaga todo el scheduler (el
default es `true`, pero es inofensivo porque los flags de escritura real
siguen en su default seguro).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from b2b_ai.db.db import Database
from b2b_ai.features.compliance_tracker.service import ComplianceService
from b2b_ai.features.pipeline.orchestrator import (
    EndToEndOrchestrator,
    EndToEndPipelineError,
)
from b2b_ai.sat.scheduler import SATScheduler

log = logging.getLogger("b2b_ai.scheduler.internal")

DEFAULT_INTERVAL_SECONDS = 3600.0
DEFAULT_UPCOMING_DAYS = 7
DEFAULT_CFDI_INBOX_DIR = "data/cfdi_pendientes"


# --------------------------------------------------------------------------#
# Flags de entorno
# --------------------------------------------------------------------------#
def scheduler_enabled_from_env() -> bool:
    """B2B_SCHEDULER_ENABLED — flag maestro del scheduler. Default: true.

    Inofensivo en su default: aunque el scheduler corra, el registro real en
    CONTPAQi sigue exigiendo que los flags de escritura (que SÍ tienen
    default seguro) se activen explícitamente — ver `_real_erp_write_allowed`.
    """
    raw = os.environ.get("B2B_SCHEDULER_ENABLED", "true").strip().lower()
    return raw in ("true", "1", "yes")


def _interval_seconds_from_env() -> float:
    raw = os.environ.get("B2B_SCHEDULER_INTERVAL_SECONDS", "")
    try:
        return float(raw) if raw.strip() else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        log.warning("B2B_SCHEDULER_INTERVAL_SECONDS=%r inválido; usando default %ss",
                    raw, DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


def _cfdi_inbox_dir_from_env() -> str:
    return os.environ.get("B2B_CFDI_INBOX_DIR", DEFAULT_CFDI_INBOX_DIR)


def _real_erp_write_allowed() -> Tuple[bool, str]:
    """True solo si TODOS los gates de escritura real ya existentes lo permiten.

    No define un gate nuevo y paralelo: reutiliza `rpa_execution_allowed()`
    (`B2B_COMPUTER_USE_MODE=playwright` + `B2B_COMPUTER_USE_ALLOW_WRITES=true`,
    ya definido en `sat_rpa_bridge.py` para el envío RPA de declaraciones) y
    además exige `B2B_SAT_SUBMIT_MODE=rpa` — el mismo flag que gatea el resto
    de la automatización real de portales/escritorio en este repo. Import
    perezoso (no en el nivel de módulo) para no acoplar la carga de este
    scheduler a la disponibilidad de Playwright/el driver RPA cuando el
    scheduler corre en modo puramente mock (caso por defecto).
    """
    from b2b_ai.features.declaraciones.sat_rpa_bridge import (
        get_sat_submit_mode,
        rpa_execution_allowed,
    )
    allowed, reason = rpa_execution_allowed()
    if not allowed:
        return False, reason
    mode = get_sat_submit_mode()
    if mode != "rpa":
        return False, (
            f"B2B_SAT_SUBMIT_MODE='{mode}' (se requiere 'rpa', junto con "
            "B2B_COMPUTER_USE_MODE=playwright y B2B_COMPUTER_USE_ALLOW_WRITES=true, "
            "para registrar CFDIs reales en CONTPAQi de forma automática)."
        )
    return True, "ok"


# --------------------------------------------------------------------------#
# Scheduler
# --------------------------------------------------------------------------#
class InternalScheduler:
    """Scheduler interno: un tick síncrono (`tick()`) + un loop asyncio
    (`run_forever()`) que lo repite cada `interval_seconds`.

    Todas las dependencias son inyectables para poder testear sin red, sin
    reloj real y sin depender de qué flags tenga puesto el entorno de CI.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        *,
        interval_seconds: Optional[float] = None,
        upcoming_days: int = DEFAULT_UPCOMING_DAYS,
        cfdi_inbox_dir: Optional[str] = None,
        orchestrator: Optional[EndToEndOrchestrator] = None,
        compliance_service_factory: Optional[Callable[[], ComplianceService]] = None,
        sat_scheduler_factory: Optional[
            Callable[[Any, str, str], SATScheduler]
        ] = None,
        real_erp_write_allowed_fn: Optional[Callable[[], Tuple[bool, str]]] = None,
        sleep_fn: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self.db = db if db is not None else Database()
        self.interval_seconds = (
            interval_seconds if interval_seconds is not None
            else _interval_seconds_from_env()
        )
        self.upcoming_days = upcoming_days
        self.cfdi_inbox_dir = Path(cfdi_inbox_dir or _cfdi_inbox_dir_from_env())
        self._orchestrator = orchestrator or EndToEndOrchestrator()
        self._compliance_service_factory = (
            compliance_service_factory or ComplianceService
        )
        self._sat_scheduler_factory = (
            sat_scheduler_factory or self._default_sat_scheduler_factory
        )
        self._real_erp_write_allowed_fn = (
            real_erp_write_allowed_fn or _real_erp_write_allowed
        )
        self._sleep_fn = sleep_fn or asyncio.sleep

    # ------------------------------------------------------------------ #
    # Factories por defecto
    # ------------------------------------------------------------------ #
    def _default_sat_scheduler_factory(
        self, tenant_id: Any, rfc: str, ciec: str
    ) -> SATScheduler:
        return SATScheduler(db=self.db, tenant_id=tenant_id, rfc=rfc, ciec=ciec)

    # ------------------------------------------------------------------ #
    # Un tick (síncrono, sin sleep — apto para tests directos)
    # ------------------------------------------------------------------ #
    def tick(self) -> Dict[str, Any]:
        """Ejecuta una pasada completa sobre todos los tenants no bloqueados.

        Nunca lanza: cada tenant se procesa de forma aislada (un tenant que
        falla no detiene a los demás) y cualquier error queda en el
        resultado + el log, nunca silencioso.
        """
        try:
            tenants = self.db.list_tenants()
        except Exception:
            log.exception("No se pudo listar tenants; scheduler_tick abortado")
            return {"tenants_checked": 0, "sat": [], "cfdi_erp": [], "error": "list_tenants_failed"}

        active = [t for t in tenants if not t.get("blocked")]
        sat_results: List[Dict[str, Any]] = []
        cfdi_results: List[Dict[str, Any]] = []
        for tenant in active:
            tenant_id = tenant["id"]
            try:
                sat_results.append(self._check_and_run_sat(tenant))
            except Exception as exc:  # noqa: BLE001 — un tenant no debe tumbar el tick
                log.exception("SAT scheduler check falló para tenant %s", tenant_id)
                sat_results.append({"tenant_id": tenant_id, "triggered": False,
                                    "error": str(exc)})
            try:
                cfdi_results.append(self._check_and_register_cfdis(tenant_id))
            except Exception as exc:  # noqa: BLE001
                log.exception("Registro de CFDIs pendientes falló para tenant %s", tenant_id)
                cfdi_results.append({"tenant_id": tenant_id, "attempted": False,
                                     "error": str(exc)})

        summary = {
            "tenants_checked": len(active),
            "sat": sat_results,
            "cfdi_erp": cfdi_results,
        }
        log.info("scheduler_tick tenants_checked=%d sat_triggered=%d cfdi_attempted=%d",
                 len(active),
                 sum(1 for r in sat_results if r.get("triggered")),
                 sum(1 for r in cfdi_results if r.get("attempted")))
        return summary

    # ------------------------------------------------------------------ #
    # 1) compliance_tracker → SATScheduler.process() (run_daily/run_weekly)
    # ------------------------------------------------------------------ #
    def _check_and_run_sat(self, tenant: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = tenant["id"]
        tid_str = str(tenant_id)
        service = self._compliance_service_factory()

        # Idempotente: crea las obligaciones del año si aún no existían para
        # este tenant, sin duplicar las que ya hay (ver ComplianceService.
        # generate_calendar). Si falla, seguimos con lo que ya hubiera en
        # memoria en vez de abortar el tenant completo.
        try:
            service.generate_calendar(tid_str, date.today().year)
        except Exception:
            log.exception("No se pudo generar el calendario de obligaciones (tenant %s)",
                          tid_str)

        overdue = service.get_overdue(tid_str)
        upcoming = service.get_upcoming(tid_str, days=self.upcoming_days)
        if not overdue and not upcoming:
            return {
                "tenant_id": tenant_id, "triggered": False,
                "overdue": 0, "upcoming": 0,
                "reason": "sin obligaciones vencidas ni por vencer",
            }

        rfc = (self.db.get_tenant_config(tenant_id, "sat_rfc", "")
              or tenant.get("rfc") or "")
        ciec = self.db.get_tenant_config(tenant_id, "sat_ciec", "") or ""
        if not rfc:
            return {
                "tenant_id": tenant_id, "triggered": False,
                "overdue": len(overdue), "upcoming": len(upcoming),
                "reason": ("hay obligaciones pendientes pero el tenant no tiene "
                          "sat_rfc configurado (tenant_config o tabla tenants)"),
            }

        sched = self._sat_scheduler_factory(tenant_id, rfc, ciec)
        try:
            result = sched.process()
        except Exception as exc:  # noqa: BLE001 — reportar, nunca tumbar el tick
            log.exception("SATScheduler.process() falló para tenant %s", tenant_id)
            return {
                "tenant_id": tenant_id, "triggered": True, "ok": False,
                "overdue": len(overdue), "upcoming": len(upcoming),
                "error": str(exc),
            }
        return {
            "tenant_id": tenant_id, "triggered": True,
            "ok": bool(result.get("ok")),
            "overdue": len(overdue), "upcoming": len(upcoming),
            "result": result,
        }

    # ------------------------------------------------------------------ #
    # 2) inbox de CFDIs pendientes → orchestrator.upload_cfdis (CONTPAQi)
    # ------------------------------------------------------------------ #
    def _pending_cfdi_files(self, tenant_id: Any) -> List[Path]:
        tenant_dir = self.cfdi_inbox_dir / str(tenant_id)
        if not tenant_dir.is_dir():
            return []
        return sorted(p for p in tenant_dir.glob("*.xml") if p.is_file())

    def _archive_cfdi_files(self, tenant_id: Any, files: List[Path]) -> None:
        """Mueve (nunca borra) los CFDIs ya registrados a `procesados/`."""
        dest_dir = self.cfdi_inbox_dir / str(tenant_id) / "procesados"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                target = dest_dir / f.name
                if target.exists():
                    target = dest_dir / f"{f.stem}.{uuid.uuid4().hex[:8]}{f.suffix}"
                f.rename(target)
            except OSError:
                log.exception("No se pudo archivar %s tras registrarlo en ERP", f)

    def _check_and_register_cfdis(self, tenant_id: Any) -> Dict[str, Any]:
        files = self._pending_cfdi_files(tenant_id)
        if not files:
            return {
                "tenant_id": tenant_id, "pending_files": 0, "attempted": False,
                "reason": "sin CFDIs pendientes en el inbox",
            }

        allowed, reason = self._real_erp_write_allowed_fn()
        if not allowed:
            log.info(
                "cfdi_erp_registration_skipped tenant=%s pending=%d reason=%s",
                tenant_id, len(files), reason)
            return {
                "tenant_id": tenant_id, "pending_files": len(files),
                "attempted": False,
                "reason": f"omitido por configuración (flags en su default seguro): {reason}",
            }

        xml_files: List[Tuple[str, str]] = []
        unreadable: List[str] = []
        for f in files:
            try:
                xml_files.append((f.name, f.read_text(encoding="utf-8")))
            except OSError as exc:
                unreadable.append(f.name)
                log.warning("No se pudo leer el CFDI pendiente %s: %s", f, exc)

        if not xml_files:
            return {
                "tenant_id": tenant_id, "pending_files": len(files),
                "attempted": False,
                "reason": "ningún archivo pendiente pudo leerse",
                "unreadable": unreadable,
            }

        try:
            result = self._orchestrator.upload_cfdis(
                xml_files=xml_files,
                tenant_id=str(tenant_id),
                auto_register_erp=True,
            )
        except EndToEndPipelineError as exc:
            log.warning("Registro automático de CFDIs falló para tenant %s: %s",
                       tenant_id, exc)
            return {
                "tenant_id": tenant_id, "pending_files": len(files),
                "attempted": True, "ok": False, "error": str(exc),
            }

        ok = result.get("status") == "completed"
        registered_files = [f for f in files if f.name not in unreadable]
        if ok:
            self._archive_cfdi_files(tenant_id, registered_files)
        else:
            # No se archiva: se reintenta en el siguiente tick. Nunca se
            # finge éxito -- el status real del job queda en el resultado.
            log.warning(
                "Registro automático de CFDIs sin éxito completo para tenant %s "
                "(status=%s); los archivos quedan pendientes para el próximo tick.",
                tenant_id, result.get("status"))

        return {
            "tenant_id": tenant_id, "pending_files": len(files),
            "attempted": True, "ok": ok, "result": result,
        }

    # ------------------------------------------------------------------ #
    # Loop asyncio (para el lifespan de FastAPI)
    # ------------------------------------------------------------------ #
    async def run_forever(self) -> None:
        """Corre `tick()` cada `interval_seconds` hasta que se cancele la task.

        `tick()` es síncrono (I/O de disco + sqlite/postgres, no de red real
        — todo el transporte SAT es mock); se despacha con `asyncio.to_thread`
        para no bloquear el event loop mientras corre.
        """
        if not scheduler_enabled_from_env():
            log.info("internal_scheduler_disabled (B2B_SCHEDULER_ENABLED=false)")
            return

        log.info("internal_scheduler_started interval_seconds=%s", self.interval_seconds)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — un tick roto no debe matar el loop
                log.exception("Error inesperado ejecutando scheduler_tick")
            await self._sleep_fn(self.interval_seconds)


__all__ = ["InternalScheduler", "scheduler_enabled_from_env"]
