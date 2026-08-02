# -*- coding: utf-8 -*-
"""google_analytics_adapter.py — Google Analytics 4 adapter."""
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


class GoogleAnalyticsAdapter(AnalyticsAdapter):
    """Google Analytics 4 Measurement Protocol adapter."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(
            provider=AnalyticsProvider.GOOGLE_ANALYTICS,
            api_key=os.environ.get("GA_MEASUREMENT_ID", ""),
            api_secret=os.environ.get("GA_API_SECRET", ""),
        )
        super().__init__(config=config)
        self._base_url = "https://www.google-analytics.com/mp/collect"

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        mid = (credentials or {}).get("measurement_id") or self.config.api_key
        secret = (credentials or {}).get("api_secret") or self.config.api_secret
        if not mid or not secret:
            logger.warning("GoogleAnalyticsAdapter: missing GA_MEASUREMENT_ID or GA_API_SECRET — MOCK mode")
        self._connected = True
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        event_id = f"ga_{_uuid.uuid4().hex[:16]}"
        payload = {
            "client_id": event.user_id or f"anon_{_uuid.uuid4().hex[:12]}",
            "events": [{"name": event.event_name, "params": event.properties}],
        }
        try:
            resp = httpx.post(
                f"{self._base_url}?measurement_id={self.config.api_key}&api_secret={self.config.api_secret}",
                json=payload, timeout=self.config.timeout,
            )
            if resp.status_code in (200, 204):
                logger.info(f"GoogleAnalyticsAdapter: event '{event.event_name}' sent")
                return AnalyticsEventResult(success=True, event_id=event_id)
            logger.warning(f"GoogleAnalyticsAdapter: HTTP {resp.status_code}")
            return AnalyticsEventResult(success=False, event_id=event_id, message=f"HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"GoogleAnalyticsAdapter: track_event failed: {e}")
            return AnalyticsEventResult(success=False, event_id=event_id, message=str(e))

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        logger.warning("GoogleAnalyticsAdapter: query() not implemented for Measurement Protocol")
        return AnalyticsQueryResult(success=False, metadata={"message": "Use GA4 Data API for queries"})
