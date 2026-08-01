# -*- coding: utf-8 -*-
"""trail.py — Auditoría de acciones de negocio (AuditTrail).

Clase de alto nivel sobre la tabla `audit_entries`:

  - log_action      : registra una acción.
  - get_audit_log   : lista filtrada por tenant (acciones, recurso, usuario,
                      rango temporal, límite).
  - export_audit_log: exporta a JSON o CSV (para cumplimiento/entrega).
  - search_audit_log: búsqueda de texto libre sobre los campos.

Reutiliza la conexión thread-local de `b2b_ai.db.db.Database` (db.conn), de
modo que es coherente con el resto de la capa de datos y funciona tanto sobre
SQLite como sobre PostgreSQL (placeholders `?`, que PG traduce a `%s`).

Toda lectura FILTRA por tenant_id salvo la búsqueda, que es una herramienta
de administración y acepta un tenant opcional para acotar.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from b2b_ai.audit.models import Actions, AuditEntry, normalize_action
from b2b_ai.db.db import Database


class AuditTrail:
    """Bitácora de auditoría multi-tenant (tabla audit_entries)."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self.db = db or Database()

    # ---- Escritura --------------------------------------------------------
    def log_action(self, user_id, tenant_id, action, resource, details=None,
                   resource_id: Optional[str] = None,
                   ip: Optional[str] = None) -> int:
        """Registra una acción en el audit trail.

        Devuelve el id de la fila creada. `details` (dict) se persiste como
        JSON; `action` acepta `Actions` o su string.
        """
        action_str = normalize_action(action)
        details_txt = json.dumps(details, default=str, ensure_ascii=False) \
            if details is not None else None
        cur = self.db.conn.execute(
            "INSERT INTO audit_entries(user_id, tenant_id, action, resource, "
            "resource_id, details, ip) VALUES (?,?,?,?,?,?,?)",
            (user_id, tenant_id, action_str, resource, resource_id,
             details_txt, ip))
        self.db.conn.commit()
        return cur.lastrowid

    # ---- Lectura ----------------------------------------------------------
    def get_audit_log(self, tenant_id, filters: Optional[Dict[str, Any]] = None
                      ) -> List[AuditEntry]:
        """Lista de entradas de un tenant, ordenadas de más reciente a más
        antigua, con filtros opcionales:

          - action   : verbo (Actions o string).
          - resource : tipo de recurso (match exacto).
          - resource_id : id del recurso.
          - user_id  : usuario (match exacto).
          - from / to: rango temporal (ISO) sobre `timestamp`.
          - limit    : máximo de filas (default 100).

        Aislamiento multi-tenant: filtra SIEMPRE por tenant_id.
        """
        filters = filters or {}
        q = "SELECT * FROM audit_entries"
        clauses: List[str] = []
        params: List[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if filters.get("action") is not None:
            clauses.append("action=?")
            params.append(normalize_action(filters["action"]))
        if filters.get("resource") is not None:
            clauses.append("resource=?")
            params.append(str(filters["resource"]))
        if filters.get("resource_id") is not None:
            clauses.append("resource_id=?")
            params.append(str(filters["resource_id"]))
        if filters.get("user_id") is not None:
            clauses.append("user_id=?")
            params.append(str(filters["user_id"]))
        if filters.get("from") is not None:
            clauses.append("timestamp>=?")
            params.append(str(filters["from"]))
        if filters.get("to") is not None:
            clauses.append("timestamp<=?")
            params.append(str(filters["to"]))
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        limit = int(filters.get("limit") or 100)
        q += f" LIMIT {limit}"
        return [AuditEntry.from_row(r)
                for r in self.db.conn.execute(q, params).fetchall()]

    def search_audit_log(self, query: str,
                         tenant_id: Optional[int] = None) -> List[AuditEntry]:
        """Búsqueda de texto libre (LIKE) sobre action, resource,
        resource_id, details, user_id e ip.

        `tenant_id` es opcional: si se pasa, acota la búsqueda a un tenant
        (recomendado en operación multi-tenant).
        """
        like = f"%{query}%"
        q = ("SELECT * FROM audit_entries WHERE "
             "action LIKE ? OR resource LIKE ? OR resource_id LIKE ? "
             "OR details LIKE ? OR user_id LIKE ? OR ip LIKE ?")
        params: List[Any] = [like] * 6
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY id DESC LIMIT 100"
        return [AuditEntry.from_row(r)
                for r in self.db.conn.execute(q, params).fetchall()]

    # ---- Exportación ------------------------------------------------------
    def export_audit_log(self, tenant_id, format: str = "json") -> str:
        """Exporta el audit log de un tenant a `format` ('json' | 'csv').

        Devuelve el contenido serializado como string (para descargar o
        persistir). JSON: lista indentada; CSV: con cabecera estándar.
        """
        rows = self.get_audit_log(tenant_id, {"limit": 100000})
        if format == "csv":
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf, fieldnames=["id", "user_id", "tenant_id", "action",
                                 "resource", "resource_id", "ip", "timestamp"])
            writer.writeheader()
            for e in rows:
                writer.writerow({
                    "id": e.id, "user_id": e.user_id,
                    "tenant_id": e.tenant_id, "action": e.action,
                    "resource": e.resource, "resource_id": e.resource_id,
                    "ip": e.ip, "timestamp": e.timestamp,
                })
            return buf.getvalue()
        # default: json
        return json.dumps([e.to_dict() for e in rows],
                          ensure_ascii=False, indent=2, default=str)
