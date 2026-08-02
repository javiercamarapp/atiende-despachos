# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de Bank Feeds.

Endpoints (/api/v1/bank-feeds/*):
    POST   /accounts                 Conecta una cuenta bancaria.
    GET    /accounts                 Lista cuentas del tenant.
    GET    /accounts/{id}            Detalle de una cuenta.
    POST   /accounts/{id}/sync       Ejecuta sincronización del feed.
    GET    /accounts/{id}/transactions  Lista transacciones de la cuenta.
    GET    /accounts/{id}/syncs      Historial de sincronizaciones.
    POST   /transactions/{id}/categorize  Categoriza una transacción.
    POST   /reconcile                Cruza transacciones con CFDI/pólizas.

Todos los endpoints exigen autenticación por API key (require_api_key).
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.bank_feeds.models import (
    BankProvider,
    Category,
    TransactionStatus,
)
from b2b_ai.features.bank_feeds.service import BankFeedService
from b2b_ai.features.roles.middleware import make_require_permission
from b2b_ai.features.roles.models import Permission
from b2b_ai.features.roles.service import RolesService

logger = logging.getLogger("b2b_ai.bank_feeds")


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""
    data: Optional[Any] = None


class ConnectAccountRequest(BaseModel):
    provider: BankProvider = Field(..., description="Banco (BBVA, BANORTE, SANTANDER, HSBC)")
    clabe: str = Field(default="", description="CLABE de 18 dígitos (opcional para MVP)")
    account_label: str = Field(default="", description="Etiqueta amigable")
    ofx_content: Optional[str] = Field(default=None, description="Estado de cuenta OFX/QFX (MVP)")
    statement_text: Optional[str] = Field(default=None, description="Estado CNBV (MVP)")
    tenant_id: str = Field(default="")


class CategorizeRequest(BaseModel):
    category: Optional[Category] = Field(default=None, description="Categoría explícita")
    auto: bool = Field(default=False, description="Inferir por heurística")


class ReconcileRequest(BaseModel):
    account_id: Optional[str] = Field(default=None)
    cfdi_list: Optional[List[dict]] = Field(default=None)
    tolerance_days: int = Field(default=3, ge=0, le=30)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def build_bank_feeds_router(db: Any = None, require_api_key: Any = None) -> APIRouter:
    """Construye el router de bank feeds (/api/v1/bank-feeds)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    require_permission = make_require_permission(require_api_key, RolesService())
    service = BankFeedService(db=db)
    router = APIRouter(prefix="/api/v1/bank-feeds", tags=["bank-feeds", "conciliacion"])

    @router.post("/accounts", summary="Conecta una cuenta bancaria.",
                 response_model=None)
    def connect_account(
        req: ConnectAccountRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_MANAGE)),
    ) -> dict:
        """Registra una cuenta bancaria para importar transacciones."""
        tenant_id = req.tenant_id or auth_info.get("tenant_id") or ""
        try:
            account = service.register_account(
                provider=req.provider,
                clabe=req.clabe,
                account_label=req.account_label,
                tenant_id=tenant_id,
                ofx_content=req.ofx_content,
                statement_text=req.statement_text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "message": "Cuenta conectada.", "data": account.to_dict()}

    @router.get("/accounts", summary="Lista cuentas bancarias del tenant.",
                response_model=None)
    def list_accounts(
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_VIEW)),
    ) -> dict:
        tenant_id = auth_info.get("tenant_id") or ""
        accounts = service.list_accounts(tenant_id=tenant_id)
        return {"ok": True, "data": [a.to_dict() for a in accounts]}

    @router.get("/accounts/{account_id}", summary="Detalle de una cuenta.",
                response_model=None)
    def get_account(account_id: str, auth_info: dict = Depends(auth_dep),
                    _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_VIEW))) -> dict:
        account = service.get_account(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
        return {"ok": True, "data": account.to_dict()}

    @router.post("/accounts/{account_id}/sync",
                 summary="Ejecuta una sincronización del feed.",
                 response_model=None)
    def sync_account(
        account_id: str,
        from_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        to_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        limit: int = Query(default=200, ge=1, le=1000),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_SYNC)),
    ) -> dict:
        try:
            result = service.sync_transactions(
                account_id, from_date=from_date, to_date=to_date, limit=limit
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": True, "data": result.to_dict()}

    @router.get("/accounts/{account_id}/transactions",
                summary="Lista transacciones de una cuenta.",
                response_model=None)
    def list_transactions(
        account_id: str,
        status: Optional[TransactionStatus] = Query(default=None),
        category: Optional[Category] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_VIEW)),
    ) -> dict:
        txns = service.list_transactions(
            account_id=account_id, status=status, category=category, limit=limit
        )
        return {"ok": True, "data": [t.to_dict() for t in txns]}

    @router.get("/accounts/{account_id}/syncs",
                summary="Historial de sincronizaciones de la cuenta.",
                response_model=None)
    def list_syncs(account_id: str, auth_info: dict = Depends(auth_dep),
                   _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_VIEW))) -> dict:
        syncs = service.get_syncs(account_id=account_id)
        return {"ok": True, "data": [s.to_dict() for s in syncs]}

    @router.post("/transactions/{txn_id}/categorize",
                 summary="Categoriza una transacción.",
                 response_model=None)
    def categorize_transaction(
        txn_id: str,
        req: CategorizeRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_MANAGE)),
    ) -> dict:
        try:
            txn = service.categorize_transaction(
                txn_id, category=req.category, auto=req.auto
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "data": txn.to_dict()}

    @router.post("/reconcile", summary="Cruza transacciones con CFDI/pólizas.",
                 response_model=None)
    def reconcile(req: ReconcileRequest, auth_info: dict = Depends(auth_dep),
                  _perm: dict = Depends(require_permission(Permission.BANK_FEEDS_SYNC))) -> dict:
        result = service.reconcile_with_cfdi(
            account_id=req.account_id,
            cfdi_list=req.cfdi_list,
            tolerance_days=req.tolerance_days,
        )
        return {"ok": True, "data": result}

    return router
