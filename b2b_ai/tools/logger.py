# -*- coding: utf-8 -*-
"""
logger.py — Logger de TODAS las llamadas a tools.

Persiste en la tabla `audit_log` de la DB multi-tenant y mantiene un buffer
en memoria para consultas rápidas. El orquestador/API usa este logger para
cumplir el requisito de auditoría completa de cada invocación.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime


class ToolCallLogger:
    def __init__(self, db=None, buffer_size=500):
        self.db = db
        self._buffer = []
        self._buffer_size = buffer_size
        self._lock = threading.Lock()

    def set_db(self, db):
        self.db = db

    def log(self, tool_name, action, entity="", entity_id="", payload=None,
            status="ok", tenant_id=None):
        """Registra una llamada. Siempre devuelve el id (aunque sea 0)."""
        record = {
            "id": None,
            "tenant_id": tenant_id,
            "tool_name": tool_name,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "payload": payload,
            "status": status,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) > self._buffer_size:
                self._buffer.pop(0)
            row_id = 0
            if self.db is not None:
                row_id = self.db.log_call(
                    tool_name, action, entity, entity_id, payload, status, tenant_id)
            record["id"] = row_id
        return row_id

    def recent(self, limit=50):
        with self._lock:
            return list(self._buffer[-limit:])

    def count(self, tool_name=None):
        if self.db is not None:
            return self.db.count_audit(tool_name)
        with self._lock:
            if tool_name:
                return sum(1 for r in self._buffer if r["tool_name"] == tool_name)
            return len(self._buffer)


# Logger global por defecto (puede ligarse a una DB con set_db).
logger = ToolCallLogger()
