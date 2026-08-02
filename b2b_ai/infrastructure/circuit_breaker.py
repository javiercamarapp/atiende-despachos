# -*- coding: utf-8 -*-
"""
circuit_breaker.py — Circuit Breaker pattern for external service resilience.

States:
    CLOSED    → normal operation, requests flow through
    OPEN      → circuit tripped, requests fail immediately with fallback
    HALF_OPEN → testing recovery, limited requests allowed through

Protected services:
    - SAT SOAP (fiscal authority)
    - Facturapi API (CFDI generation)
    - CONTPAQi COM (ERP integration)
    - SPEI STP (bank transfers)
    - LLM calls (AI processing)

Each service gets its own circuit breaker with independent configuration.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar

from b2b_ai.infrastructure.structured_logging import get_logger

logger = get_logger("b2b_ai.circuit_breaker")

F = TypeVar("F", bound=Callable[..., Any])


# --------------------------------------------------------------------------- #
# States
# --------------------------------------------------------------------------- #

class CircuitState(enum.Enum):
    """Circuit breaker states."""
    CLOSED = "closed"           # Normal: requests flow through
    OPEN = "open"               # Tripped: fail immediately
    HALF_OPEN = "half_open"     # Testing: limited requests


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class CircuitBreakerConfig:
    """Configuration for a circuit breaker instance.

    Attributes:
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait before trying half-open.
        half_open_max_calls: Max calls allowed in half-open state.
        success_threshold: Consecutive successes in half-open to close.
        excluded_exceptions: Exception types that don't count as failures
            (e.g., validation errors that are not service failures).
    """
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    success_threshold: int = 2
    excluded_exceptions: tuple = (ValueError, TypeError, KeyError)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class CircuitBreakerError(Exception):
    """Raised when circuit is open and request is rejected."""
    def __init__(self, service_name: str, state: CircuitState):
        self.service_name = service_name
        self.state = state
        super().__init__(
            f"Circuit breaker for '{service_name}' is {state.value}. "
            f"Request rejected."
        )


class CircuitBreakerOpenError(CircuitBreakerError):
    """Raised when circuit is OPEN."""
    pass


class CircuitBreakerHalfOpenLimitError(CircuitBreakerError):
    """Raised when half-open call limit is exceeded."""
    pass


# --------------------------------------------------------------------------- #
# Core Circuit Breaker
# --------------------------------------------------------------------------- #

class CircuitBreaker:
    """Thread-safe circuit breaker implementation.

    Usage:
        cb = CircuitBreaker("sat_soap", config=CircuitBreakerConfig(...))

        @cb.protect
        def call_sat_ws(data):
            return sat_client.send(data)

        # Or manual:
        with cb:
            result = sat_client.send(data)
    """

    def __init__(
        self,
        service_name: str,
        config: Optional[CircuitBreakerConfig] = None,
        fallback: Optional[Callable[..., Any]] = None,
    ):
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()
        self.fallback = fallback

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.RLock()

        # Metrics
        self._total_requests = 0
        self._total_failures = 0
        self._total_rejected = 0
        self._total_fallbacks = 0
        self._state_transitions: list = []

    # -- Properties -- #

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning OPEN → HALF_OPEN if timeout elapsed."""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time is not None
                and time.monotonic() - self._last_failure_time >= self.config.recovery_timeout
            ):
                self._transition_to(CircuitState.HALF_OPEN)
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics."""
        with self._lock:
            return {
                "service": self.service_name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_requests": self._total_requests,
                "total_failures": self._total_failures,
                "total_rejected": self._total_rejected,
                "total_fallbacks": self._total_fallbacks,
                "last_failure_time": self._last_failure_time,
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "recovery_timeout": self.config.recovery_timeout,
                    "half_open_max_calls": self.config.half_open_max_calls,
                },
            }

    # -- State transitions -- #

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state (must be called with lock held)."""
        old_state = self._state
        self._state = new_state
        self._state_transitions.append({
            "from": old_state.value,
            "to": new_state.value,
            "time": time.monotonic(),
        })
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        logger.info(
            f"Circuit breaker '{self.service_name}' state: "
            f"{old_state.value} → {new_state.value}",
            extra={"extra_fields": {
                "service": self.service_name,
                "old_state": old_state.value,
                "new_state": new_state.value,
            }},
        )

    def _record_success(self) -> None:
        """Record a successful call (must be called with lock held)."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _record_failure(self, exc: Exception) -> None:
        """Record a failed call (must be called with lock held)."""
        if isinstance(exc, self.config.excluded_exceptions):
            return

        with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open → back to open
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    # -- Context manager -- #

    def __enter__(self):
        self._total_requests += 1
        current = self.state  # Triggers auto-transition check

        with self._lock:
            if current == CircuitState.OPEN:
                self._total_rejected += 1
                if self.fallback:
                    self._total_fallbacks += 1
                    # Signal that fallback should be used
                    raise CircuitBreakerOpenError(self.service_name, current)
                raise CircuitBreakerOpenError(self.service_name, current)

            if current == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self._total_rejected += 1
                    raise CircuitBreakerHalfOpenLimitError(
                        self.service_name, current
                    )
                self._half_open_calls += 1

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with self._lock:
            if exc_type is not None:
                self._record_failure(exc_val)
            else:
                self._record_success()
        return False  # Don't suppress exceptions

    # -- Decorator -- #

    def protect(self, func: F) -> F:
        """Decorator to protect a function with this circuit breaker.

        Usage:
            @cb.protect
            def call_service(data):
                return service.process(data)
        """
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                with self:
                    return func(*args, **kwargs)
            except (CircuitBreakerOpenError, CircuitBreakerHalfOpenLimitError):
                if self.fallback:
                    logger.warning(
                        f"Circuit '{self.service_name}' open — using fallback",
                        extra={"extra_fields": {
                            "service": self.service_name,
                            "fallback": self.fallback.__name__,
                        }},
                    )
                    return self.fallback(*args, **kwargs)
                raise

        return wrapper  # type: ignore

    # -- Manual control -- #

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0

    def trip(self) -> None:
        """Manually trip the circuit breaker to OPEN state."""
        with self._lock:
            self._transition_to(CircuitState.OPEN)
            self._last_failure_time = time.monotonic()


# --------------------------------------------------------------------------- #
# Registry: all circuit breakers for the application
# --------------------------------------------------------------------------- #

class CircuitBreakerRegistry:
    """Registry of all circuit breakers in the application.

    Provides centralized management, monitoring, and health reporting.
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def register(
        self,
        service_name: str,
        config: Optional[CircuitBreakerConfig] = None,
        fallback: Optional[Callable] = None,
    ) -> CircuitBreaker:
        """Register a circuit breaker for a service."""
        with self._lock:
            if service_name not in self._breakers:
                self._breakers[service_name] = CircuitBreaker(
                    service_name, config=config, fallback=fallback
                )
            return self._breakers[service_name]

    def get(self, service_name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by service name."""
        with self._lock:
            return self._breakers.get(service_name)

    def all_metrics(self) -> Dict[str, Any]:
        """Get metrics for all registered circuit breakers."""
        with self._lock:
            return {
                name: cb.metrics
                for name, cb in self._breakers.items()
            }

    def all_states(self) -> Dict[str, str]:
        """Get current state of all circuit breakers."""
        with self._lock:
            return {
                name: cb.state.value
                for name, cb in self._breakers.items()
            }

    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED."""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()

    def any_open(self) -> bool:
        """Check if any circuit breaker is in OPEN state."""
        with self._lock:
            return any(
                cb.state == CircuitState.OPEN
                for cb in self._breakers.values()
            )


# --------------------------------------------------------------------------- #
# Default registry + service configurations
# --------------------------------------------------------------------------- #

# Default configurations for each protected service
SERVICE_CONFIGS: Dict[str, CircuitBreakerConfig] = {
    "sat_soap": CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=60.0,       # SAT can be slow to recover
        half_open_max_calls=2,
        success_threshold=2,
    ),
    "facturapi": CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=30.0,
        half_open_max_calls=3,
        success_threshold=2,
    ),
    "contpaqi_com": CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=45.0,       # COM objects need time to recover
        half_open_max_calls=2,
        success_threshold=2,
    ),
    "spei_stp": CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=30.0,
        half_open_max_calls=3,
        success_threshold=2,
    ),
    "llm_calls": CircuitBreakerConfig(
        failure_threshold=8,          # LLMs can be flaky
        recovery_timeout=20.0,
        half_open_max_calls=5,
        success_threshold=3,
    ),
}

# Global registry singleton
registry = CircuitBreakerRegistry()


def get_or_create_breaker(
    service_name: str,
    config: Optional[CircuitBreakerConfig] = None,
    fallback: Optional[Callable] = None,
) -> CircuitBreaker:
    """Get or create a circuit breaker for a service.

    Uses default config for known services if none provided.
    """
    existing = registry.get(service_name)
    if existing:
        return existing
    cfg = config or SERVICE_CONFIGS.get(service_name, CircuitBreakerConfig())
    return registry.register(service_name, config=cfg, fallback=fallback)
