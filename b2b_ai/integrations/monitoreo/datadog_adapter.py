# -*- coding: utf-8 -*-
"""datadog_adapter.py — Datadog monitoring adapter (stub/mock)."""
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


class DatadogAdapter(MonitoringAdapter):
    """Datadog monitoring adapter. Requires DD_API_KEY."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.DATADOG,
            environment=os.environ.get("B2B_ENV", "development"),
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        api_key = (credentials or {}).get("api_key") or os.environ.get("DD_API_KEY", "")
        if not api_key:
            logger.warning("DatadogAdapter: no DD_API_KEY — MOCK mode")
        self._connected = True
        return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None, level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        error_id = f"datadog_{_uuid.uuid4().hex[:16]}"
        import traceback
        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        logger.error(f"DatadogAdapter: {type(error).__name__}: {error}")
        return ErrorReport(id=error_id, message=f"{type(error).__name__}: {error}", level=level, stacktrace=stacktrace, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO, context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        error_id = f"datadog_msg_{_uuid.uuid4().hex[:16]}"
        logger.info(f"DatadogAdapter: [{level.value}] {message}")
        return ErrorReport(id=error_id, message=message, level=level, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())
