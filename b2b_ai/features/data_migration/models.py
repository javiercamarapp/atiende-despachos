# -*- coding: utf-8 -*-
"""models.py — Entidades de dominio del módulo de migración de datos.

Define las entidades centrales del subsistema de importación de datos desde
sistemas existentes (CONTPAQi, Excel, CSV) al MVP de Likida AI:

    MigrationJob   — un trabajo de migración (archivo subido por un tenant).
    MigrationItem  — una pieza de datos extraída del archivo (cliente, CFDI,
                     cuenta bancaria o empleado) lista para validar/importar.
    MigrationStatus— ciclo de vida del job.
    MigrationDataType — tipo de datos de cada ítem.

Sigue el patrón del proyecto (pydantic v2, Field con description, enums y
timestamps ISO UTC) usado por `batch`, `bank_feeds`, `onboarding`, `billing`.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MigrationStatus(str, Enum):
    """Ciclo de vida de un trabajo de migración."""
    PENDING = "pending"                # creado, archivo subido, aún no validado
    VALIDATING = "validating"          # validando los ítems extraídos
    VALIDATED = "validated"            # validación terminada (puede tener errores)
    PROCESSING = "processing"          # ejecutando la importación
    COMPLETED = "completed"            # importación terminada con éxito
    PARTIAL = "partial"                # terminada con errores parciales (algunos ítems fallaron)
    FAILED = "failed"                  # no se pudo importar nada / fallo fatal


class MigrationDataType(str, Enum):
    """Tipo de datos que migra un ítem."""
    CLIENTE = "cliente"
    CFDI = "cfdi"
    CUENTA_BANCARIA = "cuenta_bancaria"
    EMPLEADO = "empleado"


class MigrationFileType(str, Enum):
    """Formato del archivo de origen."""
    EXCEL = "excel"
    CSV = "csv"
    CONTPAQI = "contpaqi"


# ---------------------------------------------------------------------------
# Helpers de tiempo
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


# ---------------------------------------------------------------------------
# Entidades
# ---------------------------------------------------------------------------

class MigrationItem(BaseModel):
    """Una pieza de datos a migrar, extraída del archivo de origen."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno del ítem")
    data_type: MigrationDataType = Field(..., description="Tipo de datos")
    source: str = Field("", description="Origen (nombre de hoja o archivo)")
    row: int = Field(0, description="Número de fila de origen (1-based)")
    data: Dict[str, Any] = Field(default_factory=dict,
                                 description="Datos crudos normalizados")
    valid: bool = Field(default=False, description="Si pasó la validación")
    errors: List[str] = Field(default_factory=list,
                              description="Errores de validación de este ítem")
    imported: bool = Field(default=False,
                           description="Si el ítem ya se importó (execute)")
    imported_at: Optional[str] = Field(default=None,
                                       description="Fecha de importación ISO UTC")
    error: Optional[str] = Field(default=None,
                                 description="Error de importación en execute")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "data_type": self.data_type.value,
            "source": self.source,
            "row": self.row,
            "data": self.data,
            "valid": self.valid,
            "errors": self.errors,
            "imported": self.imported,
            "imported_at": self.imported_at,
            "error": self.error,
        }


class MigrationJob(BaseModel):
    """Trabajo de migración de un archivo para un tenant."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno del job")
    tenant_id: str = Field(..., description="Tenant dueño del job")
    file_name: str = Field(..., description="Nombre del archivo subido")
    file_type: MigrationFileType = Field(..., description="Formato del archivo")
    status: MigrationStatus = Field(default=MigrationStatus.PENDING,
                                    description="Estado del job")
    items: List[MigrationItem] = Field(default_factory=list,
                                       description="Ítems extraídos del archivo")
    total_items: int = Field(0, description="Total de ítems")
    valid_count: int = Field(0, description="Ítems válidos")
    invalid_count: int = Field(0, description="Ítems inválidos")
    imported_count: int = Field(0, description="Ítems importados con éxito")
    failed_count: int = Field(0, description="Ítems fallidos en importación")
    created_at: str = Field(default_factory=_utcnow_iso,
                            description="Fecha de creación ISO UTC")
    validated_at: Optional[str] = Field(default=None,
                                        description="Fin de validación ISO UTC")
    completed_at: Optional[str] = Field(default=None,
                                        description="Fin de ejecución ISO UTC")
    metadata: Dict[str, Any] = Field(default_factory=dict,
                                     description="Metadatos extra (resumen, conteos por tipo)")

    @property
    def errors(self) -> List[Dict[str, Any]]:
        """Errores agregados de todos los ítems inválidos."""
        out: List[Dict[str, Any]] = []
        for item in self.items:
            if item.errors:
                out.append({
                    "item_id": item.id,
                    "data_type": item.data_type.value,
                    "source": item.source,
                    "row": item.row,
                    "errors": item.errors,
                })
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "file_name": self.file_name,
            "file_type": self.file_type.value,
            "status": self.status.value,
            "total_items": self.total_items,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "imported_count": self.imported_count,
            "failed_count": self.failed_count,
            "created_at": self.created_at,
            "validated_at": self.validated_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Store en memoria (patrón batch / bank_feeds / onboarding)
# ---------------------------------------------------------------------------

# job_id -> MigrationJob
_jobs: Dict[str, MigrationJob] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _jobs.clear()


def save_job(job: MigrationJob) -> MigrationJob:
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Optional[MigrationJob]:
    return _jobs.get(job_id)


def list_jobs(tenant_id: Optional[str] = None, limit: int = 50) -> List[MigrationJob]:
    all_jobs = list(_jobs.values())
    if tenant_id is not None:
        all_jobs = [j for j in all_jobs if j.tenant_id == tenant_id]
    all_jobs.sort(key=lambda j: j.created_at, reverse=True)
    return all_jobs[:limit]
