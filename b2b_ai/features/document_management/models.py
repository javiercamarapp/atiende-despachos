# -*- coding: utf-8 -*-
"""
models.py — Entidades de dominio del sistema de gestión documental.

Cubre:
  - DocumentCategory   : categorías (CFDI, contrato, carta porte, nómina XML,
                         constancia, otro).
  - DocumentStatus     : ciclo de vida del documento.
  - Document           : documento con hash SHA-256 de integridad, versionado,
                         metadata y tags.
  - DocumentVersion    : versión congelada de un documento (inmutable).
  - DocumentShare      : compartición con un tercero/colaborador.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class DocumentCategory(str, Enum):
    """Categorías de documentos del despacho contable."""
    CFDI = "CFDI"
    CONTRATO = "contrato"
    CARTA_PORTE = "carta_porte"
    NOMINA_XML = "nomina_xml"
    CONSTANCIA = "constancia"
    OTRO = "otro"


class DocumentStatus(str, Enum):
    """Ciclo de vida de un documento."""
    ACTIVO = "ACTIVO"
    ARCHIVADO = "ARCHIVADO"
    ELIMINADO = "ELIMINADO"


class SharePermission(str, Enum):
    """Permisos de compartición de documentos."""
    LECTURA = "lectura"
    EDICION = "edicion"


class Document(BaseModel):
    """Documento gestionado con integridad y versionado.

    Campos clave:
      - sha256     : hash de integridad del contenido actual.
      - version    : versión actual (empieza en 1).
      - metadata   : dict libre (tipo CFDI, RFC, folio fiscal, etc).
      - tags       : etiquetas para búsqueda flexible.
    """
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    tenant_id: Optional[str] = Field(default=None, description="Tenant dueño del documento")
    name: str = Field(..., description="Nombre original del archivo")
    category: DocumentCategory = Field(default=DocumentCategory.OTRO)
    content_type: str = Field(default="application/octet-stream")
    size: int = Field(default=0, ge=0)
    sha256: str = Field(default="", description="Hash SHA-256 del contenido")
    storage_path: str = Field(default="", description="Path lógico en el backend")
    version: int = Field(default=1, ge=1)
    metadata: Dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    status: DocumentStatus = Field(default=DocumentStatus.ACTIVO)
    created_by: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.utcnow())
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.utcnow())

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name no puede estar vacío")
        return v

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "category": self.category.value,
            "content_type": self.content_type,
            "size": self.size,
            "sha256": self.sha256,
            "storage_path": self.storage_path,
            "version": self.version,
            "metadata": self.metadata,
            "tags": list(self.tags),
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentVersion(BaseModel):
    """Versión congelada e inmutable de un documento."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    document_id: str = Field(..., description="Documento padre")
    version: int = Field(..., ge=1)
    sha256: str = Field(..., description="Hash SHA-256 del contenido en esta versión")
    storage_path: str = Field(..., description="Path lógico de esta versión")
    size: int = Field(default=0, ge=0)
    note: str = Field(default="", description="Nota del cambio")
    created_by: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "version": self.version,
            "sha256": self.sha256,
            "storage_path": self.storage_path,
            "size": self.size,
            "note": self.note,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DocumentShare(BaseModel):
    """Compartición de un documento con un tercero/colaborador."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    document_id: str = Field(..., description="Documento compartido")
    shared_with: str = Field(..., description="Email o RFC del destinatario")
    permission: SharePermission = Field(default=SharePermission.LECTURA)
    token: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                       description="Token de acceso para el destinatario")
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    expires_at: Optional[datetime] = Field(default=None)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "shared_with": self.shared_with,
            "permission": self.permission.value,
            "token": self.token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
