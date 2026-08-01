# -*- coding: utf-8 -*-
"""
security_headers.py — Middleware de cabeceras de seguridad (FASE hardening).

Añade a TODAS las respuestas las cabeceras recomendadas por OWASP para
proteger el transporte y mitigar XSS / clickjacking / MIME-sniffing:

    Strict-Transport-Security  (HSTS)   — exige HTTPS
    X-Frame-Options                     — bloquea clickjacking (deny)
    X-Content-Type-Options:nosniff      — evita MIME-sniffing
    Referrer-Policy                     — no filtra la URL completa
    Content-Security-Policy             — restringe fuentes de script/frame/object

CSP pragmática: las SPAs del dashboard/portal usan JS inline (vanilla) y
Chart.js desde CDN (jsdelivr), así que se permiten 'unsafe-inline' y ese CDN,
pero se bloquea el framing (frame-ancestors 'none'), objetos embebidos
(object-src 'none') y base-uri. En producción puede endurecerse vía env
B2B_CSP (reemplaza la por defecto) cuando se eliminen los scripts inline.

La cabecera HSTS solo se envía cuando la petición llega por HTTPS (o cuando
B2B_HSTS_ALWAYS=true), para no degradar el desarrollo en HTTP local.
"""
from __future__ import annotations

import os

# CSP por defecto: mismo origen + JS inline (SPAs vanilla) + CDN de Chart.js.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def _is_https(scope) -> bool:
    """Detecta si la petición llegó por HTTPS (uvicorn pone el scheme en scope)."""
    try:
        scheme = scope.get("scheme", "")
        headers = dict(scope.get("headers", []))
        # uvicorn detrás de proxy: confiar en X-Forwarded-Proto solo si se
        # habilitó explícitamente (B2B_TRUST_PROXY=true).
        if os.environ.get("B2B_TRUST_PROXY", "").lower() == "true":
            fwd = headers.get(b"x-forwarded-proto", b"").decode("latin-1")
            if fwd:
                return fwd.startswith("https")
        return scheme == "https"
    except Exception:  # noqa: BLE001
        return False


class SecurityHeadersMiddleware:
    """ASGI middleware que inyecta cabeceras de seguridad en cada respuesta."""

    def __init__(self, app, csp: str = None, hsts_always: bool = False):
        self.app = app
        self.csp = csp or os.environ.get("B2B_CSP", "").strip() or _DEFAULT_CSP
        self.hsts_always = hsts_always or (
            os.environ.get("B2B_HSTS_ALWAYS", "").lower() == "true")
        # HSTS solo si hay HTTPS terminado en este proceso o se forzó.
        self.hsts_enabled = self.hsts_always or (
            os.environ.get("B2B_HSTS", "").lower() == "true")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                add = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy", self.csp.encode("latin-1")),
                ]
                # HSTS solo sobre HTTPS (evita que el navegador recuerde HSTS
                # y luego falle el desarrollo local por HTTP).
                if self.hsts_enabled and _is_https(scope):
                    add.append((b"strict-transport-security",
                                b"max-age=31536000; includeSubDomains; preload"))
                existing = {k.lower() for k, _ in headers}
                for k, v in add:
                    if k not in existing:
                        headers.append((k, v))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def install(app):
    """Añade el middleware de cabeceras de seguridad a la app FastAPI."""
    app.add_middleware(SecurityHeadersMiddleware)
    return app
