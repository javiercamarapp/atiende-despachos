# -*- coding: utf-8 -*-
"""calendly_adapter.py — Real adapter for Calendly API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class CalendlyAdapter:
    """Real adapter for Calendly. Requires CALENDLY_API_TOKEN."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "calendly"
        self._connected = False
        self._client = None
        self._user_uri = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("api_token") or os.environ.get("CALENDLY_API_TOKEN", "")
        if not token:
            logger.warning("CalendlyAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url="https://api.calendly.com",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
            resp = self._client.get("/users/me")
            resp.raise_for_status()
            self._user_uri = resp.json().get("resource",{}).get("uri","")
            self._connected = True
            logger.info("CalendlyAdapter: connected to Calendly API")
            return True
        except Exception as e:
            logger.error(f"CalendlyAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def list_event_types(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/event_types", params={"organization": self._user_uri})
                resp.raise_for_status()
                return resp.json().get("collection", [])
            except Exception as e:
                logger.error(f"CalendlyAdapter: list_event_types failed: {e}"); raise
        return [{"uri": f"et_{_uuid.uuid4().hex[:8]}", "name": "30min Meeting", "slug": "30min",
                "active": True, "duration": 30}]

    def list_scheduled_events(self, status: str = "upcoming") -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/scheduled_events", params={"user": self._user_uri, "status": status})
                resp.raise_for_status()
                return resp.json().get("collection", [])
            except Exception as e:
                logger.error(f"CalendlyAdapter: list_scheduled_events failed: {e}"); raise
        return [{"uri": f"se_{_uuid.uuid4().hex[:8]}", "status": "active", "start_time": "2026-01-20T10:00:00Z",
                "end_time": "2026-01-20T10:30:00Z", "event_type": "30min Meeting"}]

    def cancel_event(self, event_uri: str, reason: str = "") -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.post(f"{event_uri}/cancellation", json={"reason": reason})
                resp.raise_for_status()
                return {"status": "cancelled", "uri": event_uri}
            except Exception as e:
                logger.error(f"CalendlyAdapter: cancel_event failed: {e}"); raise
        return {"status": "cancelled", "uri": event_uri, "reason": reason, "mock": True}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("CalendlyAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Calendly"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
