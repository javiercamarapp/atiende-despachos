# -*- coding: utf-8 -*-
"""
rate_limiter.py — Token-bucket rate limiting middleware para la API FastAPI.

Algoritmo: **token bucket** con recarga continua. Cada bucket tiene capacidad
``capacity`` (ráfaga máxima) y recarga ``rate`` tokens por segundo. Un bucket
se identifica por una clave ``(scope, identifier, endpoint_class)``.

Clases de endpoint configurables (default):

    auth     -> 5 /min      (login, register, refresh — antibrute-force)
    api      -> 100 /min    (endpoints REST normales)
    webhooks -> 30 /min     (entrega/recepción de webhooks)

Backend: **Redis** (distribuido, multi-réplica) con fallback automático a
**memoria** (single-node / dev / tests) si Redis no está disponible.

Respuesta al exceder el límite:

    HTTP 429 Too Many Requests
    Headers: Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining,
             X-RateLimit-Reset

Usage (dentro de create_app):

    from b2b_ai.middleware.rate_limiter import install_rate_limit
    install_rate_limit(app, redis_url=os.environ.get("B2B_REDIS_URL"))
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


# ---------------------------------------------------------------------------
# Configuración de límites por clase de endpoint
# ---------------------------------------------------------------------------
# {endpoint_class: {"limit": tokens, "window": segundos}}
DEFAULT_LIMITS: Dict[str, dict] = {
    "auth": {"limit": 5, "window": 60},
    "api": {"limit": 100, "window": 60},
    "webhooks": {"limit": 30, "window": 60},
}

# Asociación prefix-de-ruta -> clase de endpoint. La más específica (prefijo
# más largo) gana; si ninguna coincide se usa la clase "api".
ENDPOINT_CLASS_BY_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("/api/v1/auth", "auth"),
    ("/api/v1/webhooks", "webhooks"),
    ("/webhooks", "webhooks"),
)

# Rutas exentas (healthcheck, estáticos, docs) — no se limitan.
EXEMPT_PREFIXES: Tuple[str, ...] = (
    "/health", "/metrics", "/static", "/icons", "/manifest.json",
    "/sw.js", "/robots.txt", "/sitemap.xml", "/docs", "/openapi.json",
    "/redoc", "/favicon.ico",
)


def _endpoint_class(path: str) -> str:
    """Devuelve la clase de endpoint para una ruta (prefijo más largo gana)."""
    best = ""
    best_class = "api"
    for prefix, cls in ENDPOINT_CLASS_BY_PREFIX:
        if path.startswith(prefix) and len(prefix) > len(best):
            best = prefix
            best_class = cls
    return best_class


def _resolve_limit(limit: Dict[str, int]) -> Tuple[int, float]:
    """Normaliza {limit, window} -> (tokens, rate_per_second)."""
    tokens = max(1, int(limit.get("limit", 100)))
    window = max(1.0, float(limit.get("window", 60)))
    rate = tokens / window
    return tokens, rate


# ---------------------------------------------------------------------------
# Token bucket backends
# ---------------------------------------------------------------------------
class TokenBucket:
    """Bucket de tokens no-bloqueante (estructura de datos pura, testeable).

    ``capacity``: tokens máximos (ráfaga). ``rate``: tokens/seg recargados.
    Devuelve ``(allowed, tokens_remaining, seconds_until_full)``.
    """

    __slots__ = ("capacity", "rate", "tokens", "last_refill")

    def __init__(self, capacity: float, rate: float,
                 now: Optional[float] = None) -> None:
        self.capacity = float(capacity)
        self.rate = float(rate)
        self.tokens = float(capacity)
        self.last_refill = now if now is not None else time.monotonic()

    def refill(self, now: float) -> None:
        """Recarga tokens según el tiempo transcurrido (capped a capacity)."""
        if now <= self.last_refill:
            return
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def try_consume(self, now: Optional[float] = None) -> Tuple[bool, float, float]:
        """Intenta consumir un token.

        Returns:
            (allowed, remaining, seconds_until_full)
        """
        now = now if now is not None else time.monotonic()
        self.refill(now)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            remaining = self.tokens
            until_full = (self.capacity - self.tokens) / self.rate \
                if self.rate > 0 else 0.0
            return True, remaining, until_full
        until_full = (1.0 - self.tokens) / self.rate if self.rate > 0 else 0.0
        return False, self.tokens, until_full

    @property
    def available(self) -> float:
        return max(0.0, self.tokens)


class _MemoryBackend:
    """Backend token-bucket en memoria (single-node / dev / tests)."""

    def __init__(self) -> None:
        self._buckets: "OrderedDict[str, TokenBucket]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_buckets = 100_000  # techo anti-DoS de memoria

    def check_and_consume(self, key: str, capacity: int, rate: float):
        """Consume un token del bucket. Returns (allowed, remaining, until_full)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                # Poda oportunista cuando crecemos demasiado.
                if len(self._buckets) >= self._max_buckets:
                    self._buckets.popitem(last=False)
                bucket = TokenBucket(capacity, rate, now=now)
                self._buckets[key] = bucket
            allowed, remaining, until_full = bucket.try_consume(now)
            return allowed, remaining, until_full

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


