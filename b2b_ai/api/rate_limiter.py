# -*- coding: utf-8 -*-
"""
rate_limiter.py — Enterprise Distributed Rate Limiter.

Features:
  - Redis-backed sliding window (falls back to in-memory for dev/tests)
  - Configurable per endpoint, per tenant, per role
  - Standard rate limit headers: X-RateLimit-Limit, X-RateLimit-Remaining,
    X-RateLimit-Reset, Retry-After
  - 429 Too Many Requests with structured JSON error

Config (env vars):
  B2B_REDIS_URL              Redis connection string (default: in-memory)
  B2B_RATE_LIMIT_PER_MIN     Global default (default: 300)
  B2B_RATE_LIMIT_PER_TENANT  Per-tenant default (default: 600)

Usage:
    from b2b_ai.api.rate_limiter import install_enterprise_rate_limit
    install_enterprise_rate_limit(app, redis_url="redis://...")
"""
from __future__ import annotations

import os
import time
import threading
from collections import defaultdict
from typing import Any, Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


# ---------------------------------------------------------------------------
# Redis adapter (optional dependency)
# ---------------------------------------------------------------------------
class _RedisBackend:
    """Sliding window rate limiter backed by Redis sorted sets.

    Uses ZRANGEBYSCORE to prune old entries and ZCARD to count current window.
    Each key is a rate limit bucket (e.g. "rl:{tenant_id}:{endpoint}").
    """

    def __init__(self, redis_url: str):
        try:
            import redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
        except ImportError:
            raise RuntimeError(
                "redis package is required for distributed rate limiting. "
                "Install with: pip install redis"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to Redis at {redis_url}: {exc}"
            )

    def check_and_consume(
        self, key: str, limit: int, window_seconds: float
    ) -> Tuple[int, float]:
        """Check rate limit and consume one token.

        Returns (remaining, reset_timestamp).
        """
        now = time.time()
        window_start = now - window_seconds
        pipe = self._client.pipeline(True)
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Add current request
        pipe.zadd(key, {f"{now}:{id(threading.current_thread())}": now})
        # Count entries in window
        pipe.zcard(key)
        # Set TTL on the key
        pipe.expire(key, int(window_seconds) + 1)
        results = pipe.execute()
        count = results[2]
        remaining = max(0, limit - count)
        reset = now + window_seconds
        return remaining, reset

    def get_usage(self, key: str, window_seconds: float) -> int:
        """Get current usage count for a key."""
        now = time.time()
        window_start = now - window_seconds
        self._client.zremrangebyscore(key, 0, window_start)
        return self._client.zcard(key)

    def reset(self, key: str) -> None:
        self._client.delete(key)

    def health(self) -> bool:
        try:
            return self._client.ping()
        except Exception:
            return False


