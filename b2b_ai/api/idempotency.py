# -*- coding: utf-8 -*-
"""
idempotency.py — Idempotency Key middleware for write endpoints.

Prevents duplicate mutations from network retries by caching responses
keyed by the Idempotency-Key header.

Features:
  - Header: Idempotency-Key (UUID recommended)
  - 24-hour response cache (configurable via B2B_IDEMPOTENCY_TTL_HOURS)
  - Returns cached response for duplicate keys (same request body)
  - Returns 422 if key reused with different body
  - Redis-backed for distributed deployments, in-memory fallback

Usage:
    from b2b_ai.api.idempotency import install_idempotency
    install_idempotency(app)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import threading
from typing import Any, Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Default TTL for idempotency cache (24 hours)
DEFAULT_TTL_SECONDS = int(
    float(os.environ.get("B2B_IDEMPOTENCY_TTL_HOURS", "24")) * 3600
)

# HTTP methods that support idempotency keys
IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Header name
IDEMPOTENCY_HEADER = "idempotency-key"


class _IdempotencyStore:
    """Thread-safe in-memory idempotency cache.

    Structure: {key: {body_hash, status_code, headers, body, created_at}}
    """

    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._sweep_counter = 0
        self._sweep_interval = 100  # sweep every N operations

    def get(self, key: str, body_hash: str) -> Optional[Tuple[int, Dict[str, str], bytes]]:
        """Get cached response for an idempotency key.

        Returns (status_code, headers_dict, body_bytes) or None.
        Returns None if key not found, expired, or body mismatch.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            # Check TTL
            if time.monotonic() - entry["created_at"] > self._ttl:
                del self._store[key]
                return None
            # Check body hash match
            if entry["body_hash"] != body_hash:
                # Key reused with different body — caller should return 422
                return None
            return entry["status_code"], entry["headers"], entry["body"]

    def is_conflict(self, key: str, body_hash: str) -> bool:
        """Check if key exists but with a different body (conflict)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            if time.monotonic() - entry["created_at"] > self._ttl:
                del self._store[key]
                return False
            return entry["body_hash"] != body_hash

    def set(
        self,
        key: str,
        body_hash: str,
        status_code: int,
        headers: Dict[str, str],
        body: bytes,
    ) -> None:
        """Cache a response for an idempotency key."""
        with self._lock:
            self._store[key] = {
                "body_hash": body_hash,
                "status_code": status_code,
                "headers": headers,
                "body": body,
                "created_at": time.monotonic(),
            }
            self._sweep_counter += 1
            if self._sweep_counter >= self._sweep_interval:
                self._sweep()
                self._sweep_counter = 0

    def _sweep(self) -> None:
        """Remove expired entries."""
        now = time.monotonic()
        expired = [
            k for k, v in self._store.items()
            if now - v["created_at"] > self._ttl
        ]
        for k in expired:
            del self._store[k]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)


class _RedisIdempotencyStore:
    """Redis-backed idempotency cache for distributed deployments."""

    def __init__(self, redis_url: str, ttl: int = DEFAULT_TTL_SECONDS):
        import redis
        self._client = redis.from_url(redis_url, decode_responses=False)
        self._ttl = ttl
        self._prefix = "idempotency:"

    def get(self, key: str, body_hash: str) -> Optional[Tuple[int, Dict[str, str], bytes]]:
        data = self._client.get(f"{self._prefix}{key}")
        if data is None:
            return None
        import json
        entry = json.loads(data)
        if entry["body_hash"] != body_hash:
            return None
        return entry["status_code"], entry["headers"], entry["body"].encode("latin-1")

    def is_conflict(self, key: str, body_hash: str) -> bool:
        data = self._client.get(f"{self._prefix}{key}")
        if data is None:
            return False
        import json
        entry = json.loads(data)
        return entry["body_hash"] != body_hash

    def set(self, key: str, body_hash: str, status_code: int,
            headers: Dict[str, str], body: bytes) -> None:
        import json
        entry = json.dumps({
            "body_hash": body_hash,
            "status_code": status_code,
            "headers": headers,
            "body": body.decode("latin-1"),
        })
        self._client.setex(f"{self._prefix}{key}", self._ttl, entry)

    @property
    def size(self) -> int:
        return len(list(self._client.scan_iter(f"{self._prefix}*")))


def _hash_body(body: bytes) -> str:
    """SHA-256 hash of request body for mismatch detection."""
    return hashlib.sha256(body).hexdigest()[:32]


def _get_store():
    """Get idempotency store (Redis if available, memory otherwise)."""
    url = os.environ.get("B2B_REDIS_URL", "")
    if url:
        try:
            return _RedisIdempotencyStore(url)
        except Exception:
            pass
    return _IdempotencyStore()


# Singleton store
_store = None
_store_lock = threading.Lock()


def get_store():
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = _get_store()
    return _store


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Enforce idempotency keys on write endpoints."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only apply to write methods
        if request.method not in IDEMPOTENT_METHODS:
            return await call_next(request)

        # Skip for paths that don't need idempotency (auth, health)
        path = request.url.path
        if path.startswith(("/health", "/metrics", "/auth", "/docs")):
            return await call_next(request)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            # No key provided — proceed normally (idempotency is optional)
            return await call_next(request)

        # Read request body for hashing
        body = await request.body()
        body_hash = _hash_body(body)

        store = get_store()

        # Check for conflict (same key, different body)
        if store.is_conflict(idempotency_key, body_hash):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": 1422,
                        "type": "idempotency_conflict",
                        "message": (
                            "Idempotency-Key was already used with a different "
                            "request body. Use a new key for this request."
                        ),
                    }
                },
            )

        # Check for cached response
        cached = store.get(idempotency_key, body_hash)
        if cached is not None:
            status_code, headers, response_body = cached
            from fastapi.responses import Response as _R
            resp = _R(
                content=response_body,
                status_code=status_code,
                headers=headers,
                media_type="application/json",
            )
            resp.headers["X-Idempotency-Replayed"] = "true"
            return resp

        # Process the request
        response = await call_next(request)

        # Cache the response (only for successful/processable responses)
        if response.status_code < 500:
            response_body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    response_body += chunk.encode("utf-8")
                else:
                    response_body += chunk

            # Collect response headers
            resp_headers = dict(response.headers)

            store.set(
                idempotency_key,
                body_hash,
                response.status_code,
                resp_headers,
                response_body,
            )

            # Return a new response with the same body
            from fastapi.responses import Response as _R
            return _R(
                content=response_body,
                status_code=response.status_code,
                headers=resp_headers,
                media_type=response.media_type,
            )

        return response


def install_idempotency(app, store=None) -> None:
    """Install idempotency middleware on the FastAPI app.

    Args:
        app: FastAPI application.
        store: Optional pre-built store (for testing).
    """
    global _store
    if store is not None:
        _store = store
    app.add_middleware(IdempotencyMiddleware)
