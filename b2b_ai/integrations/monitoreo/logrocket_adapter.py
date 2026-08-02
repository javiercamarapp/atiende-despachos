# -*- coding: utf-8 -*-
"""logrocket_adapter.py — LogRocket monitoring adapter (stub/mock)."""
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


class LogRocketAdapter(MonitoringAdapter):
    """LogRocket monitoring adapter. Requires LOGROCKET_APP_ID."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.LOGROCKET,
            environment=os.environ.get("B2B_ENV", "development"),
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        app_id = (credentials or {}).get("app_id") or os.environ.get("LOGROCKET_APP_ID", "")
        if not app_id:
            logger.warning("LogRocketAdapter: no LOGROCKET_APP_ID — MOCK mode")
        self._connected = True
        return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None, level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        error_id = f"logrocket_{_uuid.uuid4().hex[:16]}"
        import traceback
        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        logger.error(f"LogRocketAdapter: {type(error).__name__}: {error}")
        return ErrorReport(id=error_id, message=f"{type(error).__name__}: {error}", level=level, stacktrace=stacktrace, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO, context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        error_id = f"logrocket_msg_{_uuid.uuid4().hex[:16]}"
        logger.info(f"LogRocketAdapter: [{level.value}] {message}")
        return ErrorReport(id=error_id, message=message, level=level, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())
