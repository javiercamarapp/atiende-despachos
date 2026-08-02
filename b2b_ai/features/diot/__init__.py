# -*- coding: utf-8 -*-
"""
Módulo DIOT (Declaración Informativa de Operaciones con Terceros).

Cumplimiento fiscal mexicano (CFF Art. 32-H / Resolución Miscelánea).
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
from b2b_ai.features.diot.service import (
    DiotService,
    generate_diot,
    validate_diot_data,
    detect_inconsistencies,
    export_diot_xml,
    get_report,
    list_reports,
)
from b2b_ai.features.diot.validators import (
    ValidationResult,
    validate_rfc,
    validate_iva_rate,
    validate_iva_amount,
    validate_diot_entries,
    validate_all_rfcs,
    validate_all_iva,
)
from b2b_ai.features.diot.routes import build_diot_router

__all__ = [
    "TipoOperacion", "OperacionType", "TipoIva", "EstatusDIOT",
    "CFDIInvoiceInput", "DiotEntry", "DiotSummary", "DiotReport", "Inconsistencia",
    "DiotService", "generate_diot", "validate_diot_data", "detect_inconsistencies",
    "export_diot_xml", "get_report", "list_reports",
    "ValidationResult", "validate_rfc", "validate_iva_rate", "validate_iva_amount",
    "validate_diot_entries", "validate_all_rfcs", "validate_all_iva",
    "build_diot_router",
]
