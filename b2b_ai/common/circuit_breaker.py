# -*- coding: utf-8 -*-
"""circuit_breaker.py — Circuit breaker pattern for external service calls.

States: closed (normal) -> open (failing, reject calls) -> half_open (test one call).
"""
from __future__ import annotations
import time
import threading
from typing import Callable, Any
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3,
                 recovery_timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        current_state = self.state
        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit '{self.name}' is OPEN. Retry after {self.recovery_timeout}s")
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN


class CircuitBreakerOpenError(Exception):
    pass


# Global circuit breakers for external services
_breakers: dict = {}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, **kwargs)
    return _breakers[name]
