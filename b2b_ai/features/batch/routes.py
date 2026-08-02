# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de procesamiento batch de CFDIs.

Endpoints:
    POST /api/v1/cfdi/batch        Sube un ZIP/CSV y procesa múltiples CFDIs
                                   (asíncrono vía BackgroundTasks).
    GET  /api/v1/cfdi/batch/{id}   Consulta estado, progreso y reporte resumen.

Todos los endpoints exigen autenticación por API key (require_api_key).

Límites:
    - 500 CFDIs por batch
    - 10 MB máximo de subida (zip/csv)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from b2b_ai.features.batch.models import BatchItemStatus, BatchJob, BatchJobStatus
from b2b_ai.features.batch.service import (
    BatchLimitError,
    BatchService,
    MAX_UPLOAD_BYTES,
)

logger = logging.getLogger("b2b_ai.batch")


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""
    data: Optional[dict] = None


def build_batch_router(db: Any = None, require_api_key: Any = None) -> APIRouter:
    """Construye el router de batch CFDI (/api/v1/cfdi/batch)."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = BatchService()
    router = APIRouter(prefix="/api/v1/cfdi", tags=["CFDI", "batch"])

    @router.post("/batch", summary="Sube y procesa múltiples CFDIs en batch.",
                 response_model=None)
    async def upload_batch(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Recibe un ZIP de XML o un CSV y procesa todos los CFDIs.

        El procesamiento es asíncrono: el endpoint responde 202 con el
        ``batch_id``. El estado se consulta con GET /api/v1/cfdi/batch/{id}.
        """
        data = await file.read()
        size = len(data)
        if size == 0:
            raise HTTPException(status_code=400, detail="Archivo subido vacío.")
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"El archivo excede el límite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        filename = file.filename or "upload.zip"
        tenant_id = str(auth_info.get("tenant_id") or "") if auth_info else ""

        try:
            xmls = service.extract_xmls(data, filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            job = service.create_job(tenant_id, xmls)
        except BatchLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Procesamiento asíncrono (BackgroundTasks corre después de la respuesta).
        background_tasks.add_task(service.process_job, tenant_id, job.id)

        return {
            "ok": True,
            "message": "Batch creado. Procesamiento en curso.",
            "data": {
                "batch_id": job.id,
                "status": job.status.value,
                "total_items": job.total_items,
                "status_url": f"/api/v1/cfdi/batch/{job.id}",
            },
        }

    @router.get("/batch/{batch_id}", summary="Estado, progreso y resumen del batch.",
                response_model=None)
    def get_batch(batch_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        tenant_id = str(auth_info.get("tenant_id") or "") if auth_info else ""
        job = service.get_job(tenant_id, batch_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Batch no encontrado.")
        return {"ok": True, "batch": job.to_dict()}

    return router
