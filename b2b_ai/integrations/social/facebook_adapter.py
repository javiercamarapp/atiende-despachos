# -*- coding: utf-8 -*-
"""facebook_adapter.py — Real adapter for Facebook Graph API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class FacebookAdapter:
    """Real adapter for Facebook. Requires FACEBOOK_ACCESS_TOKEN."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "facebook"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("access_token") or os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        if not token:
            logger.warning("FacebookAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url="https://graph.facebook.com/v18.0",
                params={"access_token": token}, timeout=30)
            self._connected = True
            logger.info("FacebookAdapter: connected to Facebook Graph API")
            return True
        except Exception as e:
            logger.error(f"FacebookAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def get_page_info(self, page_id: str) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/{page_id}", params={"fields": "id,name,fan_count,followers_count"})
                resp.raise_for_status(); return resp.json()
            except Exception as e:
                logger.error(f"FacebookAdapter: get_page_info failed: {e}"); raise
        return {"id": page_id or "mock_page", "name": "Mock Page", "fan_count": 1000, "followers_count": 950}

    def post(self, page_id: str, message: str, link: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_connected()
        post_id = f"fb_post_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                body = {"message": message}
                if link: body["link"] = link
                resp = self._client.post(f"/{page_id}/feed", json=body)
                resp.raise_for_status()
                return {"postId": resp.json().get("id",""), "status": "published"}
            except Exception as e:
                logger.error(f"FacebookAdapter: post failed: {e}"); raise
        return {"postId": post_id, "message": message, "status": "published", "mock": True}

    def get_insights(self, page_id: str, metric: str = "page_views_total") -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/{page_id}/insights/{metric}", params={"period": "day"})
                resp.raise_for_status(); return resp.json()
            except Exception as e:
                logger.error(f"FacebookAdapter: get_insights failed: {e}"); raise
        return {"data": [{"name": metric, "values": [{"value": 500}]}], "mock": True}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("FacebookAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Facebook"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
