# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de nómina.

Endpoints:
    POST /nomina/parse     — Sube XML CFDI 4.0, retorna datos Nomina 1.2.
    POST /nomina/validate  — Sube XML CFDI 4.0, retorna errores de validación.
    GET  /nomina/catalog   — Catálogo SAT de códigos de nómina.

El router se construye con `build_nomina_router()` para inyectar DB y
dependencias de auth en tests.
"""
from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from b2b_ai.features.nomina.parser import parse_nomina, parse_nomina_bytes
from b2b_ai.features.nomina.validators import (
    validate_nomina,
    PERIODICIDAD_PAGO_CODES,
    TIPO_NOMINA_CODES,
    TIPO_JORNADA_CODES,
    RIESGO_PUESTO_CODES,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NominaCatalog(BaseModel):
    """Catálogo SAT de códigos de nómina."""
    periodicidad_pago: dict
    tipo_nomina: dict
    tipo_jornada: dict
    riesgo_puesto: dict


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_nomina_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /nomina/*.

    Sigue el patrón `build_*_router()` del proyecto para inyección de DB.
    Los endpoints de nómina no requieren auth por ser parsing/validación
    local (sin persistencia).
    """
    router = APIRouter(prefix="/nomina", tags=["nomina"])
    if require_api_key:
        router.dependencies.append(Depends(require_api_key))

    @router.post(
        "/parse",
        summary="Parsea complemento Nomina 1.2 de un CFDI XML.",
        response_model=None,
    )
    async def parse_nomina_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y extrae el complemento Nomina 1.2.

        Retorna los campos de nómina como JSON o 404 si no hay complemento.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_nomina_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene complemento de Nómina 1.2.",
            )

        return {"ok": True, "nomina": data.to_dict()}

    @router.post(
        "/validate",
        summary="Valida un CFDI con complemento Nomina 1.2 contra reglas SAT.",
        response_model=None,
    )
    async def validate_nomina_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y valida su complemento Nomina.

        Retorna errores de validación (lista vacía = válido).
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_nomina_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        errors = validate_nomina(data)
        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "nomina": data.to_dict() if data is not None else None,
        }

    @router.get(
        "/catalog",
        summary="Catálogo SAT de códigos de nómina.",
    )
    def nomina_catalog():
        """Retorna los catálogos SAT para código de periodicidad, tipo nómina,
        tipo de jornada y riesgo del puesto.
        """
        return {
            "periodicidad_pago": PERIODICIDAD_PAGO_CODES,
            "tipo_nomina": TIPO_NOMINA_CODES,
            "tipo_jornada": TIPO_JORNADA_CODES,
            "riesgo_puesto": RIESGO_PUESTO_CODES,
        }

    return router
