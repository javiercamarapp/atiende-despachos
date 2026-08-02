# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Client Query Response API.

Endpoints:
    POST /api/v1/clientes/query          — Process a client query
    GET  /api/v1/clientes/faq            — List FAQ entries
    GET  /api/v1/clientes/status/{cfdi_id} — Get invoice status
    POST /api/v1/clientes/deductibility  — Get deductibility info

The router is built with `build_clientes_router(db, require_api_key)`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.clientes.models import (
    ClientQuery,
    FAQEntry,
    InvoiceStatus,
    QueryCategory,
    QueryType,
)
from b2b_ai.features.clientes.service import ClientService
from b2b_ai.features.clientes.validators import (
    validate_cfdi_id,
    validate_client_query,
    validate_query_type,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request to process a client query."""
    tipo: QueryType = Field(..., description="Type of query")
    contenido: str = Field(..., description="Query content/body")
    tenant_id: str = Field(default="default", description="Tenant ID")
    cliente_rfc: Optional[str] = Field(default=None, description="Client RFC")
    prioridad: int = Field(default=3, ge=1, le=5, description="Priority 1-5")


class DeductibilityRequest(BaseModel):
    """Request for deductibility information."""
    concepto: str = Field(..., description="Expense concept to check")


class QueryResponse(BaseModel):
    """Response from query processing."""
    ok: bool = Field(default=True)
    query_id: str = Field(default="")
    tipo: str = Field(default="")
    categoria: Optional[str] = Field(default=None)
    respuesta: str = Field(default="")


class FAQResponse(BaseModel):
    """FAQ listing response."""
    ok: bool = Field(default=True)
    total: int = Field(default=0)
    entries: List[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_clientes_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the clientes API router.

    Parameters
    ----------
    db : Database instance.
    require_api_key : FastAPI dependency for auth.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key

    # In-memory stores (per-service instance)
    _services: Dict[str, ClientService] = {}
    _invoices_store: Dict[str, InvoiceStatus] = {}

    def _get_service(tenant_id: str) -> ClientService:
        if tenant_id not in _services:
            _services[tenant_id] = ClientService(tenant_id=tenant_id)
        return _services[tenant_id]

    router = APIRouter(prefix="/api/v1/clientes", tags=["clientes"])

    # -----------------------------------------------------------------------
    # POST /query — Process a client query
    # -----------------------------------------------------------------------
    @router.post(
        "/query",
        summary="Process a client query and generate a draft response.",
        response_model=None,
    )
    def process_query(
        req: QueryRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Receive a client query, route it to the correct handler,
        and return a draft response."""
        # Validate
        is_valid, errors = validate_client_query(req.model_dump())
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Errores de validación: {'; '.join(errors)}",
            )

        service = _get_service(req.tenant_id)
        query = ClientQuery(
            tipo=req.tipo,
            contenido=req.contenido,
            tenant_id=req.tenant_id,
            cliente_rfc=req.cliente_rfc,
            prioridad=req.prioridad,
        )

        result = service.process_client_query(query)

        return {
            "ok": True,
            "query_id": result.id,
            "tipo": result.tipo.value,
            "categoria": result.categoria.value if result.categoria else None,
            "respuesta": result.respuesta,
            "created_at": result.created_at,
        }

    # -----------------------------------------------------------------------
    # GET /faq — List FAQ entries
    # -----------------------------------------------------------------------
    @router.get(
        "/faq",
        summary="List FAQ entries, optionally filtered by category.",
        response_model=None,
    )
    def list_faqs(
        category: Optional[str] = Query(default=None, description="Filter by category"),
        tenant_id: str = Query(default="default", description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Return FAQ entries. Optionally filter by category."""
        service = _get_service(tenant_id)

        cat_enum = None
        if category:
            try:
                cat_enum = QueryCategory(category)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Categoría inválida: '{category}'",
                )

        entries = service.get_faqs(category=cat_enum)
        return {
            "ok": True,
            "total": len(entries),
            "entries": [e.model_dump() for e in entries],
        }

    # -----------------------------------------------------------------------
    # GET /status/{cfdi_id} — Get invoice status
    # -----------------------------------------------------------------------
    @router.get(
        "/status/{cfdi_id}",
        summary="Get invoice status by CFDI UUID.",
        response_model=None,
    )
    def get_status(
        cfdi_id: str,
        tenant_id: str = Query(default="default", description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Look up invoice status by CFDI UUID."""
        is_valid, errors = validate_cfdi_id(cfdi_id)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"ID de CFDI inválido: {'; '.join(errors)}",
            )

        service = _get_service(tenant_id)
        invoice = service.get_invoice_status(cfdi_id)

        if not invoice:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró factura con ID '{cfdi_id}'.",
            )

        return {
            "ok": True,
            "invoice": invoice.model_dump(),
        }

    # -----------------------------------------------------------------------
    # POST /deductibility — Get deductibility info
    # -----------------------------------------------------------------------
    @router.post(
        "/deductibility",
        summary="Get deductibility information for an expense concept.",
        response_model=None,
    )
    def get_deductibility(
        req: DeductibilityRequest,
        tenant_id: str = Query(default="default", description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Return deductibility information for a given expense concept."""
        if not req.concepto or not req.concepto.strip():
            raise HTTPException(
                status_code=422,
                detail="El concepto es obligatorio.",
            )

        service = _get_service(tenant_id)
        info = service.get_deductibility_info(req.concepto)

        return {
            "ok": True,
            **info,
        }

    return router
