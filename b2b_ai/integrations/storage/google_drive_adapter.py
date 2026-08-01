# -*- coding: utf-8 -*-
"""
google_drive_adapter.py — Adaptador mock para Google Drive.

Implementa la interfaz StorageAdapter con respuestas simuladas.
En producción, se conectaría a la Google Drive API (https://developers.google.com/drive/api/reference/rest).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.storage.adapter import StorageAdapter
from b2b_ai.integrations.storage.models import (
    FileMetadata,
    SharePermission,
    ShareResult,
    StorageConfig,
    StorageProvider,
    UploadResult,
)

logger = logging.getLogger(__name__)


class GoogleDriveAdapter(StorageAdapter):
    """Adaptador mock para Google Drive.

    En producción, se conectaría a la Google Drive API v3
    (https://developers.google.com/drive/api/v3/reference).
    Usa service account o OAuth 2.0.
    """

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.GOOGLE_DRIVE,
            api_key="MockGoogleDriveAPIKey",
            folder_id="root",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Google Drive.

        En producción:
        1. Autenticar con service account o OAuth
        2. Verificar permisos del Drive
        """
        logger.info("GoogleDriveAdapter: conectando a Google Drive (mock)...")
        self._connected = True
        logger.info("GoogleDriveAdapter: conexión exitosa (mock)")
        return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        """Sube un archivo mock a Google Drive.

        En producción: POST /upload/drive/v3/files?uploadType=multipart
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        file_id = f"gd_{_uuid.uuid4().hex[:20]}"

        logger.info(f"GoogleDriveAdapter: subiendo {file_path} a {folder}")

        return UploadResult(
            success=True,
            file=FileMetadata(
                id=file_id,
                name=file_path.split("/")[-1],
                path=f"{folder}/{file_path.split('/')[-1]}",
                size=1024 * 50,
                mime_type="application/pdf",
                created_at=now,
                updated_at=now,
                download_url=f"https://drive.google.com/file/d/{file_id}/view",
            ),
            message="Archivo subido exitosamente a Google Drive (mock)",
        )

    def download(self, file_id: str) -> bytes:
        """Descarga un archivo mock de Google Drive.

        En producción: GET /drive/v3/files/{id}?alt=media
        """
        self._ensure_connected()
        logger.info(f"GoogleDriveAdapter: descargando archivo {file_id}")
        return b"mock file content from Google Drive"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        """Lista archivos mock de Google Drive.

        En producción: GET /drive/v3/files?q='{folderId}' in parents
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"GoogleDriveAdapter: listando archivos en {folder}")

        return [
            FileMetadata(
                id=f"gd_doc_{i:04d}",
                name=f"documento_{i}.pdf",
                path=f"{folder}/documento_{i}.pdf",
                size=1024 * (100 + i * 50),
                mime_type="application/pdf",
                created_at=now,
                updated_at=now,
            )
            for i in range(1, 4)
        ]

    def delete(self, file_id: str) -> bool:
        """Elimina un archivo mock de Google Drive.

        En producción: DELETE /drive/v3/files/{id}
        """
        self._ensure_connected()
        logger.info(f"GoogleDriveAdapter: eliminando archivo {file_id}")
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        """Comparte un archivo mock en Google Drive.

        En producción: POST /drive/v3/files/{id}/permissions
        """
        self._ensure_connected()
        logger.info(f"GoogleDriveAdapter: compartiendo archivo {file_id}")

        return ShareResult(
            success=True,
            share_url=f"https://drive.google.com/file/d/{file_id}/view",
            permissions=permissions,
            message="Archivo compartido exitosamente en Google Drive (mock)",
        )
