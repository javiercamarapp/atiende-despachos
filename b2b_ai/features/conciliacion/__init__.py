# -*- coding: utf-8 -*-
"""
Módulo Conciliación Bancaria: cruza estados de cuenta bancarios con CFDI
para encontrar coincidencias, detectar discrepancias y generar reportes.

Expone:
  - TransactionType, MatchStatus, MatchType — enums
  - BankTransaction, CFDIReference, MatchResult, ConciliationReport — schemas
  - ConciliationService — lógica de matching y reportes
  - validate_bank_statement, validate_cfdi_for_conciliation — validators
  - build_conciliacion_router() — FastAPI router (/api/v1/conciliacion/*)
"""
from b2b_ai.features.conciliacion.models import (
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    MatchResult,
    MatchStatus,
    MatchType,
    TransactionType,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_bank_statement,
    validate_cfdi_for_conciliation,
)
from b2b_ai.features.conciliacion.routes import build_conciliacion_router

__all__ = [
    "TransactionType",
    "MatchStatus",
    "MatchType",
    "BankTransaction",
    "CFDIReference",
    "MatchResult",
    "ConciliationReport",
    "ConciliationService",
    "validate_bank_statement",
    "validate_cfdi_for_conciliation",
    "build_conciliacion_router",
]
