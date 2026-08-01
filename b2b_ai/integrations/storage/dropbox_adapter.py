# -*- coding: utf-8 -*-
"""
dropbox_adapter.py — Adaptador mock para Dropbox.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.storage.adapter import StorageAdapter
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)

logger = logging.getLogger(__name__)


class DropboxAdapter(StorageAdapter):
    """Adaptador mock para Dropbox."""

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(provider=StorageProvider.DROPBOX, api_key="mock_dropbox_key")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("DropboxAdapter: conexión exitosa (mock)")
        return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        meta = FileMetadata(id=f"dbx_{_uuid.uuid4().hex[:12]}", name=file_path.split("/")[-1],
                            path=f"{folder}/{file_path.split('/')[-1]}", size=1024,
                            mime_type="application/octet-stream", created_at=now, updated_at=now)
        return UploadResult(success=True, file=meta, message="Archivo subido a Dropbox (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        return b"MOCK_DROPBOX_CONTENT"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return [FileMetadata(id=f"dbx_{_uuid.uuid4().hex[:12]}", name=f"archivo_{i}.pdf",
                            path=f"{folder}/archivo_{i}.pdf", size=1024 * i, created_at=now, updated_at=now)
                for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        logger.info(f"DropboxAdapter: eliminando archivo {file_id}")
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        return ShareResult(success=True, share_url=f"https://dropbox.com/s/{file_id}",
                          permissions=permissions, message="Compartido en Dropbox (mock)")
