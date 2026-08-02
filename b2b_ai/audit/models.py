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
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


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


# ===========================================================================
# Audit logging system (quién / qué / cuándo / dónde / resultado)
# ===========================================================================
class AuditEvent(str, enum.Enum):
    """Eventos sensibles que registra el AuditLogger (contracto de trazabilidad).

    Cada evento se persiste como el verbo `action` en `audit_entries`. Usar
    `.value` para persistir de forma portable entre SQLite y PostgreSQL.
    """

    LOGIN = "login"
    LOGOUT = "logout"
    TENANT_CREATE = "tenant.create"
    TENANT_UPDATE = "tenant.update"
    TENANT_DELETE = "tenant.delete"
    CFDI_UPLOAD = "cfdi.upload"
    CFDI_PROCESS = "cfdi.process"
    DECLARATION_SUBMIT = "declaration.submit"
    BILLING_CHANGE = "billing.change"
    WEBHOOK_CONFIG_CHANGE = "webhook.config.change"


def normalize_event(event) -> str:
    """Devuelve el string de un evento, aceptando `AuditEvent` o string."""
    if isinstance(event, AuditEvent):
        return event.value
    return str(event)


@dataclass
class AuditLog:
    """Entrada del audit logging (who/what/when/where/result).

    Estructura de trazabilidad completa de una acción sensible:

      - who    : `actor` (usuario o sistema que ejecutó la acción).
      - what   : `event` (AuditEvent) + `resource`/`resource_id` afectados.
      - when   : `timestamp` (ISO, UTC).
      - where  : `tenant_id` + `ip` (origen).
      - result : `result` ('success' | 'failure' | ...) + `details` (JSON).

    Se persiste en la misma tabla `audit_entries` (schema ya migrado), con el
    resultado y detalles en el campo `details` (JSON estructurado) para que la
    consulta sea directa tanto sobre SQLite como sobre PostgreSQL.
    """

    id: Optional[int] = None
    actor: Optional[str] = None          # who
    tenant_id: Optional[int] = None      # where
    event: str = AuditEvent.LOGIN.value  # what
    resource: str = ""                   # what
    resource_id: Optional[str] = None    # what
    result: str = "success"              # result
    details: Optional[dict] = field(default=None)   # context
    ip: Optional[str] = None             # where
    timestamp: Optional[str] = None      # when (ISO UTC)

    def to_dict(self) -> dict:
        """Serialización estructurada para queryability."""
        return {
            "id": self.id,
            "actor": self.actor,
            "tenant_id": self.tenant_id,
            "event": self.event,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "result": self.result,
            "details": self.details or {},
            "ip": self.ip,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_row(cls, row: Any) -> "AuditLog":
        """Construye un AuditLog desde una fila de `audit_entries`.

        El campo `action` de la tabla guarda el evento; `details` guarda el
        JSON estructurado `{result, details}` o bien un dict directo.
        """
        details_raw = row["details"] if row["details"] is not None else None
        details: Dict[str, Any] = {}
        result = "success"
        if isinstance(details_raw, str):
            try:
                parsed = json.loads(details_raw)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                # El logger guarda {"result": ..., "details": {...}}
                if "result" in parsed and "details" in parsed:
                    result = str(parsed.get("result") or "success")
                    details = parsed.get("details") or {}
                else:
                    details = parsed
        elif isinstance(details_raw, dict):
            details = details_raw
        return cls(
            id=row["id"],
            actor=row["user_id"],
            tenant_id=row["tenant_id"],
            event=row["action"],
            resource=row["resource"],
            resource_id=row["resource_id"],
            result=result,
            details=details,
            ip=row["ip"],
            timestamp=row["timestamp"],
        )
