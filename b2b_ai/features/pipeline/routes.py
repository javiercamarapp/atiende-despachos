# -*- coding: utf-8 -*-
"""routes.py — FastAPI router del orquestador end-to-end del pipeline.

Endpoint:
    POST /api/v1/pipeline/run    flujo completo CFDI → bookkeeping → conciliación

Recibe una lista de CFDIs (contenido XML) y opcionalmente transacciones
bancarias para la conciliación. Un solo endpoint que hace todo el flujo.

Auth: requiere API key (require_api_key). El tenant se deriva SIEMPRE del
token autenticado (auth_info) — nunca del body (patrón P1-2 del repo).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from b2b_ai.features.pipeline.orchestrator import (
    EndToEndOrchestrator,
    EndToEndPipelineError,
)
from b2b_ai.features.roles.middleware import make_require_permission
from b2b_ai.features.roles.models import Permission
from b2b_ai.features.roles.service import RolesService


class CfdiFileIn(BaseModel):
    """Un CFDI a procesar (contenido XML)."""
    filename: str = Field(..., description="Nombre del archivo (diagnóstico).")
    content: str = Field(..., description="Contenido XML del CFDI.")


class PipelineRunRequest(BaseModel):
    """Request del flujo end-to-end."""
    cfdis: List[CfdiFileIn] = Field(..., description="Lista de CFDIs a procesar.")
    periodo: str = Field(default="", description="Periodo YYYY-MM.")
    fecha: Optional[str] = Field(default=None, description="Fecha override de pólizas.")
    auto_register_erp: bool = Field(default=True, description="Registrar en ERP (mock).")
    bank_transactions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Transacciones bancarias (id, date, description, amount, type, reference, bank_account).",
    )
    date_tolerance_days: int = Field(default=3, ge=0, le=30)


def build_pipeline_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router del pipeline end-to-end (/api/v1/pipeline)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    require_permission = make_require_permission(require_api_key, RolesService())
    orchestrator = EndToEndOrchestrator()

    router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

    @router.post(
        "/run",
        summary="Ejecuta el flujo completo CFDI → bookkeeping → conciliación.",
        response_model=None,
    )
    async def run_pipeline(
        req: PipelineRunRequest,
        auth_info: dict = Depends(auth_dep),
        _perm: dict = Depends(require_permission(Permission.PIPELINE_RUN)),
    ) -> dict:
        """Un solo endpoint que hace todo el flujo.

        parse → adapt → generate_entries → reconcile_with_bank.
        El tenant se toma del token autenticado.
        """
        if not req.cfdis:
            raise HTTPException(400, "Se requiere al menos un CFDI.")

        tenant_id = str(auth_info.get("tenant_id") or "") if auth_info else ""
        xml_files = [(c.filename, c.content) for c in req.cfdis]

        try:
            result = orchestrator.upload_cfdis(
                xml_files=xml_files,
                tenant_id=tenant_id,
                periodo=req.periodo,
                fecha=req.fecha,
                auto_register_erp=req.auto_register_erp,
                bank_transactions=req.bank_transactions or None,
                date_tolerance_days=req.date_tolerance_days,
            )
        except EndToEndPipelineError as exc:
            raise HTTPException(400, str(exc)) from exc

        return {"ok": True, **result}

    return router


__all__ = ["build_pipeline_router"]
