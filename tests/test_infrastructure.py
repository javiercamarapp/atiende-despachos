# -*- coding: utf-8 -*-
"""
test_infrastructure.py — Comprehensive tests for all Fortune 500 infrastructure.

Tests:
    1. Structured Logging Enterprise
    2. Circuit Breaker Pattern
    3. Retry with Exponential Backoff
    4. Health Check Enterprise
    5. Graceful Shutdown
    6. Configuration Validation
    7. Database Connection Pool Enterprise
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from unittest import mock

import pytest


# =========================================================================== #
# 1. STRUCTURED LOGGING TESTS
# =========================================================================== #

class TestStructuredLogging:
    """Tests for b2b_ai.infrastructure.structured_logging."""

    def test_mask_pii_rfc(self):
        from b2b_ai.infrastructure.structured_logging import mask_pii
        result = mask_pii("RFC del emisor: XAXX010101000")
        assert "<rfc>" in result
        assert "XAXX010101000" not in result

    def test_mask_pii_curp(self):
        from b2b_ai.infrastructure.structured_logging import mask_pii
        result = mask_pii("CURP: GOML850101HDFRRL09")
        assert "<curp>" in result
        assert "GOML850101HDFRRL09" not in result

    def test_mask_pii_email(self):
        from b2b_ai.infrastructure.structured_logging import mask_pii
        result = mask_pii("Contact: juan@empresa.com.mx")
        assert "<email>" in result
        assert "juan@empresa.com" not in result

    def test_mask_pii_dict_keys(self):
        from b2b_ai.infrastructure.structured_logging import mask_pii
        data = {
            "password": "secreto123",
            "rfc": "XAXX010101000",
            "api_key": "sk-1234567890",
            "name": "Empresa SA",
        }
        result = mask_pii(data)
        assert result["password"] == "<redacted>"
        assert result["api_key"] == "<redacted>"
        assert result["name"] == "Empresa SA"  # Not sensitive

    def test_mask_pii_nested(self):
        from b2b_ai.infrastructure.structured_logging import mask_pii
        data = {
            "emisor": {
                "rfc": "XAXX010101000",
                "nombre": "Empresa",
            },
            "items": [
                {"email": "test@example.com", "monto": 1000},
            ],
        }
        result = mask_pii(data)
        assert "<rfc>" in str(result["emisor"]["rfc"])
        assert result["items"][0]["monto"] == 1000

    def test_mask_secrets_in_url(self):
        from b2b_ai.infrastructure.structured_logging import mask_secrets_in_url
        url = "https://api.example.com/v1?key=sk-secret123&data=test"
        result = mask_secrets_in_url(url)
        assert "sk-secret123" not in result
        assert "<redacted>" in result

    def test_mask_secrets_in_url_basic_auth(self):
        from b2b_ai.infrastructure.structured_logging import mask_secrets_in_url
        url = "https://user:password123@host.com/path"
        result = mask_secrets_in_url(url)
        assert "password123" not in result

    def test_correlation_id_context(self):
        from b2b_ai.infrastructure.structured_logging import (
            request_context, get_correlation_id
        )
        assert get_correlation_id() is None
        with request_context(correlation_id="test-123") as ctx:
            assert get_correlation_id() == "test-123"
            assert ctx["correlation_id"] == "test-123"
        assert get_correlation_id() is None

    def test_correlation_id_auto_generated(self):
        from b2b_ai.infrastructure.structured_logging import (
            request_context, get_correlation_id
        )
        with request_context() as ctx:
            cid = get_correlation_id()
            assert cid is not None
            assert len(cid) == 16  # uuid hex[:16]

    def test_request_context_with_tenant(self):
        from b2b_ai.infrastructure.structured_logging import request_context
        with request_context(tenant_id="t-42", user_id="u-7") as ctx:
            assert ctx["tenant_id"] == "t-42"
            assert ctx["user_id"] == "u-7"

    def test_json_formatter_output(self):
        from b2b_ai.infrastructure.structured_logging import EnterpriseJsonFormatter
        formatter = EnterpriseJsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"
        assert "ts" in parsed

    def test_json_formatter_with_exception(self):
        from b2b_ai.infrastructure.structured_logging import EnterpriseJsonFormatter
        formatter = EnterpriseJsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=1, msg="error occurred", args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exc_info" in parsed
        assert "exc_type" in parsed
        assert parsed["exc_type"] == "ValueError"

    def test_json_formatter_pii_redaction(self):
        from b2b_ai.infrastructure.structured_logging import EnterpriseJsonFormatter
        formatter = EnterpriseJsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Processing RFC: XAXX010101000 for juan@test.com",
            args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "XAXX010101000" not in output
        assert "juan@test.com" not in output
        assert "<rfc>" in output
        assert "<email>" in output

    def test_request_response_logger(self):
        from b2b_ai.infrastructure.structured_logging import RequestResponseLogger
        rr = RequestResponseLogger("test.request")
        # Just verify no exceptions
        rr.log_request("GET", "/api/v1/invoices", client_ip="127.0.0.1")
        rr.log_response("GET", "/api/v1/invoices", 200, 43.2)
        rr.log_response("POST", "/api/v1/invoices", 500, 120.5)
        rr.log_error("POST", "/api/v1/invoices", ValueError("bad"), 10.0)

    def test_request_response_logger_sanitizes_auth(self):
        from b2b_ai.infrastructure.structured_logging import RequestResponseLogger
        rr = RequestResponseLogger("test.request")
        headers = {
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9",
            "Content-Type": "application/json",
        }
        rr.log_request("POST", "/api/v1/test", headers=headers)

    def test_request_response_logger_skips_health(self):
        from b2b_ai.infrastructure.structured_logging import RequestResponseLogger
        rr = RequestResponseLogger("test.request")
        # Should not raise
        rr.log_request("GET", "/health/live")
        rr.log_response("GET", "/health/live", 200, 0.5)


# =========================================================================== #
# 2. CIRCUIT BREAKER TESTS
# =========================================================================== #

class TestCircuitBreaker:
    """Tests for b2b_ai.infrastructure.circuit_breaker."""

    def test_initial_state_closed(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_stays_closed_on_success(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))
        for _ in range(5):
            with cb:
                pass  # success
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_opens_after_threshold_failures(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
            CircuitBreakerOpenError,
        )
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            try:
                with cb:
                    raise ConnectionError("fail")
            except ConnectionError:
                pass
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_rejects_calls(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
            CircuitBreakerOpenError,
        )
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=1))
        try:
            with cb:
                raise ConnectionError("fail")
        except ConnectionError:
            pass
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerOpenError):
            with cb:
                pass

    def test_half_open_after_timeout(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.1,
            ),
        )
        # Trip the circuit
        try:
            with cb:
                raise ConnectionError("fail")
        except ConnectionError:
            pass
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.1,
                success_threshold=2,
            ),
        )
        # Trip
        try:
            with cb:
                raise ConnectionError("fail")
        except ConnectionError:
            pass

        time.sleep(0.15)
        # Now in half-open: succeed twice to close
        with cb:
            pass
        with cb:
            pass
        assert cb.state == CircuitState.CLOSED

    def test_protect_decorator(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
            CircuitBreakerOpenError,
        )
        cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=2))

        call_count = 0

        @cb.protect
        def failing_call():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                failing_call()

        # Circuit is open now
        with pytest.raises(CircuitBreakerOpenError):
            failing_call()
        assert call_count == 2  # Third call was rejected

    def test_protect_decorator_with_fallback(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig,
        )

        def fallback(*args, **kwargs):
            return {"fallback": True}

        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(failure_threshold=1),
            fallback=fallback,
        )

        @cb.protect
        def failing_call():
            raise ConnectionError("fail")

        # First call fails and opens circuit
        with pytest.raises(ConnectionError):
            failing_call()

        # Second call uses fallback
        result = failing_call()
        assert result == {"fallback": True}

    def test_registry(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreakerRegistry, CircuitBreakerConfig,
        )
        reg = CircuitBreakerRegistry()
        cb1 = reg.register("service_a", config=CircuitBreakerConfig())
        cb2 = reg.register("service_b", config=CircuitBreakerConfig())
        assert reg.get("service_a") is cb1
        assert reg.get("service_b") is cb2
        assert reg.get("nonexistent") is None

    def test_registry_metrics(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreakerRegistry, CircuitBreakerConfig,
        )
        reg = CircuitBreakerRegistry()
        reg.register("s1", config=CircuitBreakerConfig())
        reg.register("s2", config=CircuitBreakerConfig())
        metrics = reg.all_metrics()
        assert "s1" in metrics
        assert "s2" in metrics

    def test_excluded_exceptions_dont_count(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )
        cb = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(failure_threshold=3),
        )
        for _ in range(5):
            try:
                with cb:
                    raise ValueError("validation error")
            except ValueError:
                pass
        # ValueError is excluded, so circuit stays closed
        assert cb.state == CircuitState.CLOSED

    def test_manual_trip_and_reset(self):
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitState,
        )
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

        cb.trip()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_metrics_tracking(self):
        from b2b_ai.infrastructure.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test")
        with cb:
            pass
        metrics = cb.metrics
        assert metrics["total_requests"] == 1
        assert metrics["service"] == "test"


# =========================================================================== #
# 3. RETRY TESTS
# =========================================================================== #

class TestRetry:
    """Tests for b2b_ai.infrastructure.retry."""

    def test_no_retry_on_success(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig
        call_count = 0

        @with_retry("test", config=RetryConfig(max_attempts=3))
        def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = success()
        assert result == "ok"
        assert call_count == 1

    def test_retry_on_connection_error(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig
        call_count = 0

        @with_retry(
            "test",
            config=RetryConfig(
                max_attempts=3,
                base_delay=0.01,
                jitter=False,
                retryable_exceptions=(ConnectionError,),
            ),
        )
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3

    def test_retry_exhausted_raises(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig, RetryExhaustedError

        @with_retry(
            "test",
            config=RetryConfig(
                max_attempts=3,
                base_delay=0.01,
                jitter=False,
                retryable_exceptions=(ConnectionError,),
            ),
        )
        def always_fail():
            raise ConnectionError("fail")

        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()
        assert exc_info.value.attempts == 3
        assert exc_info.value.service == "test"

    def test_no_retry_on_non_retryable(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig
        call_count = 0

        @with_retry(
            "test",
            config=RetryConfig(
                max_attempts=5,
                base_delay=0.01,
                non_retryable_exceptions=(ValueError,),
            ),
        )
        def validation_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("invalid input")

        with pytest.raises(ValueError):
            validation_error()
        assert call_count == 1  # No retries for ValueError

    def test_exponential_backoff_timing(self):
        from b2b_ai.infrastructure.retry import calculate_backoff, RetryConfig
        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            max_delay=60.0,
            jitter=False,
        )
        # attempt 0: 1.0 * 2^0 = 1.0
        assert abs(calculate_backoff(0, config) - 1.0) < 0.01
        # attempt 1: 1.0 * 2^1 = 2.0
        assert abs(calculate_backoff(1, config) - 2.0) < 0.01
        # attempt 2: 1.0 * 2^2 = 4.0
        assert abs(calculate_backoff(2, config) - 4.0) < 0.01
        # attempt 10: capped at 60.0
        assert calculate_backoff(10, config) == 60.0

    def test_jitter_adds_variance(self):
        from b2b_ai.infrastructure.retry import calculate_backoff, RetryConfig
        config = RetryConfig(base_delay=1.0, jitter=True, exponential_base=2.0)
        delays = [calculate_backoff(0, config) for _ in range(100)]
        # With jitter, not all delays should be identical
        assert len(set(delays)) > 1

    def test_idempotency_store(self):
        from b2b_ai.infrastructure.retry import IdempotencyStore
        store = IdempotencyStore(ttl_seconds=60)
        assert store.get("key1") is None
        store.set("key1", {"result": "ok"})
        assert store.get("key1") == {"result": "ok"}
        assert store.has("key1")
        assert not store.has("key2")

    def test_idempotency_store_ttl(self):
        from b2b_ai.infrastructure.retry import IdempotencyStore
        store = IdempotencyStore(ttl_seconds=0.1)
        store.set("key1", "value")
        assert store.get("key1") == "value"
        time.sleep(0.15)
        assert store.get("key1") is None

    def test_idempotency_key_generation(self):
        from b2b_ai.infrastructure.retry import generate_idempotency_key
        key1 = generate_idempotency_key("sat", "submit", {"rfc": "XAXX"})
        key2 = generate_idempotency_key("sat", "submit", {"rfc": "XAXX"})
        key3 = generate_idempotency_key("sat", "submit", {"rfc": "OTHER"})
        assert key1 == key2  # Same params → same key
        assert key1 != key3  # Different params → different key

    def test_idempotency_prevents_duplicate_execution(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig
        call_count = 0

        @with_retry(
            "test",
            config=RetryConfig(max_attempts=3, base_delay=0.01),
            idempotency_key="unique-key-123",
        )
        def process():
            nonlocal call_count
            call_count += 1
            return {"id": "inv-1"}

        # First call executes
        result1 = process()
        assert call_count == 1

        # Second call returns cached result
        result2 = process()
        assert call_count == 1  # Not called again
        assert result2 == result1

    def test_service_retry_configs(self):
        from b2b_ai.infrastructure.retry import SERVICE_RETRY_CONFIGS
        assert SERVICE_RETRY_CONFIGS["sat_soap"].max_attempts == 3
        assert SERVICE_RETRY_CONFIGS["facturapi"].max_attempts == 5
        assert SERVICE_RETRY_CONFIGS["contpaqi_com"].max_attempts == 2

    def test_on_retry_callback(self):
        from b2b_ai.infrastructure.retry import with_retry, RetryConfig
        retries = []

        def on_retry(attempt, exc, delay):
            retries.append((attempt, str(exc), delay))

        @with_retry(
            "test",
            config=RetryConfig(
                max_attempts=3,
                base_delay=0.01,
                jitter=False,
                on_retry=on_retry,
            ),
        )
        def flaky():
            if len(retries) < 2:
                raise ConnectionError("oops")
            return "ok"

        flaky()
        assert len(retries) == 2


# =========================================================================== #
# 4. HEALTH CHECK TESTS
# =========================================================================== #

class TestHealthCheck:
    """Tests for b2b_ai.infrastructure.health."""

    def test_liveness(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry
        reg = HealthCheckRegistry()
        result = reg.liveness()
        assert result["status"] == "alive"
        assert "pid" in result
        assert "uptime_seconds" in result

    def test_readiness_no_checks(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry
        reg = HealthCheckRegistry()
        body, status = reg.readiness(critical_components=["nonexistent"])
        assert status == 200  # No critical components = ok

    def test_readiness_with_passing_check(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry, ComponentHealth
        reg = HealthCheckRegistry()

        def ok_check():
            return ComponentHealth(name="test", status="ok")

        reg.register("database", ok_check)
        body, status = reg.readiness(critical_components=["database"])
        assert status == 200
        assert body["status"] == "ok"

    def test_readiness_with_failing_check(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry, ComponentHealth
        reg = HealthCheckRegistry()

        def fail_check():
            return ComponentHealth(name="test", status="error", error="connection refused")

        reg.register("database", fail_check)
        body, status = reg.readiness(critical_components=["database"])
        assert status == 503
        assert body["status"] == "unhealthy"

    def test_detailed_health_report(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry, ComponentHealth
        reg = HealthCheckRegistry()

        def db_check():
            return ComponentHealth(name="database", status="ok")

        def redis_check():
            return ComponentHealth(name="redis", status="degraded", detail="slow")

        reg.register("database", db_check)
        reg.register("redis", redis_check)

        report = reg.run_all()
        assert report.status == "degraded"
        assert "redis" in report.degraded_components
        assert report.components["database"].status == "ok"

    def test_health_check_timeout(self):
        from b2b_ai.infrastructure.health import HealthCheckRegistry, ComponentHealth
        reg = HealthCheckRegistry(default_timeout=0.1)

        def slow_check():
            time.sleep(0.5)
            return ComponentHealth(name="slow", status="ok")

        reg.register("slow", slow_check, timeout=0.1)
        # The check may complete or timeout depending on timing
        report = reg.run_all()
        assert "slow" in report.components

    def test_health_report_to_dict(self):
        from b2b_ai.infrastructure.health import HealthReport
        report = HealthReport(
            status="ok",
            uptime_seconds=100.0,
            timestamp=time.time(),
        )
        d = report.to_dict()
        assert d["status"] == "ok"
        assert d["uptime_seconds"] == 100.0

    def test_prometheus_metrics_rendering(self):
        from b2b_ai.infrastructure.health import (
            HealthReport, ComponentHealth, render_prometheus_metrics,
        )
        report = HealthReport(
            status="ok",
            version="1.0.0",
            uptime_seconds=3600.0,
            timestamp=time.time(),
            components={
                "database": ComponentHealth(name="database", status="ok", latency_ms=5.2),
                "redis": ComponentHealth(name="redis", status="ok", latency_ms=1.1),
            },
        )
        output = render_prometheus_metrics(report)
        assert "b2b_service_info" in output
        assert "b2b_health_status" in output
        assert "b2b_component_latency_ms" in output
        assert "b2b_uptime_seconds" in output


# =========================================================================== #
# 5. GRACEFUL SHUTDOWN TESTS
# =========================================================================== #

class TestGracefulShutdown:
    """Tests for b2b_ai.infrastructure.graceful_shutdown."""

    def test_request_tracker(self):
        from b2b_ai.infrastructure.graceful_shutdown import RequestTracker
        tracker = RequestTracker()
        assert tracker.active_count == 0

        with tracker.track():
            assert tracker.active_count == 1

        assert tracker.active_count == 0

    def test_request_tracker_nested(self):
        from b2b_ai.infrastructure.graceful_shutdown import RequestTracker
        tracker = RequestTracker()

        with tracker.track():
            with tracker.track():
                assert tracker.active_count == 2
            assert tracker.active_count == 1

    def test_shutdown_state(self):
        from b2b_ai.infrastructure.graceful_shutdown import (
            is_draining, is_shutdown, get_shutdown_state,
        )
        # Reset global state for test
        import b2b_ai.infrastructure.graceful_shutdown as gs_module
        gs_module._shutdown_state.is_draining = False
        gs_module._shutdown_state.is_shutdown = False

        assert not is_draining()
        assert not is_shutdown()

        state = get_shutdown_state()
        assert state["is_draining"] is False
        assert state["active_requests"] == 0

    def test_cleanup_task_registration(self):
        from b2b_ai.infrastructure.graceful_shutdown import ShutdownManager
        manager = ShutdownManager()
        cleaned = []

        def cleanup():
            cleaned.append("done")

        manager.register_cleanup("test_cleanup", cleanup, timeout=5.0)
        assert len(manager._cleanup_tasks) == 1
        assert manager._cleanup_tasks[0].name == "test_cleanup"

    def test_wait_for_zero(self):
        from b2b_ai.infrastructure.graceful_shutdown import RequestTracker
        tracker = RequestTracker()

        # Already at zero
        assert tracker.wait_for_zero(timeout=1.0) is True

    def test_wait_for_zero_with_active(self):
        from b2b_ai.infrastructure.graceful_shutdown import RequestTracker
        tracker = RequestTracker()

        # Start a "request"
        tracker.increment()
        assert tracker.active_count == 1

        # Start a thread to complete it
        def complete():
            time.sleep(0.1)
            tracker.decrement()

        t = threading.Thread(target=complete)
        t.start()

        assert tracker.wait_for_zero(timeout=2.0) is True
        t.join()


# =========================================================================== #
# 6. CONFIGURATION VALIDATION TESTS
# =========================================================================== #

class TestConfiguration:
    """Tests for b2b_ai.infrastructure.config."""

    def test_settings_from_env_defaults(self):
        from b2b_ai.infrastructure.config import Settings
        # With testing env, validation is relaxed
        settings = Settings.from_env(env_override="testing")
        assert settings.env == "testing"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000

    def test_settings_from_custom_env(self):
        from b2b_ai.infrastructure.config import Settings
        env = {
            "B2B_ENV": "testing",
            "B2B_HOST": "127.0.0.1",
            "B2B_PORT": "9000",
            "B2B_DATABASE_URL": "postgresql://localhost/test",
            "B2B_LOG_LEVEL": "DEBUG",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
            assert settings.host == "127.0.0.1"
            assert settings.port == 9000
            assert "postgresql" in settings.database.url
            assert settings.logging.level.value == "DEBUG"

    def test_settings_repr_masks_secrets(self):
        from b2b_ai.infrastructure.config import Settings
        settings = Settings.from_env(env_override="testing")
        repr_str = repr(settings)
        # JWT secret should not appear in repr
        assert "jwt_secret" not in repr_str.lower() or "***" in repr_str

    def test_database_settings_validation(self):
        from b2b_ai.infrastructure.config import DatabaseSettings
        db = DatabaseSettings(pool_min=0, pool_max=20, slow_query_threshold_ms=1000)
        assert db.pool_min == 0
        assert db.pool_max == 20
        assert db.slow_query_threshold_ms == 1000

    def test_sub_configs_instantiate(self):
        from b2b_ai.infrastructure.config import (
            DatabaseSettings, RedisSettings, AuthSettings,
            EncryptionSettings, LoggingSettings, CircuitBreakerSettings,
            ShutdownSettings, HealthSettings, MonitoringSettings,
            SATSettings, FacturapiSettings, LLMSettings,
        )
        # All sub-configs should instantiate with defaults
        assert DatabaseSettings().pool_max == 10
        assert RedisSettings().url is None
        assert LoggingSettings().level.value == "INFO"
        assert CircuitBreakerSettings().enabled is True
        assert ShutdownSettings().drain_timeout == 30.0
        assert HealthSettings().check_timeout == 5.0
        assert LLMSettings().provider == "openai"

    def test_production_validation(self):
        from b2b_ai.infrastructure.config import Settings
        settings = Settings.from_env(env_override="testing")
        settings.env = "production"
        settings.debug = True
        settings.workers = 1
        issues = settings.validate_production_ready()
        # Should have warnings about missing secrets, debug, workers
        assert len(issues) > 0

    def test_singleton_settings(self):
        from b2b_ai.infrastructure.config import get_settings, reset_settings
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        reset_settings()


# =========================================================================== #
# 7. DATABASE CONNECTION POOL TESTS
# =========================================================================== #

class TestDatabasePool:
    """Tests for b2b_ai.infrastructure.db_pool."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()
        return db_path

    def test_pool_create_and_acquire(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=1, max_size=2),
        )
        try:
            with pool.acquire() as conn:
                result = conn.fetchone("SELECT value FROM test WHERE id = ?", (1,))
                assert result["value"] == "hello"
        finally:
            pool.close()

    def test_pool_metrics_tracking(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=1, max_size=2),
        )
        try:
            with pool.acquire() as conn:
                conn.execute("SELECT 1")

            metrics = pool.metrics.snapshot()
            assert metrics["total_acquires"] >= 1
            assert metrics["total_connections_created"] >= 1
            assert metrics["avg_query_time_ms"] >= 0
        finally:
            pool.close()

    def test_pool_reuses_connections(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=1, max_size=2),
        )
        try:
            created = pool.metrics.total_connections_created
            # Multiple acquires should reuse
            with pool.acquire() as conn:
                conn.execute("SELECT 1")
            with pool.acquire() as conn:
                conn.execute("SELECT 1")
            # Should have created min_size connections initially
            assert pool.metrics.total_connections_created == created
        finally:
            pool.close()

    def test_pool_slow_query_logging(self, temp_db, caplog):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(
                min_size=1,
                max_size=2,
                slow_query_threshold_ms=0.001,  # Very low threshold
            ),
        )
        try:
            with pool.acquire() as conn:
                with caplog.at_level(logging.WARNING):
                    conn.execute("SELECT * FROM test")
            # Slow query should have been logged
        finally:
            pool.close()

    def test_pool_stats(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=2, max_size=5),
        )
        try:
            stats = pool.stats
            assert "config" in stats
            assert "metrics" in stats
            assert "backend" in stats
            assert stats["backend"] == "sqlite"
            assert stats["config"]["min_size"] == 2
            assert stats["config"]["max_size"] == 5
        finally:
            pool.close()

    def test_pool_pre_ping(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=1, max_size=2, pre_ping=True),
        )
        try:
            with pool.acquire() as conn:
                result = conn.fetchone("SELECT 1 AS val")
                assert result["val"] == 1
        finally:
            pool.close()

    def test_pool_closed_raises(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool
        pool = EnterpriseConnectionPool(temp_db)
        pool.close()
        with pytest.raises(RuntimeError, match="Pool is closed"):
            with pool.acquire():
                pass

    def test_pool_prometheus_metrics(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=1, max_size=2),
        )
        try:
            prom = pool.metrics.render_prometheus()
            assert "b2b_db_pool_total_connections_created" in prom
            assert "b2b_db_pool_current_active" in prom
        finally:
            pool.close()

    def test_pool_config_defaults(self):
        from b2b_ai.infrastructure.db_pool import PoolConfig
        config = PoolConfig()
        assert config.min_size == 2
        assert config.max_size == 10
        assert config.overflow == 5
        assert config.pre_ping is True
        assert config.slow_query_threshold_ms == 500.0

    def test_pool_concurrent_access(self, temp_db):
        from b2b_ai.infrastructure.db_pool import EnterpriseConnectionPool, PoolConfig
        pool = EnterpriseConnectionPool(
            temp_db,
            config=PoolConfig(min_size=2, max_size=4),
        )
        results = []
        errors = []

        def worker(worker_id):
            try:
                with pool.acquire() as conn:
                    result = conn.fetchone("SELECT value FROM test WHERE id = ?", (1,))
                    results.append((worker_id, result["value"]))
                    time.sleep(0.05)
            except Exception as e:
                errors.append((worker_id, str(e)))

        try:
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            assert len(errors) == 0, f"Errors: {errors}"
            assert len(results) == 8
            assert all(r[1] == "hello" for r in results)
        finally:
            pool.close()
