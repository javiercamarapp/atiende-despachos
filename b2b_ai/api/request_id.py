# -*- coding: utf-8 -*-
"""
request_id.py — Request ID tracking para observabilidad en piloto.

Cada request HTTP recibe un ID correlacionable (X-Request-ID) para saber qué
request causó qué error en los logs. Comportamiento:

  - Si el cliente envía un header `X-Request-ID`, se reutiliza (idempotente
    para retries del cliente).
  - Si no lo envía, se genera un UUID4.
  - El ID se expone en:
        · Header de respuesta `X-Request-ID` (todas las respuestas).
        · `request.state.request_id` (accesible en cualquier handler).
        · contextvar `get_request_id()` (para handlers de error y logging).
  - Los logs estructurados (b2b_ai.monitoring.logger) llevan el mismo ID,
    de modo que un error en logs es correlacionable con el request.

Se integra como la capa más externa (add_middleware), por lo que envuelve
también los errores producidos por exception handlers y rate limiting.

Usage:
    from b2b_ai.api.request_id import install_request_id, get_request_id
    install_request_id(app)
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Nombre del header canónico.
REQUEST_ID_HEADER = "X-Request-ID"


# contextvar accesible desde cualquier handler / exception handler / log.
_request_id_ctx: "ContextVar[str]" = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Devuelve el request_id del request actual ("" si no hay contexto)."""
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> str:
    """Fija el request_id en el contextvar actual. Devuelve el id."""
    _request_id_ctx.set(request_id)
    return request_id


def generate_request_id() -> str:
    """Genera un UUID4 como request id."""
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Asegura que todo request tenga un X-Request-ID.

    Reutiliza el header entrante si existe; si no, genera un UUID4. Registra
    el id en `request.state` y en el contextvar, y lo refleja en la respuesta.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        # 1) Resolver: header del cliente o UUID4 generado.
        request_id = request.headers.get("x-request-id") or generate_request_id()

        # 2) Registrar en state (handlers) y en el contextvar (errores/logs).
        request.state.request_id = request_id
        set_request_id(request_id)

        # 3) Procesar. El contextvar se propaga por contextvars a las
        #    coroutines hijas (mismo request_id en todo el request).
        response = await call_next(request)

        # 4) Reflejar en la respuesta SIEMPRE (también en errores).
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def install_request_id(app) -> None:
    """Instala el middleware de request id en la app FastAPI."""
    app.add_middleware(RequestIDMiddleware)
