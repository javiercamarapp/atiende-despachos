# -*- coding: utf-8 -*-
"""
graceful_shutdown.py — Fortune 500 graceful shutdown handler.

Handles SIGTERM/SIGINT to:
    1. Stop accepting new requests (set draining flag)
    2. Wait for active workers to complete (configurable drain period)
    3. Close database connections
    4. Flush log buffers
    5. Exit cleanly

Compatible with Kubernetes, ECS, Docker, and systemd lifecycle signals.
"""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from b2b_ai.infrastructure.structured_logging import get_logger

logger = get_logger("b2b_ai.shutdown")


# --------------------------------------------------------------------------- #
# Shutdown state
# --------------------------------------------------------------------------- #

@dataclass
class ShutdownState:
    """Track shutdown progress."""
    is_draining: bool = False
    is_shutdown: bool = False
    drain_started_at: Optional[float] = None
    shutdown_completed_at: Optional[float] = None
    active_requests: int = 0
    shutdown_reason: str = ""
    cleanup_tasks_completed: List[str] = field(default_factory=list)
    cleanup_tasks_failed: List[str] = field(default_factory=list)


# Global singleton
_shutdown_state = ShutdownState()
_shutdown_lock = threading.Lock()


def is_draining() -> bool:
    """Check if the application is draining (no new requests should be accepted)."""
    return _shutdown_state.is_draining


def is_shutdown() -> bool:
    """Check if shutdown is complete."""
    return _shutdown_state.is_shutdown


def get_shutdown_state() -> Dict[str, Any]:
    """Get current shutdown state (for health endpoints)."""
    with _shutdown_lock:
        return {
            "is_draining": _shutdown_state.is_draining,
            "is_shutdown": _shutdown_state.is_shutdown,
            "active_requests": _shutdown_state.active_requests,
            "drain_elapsed_seconds": (
                round(time.monotonic() - _shutdown_state.drain_started_at, 1)
                if _shutdown_state.drain_started_at
                else None
            ),
            "shutdown_reason": _shutdown_state.shutdown_reason,
        }


# --------------------------------------------------------------------------- #
# Request tracking
# --------------------------------------------------------------------------- #

