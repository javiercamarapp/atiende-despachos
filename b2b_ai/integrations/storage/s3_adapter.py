import os
# -*- coding: utf-8 -*-
"""
s3_adapter.py — Adaptador mock para AWS S3.

Implementa la interfaz StorageAdapter con respuestas simuladas.
En producción, se conectaría a la AWS S3 API (https://docs.aws.amazon.com/s3/latest/API/).
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


class S3Adapter(StorageAdapter):
    """Adaptador mock para AWS S3.

    En producción, se conectaría a la AWS S3 API
    (https://docs.aws.amazon.com/AmazonS3/latest/API/).
    Usa access_key + secret_key o IAM roles.
    """

    def __init__(self, config: Optional[StorageConfig] = None):
        config = config or StorageConfig(
            provider=StorageProvider.S3,
            api_key="AKIA_MockAWSAccessKey1234",
            api_key=os.environ.get("AWS_S3_ACCESS_KEY", ""),            api_secret="MockAWSSecretKey5678901234567890",
            bucket="b2b-ai-documents",
            region="us-east-1",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a AWS S3.

        En producción:
        1. Validar credenciales con ListBuckets
        2. Verificar acceso al bucket
        """
        logger.info("S3Adapter: conectando a AWS S3 (mock)...")
        self._connected = True
        logger.info("S3Adapter: conexión exitosa (mock)")
        return True

    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        """Sube un archivo mock a S3.

        En producción: PutObject API
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        file_id = f"s3_{_uuid.uuid4().hex[:20]}"
        key = f"{folder.strip('/')}/{file_path.split('/')[-1]}"

        logger.info(f"S3Adapter: subiendo {file_path} a s3://{self.config.bucket}/{key}")

        return UploadResult(
            success=True,
            file=FileMetadata(
                id=file_id,
                name=file_path.split("/")[-1],
                path=f"s3://{self.config.bucket}/{key}",
                size=1024 * 120,
                mime_type="application/pdf",
                created_at=now,
                updated_at=now,
                download_url=f"https://{self.config.bucket}.s3.{self.config.region}.amazonaws.com/{key}",
            ),
            message="Archivo subido exitosamente a S3 (mock)",
        )

    def download(self, file_id: str) -> bytes:
        """Descarga un archivo mock de S3.

        En producción: GetObject API
        """
        self._ensure_connected()
        logger.info(f"S3Adapter: descargando archivo {file_id}")
        return b"mock file content from AWS S3"

    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        """Lista archivos mock de S3.

        En producción: ListObjectsV2 API con prefix
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        logger.info(f"S3Adapter: listando archivos en {folder}")

        return [
            FileMetadata(
                id=f"s3_obj_{i:04d}",
                name=f"backup_{i}.zip",
                path=f"s3://{self.config.bucket}/{folder.strip('/')}/backup_{i}.zip",
                size=1024 * (500 + i * 250),
                mime_type="application/zip",
                created_at=now,
                updated_at=now,
            )
            for i in range(1, 4)
        ]

    def delete(self, file_id: str) -> bool:
        """Elimina un archivo mock de S3.

        En producción: DeleteObject API
        """
        self._ensure_connected()
        logger.info(f"S3Adapter: eliminando archivo {file_id}")
        return True

    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        """Genera un presigned URL mock para compartir en S3.

        En producción: GeneratePresignedUrl o BucketPolicy
        """
        self._ensure_connected()
        logger.info(f"S3Adapter: generando URL presignada para {file_id}")

        return ShareResult(
            success=True,
            share_url=f"https://{self.config.bucket}.s3.amazonaws.com/{file_id}?X-Amz-Signature=mock",
            permissions=permissions,
            message="URL presignada generada en S3 (mock)",
        )
