# -*- coding: utf-8 -*-
"""Tests for Computer Use metrics (b2b_ai.monitoring.computer_use_metrics)."""
from __future__ import annotations

import time

import pytest


class TestComputerUseMetrics:
    def setup_method(self):
        from b2b_ai.monitoring.computer_use_metrics import ComputerUseMetrics
        self.metrics = ComputerUseMetrics()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def test_session_opened(self):
        self.metrics.session_opened(tenant_id="t1", provider="contpaqi")
        snap = self.metrics.snapshot()
        assert snap["sessions"]["opened"] == 1
        assert snap["sessions"]["active"] == 1

    def test_session_closed(self):
        self.metrics.session_opened(tenant_id="t1")
        self.metrics.session_closed(tenant_id="t1")
        snap = self.metrics.snapshot()
        assert snap["sessions"]["closed"] == 1
        assert snap["sessions"]["active"] == 0

    def test_sessions_by_provider(self):
        self.metrics.session_opened(provider="contpaqi")
        self.metrics.session_opened(provider="aspel")
        self.metrics.session_opened(provider="contpaqi")
        snap = self.metrics.snapshot()
        assert snap["sessions"]["by_provider"]["contpaqi"] == 2
        assert snap["sessions"]["by_provider"]["aspel"] == 1

    def test_active_never_negative(self):
        self.metrics.session_closed()  # Close without open
        snap = self.metrics.snapshot()
        assert snap["sessions"]["active"] >= 0

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def test_action_success(self):
        self.metrics.action_completed("login", status="success", duration_s=0.5)
        snap = self.metrics.snapshot()
        assert snap["actions"]["success"] == 1
        assert snap["actions"]["total"] == 1

    def test_action_failed(self):
        self.metrics.action_completed("navigate", status="failed")
        snap = self.metrics.snapshot()
        assert snap["actions"]["failed"] == 1

    def test_actions_by_type(self):
        self.metrics.action_completed("login", status="success")
        self.metrics.action_completed("login", status="success")
        self.metrics.action_completed("login", status="failed")
        snap = self.metrics.snapshot()
        assert snap["actions"]["by_type"]["login"]["success"] == 2
        assert snap["actions"]["by_type"]["login"]["failed"] == 1

    # ------------------------------------------------------------------
    # Latency
    # ------------------------------------------------------------------

    def test_latency_tracking(self):
        self.metrics.action_completed("navigate", status="success", duration_s=0.1)
        self.metrics.action_completed("navigate", status="success", duration_s=0.5)
        self.metrics.action_completed("navigate", status="success", duration_s=0.3)
        snap = self.metrics.snapshot()
        lat = snap["latency"]["navigate"]
        assert lat["count"] == 3
        assert lat["avg_ms"] > 0
        assert lat["p95_ms"] >= lat["avg_ms"]

    # ------------------------------------------------------------------
    # Retries, timeouts, human reviews
    # ------------------------------------------------------------------

    def test_retries(self):
        self.metrics.action_retry("navigate")
        self.metrics.action_retry("navigate")
        snap = self.metrics.snapshot()
        assert snap["retries"] == 2

    def test_timeouts(self):
        self.metrics.action_timeout("extract")
        snap = self.metrics.snapshot()
        assert snap["timeouts"] == 1

    def test_human_reviews(self):
        self.metrics.action_completed("register_invoice", status="needs_human_review")
        snap = self.metrics.snapshot()
        assert snap["human_reviews"] == 1

    def test_selector_changes(self):
        self.metrics.selector_change_detected("login button moved")
        snap = self.metrics.snapshot()
        assert snap["selector_changes"] == 1

    def test_verification_failures(self):
        self.metrics.verification_failed("screenshot mismatch")
        snap = self.metrics.snapshot()
        assert snap["verification_failures"] == 1

    # ------------------------------------------------------------------
    # Timer context manager
    # ------------------------------------------------------------------

    def test_action_timer(self):
        with self.metrics.action_timer("login", tenant_id="t1") as timer:
            time.sleep(0.01)
        snap = self.metrics.snapshot()
        assert snap["actions"]["success"] == 1
        assert "login" in snap["latency"]

    def test_action_timer_failure(self):
        try:
            with self.metrics.action_timer("navigate") as timer:
                raise ValueError("boom")
        except ValueError:
            pass
        snap = self.metrics.snapshot()
        assert snap["actions"]["failed"] == 1

    # ------------------------------------------------------------------
    # Prometheus
    # ------------------------------------------------------------------

    def test_prometheus_render(self):
        self.metrics.session_opened(provider="contpaqi")
        self.metrics.action_completed("login", status="success", duration_s=0.1)
        output = self.metrics.render_prometheus()
        assert "b2b_cu_sessions_opened_total" in output
        assert "b2b_cu_actions_total" in output
        assert "b2b_cu_action_duration_seconds" in output

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def test_reset(self):
        self.metrics.session_opened()
        self.metrics.action_completed("test", status="success")
        self.metrics.reset()
        snap = self.metrics.snapshot()
        assert snap["sessions"]["opened"] == 0
        assert snap["actions"]["total"] == 0
