# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de almacenamiento.

StorageAdapter es la clase base abstracta que todos los adaptadores
de almacenamiento deben implementar (Google Drive, OneDrive, S3).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.storage.models import (
    FileMetadata,
    SharePermission,
    ShareResult,
    StorageConfig,
    UploadResult,
)

logger = logging.getLogger(__name__)


class StorageAdapterError(Exception):
    """Error genérico de adaptador de almacenamiento."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class StorageAdapter(ABC):
    """Clase base abstracta para integración de almacenamiento en la nube.

    Todos los adaptadores (Google Drive, OneDrive, S3)
    deben implementar estos métodos.
    """

    def __init__(self, config: StorageConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        logger.info(f"StorageAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise StorageAdapterError(
                f"Adaptador de almacenamiento '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de almacenamiento.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def upload(self, file_path: str, folder: str = "/") -> UploadResult:
        """Sube un archivo.

        Args:
            file_path: Ruta local del archivo.
            folder: Carpeta destino.

        Returns:
            UploadResult con el resultado.
        """
        ...

    @abstractmethod
    def download(self, file_id: str) -> bytes:
        """Descarga un archivo.

        Args:
            file_id: ID del archivo.

        Returns:
            Contenido del archivo en bytes.
        """
        ...

    @abstractmethod
    def list_files(self, folder: str = "/") -> List[FileMetadata]:
        """Lista archivos de una carpeta.

        Args:
            folder: Ruta de la carpeta.

        Returns:
            Lista de metadatos de archivos.
        """
        ...

    @abstractmethod
    def delete(self, file_id: str) -> bool:
        """Elimina un archivo.

        Args:
            file_id: ID del archivo.

        Returns:
            True si se eliminó correctamente.
        """
        ...

    @abstractmethod
    def share(self, file_id: str, permissions: List[SharePermission]) -> ShareResult:
        """Comparte un archivo.

        Args:
            file_id: ID del archivo.
            permissions: Lista de permisos a aplicar.

        Returns:
            ShareResult con el resultado.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al proveedor.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "message": f"Conectado a {self.name} correctamente",
            }
        except StorageAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
