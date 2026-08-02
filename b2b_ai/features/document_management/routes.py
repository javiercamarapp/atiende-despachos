# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del sistema de gestión documental.

Endpoints (todos autenticados por API key):
    POST /api/v1/documents/upload                 Sube un documento (multipart).
    GET  /api/v1/documents/search                 Busca documentos (query/tags/categoría).
    GET  /api/v1/documents/{id}                   Obtiene metadata de un documento.
    GET  /api/v1/documents/{id}/content           Descarga el contenido.
    GET  /api/v1/documents/{id}/versions          Historial de versiones.
    POST /api/v1/documents/{id}/share             Comparte el documento.
    GET  /api/v1/documents/{id}/shares            Lista comparticiones.
    POST /api/v1/documents/{id}/tags              Añade un tag.

Prefijo /api/v1/documents — no colisiona con módulos existentes.
"""
from __future__ import annotations

import tempfile
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from b2b_ai.features.document_management.models import (
    Document,
    DocumentCategory,
    SharePermission,
)
from b2b_ai.features.document_management.ocr_integration import (
    extract_document_metadata,
)
from b2b_ai.features.document_management.service import (
    DocumentService,
    _reset_state as _docs_reset_state,
)

ROUTER_PREFIX = "/api/v1/documents"

# Límite de subida (15 MB, coherente con el módulo batch/data-migration).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _require_tenant(auth_info: dict) -> str:
    """Extrae tenant_id del contexto de auth.

    El dep de auth ya valida la API key y resuelve el tenant. Si el tenant
    no está disponible, NO degradamos a un bucket compartido: rechazamos
    con 400. Esto preserva el aislamiento multi-tenant en todos los casos.
    """
    tenant_id = (auth_info or {}).get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Falta tenant_id en el contexto de autenticación. "
                   "No se permite acceder al bucket compartido.",
        )
    return str(tenant_id)


def _sanitize_download_name(name: str) -> str:
    """Devuelve solo el basename del nombre, sin comillas / CR / LF.

    Previene header injection / response splitting vía Content-Disposition.
    """
    import os as _os
    base = _os.path.basename(str(name or ""))
    # Elimina caracteres peligrosos para headers HTTP.
    return "".join(ch for ch in base if ch not in ('"', "'", "\r", "\n", ";"))



def build_document_router(db: Any = None,
                          require_api_key: Any = None) -> APIRouter:
    """Construye el router /api/v1/documents/* de gestión documental."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = DocumentService(db=db)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["document-management"])

    @router.post("/upload", summary="Sube un documento.")
    async def upload_document(
        file: UploadFile = File(...),
        category: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        created_by: Optional[str] = Form(None),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"El archivo supera el límite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )
        try:
            cat = DocumentCategory(category) if category else DocumentCategory.OTRO
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Categoría inválida: {category}")

        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

        # Auto-metadata vía OCR/integración
        meta = extract_document_metadata(
            file.filename or "",
            file.content_type or "",
            data,
            category=cat.value,
        )

        try:
            doc = service.upload_document(
                tenant_id=tenant_id,
                name=file.filename or "documento",
                data=data,
                category=cat,
                content_type=file.content_type or "application/octet-stream",
                metadata={k: str(v) for k, v in meta.items()},
                tags=tag_list,
                created_by=created_by or auth_info.get("user_id"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"ok": True, "document": doc.to_dict()}

    @router.get("/search", summary="Busca documentos.")
    def search_documents(
        q: Optional[str] = Query(None, description="Texto de búsqueda"),
        category: Optional[str] = Query(None),
        tag: Optional[str] = Query(None, description="Tag a filtrar (repetible)"),
        limit: int = Query(50, ge=1, le=200),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        cat = None
        if category:
            try:
                cat = DocumentCategory(category)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Categoría inválida: {category}")
        tags = [t.strip() for t in (tag or "").split(",") if t.strip()] if tag else None
        docs = service.search_documents(
            tenant_id=tenant_id, query=q, category=cat, tags=tags, limit=limit)
        return {"ok": True, "count": len(docs), "results": [d.to_dict() for d in docs]}

    @router.get("/{document_id}", summary="Obtiene metadata de un documento.")
    def get_document(document_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            doc = service.get_document(tenant_id, document_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        return {"ok": True, "document": doc.to_dict()}

    @router.get("/{document_id}/content", summary="Descarga el contenido del documento.")
    def get_content(document_id: str, auth_info: dict = Depends(auth_dep)) -> Response:
        tenant_id = _require_tenant(auth_info)
        try:
            doc = service.get_document(tenant_id, document_id)
            data = service.read_document_bytes(tenant_id, document_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        safe_name = _sanitize_download_name(doc.name)
        return Response(
            content=data,
            media_type=doc.content_type,
            headers={
                "Content-Disposition":
                    f'attachment; filename="{safe_name}"'
            },
        )

    @router.get("/{document_id}/versions", summary="Historial de versiones.")
    def get_versions(document_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            versions = service.get_version_history(tenant_id, document_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        return {"ok": True, "versions": [v.to_dict() for v in versions]}

    @router.post("/{document_id}/share", summary="Comparte un documento.")
    def share_document(
        document_id: str,
        payload: dict,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant_id = _require_tenant(auth_info)
        shared_with = (payload.get("shared_with") or "").strip()
        if not shared_with:
            raise HTTPException(status_code=400, detail="shared_with es obligatorio.")
        try:
            perm = SharePermission(payload.get("permission", SharePermission.LECTURA))
        except ValueError:
            raise HTTPException(status_code=400, detail="Permiso inválido.")
        try:
            share = service.share_document(
                tenant_id, document_id, shared_with, permission=perm)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        return {"ok": True, "share": share.to_dict()}

    @router.get("/{document_id}/shares", summary="Lista comparticiones.")
    def list_shares(document_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = _require_tenant(auth_info)
        try:
            shares = service.list_shares(tenant_id, document_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        return {"ok": True, "shares": [s.to_dict() for s in shares]}

    @router.post("/{document_id}/tags", summary="Añade un tag a un documento.")
    def add_tag(document_id: str, payload: dict,
                auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = _require_tenant(auth_info)
        tag = (payload.get("tag") or "").strip()
        if not tag:
            raise HTTPException(status_code=400, detail="tag es obligatorio.")
        try:
            doc = service.add_tag(tenant_id, document_id, tag)
        except KeyError:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        return {"ok": True, "document": doc.to_dict()}

    return router
