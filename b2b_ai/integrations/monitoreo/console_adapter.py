# -*- coding: utf-8 -*-
"""console_adapter.py — Console-based monitoring adapter (logs to stderr/stdout)."""
from __future__ import annotations
import logging
import sys
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional
from b2b_ai.integrations.monitoreo.adapter import MonitoringAdapter
from b2b_ai.integrations.monitoreo.models import (
    ErrorLevel, ErrorReport, MonitoringConfig, MonitoringProvider,
)
logger = logging.getLogger(__name__)


class ConsoleAdapter(MonitoringAdapter):
    """Console-based monitoring adapter. Logs errors to stderr."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(provider=MonitoringProvider.CONSOLE)
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("ConsoleAdapter: connected (console mode)")
        return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None, level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        error_id = f"console_{_uuid.uuid4().hex[:16]}"
        import traceback
        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        report = ErrorReport(id=error_id, message=f"{type(error).__name__}: {error}", level=level, stacktrace=stacktrace, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())
        print(f"[{level.value.upper()}] {report.message}\n{stacktrace}", file=sys.stderr)
        return report

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO, context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        error_id = f"console_msg_{_uuid.uuid4().hex[:16]}"
        report = ErrorReport(id=error_id, message=message, level=level, context=context or {}, environment=self.config.environment, timestamp=datetime.now().isoformat())
        print(f"[{level.value.upper()}] {message}", file=sys.stderr)
        return report
