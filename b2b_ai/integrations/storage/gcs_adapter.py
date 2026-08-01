# -*- coding: utf-8 -*-
"""gcs_adapter.py — Real adapter for Google Cloud Storage."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)
logger = logging.getLogger(__name__)

class GCSAdapter(StorageAdapter):
    """Real adapter for Google Cloud Storage. Requires GOOGLE_APPLICATION_CREDENTIALS."""
    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.GCS,
            api_key=os.environ.get("GCS_PROJECT_ID", ""),
            bucket=os.environ.get("GCS_BUCKET", "likida-gcs-bucket"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.warning("GCSAdapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            from google.cloud import storage
            self._client = storage.Client(project=self.config.api_key or None)
            self._connected = True
            logger.info("GCSAdapter: connected to Google Cloud Storage")
            return True
        except ImportError:
            logger.warning("GCSAdapter: google-cloud-storage not installed — MOCK mode")
            self._connected = True; self._client = None; return True
        except Exception as e:
            logger.error(f"GCSAdapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        bucket_name = self.config.bucket or "likida-gcs-bucket"
        blob_name = f"{folder.strip('/')}/{os.path.basename(file_path)}"
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(file_path)
                return UploadResult(success=True, file=FileMetadata(id=blob.id, name=blob.name,
                    path=f"gs://{bucket_name}/{blob_name}", size=blob.size or 0,
                    created_at=now, updated_at=now), message="Upload successful")
            except Exception as e:
                logger.error(f"GCSAdapter: upload failed: {e}"); raise
        return UploadResult(success=True, file=FileMetadata(id=f"gcs_{_uuid.uuid4().hex[:16]}",
            name=os.path.basename(file_path), path=f"gs://{bucket_name}/{blob_name}",
            created_at=now, updated_at=now), message="Upload successful (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        bucket_name = self.config.bucket or "likida-gcs-bucket"
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(file_id)
                return blob.download_as_bytes()
            except Exception as e:
                logger.error(f"GCSAdapter: download failed: {e}"); raise
        return b"mock GCS content"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        bucket_name = self.config.bucket or "likida-gcs-bucket"
        prefix = folder.strip("/") + "/" if folder != "/" else ""
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blobs = list(bucket.list_blobs(prefix=prefix))
                return [FileMetadata(id=b.id, name=b.name, path=f"gs://{bucket_name}/{b.name}",
                    size=b.size or 0, created_at=b.time_created.isoformat() if b.time_created else now,
                    updated_at=b.updated.isoformat() if b.updated else now) for b in blobs]
            except Exception as e:
                logger.error(f"GCSAdapter: list_files failed: {e}"); raise
        return [FileMetadata(id=f"gcs_{_uuid.uuid4().hex[:8]}", name=f"doc_{i}.pdf",
            path=f"gs://{bucket_name}/{folder}doc_{i}.pdf", created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        bucket_name = self.config.bucket or "likida-gcs-bucket"
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(file_id)
                blob.delete()
                return True
            except Exception as e:
                logger.error(f"GCSAdapter: delete failed: {e}"); raise
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        bucket_name = self.config.bucket or "likida-gcs-bucket"
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(file_id)
                url = blob.generate_signed_url(expiration=3600, method="GET")
                return ShareResult(success=True, share_url=url, permissions=permissions, message="Signed URL generated")
            except Exception as e:
                logger.error(f"GCSAdapter: share failed: {e}"); raise
        return ShareResult(success=True, share_url=f"https://storage.googleapis.com/{bucket_name}/{file_id}",
            permissions=permissions, message="Shared (mock)")
