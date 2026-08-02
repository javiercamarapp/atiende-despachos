# -*- coding: utf-8 -*-
"""storage — Abstracción de backend de almacenamiento para documentos.

Sigue el patrón backend-abstraction:
  - `LocalStorage` : filesystem local (MVP / desarrollo / single-node).
  - `S3Storage`    : AWS S3 (producción). Requiere boto3.
  - `get_backend`  : factory que resuelve el backend desde configuración.

Cada backend implementa:
  - save(relative_path, data: bytes) -> str     : guarda y devuelve el path lógico
  - read(relative_path) -> bytes                : lee el contenido
  - delete(relative_path) -> bool               : elimina
  - exists(relative_path) -> bool               : verifica existencia
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class StorageBackendError(Exception):
    """Error de almacenamiento de documentos."""


class BaseStorage:
    """Contrato mínimo de un backend de almacenamiento."""

    def save(self, relative_path: str, data: bytes) -> str:
        raise NotImplementedError

    def read(self, relative_path: str) -> bytes:
        raise NotImplementedError

    def delete(self, relative_path: str) -> bool:
        raise NotImplementedError

    def exists(self, relative_path: str) -> bool:
        raise NotImplementedError


class LocalStorage(BaseStorage):
    """Backend de filesystem local (MVP)."""

    def __init__(self, root: Optional[str] = None):
        root = root or os.environ.get("DOCS_STORAGE_ROOT", "/tmp/document_management")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        # Evita path traversal
        p = (self.root / relative_path).resolve()
        if not str(p).startswith(str(self.root)):
            raise StorageBackendError(f"Path fuera del root: {relative_path}")
        return p

    def save(self, relative_path: str, data: bytes) -> str:
        p = self._resolve(relative_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return relative_path

    def read(self, relative_path: str) -> bytes:
        p = self._resolve(relative_path)
        if not p.exists():
            raise StorageBackendError(f"No existe: {relative_path}")
        return p.read_bytes()

    def delete(self, relative_path: str) -> bool:
        p = self._resolve(relative_path)
        if p.exists():
            p.unlink()
            return True
        return False

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()


class S3Storage(BaseStorage):
    """Backend S3 para producción (requiere boto3)."""

    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        try:
            import boto3  # noqa: F401
            self._s3 = boto3.client("s3")
        except ImportError as e:  # pragma: no cover - solo si no hay boto3
            raise StorageBackendError(
                "S3Storage requiere boto3. Instala 'boto3' para producción."
            ) from e

    def _key(self, relative_path: str) -> str:
        return f"{self.prefix}/{relative_path.lstrip('/')}" if self.prefix else relative_path

    def save(self, relative_path: str, data: bytes) -> str:
        self._s3.put_object(Bucket=self.bucket, Key=self._key(relative_path), Body=data)
        return relative_path

    def read(self, relative_path: str) -> bytes:
        obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(relative_path))
        return obj["Body"].read()

    def delete(self, relative_path: str) -> bool:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(relative_path))
        return True

    def exists(self, relative_path: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(relative_path))
            return True
        except Exception:
            return False


def get_backend(kind: str = "local", **kwargs) -> BaseStorage:
    """Factory que devuelve el backend de almacenamiento solicitado.

    - kind="local" -> LocalStorage(root=...)
    - kind="s3"    -> S3Storage(bucket=..., prefix=...)
    """
    kind = (kind or "local").lower()
    if kind == "local":
        return LocalStorage(root=kwargs.get("root"))
    if kind == "s3":
        return S3Storage(bucket=kwargs.get("bucket", ""), prefix=kwargs.get("prefix", ""))
    raise StorageBackendError(f"Backend de almacenamiento desconocido: {kind}")
