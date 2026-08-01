import os
# -*- coding: utf-8 -*-
"""
datadog_adapter.py — Adaptador mock para Datadog (infrastructure monitoring).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.monitoreo.adapter import MonitoringAdapter
from b2b_ai.integrations.monitoreo.models import (
    ErrorLevel, ErrorReport, MonitoringConfig, MonitoringProvider,
)

logger = logging.getLogger(__name__)


class DatadogAdapter(MonitoringAdapter):
    """Adaptador mock para Datadog."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(provider=MonitoringProvider.DATADOG,
                                           dsn="https://mock.datadoghq.com/api/v1")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("DatadogAdapter: conexión exitosa (mock)")
        return True

    def capture_exception(self, error: Exception, context: Optional[Dict[str, Any]] = None,
                          level: ErrorLevel = ErrorLevel.ERROR) -> ErrorReport:
        self._ensure_connected()
        return ErrorReport(id=f"dd_{_uuid.uuid4().hex[:12]}", message=str(error),
                          level=level, context=context or {}, environment=self.config.environment,
                          release=self.config.release, timestamp=datetime.now().isoformat())

    def capture_message(self, message: str, level: ErrorLevel = ErrorLevel.INFO,
                        context: Optional[Dict[str, Any]] = None) -> ErrorReport:
        self._ensure_connected()
        return ErrorReport(id=f"dd_msg_{_uuid.uuid4().hex[:12]}", message=message,
                          level=level, context=context or {}, environment=self.config.environment,
                          release=self.config.release, timestamp=datetime.now().isoformat())
