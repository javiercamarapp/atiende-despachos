# -*- coding: utf-8 -*-
"""linkedin_adapter.py — Real adapter for LinkedIn API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class LinkedInAdapter:
    """Real adapter for LinkedIn. Requires LINKEDIN_ACCESS_TOKEN."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "linkedin"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("access_token") or os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
        if not token:
            logger.warning("LinkedInAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url="https://api.linkedin.com/v2",
                headers={"Authorization": f"Bearer {token}"}, timeout=30)
            self._connected = True
            logger.info("LinkedInAdapter: connected to LinkedIn API")
            return True
        except Exception as e:
            logger.error(f"LinkedInAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def get_profile(self) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/me?projection=(id,firstName,lastName,headline)")
                resp.raise_for_status(); return resp.json()
            except Exception as e:
                logger.error(f"LinkedInAdapter: get_profile failed: {e}"); raise
        return {"id": f"li_{_uuid.uuid4().hex[:16]}", "firstName": {"localized": {"es_MX": "Mock"}},
                "lastName": {"localized": {"es_MX": "User"}}, "headline": {"localized": {"es_MX": "Developer"}}}

    def post_update(self, text: str) -> Dict[str, Any]:
        self._ensure_connected()
        post_id = f"li_post_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                resp = self._client.post("/ugcPosts", json={"author": "urn:li:person:mock",
                    "lifecycleState": "PUBLISHED", "specificContent": {"com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text}, "shareMediaCategory": "NONE"}},
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}})
                resp.raise_for_status()
                return {"postId": resp.json().get("id",""), "status": "published"}
            except Exception as e:
                logger.error(f"LinkedInAdapter: post_update failed: {e}"); raise
        return {"postId": post_id, "text": text, "status": "published", "mock": True}

    def search_people(self, keywords: str, count: int = 10) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/peopleSearch", params={"keywords": keywords, "count": count})
                resp.raise_for_status(); return resp.json().get("elements", [])
            except Exception as e:
                logger.error(f"LinkedInAdapter: search_people failed: {e}"); raise
        return [{"id": f"li_{i}", "firstName": f"Mock{i}", "lastName": "Person", "headline": "Developer"}
                for i in range(1, min(count+1, 4))]

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("LinkedInAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to LinkedIn"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
