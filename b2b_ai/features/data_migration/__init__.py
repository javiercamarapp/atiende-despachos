# -*- coding: utf-8 -*-
"""data_migration — Módulo de migración de datos hacia Likida AI.

Importa información de sistemas existentes (CONTPAQi, Excel, CSV) al MVP de
Likida AI. El primer piloto importa los datos del despacho actual.

Expone:
  - MigrationStatus, MigrationDataType, MigrationFileType, MigrationJob,
    MigrationItem — entidades y enums de dominio
  - ImportClientData (Excel), ImportCSVData (CSV), ContpaqiMapper (CONTPAQi) —
    importadores que normalizan a esquema canónico
  - is_valid_mx_rfc, validate_items — validación de RFC e integridad de datos
  - MigrationService — lógica de negocio (start/validate/execute/status)
  - build_data_migration_router() — router FastAPI /api/v1/migration/*
"""
from __future__ import annotations

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
from b2b_ai.features.data_migration.importers import (
    CSVImportError,
    ContpaqiMapper,
    ExcelImportError,
    ImportCSVData,
    ImportClientData,
    detect_sheet_type,
    normalize_row,
)
from b2b_ai.features.data_migration.validators import (
    describe_rfc_error,
    is_valid_mx_rfc,
    normalize_rfc,
    validate_item,
    validate_items,
)
from b2b_ai.features.data_migration.service import (
    MigrationError,
    MigrationService,
    reset_state,
)
from b2b_ai.features.data_migration.routes import build_data_migration_router

__all__ = [
    "MigrationStatus",
    "MigrationDataType",
    "MigrationFileType",
    "MigrationJob",
    "MigrationItem",
    "get_job",
    "list_jobs",
    "save_job",
    "CSVImportError",
    "ContpaqiMapper",
    "ExcelImportError",
    "ImportCSVData",
    "ImportClientData",
    "detect_sheet_type",
    "normalize_row",
    "describe_rfc_error",
    "is_valid_mx_rfc",
    "normalize_rfc",
    "validate_item",
    "validate_items",
    "MigrationError",
    "MigrationService",
    "reset_state",
    "build_data_migration_router",
    "_reset_state",
]
