# -*- coding: utf-8 -*-
"""logger.py — AuditLogger: trazabilidad de acciones sensibles (who/what/when/where/result).

`AuditLogger` registra cada acción sensible de la plataforma en la tabla
`audit_entries` (schema ya migrado, portable SQLite/PostgreSQL) con contexto
completo de trazabilidad:

    who    -> actor (usuario o sistema)
    what   -> event (AuditEvent) + resource / resource_id
    when   -> timestamp (ISO UTC)
    where  -> tenant_id + ip
    result -> result ('success' | 'failure' | ...) + details (JSON estructurado)

Diseño:

  - ASYNC NO-BLOCKING: `log()` mete la entrada en una `queue.Queue` y un worker
    en background la drena y la persiste. El request nunca espera por el I/O
    del audit. Toda excepción se traga (best-effort: el audit no debe romper
    el flujo de negocio ni latir el request).
  - STRUCTURED JSON: cada entrada se serializa como JSON estructurado (dict
    con claves who/what/when/where/result) para queryability directa.
  - CONFIGURABLE: `enabled_events` (qué eventos se loguean, None = todos) y
    `retention_days` (política de retención; `prune()` borra lo anterior).
  - `flush()` drena la cola de forma síncrona (útil en tests y al apagar).

Uso:

    from b2b_ai.audit.logger import AuditLogger
    logger = AuditLogger(db)
    logger.start()          # arranca el worker en background
    logger.log(event="login", actor="alice@x.io", tenant_id=1, ip="10.0.0.1")
    logger.flush()          # espera a que todo se persista
    logger.stop()           # detiene el worker al apagar la app
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from b2b_ai.audit.models import AuditEvent, AuditLog, normalize_event
from b2b_ai.db.db import Database

log = logging.getLogger("b2b_ai.audit")


def _now_iso() -> str:
    """Timestamp ISO 8601 UTC (cuándo ocurrió la acción)."""
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    """Registra acciones sensibles con trazabilidad who/what/when/where/result.

    No-bloqueante: `log()` encola y devuelve al instante; un worker en
    background drena la cola y persiste. Configurable por eventos y con
    política de retención.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        *,
        enabled_events: Optional[Iterable] = None,
        retention_days: Optional[int] = None,
        max_queue: int = 5000,
        auto_start: bool = True,
    ) -> None:
        self.db = db or Database()
        self.max_queue = max_queue
        # Qué eventos se loguean: None = todos; si no, solo los de la lista.
        self.enabled_events: Optional[set] = None
        if enabled_events is not None:
            self.enabled_events = {normalize_event(e) for e in enabled_events}
        self.retention_days = retention_days
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=max_queue)
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False
        if auto_start:
            self.start()

    # ---- Ciclo de vida ----------------------------------------------------
    def start(self) -> "AuditLogger":
        """Arranca el worker en background (idempotente)."""
        if self._started:
            return self
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run, name="audit-logger", daemon=True
        )
        self._started = True
        self._worker.start()
        return self

    def stop(self, flush: bool = True) -> None:
        """Detiene el worker. Si `flush`, drena primero la cola."""
        if flush:
            self.flush()
        self._stop_event.set()
        self._started = False
        if self._worker is not None and self._worker is not threading.current_thread():
            try:
                self._worker.join(timeout=2)
            except RuntimeError:
                pass
        self._worker = None

    # ---- Escritura --------------------------------------------------------
    def log(
        self,
        event,
        actor: Optional[str] = None,
        tenant_id: Optional[int] = None,
        resource: str = "",
        resource_id: Optional[str] = None,
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
        ip: Optional[str] = None,
        *,
        _when: Optional[str] = None,
    ) -> Optional[int]:
        """Encola una entrada de auditoría (no-bloqueante).

        Devuelve inmediatamente (None o el id si se procesó en modo síncrono
        con `_when`). El worker persiste en background.
        """
        ev = normalize_event(event)
        if self.enabled_events is not None and ev not in self.enabled_events:
            return None  # evento deshabilitado por configuración
        entry: Dict[str, Any] = {
            "event": ev,
            "actor": actor,
            "tenant_id": tenant_id,
            "resource": resource or "",
            "resource_id": resource_id,
            "result": result,
            "details": details or {},
            "ip": ip,
            "timestamp": _when or _now_iso(),
        }
        # Structured JSON al log (queryability en stdout/logs agregados).
        log.info("audit %s", json.dumps(entry, ensure_ascii=False, default=str))
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            # Cola llena: no romper el request. Se descarta la entrada.
            log.warning("audit queue full, dropping entry: %s", ev)
        return None

    # Métodos de conveniencia por evento sensible --------------------------
    def login(self, actor, tenant_id=None, ip=None, details=None, **kw):
        return self.log(AuditEvent.LOGIN, actor=actor, tenant_id=tenant_id,
                        resource="auth", ip=ip, details=details, **kw)

    def logout(self, actor, tenant_id=None, ip=None, details=None, **kw):
        return self.log(AuditEvent.LOGOUT, actor=actor, tenant_id=tenant_id,
                        resource="auth", ip=ip, details=details, **kw)

    def tenant_created(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.TENANT_CREATE, actor=actor,
                        tenant_id=tenant_id, resource="tenant",
                        resource_id=str(resource_id) if resource_id else None,
                        details=details, **kw)

    def tenant_updated(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.TENANT_UPDATE, actor=actor,
                        tenant_id=tenant_id, resource="tenant",
                        resource_id=str(resource_id) if resource_id else None,
                        details=details, **kw)

    def tenant_deleted(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.TENANT_DELETE, actor=actor,
                        tenant_id=tenant_id, resource="tenant",
                        resource_id=str(resource_id) if resource_id else None,
                        details=details, **kw)

    def cfdi_uploaded(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.CFDI_UPLOAD, actor=actor, tenant_id=tenant_id,
                        resource="cfdi", resource_id=resource_id, details=details,
                        **kw)

    def cfdi_processed(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.CFDI_PROCESS, actor=actor, tenant_id=tenant_id,
                        resource="cfdi", resource_id=resource_id, details=details,
                        **kw)

    def declaration_submitted(self, actor, tenant_id, resource_id=None,
                              details=None, **kw):
        return self.log(AuditEvent.DECLARATION_SUBMIT, actor=actor,
                        tenant_id=tenant_id, resource="declaration",
                        resource_id=resource_id, details=details, **kw)

    def billing_changed(self, actor, tenant_id, resource_id=None, details=None, **kw):
        return self.log(AuditEvent.BILLING_CHANGE, actor=actor, tenant_id=tenant_id,
                        resource="billing", resource_id=resource_id, details=details,
                        **kw)

    def webhook_config_changed(self, actor, tenant_id, resource_id=None,
                               details=None, **kw):
        return self.log(AuditEvent.WEBHOOK_CONFIG_CHANGE, actor=actor,
                        tenant_id=tenant_id, resource="webhook",
                        resource_id=resource_id, details=details, **kw)

    # ---- Worker interno ---------------------------------------------------
    def _run(self) -> None:
        """Drena la cola y persiste cada entrada (best-effort)."""
        while not self._stop_event.is_set():
            try:
                entry = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self._persist(entry)
            self._queue.task_done()

    def _persist(self, entry: Dict[str, Any]) -> None:
        """Persiste una entrada estructurada en `audit_entries` (JSON details)."""
        try:
            details_payload = {
                "result": entry["result"],
                "details": entry["details"],
            }
            self.db.conn.execute(
                "INSERT INTO audit_entries(user_id, tenant_id, action, resource, "
                "resource_id, details, ip, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (
                    entry["actor"],
                    entry["tenant_id"],
                    entry["event"],
                    entry["resource"],
                    entry["resource_id"],
                    json.dumps(details_payload, ensure_ascii=False, default=str),
                    entry["ip"],
                    entry["timestamp"],
                ),
            )
            self.db.conn.commit()
        except Exception as exc:  # noqa: BLE001 — best-effort, nunca romper
            log.warning("audit persist failed: %s", exc)

    def flush(self) -> None:
        """Drena la cola de forma síncrona (persiste todo lo pendiente).

        Primero vacía la cola en el hilo actual y después espera a que el
        worker termine de persistir las entradas que ya tomó (queue.join).
        Así, al retornar, toda entrada encolada está persistida y visible
        para las lecturas (seguro en tests y al apagar la app).
        """
        while True:
            try:
                entry = self._queue.get_nowait()
            except queue.Empty:
                break
            self._persist(entry)
            self._queue.task_done()
        # Espera a que las entradas que el worker ya tomó se marquen done.
        if self._started:
            self._queue.join()

    # ---- Lectura ----------------------------------------------------------
    def query(
        self,
        *,
        tenant_id: Optional[int] = None,
        actor: Optional[str] = None,
        event: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Consulta entradas de auditoría con filtros (user, action, date range, tenant)."""
        q = "SELECT * FROM audit_entries"
        clauses: List[str] = []
        params: List[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if actor is not None:
            clauses.append("user_id=?")
            params.append(actor)
        if event is not None:
            clauses.append("action=?")
            params.append(normalize_event(event))
        if from_ts is not None:
            clauses.append("timestamp>=?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("timestamp<=?")
            params.append(to_ts)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        q += f" LIMIT {int(limit)}"
        rows = self.db.conn.execute(q, params).fetchall()
        return [AuditLog.from_row(r) for r in rows]

    # ---- Retención --------------------------------------------------------
    def prune(self, retention_days: Optional[int] = None) -> int:
        """Borra entradas más antiguas que `retention_days` (default: config).

        Devuelve el número de filas eliminadas.
        """
        days = retention_days if retention_days is not None else self.retention_days
        if not days:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = self.db.conn.execute(
            "DELETE FROM audit_entries WHERE timestamp < ?", (cutoff,)
        )
        self.db.conn.commit()
        return cur.rowcount if cur.rowcount else 0
