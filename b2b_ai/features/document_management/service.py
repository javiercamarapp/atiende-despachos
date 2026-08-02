# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del sistema de gestión documental.

Expone:
  - DocumentService : upload_document / search_documents / get_document /
                      get_version_history / share_document / list_shares /
                      add_tag / archive_document.
  - registros en memoria por tenant + backend de almacenamiento (abstracción).

El hash SHA-256 garantiza integridad del contenido; cada nueva subida del
mismo documento (mismo hash) no duplica contenido y versiona.

Persistencia opcional: si se pasa ``state_file`` (o la env ``DOCS_STATE_FILE``),
el índice de documentos/versiones/comparticiones se vuelca a un archivo JSON
después de cada mutación y se recarga al arrancar. El contenido binario sigue
viviendo en el backend de storage. Si no se configura, el estado es solo en
memoria (comportamiento por defecto, sin romper tests existentes).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from b2b_ai.features.document_management.models import (
    Document,
    DocumentCategory,
    DocumentShare,
    DocumentStatus,
    DocumentVersion,
    SharePermission,
)
from b2b_ai.features.document_management.storage import (
    BaseStorage,
    LocalStorage,
    StorageBackendError,
    get_backend,
)

# Registro en memoria (MVP). En producción se sustituye por el repositorio DB.
_documents: Dict[str, Document] = {}
_versions: Dict[str, List[DocumentVersion]] = {}
_shares: Dict[str, List[DocumentShare]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (útil para tests)."""
    _documents.clear()
    _versions.clear()
    _shares.clear()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tenant_key(tenant_id: str) -> str:
    return str(tenant_id).strip().upper()


class _StateCodec:
    """Codifica/decodifica el índice entre modelos Pydantic y JSON."""

    @staticmethod
    def encode_document(doc: Document) -> Dict[str, Any]:
        return doc.to_dict()

    @staticmethod
    def decode_document(data: Dict[str, Any]) -> Document:
        # status/category vienen como string en JSON → re-mapear a enum.
        d = dict(data)
        d["category"] = DocumentCategory(d["category"])
        d["status"] = DocumentStatus(d["status"])
        return Document.model_validate(d)

    @staticmethod
    def encode_version(v: DocumentVersion) -> Dict[str, Any]:
        return v.to_dict()

    @staticmethod
    def decode_version(data: Dict[str, Any]) -> DocumentVersion:
        return DocumentVersion.model_validate(data)

    @staticmethod
    def encode_share(s: DocumentShare) -> Dict[str, Any]:
        return s.to_dict()

    @staticmethod
    def decode_share(data: Dict[str, Any]) -> DocumentShare:
        d = dict(data)
        d["permission"] = SharePermission(d["permission"])
        return DocumentShare.model_validate(d)


class DocumentService:
    """Servicio stateless para el sistema de gestión documental."""

    def __init__(self, storage: Optional[BaseStorage] = None, kind: str = "local",
                 state_file: Optional[str] = None, **storage_kwargs):
        if storage is not None:
            self.storage = storage
        else:
            self.storage = get_backend(kind, **storage_kwargs)
        self._state_file = (
            state_file or os.environ.get("DOCS_STATE_FILE")
        )
        if self._state_file:
            self._load_state()

    # -- Persistencia -----------------------------------------------------
    def _load_state(self) -> None:
        """Carga el índice desde el archivo JSON (si existe)."""
        if not self._state_file:
            return
        p = Path(self._state_file)
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        _reset_state()
        for d in raw.get("documents", []):
            try:
                doc = _StateCodec.decode_document(d)
                _documents[doc.id] = doc
            except Exception:
                continue
        for vid, vlist in raw.get("versions", {}).items():
            _versions[vid] = [
                _StateCodec.decode_version(v) for v in vlist
            ]
        for sid, slist in raw.get("shares", {}).items():
            _shares[sid] = [
                _StateCodec.decode_share(s) for s in slist
            ]

    def _save_state(self) -> None:
        """Vuelca el índice a JSON (best-effort, nunca rompe la mutación)."""
        if not self._state_file:
            return
        payload = {
            "documents": [
                _StateCodec.encode_document(d) for d in _documents.values()
            ],
            "versions": {
                vid: [_StateCodec.encode_version(v) for v in vlist]
                for vid, vlist in _versions.items()
            },
            "shares": {
                sid: [_StateCodec.encode_share(s) for s in slist]
                for sid, slist in _shares.items()
            },
        }
        try:
            p = Path(self._state_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass

    def _mutate(self) -> None:
        """Persiste tras una mutación del índice."""
        self._save_state()

    # -- Alta -------------------------------------------------------------
    def upload_document(
        self,
        tenant_id: str,
        name: str,
        data: bytes,
        category: DocumentCategory = DocumentCategory.OTRO,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
    ) -> Document:
        """Sube un documento, calcula su hash, lo versiona y lo guarda.

        Si ya existe un documento con el mismo (tenant, name), crea una nueva
        versión; de lo contrario crea el documento en versión 1.
        """
        tenant_key = _tenant_key(tenant_id)
        if not data:
            raise ValueError("El contenido del documento está vacío.")
        digest = _sha256(data)

        existing = self._find_by_name(tenant_key, name)

        rel_path = f"{tenant_key}/{digest[:2]}/{digest}.bin"
        self.storage.save(rel_path, data)

        if existing:
            # Versionar: no duplicamos contenido (mismo hash) pero sí la versión
            version = existing.version + 1
            doc = existing.model_copy(deep=True)
            doc.version = version
            doc.sha256 = digest
            doc.storage_path = rel_path
            doc.size = len(data)
            doc.content_type = content_type
            doc.updated_at = datetime.utcnow()
            if tags:
                doc.tags = list(dict.fromkeys([*doc.tags, *tags]))
            if metadata:
                doc.metadata = {**doc.metadata, **metadata}
            if category != DocumentCategory.OTRO or not doc.metadata:
                doc.category = category
            _documents[doc.id] = doc
        else:
            doc = Document(
                tenant_id=tenant_key,
                name=name,
                category=category,
                content_type=content_type,
                size=len(data),
                sha256=digest,
                storage_path=rel_path,
                version=1,
                metadata=metadata or {},
                tags=tags or [],
                created_by=created_by,
            )
            _documents[doc.id] = doc

        # Guardar versión inmutable
        _versions.setdefault(doc.id, []).append(DocumentVersion(
            document_id=doc.id,
            version=doc.version,
            sha256=digest,
            storage_path=rel_path,
            size=len(data),
            note="Versión inicial" if doc.version == 1 else f"Versión {doc.version}",
            created_by=created_by,
        ))
        self._mutate()
        return doc

    # -- Búsqueda ----------------------------------------------------------
    def search_documents(
        self,
        tenant_id: str,
        query: Optional[str] = None,
        category: Optional[DocumentCategory] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Document]:
        """Busca documentos del tenant por nombre/metadata/tags/categoría."""
        tenant_key = _tenant_key(tenant_id)
        q = (query or "").strip().lower()
        tagset = {t.lower() for t in (tags or [])}
        results: List[Document] = []
        for doc in _documents.values():
            if doc.tenant_id != tenant_key:
                continue
            if doc.status != DocumentStatus.ACTIVO:
                continue
            if category is not None and doc.category != category:
                continue
            if tagset:
                doc_tags = {t.lower() for t in doc.tags}
                if not tagset.issubset(doc_tags):
                    continue
            if q:
                haystack = " ".join([
                    doc.name, doc.sha256,
                    " ".join(doc.tags),
                    " ".join(f"{k}:{v}" for k, v in doc.metadata.items()),
                ]).lower()
                if q not in haystack:
                    continue
            results.append(doc)
        results.sort(key=lambda d: d.updated_at, reverse=True)
        return results[:limit]

    # -- Lectura -----------------------------------------------------------
    def get_document(self, tenant_id: str, document_id: str) -> Document:
        tenant_key = _tenant_key(tenant_id)
        doc = _documents.get(document_id)
        if not doc or doc.tenant_id != tenant_key:
            raise KeyError(f"Documento no encontrado: {document_id}")
        return doc

    def read_document_bytes(self, tenant_id: str, document_id: str) -> bytes:
        doc = self.get_document(tenant_id, document_id)
        try:
            return self.storage.read(doc.storage_path)
        except StorageBackendError as e:
            raise StorageBackendError(f"Contenido no disponible: {e}") from e

    # -- Versiones ---------------------------------------------------------
    def get_version_history(self, tenant_id: str, document_id: str) -> List[DocumentVersion]:
        self.get_document(tenant_id, document_id)  # valida pertenencia
        return sorted(
            _versions.get(document_id, []),
            key=lambda v: v.version,
            reverse=True,
        )

    # -- Compartición ------------------------------------------------------
    def share_document(
        self,
        tenant_id: str,
        document_id: str,
        shared_with: str,
        permission: SharePermission = SharePermission.LECTURA,
        expires_at: Optional[datetime] = None,
    ) -> DocumentShare:
        self.get_document(tenant_id, document_id)
        share = DocumentShare(
            document_id=document_id,
            shared_with=shared_with.strip(),
            permission=permission,
            expires_at=expires_at,
        )
        _shares.setdefault(document_id, []).append(share)
        self._mutate()
        return share

    def list_shares(self, tenant_id: str, document_id: str) -> List[DocumentShare]:
        self.get_document(tenant_id, document_id)
        return list(_shares.get(document_id, []))

    # -- Utilidades --------------------------------------------------------
    def add_tag(self, tenant_id: str, document_id: str, tag: str) -> Document:
        doc = self.get_document(tenant_id, document_id)
        tag = tag.strip()
        if tag and tag not in doc.tags:
            doc.tags.append(tag)
            _documents[doc.id] = doc
        self._mutate()
        return doc

    def archive_document(self, tenant_id: str, document_id: str) -> Document:
        doc = self.get_document(tenant_id, document_id)
        doc.status = DocumentStatus.ARCHIVADO
        _documents[doc.id] = doc
        self._mutate()
        return doc

    def _find_by_name(self, tenant_key: str, name: str) -> Optional[Document]:
        for doc in _documents.values():
            if doc.tenant_id == tenant_key and doc.name == name \
               and doc.status != DocumentStatus.ELIMINADO:
                return doc
        return None
