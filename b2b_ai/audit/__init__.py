# -*- coding: utf-8 -*-
"""Audit trail enterprise: bitácora de acciones con contexto de usuario.

Subsistema de auditoría sobre la tabla `audit_entries`. Distinto del
`audit_log` de tools internas (db.log_call): este rastrea acciones de negocio
y de API con user_id, resource, resource_id, detalles y dirección IP.

  - models     : AuditEntry + enumerado de acciones (Actions) + AuditEvent /
                 AuditLog (who/what/when/where/result).
  - trail      : clase AuditTrail (escribir/leer/exportar/buscar).
  - logger     : AuditLogger async no-bloqueante (queue-based) para
                 trazabilidad de acciones sensibles.
  - middleware : auto-registro de mutaciones de la API (FastAPI).
"""
from b2b_ai.audit.models import (
    AuditEntry,
    AuditEvent,
    AuditLog,
    Actions,
    normalize_action,
    normalize_event,
)
from b2b_ai.audit.trail import AuditTrail
from b2b_ai.audit.logger import AuditLogger

__all__ = [
    "AuditEntry",
    "AuditEvent",
    "AuditLog",
    "AuditLogger",
    "Actions",
    "AuditTrail",
    "normalize_action",
    "normalize_event",
]
