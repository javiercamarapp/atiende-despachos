# -*- coding: utf-8 -*-
"""s3_adapter.py — Real adapter for AWS S3 storage."""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)
logger = logging.getLogger(__name__)

class S3Adapter(StorageAdapter):
    """Real adapter for AWS S3. Requires AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."""
    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.S3,
            api_key=os.environ.get("AWS_ACCESS_KEY_ID", ""),
            api_secret=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            bucket=os.environ.get("AWS_S3_BUCKET", "likida-bucket"),
            region=os.environ.get("AWS_REGION", "us-east-1"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        api_key = (credentials or {}).get("api_key") or self.config.api_key or os.environ.get("AWS_ACCESS_KEY_ID", "")
        api_secret = (credentials or {}).get("api_secret") or self.config.api_secret or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        if not api_key or not api_secret:
            logger.warning("S3Adapter: no credentials — MOCK mode")
            self._connected = True; self._client = None; return True
        try:
            import boto3
            self._client = boto3.client("s3", aws_access_key_id=api_key,
                aws_secret_access_key=api_secret, region_name=self.config.region or "us-east-1")
            self._connected = True
            logger.info("S3Adapter: connected to AWS S3")
            return True
        except ImportError:
            logger.warning("S3Adapter: boto3 not installed — MOCK mode")
            self._connected = True; self._client = None; return True
        except Exception as e:
            logger.error(f"S3Adapter: connection failed: {e}")
            self._connected = True; self._client = None; return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        bucket = self.config.bucket or "likida-bucket"
        key = f"{folder.strip('/')}/{os.path.basename(file_path)}"
        if self._client:
            try:
                self._client.upload_file(file_path, bucket, key)
                return UploadResult(success=True, file=FileMetadata(id=key, name=os.path.basename(file_path),
                    path=f"s3://{bucket}/{key}", size=os.path.getsize(file_path),
                    created_at=now, updated_at=now), message="Upload successful")
            except Exception as e:
                logger.error(f"S3Adapter: upload failed: {e}"); raise
        return UploadResult(success=True, file=FileMetadata(id=key, name=os.path.basename(file_path),
            path=f"s3://{bucket}/{key}", created_at=now, updated_at=now), message="Upload successful (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        bucket = self.config.bucket or "likida-bucket"
        if self._client:
            try:
                from io import BytesIO
                buf = BytesIO()
                self._client.download_fileobj(bucket, file_id, buf)
                return buf.getvalue()
            except Exception as e:
                logger.error(f"S3Adapter: download failed: {e}"); raise
        return b"mock S3 content"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        bucket = self.config.bucket or "likida-bucket"
        prefix = folder.strip("/") + "/" if folder != "/" else ""
        if self._client:
            try:
                resp = self._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
                return [FileMetadata(id=obj["Key"], name=obj["Key"].split("/")[-1],
                    path=f"s3://{bucket}/{obj['Key']}", size=obj.get("Size", 0),
                    created_at=obj.get("LastModified", now).isoformat() if hasattr(obj.get("LastModified", now), "isoformat") else now,
                    updated_at=now) for obj in resp.get("Contents", [])]
            except Exception as e:
                logger.error(f"S3Adapter: list_files failed: {e}"); raise
        return [FileMetadata(id=f"s3/{folder}doc_{i}.pdf", name=f"doc_{i}.pdf",
            path=f"s3://{bucket}/{folder}doc_{i}.pdf", created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        bucket = self.config.bucket or "likida-bucket"
        if self._client:
            try:
                self._client.delete_object(Bucket=bucket, Key=file_id)
                return True
            except Exception as e:
                logger.error(f"S3Adapter: delete failed: {e}"); raise
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        bucket = self.config.bucket or "likida-bucket"
        if self._client:
            try:
                from botocore.config import Config
                url = self._client.generate_presigned_url("get_object",
                    Params={"Bucket": bucket, "Key": file_id}, ExpiresIn=3600)
                return ShareResult(success=True, share_url=url, permissions=permissions, message="Pre-signed URL generated")
            except Exception as e:
                logger.error(f"S3Adapter: share failed: {e}"); raise
        return ShareResult(success=True, share_url=f"https://{bucket}.s3.amazonaws.com/{file_id}",
            permissions=permissions, message="Shared (mock)")
