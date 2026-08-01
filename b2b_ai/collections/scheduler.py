# -*- coding: utf-8 -*-
"""
scheduler.py — Scheduler de recordatorios de cobranza automatizada.

Programa y ejecuta la secuencia de recordatorios (pre_vencimiento →
vencimiento → recordatorio_formal → segundo_recordatorio → escalamiento)
para cada factura pendiente, usando la fecha de vencimiento como trigger.

Componentes:
  - ScheduledReminder: recordatorio pendiente con fecha de envío
  - CollectionsScheduler: cola de recordatorios con persistencia en DB

El scheduler NO envía mensajes reales: genera el contenido y lo registra
en collection_events. El envío real queda a cargo del canal de notificaciones
del cliente (notifications/scheduler.py).

Uso típico:
    sched = CollectionsScheduler(db=db, tenant_id=1)
    # Programar recordatorios para toda la cartera
    result = sched.schedule_batch(invoices)
    # Procesar recordatorios vencidos (cron/worker)
    sent = sched.process_pending()
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from b2b_ai.services.collections_templates import SEQUENCE, STAGE_OFFSET_DAYS
from b2b_ai.services.collections import (
    CollectionsManager,
    age_bucket,
    days_overdue,
    _parse_date,
)
from b2b_ai.services.collections_templates import format_monto, render, render_subject


# --------------------------------------------------------------------------- #
# Recordatorio programado
# --------------------------------------------------------------------------- #

@dataclass
class ScheduledReminder:
    """Un recordatorio pendiente de envío."""
    factura_id: str
    nombre_empresa: str
    monto: str
    fecha_vencimiento: str
    stage: str
    channel: str
    scheduled_date: str  # ISO date (YYYY-MM-DD)
    status: str = "pending"  # pending | sent | skipped | failed
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sent_at: Optional[str] = None
    event_id: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factura_id": self.factura_id,
            "nombre_empresa": self.nombre_empresa,
            "monto": self.monto,
            "fecha_vencimiento": self.fecha_vencimiento,
            "stage": self.stage,
            "channel": self.channel,
            "scheduled_date": self.scheduled_date,
            "status": self.status,
            "created_at": self.created_at,
            "sent_at": self.sent_at,
            "event_id": self.event_id,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# Cola en memoria (persistida en DB como JSON en tenant_config)
# --------------------------------------------------------------------------- #

_CONFIG_KEY_REMINDERS = "collections_scheduled_reminders"
_LOCK = threading.Lock()


class CollectionsScheduler:
    """Scheduler de recordatorios de cobranza.

    Mantiene una cola de recordatorios programados por tenant. La cola se
    persiste en tenant_config como JSON (lista de dicts). El scheduler
    procesa la cola comparando scheduled_date con la fecha actual.

    Args:
        db:          instancia de Database (requerido para persistencia).
        tenant_id:   ID del tenant.
        manager:     CollectionsManager opcional (se crea uno si falta).
    """

    def __init__(self, db=None, tenant_id: Optional[int] = None,
                 manager: Optional[CollectionsManager] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.manager = manager or CollectionsManager(db=db, tenant_id=tenant_id)
        self._queue: List[ScheduledReminder] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Persistencia
    # ------------------------------------------------------------------ #

    def _load_queue(self):
        """Carga la cola desde la DB (una sola vez por instancia)."""
        if self._loaded or self.db is None:
            return
        try:
            raw = self.db.get_tenant_config(self.tenant_id,
                                            _CONFIG_KEY_REMINDERS)
            if raw:
                items = json.loads(raw) if isinstance(raw, str) else raw
                self._queue = [
                    ScheduledReminder(**item) for item in items
                    if isinstance(item, dict)
                ]
        except Exception:  # noqa: BLE001
            self._queue = []
        self._loaded = True

    def _save_queue(self):
        """Persiste la cola actual en la DB."""
        if self.db is None:
            return
        items = [r.to_dict() for r in self._queue]
        self.db.set_tenant_config(
            self.tenant_id,
            _CONFIG_KEY_REMINDERS,
            json.dumps(items, default=str, ensure_ascii=False),
        )

    # ------------------------------------------------------------------ #
    # Programación
    # ------------------------------------------------------------------ #

    def schedule_reminder(self, factura_id: str, nombre_empresa: str,
                          monto: str, fecha_vencimiento: str,
                          stage: str, channel: str = "email",
                          scheduled_date: Optional[str] = None,
                          today: Optional[date] = None) -> ScheduledReminder:
        """Programa un recordatorio individual.

        Si no se da `scheduled_date`, se calcula automáticamente a partir
        de la fecha de vencimiento y el offset de la etapa.
        """
        self._load_queue()

        if scheduled_date is None:
            due = _parse_date(fecha_vencimiento)
            if due is None:
                raise ValueError(
                    f"No se pudo parsear fecha_vencimiento: {fecha_vencimiento}"
                )
            offset = STAGE_OFFSET_DAYS.get(stage, 0)
            import datetime as _dt
            sched_date = due + _dt.timedelta(days=-offset)
            # Para etapas post-vencimiento (offset positivo), la fecha de
            # envío es vencimiento + offset días.
            if offset > 0:
                sched_date = due + _dt.timedelta(days=offset)
            elif offset < 0:
                # Pre-vencimiento: enviar |offset| días ANTES.
                sched_date = due + _dt.timedelta(days=offset)
            # Si hoy es la fecha calculada o pasó, enviar hoy.
            t = today or date.today()
            if sched_date <= t:
                sched_date = t
            scheduled_date = sched_date.isoformat()

        reminder = ScheduledReminder(
            factura_id=factura_id,
            nombre_empresa=nombre_empresa,
            monto=monto,
            fecha_vencimiento=fecha_vencimiento,
            stage=stage,
            channel=channel,
            scheduled_date=scheduled_date,
        )

        # Evitar duplicados (misma factura + etapa + canal).
        for existing in self._queue:
            if (existing.factura_id == factura_id
                    and existing.stage == stage
                    and existing.channel == channel
                    and existing.status in ("pending", "sent")):
                return existing

        self._queue.append(reminder)
        self._save_queue()
        return reminder

    def schedule_batch(self, invoices: List[Dict[str, Any]],
                       channels: Optional[List[str]] = None,
                       today: Optional[date] = None) -> Dict[str, Any]:
        """Programa recordatorios para toda la cartera pendiente.

        Para cada factura, determina el stage que corresponde según la
        fecha de vencimiento y la fecha actual, y programa un recordatorio
        para cada canal.

        Devuelve: {total_scheduled, reminders: [...], skipped}
        """
        self._load_queue()
        channels = channels or ["email"]
        today = today or date.today()
        scheduled = []
        skipped = 0

        for inv in invoices:
            due_str = inv.get("fecha_vencimiento", "")
            stage = self._get_current_stage(due_str, today)
            if stage is None:
                skipped += 1
                continue

            for channel in channels:
                reminder = self.schedule_reminder(
                    factura_id=str(inv.get("factura_id", "")),
                    nombre_empresa=inv.get("nombre_empresa", ""),
                    monto=str(inv.get("monto", "0")),
                    fecha_vencimiento=due_str,
                    stage=stage,
                    channel=channel,
                    scheduled_date=today.isoformat(),
                    today=today,
                )
                scheduled.append(reminder.to_dict())

        return {
            "total_scheduled": len(scheduled),
            "reminders": scheduled,
            "skipped": skipped,
        }

    def _get_current_stage(self, fecha_vencimiento: str,
                           today: date) -> Optional[str]:
        """Determina el stage actual para una factura."""
        dias = days_overdue(fecha_vencimiento, today)
        bucket = age_bucket(dias)

        # Mapeo directo por días de atraso
        if dias <= -7:
            return None  # Aún no toca
        if -7 <= dias < 0:
            return "pre_vencimiento"
        if dias == 0:
            return "vencimiento"
        if 1 <= dias <= 30:
            return "recordatorio_formal"
        if 31 <= dias <= 60:
            return "segundo_recordatorio"
        if dias >= 61:
            return "escalamiento"
        return None

    # ------------------------------------------------------------------ #
    # Procesamiento
    # ------------------------------------------------------------------ #

    def process_pending(self, today: Optional[date] = None,
                        record: bool = True) -> Dict[str, Any]:
        """Procesa recordatorios pendientes cuya fecha ya llegó.

        Genera el contenido, lo registra en collection_events (si record=True)
        y marca el reminder como 'sent'. Devuelve el resumen del procesamiento.
        """
        self._load_queue()
        today = today or date.today()
        sent = []
        failed = []
        skipped = []

        for reminder in self._queue:
            if reminder.status != "pending":
                continue

            sched_date = _parse_date_str(reminder.scheduled_date)
            if sched_date is None or sched_date > today:
                continue

            try:
                invoice = {
                    "factura_id": reminder.factura_id,
                    "nombre_empresa": reminder.nombre_empresa,
                    "monto": reminder.monto,
                    "fecha_vencimiento": reminder.fecha_vencimiento,
                }
                msg = self.manager.send_reminder(
                    invoice,
                    stage=reminder.stage,
                    channel=reminder.channel,
                    today=today,
                    record=record,
                )
                reminder.status = "sent"
                reminder.sent_at = datetime.utcnow().isoformat()
                reminder.event_id = msg.get("event_id")
                sent.append(reminder.to_dict())
            except Exception as exc:  # noqa: BLE001
                reminder.status = "failed"
                reminder.error = str(exc)
                failed.append(reminder.to_dict())

        self._save_queue()
        return {
            "sent": len(sent),
            "failed": len(failed),
            "details_sent": sent,
            "details_failed": failed,
        }

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #

    def list_pending(self) -> List[Dict[str, Any]]:
        """Lista recordatorios pendientes."""
        self._load_queue()
        return [r.to_dict() for r in self._queue if r.status == "pending"]

    def list_all(self) -> List[Dict[str, Any]]:
        """Lista todos los recordatorios (cualquier estado)."""
        self._load_queue()
        return [r.to_dict() for r in self._queue]

    def get_stats(self) -> Dict[str, Any]:
        """Estadísticas de la cola de recordatorios."""
        self._load_queue()
        by_status = {}
        by_stage = {}
        by_channel = {}
        for r in self._queue:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
            by_channel[r.channel] = by_channel.get(r.channel, 0) + 1
        return {
            "total": len(self._queue),
            "by_status": by_status,
            "by_stage": by_stage,
            "by_channel": by_channel,
        }

    def cancel_reminder(self, factura_id: str, stage: str,
                        channel: str = "email") -> bool:
        """Cancela un recordatorio pendiente. Devuelve True si se canceló."""
        self._load_queue()
        for r in self._queue:
            if (r.factura_id == factura_id and r.stage == stage
                    and r.channel == channel and r.status == "pending"):
                r.status = "skipped"
                self._save_queue()
                return True
        return False

    def clear_processed(self) -> int:
        """Elimina recordatorios procesados (sent/skipped/failed) de la cola.
        Devuelve cuántos se eliminaron."""
        self._load_queue()
        before = len(self._queue)
        self._queue = [r for r in self._queue if r.status == "pending"]
        self._save_queue()
        return before - len(self._queue)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _parse_date_str(s: str) -> Optional[date]:
    """Parsea una fecha ISO (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS)."""
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
