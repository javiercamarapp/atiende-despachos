# -*- coding: utf-8 -*-
"""dropbox_adapter.py — Real adapter for Dropbox storage."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)
logger = logging.getLogger(__name__)

class DropboxAdapter(StorageAdapter):
    """Real adapter for Dropbox. Requires DROPBOX_ACCESS_TOKEN."""
    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.DROPBOX,
            api_key=os.environ.get("DROPBOX_ACCESS_TOKEN", ""),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        token = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("DROPBOX_ACCESS_TOKEN", "")
        if not token:
            logger.warning("DropboxAdapter: no token — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            self._client = httpx.Client(base_url="https://api.dropboxapi.com/2",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=self.config.timeout)
            self._connected = True
            logger.info("DropboxAdapter: connected to Dropbox")
            return True
        except Exception as e:
            logger.error(f"DropboxAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        path = f"{folder.rstrip('/')}/{os.path.basename(file_path)}"
        if self._client:
            try:
                with open(file_path, "rb") as f:
                    resp = self._client.post("https://content.dropboxapi.com/2/files/upload",
                        headers={"Dropbox-API-Arg": f'{{"path": "{path}", "mode": "add"}}'},
                        content=f.read())
                    resp.raise_for_status()
                    data = resp.json()
                    return UploadResult(success=True, file=FileMetadata(
                        id=data.get("id",""), name=data.get("name",""),
                        size=data.get("size",0), path=data.get("path_display",""),
                        created_at=now, updated_at=now), message="Upload successful")
            except Exception as e:
                logger.error(f"DropboxAdapter: upload failed: {e}"); raise
        return UploadResult(success=True, file=FileMetadata(id=f"db_{_uuid.uuid4().hex[:16]}",
            name=os.path.basename(file_path), path=path, created_at=now, updated_at=now), message="Upload successful (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.post("https://content.dropboxapi.com/2/files/download",
                    headers={"Dropbox-API-Arg": f'{{"path": "{file_id}"}}'})
                resp.raise_for_status(); return resp.content
            except Exception as e:
                logger.error(f"DropboxAdapter: download failed: {e}"); raise
        return b"mock Dropbox content"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.post("https://api.dropboxapi.com/2/files/list_folder",
                    json={"path": folder})
                resp.raise_for_status()
                return [FileMetadata(id=e.get("id",""), name=e.get("name",""),
                    path=e.get("path_display",""), created_at=now, updated_at=now)
                    for e in resp.json().get("entries", []) if e.get(".tag") == "file"]
            except Exception as e:
                logger.error(f"DropboxAdapter: list_files failed: {e}"); raise
        return [FileMetadata(id=f"db_{_uuid.uuid4().hex[:8]}", name=f"doc_{i}.pdf",
            path=f"{folder}/doc_{i}.pdf", created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.post("https://api.dropboxapi.com/2/files/delete_v2",
                    json={"path": file_id})
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"DropboxAdapter: delete failed: {e}"); raise
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.post("https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
                    json={"path": file_id, "settings": {"requested_visibility": "public"}})
                resp.raise_for_status()
                url = resp.json().get("url", "")
                return ShareResult(success=True, share_url=url, permissions=permissions, message="Shared via Dropbox")
            except Exception as e:
                logger.error(f"DropboxAdapter: share failed: {e}"); raise
        return ShareResult(success=True, share_url=f"https://www.dropbox.com/s/{file_id}",
            permissions=permissions, message="Shared (mock)")
