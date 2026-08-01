# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Income/Expense Reconciliation API.

Endpoints:
    POST /api/v1/reconciliacion-ingresos/recopilar         — Collect data
    POST /api/v1/reconciliacion-ingresos/clasificar         — Classify deposits
    POST /api/v1/reconciliacion-ingresos/conciliar          — Run reconciliation
    POST /api/v1/reconciliacion-ingresos/balance-iva        — Calculate IVA balance
    GET  /api/v1/reconciliacion-ingresos/papel-trabajo/{periodo} — Get working paper
    GET  /api/v1/reconciliacion-ingresos/discrepancias/{periodo} — Get discrepancies

The router is built with `build_reconciliacion_ingresos_egresos_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    BalanceIVA,
    ConciliacionIngresosEgresos,
    DepositoBancario,
    DiscrepanciaFiscal,
    PapelTrabajoConciliacion,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.validators import (
    validate_periodo,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RecopilarRequest(BaseModel):
    """Request to collect deposit and auxiliary data."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos bancarios (id, fecha, monto, descripcion, referencia, banco, cuenta, es_credito)",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares contables (cuenta_id, cuenta_mayor, cuenta_auxiliar, descripcion, saldo_inicial, movimientos, saldo_final)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ClasificarRequest(BaseModel):
    """Request to classify deposits."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos a clasificar",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares para matching",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ConciliarRequest(BaseModel):
    """Request to run reconciliation."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos bancarios",
    )
    auxiliares: List[dict] = Field(
        default_factory=list,
        description="Auxiliares contables",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class BalanceIVARequest(BaseModel):
    """Request to calculate IVA balance."""
    periodo: str = Field(
        ...,
        description="Período fiscal (YYYY-MM)",
    )
    declaraciones: List[dict] = Field(
        default_factory=list,
        description="Declaraciones de IVA (iva_cobrado, iva_pagado, declarado)",
    )
    depositos: List[dict] = Field(
        default_factory=list,
        description="Depósitos clasificados",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )


class ReconciliacionResponse(BaseModel):
    """Standard response for reconciliation operations."""
    ok: bool
    message: str = ""
    data: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_reconciliacion_ingresos_egresos_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construct the income/expense reconciliation API router.

    Parameters
    ----------
    db : Database instance (unused for now; matching is in-memory).
    require_api_key : FastAPI dependency for auth.
    """
    auth_dep = require_api_key or (lambda: None)

    # In-memory service
    service = ReconciliacionIngresosEgresosService()

    router = APIRouter(
        prefix="/api/v1/reconciliacion-ingresos",
        tags=["reconciliacion-ingresos"],
    )

    # -------------------------------------------------------------------
    # POST /recopilar — Collect data
    # -------------------------------------------------------------------
    @router.post(
        "/recopilar",
        summary="Recopilar depósitos bancarios y auxiliares contables.",
        response_model=None,
    )
    def recopilar_datos(
        req: RecopilarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Collect and validate bank deposits and auxiliary entries for a period."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        depositos = service.recopilar_depositos(
            req.periodo, tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, tenant_id, req.auxiliares
        )

        return {
            "ok": True,
            "message": f"Datos recopilados para período {req.periodo}.",
            "depositos_recibidos": len(req.depositos),
            "depositos_validos": len(depositos),
            "auxiliares_recibidos": len(req.auxiliares),
            "auxiliares_validos": len(auxiliares),
            "depositos": [d.model_dump() for d in depositos],
            "auxiliares": [a.model_dump() for a in auxiliares],
        }

    # -------------------------------------------------------------------
    # POST /clasificar — Classify deposits
    # -------------------------------------------------------------------
    @router.post(
        "/clasificar",
        summary="Clasificar depósitos bancarios por tipo fiscal.",
        response_model=None,
    )
    def clasificar_depositos(
        req: ClasificarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Classify deposits as income, financing, partner contribution, guarantee, or other."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        depositos = service.recopilar_depositos(
            req.periodo, req.tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, req.tenant_id, req.auxiliares
        )

        clasificaciones = service.clasificar_todos(depositos, auxiliares)

        return {
            "ok": True,
            "message": f"Clasificación completada: {len(clasificaciones)} depósitos.",
            "clasificaciones": [c.model_dump() for c in clasificaciones],
        }

    # -------------------------------------------------------------------
    # POST /conciliar — Run reconciliation
    # -------------------------------------------------------------------
    @router.post(
        "/conciliar",
        summary="Conciliar depósitos bancarios con auxiliares contables.",
        response_model=None,
    )
    def conciliar(
        req: ConciliarRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Run full reconciliation between bank deposits and auxiliary entries."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tenant_id = auth_info.get("tenant_id") if auth_info else req.tenant_id

        depositos = service.recopilar_depositos(
            req.periodo, tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, tenant_id, req.auxiliares
        )

        conciliacion = service.conciliar_depositos_auxiliares(depositos, auxiliares)
        conciliacion.periodo = req.periodo
        conciliacion.tenant_id = tenant_id

        # Generate working paper
        papel = service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

        return {
            "ok": True,
            "message": f"Conciliación completada para {req.periodo}.",
            "conciliacion": conciliacion.model_dump(),
            "papel_trabajo_id": f"{req.periodo}_{tenant_id or 'default'}",
        }

    # -------------------------------------------------------------------
    # POST /balance-iva — Calculate IVA balance
    # -------------------------------------------------------------------
    @router.post(
        "/balance-iva",
        summary="Calcular balance de IVA para un período.",
        response_model=None,
    )
    def balance_iva(
        req: BalanceIVARequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Calculate IVA balance from declarations and classified deposits."""
        is_valid, period_err = validate_periodo(req.periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        depositos = service.recopilar_depositos(
            req.periodo, req.tenant_id, req.depositos
        )
        auxiliares = service.recopilar_auxiliares(
            req.periodo, req.tenant_id, []
        )

        clasificaciones = service.clasificar_todos(depositos, auxiliares)

        balance = service.calcular_balance_iva(
            req.declaraciones, clasificaciones, depositos
        )

        return {
            "ok": True,
            "message": f"Balance IVA calculado para {req.periodo}.",
            "balance_iva": balance.model_dump(),
        }

    # -------------------------------------------------------------------
    # GET /papel-trabajo/{periodo} — Get working paper
    # -------------------------------------------------------------------
    @router.get(
        "/papel-trabajo/{periodo}",
        summary="Obtener papel de trabajo de conciliación.",
        response_model=None,
    )
    def get_papel_trabajo(
        periodo: str,
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve the working paper for a given period."""
        is_valid, period_err = validate_periodo(periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tid = tenant_id
        if auth_info and not tid:
            tid = auth_info.get("tenant_id")

        papel = service.get_papel_trabajo(periodo, tid)
        if not papel:
            raise HTTPException(
                status_code=404,
                detail=f"Papel de trabajo para período '{periodo}' no encontrado.",
            )

        return {
            "ok": True,
            "papel_trabajo": papel.model_dump(),
        }

    # -------------------------------------------------------------------
    # GET /discrepancias/{periodo} — Get discrepancies
    # -------------------------------------------------------------------
    @router.get(
        "/discrepancias/{periodo}",
        summary="Obtener discrepancias de conciliación para un período.",
        response_model=None,
    )
    def get_discrepancias(
        periodo: str,
        tenant_id: Optional[str] = Query(default=None, description="Tenant ID"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Retrieve discrepancies found during reconciliation for a period."""
        is_valid, period_err = validate_periodo(periodo)
        if not is_valid:
            raise HTTPException(status_code=422, detail=period_err)

        tid = tenant_id
        if auth_info and not tid:
            tid = auth_info.get("tenant_id")

        papel = service.get_papel_trabajo(periodo, tid)
        if not papel:
            raise HTTPException(
                status_code=404,
                detail=f"Papel de trabajo para período '{periodo}' no encontrado.",
            )

        return {
            "ok": True,
            "periodo": periodo,
            "discrepancias": [d.model_dump() for d in papel.discrepancias],
            "total": len(papel.discrepancias),
        }

    return router
