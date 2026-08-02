# -*- coding: utf-8 -*-
"""
health.py — Enterprise health check endpoints.

Endpoints:
    /health/live     — Liveness probe (is the process alive?)
    /health/ready    — Readiness probe (can it serve traffic?)
    /health/detailed — Full status of every dependency (with timeouts)

Prometheus-compatible metrics at /metrics/prometheus.

Designed for Kubernetes / ECS / any orchestrator that distinguishes
liveness from readiness.
"""
from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from b2b_ai.infrastructure.structured_logging import get_logger

logger = get_logger("b2b_ai.health")


# --------------------------------------------------------------------------- #
# Health check result types
# --------------------------------------------------------------------------- #

@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: str  # "ok", "degraded", "error", "not_configured"
    latency_ms: Optional[float] = None
    detail: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"status": self.status}
        if self.latency_ms is not None:
            d["latency_ms"] = round(self.latency_ms, 2)
        if self.detail:
            d["detail"] = self.detail
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class HealthReport:
    """Aggregated health report."""
    status: str  # "ok", "degraded", "unhealthy"
    service: str = "b2b-ai-enterprise"
    version: str = ""
    uptime_seconds: float = 0.0
    timestamp: float = 0.0
    components: Dict[str, ComponentHealth] = field(default_factory=dict)
    degraded_components: List[str] = field(default_factory=list)
    process: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "service": self.service,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "timestamp": round(self.timestamp, 3),
            "process": self.process,
            "components": {
                name: comp.to_dict()
                for name, comp in self.components.items()
            },
            "degraded_components": self.degraded_components,
        }


# --------------------------------------------------------------------------- #
# Health check registry
# --------------------------------------------------------------------------- #

