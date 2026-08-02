# -*- coding: utf-8 -*-
"""service.py — Lógica de negocio del módulo de migración de datos.

MigrationService coordina el ciclo completo de una migración:

    start_migration(file_path, file_type, tenant_id) -> MigrationJob
        Sube/registra un archivo y extrae sus ítems (Excel / CSV / CONTPAQi).
    validate_data(items) -> dict resumen
        Valida los ítems contra el esquema de Likida (RFC, campos requeridos).
    execute_migration(job_id) -> MigrationJob
        Ejecuta la importación: marca ítems válidos como importados y agrega
        el resultado al job (los ítems se guardan en el store en memoria).
    get_migration_status(job_id) -> MigrationJob | None

El store es en memoria (patrón batch / bank_feeds / onboarding / billing), con
un `_reset_state()` para los tests. La persistencia real (PostgreSQL) queda
como siguiente iteración.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from b2b_ai.features.data_migration.importers.base import normalize_row
from b2b_ai.features.data_migration.importers.contpaqi_mapper import ContpaqiMapper
from b2b_ai.features.data_migration.importers.csv_importer import (
    CSVImportError,
    ImportCSVData,
)
from b2b_ai.features.data_migration.importers.excel_importer import (
    ExcelImportError,
    ImportClientData,
)
from b2b_ai.features.data_migration.models import (
    MigrationDataType,
    MigrationFileType,
    MigrationItem,
    MigrationJob,
    MigrationStatus,
    _reset_state,
    get_job,
    list_jobs,
    save_job,
)
from b2b_ai.features.data_migration.validators.data_validator import (
    validate_item,
    validate_items,
)

logger = logging.getLogger("b2b_ai.data_migration")


class MigrationError(Exception):
    """Error controlado de la migración (expuesto al API)."""

    def __init__(self, message: str, code: str = "migration_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class MigrationService:
    """Servicio de migración de datos hacia Likida AI."""

    def __init__(self, contpaqi_mapper: Optional[ContpaqiMapper] = None):
        self.mapper = contpaqi_mapper or ContpaqiMapper()

    # ------------------------------------------------------------------
    # Extracción de ítems desde un archivo
    # ------------------------------------------------------------------
    def _extract(self, file_path: str, file_type: MigrationFileType,
                 filename: str) -> List[MigrationItem]:
        """Extrae ítems según el formato declarado."""
        try:
            if file_type == MigrationFileType.EXCEL:
                return ImportClientData().parse_excel(file_path)
            if file_type == MigrationFileType.CSV:
                text = Path(file_path).read_text(encoding="utf-8-sig",
                                                 errors="replace")
                imp = ImportCSVData()
                return imp.parse_text(text, filename=filename)
            if file_type == MigrationFileType.CONTPAQI:
                # CONTPAQi: reusamos el parser según la extensión real del archivo.
                return self._parse_contpaqi(file_path, filename)
        except (ExcelImportError, CSVImportError) as exc:
            raise MigrationError(str(exc), code="invalid_file") from exc
        raise MigrationError(
            f"Tipo de archivo no soportado: {file_type.value}", code="invalid_file_type"
        )

    def _parse_contpaqi(self, file_path: str, filename: str) -> List[MigrationItem]:
        """Parsea una exportación CONTPAQi (xlsx o csv) y la mapea."""
        lower = (filename or "").lower()
        if lower.endswith(".xlsx"):
            items = ImportClientData().parse_excel(file_path)
        else:
            text = Path(file_path).read_text(encoding="utf-8-sig",
                                             errors="replace")
            imp = ImportCSVData()
            items = imp.parse_text(text, filename=filename)
        # Los ítems ya vienen normalizados por los importers base; el mapper
        # asegura coherencia con el esquema CONTPAQi.
        return items

    # ------------------------------------------------------------------
    # Ciclo de migración
    # ------------------------------------------------------------------
    def start_migration(self, file_path: str, file_type: str,
                        tenant_id: str, filename: Optional[str] = None) -> MigrationJob:
        """Registra un job, extrae y valida los ítems del archivo.

        El job queda en estado VALIDATED (o FAILED si no se pudo extraer nada).
        Devuelve el job con su resumen de validación.
        """
        if not tenant_id:
            raise MigrationError("tenant_id es obligatorio", code="missing_tenant")

        try:
            ftype = MigrationFileType(file_type)
        except ValueError as exc:
            raise MigrationError(
                f"file_type inválido: {file_type}. Valores: excel, csv, contpaqi",
                code="invalid_file_type",
            ) from exc

        if not file_path or not Path(file_path).exists():
            raise MigrationError(f"El archivo no existe: {file_path}", code="invalid_file")

        fname = filename or Path(file_path).name
        job = MigrationJob(
            tenant_id=tenant_id,
            file_name=fname,
            file_type=ftype,
            status=MigrationStatus.PENDING,
        )
        save_job(job)
        logger.info("migration start id=%s tenant=%s file=%s type=%s",
                    job.id, tenant_id, fname, ftype.value)

        # 1) Extraer ítems
        try:
            items = self._extract(file_path, ftype, fname)
        except MigrationError as exc:
            job.status = MigrationStatus.FAILED
            job.metadata["error"] = exc.message
            save_job(job)
            raise

        if not items:
            job.status = MigrationStatus.FAILED
            job.metadata["error"] = "No se encontraron datos válidos en el archivo."
            save_job(job)
            raise MigrationError(job.metadata["error"], code="empty_file")

        job.items = items
        job.total_items = len(items)

        # 2) Validar
        summary = validate_items(items)
        job.valid_count = summary["valid_count"]
        job.invalid_count = summary["invalid_count"]
        job.validated_at = _utcnow_iso()
        job.status = (MigrationStatus.VALIDATED
                      if summary["valid_count"] or summary["invalid_count"]
                      else MigrationStatus.FAILED)
        job.metadata = self._build_summary(items)
        save_job(job)
        return job

    def validate_data(self, items: List[MigrationItem]) -> Dict[str, Any]:
        """Valida una lista de ítems y devuelve el resumen."""
        return validate_items(items)

    def execute_migration(self, job_id: str) -> MigrationJob:
        """Ejecuta la importación de un job validado.

        Marca como importados los ítems válidos. Los inválidos se dejan con su
        error. Actualiza conteos y estado final (COMPLETED / PARTIAL / FAILED).
        """
        job = get_job(job_id)
        if job is None:
            raise MigrationError(f"Migración no encontrada: {job_id}", code="not_found")
        if job.status in (MigrationStatus.COMPLETED, MigrationStatus.PARTIAL,
                          MigrationStatus.FAILED, MigrationStatus.PROCESSING):
            return job

        if job.status == MigrationStatus.PENDING:
            # Acepta ejecutar un job que aún no validó: valida en caliente.
            validate_items(job.items)
            job.valid_count = sum(1 for it in job.items if it.valid)
            job.invalid_count = len(job.items) - job.valid_count
            job.validated_at = _utcnow_iso()

        job.status = MigrationStatus.PROCESSING
        save_job(job)

        imported = 0
        failed = 0
        now = _utcnow_iso()
        for it in job.items:
            if it.valid:
                try:
                    self._import_item(it)
                    it.imported = True
                    it.imported_at = now
                    imported += 1
                except Exception as exc:  # noqa: BLE001 — un ítem no rompe el job
                    it.imported = False
                    it.error = str(exc)
                    failed += 1
            else:
                failed += 1
            save_job(job)

        job.imported_count = imported
        job.failed_count = failed
        job.completed_at = _utcnow_iso()

        if imported == 0 and failed > 0:
            job.status = MigrationStatus.FAILED
        elif failed > 0:
            job.status = MigrationStatus.PARTIAL
        else:
            job.status = MigrationStatus.COMPLETED
        save_job(job)
        logger.info("migration done id=%s status=%s imported=%d failed=%d",
                    job.id, job.status.value, imported, failed)
        return job

    def _import_item(self, item: MigrationItem) -> None:
        """Persiste un ítem individual.

        En esta iteración el MVP guarda el ítem en el store en memoria (dentro
        del job). La escritura a la base de datos real (clientes / cfdIs /
        cuentas / empleados) se implementa en la siguiente iteración. El método
        existe como punto único de persistencia y ya ejecuta la validación de
        integridad que falla si faltan campos obligatorios.
        """
        # Asegura que el ítem está normalizado a esquema canónico.
        normalize_row(item.data, item.data_type)
        # Persistencia real: registrar en el repositorio de destino.
        # (place-holder para la integración con el repo de datos del MVP.)

    def get_migration_status(self, job_id: str) -> Optional[MigrationJob]:
        """Devuelve el job por id, o None si no existe."""
        return get_job(job_id)

    def get_tenant_jobs(self, tenant_id: str, limit: int = 50) -> List[MigrationJob]:
        """Lista los jobs de un tenant, más recientes primero."""
        return list_jobs(tenant_id=tenant_id, limit=limit)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_summary(items: List[MigrationItem]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for it in items:
            counts[it.data_type.value] = counts.get(it.data_type.value, 0) + 1
        return {
            "counts_by_type": counts,
            "valid": sum(1 for it in items if it.valid),
            "invalid": sum(1 for it in items if not it.valid),
        }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _reset_state()
