# -*- coding: utf-8 -*-
"""
errors.py — Enterprise Error Handling.

Structured JSON error responses with:
  - Numeric error codes by category (1xxx auth, 2xxx fiscal, 3xxx ERP, etc.)
  - Trace ID in every error response
  - No PII in error messages
  - Consistent format across all endpoints

Error code ranges:
  1000-1999  Authentication & Authorization
  2000-2999  Fiscal / CFDI / SAT
  3000-3999  ERP Integration
  4000-4999  Database & Storage
  5000-5999  External Services
  6000-6999  Validation & Input
  7000-7999  Rate Limiting & Quotas
  8000-8999  Webhook & Notifications
  9000-9999  Internal / System

Usage:
    from b2b_ai.api.errors import (
        install_error_handlers, EnterpriseError, raise_auth_error
    )
    install_error_handlers(app)
"""
from __future__ import annotations

import os
import re
import secrets
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Trace ID context variable
# ---------------------------------------------------------------------------
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Get the current request's trace ID."""
    return _trace_id_ctx.get("")


def set_trace_id(trace_id: str) -> str:
    """Set the trace ID for the current context. Returns the trace ID."""
    _trace_id_ctx.set(trace_id)
    return trace_id


def generate_trace_id() -> str:
    """Generate a new trace ID (UUID-like, short for headers)."""
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Error code registry
# ---------------------------------------------------------------------------
class ErrorCode:
    """Numeric error codes by category."""

    # 1xxx — Authentication & Authorization
    AUTH_MISSING_API_KEY = 1001
    AUTH_INVALID_API_KEY = 1002
    AUTH_TENANT_BLOCKED = 1003
    AUTH_TOKEN_EXPIRED = 1004
    AUTH_TOKEN_INVALID = 1005
    AUTH_PERMISSION_DENIED = 1006
    AUTH_RATE_LIMIT = 1007
    AUTH_VERSION_CONFLICT = 1008
    AUTH_VERSION_UNSUPPORTED = 1009

    # 2xxx — Fiscal / CFDI / SAT
    FISCAL_CFDI_INVALID = 2001
    FISCAL_CFDI_PARSE_ERROR = 2002
    FISCAL_CFDI_VALIDATION_FAILED = 2003
    FISCAL_RFC_INVALID = 2004
    FISCAL_RFC_CHECK_DIGIT = 2005
    FISCAL_CURP_INVALID = 2006
    FISCAL_NSS_INVALID = 2007
    FISCAL_CLABE_INVALID = 2008
    FISCAL_XML_GENERATION = 2009
    FISCAL_SAT_REJECTED = 2010
    FISCAL_FIEL_REQUIRED = 2011
    FISCAL_PERIOD_INVALID = 2012

    # 3xxx — ERP Integration
    ERP_CONNECTION_FAILED = 3001
    ERP_AUTH_FAILED = 3002
    ERP_SYNC_FAILED = 3003
    ERP_MAPPING_ERROR = 3004
    ERP_POLIZA_FAILED = 3005
    ERP_CATALOG_ERROR = 3006

    # 4xxx — Database & Storage
    DB_CONNECTION_FAILED = 4001
    DB_QUERY_FAILED = 4002
    DB_CONSTRAINT_VIOLATION = 4003
    DB_MIGRATION_PENDING = 4004
    DB_POOL_EXHAUSTED = 4005

    # 5xxx — External Services
    EXT_SERVICE_UNAVAILABLE = 5001
    EXT_SERVICE_TIMEOUT = 5002
    EXT_WEBHOOK_DELIVERY_FAILED = 5003
    EXT_EMAIL_FAILED = 5004

    # 6xxx — Validation & Input
    VALIDATION_FAILED = 6001
    VALIDATION_MISSING_FIELD = 6002
    VALIDATION_INVALID_FORMAT = 6003
    VALIDATION_OUT_OF_RANGE = 6004
    VALIDATION_FILE_TOO_LARGE = 6005
    VALIDATION_INVALID_FILE_TYPE = 6006
    VALIDATION_PATH_TRAVERSAL = 6007
    VALIDATION_IDEMPOTENCY_CONFLICT = 6008

    # 7xxx — Rate Limiting & Quotas
    RATE_LIMIT_EXCEEDED = 7001
    RATE_LIMIT_TENANT = 7002
    QUOTA_EXCEEDED = 7003

    # 8xxx — Webhook & Notifications
    WEBHOOK_SUBSCRIPTION_EXISTS = 8001
    WEBHOOK_INVALID_URL = 8002
    WEBHOOK_DELIVERY_FAILED = 8003
    NOTIFICATION_CHANNEL_ERROR = 8004

    # 9xxx — Internal / System
    INTERNAL_ERROR = 9001
    INTERNAL_TIMEOUT = 9002
    INTERNAL_NOT_IMPLEMENTED = 9003
    INTERNAL_SERVICE_DEGRADED = 9004