class _RedisBackend:
    """Backend token-bucket distribuido sobre Redis.

    Usa un script Lua atómico por clave. Token bucket no tiene un equivalente
    nativo en Redis, así que se implementa con contador + last_refill: los
    tokens se recargan sobre la marcha calculando el tiempo transcurrido.
    """

    LUA = """
local tokens = tonumber(redis.call('GET', KEYS[1]) or '-1')
local last = tonumber(redis.call('GET', KEYS[2]) or '-1')
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local rate = tonumber(ARGV[3])
if tokens < 0 or last < 0 then
    tokens = capacity
    last = now
end
local elapsed = now - last
tokens = math.min(capacity, tokens + elapsed * rate)
local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end
redis.call('SET', KEYS[1], tokens, 'EX', math.ceil(capacity / rate) + 1)
redis.call('SET', KEYS[2], now, 'EX', math.ceil(capacity / rate) + 1)
return {allowed, tokens, (capacity - tokens) / rate}
"""

    def __init__(self, redis_url: str) -> None:
        import redis  # import tardío: depende opcional
        self._client = redis.from_url(redis_url, decode_responses=False)
        self._client.ping()  # falla si no hay conexión -> se usa memoria
        self._script = self._client.register_script(self.LUA)

    def check_and_consume(self, key: str, capacity: int, rate: float):
        now = time.time()
        res = self._script(
            keys=[f"rl:tb:tokens:{key}", f"rl:tb:last:{key}"],
            args=[now, capacity, rate],
        )
        allowed, tokens, until_full = bool(res[0]), float(res[1]), float(res[2])
        return allowed, tokens, until_full

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            return  # borrar todo requiere scan — no se usa en producción
        try:
            self._client.delete(f"rl:tb:tokens:{key}", f"rl:tb:last:{key}")
        except Exception:  # noqa: BLE001
            pass


def _get_backend(redis_url: Optional[str] = None):
    """Devuelve backend Redis si está disponible, si no el de memoria."""
    url = redis_url or os.environ.get("B2B_REDIS_URL", "")
    if url:
        try:
            return _RedisBackend(url)
        except Exception:  # noqa: BLE001 — fallback a memoria
            pass
    return _MemoryBackend()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware de rate limiting por token bucket, por clase de endpoint.

    Aplica un bucket por ``(identificador, endpoint_class)``. El identificador
    es, en orden de preferencia: API key (``X-API-Key``), ``Authorization``,
    o IP del cliente. Así un usuario autenticado comparte límite entre sus
    peticiones aunque roten de IP, y un atacante sin credenciales queda
    acotado por IP.
    """

    def __init__(self, app, backend=None, redis_url: Optional[str] = None,
                 limits: Optional[Dict[str, dict]] = None) -> None:
        super().__init__(app)
        self._backend = backend or _get_backend(redis_url)
        self._limits = limits or DEFAULT_LIMITS
        self._enabled = (
            os.environ.get("B2B_RATE_LIMIT", "on").lower() != "off"
        )

    def _identifier(self, request: Request) -> str:
        key = request.headers.get("x-api-key") or request.headers.get("authorization")
        if key:
            # Acotar longitud para no abusar de la memoria/Redis.
            return key[:128]
        if request.client:
            return f"ip:{request.client.host}"
        return "unknown"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        cls = _endpoint_class(path)
        capacity, rate = _resolve_limit(self._limits.get(cls, self._limits["api"]))
        key = f"{self._identifier(request)}:{cls}"

        allowed, remaining, until_full = self._backend.check_and_consume(
            key, capacity, rate
        )

        if not allowed:
            retry_after = max(1, int(until_full))
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded. Max {capacity} requests "
                        f"per window for {cls} endpoints."
                    ),
                    "error": {
                        "code": 1429,
                        "type": "rate_limit_exceeded",
                        "endpoint_class": cls,
                        "limit": capacity,
                    },
                },
            )
            _set_headers(response, capacity, 0, retry_after)
            return response

        response = await call_next(request)
        # remaining se reporta como entero techo (tokens enteros disponibles).
        _set_headers(response, capacity, max(0, int(remaining)), None)
        return response


def _set_headers(response: Response, limit: int, remaining: int,
                 retry_after: Optional[int]) -> None:
    """Escribe los headers estándar de rate limiting."""
    now = time.time()
    window = DEFAULT_LIMITS["api"]["window"]
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int(now + window))
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)


def install_rate_limit(app, redis_url: Optional[str] = None, backend=None,
                       limits: Optional[Dict[str, dict]] = None) -> None:
    """Instala el middleware de rate limiting sobre ``app``.

    Args:
        app: aplicación FastAPI.
        redis_url: conexión Redis (default: env ``B2B_REDIS_URL``).
        backend: backend pre-construido (para tests).
        limits: override de límites por clase de endpoint.
    """
    app.add_middleware(
        RateLimitMiddleware,
        backend=backend,
        redis_url=redis_url,
        limits=limits,
    )
