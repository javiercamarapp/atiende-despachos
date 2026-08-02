# -*- coding: utf-8 -*-
"""
openapi_docs.py — Enterprise OpenAPI Documentation Enhancement.

Adds to the auto-generated OpenAPI spec:
  - Complete error response schemas per endpoint
  - Authentication flow documentation
  - Webhook payload examples
  - Mexican fiscal domain examples
  - Security scheme definitions

Usage:
    from b2b_ai.api.openapi_docs import install_openapi_docs
    install_openapi_docs(app)
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def _get_error_response_schemas() -> Dict[str, Any]:
    """Common error response schemas."""
    return {
        "ErrorResponse": {
            "type": "object",
            "required": ["error"],
            "properties": {
                "error": {
                    "type": "object",
                    "required": ["code", "type", "message", "trace_id"],
                    "properties": {
                        "code": {
                            "type": "integer",
                            "description": "Numeric error code by category",
                            "example": 6001,
                        },
                        "type": {
                            "type": "string",
                            "description": "Error type identifier",
                            "example": "validation_error",
                        },
                        "message": {
                            "type": "string",
                            "description": "Human-readable error message (no PII)",
                            "example": "Request validation failed.",
                        },
                        "trace_id": {
                            "type": "string",
                            "description": "Unique trace ID for debugging",
                            "example": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                        },
                        "details": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string"},
                                    "message": {"type": "string"},
                                    "type": {"type": "string"},
                                },
                            },
                            "description": "Validation error details",
                        },
                    },
                }
            },
        },
        "RateLimitResponse": {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "integer", "example": 7001},
                        "type": {"type": "string", "example": "rate_limit_exceeded"},
                        "message": {"type": "string", "example": "Too many requests. Please retry later."},
                        "retry_after_seconds": {"type": "integer", "example": 42},
                        "trace_id": {"type": "string"},
                    },
                }
            },
        },
    }


def _get_security_schemes() -> Dict[str, Any]:
    """OpenAPI security scheme definitions."""
    return {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "API key for authentication. Each tenant has a unique key. "
                "The service key (set via B2B_API_KEY env var) has unrestricted access. "
                "Keys are resolved against the `api_keys` table (multi-tenant) "
                "or the B2B_API_KEY environment variable (single-tenant)."
            ),
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "JWT Bearer token for user authentication. "
                "Obtain via POST /auth/login. Tokens expire after 30 minutes (configurable). "
                "Use the refresh token endpoint to obtain new access tokens."
            ),
        },
        "IdempotencyKey": {
            "type": "apiKey",
            "in": "header",
            "name": "Idempotency-Key",
            "description": (
                "Idempotency key (UUID recommended) for write endpoints. "
                "Ensures that retrying a request with the same key returns the "
                "cached response without re-executing the mutation. "
                "Cached for 24 hours. Returns 422 if reused with a different body."
            ),
        },
    }


def _get_example_responses() -> Dict[str, Any]:
    """Example responses for common scenarios."""
    return {
        "health": {
            "summary": "Healthy service",
            "value": {
                "status": "ok",
                "service": "b2b-ai",
                "version": "1.0.0",
                "backend": "postgresql",
                "schema_version": 7,
                "invoices": 1500,
                "tenants": 5,
                "uptime_seconds": 86400,
                "total_requests": 50000,
            },
        },
        "auth_error": {
            "summary": "Authentication error",
            "value": {
                "error": {
                    "code": 1002,
                    "type": "auth_error",
                    "message": "API key inválida o no autorizada.",
                    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                }
            },
        },
        "rate_limited": {
            "summary": "Rate limited",
            "value": {
                "error": {
                    "code": 7001,
                    "type": "rate_limit_exceeded",
                    "message": "Too many requests. Please retry later.",
                    "retry_after_seconds": 42,
                    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                }
            },
        },
        "cfdi_processed": {
            "summary": "CFDI processed successfully",
            "value": {
                "result": {
                    "archivo": "invoice_001.xml",
                    "validacion": {"ok": True, "requires_human_review": False},
                    "clasificacion": {
                        "categoria": "gasto_operativo",
                        "confianza": 0.95,
                    },
                    "erp": {"poliza": "DIARIO-001", "status": "synced"},
                    "insertado": True,
                    "datos": {
                        "total": 15000.00,
                        "emisor_rfc": "DESP820101AB1",
                    },
                    "invoice_id": 42,
                }
            },
        },
        "webhook_payload": {
            "summary": "Webhook event payload",
            "value": {
                "event": "invoice_processed",
                "timestamp": "2026-01-15T10:30:00Z",
                "tenant_id": 1,
                "data": {
                    "invoice_id": 42,
                    "rfc": "DESP820101AB1",
                    "total": 15000.00,
                    "categoria": "gasto_operativo",
                },
            },
        },
    }


def _custom_openapi(app: FastAPI) -> Dict[str, Any]:
    """Generate enhanced OpenAPI spec."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        contact=app.contact,
    )

    # Add security schemes
    openapi_schema.setdefault("components", {})
    openapi_schema["components"]["securitySchemes"] = _get_security_schemes()

    # Add error response schemas
    openapi_schema["components"].setdefault("schemas", {})
    openapi_schema["components"]["schemas"].update(_get_error_response_schemas())

    # Add examples
    openapi_schema["components"]["examples"] = _get_example_responses()

    # Add security requirement globally
    openapi_schema["security"] = [{"ApiKeyAuth": []}]

    # Enhance endpoint documentation
    _enhance_endpoints(openapi_schema)

    app.openapi_schema = openapi_schema
    return openapi_schema


