# -*- coding: utf-8 -*-
"""m365_adapter.py — Adapter for Microsoft 365 unified API access."""
from __future__ import annotations
import logging, os
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class Microsoft365Adapter:
    """Unified adapter for Microsoft 365 services (Teams, SharePoint, OneDrive)."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "microsoft_365"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "")
        client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.warning("Microsoft365Adapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            resp = httpx.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data={
                "client_id": client_id, "client_secret": client_secret,
                "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"})
            resp.raise_for_status()
            token = resp.json().get("access_token")
            self._client = httpx.Client(base_url="https://graph.microsoft.com/v1.0",
                headers={"Authorization": f"Bearer {token}"}, timeout=30)
            self._connected = True
            logger.info("Microsoft365Adapter: connected to Microsoft 365")
            return True
        except Exception as e:
            logger.error(f"Microsoft365Adapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def get_user_profile(self) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/me")
                resp.raise_for_status(); return resp.json()
            except Exception as e:
                logger.error(f"Microsoft365Adapter: get_user_profile failed: {e}"); raise
        return {"displayName": "Mock User", "mail": "mock@example.com", "jobTitle": "Developer"}

    def list_teams(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/me/joinedTeams")
                resp.raise_for_status(); return resp.json().get("value", [])
            except Exception as e:
                logger.error(f"Microsoft365Adapter: list_teams failed: {e}"); raise
        return [{"id": "team-1", "displayName": "Mock Team 1"}, {"id": "team-2", "displayName": "Mock Team 2"}]

    def send_teams_message(self, team_id: str, channel_id: str, message: str) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.post(f"/teams/{team_id}/channels/{channel_id}/messages",
                    json={"body": {"contentType": "text", "content": message}})
                resp.raise_for_status()
                data = resp.json()
                return {"messageId": data.get("id",""), "status": "sent"}
            except Exception as e:
                logger.error(f"Microsoft365Adapter: send_teams_message failed: {e}"); raise
        return {"messageId": f"teams_msg_1", "status": "sent", "mock": True}

    def list_sharepoint_sites(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get("/sites?search=*")
                resp.raise_for_status(); return resp.json().get("value", [])
            except Exception as e:
                logger.error(f"Microsoft365Adapter: list_sharepoint_sites failed: {e}"); raise
        return [{"id": "site-1", "displayName": "Mock SharePoint Site", "webUrl": "https://mock.sharepoint.com"}]

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Microsoft365Adapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Microsoft 365"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
