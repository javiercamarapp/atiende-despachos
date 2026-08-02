# -*- coding: utf-8 -*-
"""
computer_use_metrics.py — Metrics specific to Computer Use operations.

Tracks:
    - Sessions opened / closed (by tenant, by provider)
    - Actions performed (success / failed / needs_human_review)
    - Latency per action type
    - Retries and timeouts
    - Selector changes detected (DOM drift)
    - Verification failures (screenshot mismatch)

Integrates with the existing MetricsRegistry in b2b_ai.monitoring.metrics
for Prometheus-compatible output. Also exposes a snapshot() method for
JSON consumption by dashboards and health checks.

Thread-safe. Zero external dependencies beyond stdlib.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

# Prometheus metric names and help text.
_CU_METRIC_HELP = {
    "b2b_cu_sessions_opened_total": ("counter", "Total Computer Use sessions opened."),
    "b2b_cu_sessions_closed_total": ("counter", "Total Computer Use sessions closed."),
    "b2b_cu_sessions_active": ("gauge", "Currently active Computer Use sessions."),
    "b2b_cu_actions_total": ("counter", "Total Computer Use actions by outcome."),
    "b2b_cu_action_duration_seconds": ("summary", "Latency of Computer Use actions."),
    "b2b_cu_retries_total": ("counter", "Total retries in Computer Use actions."),
    "b2b_cu_timeouts_total": ("counter", "Total timeouts in Computer Use actions."),
    "b2b_cu_human_review_total": ("counter", "Actions flagged as needs_human_review."),
    "b2b_cu_selector_changes_total": ("counter", "Selector/element changes detected (DOM drift)."),
    "b2b_cu_verification_failures_total": ("counter", "Screenshot verification failures."),
}


@dataclass
class _ActionLatency:
    """Tracks latency samples for a specific action type."""
    samples: List[float] = field(default_factory=list)
    _MAX_SAMPLES = 1000

    def record(self, duration_s: float):
        self.samples.append(duration_s)
        if len(self.samples) > self._MAX_SAMPLES:
            self.samples = self.samples[-self._MAX_SAMPLES:]

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def sum(self) -> float:
        return sum(self.samples)

    @property
    def avg(self) -> float:
        return self.sum / self.count if self.count else 0.0

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        idx = int(len(s) * 0.95)
        return s[min(idx, len(s) - 1)]

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0


class ComputerUseMetrics:
    """Thread-safe metrics registry for Computer Use operations.

    Usage:
        from b2b_ai.monitoring.computer_use_metrics import cu_metrics

        # Record a session open
        cu_metrics.session_opened(tenant_id="t1", provider="contpaqi")

        # Time an action
        with cu_metrics.action_timer("login", tenant_id="t1", provider="contpaqi") as timer:
            result = await driver.login(creds)
            timer.set_status("success" if result.ok else "failed")

        # Or manually
        cu_metrics.action_completed("navigate", status="success", duration_s=1.2, tenant_id="t1")

        # Get snapshot
        print(cu_metrics.snapshot())
        print(cu_metrics.render_prometheus())
    """

    def __init__(self):
        self._lock = threading.RLock()

        # Counters (cumulative).
        self._sessions_opened: int = 0
        self._sessions_closed: int = 0
        self._active_sessions: int = 0

        # Per-provider/session tracking.
        self._sessions_by_provider: Dict[str, int] = collections.defaultdict(int)
        self._sessions_by_tenant: Dict[str, int] = collections.defaultdict(int)

        # Action counters by status.
        self._actions_total: Dict[str, int] = collections.defaultdict(int)  # status -> count
        self._actions_by_type: Dict[str, Dict[str, int]] = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )  # action -> status -> count
        self._actions_by_tenant: Dict[str, int] = collections.defaultdict(int)

        # Latency by action type.
        self._latency: Dict[str, _ActionLatency] = collections.defaultdict(_ActionLatency)

        # Specific counters.
        self._retries: int = 0
        self._timeouts: int = 0
        self._human_reviews: int = 0
        self._selector_changes: int = 0
        self._verification_failures: int = 0

    # ------------------------------------------------------------------
    # Session tracking
    # ------------------------------------------------------------------

    def session_opened(
        self,
        tenant_id: str = "",
        provider: str = "",
    ):
        """Record a session being opened."""
        with self._lock:
            self._sessions_opened += 1
            self._active_sessions += 1
            if provider:
                self._sessions_by_provider[provider] += 1
            if tenant_id:
                self._sessions_by_tenant[tenant_id] += 1
            logger.debug("CU session opened: tenant=%s provider=%s", tenant_id, provider)

    def session_closed(
        self,
        tenant_id: str = "",
        provider: str = "",
        reason: str = "normal",
    ):
        """Record a session being closed."""
        with self._lock:
            self._sessions_closed += 1
            self._active_sessions = max(0, self._active_sessions - 1)
            logger.debug(
                "CU session closed: tenant=%s provider=%s reason=%s",
                tenant_id, provider, reason,
            )

    # ------------------------------------------------------------------
    # Action tracking
    # ------------------------------------------------------------------

    def action_completed(
        self,
        action: str,
        status: str = "success",
        duration_s: float = 0.0,
        tenant_id: str = "",
        provider: str = "",
    ):
        """Record a completed Computer Use action."""
        with self._lock:
            self._actions_total[status] += 1
            self._actions_by_type[action][status] += 1
            if tenant_id:
                self._actions_by_tenant[tenant_id] += 1
            if duration_s > 0:
                self._latency[action].record(duration_s)

            if status == "needs_human_review":
                self._human_reviews += 1
            if status == "verification_failed":
                self._verification_failures += 1

    def action_retry(self, action: str = ""):
        """Record a retry."""
        with self._lock:
            self._retries += 1

    def action_timeout(self, action: str = ""):
        """Record a timeout."""
        with self._lock:
            self._timeouts += 1

    def selector_change_detected(self, details: str = ""):
        """Record a selector/element change (DOM drift detection)."""
        with self._lock:
            self._selector_changes += 1
            logger.info("CU selector change detected: %s", details)

    def verification_failed(self, details: str = ""):
        """Record a screenshot verification failure."""
        with self._lock:
            self._verification_failures += 1
            logger.warning("CU verification failed: %s", details)

    # ------------------------------------------------------------------
    # Context manager for timing
    # ------------------------------------------------------------------

    @dataclass
    class _Timer:
        """Context manager that records action timing."""
        _metrics: "ComputerUseMetrics"
        _action: str
        _tenant_id: str
        _provider: str
        _start: float = field(default_factory=time.monotonic)
        _status: str = "success"

        def set_status(self, status: str):
            self._status = status

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            duration = time.monotonic() - self._start
            if exc[0] is not None:
                self._status = "failed"
            self._metrics.action_completed(
                self._action,
                status=self._status,
                duration_s=duration,
                tenant_id=self._tenant_id,
                provider=self._provider,
            )
            return False

    def action_timer(
        self,
        action: str,
        tenant_id: str = "",
        provider: str = "",
    ) -> _Timer:
        """Get a context manager that times an action."""
        return self._Timer(
            _metrics=self,
            _action=action,
            _tenant_id=tenant_id,
            _provider=provider,
        )

    # ------------------------------------------------------------------
    # Snapshot (JSON)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Get a JSON-serializable snapshot of all Computer Use metrics."""
        with self._lock:
            # Aggregate action totals.
            total_actions = sum(self._actions_total.values())
            success = self._actions_total.get("success", 0)
            failed = self._actions_total.get("failed", 0)

            # Latency summary.
            latency_summary = {}
            for action, lat in self._latency.items():
                latency_summary[action] = {
                    "count": lat.count,
                    "avg_ms": round(lat.avg * 1000, 2),
                    "p95_ms": round(lat.p95 * 1000, 2),
                    "max_ms": round(lat.max * 1000, 2),
                }

            return {
                "sessions": {
                    "opened": self._sessions_opened,
                    "closed": self._sessions_closed,
                    "active": self._active_sessions,
                    "by_provider": dict(self._sessions_by_provider),
                },
                "actions": {
                    "total": total_actions,
                    "success": success,
                    "failed": failed,
                    "by_status": dict(self._actions_total),
                    "by_type": {
                        k: dict(v) for k, v in self._actions_by_type.items()
                    },
                },
                "latency": latency_summary,
                "retries": self._retries,
                "timeouts": self._timeouts,
                "human_reviews": self._human_reviews,
                "selector_changes": self._selector_changes,
                "verification_failures": self._verification_failures,
            }

    # ------------------------------------------------------------------
    # Prometheus rendering
    # ------------------------------------------------------------------

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        lines = []

        def _add(name: str, value: int, labels: Optional[Dict[str, str]] = None):
            typ, help_text = _CU_METRIC_HELP.get(name, ("counter", ""))
            # Only emit HELP/TYPE once per metric name.
            if not any(name in l and "# HELP" in l for l in lines):
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {typ}")
            label_str = ""
            if labels:
                parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
                label_str = f"{{{parts}}}"
            lines.append(f"{name}{label_str} {value}")

        with self._lock:
            _add("b2b_cu_sessions_opened_total", self._sessions_opened)
            _add("b2b_cu_sessions_closed_total", self._sessions_closed)
            _add("b2b_cu_sessions_active", self._active_sessions)

            for provider, count in self._sessions_by_provider.items():
                _add("b2b_cu_sessions_opened_total", count, {"provider": provider})

            for status, count in self._actions_total.items():
                _add("b2b_cu_actions_total", count, {"status": status})

            for action, statuses in self._actions_by_type.items():
                for status, count in statuses.items():
                    _add("b2b_cu_actions_total", count, {"action": action, "status": status})

            # Latency summaries.
            for action, lat in self._latency.items():
                name = "b2b_cu_action_duration_seconds"
                if not any(name in l and "# HELP" in l for l in lines):
                    typ, help_text = _CU_METRIC_HELP.get(name, ("summary", ""))
                    lines.append(f"# HELP {name} {help_text}")
                    lines.append(f"# TYPE {name} {typ}")
                lines.append(f'{name}{{action="{action}",quantile="0.95"}} {lat.p95:.6f}')
                lines.append(f'{name}{{action="{action}",quantile="avg"}} {lat.avg:.6f}')
                lines.append(f'{name}_sum{{action="{action}"}} {lat.sum:.6f}')
                lines.append(f'{name}_count{{action="{action}"}} {lat.count}')

            _add("b2b_cu_retries_total", self._retries)
            _add("b2b_cu_timeouts_total", self._timeouts)
            _add("b2b_cu_human_review_total", self._human_reviews)
            _add("b2b_cu_selector_changes_total", self._selector_changes)
            _add("b2b_cu_verification_failures_total", self._verification_failures)

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Reset (for testing)
    # ------------------------------------------------------------------

    def reset(self):
        """Reset all metrics. For testing only."""
        with self._lock:
            self._sessions_opened = 0
            self._sessions_closed = 0
            self._active_sessions = 0
            self._sessions_by_provider.clear()
            self._sessions_by_tenant.clear()
            self._actions_total.clear()
            self._actions_by_type.clear()
            self._actions_by_tenant.clear()
            self._latency.clear()
            self._retries = 0
            self._timeouts = 0
            self._human_reviews = 0
            self._selector_changes = 0
            self._verification_failures = 0


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------
cu_metrics = ComputerUseMetrics()
