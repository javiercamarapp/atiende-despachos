import os
# -*- coding: utf-8 -*-
"""
onedrive_adapter.py — Adaptador mock para Microsoft OneDrive.

Implementa la interfaz StorageAdapter con respuestas simuladas.
En producción, se conectaría a la Microsoft Graph API (https://learn.microsoft.com/en-us/graph/api/overview).
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


class OneDriveAdapter(StorageAdapter):
    """Adaptador mock para Microsoft OneDrive.

    En producción, se conectaría a la Microsoft Graph API v1.0
    (https://learn.microsoft.com/en-us/graph/api/driveitem-list-children).
    Usa OAuth 2.0 con Azure AD.
    """

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.ONEDRIVE,
            api_key="MockOneDriveAccessToken",
            api_key=os.environ.get("ONEDRIVE_CLIENT_ID", ""),            folder_id="root",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a OneDrive.

        En producción:
        1. Obtener OAuth 2.0 token con Azure AD
        2. Verificar permisos del drive
        """
        logger.info("OneDriveAdapter: conectando a OneDrive (mock)...")
        self._connected = True
        logger.info("OneDriveAdapter: conexión exitosa (mock)")
        return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        """Sube un archivo mock a OneDrive.

        En producción: PUT /me/drive/root:/{path}:/content
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        file_id = f"od_{_uuid.uuid4().hex[:20]}"

        logger.info(f"OneDriveAdapter: subiendo {file_path} a {folder}")

        return UploadResult(
            success=True,
            file=FileMetadata(
                id=file_id,
                name=file_path.split("/")[-1],
                path=f"{folder}/{file_path.split('/')[-1]}",
                size=1024 * 75,
                mime_type="application/pdf",
                created_at=now,
                updated_at=now,
                download_url=f"https://onedrive.live.com/download?cid={file_id}",
            ),
            message="Archivo subido exitosamente a OneDrive (mock)",
        )

    def download(self, file_id: str) -> bytes:
        """Descarga un archivo mock de OneDrive.

        En producción: GET /me/drive/items/{id}/content
        """
        self._ensure_connected()
        logger.info(f"OneDriveAdapter: descargando archivo {file_id}")
        return b"mock file content from OneDrive"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        """Lista archivos mock de OneDrive.

        En producción: GET /me/drive/root:/{path}:/children
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"OneDriveAdapter: listando archivos en {folder}")

        return [
            FileMetadata(
                id=f"od_file_{i:04d}",
                name=f"reporte_{i}.xlsx",
                path=f"{folder}/reporte_{i}.xlsx",
                size=1024 * (200 + i * 100),
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                created_at=now,
                updated_at=now,
            )
            for i in range(1, 4)
        ]

    def delete(self, file_id: str) -> bool:
        """Elimina un archivo mock de OneDrive.

        En producción: DELETE /me/drive/items/{id}
        """
        self._ensure_connected()
        logger.info(f"OneDriveAdapter: eliminando archivo {file_id}")
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        """Comparte un archivo mock en OneDrive.

        En producción: POST /me/drive/items/{id}/invite
        """
        self._ensure_connected()
        logger.info(f"OneDriveAdapter: compartiendo archivo {file_id}")

        return ShareResult(
            success=True,
            share_url=f"https://1drv.ms/f/s!{file_id}",
            permissions=permissions,
            message="Archivo compartido exitosamente en OneDrive (mock)",
        )
