# -*- coding: utf-8 -*-
"""
sentry_adapter.py — Real adapter for Sentry error tracking.

Provides SentryAdapter with actual Sentry SDK integration.
Falls back to mock if SENTRY_DSN is not set.
"""
from __future__ import annotations

import logging
import os
import traceback
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.monitoreo.adapter import MonitoringAdapter
from b2b_ai.integrations.monitoreo.models import (
    ErrorLevel, ErrorReport, MonitoringConfig, MonitoringProvider,
)

logger = logging.getLogger(__name__)


class SentryAdapter(MonitoringAdapter):
    """Real adapter for Sentry error tracking. Requires SENTRY_DSN."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.SENTRY,
            dsn=os.environ.get("SENTRY_DSN", ""),
            environment=os.environ.get("B2B_ENV", "development"),
            release=os.environ.get("B2B_RELEASE", "b2b-ai@1.0.0"),
            sample_rate=float(os.environ.get("SENTRY_SAMPLE_RATE", "1.0")),
        )
        super().__init__(config=config)
        self._sentry_initialized = False

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        dsn = (credentials or {}).get("dsn") or self.config.dsn or os.environ.get("SENTRY_DSN", "")
        if not dsn:
            logger.warning("SentryAdapter: no DSN — MOCK mode")
            self._connected = True
            self._sentry_initialized = False
            return True
        try:
            import sentry_sdk
            from sentry_sdk.integrations.logging import LoggingIntegration
            sentry_sdk.init(
                dsn=dsn, environment=self.config.environment, release=self.config.release,
                sample_rate=self.config.sample_rate,
                integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
                traces_sample_rate=0.1,
            )
            self._sentry_initialized = True
            self._connected = True
            logger.info("SentryAdapter: connected to Sentry")
            return True
        except ImportError:
            logger.warning("SentryAdapter: sentry-sdk not installed — MOCK mode")
            self._connected = True
            self._sentry_initialized = False
            return True
        except Exception as e:
            logger.error(f"SentryAdapter: connection failed: {e}")
            self._connected = True
            self._sentry_initialized = False
            return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None, level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"sentry_{_uuid.uuid4().hex[:16]}"
        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if self._sentry_initialized:
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    if context:
                        for k, v in context.items():
                            scope.set_extra(k, v)
                    scope.set_tag("level", level.value)
                    sentry_sdk.capture_exception(error)
            except Exception as e:
                logger.error(f"SentryAdapter: capture_exception SDK failed: {e}")
        logger.error(f"SentryAdapter: captured '{type(error).__name__}: {error}'")
        return ErrorReport(id=error_id, message=f"{type(error).__name__}: {error}", level=level, stacktrace=stacktrace, context=context or {}, environment=self.config.environment, release=self.config.release, timestamp=now)

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO, context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"sentry_msg_{_uuid.uuid4().hex[:16]}"
        if self._sentry_initialized:
            try:
                import sentry_sdk
                lmap = {ErrorLevel.DEBUG: "debug", ErrorLevel.INFO: "info", ErrorLevel.WARNING: "warning", ErrorLevel.ERROR: "error", ErrorLevel.FATAL: "fatal"}
                sentry_sdk.capture_message(message, level=lmap.get(level, "info"), extras=context or {})
            except Exception as e:
                logger.error(f"SentryAdapter: capture_message SDK failed: {e}")
        logger.info(f"SentryAdapter: captured [{level.value}] '{message}'")
        return ErrorReport(id=error_id, message=message, level=level, context=context or {}, environment=self.config.environment, release=self.config.release, timestamp=now)
