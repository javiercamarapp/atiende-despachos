# -*- coding: utf-8 -*-
"""amplitude_adapter.py — Amplitude analytics adapter."""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from b2b_ai.integrations.analytics.adapter import AnalyticsAdapter
from b2b_ai.integrations.analytics.models import (
    AnalyticsConfig, AnalyticsEvent, AnalyticsEventResult, AnalyticsProvider,
    AnalyticsQuery, AnalyticsQueryResult,
)

logger = logging.getLogger(__name__)


class AmplitudeAdapter(AnalyticsAdapter):
    """Amplitude analytics adapter."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(
            provider=AnalyticsProvider.AMPLITUDE,
            api_key=os.environ.get("AMPLITUDE_API_KEY", ""),
            api_secret=os.environ.get("AMPLITUDE_API_SECRET", ""),
        )
        super().__init__(config=config)
        self._track_url = "https://api2.amplitude.com/2/httpapi"

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        api_key = (credentials or {}).get("api_key") or self.config.api_key
        if not api_key:
            logger.warning("AmplitudeAdapter: missing AMPLITUDE_API_KEY — MOCK mode")
        self._connected = True
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        event_id = f"amp_{_uuid.uuid4().hex[:16]}"
        payload = {
            "api_key": self.config.api_key,
            "events": [{
                "user_id": event.user_id or "anonymous",
                "event_type": event.event_name,
                "event_properties": event.properties,
                "time": int(datetime.now().timestamp() * 1000),
            }],
        }
        try:
            resp = httpx.post(self._track_url, json=payload, timeout=self.config.timeout)
            if resp.status_code == 200 and resp.json().get("code") == 200:
                return AnalyticsEventResult(success=True, event_id=event_id)
            return AnalyticsEventResult(success=False, event_id=event_id, message=f"HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"AmplitudeAdapter: track_event failed: {e}")
            return AnalyticsEventResult(success=False, event_id=event_id, message=str(e))

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        logger.warning("AmplitudeAdapter: query() not implemented for HTTP API")
        return AnalyticsQueryResult(success=False, metadata={"message": "Use Amplitude Dashboard API for queries"})
