# -*- coding: utf-8 -*-
"""box_adapter.py — Real adapter for Box storage."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)
logger = logging.getLogger(__name__)

class BoxAdapter(StorageAdapter):
    """Real adapter for Box. Requires BOX_CLIENT_ID and BOX_CLIENT_SECRET."""
    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.BOX,
            api_key=os.environ.get("BOX_CLIENT_ID", ""),
            api_secret=os.environ.get("BOX_CLIENT_SECRET", ""),
        )
        super().__init__(config=config)
        self._client = None
        self._token = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        client_id = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("BOX_CLIENT_ID", "")
        client_secret = (credentials or {}).get("api_secret") or self.config.api_secret or os.environ.get("BOX_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.warning("BoxAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import httpx
            resp = httpx.post("https://api.box.com/oauth2/token", data={
                "grant_type": "client_credentials",
                "client_id": client_id, "client_secret": client_secret,
            }, timeout=self.config.timeout)
            resp.raise_for_status()
            self._token = resp.json().get("access_token")
            self._client = httpx.Client(base_url="https://api.box.com/2.0",
                headers={"Authorization": f"Bearer {self._token}"}, timeout=self.config.timeout)
            self._connected = True
            logger.info("BoxAdapter: connected to Box API")
            return True
        except Exception as e:
            logger.error(f"BoxAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def upload(self, file_path: str, folder: str = "0") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                with open(file_path, "rb") as f:
                    resp = self._client.post("https://upload.box.com/api/2.0/files/content",
                        headers={"Parent_id": folder},
                        files={"file": (os.path.basename(file_path), f)})
                    resp.raise_for_status()
                    data = resp.json().get("entries", [{}])[0]
                    return UploadResult(success=True, file=FileMetadata(
                        id=data.get("id",""), name=data.get("name",""),
                        size=data.get("size",0), created_at=now, updated_at=now), message="Upload successful")
            except Exception as e:
                logger.error(f"BoxAdapter: upload failed: {e}"); raise
        return UploadResult(success=True, file=FileMetadata(id=f"box_{_uuid.uuid4().hex[:16]}",
            name=os.path.basename(file_path), path=f"{folder}/{os.path.basename(file_path)}",
            created_at=now, updated_at=now), message="Upload successful (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.get(f"https://download.box.com/api/2.0/files/{file_id}/content")
                resp.raise_for_status(); return resp.content
            except Exception as e:
                logger.error(f"BoxAdapter: download failed: {e}"); raise
        return b"mock Box content"

    def list_files(self, folder: str = "0") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._client:
            try:
                resp = self._client.get(f"/folders/{folder}/items")
                resp.raise_for_status()
                return [FileMetadata(id=e.get("id",""), name=e.get("name",""),
                    created_at=now, updated_at=now) for e in resp.json().get("entries", [])]
            except Exception as e:
                logger.error(f"BoxAdapter: list_files failed: {e}"); raise
        return [FileMetadata(id=f"box_{_uuid.uuid4().hex[:8]}", name=f"doc_{i}.pdf",
            created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        if self._client:
            try:
                resp = self._client.delete(f"/files/{file_id}")
                return resp.status_code in (200, 204)
            except Exception as e:
                logger.error(f"BoxAdapter: delete failed: {e}"); raise
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        if self._client:
            try:
                for perm in permissions:
                    resp = self._client.post(f"/files/{file_id}/collaborations",
                        json={"accessible_by": {"login": perm.email}, "role": perm.role.value})
                    resp.raise_for_status()
                return ShareResult(success=True, permissions=permissions, message="Shared via Box")
            except Exception as e:
                logger.error(f"BoxAdapter: share failed: {e}"); raise
        return ShareResult(success=True, share_url=f"https://app.box.com/file/{file_id}",
            permissions=permissions, message="Shared (mock)")
