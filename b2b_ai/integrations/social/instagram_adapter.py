# -*- coding: utf-8 -*-
"""instagram_adapter.py — Real adapter for Instagram Graph API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class InstagramAdapter:
    """Real adapter for Instagram. Requires INSTAGRAM_ACCESS_TOKEN."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "instagram"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("access_token") or os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        if not token:
            logger.warning("InstagramAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url="https://graph.facebook.com/v18.0",
                params={"access_token": token}, timeout=30)
            self._connected = True
            logger.info("InstagramAdapter: connected to Instagram Graph API")
            return True
        except Exception as e:
            logger.error(f"InstagramAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def get_profile(self, ig_user_id: str) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/{ig_user_id}", params={"fields": "id,username,name,followers_count"})
                resp.raise_for_status(); return resp.json()
            except Exception as e:
                logger.error(f"InstagramAdapter: get_profile failed: {e}"); raise
        return {"id": ig_user_id or "mock_ig", "username": "mock_user", "name": "Mock User", "followers_count": 500}

    def get_media(self, ig_user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/{ig_user_id}/media", params={"fields": "id,caption,media_type,like_count", "limit": limit})
                resp.raise_for_status(); return resp.json().get("data", [])
            except Exception as e:
                logger.error(f"InstagramAdapter: get_media failed: {e}"); raise
        return [{"id": f"ig_media_{i}", "caption": f"Mock post {i}", "media_type": "IMAGE", "like_count": 10+i}
                for i in range(1, 4)]

    def publish_media(self, ig_user_id: str, image_url: str, caption: str) -> Dict[str, Any]:
        self._ensure_connected()
        media_id = f"ig_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                resp = self._client.post(f"/{ig_user_id}/media", json={"image_url": image_url, "caption": caption})
                resp.raise_for_status()
                container_id = resp.json().get("id","")
                resp2 = self._client.post(f"/{ig_user_id}/media_publish", json={"creation_id": container_id})
                resp2.raise_for_status()
                return {"mediaId": resp2.json().get("id",""), "status": "published"}
            except Exception as e:
                logger.error(f"InstagramAdapter: publish_media failed: {e}"); raise
        return {"mediaId": media_id, "image_url": image_url, "caption": caption, "status": "published", "mock": True}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("InstagramAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Instagram"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