class RequestTracker:
    """Track active requests for drain period management.

    Usage:
        tracker = RequestTracker()

        # In middleware:
        with tracker.track():
            response = await call_next(request)
    """

    def __init__(self):
        self._active = 0
        self._lock = threading.Lock()

    def track(self):
        """Context manager to track a request's lifetime."""
        return _RequestTrackerContext(self)

    def increment(self) -> None:
        with self._lock:
            self._active += 1
            _shutdown_state.active_requests = self._active

    def decrement(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            _shutdown_state.active_requests = self._active

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    def wait_for_zero(self, timeout: float = 30.0) -> bool:
        """Wait until all active requests complete.

        Returns True if all requests completed, False on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active_count == 0:
                return True
            time.sleep(0.1)
        return self.active_count == 0


class _RequestTrackerContext:
    """Context manager for request tracking."""

    def __init__(self, tracker: RequestTracker):
        self._tracker = tracker

    def __enter__(self):
        if is_draining():
            raise RuntimeError("Service is draining, not accepting new requests")
        self._tracker.increment()
        return self

    def __exit__(self, *exc):
        self._tracker.decrement()
        return False


# Global request tracker
request_tracker = RequestTracker()


# --------------------------------------------------------------------------- #
# Cleanup tasks
# --------------------------------------------------------------------------- #

@dataclass
class CleanupTask:
    """A cleanup task to run during shutdown."""
    name: str
    fn: Callable[[], None]
    timeout: float = 10.0  # Max seconds to wait for this task
    critical: bool = False  # If True, log ERROR on failure; otherwise WARNING


class ShutdownManager:
    """Manages graceful shutdown lifecycle.

    Registers cleanup tasks and handles signals.
    """

    def __init__(
        self,
        drain_timeout: float = 30.0,
        total_shutdown_timeout: float = 60.0,
    ):
        self.drain_timeout = drain_timeout
        self.total_shutdown_timeout = total_shutdown_timeout
        self._cleanup_tasks: List[CleanupTask] = []
        self._original_handlers: Dict[int, Any] = {}
        self._registered = False

    def register_cleanup(
        self,
        name: str,
        fn: Callable[[], None],
        timeout: float = 10.0,
        critical: bool = False,
    ) -> None:
        """Register a cleanup task to run during shutdown.

        Args:
            name: Task name (for logging).
            fn: Callable to execute.
            timeout: Max seconds to wait.
            critical: If True, failure is logged as ERROR.
        """
        self._cleanup_tasks.append(
            CleanupTask(name=name, fn=fn, timeout=timeout, critical=critical)
        )

    def install_signal_handlers(self) -> None:
        """Install SIGTERM and SIGINT handlers."""
        if self._registered:
            return

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"Received {sig_name}, initiating graceful shutdown...")
            self._initiate_shutdown(reason=sig_name)

        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _handle_signal)

        atexit.register(self._on_exit)
        self._registered = True

    def _initiate_shutdown(self, reason: str = "unknown") -> None:
        """Begin the shutdown sequence."""
        with _shutdown_lock:
            if _shutdown_state.is_draining:
                return  # Already shutting down
            _shutdown_state.is_draining = True
            _shutdown_state.drain_started_at = time.monotonic()
            _shutdown_state.shutdown_reason = reason

        logger.info(
            "Shutdown initiated — draining active requests",
            extra={"extra_fields": {
                "drain_timeout": self.drain_timeout,
                "active_requests": request_tracker.active_count,
            }},
        )

        # Phase 1: Wait for active requests to complete
        self._drain_phase()

        # Phase 2: Run cleanup tasks
        self._cleanup_phase()

        # Phase 3: Final flush
        self._flush_phase()

        with _shutdown_lock:
            _shutdown_state.is_shutdown = True
            _shutdown_state.shutdown_completed_at = time.monotonic()

        total = time.monotonic() - _shutdown_state.drain_started_at
        logger.info(
            f"Graceful shutdown complete ({total:.1f}s)",
            extra={"extra_fields": {
                "total_seconds": round(total, 2),
                "completed_tasks": _shutdown_state.cleanup_tasks_completed,
                "failed_tasks": _shutdown_state.cleanup_tasks_failed,
            }},
        )

    def _drain_phase(self) -> None:
        """Wait for active requests to complete."""
        logger.info(
            f"Drain phase: waiting up to {self.drain_timeout}s for "
            f"{request_tracker.active_count} active requests"
        )
        completed = request_tracker.wait_for_zero(self.drain_timeout)
        if not completed:
            logger.warning(
                f"Drain timeout: {request_tracker.active_count} requests still active"
            )
        else:
            logger.info("All active requests completed")

    def _cleanup_phase(self) -> None:
        """Run all registered cleanup tasks."""
        for task in self._cleanup_tasks:
            try:
                # Run with timeout (best-effort in single-thread)
                start = time.monotonic()
                task.fn()
                elapsed = time.monotonic() - start
                if elapsed > task.timeout:
                    logger.warning(
                        f"Cleanup task '{task.name}' exceeded timeout "
                        f"({elapsed:.1f}s > {task.timeout}s)"
                    )
                _shutdown_state.cleanup_tasks_completed.append(task.name)
                logger.debug(f"Cleanup task '{task.name}' completed ({elapsed:.1f}s)")
            except Exception as exc:
                _shutdown_state.cleanup_tasks_failed.append(task.name)
                level = logging.ERROR if task.critical else logging.WARNING
                logger.log(
                    level,
                    f"Cleanup task '{task.name}' failed: {exc}",
                    exc_info=True,
                )

    def _flush_phase(self) -> None:
        """Flush log buffers."""
        logging.shutdown()

    def _on_exit(self) -> None:
        """Called via atexit as a last resort."""
        if not _shutdown_state.is_shutdown:
            logger.warning("atexit handler called without prior signal — forcing cleanup")
            self._initiate_shutdown(reason="atexit")


# --------------------------------------------------------------------------- #
# FastAPI integration middleware
# --------------------------------------------------------------------------- #

def create_drain_middleware(shutdown_manager: ShutdownManager):
    """Create a FastAPI/Starlette middleware that rejects requests during drain.

    Usage:
        from b2b_ai.infrastructure.graceful_shutdown import (
            shutdown_manager, create_drain_middleware
        )
        app.add_middleware(BaseHTTPMiddleware, dispatch=create_drain_middleware(shutdown_manager))
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def drain_dispatch(request: Request, call_next):
        if is_draining():
            # Allow health checks even during drain (for k8s)
            if request.url.path in ("/health/live", "/health/ready"):
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service is shutting down",
                    "retry_after": 5,
                },
                headers={"Retry-After": "5"},
            )

        with request_tracker.track():
            return await call_next(request)

    return drain_dispatch


# --------------------------------------------------------------------------- #
# Singleton
# --------------------------------------------------------------------------- #

shutdown_manager = ShutdownManager()
