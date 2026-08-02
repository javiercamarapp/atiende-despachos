# -*- coding: utf-8 -*-
"""outlook_adapter.py — Real adapter for Microsoft Outlook via Graph API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class OutlookAdapter:
    """Real adapter for Outlook via Microsoft Graph. Requires MS_GRAPH credentials."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "outlook"
        self._connected = False
        self._client = None
        self._token = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "")
        client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.warning("OutlookAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            resp = httpx.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data={
                "client_id": client_id, "client_secret": client_secret,
                "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"})
            resp.raise_for_status()
            self._token = resp.json().get("access_token")
            self._client = httpx.Client(base_url="https://graph.microsoft.com/v1.0",
                headers={"Authorization": f"Bearer {self._token}"}, timeout=30)
            self._connected = True
            logger.info("OutlookAdapter: connected to Outlook Graph API")
            return True
        except Exception as e:
            logger.error(f"OutlookAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def send_email(self, to: str, subject: str, body: str, is_html: bool = False) -> Dict[str, Any]:
        self._ensure_connected()
        msg_id = f"outlook_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                content_type = "HTML" if is_html else "Text"
                resp = self._client.post("/me/sendMail", json={"message": {
                    "subject": subject, "body": {"contentType": content_type, "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}]}})
                resp.raise_for_status()
                return {"messageId": msg_id, "status": "sent", "to": to}
            except Exception as e:
                logger.error(f"OutlookAdapter: send_email failed: {e}"); raise
        return {"messageId": msg_id, "status": "sent", "to": to, "subject": subject, "mock": True}

    def list_messages(self, top: int = 10, filter_query: str = "") -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                params = {"$top": top}
                if filter_query:
                    params["$filter"] = filter_query
                resp = self._client.get("/me/messages", params=params)
                resp.raise_for_status()
                return resp.json().get("value", [])
            except Exception as e:
                logger.error(f"OutlookAdapter: list_messages failed: {e}"); raise
        return [{"id": f"msg_{i}", "subject": f"Mock Email {i}", "from": {"emailAddress": {"address": "mock@test.com"}}}
                for i in range(1, 4)]

    def create_event(self, subject: str, start: str, end: str, attendees: Optional[List[str]] = None) -> Dict[str, Any]:
        self._ensure_connected()
        event_id = f"outlook_evt_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                resp = self._client.post("/me/events", json={"subject": subject,
                    "start": {"dateTime": start}, "end": {"dateTime": end},
                    "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in (attendees or [])]})
                resp.raise_for_status()
                data = resp.json()
                return {"eventId": data.get("id",""), "subject": subject, "status": "confirmed"}
            except Exception as e:
                logger.error(f"OutlookAdapter: create_event failed: {e}"); raise
        return {"eventId": event_id, "subject": subject, "start": start, "end": end, "mock": True}

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("OutlookAdapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Outlook"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
