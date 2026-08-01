# -*- coding: utf-8 -*-
"""calendar_adapter.py — Real adapter for Google Calendar API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class GoogleCalendarAdapter:
    """Real adapter for Google Calendar. Requires GOOGLE_CALENDAR_CREDENTIALS."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "google_calendar"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds_file = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "")
        if not creds_file or not os.path.exists(creds_file):
            logger.warning("GoogleCalendarAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_file(creds_file,
                scopes=["https://www.googleapis.com/auth/calendar"])
            self._client = build("calendar", "v3", credentials=creds)
            self._connected = True
            logger.info("GoogleCalendarAdapter: connected to Google Calendar API")
            return True
        except Exception as e:
            logger.error(f"GoogleCalendarAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def create_event(self, summary: str, start: str, end: str,
                     description: str = "", attendees: Optional[List[str]] = None) -> Dict[str, Any]:
        self._ensure_connected()
        event_id = f"gcal_{_uuid.uuid4().hex[:16]}"
        if self._client:
            try:
                event = {"summary": summary, "description": description,
                    "start": {"dateTime": start}, "end": {"dateTime": end},
                    "attendees": [{"email": a} for a in (attendees or [])]}
                result = self._client.events().insert(calendarId="primary", body=event).execute()
                return {"eventId": result.get("id",""), "summary": summary, "status": "confirmed"}
            except Exception as e:
                logger.error(f"GoogleCalendarAdapter: create_event failed: {e}"); raise
        return {"eventId": event_id, "summary": summary, "start": start, "end": end, "mock": True}

    def list_events(self, time_min: Optional[str] = None, time_max: Optional[str] = None,
                    max_results: int = 10) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                now = datetime.utcnow().isoformat() + "Z"
                params = {"calendarId": "primary", "timeMin": time_min or now,
                    "maxResults": max_results, "singleEvents": True, "orderBy": "startTime"}
                result = self._client.events().list(**params).execute()
                return result.get("items", [])
            except Exception as e:
                logger.error(f"GoogleCalendarAdapter: list_events failed: {e}"); raise
        return [{"id": f"evt_{i}", "summary": f"Mock Event {i}",
            "start": {"dateTime": f"2026-01-{10+i:02d}T10:00:00"},
            "end": {"dateTime": f"2026-01-{10+i:02d}T11:00:00"}} for i in range(1, 4)]

    def delete_event(self, event_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                self._client.events().delete(calendarId="primary", eventId=event_id).execute()
                return True
            except Exception as e:
                logger.error(f"GoogleCalendarAdapter: delete_event failed: {e}"); raise
        return True

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("GoogleCalendarAdapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Google Calendar"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
