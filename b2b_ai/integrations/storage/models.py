# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de almacenamiento en la nube.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StorageProvider(str, Enum):
    """Proveedores de almacenamiento."""
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    S3 = "s3"
    DROPBOX = "dropbox"
    BOX = "box"
    GCS = "gcs"


class PermissionRole(str, Enum):
    """Roles de permiso."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class StorageConfig(BaseModel):
    """Configuración del adaptador de almacenamiento."""
    provider: StorageProvider = Field(..., description="Proveedor de almacenamiento")
    api_key: str = Field(default="", description="API key / Access key")
    api_secret: str = Field(default="", description="API secret / Secret key")
    bucket: Optional[str] = Field(default=None, description="Bucket name (S3)")
    folder_id: Optional[str] = Field(default=None, description="Folder ID (Drive/OneDrive)")
    region: Optional[str] = Field(default=None, description="AWS region (S3)")
    timeout: int = Field(default=30, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FileMetadata(BaseModel):
    """Metadatos de un archivo."""
    id: str = Field(default="", description="ID del archivo")
    name: str = Field(default="", description="Nombre del archivo")
    path: str = Field(default="", description="Ruta completa")
    size: int = Field(default=0, description="Tamaño en bytes")
    mime_type: str = Field(default="application/octet-stream", description="MIME type")
    created_at: str = Field(default="", description="Fecha de creación ISO")
    updated_at: str = Field(default="", description="Fecha de actualización ISO")
    owner: Optional[str] = Field(default=None, description="Propietario")
    download_url: Optional[str] = Field(default=None, description="URL de descarga")


class SharePermission(BaseModel):
    """Permiso de compartir archivo."""
    user_id: str = Field(..., description="ID del usuario")
    email: Optional[str] = Field(default=None, description="Email del usuario")
    role: PermissionRole = Field(default=PermissionRole.READ, description="Rol")
    expires_at: Optional[str] = Field(default=None, description="Expira ISO date")


class UploadResult(BaseModel):
    """Resultado de subida de archivo."""
    success: bool = Field(default=True, description="Si fue exitoso")
    file: FileMetadata = Field(default_factory=FileMetadata, description="Metadata del archivo")
    message: str = Field(default="", description="Mensaje")


class ShareResult(BaseModel):
    """Resultado de compartir archivo."""
    success: bool = Field(default=True, description="Si fue exitoso")
    share_url: Optional[str] = Field(default=None, description="URL de compartir")
    permissions: List[SharePermission] = Field(default_factory=list, description="Permisos")
    message: str = Field(default="", description="Mensaje")
