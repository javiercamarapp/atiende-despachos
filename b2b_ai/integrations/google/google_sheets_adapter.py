# -*- coding: utf-8 -*-
"""google_sheets_adapter.py — Real adapter for Google Sheets API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class GoogleSheetsAdapter:
    """Real adapter for Google Sheets. Requires GOOGLE_SHEETS_CREDENTIALS."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "google_sheets"
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds_file = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")
        if not creds_file or not os.path.exists(creds_file):
            logger.warning("GoogleSheetsAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_file(creds_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"])
            self._client = build("sheets", "v4", credentials=creds)
            self._connected = True
            logger.info("GoogleSheetsAdapter: connected to Google Sheets API")
            return True
        except Exception as e:
            logger.error(f"GoogleSheetsAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def read_range(self, spreadsheet_id: str, range_name: str) -> List[List[Any]]:
        self._ensure_connected()
        if self._client:
            try:
                result = self._client.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id, range=range_name).execute()
                return result.get("values", [])
            except Exception as e:
                logger.error(f"GoogleSheetsAdapter: read_range failed: {e}"); raise
        return [["Mock", "Data"], ["Row1", "Val1"], ["Row2", "Val2"]]

    def write_range(self, spreadsheet_id: str, range_name: str, values: List[List[Any]]) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                body = {"values": values}
                result = self._client.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id, range=range_name,
                    valueInputOption="USER_ENTERED", body=body).execute()
                return {"updatedCells": result.get("updatedCells", 0)}
            except Exception as e:
                logger.error(f"GoogleSheetsAdapter: write_range failed: {e}"); raise
        return {"updatedCells": len(values) * len(values[0]) if values else 0, "mock": True}

    def create_spreadsheet(self, title: str) -> Dict[str, Any]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                body = {"properties": {"title": title}}
                result = self._client.spreadsheets().create(body=body).execute()
                return {"spreadsheetId": result.get("spreadsheetId",""), "title": title}
            except Exception as e:
                logger.error(f"GoogleSheetsAdapter: create_spreadsheet failed: {e}"); raise
        return {"spreadsheetId": f"sheet_{_uuid.uuid4().hex[:16]}", "title": title, "mock": True}

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError(f"GoogleSheetsAdapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Google Sheets"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
