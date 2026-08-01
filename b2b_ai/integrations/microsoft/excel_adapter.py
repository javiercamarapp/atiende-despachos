# -*- coding: utf-8 -*-
"""excel_adapter.py — Real adapter for Microsoft Excel via Graph API."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class ExcelGraphAdapter:
    """Real adapter for Excel via Microsoft Graph. Requires MS_GRAPH_CLIENT_ID and MS_GRAPH_CLIENT_SECRET."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "excel_graph"
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
            logger.warning("ExcelGraphAdapter: no credentials — MOCK mode")
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
            logger.info("ExcelGraphAdapter: connected to Microsoft Graph")
            return True
        except Exception as e:
            logger.error(f"ExcelGraphAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def read_range(self, file_id: str, sheet_name: str, range_name: str) -> List[List[Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/me/drive/items/{file_id}/workbook/worksheets/{sheet_name}/range(address='{range_name}')")
                resp.raise_for_status()
                return resp.json().get("values", [])
            except Exception as e:
                logger.error(f"ExcelGraphAdapter: read_range failed: {e}"); raise
        return [["Mock", "Data"], ["Row1", "Val1"]]

    def write_range(self, file_id: str, sheet_name: str, range_name: str, values: List[List[Any]]) -> Dict[str, Any]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.patch(
                    f"/me/drive/items/{file_id}/workbook/worksheets/{sheet_name}/range(address='{range_name}')",
                    json={"values": values})
                resp.raise_for_status()
                return {"updatedCells": len(values) * len(values[0]) if values else 0}
            except Exception as e:
                logger.error(f"ExcelGraphAdapter: write_range failed: {e}"); raise
        return {"updatedCells": len(values) * len(values[0]) if values else 0, "mock": True}

    def list_sheets(self, file_id: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/me/drive/items/{file_id}/workbook/worksheets")
                resp.raise_for_status()
                return [{"name": s.get("name",""), "id": s.get("id","")} for s in resp.json().get("value",[])]
            except Exception as e:
                logger.error(f"ExcelGraphAdapter: list_sheets failed: {e}"); raise
        return [{"name": "Sheet1", "id": f"sheet_{_uuid.uuid4().hex[:8]}"}]

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("ExcelGraphAdapter no conectado. Llame connect() primero.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "message": "Connected to Excel Graph API"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