class _MemoryBackend:
    """In-memory sliding window rate limiter (single-node fallback)."""

    def __init__(self):
        self._hits: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def check_and_consume(
        self, key: str, limit: int, window_seconds: float
    ) -> Tuple[int, float]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            # Prune expired
            bucket[:] = [t for t in bucket if t > cutoff]
            remaining = max(0, limit - len(bucket) - 1)
            if len(bucket) >= limit:
                # Find when oldest entry expires
                reset = bucket[0] + window_seconds
                return remaining, reset
            bucket.append(now)
        reset = now + window_seconds
        return remaining, reset

    def get_usage(self, key: str, window_seconds: float) -> int:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            bucket[:] = [t for t in bucket if t > cutoff]
            return len(bucket)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def health(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Rate limit configuration
# ---------------------------------------------------------------------------
# Default limits. Overridable via env or per-tenant config.
DEFAULT_GLOBAL_LIMIT = int(os.environ.get("B2B_RATE_LIMIT_PER_MIN", "300"))
DEFAULT_TENANT_LIMIT = int(os.environ.get("B2B_RATE_LIMIT_PER_TENANT", "600"))
DEFAULT_WINDOW = 60.0  # seconds

# Endpoint-specific overrides: {path_pattern: limit_per_minute}
ENDPOINT_LIMITS: Dict[str, int] = {
    "/api/v1/leads": 10,              # Public, very strict
    "/api/v1/invoices/process": 60,   # Heavy processing
    "/api/v2/batch": 10,              # Expensive
    "/api/v1/payroll/calculate": 30,  # Moderate
}

# Role-specific multipliers (applied to the tenant limit)
ROLE_MULTIPLIERS: Dict[str, float] = {
    "admin": 2.0,
    "accountant": 1.0,
    "viewer": 0.5,
    "service": 5.0,  # API keys for integrations get higher limits
}

# Paths exempt from rate limiting (no auth, health checks, etc.)
EXEMPT_PREFIXES = (
    "/health", "/metrics", "/static", "/icons", "/manifest.json",
    "/sw.js", "/robots.txt", "/sitemap.xml", "/docs", "/openapi.json",
    "/redoc", "/favicon.ico",
)


def _get_backend(redis_url: Optional[str] = None):
    """Get rate limiter backend. Tries Redis, falls back to memory."""
    url = redis_url or os.environ.get("B2B_REDIS_URL", "")
    if url:
        try:
            return _RedisBackend(url)
        except RuntimeError:
            pass  # Fall back to in-memory
    return _MemoryBackend()


def _build_key(request: Request, tenant_id: Optional[int],
               endpoint_limit: Optional[int]) -> Tuple[str, int]:
    """Build the rate limit key and determine the effective limit.

    Key format: rl:{scope}:{identifier}
    Scope can be: tenant, ip, or global.
    """
    path = request.url.path

    # Determine effective limit
    limit = endpoint_limit or DEFAULT_GLOBAL_LIMIT

    # Build key based on tenant (preferred) or IP
    if tenant_id is not None:
        key = f"rl:tenant:{tenant_id}:{path}"
        limit = endpoint_limit or DEFAULT_TENANT_LIMIT
    else:
        # No tenant (public endpoints) — rate limit by IP
        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:ip:{client_ip}:{path}"
        limit = endpoint_limit or DEFAULT_GLOBAL_LIMIT

    return key, limit


def _get_endpoint_limit(path: str) -> Optional[int]:
    """Get endpoint-specific rate limit."""
    # Exact match first
    if path in ENDPOINT_LIMITS:
        return ENDPOINT_LIMITS[path]
    # Prefix match
    for pattern, limit in ENDPOINT_LIMITS.items():
        if path.startswith(pattern):
            return limit
    return None


def _get_role_multiplier(role: Optional[str]) -> float:
    """Get rate limit multiplier for a role."""
    if not role:
        return 1.0
    return ROLE_MULTIPLIERS.get(role, 1.0)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in EXEMPT_PREFIXES)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class EnterpriseRateLimitMiddleware(BaseHTTPMiddleware):
    """Enterprise rate limiter with Redis backend and per-tenant limits."""

    def __init__(self, app, backend=None, redis_url: Optional[str] = None):
        super().__init__(app)
        self._backend = backend or _get_backend(redis_url)
        self._enabled = (
            os.environ.get("B2B_RATE_LIMIT", "on").lower() != "off"
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if _is_exempt(path):
            return await call_next(request)

        # Extract tenant info from request state (set by auth middleware)
        # or from API key header for pre-auth rate limiting
        tenant_id = getattr(request.state, "tenant_id", None)
        role = getattr(request.state, "role", None)

        # Endpoint-specific limit
        endpoint_limit = _get_endpoint_limit(path)

        # Build key and base limit
        key, base_limit = _build_key(request, tenant_id, endpoint_limit)

        # Apply role multiplier
        multiplier = _get_role_multiplier(role)
        effective_limit = max(1, int(base_limit * multiplier))

        # Check rate limit
        remaining, reset_ts = self._backend.check_and_consume(
            key, effective_limit, DEFAULT_WINDOW
        )

        # If limit exceeded
        if remaining == 0 and self._backend.get_usage(key, DEFAULT_WINDOW) > effective_limit:
            retry_after = max(1, int(reset_ts - time.time()))
            from fastapi.responses import JSONResponse
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": 1429,
                        "type": "rate_limit_exceeded",
                        "message": "Too many requests. Please retry later.",
                        "retry_after_seconds": retry_after,
                    }
                },
            )
            _set_rate_limit_headers(
                response, effective_limit, 0, reset_ts, retry_after
            )
            return response

        # Process request and add headers to response
        response = await call_next(request)
        _set_rate_limit_headers(
            response, effective_limit, remaining, reset_ts
        )
        return response


def _set_rate_limit_headers(
    response: Response,
    limit: int,
    remaining: int,
    reset_ts: float,
    retry_after: Optional[int] = None,
) -> None:
    """Set standard rate limit headers on the response."""
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int(reset_ts))
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)


def install_enterprise_rate_limit(
    app, redis_url: Optional[str] = None, backend=None
) -> None:
    """Install enterprise rate limiting middleware.

    Args:
        app: FastAPI application.
        redis_url: Redis connection string. Falls back to env B2B_REDIS_URL.
        backend: Optional pre-built backend (for testing).
    """
    app.add_middleware(
        EnterpriseRateLimitMiddleware,
        backend=backend,
        redis_url=redis_url,
    )
