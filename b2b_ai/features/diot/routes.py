# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo DIOT.

Endpoints:
    POST /api/v1/diot/generate                       Generar DIOT
    GET  /api/v1/diot/{client_rfc}/{period}          Obtener DIOT
    POST /api/v1/diot/{client_rfc}/{period}/validate Validar DIOT
    GET  /api/v1/diot/{client_rfc}/{period}/export/txt  Exportar TXT
    GET  /api/v1/diot/{client_rfc}/{period}/export/xml  Exportar XML
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from b2b_ai.features.diot.models import DIOTPeriod
from b2b_ai.features.diot.service import DIOTService
from b2b_ai.features.diot.validators import validate_records


class GenerateDiotRequest(BaseModel):
    client_rfc: str = Field(..., description="RFC del contribuyente")
    period: str = Field(..., description="Período YYYY-QN (ej. 2024-Q3)")
    records: List[dict] = Field(default_factory=list, description="Operaciones con terceros")


class ValidateDiotRequest(BaseModel):
    records: List[dict] = Field(..., description="Registros DIOT a validar")


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""
    data: Optional[dict] = None


def build_diot_router(db: Any = None, require_api_key: Any = None) -> APIRouter:
    """Construye el router DIOT (/api/v1/diot/*)."""
    if require_api_key is None:
        raise ValueError("require_api_key es obligatorio. Nunca construir el router sin auth.")
    auth_dep = require_api_key
    service = DIOTService()
    router = APIRouter(prefix="/api/v1/diot", tags=["diot"])

    def _parse_period(period: str) -> DIOTPeriod:
        try:
            return DIOTPeriod.from_string(period)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Período inválido: {e}")

    @router.post("/generate", summary="Genera una DIOT.", response_model=None)
    def generate_diot(req: GenerateDiotRequest, auth_info: dict = Depends(auth_dep)) -> dict:
        period = _parse_period(req.period)
        declaration = service.generate_diot(period=period, client_rfc=req.client_rfc, records=req.records)
        return {"ok": True, "message": f"DIOT {declaration.period_label} generada.", "declaration": declaration.to_dict()}

    @router.get("/{client_rfc}/{period}", summary="Obtiene la DIOT.", response_model=None)
    def get_diot(client_rfc: str, period: str, auth_info: dict = Depends(auth_dep)) -> dict:
        p = _parse_period(period)
        declaration = service.get_declaration(client_rfc, p)
        if not declaration:
            raise HTTPException(status_code=404, detail=f"No existe DIOT para {client_rfc} / {p.label}.")
        return {"ok": True, "declaration": declaration.to_dict()}

    @router.post("/{client_rfc}/{period}/validate", summary="Valida la DIOT.", response_model=None)
    def validate_diot(client_rfc: str, period: str, req: Optional[ValidateDiotRequest] = None,
                      auth_info: dict = Depends(auth_dep)) -> dict:
        p = _parse_period(period)
        if req and req.records:
            result = validate_records(req.records)
        else:
            declaration = service.get_declaration(client_rfc, p)
            if not declaration:
                raise HTTPException(status_code=404, detail=f"No existe DIOT para {client_rfc} / {p.label}.")
            result = service.validate_diot(declaration.records)
        return {"ok": result.valid, "message": "DIOT válida." if result.valid else "Se encontraron errores.",
                "data": result.to_dict()}

    @router.get("/{client_rfc}/{period}/export/txt", summary="Exporta la DIOT a TXT.", response_class=PlainTextResponse)
    def export_txt(client_rfc: str, period: str, auth_info: dict = Depends(auth_dep)) -> str:
        p = _parse_period(period)
        declaration = service.get_declaration(client_rfc, p)
        if not declaration:
            raise HTTPException(status_code=404, detail=f"No existe DIOT para {client_rfc} / {p.label}.")
        path = service.export_to_txt(declaration.records)
        return Path(path).read_text(encoding="utf-8")

    @router.get("/{client_rfc}/{period}/export/xml", summary="Exporta la DIOT a XML.", response_class=PlainTextResponse)
    def export_xml(client_rfc: str, period: str, auth_info: dict = Depends(auth_dep)) -> str:
        p = _parse_period(period)
        declaration = service.get_declaration(client_rfc, p)
        if not declaration:
            raise HTTPException(status_code=404, detail=f"No existe DIOT para {client_rfc} / {p.label}.")
        path = service.export_to_xml(declaration.records)
        return Path(path).read_text(encoding="utf-8")

    return router
