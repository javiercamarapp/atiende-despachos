# -*- coding: utf-8 -*-
"""models.py — Modelos del audit trail (entrada + enumerado de acciones).

`AuditEntry` es un dataclass que refleja una fila de `audit_entries`:

  - id          : PK (autoincremental).
  - user_id     : identificador del usuario que ejecutó la acción
                  (None si es anónimo / sistema).
  - tenant_id   : tenant al que pertenece la acción (aislamiento multi-tenant).
  - action      : verbo normalizado (Actions).
  - resource    : tipo de recurso afectado (p. ej. "invoice", "invoices/process").
  - resource_id : id del recurso concreto (si aplica).
  - details     : dict libre con contexto adicional (se persiste como JSON).
  - ip          : dirección IP del cliente (forense).
  - timestamp   : cuándo ocurrió (ISO).

`Actions` es el enumerado de verbos soportados. Se persiste como su `.value`
(string en mayúsculas).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional


class Actions(str, enum.Enum):
    """Verbos normalizados del audit trail.

    Se serializa a su `.value` (string) para persistir de forma portable
    entre SQLite y PostgreSQL.
    """

    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    EXPORT = "EXPORT"
    APPROVE = "APPROVE"


def normalize_action(action) -> str:
    """Devuelve el string del verbo, aceptando `Actions` o string."""
    if isinstance(action, Actions):
        return action.value
    return str(action)


@dataclass
class AuditEntry:
    """Una entrada del audit trail (equivalente a una fila de audit_entries)."""

    id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[int] = None
    action: str = Actions.READ.value
    resource: str = ""
    resource_id: Optional[str] = None
    details: Optional[dict] = field(default=None)
    ip: Optional[str] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialización a dict (con `details` ya deserializado)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "action": self.action,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip": self.ip,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_row(cls, row: Any) -> "AuditEntry":
        """Construye una entrada a partir de una fila (dict-like) de la DB.

        `details` se lee como JSON; si no es parseable se conserva el texto
        crudo para no perder información.
        """
        details = row["details"] if row["details"] is not None else None
        if isinstance(details, str):
            import json
            try:
                details = json.loads(details)
            except (ValueError, TypeError):
                pass
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            action=row["action"],
            resource=row["resource"],
            resource_id=row["resource_id"],
            details=details,
            ip=row["ip"],
            timestamp=row["timestamp"],
        )
