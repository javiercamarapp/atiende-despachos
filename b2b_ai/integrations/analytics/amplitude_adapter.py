# -*- coding: utf-8 -*-
"""
amplitude_adapter.py — Adaptador mock para Amplitude (product analytics).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.analytics.adapter import AnalyticsAdapter
from b2b_ai.integrations.analytics.models import (
    AnalyticsConfig, AnalyticsEvent, AnalyticsEventResult, AnalyticsProvider,
    AnalyticsQuery, AnalyticsQueryResult,
)

logger = logging.getLogger(__name__)


class AmplitudeAdapter(AnalyticsAdapter):
    """Adaptador mock para Amplitude."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(provider=AnalyticsProvider.AMPLITUDE,
                                           api_key="mock_amplitude_key", project_id="likida_amp")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("AmplitudeAdapter: conexión exitosa (mock)")
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        logger.info(f"Amplitude: track event '{event.event_name}' (mock)")
        return AnalyticsEventResult(success=True, event_id=f"amp_{_uuid.uuid4().hex[:12]}",
                                   message="Evento registrado en Amplitude")

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        logger.info(f"Amplitude: query '{query.metric}' (mock)")
        return AnalyticsQueryResult(data=[{"date": "2026-01-15", "daily_active_users": 950, "retention": 0.42}],
                                   totals={"dau": 28500, "avg_retention": 0.38})
