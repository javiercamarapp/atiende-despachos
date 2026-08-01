# -*- coding: utf-8 -*-
"""Audit trail enterprise: bitácora de acciones con contexto de usuario.

Subsistema de auditoría sobre la tabla `audit_entries`. Distinto del
`audit_log` de tools internas (db.log_call): este rastrea acciones de negocio
y de API con user_id, resource, resource_id, detalles y dirección IP.

  - models     : AuditEntry + enumerado de acciones (Actions).
  - trail      : clase AuditTrail (escribir/leer/exportar/buscar).
  - middleware : auto-registro de mutaciones de la API (FastAPI).
"""
from b2b_ai.audit.models import AuditEntry, Actions
from b2b_ai.audit.trail import AuditTrail

__all__ = ["AuditEntry", "Actions", "AuditTrail"]
