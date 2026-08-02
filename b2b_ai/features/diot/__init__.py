# -*- coding: utf-8 -*-
"""
Módulo DIOT (Declaración Informativa de Operaciones con Terceros).

Cumplimiento fiscal mexicano (CFF Art. 32-H / Resolución Miscelánea).
"""
from b2b_ai.features.diot.models import (
    DIOTDeclaration, DIOTPeriod, DIOTRecord, DIOTStatus, DIOTSummary, TipoIVA, TipoOperacion,
)
from b2b_ai.features.diot.service import DIOTService
from b2b_ai.features.diot.validators import (
    ValidationResult, is_valid_rfc, validate_iva_rate, validate_positive_amount,
    validate_rfc, validate_records,
)
from b2b_ai.features.diot.routes import build_diot_router
from b2b_ai.features.diot.automation import (
    DIOTAutomation,
    DIOTAutomationError,
    DIOTAutomationResult,
    MissingProvider,
    ProviderClassification,
    ingest_cfdi,
    register_provider,
    _reset_state as _automation_reset_state,
)

__all__ = [
    "TipoOperacion", "TipoIVA", "DIOTStatus",
    "DIOTPeriod", "DIOTRecord", "DIOTSummary", "DIOTDeclaration",
    "DIOTService",
    "ValidationResult", "validate_rfc", "is_valid_rfc", "validate_iva_rate",
    "validate_positive_amount", "validate_records",
    "build_diot_router",
    "DIOTAutomation", "DIOTAutomationError", "DIOTAutomationResult",
    "MissingProvider", "ProviderClassification",
    "ingest_cfdi", "register_provider", "_automation_reset_state",
]
