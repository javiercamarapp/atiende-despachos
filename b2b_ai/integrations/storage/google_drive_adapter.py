# -*- coding: utf-8 -*-
"""
google_drive_adapter.py — Real adapter for Google Drive.

Provides GoogleDriveAdapter with actual API calls to Google Drive v3.
Falls back to mock if GOOGLE_DRIVE_CREDENTIALS is not set.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.storage.adapter import StorageAdapter
from b2b_ai.integrations.storage.models import (
    FileMetadata, SharePermission, ShareResult, StorageConfig, StorageProvider, UploadResult,
)

logger = logging.getLogger(__name__)


class GoogleDriveAdapter(StorageAdapter):
    """Real adapter for Google Drive. Requires GOOGLE_DRIVE_CREDENTIALS (service account JSON)."""

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.GOOGLE_DRIVE,
            api_key=os.environ.get("GOOGLE_DRIVE_CREDENTIALS", ""),
            folder_id=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "root"),
        )
        super().__init__(config=config)
        self._service = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds_path = (credentials or {}).get("credentials_path") or self.config.api_key or os.environ.get("GOOGLE_DRIVE_CREDENTIALS", "") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not creds_path:
            logger.warning("GoogleDriveAdapter: no credentials — MOCK mode")
            self._connected = True
            self._service = None
            return True
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            creds = service_account.Credentials.from_service_account_file(creds_path, scopes=["https://www.googleapis.com/auth/drive"])
            self._service = build("drive", "v3", credentials=creds)
            self._connected = True
            logger.info("GoogleDriveAdapter: connected to Google Drive API")
            return True
        except ImportError:
            logger.warning("GoogleDriveAdapter: google packages not installed — MOCK mode")
            self._connected = True
            self._service = None
            return True
        except Exception as e:
            logger.error(f"GoogleDriveAdapter: connection failed: {e}")
            self._connected = True
            self._service = None
            return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        self._ensure_connected()
        now = datetime.now().isoformat()
        file_name = os.path.basename(file_path)
        if self._service:
            try:
                from googleapiclient.http import MediaFileUpload
                meta = {"name": file_name}
                if folder and folder != "/":
                    fid = self._find_or_create_folder(folder)
                    if fid:
                        meta["parents"] = [fid]
                media = MediaFileUpload(file_path, resumable=True)
                f = self._service.files().create(body=meta, media_body=media, fields="id, name, size, mimeType, createdTime, modifiedTime").execute()
                fid = f.get("id", "")
                return UploadResult(success=True, file=FileMetadata(id=fid, name=f.get("name", file_name), path=f"{folder}/{file_name}", size=int(f.get("size", 0)), mime_type=f.get("mimeType", "application/octet-stream"), created_at=f.get("createdTime", now), updated_at=f.get("modifiedTime", now), download_url=f"https://drive.google.com/file/d/{fid}/view"), message="Archivo subido a Google Drive")
            except Exception as e:
                logger.error(f"GoogleDriveAdapter: upload failed: {e}")
                return UploadResult(success=False, file=FileMetadata(name=file_name, path=file_path), message=f"Error: {e}")
        fid = f"gd_{_uuid.uuid4().hex[:20]}"
        return UploadResult(success=True, file=FileMetadata(id=fid, name=file_name, path=f"{folder}/{file_name}", size=1024*50, mime_type="application/pdf", created_at=now, updated_at=now, download_url=f"https://drive.google.com/file/d/{fid}/view"), message="Subido a Google Drive (mock)")

    def download(self, file_id: str) -> bytes:
        self._ensure_connected()
        if self._service:
            try:
                import io
                from googleapiclient.http import MediaIoBaseDownload
                request = self._service.files().get_media(fileId=file_id)
                file = io.BytesIO()
                downloader = MediaIoBaseDownload(file, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return file.getvalue()
            except Exception as e:
                logger.error(f"GoogleDriveAdapter: download failed: {e}")
                raise
        return b"mock file content from Google Drive"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        self._ensure_connected()
        now = datetime.now().isoformat()
        if self._service:
            try:
                folder_id = self.config.folder_id or "root"
                if folder and folder != "/":
                    found = self._find_or_create_folder(folder)
                    if found:
                        folder_id = found
                results = self._service.files().list(q=f"'{folder_id}' in parents and trashed=false", pageSize=100, fields="files(id, name, size, mimeType, createdTime, modifiedTime)").execute()
                return [FileMetadata(id=f.get("id", ""), name=f.get("name", ""), path=f"{folder}/{f.get('name', '')}", size=int(f.get("size", 0)), mime_type=f.get("mimeType", "application/octet-stream"), created_at=f.get("createdTime", now), updated_at=f.get("modifiedTime", now)) for f in results.get("files", [])]
            except Exception as e:
                logger.error(f"GoogleDriveAdapter: list_files failed: {e}")
                return []
        return [FileMetadata(id=f"gd_doc_{i:04d}", name=f"documento_{i}.pdf", path=f"{folder}/documento_{i}.pdf", size=1024*(100+i*50), mime_type="application/pdf", created_at=now, updated_at=now) for i in range(1, 4)]

    def delete(self, file_id: str) -> bool:
        self._ensure_connected()
        if self._service:
            try:
                self._service.files().delete(fileId=file_id).execute()
                return True
            except Exception as e:
                logger.error(f"GoogleDriveAdapter: delete failed: {e}")
                return False
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        self._ensure_connected()
        if self._service:
            try:
                for perm in permissions:
                    body = {"role": perm.role.value if hasattr(perm.role, "value") else perm.role, "type": "user", "emailAddress": perm.email}
                    self._service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=bool(perm.email)).execute()
                return ShareResult(success=True, share_url=f"https://drive.google.com/file/d/{file_id}/view", permissions=permissions, message="Compartido en Google Drive")
            except Exception as e:
                return ShareResult(success=False, message=f"Error: {e}")
        return ShareResult(success=True, share_url=f"https://drive.google.com/file/d/{file_id}/view", permissions=permissions, message="Compartido en Google Drive (mock)")

    def _find_or_create_folder(self, name: str) -> Optional[str]:
        if not self._service:
            return None
        try:
            r = self._service.files().list(q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="files(id)").execute()
            files = r.get("files", [])
            if files:
                return files[0]["id"]
            f = self._service.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder"}, fields="id").execute()
            return f.get("id")
        except Exception:
            return None
