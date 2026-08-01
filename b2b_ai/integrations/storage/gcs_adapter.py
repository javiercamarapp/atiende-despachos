# -*- coding: utf-8 -*-
"""
gcs_adapter.py — Adaptador mock para Google Cloud Storage.
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


class GCSAdapter(StorageAdapter):
    """Adaptador mock para Google Cloud Storage."""

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(provider=StorageProvider.GCS, api_key="mock_gcs_key",
                                         bucket="mock-gcs-bucket")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("GCSAdapter: conexión exitosa (mock)")
        return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        meta = FileMetadata(id=f"gcs_{_uuid.uuid4().hex[:12]}", name=file_path.split("/")[-1],
                            path=f"{self.config.bucket}/{folder}/{file_path.split('/')[-1]}",
                            size=4096, mime_type="application/octet-stream",
                            created_at=now, updated_at=now)
        return UploadResult(success=True, file=meta, message="Archivo subido a GCS (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        return b"MOCK_GCS_CONTENT"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        return [FileMetadata(id=f"gcs_{_uuid.uuid4().hex[:12]}", name=f"data_{i}.parquet",
                            path=f"{self.config.bucket}/{folder}/data_{i}.parquet",
                            size=4096 * i, created_at=now, updated_at=now)
                for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        logger.info(f"GCSAdapter: eliminando archivo {file_id}")
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        return ShareResult(success=True, share_url=f"https://storage.googleapis.com/{self.config.bucket}/{file_id}",
                          permissions=permissions, message="Compartido en GCS (mock)")
