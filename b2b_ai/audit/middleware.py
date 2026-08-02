# -*- coding: utf-8 -*-
"""middleware.py — Auto-registro de mutaciones de la API en el audit trail.

Registra un middleware HTTP de FastAPI que audita TÁCTICAMENTE todas las
mutaciones (POST/PUT/PATCH/DELETE) de la API: captura el contexto de usuario
(a partir de la API key) y los detalles del request (método, ruta, IP, estado
de la respuesta).

Garantías de diseño:

  - NO rompe ni ralentiza el request: la escritura va en un threadpool y toda
    excepción se traga (el audit es best-effort).
  - NO consume el body del request (para no romper los endpoints multipart
    que leen `request.form()` más abajo).
  - Captura el contexto de usuario resolviendo la API key contra el auth
    existente, sin añadir dependencias.

Uso (dentro de create_app, tras crear `auth`):

    from b2b_ai.audit.middleware import install_audit_middleware
    install_audit_middleware(app, db, auth, client_ip_fn=_client_ip)
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from starlette.concurrency import run_in_threadpool

from b2b_ai.audit.models import Actions
from b2b_ai.audit.trail import AuditTrail

# Métodos HTTP que mutan estado → verbo de auditoría.
_MUTATION_ACTIONS = {
    "POST": Actions.CREATE,
    "PUT": Actions.UPDATE,
    "PATCH": Actions.UPDATE,
    "DELETE": Actions.DELETE,
}


def _default_client_ip(request) -> str:
    """IP del cliente sin depender de X-Forwarded-For (solo REMOTE_ADDR)."""
    return request.client.host if request.client else "unknown"


def install_audit_middleware(app, db, auth=None,
                             client_ip_fn: Optional[Callable] = None,
                             enabled: bool = True,
                             logger=None) -> Optional[AuditTrail]:
    """Instala el middleware de auditoría en `app`. Devuelve el AuditTrail
    usado (útil para tests) o None si `enabled` es False.

    `client_ip_fn(request)` permite reutilizar la resolución de IP con
    confianza de proxy de la app (p. ej. `_client_ip` de app.py).

    Si se pasa un `AuditLogger` (`logger`), las mutaciones se registran a
    través de él (async, no-bloqueante) con eventos estructurados; si no,
    se usa el AuditTrail síncrono como antes.
    """
    if not enabled:
        return None
    trail = AuditTrail(db)
    get_ip = client_ip_fn or _default_client_ip
    use_logger = logger is not None

    @app.middleware("http")
    async def audit_middleware(request, call_next):
        # Primero se deja pasar el request; al volver, si fue una mutación y
        # no se rompió la app, se audita con el estado final.
        response = await call_next(request)
        method = request.method
        if method in _MUTATION_ACTIONS:
            try:
                user_id = None
                tenant_id = None
                key = request.headers.get("x-api-key")
                if key and auth is not None:
                    info = auth.resolve(key)
                    if info:
                        user_id = info.get("name") or info.get("source")
                        tenant_id = info.get("tenant_id")
                ip = get_ip(request)
                action = _MUTATION_ACTIONS[method]
                if use_logger:
                    from b2b_ai.audit.logger import AuditLogger
                    if isinstance(logger, AuditLogger):
                        logger.log(
                            event=action.value.lower(), actor=user_id,
                            tenant_id=tenant_id, resource=request.url.path,
                            result=("success" if response.status_code < 400
                                    else "failure"),
                            details={"method": method,
                                     "status": response.status_code},
                            ip=ip,
                        )
                        return response
                await run_in_threadpool(
                    trail.log_action,
                    user_id, tenant_id, action, request.url.path,
                    details={"method": method,
                             "status": response.status_code},
                    resource_id=None, ip=ip)
            except Exception:  # noqa: BLE001 — el audit nunca debe romper nada
                pass
        return response

    return trail
