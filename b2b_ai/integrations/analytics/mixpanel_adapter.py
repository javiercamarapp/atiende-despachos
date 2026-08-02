# -*- coding: utf-8 -*-
"""mixpanel_adapter.py — Mixpanel analytics adapter."""
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


class MixpanelAdapter(AnalyticsAdapter):
    """Mixpanel analytics adapter."""

    def __init__(self, config: Optional[AnalyticsConfig] = None):
        config = config or AnalyticsConfig(
            provider=AnalyticsProvider.MIXPANEL,
            api_key=os.environ.get("MIXPANEL_TOKEN", ""),
            api_secret=os.environ.get("MIXPANEL_API_SECRET", ""),
        )
        super().__init__(config=config)
        self._track_url = "https://api.mixpanel.com/track"
        self._query_url = "https://mixpanel.com/api/2.0"

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("token") or self.config.api_key
        if not token:
            logger.warning("MixpanelAdapter: missing MIXPANEL_TOKEN — MOCK mode")
        self._connected = True
        return True

    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        self._ensure_connected()
        event_id = f"mp_{_uuid.uuid4().hex[:16]}"
        payload = {
            "event": event.event_name,
            "properties": {
                "token": self.config.api_key,
                "distinct_id": event.user_id or "anonymous",
                "time": int(datetime.now().timestamp() * 1000),
                **event.properties,
            },
        }
        try:
            import base64, json
            encoded = base64.b64encode(json.dumps(payload).encode()).decode()
            resp = httpx.get(f"{self._track_url}?data={encoded}", timeout=self.config.timeout)
            if resp.status_code == 200 and resp.json().get("status") == 1:
                return AnalyticsEventResult(success=True, event_id=event_id)
            return AnalyticsEventResult(success=False, event_id=event_id, message=f"HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"MixpanelAdapter: track_event failed: {e}")
            return AnalyticsEventResult(success=False, event_id=event_id, message=str(e))

    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        self._ensure_connected()
        try:
            auth = (self.config.api_key, self.config.api_secret or "")
            resp = httpx.get(f"{self._query_url}/events", params={"event": f'["{query.metric}"]'}, auth=auth, timeout=self.config.timeout)
            if resp.status_code == 200:
                return AnalyticsQueryResult(success=True, data=resp.json().get("data", {}).get("values", {}))
            return AnalyticsQueryResult(success=False, metadata={"message": f"HTTP {resp.status_code}"})
        except Exception as e:
            logger.error(f"MixpanelAdapter: query failed: {e}")
            return AnalyticsQueryResult(success=False, metadata={"message": str(e)})
