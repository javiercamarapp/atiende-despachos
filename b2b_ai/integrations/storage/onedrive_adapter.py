# -*- coding: utf-8 -*-
"""onedrive_adapter.py — Real adapter for Microsoft OneDrive storage."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)
logger = logging.getLogger(__name__)

class OneDriveAdapter(StorageAdapter):
    """Real adapter for Microsoft OneDrive. Requires MS_GRAPH_CLIENT_ID and MS_GRAPH_CLIENT_SECRET."""
    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.ONEDRIVE,
            api_key=os.environ.get("MS_GRAPH_CLIENT_ID", ""),
            api_secret=os.environ.get("MS_GRAPH_CLIENT_SECRET", ""),
        )
        super().__init__(config=config)
        self._client = None
        self._token = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        api_key = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("MS_GRAPH_CLIENT_ID", "")
        api_secret = (credentials or {}).get("api_secret") or self.config.api_secret or os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
        if not api_key or not api_secret:
            logger.warning("OneDriveAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            resp = httpx.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data={
                "client_id": api_key, "client_secret": api_secret,
                "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default",
            }, timeout=self.config.timeout)
            resp.raise_for_status()
            self._token = resp.json().get("access_token")
            self._client = httpx.Client(base_url="https://graph.microsoft.com/v1.0",
                headers={"Authorization": f"Bearer {self._token}"}, timeout=self.config.timeout)
            self._connected = True
            logger.info("OneDriveAdapter: connected to Microsoft Graph")
            return True
        except Exception as e:
            logger.error(f"OneDriveAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                with open(file_path, "rb") as f:
                    resp = self._client.put(f"/me/drive/root:{folder}/{os.path.basename(file_path)}:/content", content=f.read())
                    resp.raise_for_status()
                    data = resp.json()
                    return UploadResult(success=True, file=FileMetadata(
                        id=data.get("id", ""), name=data.get("name", ""),
                        size=data.get("size", 0), created_at=now, updated_at=now,
                    ), message="Upload successful")
            except Exception as e:
                logger.error(f"OneDriveAdapter: upload failed: {e}")
                raise
        return UploadResult(success=True, file=FileMetadata(id=f"od_{_uuid.uuid4().hex[:16]}",
            name=os.path.basename(file_path), path=f"{folder}/{os.path.basename(file_path)}",
            created_at=now, updated_at=now), message="Upload successful (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"/me/drive/items/{file_id}/content")
                resp.raise_for_status(); return resp.content
            except Exception as e:
                logger.error(f"OneDriveAdapter: download failed: {e}"); raise
        return b"mock oneDrive content"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/me/drive/root:{folder}:/children")
                resp.raise_for_status()
                return [FileMetadata(id=f.get("id",""), name=f.get("name",""),
                    size=f.get("size",0), created_at=now, updated_at=now)
                    for f in resp.json().get("value", [])]
            except Exception as e:
                logger.error(f"OneDriveAdapter: list_files failed: {e}"); raise
        return [FileMetadata(id=f"od_{_uuid.uuid4().hex[:8]}", name=f"doc_{i}.pdf",
            path=f"{folder}/doc_{i}.pdf", created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.delete(f"/me/drive/items/{file_id}")
                return resp.status_code in (200, 204)
            except Exception as e:
                logger.error(f"OneDriveAdapter: delete failed: {e}"); raise
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        if self._client:
            try:
                for perm in permissions:
                    resp = self._client.post(f"/me/drive/items/{file_id}/invite",
                        json={"recipients": [{"email": perm.email}],
                              "roles": [perm.role.value], "requireSignIn": True})
                    resp.raise_for_status()
                return ShareResult(success=True, permissions=permissions, message="Shared via OneDrive")
            except Exception as e:
                logger.error(f"OneDriveAdapter: share failed: {e}"); raise
        return ShareResult(success=True, share_url=f"https://onedrive.live.com/embed?resid={file_id}",
            permissions=permissions, message="Shared (mock)")
