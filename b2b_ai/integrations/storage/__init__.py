# -*- coding: utf-8 -*-
"""Módulo de integración de Almacenamiento — Google Drive, OneDrive, S3."""

from b2b_ai.integrations.storage.adapter import StorageAdapter, StorageAdapterError
from b2b_ai.integrations.storage.google_drive_adapter import GoogleDriveAdapter
from b2b_ai.integrations.storage.onedrive_adapter import OneDriveAdapter
from b2b_ai.integrations.storage.s3_adapter import S3Adapter
from b2b_ai.integrations.storage.dropbox_adapter import DropboxAdapter
from b2b_ai.integrations.storage.box_adapter import BoxAdapter
from b2b_ai.integrations.storage.gcs_adapter import GCSAdapter
from b2b_ai.integrations.storage.models import (
    FileMetadata,
    PermissionRole,
    SharePermission,
    ShareResult,
    StorageConfig,
    StorageProvider,
    UploadResult,
)

__all__ = [
    "StorageAdapter",
    "StorageAdapterError",
    "GoogleDriveAdapter",
    "OneDriveAdapter",
    "S3Adapter",
    "DropboxAdapter",
    "BoxAdapter",
    "GCSAdapter",
    "FileMetadata",
    "PermissionRole",
    "SharePermission",
    "ShareResult",
    "StorageConfig",
    "StorageProvider",
    "UploadResult",
]
