# -*- coding: utf-8 -*-
"""routes.py — Endpoints REST del módulo de migración de datos.

Endpoints (todos exigen autenticación por API key):

    POST /api/v1/migration/upload            — sube un archivo (multipart) y crea
                                               el job con sus ítems validados.
    POST /api/v1/migration/{job_id}/execute  — ejecuta la importación del job.
    GET  /api/v1/migration/{job_id}/status   — estado actual del job.
    GET  /api/v1/migration/{job_id}/errors   — errores de validación del job.
    GET  /api/v1/migration                    — lista jobs del tenant (opcional).

Sigue el patrón `build_*_router(db, require_api_key)` del proyecto. El prefijo
`/api/v1/migration` no colisiona con ningún módulo existente.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from b2b_ai.features.data_migration.models import (
    MigrationFileType,
    MigrationJob,
    MigrationStatus,
    get_job,
)
from b2b_ai.features.data_migration.service import MigrationError, MigrationService

ROUTER_PREFIX = "/api/v1/migration"

# Límite de subida (10 MB, coherente con el módulo batch).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = (".xlsx", ".xls", ".csv")


class _ApiException(Exception):
    """Excepción interna que se traduce a HTTP con su código."""


def build_data_migration_router(db: Any = None,
                                require_api_key: Any = None) -> APIRouter:
    """Construye el router /api/v1/migration/* de migración de datos."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = MigrationService()
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["data-migration"])

    @router.post(
        "/upload",
        summary="Sube un archivo y crea un trabajo de migración.",
    )
    async def upload_migration(
        file: UploadFile = File(...),
        file_type: str = Query("auto", description="excel | csv | contpaqi | auto"),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Recibe un .xlsx/.xls/.csv y crea un MigrationJob validado."""
        tenant_id = auth_info.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Se requiere tenant_id")

        data = await file.read()
        size = len(data)
        if size == 0:
            raise HTTPException(status_code=400, detail="Archivo subido vacío.")
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"El archivo excede el límite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        filename = file.filename or "upload"
        lower = filename.lower()
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="Extensión no permitida. Sube un .xlsx, .xls o .csv.",
            )

        # Guardar en un temporal del servidor para que el servicio lo parsee.
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            resolved_type = _resolve_file_type(file_type, lower, ext)
            job = service.start_migration(
                file_path=tmp_path,
                file_type=resolved_type,
                tenant_id=tenant_id,
                filename=filename,
            )
        except MigrationError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

        return {
            "ok": True,
            "message": "Migración creada y datos validados.",
            "data": {
                "job_id": job.id,
                "status": job.status.value,
                "total_items": job.total_items,
                "valid_count": job.valid_count,
                "invalid_count": job.invalid_count,
                "status_url": f"{ROUTER_PREFIX}/{job.id}/status",
            },
        }

    @router.post(
        "/{job_id}/execute",
        summary="Ejecuta la importación de un job de migración.",
    )
    def execute_migration(job_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        """Importa los ítems válidos del job y reporta resultados."""
        _get_owned_or_404(job_id, auth_info)
        try:
            job = service.execute_migration(job_id)
        except MigrationError as exc:
            raise HTTPException(status_code=404, detail=exc.message) from exc
        return {
            "ok": True,
            "message": "Migración ejecutada.",
            "data": {
                "job_id": job.id,
                "status": job.status.value,
                "imported_count": job.imported_count,
                "failed_count": job.failed_count,
                "total_items": job.total_items,
            },
        }

    @router.get(
        "/{job_id}/status",
        summary="Estado actual de un job de migración.",
    )
    def migration_status(job_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        """Devuelve el estado y resumen del job."""
        job = _get_owned_or_404(job_id, auth_info)
        return {"ok": True, "job": job.to_dict()}

    @router.get(
        "/{job_id}/errors",
        summary="Errores de validación de un job de migración.",
    )
    def migration_errors(job_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        """Devuelve la lista de ítems inválidos con sus errores."""
        job = _get_owned_or_404(job_id, auth_info)
        return {"ok": True, "errors": job.errors}

    @router.get(
        "",
        summary="Lista los jobs de migración del tenant.",
    )
    def list_migrations(
        limit: int = Query(50, ge=1, le=200),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        """Lista los jobs del tenant autenticado, más recientes primero."""
        tenant_id = auth_info.get("tenant_id")
        jobs = service.get_tenant_jobs(tenant_id or "", limit=limit)
        return {"ok": True, "migrations": [j.to_dict() for j in jobs]}

    def _get_owned_or_404(job_id: str, auth_info: dict) -> MigrationJob:
        """Obtiene un job validando que pertenece al tenant autenticado.

        Anti-IDOR multi-tenant: si el job existe pero es de otro tenant se
        devuelve 404 (mismo error que un job inexistente, para no filtrar la
        existencia de recursos ajenos), nunca 403.
        """
        job = get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Migración no encontrada.")
        tenant_id = auth_info.get("tenant_id")
        if not tenant_id or job.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Migración no encontrada.")
        return job

    return router


def _resolve_file_type(file_type: str, lower_filename: str, ext: str) -> str:
    """Resuelve el tipo de archivo declarado, con 'auto' por extensión."""
    ft = (file_type or "auto").strip().lower()
    if ft != "auto":
        try:
            MigrationFileType(ft)
            return ft
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"file_type inválido: {file_type}. Valores: excel, csv, contpaqi, auto.",
            ) from exc
    if lower_filename.endswith(".xlsx") or lower_filename.endswith(".xls"):
        return "excel"
    if lower_filename.endswith(".csv"):
        return "csv"
    raise HTTPException(status_code=400, detail="No se pudo inferir el tipo de archivo.")
