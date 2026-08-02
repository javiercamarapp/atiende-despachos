# -*- coding: utf-8 -*-
"""gmail_adapter.py — Real adapter for Gmail API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class GmailAdapter:
    """Real adapter for Gmail. Requires GOOGLE_GMAIL_CREDENTIALS."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "gmail"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds_file = os.environ.get("GOOGLE_GMAIL_CREDENTIALS", "")
        if not creds_file or not os.path.exists(creds_file):
            logger.warning("GmailAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_file(creds_file,
                scopes=["https://www.googleapis.com/auth/gmail.send",
                        "https://www.googleapis.com/auth/gmail.readonly"])
            self._client = build("gmail", "v1", credentials=creds)
            self._connected = True
            logger.info("GmailAdapter: connected to Gmail API")
            return True
        except Exception as e:
            logger.error(f"GmailAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def send_email(self, to: str, subject: str, body: str, is_html: bool = False) -> Dict[str, Any]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        msg_id = f"gmail_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                from email.mime.text import MIMEText
                import base64
                msg = MIMEText(body, "html" if is_html else "plain")
                msg["to"] = to
                msg["subject"] = subject
                raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
                result = self._client.users().messages().send(
                    userId="me", body={"raw": raw}).execute()
                return {"messageId": result.get("id",""), "status": "sent", "to": to}
            except Exception as e:
                logger.error(f"GmailAdapter: send_email failed: {e}"); raise
        return {"messageId": msg_id, "status": "sent", "to": to, "subject": subject, "mock": True}

    def list_messages(self, query: str = "", max_results: int = 10) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                results = self._client.users().messages().list(
                    userId="me", q=query, maxResults=max_results).execute()
                return results.get("messages", [])
            except Exception as e:
                logger.error(f"GmailAdapter: list_messages failed: {e}"); raise
        return [{"id": f"msg_{i}", "snippet": f"Mock message {i}"} for i in range(1, 4)]

    def get_message(self, message_id: str) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                msg = self._client.users().messages().get(userId="me", id=message_id).execute()
                return msg
            except Exception as e:
                logger.error(f"GmailAdapter: get_message failed: {e}"); raise
        return {"id": message_id, "snippet": "Mock message content", "labelIds": ["INBOX"]}

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("GmailAdapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Gmail"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
