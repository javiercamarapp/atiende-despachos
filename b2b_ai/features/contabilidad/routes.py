# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Contabilidad Electrónica.

Endpoints:
    POST /contabilidad/balanza         — Sube XML, retorna datos Balanza.
    POST /contabilidad/catalogo        — Sube XML, retorna datos Catálogo.
    POST /contabilidad/estado-resultados — Sube XML, retorna datos EstadoResultados.
    GET  /contabilidad/catalog         — Catálogo SAT de contabilidad electrónica.

El router se construye con `build_contabilidad_router()` para inyectar DB y
dependencias de auth en tests.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from b2b_ai.features.contabilidad.parser import (
    parse_balanza_bytes,
    parse_catalogo_bytes,
    parse_estado_resultados_bytes,
)
from b2b_ai.features.contabilidad.validators import (
    validate_balanza,
    validate_catalogo,
    validate_estado_resultados,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ContabilidadCatalog(BaseModel):
    """Catálogo SAT de códigos de contabilidad electrónica."""
    naturaleza: dict
    tipo_balanza: dict


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_contabilidad_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /contabilidad/*.

    Sigue el patrón `build_*_router()` del proyecto para inyección de DB.
    Los endpoints de contabilidad no requieren auth por ser parsing/validación
    local (sin persistencia).
    """
    router = APIRouter(prefix="/contabilidad", tags=["contabilidad"])
    if require_api_key:
        router.dependencies.append(Depends(require_api_key))

    @router.post(
        "/balanza",
        summary="Parsea Balanza de Comprobación de un XML SAT.",
        response_model=None,
    )
    async def parse_balanza_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo XML de contabilidad electrónica y extrae la
        Balanza de Comprobación.

        Retorna los datos como JSON o 404 si no hay nodo Balanza.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_balanza_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene Balanza de Comprobación.",
            )

        return {"ok": True, "balanza": data.to_dict()}

    @router.post(
        "/catalogo",
        summary="Parsea Catálogo de Cuentas de un XML SAT.",
        response_model=None,
    )
    async def parse_catalogo_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo XML de contabilidad electrónica y extrae el
        Catálogo de Cuentas.

        Retorna los datos como JSON o 404 si no hay nodo Catalogo.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_catalogo_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene Catálogo de Cuentas.",
            )

        return {"ok": True, "catalogo": data.to_dict()}

    @router.post(
        "/estado-resultados",
        summary="Parsea Estado de Resultados de un XML SAT.",
        response_model=None,
    )
    async def parse_estado_resultados_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo XML de contabilidad electrónica y extrae el
        Estado de Resultados.

        Retorna los datos como JSON o 404 si no hay nodo EstadoResultados.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_estado_resultados_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene Estado de Resultados.",
            )

        return {"ok": True, "estado_resultados": data.to_dict()}

    @router.get(
        "/catalog",
        summary="Catálogo SAT de contabilidad electrónica.",
    )
    def contabilidad_catalog():
        """Retorna los catálogos SAT para naturaleza de cuenta
        y tipo de balance.
        """
        return {
            "naturaleza": {"D": "Deudor", "A": "Acreedor"},
            "tipo_balanza": {
                "A": "Auxiliar",
                "C": "Comprobación",
                "E": "Estados financieros",
                "F": "Fiscal",
                "N": "Complemento",
                "S": "Saldos y movimientos",
            },
        }

    return router
