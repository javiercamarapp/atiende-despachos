# -*- coding: utf-8 -*-
"""
request_validator.py — Validación de peticiones para la API FastAPI.

Funciones (stateless, testeables):

  - ``validate_content_type`` — valida el header Content-Type.
  - ``validate_request_size`` — límite de tamaño de cuerpo (default 10 MB),
    cubriendo Content-Length y Transfer-Encoding: chunked.
  - ``validate_sql_injection`` / ``detect_sql_injection`` — detección básica
    de payloads de inyección SQL en texto plano.
  - ``validate_xss`` / ``detect_xss`` — detección básica de XSS/scripts.

Middleware ``RequestValidationMiddleware`` que combina todas las comprobaciones
antes de que la petición llegue a la aplicación, devolviendo errores
estructurados (400/413/415/422) sin ejecutar handlers.

Usage (dentro de create_app):

    from b2b_ai.middleware.request_validator import install_request_validator
    install_request_validator(app)
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
# Límite de tamaño de cuerpo por defecto: 10 MB.  Sobreescribible vía env.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024

# Content-Type permitidos para peticiones con cuerpo (POST/PUT/PATCH).
_ALLOWED_CONTENT_TYPES = (
    "application/json",
    "multipart/form-data",
    "application/x-www-form-urlencoded",
    "application/xml",
    "text/xml",
    "application/soap+xml",
    "text/plain",
    "application/octet-stream",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)

# Rutas exentas de validación (healthcheck, estáticos, docs).
_EXEMPT_PREFIXES: Tuple[str, ...] = (
    "/health", "/metrics", "/static", "/icons", "/manifest.json",
    "/sw.js", "/robots.txt", "/sitemap.xml", "/docs", "/openapi.json",
    "/redoc", "/favicon.ico",
)


def _get_max_bytes() -> int:
    """Resuelve el máximo de tamaño de cuerpo en bytes."""
    raw = os.environ.get("B2B_MAX_REQUEST_SIZE_MB")
    if raw:
        try:
            mb = int(raw)
            if mb > 0:
                return mb * 1024 * 1024
        except ValueError:
            pass
    return _DEFAULT_MAX_BYTES


# ---------------------------------------------------------------------------
# Detección SQL injection
# ---------------------------------------------------------------------------
# Patrones típicos de inyección SQL. Se combinan con límite de longitud para
# evitar falsos positivos en strings cortos/inofensivos y para no perder
# rendimiento con regex sobre cuerpos gigantes.
_SQL_INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("union_select", re.compile(
        r"union\s+(all\s+)?select", re.IGNORECASE)),
    ("stacked_queries", re.compile(
        r";\s*(drop|delete|insert|update|alter|truncate|exec|grant)\s",
        re.IGNORECASE)),
    ("or_1_equals_1", re.compile(
        r"(\bor\b|\band\b)\s+['\"]?\s*\d+\s*=\s*['\"]?\s*\d+", re.IGNORECASE)),
    ("comments", re.compile(r"--\s*$|/\*.*\*/", re.IGNORECASE)),
    ("xp_cmdshell", re.compile(r"xp_cmdshell|exec\s*s\s*\(\s*['\"]",
                               re.IGNORECASE)),
    ("sleep_benchmark", re.compile(
        r"\b(sleep|benchmark|pg_sleep|waitfor\s+delay)\s*\(", re.IGNORECASE)),
]

_MAX_SCAN_CHARS = 4096  # escaneamos solo el inicio del cuerpo


def detect_sql_injection(text: str) -> Optional[str]:
    """Devuelve el nombre del patrón SQLi detectado, o ``None``.

    Escanea una ventana acotada del texto para acotar coste. No es un
    analizador completo (un WAF de verdad iría aparte), pero atrapa los
    payloads más comunes de forma barata.
    """
    if not text:
        return None
    scan = text[:_MAX_SCAN_CHARS]
    for name, pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(scan):
            return name
    return None


# ---------------------------------------------------------------------------
# Detección XSS
# ---------------------------------------------------------------------------
_XSS_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("script_tag", re.compile(
        r"<\s*/?\s*script[\s>]", re.IGNORECASE)),
    ("event_handler", re.compile(
        r"\bon\w+\s*=\s*(['\"]?)\s*(alert|eval|javascript|document\.|location\.)",
        re.IGNORECASE)),
    ("javascript_proto", re.compile(
        r"javascript\s*:\s*", re.IGNORECASE)),
    ("iframe_object", re.compile(
        r"<\s*(iframe|object|embed|link|meta)[\s>]", re.IGNORECASE)),
    ("srcdoc", re.compile(r"srcdoc\s*=", re.IGNORECASE)),
    ("data_uri_js", re.compile(
        r"data\s*:\s*text/html[^>]*(base64)?\s*[,]", re.IGNORECASE)),
]


def detect_xss(text: str) -> Optional[str]:
    """Devuelve el nombre del patrón XSS detectado, o ``None``."""
    if not text:
        return None
    scan = text[:_MAX_SCAN_CHARS]
    for name, pattern in _XSS_PATTERNS:
        if pattern.search(scan):
            return name
    return None


# ---------------------------------------------------------------------------
# Validaciones individuales (stateless)
# ---------------------------------------------------------------------------
def validate_content_type(request: Request) -> Optional[str]:
    """Valida el Content-Type de peticiones con cuerpo.

    Devuelve ``None`` si OK, o un mensaje de error si el Content-Type no está
    permitido. Se aplica solo a métodos que normalmente llevan cuerpo.
    """
    if request.method in ("GET", "HEAD", "OPTIONS", "DELETE"):
        return None
    ct = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ct:
        return None  # sin body declarado — se deja pasar
    if ct in _ALLOWED_CONTENT_TYPES:
        return None
    return (
        f"Unsupported Content-Type '{ct}'. Allowed: "
        f"{', '.join(_ALLOWED_CONTENT_TYPES)}."
    )


async def validate_request_size(request: Request,
                                max_bytes: Optional[int] = None) -> Optional[str]:
    """Valida el tamaño del cuerpo (Content-Length y chunked).

    Devuelve ``None`` si OK, o mensaje si excede el máximo.
    """
    if max_bytes is None:
        max_bytes = _get_max_bytes()
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                return (
                    f"Request body too large. Maximum allowed size is "
                    f"{max_bytes} bytes ({max_bytes // (1024 * 1024)} MB)."
                )
        except ValueError:
            pass  # malformado — deja que el handler decida
    else:
        # Transfer-Encoding: chunked (sin Content-Length) — leer con techo.
        try:
            body = await request.body()
            if len(body) > max_bytes:
                return (
                    f"Request body too large. Maximum allowed size is "
                    f"{max_bytes} bytes ({max_bytes // (1024 * 1024)} MB)."
                )
        except Exception:  # noqa: BLE001
            return None
    return None


def validate_request_content(request: Request, body_text: Optional[str] = None) -> List[str]:
    """Escanea el cuerpo en busca de SQLi / XSS.

    Devuelve lista de errores (vacía si limpio). ``body_text`` permite pasar
    el texto ya leído (evita doble lectura en el middleware).
    """
    errors: List[str] = []
    text = (body_text or "").strip()
    if not text:
        return errors
    sqli = detect_sql_injection(text)
    if sqli:
        errors.append(f"Request body contains suspicious SQL pattern: {sqli}.")
    xss = detect_xss(text)
    if xss:
        errors.append(f"Request body contains suspicious script pattern: {xss}.")
    return errors


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Valida Content-Type, tamaño de cuerpo y contenido (SQLi/XSS)."""

    def __init__(self, app, max_bytes: Optional[int] = None,
                 enable_content_scan: bool = True) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes or _get_max_bytes()
        self._enable_content_scan = enable_content_scan
        self._enabled = (
            os.environ.get("B2B_REQUEST_VALIDATION", "on").lower() != "off"
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # 1) Content-Type
        ct_error = validate_content_type(request)
        if ct_error:
            return JSONResponse(status_code=415, content={"detail": ct_error})

        # 2) Tamaño
        size_error = await validate_request_size(request,
                                                 max_bytes=self._max_bytes)
        if size_error:
            return JSONResponse(status_code=413, content={"detail": size_error})

        # 3) Contenido (SQLi / XSS) — solo si hay cuerpo y está habilitado
        if self._enable_content_scan and request.method not in (
            "GET", "HEAD", "OPTIONS"
        ):
            # Leer el cuerpo una vez. Reemplazamos la stream recibida para que
            # el handler posterior pueda releerla sin perder el contenido.
            try:
                raw = await request.body()
            except Exception:  # noqa: BLE001
                raw = b""
            if raw:
                # Se intenta decodificar como UTF-8; si falla, se asume binario
                # y se omite el escaneo de texto (no aplicable a uploads).
                try:
                    text = raw.decode("utf-8", errors="ignore")
                except Exception:  # noqa: BLE001
                    text = ""
                content_errors = validate_request_content(request, text)
                if content_errors:
                    return JSONResponse(
                        status_code=422,
                        content={"detail": content_errors},
                    )
                # Reponer el cuerpo para el handler downstream.
                async def _receive():
                    return {"type": "http.request", "body": raw,
                            "more_body": False}
                request._receive = _receive  # type: ignore[attr-defined]

        return await call_next(request)


def install_request_validator(app, max_bytes: Optional[int] = None,
                              enable_content_scan: bool = True) -> None:
    """Instala el middleware de validación de peticiones sobre ``app``."""
    app.add_middleware(
        RequestValidationMiddleware,
        max_bytes=max_bytes,
        enable_content_scan=enable_content_scan,
    )
