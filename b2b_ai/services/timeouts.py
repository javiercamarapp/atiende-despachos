# -*- coding: utf-8 -*-
"""
timeouts.py — Timeout wrappers for external service calls.

Prevents worker starvation when SAT, LLM, or ERP services hang.
"""
from __future__ import annotations

import concurrent.futures
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger("b2b_ai.timeouts")

# Default timeouts per service (seconds)
TIMEOUT_SAT = 10
TIMEOUT_LLM = 30
TIMEOUT_ERP = 15
TIMEOUT_EMAIL = 5


class ServiceTimeoutError(Exception):
    """Raised when an external service call exceeds its timeout."""


def with_timeout(func: Callable, timeout: float,
                 service_name: str = "external") -> Callable:
    """Wrap a synchronous function with a timeout.

    Uses a thread pool executor to enforce the timeout. If the function
    doesn't complete within `timeout` seconds, raises ServiceTimeoutError.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise ServiceTimeoutError(
                    f"Llamada a {service_name} excedió timeout de {timeout}s"
                )
    return wrapper