def _enhance_endpoints(schema: Dict[str, Any]) -> None:
    """Add error responses to all endpoints in the spec."""
    error_responses = {
        "401": {
            "description": "Authentication required or API key invalid",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                    "example": _get_example_responses()["auth_error"]["value"],
                }
            },
        },
        "403": {
            "description": "Tenant blocked or insufficient permissions",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                }
            },
        },
        "429": {
            "description": "Rate limit exceeded",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/RateLimitResponse"},
                    "example": _get_example_responses()["rate_limited"]["value"],
                }
            },
            "headers": {
                "X-RateLimit-Limit": {
                    "schema": {"type": "integer"},
                    "description": "Maximum requests per window",
                },
                "X-RateLimit-Remaining": {
                    "schema": {"type": "integer"},
                    "description": "Remaining requests in current window",
                },
                "X-RateLimit-Reset": {
                    "schema": {"type": "integer"},
                    "description": "Unix timestamp when the window resets",
                },
                "Retry-After": {
                    "schema": {"type": "integer"},
                    "description": "Seconds until the rate limit resets",
                },
            },
        },
        "500": {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                }
            },
        },
    }

    # Common headers
    common_headers = {
        "X-Trace-Id": {
            "schema": {"type": "string"},
            "description": "Unique request trace ID for debugging",
        },
        "X-API-Version": {
            "schema": {"type": "string"},
            "description": "API version used for this request",
        },
    }

    for path, methods in schema.get("paths", {}).items():
        for method, operation in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                operation.setdefault("responses", {})
                # Add error responses (only if not already present)
                for code, resp in error_responses.items():
                    if code not in operation["responses"]:
                        operation["responses"][code] = resp

                # Add common headers
                for resp in operation["responses"].values():
                    resp.setdefault("headers", {})
                    for hname, hdef in common_headers.items():
                        if hname not in resp["headers"]:
                            resp["headers"][hname] = hdef


def install_openapi_docs(app: FastAPI) -> None:
    """Install enhanced OpenAPI documentation."""
    # Override the default openapi function
    app.openapi = lambda: _custom_openapi(app)

    # Update app metadata
    app.description = (
        "# Likida AI Enterprise — API Documentation\n\n"
        "## Authentication\n"
        "All endpoints (except `/health` and `/api/v1/leads`) require authentication "
        "via the `X-API-Key` header.\n\n"
        "### API Key Authentication\n"
        "```\n"
        'curl -H "X-API-Key: your-key" https://api.b2b-ai.local/api/v1/stats\n'
        "```\n\n"
        "### JWT Bearer Token (Auth endpoints)\n"
        "```\n"
        'curl -H "Authorization: Bearer eyJhbG..." https://api.b2b-ai.local/api/v1/stats\n'
        "```\n\n"
        "## Versioning\n"
        "The API supports simultaneous v1 and v2 endpoints:\n"
        "- `/api/v1/` — Legacy, deprecated (sunset: 2027-01-01)\n"
        "- `/api/v2/` — Current, recommended\n\n"
        "Use the `Accept-Version` header for version negotiation, or include "
        "the version in the URL path.\n\n"
        "## Rate Limiting\n"
        "Requests are rate-limited per tenant/endpoint. Check response headers:\n"
        "- `X-RateLimit-Limit` — Maximum requests per window\n"
        "- `X-RateLimit-Remaining` — Remaining requests\n"
        "- `X-RateLimit-Reset` — Window reset timestamp\n"
        "- `Retry-After` — Seconds to wait (on 429)\n\n"
        "## Idempotency\n"
        "Write endpoints accept an `Idempotency-Key` header (UUID recommended) "
        "to prevent duplicate mutations from network retries. Cached for 24 hours.\n\n"
        "## Error Handling\n"
        "All errors return structured JSON with:\n"
        "- Numeric error code (by category)\n"
        "- Error type identifier\n"
        "- Human-readable message (no PII)\n"
        "- Trace ID for debugging\n\n"
        "## Webhooks\n"
        "Register webhooks via `POST /api/v2/webhooks` to receive event "
        "notifications. Supported events:\n"
        "- `invoice_processed` — When a CFDI is processed\n"
        "- `batch_completed` — When a batch job finishes\n"
        "- `reconciliation_done` — When reconciliation completes\n"
    )


def get_openapi_tags() -> list:
    """Define OpenAPI tags with descriptions."""
    return [
        {"name": "health", "description": "Health checks and service status"},
        {"name": "invoices", "description": "CFDI invoice processing and management"},
        {"name": "stats", "description": "Aggregated statistics and metrics"},
        {"name": "system", "description": "System tools and configuration"},
        {"name": "crm", "description": "Lead management (public endpoint)"},
        {"name": "reconcile", "description": "Bank reconciliation"},
        {"name": "accounting", "description": "Electronic accounting (SAT)"},
        {"name": "payroll", "description": "Payroll calculation and CFDI generation"},
        {"name": "collections", "description": "Automated collections and reminders"},
        {"name": "contabilidad", "description": "Chart of accounts and journal entries"},
        {"name": "enterprise", "description": "v2 enterprise endpoints (batch, analytics, webhooks)"},
        {"name": "auth", "description": "Authentication and authorization"},
        {"name": "notifications", "description": "Notification channels and templates"},
        {"name": "billing", "description": "Subscription billing and payments"},
        {"name": "reports", "description": "Report generation and export"},
        {"name": "declarations", "description": "Tax declarations (DIOT, IVA, ISR)"},
        {"name": "nomina", "description": "Payroll processing and CFDI Nómina"},
    ]
