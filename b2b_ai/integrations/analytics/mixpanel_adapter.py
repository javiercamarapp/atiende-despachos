# -*- coding: utf-8 -*-
"""
mixpanel_adapter.py — Adaptador mock para Mixpanel (product analytics).
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


class MixpanelAdapter(AnalyticsAdapter):
    """Adaptador mock para Mixpanel."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(provider=AnalyticsProvider.MIXPANEL,
                                           api_key="mock_mixpanel_key", project_id="likida_mp")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("MixpanelAdapter: conexión exitosa (mock)")
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        logger.info(f"Mixpanel: track event '{event.event_name}' (mock)")
        return AnalyticsEventResult(success=True, event_id=f"mp_{_uuid.uuid4().hex[:12]}",
                                   message="Evento registrado en Mixpanel")

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        logger.info(f"Mixpanel: query '{query.metric}' (mock)")
        return AnalyticsQueryResult(data=[{"date": "2026-01-15", "events": 3200, "unique_users": 1100}],
                                   totals={"events": 96000, "unique_users": 33000})
