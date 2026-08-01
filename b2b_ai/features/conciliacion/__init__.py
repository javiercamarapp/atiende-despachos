# -*- coding: utf-8 -*-
"""
Módulo Conciliación Bancaria: cruza estados de cuenta bancarios con pólizas
contables y CFDI para encontrar coincidencias, detectar discrepancias,
proponer ajustes y generar reportes.

Expone:
  - TransactionType, MatchStatus, MatchType, DiscrepancyType, AdjustmentStatus — enums
  - BankTransaction, CFDIReference, PolizaContable, MatchResult — core schemas
  - Discrepancy, Adjustment — reconciliation schemas
  - ConciliationReport — report schema
  - ConciliationService — lógica de matching, discrepancias, ajustes y reportes
  - validate_bank_statement, validate_cfdi_for_conciliation, validate_polizas_contables — validators
  - validate_amount_match, validate_date_range, validate_reconciliation_data — validators
  - build_conciliacion_router() — FastAPI router (/api/v1/conciliacion/*)
"""
from b2b_ai.features.conciliacion.models import (
    Adjustment,
    AdjustmentStatus,
    BankTransaction,
    CFDIReference,
    ConciliationReport,
    Discrepancy,
    DiscrepancyType,
    MatchResult,
    MatchStatus,
    MatchType,
    PolizaContable,
    TransactionType,
)
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.validators import (
    validate_amount_match,
    validate_bank_statement,
    validate_cfdi_for_conciliation,
    validate_date_range,
    validate_polizas_contables,
    validate_reconciliation_data,
)
from b2b_ai.features.conciliacion.routes import build_conciliacion_router

__all__ = [
    # Enums
    "TransactionType",
    "MatchStatus",
    "MatchType",
    "DiscrepancyType",
    "AdjustmentStatus",
    # Core schemas
    "BankTransaction",
    "CFDIReference",
    "PolizaContable",
    "MatchResult",
    # Reconciliation schemas
    "Discrepancy",
    "Adjustment",
    "ConciliationReport",
    # Service
    "ConciliationService",
    # Validators
    "validate_bank_statement",
    "validate_cfdi_for_conciliation",
    "validate_polizas_contables",
    "validate_amount_match",
    "validate_date_range",
    "validate_reconciliation_data",
    # Router
    "build_conciliacion_router",
]
