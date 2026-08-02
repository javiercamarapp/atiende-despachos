# -*- coding: utf-8 -*-
"""
Módulo Vencimientos: gestión de plazos fiscales con escalamiento automático.

Expone:
  - PrioridadVencimiento, EstadoVencimiento, NivelEscalamiento — enums
  - Deadline, Escalation, VencimientoSummary — schemas
  - VencimientosService — lógica de cálculo, vencimiento, escalamiento
  - validate_date, validate_priority, validate_date_range_venc — validators
  - build_vencimientos_router() — FastAPI router (/api/v1/vencimientos/*)
"""
from b2b_ai.features.vencimientos.models import (
    Deadline,
    Escalation,
    EstadoVencimiento,
    NivelEscalamiento,
    PrioridadVencimiento,
    VencimientoSummary,
)
from b2b_ai.features.vencimientos.service import VencimientosService
from b2b_ai.features.vencimientos.validators import (
    validate_date,
    validate_date_range_venc,
    validate_priority,
)
from b2b_ai.features.vencimientos.routes import build_vencimientos_router

__all__ = [
    # Enums
    "PrioridadVencimiento",
    "EstadoVencimiento",
    "NivelEscalamiento",
    # Schemas
    "Deadline",
    "Escalation",
    "VencimientoSummary",
    # Service
    "VencimientosService",
    # Validators
    "validate_date",
    "validate_priority",
    "validate_date_range_venc",
    # Router
    "build_vencimientos_router",
]
