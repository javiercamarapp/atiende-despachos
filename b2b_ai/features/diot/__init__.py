# -*- coding: utf-8 -*-
"""
Módulo DIOT (Declaración Informativa de Operaciones con Terceros).

Genera la DIOT a partir de facturas CFDI, detecta inconsistencias y
exporta a formato XML para su envío al SAT.

Expone:
  - OperacionType, EstatusDIOT — enums
  - DiotEntry, DiotSummary, DiotReport — core schemas
  - DiotService — lógica de generación, validación, inconsistencias, exportación
  - validate_rfc, validate_iva_rate, validate_diot_entries — validators
  - build_diot_router() — FastAPI router (/api/v1/diot/*)
"""
from b2b_ai.features.diot.models import (
    DiotEntry,
    DiotReport,
    DiotSummary,
    EstatusDIOT,
    OperacionType,
)
from b2b_ai.features.diot.service import DiotService
from b2b_ai.features.diot.validators import (
    validate_diot_entries,
    validate_iva_rate,
    validate_rfc,
)
from b2b_ai.features.diot.routes import build_diot_router

__all__ = [
    # Enums
    "OperacionType",
    "EstatusDIOT",
    # Schemas
    "DiotEntry",
    "DiotSummary",
    "DiotReport",
    # Service
    "DiotService",
    # Validators
    "validate_rfc",
    "validate_iva_rate",
    "validate_diot_entries",
    # Router
    "build_diot_router",
]
