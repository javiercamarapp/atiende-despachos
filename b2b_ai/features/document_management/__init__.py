# -*- coding: utf-8 -*-
"""
document_management — Sistema de gestión documental del despacho contable.

Almacena, versiona, indexa y comparte documentos (CFDI, contratos, cartas
porte, nómina XML, constancias, etc.) con integridad garantizada por hash
SHA-256 y búsqueda flexible por tags/metadata.

Expone:
  - DocumentCategory, DocumentStatus, Document, DocumentVersion,
    DocumentShare, SharePermission — entidades de dominio
  - DocumentService — lógica de negocio (upload/search/share/versionado)
  - LocalStorage, S3Storage, get_backend — abstracción de almacenamiento
  - extract_text_from_pdf / extract_cfdi_data_from_xml — OCR / extracción
  - build_document_router() — router FastAPI /api/v1/documents/*
"""
from __future__ import annotations

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
    S3Storage,
    StorageBackendError,
    get_backend,
)
from b2b_ai.features.document_management.ocr_integration import (
    extract_cfdi_data_from_xml,
    extract_document_metadata,
    extract_text_from_pdf,
)
from b2b_ai.features.document_management.service import (
    DocumentService,
    _reset_state,
)
from b2b_ai.features.document_management.routes import build_document_router

__all__ = [
    "Document",
    "DocumentCategory",
    "DocumentShare",
    "DocumentStatus",
    "DocumentVersion",
    "SharePermission",
    "BaseStorage",
    "LocalStorage",
    "S3Storage",
    "StorageBackendError",
    "get_backend",
    "extract_cfdi_data_from_xml",
    "extract_document_metadata",
    "extract_text_from_pdf",
    "DocumentService",
    "_reset_state",
    "build_document_router",
]
