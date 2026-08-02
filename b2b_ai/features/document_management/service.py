# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del sistema de gestión documental.

Expone:
  - DocumentService : upload_document / search_documents / get_document /
                      get_version_history / share_document / list_shares /
                      add_tag / archive_document.
  - CRUD persistido en la base de datos (SQLite dev / PostgreSQL prod) a
    través de la capa `Database` de b2b_ai.db.db. Cada mutación se persiste
    de inmediato, así los datos sobreviven reinicios de la app.

El hash SHA-256 garantiza integridad del contenido; cada nueva subida del
mismo documento (mismo nombre y tenant) versiona sin duplicar contenido.

El contenido binario se guarda en el backend de storage (LocalStorage / S3);
la tabla `documents` guarda el índice/metadata. El aislamiento multi-tenant
es estricto: TODA lectura/escritura filtra por tenant_id.
"""
from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.db.db import Database, DEFAULT_DB
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

# En memoria por defecto solo para backward-compat de los tests que no pasan
# db. Con db=None usamos una base SQLite efímera (:memory:), aislada por
# instancia del servicio — nunca toca la base real del repo.
_DEFAULT_DB = None


def _reset_state() -> None:
    """Compat: limpia la base efímera por defecto (útil para tests)."""
    global _DEFAULT_DB
    if _DEFAULT_DB is not None:
        try:
            _wipe_all(_DEFAULT_DB)
        except Exception:  # noqa: BLE001 — best-effort en tests
            pass


def _wipe_all(db: Database) -> None:
    """Elimina filas de las tablas documentales (uso en tests)."""
    for table in ("document_shares", "document_versions", "documents"):
        db.conn.execute(f"DELETE FROM {table}")
    db.conn.commit()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tenant_key(tenant_id: str) -> str:
    return str(tenant_id).strip().upper()


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _ensure_schema(db: Database) -> None:
    """Garantiza que las tablas documentales existan (idempotente).

    En la base por defecto ya se crean vía MIGRATIONS v20. Esta defensa
    cubre :memory: y bases creadas con migrate=False.
    """
    if db._is_pg:
        return
    try:
        row = db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
    except Exception:  # noqa: BLE001
        return
    if row:
        return
    from b2b_ai.db.models import MIGRATIONS
    for m in MIGRATIONS:
        if m["version"] == 20:
            db.conn.executescript(m["sql"])
            db.conn.commit()
            return


def _db_row_to_document(row: Any) -> Document:
    metadata = {}
    tags: List[str] = []
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except (ValueError, TypeError):
        metadata = {}
    try:
        tags = json.loads(row["tags"] or "[]")
    except (ValueError, TypeError):
        tags = []
    return Document(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        category=DocumentCategory(row["category"]),
        content_type=row["content_type"],
        size=row["size"],
        sha256=row["sha256"],
        storage_path=row["storage_path"],
        version=row["version"],
        metadata=metadata or {},
        tags=tags or [],
        status=DocumentStatus(row["status"]),
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


def _db_row_to_version(row: Any) -> DocumentVersion:
    return DocumentVersion(
        id=row["id"],
        document_id=row["document_id"],
        version=row["version"],
        sha256=row["sha256"],
        storage_path=row["storage_path"],
        size=row["size"],
        note=row["note"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


def _db_row_to_share(row: Any) -> DocumentShare:
    return DocumentShare(
        id=row["id"],
        document_id=row["document_id"],
        shared_with=row["shared_with"],
        permission=SharePermission(row["permission"]),
        token=row["token"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
    )


class DocumentService:
    """Servicio de gestión documental persistido en DB (SQLite/PG)."""

    def __init__(self, db: Optional[Database] = None, storage: Optional[BaseStorage] = None,
                 kind: str = "local", **storage_kwargs):
        global _DEFAULT_DB
        if db is not None:
            self.db = db
        else:
            if _DEFAULT_DB is None:
                _DEFAULT_DB = Database(":memory:", migrate=False)
            self.db = _DEFAULT_DB
        _ensure_schema(self.db)
        if storage is not None:
            self.storage = storage
        else:
            self.storage = get_backend(kind, **storage_kwargs)

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
        """Sube un documento, calcula su hash, lo versiona y lo persiste.

        Si ya existe un documento con el mismo (tenant, name) no-eliminado,
        crea una nueva versión; de lo contrario crea el documento en v1.
        """
        tenant_key = _tenant_key(tenant_id)
        if not data:
            raise ValueError("El contenido del documento está vacío.")
        digest = _sha256(data)

        existing = self._find_by_name(tenant_key, name)
        now = _utcnow_iso()

        rel_path = f"{tenant_key}/{digest[:2]}/{digest}.bin"
        self.storage.save(rel_path, data)

        if existing:
            new_version = existing.version + 1
            new_doc = Document(
                id=existing.id,
                tenant_id=tenant_key,
                name=existing.name,
                category=(category if category != DocumentCategory.OTRO
                          else existing.category),
                content_type=content_type,
                size=len(data),
                sha256=digest,
                storage_path=rel_path,
                version=new_version,
                metadata={**existing.metadata, **(metadata or {})},
                tags=list(dict.fromkeys([*existing.tags, *(tags or [])])),
                status=existing.status,
                created_by=existing.created_by,
                created_at=existing.created_at,
                updated_at=datetime.fromisoformat(now),
            )
            self.db.conn.execute(
                """UPDATE documents SET category=?, content_type=?, size=?,
                   sha256=?, storage_path=?, version=?, metadata=?, tags=?,
                   status=?, updated_at=? WHERE id=?""",
                (new_doc.category.value, new_doc.content_type, new_doc.size,
                 new_doc.sha256, new_doc.storage_path, new_doc.version,
                 json.dumps(new_doc.metadata), json.dumps(new_doc.tags),
                 new_doc.status.value, now, new_doc.id),
            )
        else:
            new_doc = Document(
                id=str(_uuid.uuid4()),
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
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )
            self.db.conn.execute(
                """INSERT INTO documents (id, tenant_id, name, category,
                   content_type, size, sha256, storage_path, version,
                   metadata, tags, status, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_doc.id, new_doc.tenant_id, new_doc.name, new_doc.category.value,
                 new_doc.content_type, new_doc.size, new_doc.sha256,
                 new_doc.storage_path, new_doc.version, json.dumps(new_doc.metadata),
                 json.dumps(new_doc.tags), new_doc.status.value, new_doc.created_by,
                 now, now),
            )

        # Guardar versión inmutable
        self.db.conn.execute(
            """INSERT INTO document_versions (id, document_id, tenant_id,
               version, sha256, storage_path, size, note, created_by, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(_uuid.uuid4()), new_doc.id, tenant_key, new_doc.version, digest,
             rel_path, len(data),
             "Versión inicial" if new_doc.version == 1 else f"Versión {new_doc.version}",
             created_by, now),
        )
        self.db.conn.commit()
        return new_doc

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
        rows = self.db.conn.execute(
            """SELECT * FROM documents WHERE tenant_id=? AND status=? ORDER BY updated_at DESC""",
            (tenant_key, DocumentStatus.ACTIVO.value)).fetchall()
        q = (query or "").strip().lower()
        tagset = {t.lower() for t in (tags or [])}
        results: List[Document] = []
        for row in rows:
            doc = _db_row_to_document(row)
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
        return results[:limit]

    # -- Lectura -----------------------------------------------------------
    def get_document(self, tenant_id: str, document_id: str) -> Document:
        tenant_key = _tenant_key(tenant_id)
        row = self.db.conn.execute(
            """SELECT * FROM documents WHERE id=? AND tenant_id=?""",
            (document_id, tenant_key)).fetchone()
        if not row:
            raise KeyError(f"Documento no encontrado: {document_id}")
        return _db_row_to_document(row)

    def read_document_bytes(self, tenant_id: str, document_id: str) -> bytes:
        doc = self.get_document(tenant_id, document_id)
        try:
            return self.storage.read(doc.storage_path)
        except StorageBackendError as e:
            raise StorageBackendError(f"Contenido no disponible: {e}") from e

    # -- Versiones ---------------------------------------------------------
    def get_version_history(self, tenant_id: str, document_id: str) -> List[DocumentVersion]:
        self.get_document(tenant_id, document_id)  # valida pertenencia
        rows = self.db.conn.execute(
            """SELECT * FROM document_versions WHERE document_id=? AND tenant_id=?
               ORDER BY version DESC""",
            (document_id, _tenant_key(tenant_id))).fetchall()
        return [_db_row_to_version(r) for r in rows]

    # -- Compartición ------------------------------------------------------
    def share_document(
        self,
        tenant_id: str,
        document_id: str,
        shared_with: str,
        permission: SharePermission = SharePermission.LECTURA,
        expires_at: Optional[datetime] = None,
    ) -> DocumentShare:
        tenant_key = _tenant_key(tenant_id)
        self.get_document(tenant_id, document_id)
        share = DocumentShare(
            id=str(_uuid.uuid4()),
            document_id=document_id,
            shared_with=shared_with.strip(),
            permission=permission,
            expires_at=expires_at,
        )
        self.db.conn.execute(
            """INSERT INTO document_shares (id, document_id, tenant_id,
               shared_with, permission, token, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (share.id, share.document_id, tenant_key, share.shared_with,
             share.permission.value, share.token, _utcnow_iso(),
             share.expires_at.isoformat() if share.expires_at else None),
        )
        self.db.conn.commit()
        return share

    def list_shares(self, tenant_id: str, document_id: str) -> List[DocumentShare]:
        self.get_document(tenant_id, document_id)
        rows = self.db.conn.execute(
            """SELECT * FROM document_shares WHERE document_id=? AND tenant_id=?
               ORDER BY created_at""",
            (document_id, _tenant_key(tenant_id))).fetchall()
        return [_db_row_to_share(r) for r in rows]

    # -- Utilidades --------------------------------------------------------
    def add_tag(self, tenant_id: str, document_id: str, tag: str) -> Document:
        doc = self.get_document(tenant_id, document_id)
        tag = tag.strip()
        if tag and tag not in doc.tags:
            doc.tags.append(tag)
            self.db.conn.execute(
                "UPDATE documents SET tags=?, updated_at=? WHERE id=?",
                (json.dumps(doc.tags), _utcnow_iso(), doc.id))
            self.db.conn.commit()
        return doc

    def archive_document(self, tenant_id: str, document_id: str) -> Document:
        doc = self.get_document(tenant_id, document_id)
        doc.status = DocumentStatus.ARCHIVADO
        self.db.conn.execute(
            "UPDATE documents SET status=?, updated_at=? WHERE id=?",
            (doc.status.value, _utcnow_iso(), doc.id))
        self.db.conn.commit()
        return doc

    def _find_by_name(self, tenant_key: str, name: str) -> Optional[Document]:
        row = self.db.conn.execute(
            """SELECT * FROM documents WHERE tenant_id=? AND name=? AND status!=?
               LIMIT 1""",
            (tenant_key, name, DocumentStatus.ELIMINADO.value)).fetchone()
        return _db_row_to_document(row) if row else None
