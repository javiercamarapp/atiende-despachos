# -*- coding: utf-8 -*-
"""Declaraciones Periódicas — IVA, ISR Provisional, ISR Anual, DIOT, IEPS.

Módulo para el cálculo, generación XML, firma FIEL/CSD y envío de
declaraciones fiscales al SAT.

Submódulos:
  - engine: Unified tax calculation (ISR tables, IVA, IEPS, DIOT aggregation)
  - diot_generator: Pipe-delimited DIOT export (RMF 3.10.7)
  - xml_generator: SAT-compliant XML generation
  - fiel_signer: RSA-SHA256 digital signing with FIEL/CSD
  - sat_submitter: SOAP submission to SAT web services
  - error_handler: 14 SAT-specific error codes with retry logic
  - declaration_api: FastAPI endpoints (/calculate, /generate, /submit, /status)

Reglas fiscales:
  - IVA: Mensual, vence el 17 del mes siguiente (LIVA Art. 5)
  - ISR Provisional: Mensual, vence el 17 del mes siguiente (LISR Art. 14/116)
  - ISR Anual: Anual, vence el 30 de abril del año siguiente
  - IEPS: Según Ley IEPS Art. 2
  - DIOT: Informativa mensual, RMF 3.10.7
"""
from b2b_ai.features.declaraciones.service import DeclaracionesService
from b2b_ai.features.declaraciones.models import (
    Declaracion,
    DeclaracionStatus,
    DeclaracionType,
    Deadline,
    DeadlineStatus,
    IvaData,
    IsrData,
)
from b2b_ai.features.declaraciones.engine import (
    DeclarationEngine,
    calculate_isr_pm,
    calculate_isr_pf,
    calculate_iva,
    calculate_ieps,
    aggregate_diot,
    ISR_TABLE_MONTHLY,
    ISR_TABLE_ANNUAL,
)
from b2b_ai.features.declaraciones.diot_generator import DIOTGenerator
from b2b_ai.features.declaraciones.xml_generator import XMLGenerator
from b2b_ai.features.declaraciones.fiel_signer import FIELSigner
from b2b_ai.features.declaraciones.sat_submitter import SATSubmitter
from b2b_ai.features.declaraciones.error_handler import SATErrorHandler

__all__ = [
    # Legacy
    "DeclaracionesService",
    "Declaracion",
    "DeclaracionStatus",
    "DeclaracionType",
    "Deadline",
    "DeadlineStatus",
    "IvaData",
    "IsrData",
    # Engine
    "DeclarationEngine",
    "calculate_isr_pm",
    "calculate_isr_pf",
    "calculate_iva",
    "calculate_ieps",
    "aggregate_diot",
    "ISR_TABLE_MONTHLY",
    "ISR_TABLE_ANNUAL",
    # Generators
    "DIOTGenerator",
    "XMLGenerator",
    # Signing & Submission
    "FIELSigner",
    "SATSubmitter",
    "SATErrorHandler",
]
