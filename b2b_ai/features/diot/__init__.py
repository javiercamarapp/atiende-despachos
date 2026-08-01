# -*- coding: utf-8 -*-
"""
Módulo DIOT (Declaración Informativa de Operaciones con Terceros).

Genera la DIOT a partir de facturas CFDI, detecta inconsistencias y
exporta a formato XML para su envío al SAT.

Expone:
  - OperacionType, TipoIva, EstatusDIOT — enums
  - CFDIInvoiceInput, DiotEntry, DiotSummary, DiotReport — core schemas
  - Inconsistencia — inconsistency tracking
  - DiotService — lógica de generación, validación, inconsistencias, exportación
  - validate_rfc, validate_iva_rate, validate_diot_entries — validators
  - build_diot_router() — FastAPI router (/api/v1/diot/*)
"""
from b2b_ai.features.diot.models import (
    CFDIInvoiceInput,
    DiotEntry,
    DiotReport,
    DiotSummary,
    EstatusDIOT,
    Inconsistencia,
    OperacionType,
    TipoIva,
    TipoOperacion,
)
from b2b_ai.features.diot.service import DiotService
from b2b_ai.features.diot.validators import (
    ValidationResult,
    detect_duplicate_uuids,
    validate_all_iva,
    validate_all_rfcs,
    validate_cfdi_cross_reference,
    validate_diot_entries,
    validate_iva_calculation,
    validate_iva_rate,
    validate_invoices,
    validate_rfc,
)
from b2b_ai.features.diot.routes import build_diot_router

__all__ = [
    # Enums
    "OperacionType",
    "TipoIva",
    "TipoOperacion",
    "EstatusDIOT",
    # Schemas
    "CFDIInvoiceInput",
    "DiotEntry",
    "DiotSummary",
    "DiotReport",
    "Inconsistencia",
    # Service
    "DiotService",
    # Validators
    "ValidationResult",
    "detect_duplicate_uuids",
    "validate_all_iva",
    "validate_all_rfcs",
    "validate_cfdi_cross_reference",
    "validate_rfc",
    "validate_iva_rate",
    "validate_iva_calculation",
    "validate_diot_entries",
    "validate_invoices",
    # Router
    "build_diot_router",
]
