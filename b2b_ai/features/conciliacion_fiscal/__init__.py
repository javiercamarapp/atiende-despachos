# -*- coding: utf-8 -*-
"""
Módulo Conciliación Fiscal: cruza registros ERP con declaraciones SAT
para detectar omisiones, discrepancias y generar reportes fiscales.

Expone:
  - TipoOmicion, TipoDiscrepancia — enums
  - FiscalComparison, Omission, FiscalDiscrepancy, FiscalReport — schemas
  - FiscalConciliationService — lógica de comparación y reportes
  - validate_fiscal_period, validate_fiscal_amounts, cross_reference_data — validators
  - build_fiscal_router() — FastAPI router (/api/v1/fiscal/*)
"""
from b2b_ai.features.conciliacion_fiscal.models import (
    FiscalComparison,
    FiscalDiscrepancy,
    FiscalReport,
    Omission,
    TipoDiscrepancia,
    TipoOmicion,
)
from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
from b2b_ai.features.conciliacion_fiscal.validators import (
    cross_reference_data,
    validate_fiscal_amounts,
    validate_fiscal_period,
)
from b2b_ai.features.conciliacion_fiscal.routes import build_fiscal_router

__all__ = [
    # Enums
    "TipoOmicion",
    "TipoDiscrepancia",
    # Schemas
    "FiscalComparison",
    "Omission",
    "FiscalDiscrepancy",
    "FiscalReport",
    # Service
    "FiscalConciliationService",
    # Validators
    "validate_fiscal_period",
    "validate_fiscal_amounts",
    "cross_reference_data",
    # Router
    "build_fiscal_router",
]
