# -*- coding: utf-8 -*-
"""middleware.py — Request size limit middleware for OOM prevention.

Blocks incoming requests whose Content-Length exceeds a configurable threshold
(default 10 MB) to prevent denial-of-service via oversized payloads.

Health-check endpoints (/health, /health/detailed) are exempted from the
check to keep liveness probes lightweight.

Usage (inside create_app):
    from b2b_ai.api.middleware import install_request_size_limit
    install_request_size_limit(app)
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

# Default 10 MB limit.  Overridable via B2B_MAX_REQUEST_SIZE_MB env var.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# Paths exempt from the size check.
_SIZE_EXEMPT_PATHS: tuple[str, ...] = ("/health",)


def _get_max_bytes() -> int:
    """Resolve the configured max request size in bytes."""
    raw = os.environ.get("B2B_MAX_REQUEST_SIZE_MB")
    if raw:
        try:
            mb = int(raw)
            if mb > 0:
                return mb * 1024 * 1024
        except ValueError:
            pass
    return _DEFAULT_MAX_BYTES


def install_request_size_limit(app, max_bytes: Optional[int] = None) -> None:
    """Register request-size-limit middleware on *app*.

    The middleware checks the ``Content-Length`` header (when present) and
    returns **413 Request Entity Too Large** if the declared size exceeds
    *max_bytes* (default 10 MB, overridable via ``B2B_MAX_REQUEST_SIZE_MB``).

    GET / HEAD / OPTIONS requests without a body are always allowed
    regardless of Content-Length.
    """
    _limit = max_bytes or _get_max_bytes()

    @app.middleware("http")
    async def _request_size_limit_mw(request: Request, call_next):
        path = request.url.path

        # Exempt health-check endpoints.
        if path in _SIZE_EXEMPT_PATHS or path.startswith("/health/"):
            return await call_next(request)

        # Methods that typically carry no body are always allowed.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                # Malformed Content-Length — let the downstream handler decide.
                return await call_next(request)

            if size > _limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed size is {_limit} bytes "
                            f"({_limit // (1024 * 1024)} MB)."
                        ),
                    },
                )
        else:
            # VULN-17: Transfer-Encoding: chunked bypasses Content-Length.
            # Read the body with a size limit to catch oversized chunked payloads.
            body = await request.body()
            if len(body) > _limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed size is {_limit} bytes "
                            f"({_limit // (1024 * 1024)} MB)."
                        ),
                    },
                )

        return await call_next(request)
