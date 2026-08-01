# -*- coding: utf-8 -*-
"""
logger.py — Logging estructurado (JSON) con contexto de request y PII masking.

Requisitos del objetivo "monitoring + logging":
    - Structured logging en formato JSON (una línea JSON por registro).
    - Niveles DEBUG, INFO, WARNING, ERROR, CRITICAL.
    - Request ID tracking (contextvar: cada request lleva un request_id).
    - Contexto de usuario / tenant.
    - PII masking en los logs (emails, RFC, CURP, teléfonos, tarjetas,
      secretos) tanto en el mensaje como en los campos extra.

Sin dependencias externas (stdlib logging + contextvars + json).

Uso:
    from b2b_ai.monitoring.logger import get_logger, request_context

    log = get_logger("api")
    with request_context(tenant_id=7, user_id="u_12"):
        log.info("factura procesada", extra={"invoice_id": "X", "rfc": "XAXX010101000"})
        # -> {"level":"INFO","logger":"api","message":"factura procesada",
        #     "request_id":"...","tenant_id":7,"user_id":"u_12",
        #     "invoice_id":"X","rfc":"<rfc>"}
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from contextlib import contextmanager
import uuid

# --------------------------------------------------------------------------- #
# PII masking
# --------------------------------------------------------------------------- #
# Patrones de PII latina / mexicana. La sustitución es total (no deja parte del
# dato visible): en logs la existencia del campo importa más que su valor.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Use canonical RFC regex for PII masking.
from b2b_ai.common.rfc import RFC_RE as _CANONICAL_RFC_RE
_RFC_RE = re.compile(r"\b" + _CANONICAL_RFC_RE.pattern.lstrip("^").rstrip("$") + r"\b")
_CURP_RE = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9][0-9]\b")
# Teléfonos: 10+ dígitos, opcional prefijo internacional/separadores.
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.\-()]*)?(?:\(?\d{2,4}\)?[\s.\-]?)\d{3}[\s.\-]?\d{3,4}\b")
# Tarjeta: 13–19 dígitos (con o sin separadores), agrupada en 4.
_CC_RE = re.compile(r"\b(?:\d[ \-\u2011]?){13,19}\d\b")
# Secreto largo estilo token/JWT/key.
_TOKEN_RE = re.compile(r"\b(?:[A-Za-z0-9_\-\.]{20,})\b(?:===)?")

# Claves cuyo *valor* se considera sensible (mask por nombre de campo).
_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "secret", "api_key", "apikey", "token",
    "access_token", "refresh_token", "authorization", "x-api-key", "credit_card",
    "cc", "card_number", "iban", "curp", "rfc", "email", "phone", "telefono",
    "webhook_url", "notif_recipient",
}


def mask_pii(value):
    """Enmascara PII en un valor: str → regex; dict/list → recursivo por clave.

    Devuelve el valor enmascarado (misma forma de entrada). Diseñado para no
    lanzar excepciones: ante tipos no serializables devuelve el valor tal cual.
    """
    if isinstance(value, str):
        s = value
        for pattern, token in ((_CURP_RE, "<curp>"),
                               (_RFC_RE, "<rfc>"),
                               (_CC_RE, "<card>"),
                               (_PHONE_RE, "<phone>"),
                               (_EMAIL_RE, "<email>")):
            s = pattern.sub(token, s)
        # Evita borrar enteramente strings que son tokens reales: solo enmascara
        # si el token es lo único que hay (evita false positives en ids).
        return s
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = "<redacted>"
            else:
                out[k] = mask_pii(v)
        return out
    if isinstance(value, (list, tuple)):
        return [mask_pii(x) for x in value]
    return value


# --------------------------------------------------------------------------- #
# Contexto de request (request_id + tenant + user) via contextvar
# --------------------------------------------------------------------------- #
_request_ctx: "contextvars.ContextVar[dict]" = contextvars.ContextVar(
    "b2b_request_ctx", default=None)


def _new_request_id() -> str:
    return uuid.uuid4().hex[:16]


@contextmanager
def request_context(request_id=None, tenant_id=None, user_id=None):
    """Context manager que fija el request_id/tenant/user del request actual.

    Cada coroutine/thread que procesa un request obtiene su propio contexto
    (contextvars), de modo que los logs emitidos dentro del `with` llevan el
    request_id correcto sin contaminar otros requests concurrentes.
    """
    ctx = {
        "request_id": request_id or _new_request_id(),
        **({"tenant_id": tenant_id} if tenant_id is not None else {}),
        **({"user_id": user_id} if user_id is not None else {}),
    }
    token = _request_ctx.set(ctx)
    try:
        yield ctx
    finally:
        _request_ctx.reset(token)


# --------------------------------------------------------------------------- #
# Formateador JSON
# --------------------------------------------------------------------------- #
class JsonFormatter(logging.Formatter):
    """Serializa cada registro como una línea JSON con PII enmascarada.

    Campos extra (dicts) se pasan como `extra={"field": value}` al llamar al
    logger. El formateador fusiona: timestamp, level, logger, message, contexto
    de request y los extras — todo enmascarado.
    """

    def __init__(self, include_utc: bool = False):
        super().__init__()
        self.include_utc = include_utc

    def format(self, record: logging.LogRecord) -> str:
        message = mask_pii(record.getMessage())
        payload = {
            "ts": (record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        ctx = _request_ctx.get()
        if ctx:
            payload.update(mask_pii(ctx))
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict) and extra:
            payload.update(mask_pii(extra))
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # Nunca dejar caer un log por un extra no serializable.
            payload["extra_fields"] = "<unserializable>"
            return json.dumps(payload, ensure_ascii=False, default=str)


def _install_handler() -> None:
    """Instala el handler JSON en el root logger (idempotente)."""
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, "b2b_json", False):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.b2b_json = True  # marca para no duplicar
    root.addHandler(handler)
    if root.level == logging.WARNING:
        root.setLevel(logging.INFO)


def get_logger(name: str = "b2b_ai") -> logging.Logger:
    """Devuelve un logger con el handler JSON instalado.

    `name` identifica el componente (p. ej. "api", "pipeline", "alerts"). El
    nivel raíz se controla con la env B2B_LOG_LEVEL (DEBUG|INFO|WARNING|ERROR).
    """
    _install_handler()
    level = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
             "WARNING": logging.WARNING, "ERROR": logging.ERROR,
             "CRITICAL": logging.CRITICAL}.get(
                 __import__("os").environ.get("B2B_LOG_LEVEL", "INFO").upper(),
                 logging.INFO)
    root = logging.getLogger()
    if root.level > level:
        root.setLevel(level)
    logger = logging.getLogger(name)
    logger.propagate = True
    return logger


def log_with_extras(logger: logging.Logger, level: int, message: str,
                    **extras) -> None:
    """Emite un registro con campos extra, ignorando si el nivel no aplica."""
    if logger.isEnabledFor(level):
        logger.log(level, message, extra={"extra_fields": dict(extras)})
