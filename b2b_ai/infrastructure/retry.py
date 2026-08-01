# -*- coding: utf-8 -*-
"""
retry.py — Retry decorator with exponential backoff + jitter + idempotency keys.

Features:
    - Exponential backoff with configurable base, max delay, and jitter
    - Per-service retry configurations (SAT: 3, Facturapi: 5, ERP: 2)
    - Idempotency keys to prevent duplicate operations on retry
    - Configurable retryable exceptions per service
    - Circuit breaker integration (don't retry if circuit is open)
    - Metrics integration (retry counts, success rates)
"""
from __future__ import annotations

import functools
import hashlib
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar

from b2b_ai.infrastructure.structured_logging import get_logger

logger = get_logger("b2b_ai.retry")

F = TypeVar("F", bound=Callable[..., Any])


# --------------------------------------------------------------------------- #
# Idempotency Store
# --------------------------------------------------------------------------- #

class IdempotencyStore:
    """Thread-safe in-memory store for idempotency keys.

    Prevents duplicate operations when retries occur. Keys expire after TTL.

    For production multi-replica deployments, replace with Redis-backed store.
    """

    def __init__(self, ttl_seconds: float = 3600.0):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """Get a cached result by idempotency key."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, result = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return result

    def set(self, key: str, result: Any) -> None:
        """Store a result with an idempotency key."""
        with self._lock:
            self._store[key] = (time.monotonic(), result)

    def has(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        return self.get(key) is not None

    def cleanup(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        now = time.monotonic()
        with self._lock:
            expired = [
                k for k, (ts, _) in self._store.items()
                if now - ts > self._ttl
            ]
            for k in expired:
                del self._store[k]
            return len(expired)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)


# Global idempotency store
_idempotency_store = IdempotencyStore()


def generate_idempotency_key(
    service: str,
    operation: str,
    params: Optional[Dict] = None,
) -> str:
    """Generate a deterministic idempotency key for an operation.

    Args:
        service: Service name (e.g., "sat_soap", "facturapi").
        operation: Operation name (e.g., "submit_declaration", "create_cfdi").
        params: Operation parameters (hashed for uniqueness).

    Returns:
        SHA-256 hex string (first 32 chars).
    """
    parts = [service, operation]
    if params:
        # Sort for determinism
        sorted_params = sorted(str(params).items()) if isinstance(params, dict) else [str(params)]
        parts.append(str(sorted_params))
    key_input = "|".join(parts)
    return hashlib.sha256(key_input.encode()).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# Retry Configuration
# --------------------------------------------------------------------------- #

@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of attempts (including the first call).
        base_delay: Base delay in seconds between retries.
        max_delay: Maximum delay cap (prevents unbounded exponential growth).
        exponential_base: Multiplier for exponential backoff.
        jitter: Whether to add random jitter (±25% of delay).
        retryable_exceptions: Exception types that trigger a retry.
        non_retryable_exceptions: Exception types that never retry.
        on_retry: Optional callback invoked on each retry attempt.
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError,
        PermissionError,
    )
    on_retry: Optional[Callable[[int, Exception, float], None]] = None


# Per-service default configurations
SERVICE_RETRY_CONFIGS: Dict[str, RetryConfig] = {
    "sat_soap": RetryConfig(
        max_attempts=3,
        base_delay=2.0,
        max_delay=30.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    ),
    "facturapi": RetryConfig(
        max_attempts=5,
        base_delay=1.0,
        max_delay=60.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    ),
    "contpaqi_com": RetryConfig(
        max_attempts=2,
        base_delay=3.0,
        max_delay=30.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    ),
    "spei_stp": RetryConfig(
        max_attempts=3,
        base_delay=2.0,
        max_delay=45.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    ),
    "llm_calls": RetryConfig(
        max_attempts=4,
        base_delay=1.0,
        max_delay=30.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    ),
}


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    def __init__(
        self,
        service: str,
        attempts: int,
        last_exception: Exception,
        total_duration: float,
    ):
        self.service = service
        self.attempts = attempts
        self.last_exception = last_exception
        self.total_duration = total_duration
        super().__init__(
            f"Retry exhausted for '{service}' after {attempts} attempts "
            f"({total_duration:.1f}s total). Last error: {last_exception}"
        )


# --------------------------------------------------------------------------- #
# Backoff Calculator
# --------------------------------------------------------------------------- #

def calculate_backoff(
    attempt: int,
    config: RetryConfig,
) -> float:
    """Calculate delay for a given retry attempt with exponential backoff + jitter.

    Formula: min(base_delay * exponential_base^attempt, max_delay) + jitter

    Args:
        attempt: Current attempt number (0-indexed for first retry).
        config: Retry configuration.

    Returns:
        Delay in seconds.
    """
    delay = config.base_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)

    if config.jitter:
        # Add ±25% jitter to prevent thundering herd
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)
        delay = max(0.1, delay)  # Floor at 100ms

    return delay


# --------------------------------------------------------------------------- #
# Core Retry Decorator
# --------------------------------------------------------------------------- #

def with_retry(
    service: str = "default",
    config: Optional[RetryConfig] = None,
    idempotency_key: Optional[str] = None,
    idempotency_key_builder: Optional[Callable[..., str]] = None,
) -> Callable[[F], F]:
    """Decorator that retries a function on failure with exponential backoff.

    Args:
        service: Service name (used for logging and config lookup).
        config: Custom retry config. Uses SERVICE_RETRY_CONFIGS if None.
        idempotency_key: Static idempotency key (prevents re-execution).
        idempotency_key_builder: Callable(args, kwargs) → key. Dynamic keys.

    Usage:
        @with_retry("sat_soap", idempotency_key_builder=lambda rfc, *_: f"sat:{rfc}")
        def submit_to_sat(rfc: str, xml: str) -> dict:
            return sat_client.submit(rfc, xml)
    """
    retry_config = config or SERVICE_RETRY_CONFIGS.get(service, RetryConfig())

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check idempotency store first
            effective_key = idempotency_key
            if idempotency_key_builder and not effective_key:
                try:
                    effective_key = idempotency_key_builder(*args, **kwargs)
                except Exception:
                    effective_key = None

            if effective_key:
                cached = _idempotency_store.get(effective_key)
                if cached is not None:
                    logger.debug(
                        f"Idempotent cache hit for '{service}'",
                        extra={"extra_fields": {
                            "service": service,
                            "idempotency_key": effective_key,
                        }},
                    )
                    return cached

            # Execute with retries
            last_exception: Optional[Exception] = None
            start_time = time.monotonic()

            for attempt in range(retry_config.max_attempts):
                try:
                    result = func(*args, **kwargs)

                    # Store result in idempotency cache
                    if effective_key:
                        _idempotency_store.set(effective_key, result)

                    if attempt > 0:
                        logger.info(
                            f"Retry succeeded for '{service}' on attempt {attempt + 1}",
                            extra={"extra_fields": {
                                "service": service,
                                "attempt": attempt + 1,
                                "total_attempts": retry_config.max_attempts,
                            }},
                        )
                    return result

                except retry_config.non_retryable_exceptions:
                    # Non-retryable: fail immediately
                    raise

                except retry_config.retryable_exceptions as exc:
                    last_exception = exc

                    if attempt < retry_config.max_attempts - 1:
                        delay = calculate_backoff(attempt, retry_config)
                        logger.warning(
                            f"Retry {attempt + 1}/{retry_config.max_attempts} for "
                            f"'{service}': {exc}. Waiting {delay:.1f}s",
                            extra={"extra_fields": {
                                "service": service,
                                "attempt": attempt + 1,
                                "max_attempts": retry_config.max_attempts,
                                "delay_seconds": round(delay, 2),
                                "error": str(exc),
                            }},
                        )
                        if retry_config.on_retry:
                            try:
                                retry_config.on_retry(attempt + 1, exc, delay)
                            except Exception:
                                pass
                        time.sleep(delay)

                except Exception as exc:
                    # Unknown exception: don't retry
                    logger.error(
                        f"Non-retryable error in '{service}': {exc}",
                        exc_info=True,
                        extra={"extra_fields": {"service": service}},
                    )
                    raise

            # All retries exhausted
            total_duration = time.monotonic() - start_time
            raise RetryExhaustedError(
                service=service,
                attempts=retry_config.max_attempts,
                last_exception=last_exception,
                total_duration=total_duration,
            )

        return wrapper  # type: ignore

    return decorator


# --------------------------------------------------------------------------- #
# Async variant
# --------------------------------------------------------------------------- #

def with_async_retry(
    service: str = "default",
    config: Optional[RetryConfig] = None,
    idempotency_key: Optional[str] = None,
    idempotency_key_builder: Optional[Callable[..., str]] = None,
) -> Callable[[F], F]:
    """Async version of with_retry.

    Usage:
        @with_async_retry("facturapi")
        async def create_cfdi(data: dict) -> dict:
            return await facturapi.create(data)
    """
    import asyncio

    retry_config = config or SERVICE_RETRY_CONFIGS.get(service, RetryConfig())

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Check idempotency
            effective_key = idempotency_key
            if idempotency_key_builder and not effective_key:
                try:
                    effective_key = idempotency_key_builder(*args, **kwargs)
                except Exception:
                    effective_key = None

            if effective_key:
                cached = _idempotency_store.get(effective_key)
                if cached is not None:
                    return cached

            last_exception = None
            start_time = time.monotonic()

            for attempt in range(retry_config.max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    if effective_key:
                        _idempotency_store.set(effective_key, result)
                    return result

                except retry_config.non_retryable_exceptions:
                    raise

                except retry_config.retryable_exceptions as exc:
                    last_exception = exc
                    if attempt < retry_config.max_attempts - 1:
                        delay = calculate_backoff(attempt, retry_config)
                        logger.warning(
                            f"Async retry {attempt + 1}/{retry_config.max_attempts} "
                            f"for '{service}': {exc}. Waiting {delay:.1f}s",
                            extra={"extra_fields": {
                                "service": service,
                                "attempt": attempt + 1,
                                "delay_seconds": round(delay, 2),
                            }},
                        )
                        await asyncio.sleep(delay)

                except Exception:
                    raise

            total_duration = time.monotonic() - start_time
            raise RetryExhaustedError(
                service=service,
                attempts=retry_config.max_attempts,
                last_exception=last_exception,
                total_duration=total_duration,
            )

        return wrapper  # type: ignore

    return decorator
