# -*- coding: utf-8 -*-
"""
google_analytics_adapter.py — Adaptador mock para Google Analytics (GA4).
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


class GoogleAnalyticsAdapter(AnalyticsAdapter):
    """Adaptador mock para Google Analytics (GA4)."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(provider=AnalyticsProvider.GOOGLE_ANALYTICS,
                                           api_key="mock_ga_key", property_id="GA-12345")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("GoogleAnalyticsAdapter: conexión exitosa (mock)")
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        logger.info(f"GA: track event '{event.event_name}' (mock)")
        return AnalyticsEventResult(success=True, event_id=f"ga_{_uuid.uuid4().hex[:12]}",
                                   message="Evento registrado en GA4")

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        logger.info(f"GA: query '{query.metric}' (mock)")
        return AnalyticsQueryResult(data=[{"date": "2026-01-15", "sessions": 1500, "users": 800}],
                                   totals={"sessions": 45000, "users": 24000})