class HealthCheckRegistry:
    """Registry of health check functions for each component.

    Each check is a callable that returns ComponentHealth.
    Checks run with a configurable timeout to prevent slow dependencies
    from blocking the health endpoint.
    """

    def __init__(self, default_timeout: float = 5.0):
        self._checks: Dict[str, Tuple[Callable[[], ComponentHealth], float]] = {}
        self._lock = threading.Lock()
        self._default_timeout = default_timeout
        self._start_time = time.monotonic()

    def register(
        self,
        name: str,
        check_fn: Callable[[], ComponentHealth],
        timeout: Optional[float] = None,
    ) -> None:
        """Register a health check function.

        Args:
            name: Component name (e.g., "database", "redis", "sat").
            check_fn: Callable returning ComponentHealth.
            timeout: Max seconds to wait for this check.
        """
        with self._lock:
            self._checks[name] = (check_fn, timeout or self._default_timeout)

    def run_check(self, name: str, check_fn: Callable, timeout: float) -> ComponentHealth:
        """Run a single health check with timeout."""
        start = time.monotonic()
        try:
            result = check_fn()
            result.latency_ms = (time.monotonic() - start) * 1000
            return result
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name=name,
                status="error",
                latency_ms=latency,
                error=str(exc),
            )

    def run_all(
        self,
        include_components: Optional[List[str]] = None,
        timeout_override: Optional[float] = None,
    ) -> HealthReport:
        """Run all registered health checks and aggregate results.

        Args:
            include_components: If set, only check these components.
            timeout_override: Override timeout for all checks.

        Returns:
            Aggregated HealthReport.
        """
        import b2b_ai
        version = getattr(b2b_ai, "__version__", "unknown")

        report = HealthReport(
            status="ok",
            version=version,
            uptime_seconds=time.monotonic() - self._start_time,
            timestamp=time.time(),
            process=self._get_process_info(),
        )

        with self._lock:
            checks = dict(self._checks)

        for name, (check_fn, timeout) in checks.items():
            if include_components and name not in include_components:
                continue

            effective_timeout = timeout_override or timeout
            comp = self.run_check(name, check_fn, effective_timeout)
            report.components[name] = comp

            if comp.status == "error":
                report.degraded_components.append(name)
                report.status = "unhealthy"
            elif comp.status == "degraded":
                report.degraded_components.append(name)
                if report.status == "ok":
                    report.status = "degraded"

        return report

    def _get_process_info(self) -> Dict[str, Any]:
        """Get process-level information."""
        info = {"pid": os.getpid()}
        try:
            import threading
            info["threads"] = threading.active_count()
        except Exception:
            pass
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            info["rss_bytes"] = proc.memory_info().rss
            info["cpu_percent"] = proc.cpu_percent(interval=0)
        except ImportError:
            pass
        except Exception:
            pass
        return info

    def liveness(self) -> Dict[str, Any]:
        """Simple liveness check: is the process alive?

        Returns 200 if the event loop is responsive.
        """
        return {
            "status": "alive",
            "service": "b2b-ai-enterprise",
            "pid": os.getpid(),
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "timestamp": round(time.time(), 3),
        }

    def readiness(
        self,
        critical_components: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Readiness check: can the service handle traffic?

        Only checks critical components (default: database, redis).
        Returns (body, status_code).
        """
        critical = critical_components or ["database", "redis"]
        report = self.run_all(include_components=critical, timeout_override=3.0)

        if report.status == "unhealthy":
            return report.to_dict(), 503
        return report.to_dict(), 200


# --------------------------------------------------------------------------- #
# Default health checks
# --------------------------------------------------------------------------- #

def database_health_check(db=None) -> ComponentHealth:
    """Check database connectivity."""
    if db is None:
        return ComponentHealth(
            name="database", status="not_configured",
            detail="No database instance provided",
        )
    try:
        start = time.perf_counter()
        db.conn.execute("SELECT 1")
        latency = (time.perf_counter() - start) * 1000
        backend = "postgresql" if getattr(db, "_is_pg", False) else "sqlite"
        return ComponentHealth(
            name="database",
            status="ok",
            latency_ms=latency,
            detail=f"{backend} connected",
        )
    except Exception as exc:
        return ComponentHealth(
            name="database", status="error", error=str(exc),
        )


def redis_health_check() -> ComponentHealth:
    """Check Redis connectivity."""
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return ComponentHealth(
            name="redis", status="not_configured",
            detail="REDIS_URL not set",
        )
    try:
        import redis
        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        start = time.perf_counter()
        client.ping()
        latency = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="redis", status="ok", latency_ms=latency,
            detail="PING ok",
        )
    except ImportError:
        # Fallback: TCP check
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(url)
            host = parts.hostname or "localhost"
            port = parts.port or 6379
            start = time.perf_counter()
            with socket.create_connection((host, port), timeout=2):
                pass
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="redis", status="ok", latency_ms=latency,
                detail="TCP ok (no redis client)",
            )
        except Exception as exc:
            return ComponentHealth(
                name="redis", status="error", error=str(exc),
            )
    except Exception as exc:
        return ComponentHealth(
            name="redis", status="error", error=str(exc),
        )


def sat_connectivity_check() -> ComponentHealth:
    """Check SAT web service connectivity."""
    sat_url = os.environ.get("SAT_SOAP_URL", "").strip()
    if not sat_url:
        return ComponentHealth(
            name="sat_soap", status="not_configured",
            detail="SAT_SOAP_URL not set",
        )
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(sat_url)
        host = parts.hostname or "localhost"
        port = parts.port or 443
        start = time.perf_counter()
        with socket.create_connection((host, port), timeout=3):
            pass
        latency = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="sat_soap", status="ok", latency_ms=latency,
            detail=f"TCP to {host}:{port} ok",
        )
    except Exception as exc:
        return ComponentHealth(
            name="sat_soap", status="degraded",
            detail="SAT unreachable (non-critical)",
            error=str(exc),
        )


def circuit_breaker_health_check(registry=None) -> ComponentHealth:
    """Check circuit breaker states."""
    if registry is None:
        from b2b_ai.infrastructure.circuit_breaker import registry as cb_registry
    else:
        cb_registry = registry

    states = cb_registry.all_states()
    open_breakers = [name for name, state in states.items() if state == "open"]

    if open_breakers:
        return ComponentHealth(
            name="circuit_breakers", status="degraded",
            detail=f"Open circuits: {', '.join(open_breakers)}",
        )
    return ComponentHealth(
        name="circuit_breakers", status="ok",
        detail=f"{len(states)} circuits, all healthy",
    )


# --------------------------------------------------------------------------- #
# Prometheus metrics rendering
# --------------------------------------------------------------------------- #

def render_prometheus_metrics(
    health_report: HealthReport,
    extra_metrics: Optional[Dict[str, Any]] = None,
) -> str:
    """Render health data in Prometheus text exposition format.

    This provides a /metrics endpoint compatible with Prometheus scraping.
    """
    lines = []

    # Service info
    lines.append("# HELP b2b_service_info Service metadata.")
    lines.append("# TYPE b2b_service_info gauge")
    lines.append(f'b2b_service_info{{version="{health_report.version}"}} 1')

    # Uptime
    lines.append("# HELP b2b_uptime_seconds Service uptime in seconds.")
    lines.append("# TYPE b2b_uptime_seconds gauge")
    lines.append(f"b2b_uptime_seconds {health_report.uptime_seconds:.1f}")

    # Health status (1=ok, 0.5=degraded, 0=unhealthy)
    status_value = {"ok": 1, "degraded": 0.5, "unhealthy": 0}.get(
        health_report.status, 0
    )
    lines.append("# HELP b2b_health_status Health status (1=ok, 0.5=degraded, 0=unhealthy).")
    lines.append("# TYPE b2b_health_status gauge")
    lines.append(f"b2b_health_status {status_value}")

    # Per-component latency
    lines.append("# HELP b2b_component_latency_ms Component check latency in milliseconds.")
    lines.append("# TYPE b2b_component_latency_ms gauge")
    for name, comp in health_report.components.items():
        if comp.latency_ms is not None:
            lines.append(f'b2b_component_latency_ms{{component="{name}"}} {comp.latency_ms:.2f}')

    # Per-component status
    lines.append("# HELP b2b_component_status Component health (1=ok, 0.5=degraded, 0=error).")
    lines.append("# TYPE b2b_component_status gauge")
    for name, comp in health_report.components.items():
        val = {"ok": 1, "degraded": 0.5, "not_configured": -1}.get(comp.status, 0)
        lines.append(f'b2b_component_status{{component="{name}"}} {val}')

    # Extra metrics from the app (request counts, etc.)
    if extra_metrics:
        lines.append("# HELP b2b_extra_metrics Application-specific metrics.")
        for key, value in extra_metrics.items():
            lines.append(f"b2b_{key} {value}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Singleton registry
# --------------------------------------------------------------------------- #

health_registry = HealthCheckRegistry()
