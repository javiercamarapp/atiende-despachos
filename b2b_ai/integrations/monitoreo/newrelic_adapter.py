# -*- coding: utf-8 -*-
"""newrelic_adapter.py — New Relic monitoring adapter (stub/mock)."""
from __future__ import annotations
import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional
from b2b_ai.integrations.monitoreo.adapter import MonitoringAdapter
from b2b_ai.integrations.monitoreo.models import (
    ErrorLevel, ErrorReport, MonitoringConfig, MonitoringProvider,
)
logger = logging.getLogger(__name__)


class NewRelicAdapter(MonitoringAdapter):
    """New Relic monitoring adapter. Requires NEW_RELIC_LICENSE_KEY."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.NEW_RELIC,
            environment=os.environ.get("B2B_ENV", "development"),
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        license_key = (credentials or {}).get("license_key") or os.environ.get("NEW_RELIC_LICENSE_KEY", "")
        if not license_key:
            logger.warning("NewRelicAdapter: no NEW_RELIC_LICENSE_KEY — MOCK mode")
        self._connected = True
        return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None, level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        error_id = f"newrelic_{_uuid.uuid4().hex[:16]}"
        import traceback
        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        logger.error(f"NewRelicAdapter: {type(error).__name__}: {error}")
        return ErrorReport(id=error_id, message=f"{type(error).__name__}: {error}", level=level, stacktrace=stacktrace, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO, context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        error_id = f"newrelic_msg_{_uuid.uuid4().hex[:16]}"
        logger.info(f"NewRelicAdapter: [{level.value}] {message}")
        return ErrorReport(id=error_id, message=message, level=level, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())
