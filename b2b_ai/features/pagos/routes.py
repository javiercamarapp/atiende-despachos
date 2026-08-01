# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Complemento de Pagos.

Endpoints:
    POST /pagos/parse     — Sube XML CFDI 4.0, retorna datos Pagos 1.1.
    POST /pagos/validate  — Sube XML CFDI 4.0, retorna errores de validación.
    GET  /pagos/catalog   — Catálogo SAT de códigos de pagos.

El router se construye con `build_pagos_router()` para inyectar DB y
dependencias de auth en tests.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from b2b_ai.features.pagos.parser import parse_pagos, parse_pagos_bytes
from b2b_ai.features.pagos.validators import (
    validate_pagos,
    FORMA_PAGO_CODES,
    TIPO_CADENA_PAGO_CODES,
    MONEDAS_ISO_4217,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PagosCatalog(BaseModel):
    """Catálogo SAT de códigos de pagos."""
    forma_pago: dict
    tipo_cadena_pago: dict
    monedas_iso: dict


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_pagos_router() -> APIRouter:
    """Devuelve un APIRouter con endpoints /pagos/*.

    Sigue el patrón `build_*_router()` del proyecto para inyección de DB.
    Los endpoints de pagos no requieren auth por ser parsing/validación
    local (sin persistencia).
    """
    router = APIRouter(prefix="/pagos", tags=["pagos"])

    @router.post(
        "/parse",
        summary="Parsea complemento Pagos 1.1 de un CFDI XML.",
        response_model=None,
    )
    async def parse_pagos_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y extrae el complemento Pagos 1.1.

        Retorna los campos de pagos como JSON o 404 si no hay complemento.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_pagos_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="El XML no contiene complemento de Pagos 1.1.",
            )

        return {"ok": True, "pagos": data.to_dict()}

    @router.post(
        "/validate",
        summary="Valida un CFDI con complemento Pagos 1.1 contra reglas SAT.",
        response_model=None,
    )
    async def validate_pagos_endpoint(file: UploadFile = File(...)):
        """Recibe un archivo CFDI 4.0 (XML) y valida su complemento de Pagos.

        Retorna errores de validación (lista vacía = válido).
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")

        try:
            data = parse_pagos_bytes(content)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error al parsear XML: {type(e).__name__}: {e}",
            )

        errors = validate_pagos(data)
        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "pagos": data.to_dict() if data is not None else None,
        }

    @router.get(
        "/catalog",
        summary="Catálogo SAT de códigos de pagos.",
    )
    def pagos_catalog():
        """Retorna los catálogos SAT para forma de pago, tipo de cadena
        de pago y monedas ISO 4217.
        """
        return {
            "forma_pago": FORMA_PAGO_CODES,
            "tipo_cadena_pago": TIPO_CADENA_PAGO_CODES,
            "monedas_iso": MONEDAS_ISO_4217,
        }

    return router