# ---------------------------------------------------------------------------
# Enterprise Error Exception
# ---------------------------------------------------------------------------
class EnterpriseError(Exception):
    """Structured enterprise error with code, type, and safe message."""

    def __init__(
        self,
        code: int,
        message: str,
        error_type: str = "error",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.code = code
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(message)

    def to_response(self, trace_id: Optional[str] = None) -> JSONResponse:
        """Convert to a JSONResponse."""
        body = {
            "error": {
                "code": self.code,
                "type": self.error_type,
                "message": self.message,
                "trace_id": trace_id or get_trace_id() or generate_trace_id(),
            }
        }
        if self.details:
            body["error"]["details"] = self.details
        resp_headers = dict(self.headers)
        resp_headers["X-Trace-Id"] = body["error"]["trace_id"]
        return JSONResponse(
            status_code=self.status_code,
            content=body,
            headers=resp_headers,
        )


# ---------------------------------------------------------------------------
# PII scrubbing
# ---------------------------------------------------------------------------
_PII_PATTERNS = [
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]"),
    # Phone numbers (Mexican format)
    (re.compile(r"\+?\d{2}[- ]?\d{4}[- ]?\d{4}"), "[PHONE_REDACTED]"),
    # RFC (could be PII)
    (re.compile(r"[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}"), "[RFC_REDACTED]"),
    # Credit card numbers
    (re.compile(r"\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}"), "[CARD_REDACTED]"),
    # IP addresses (in error messages only — headers are ok)
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP_REDACTED]"),
]


def scrub_pii(message: str) -> str:
    """Remove PII patterns from error messages."""
    for pattern, replacement in _PII_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------
def raise_auth_error(
    code: int = ErrorCode.AUTH_INVALID_API_KEY,
    message: str = "Authentication failed.",
    status_code: int = 401,
    **kwargs,
):
    raise EnterpriseError(
        code=code, message=message, error_type="auth_error",
        status_code=status_code, **kwargs,
    )


def raise_fiscal_error(
    code: int = ErrorCode.FISCAL_CFDI_INVALID,
    message: str = "Fiscal validation failed.",
    **kwargs,
):
    raise EnterpriseError(
        code=code, message=message, error_type="fiscal_error",
        status_code=422, **kwargs,
    )


def raise_validation_error(
    code: int = ErrorCode.VALIDATION_FAILED,
    message: str = "Validation failed.",
    **kwargs,
):
    raise EnterpriseError(
        code=code, message=message, error_type="validation_error",
        status_code=422, **kwargs,
    )


def raise_not_found(message: str = "Resource not found.", **kwargs):
    raise EnterpriseError(
        code=6009, message=message, error_type="not_found",
        status_code=404, **kwargs,
    )


def raise_forbidden(message: str = "Access denied.", **kwargs):
    raise EnterpriseError(
        code=ErrorCode.AUTH_PERMISSION_DENIED, message=message,
        error_type="forbidden", status_code=403, **kwargs,
    )


# ---------------------------------------------------------------------------
# Install global error handlers
# ---------------------------------------------------------------------------
def install_error_handlers(app: FastAPI) -> None:
    """Install global error handlers on the FastAPI app.

    Ensures ALL errors return structured JSON, never raw HTML or plain text.
    """

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        """Inject trace ID into every request/response."""
        # Use existing X-Trace-Id header or generate a new one
        trace_id = request.headers.get("x-trace-id") or generate_trace_id()
        set_trace_id(trace_id)

        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(EnterpriseError)
    async def enterprise_error_handler(request: Request, exc: EnterpriseError):
        """Handle structured enterprise errors."""
        trace_id = get_trace_id() or generate_trace_id()
        return exc.to_response(trace_id)

    @app.exception_handler(422)
    async def validation_error_handler(request: Request, exc):
        """Convert FastAPI validation errors to structured format."""
        trace_id = get_trace_id() or generate_trace_id()

        # Extract validation details (Pydantic v2)
        details = []
        if hasattr(exc, "errors"):
            for err in exc.errors():
                details.append({
                    "field": " → ".join(str(l) for l in err.get("loc", [])),
                    "message": err.get("msg", ""),
                    "type": err.get("type", ""),
                })
        elif hasattr(exc, "detail"):
            details = [{"message": str(exc.detail)}]

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.VALIDATION_FAILED,
                    "type": "validation_error",
                    "message": "Request validation failed.",
                    "trace_id": trace_id,
                    "details": details,
                }
            },
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        trace_id = get_trace_id() or generate_trace_id()
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": 6009,
                    "type": "not_found",
                    "message": "The requested resource was not found.",
                    "trace_id": trace_id,
                }
            },
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc):
        trace_id = get_trace_id() or generate_trace_id()
        return JSONResponse(
            status_code=405,
            content={
                "error": {
                    "code": 6010,
                    "type": "method_not_allowed",
                    "message": "The HTTP method is not allowed for this endpoint.",
                    "trace_id": trace_id,
                }
            },
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception):
        trace_id = get_trace_id() or generate_trace_id()
        # Log the full traceback server-side (never expose to client)
        _is_dev = os.environ.get("B2B_ENV", "").lower() in ("dev", "development", "test", "local")
        if _is_dev:
            import sys
            traceback.print_exc(file=sys.stderr)

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR,
                    "type": "internal_error",
                    "message": "An unexpected error occurred. Please try again later.",
                    "trace_id": trace_id,
                }
            },
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        """Catch-all for unhandled exceptions."""
        trace_id = get_trace_id() or generate_trace_id()
        _is_dev = os.environ.get("B2B_ENV", "").lower() in ("dev", "development", "test", "local")
        if _is_dev:
            import sys
            traceback.print_exc(file=sys.stderr)

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR,
                    "type": "internal_error",
                    "message": "An unexpected error occurred.",
                    "trace_id": trace_id,
                }
            },
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(EnterpriseError)
    async def enterprise_http_exception_handler(request: Request, exc: EnterpriseError):
        return exc.to_response()
