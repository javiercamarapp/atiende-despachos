# -*- coding: utf-8 -*-
"""
Módulo Email Processing: monitoreo de bandeja de entrada y extracción de facturas.

Expone:
  - AttachmentType, ProcessingStatus — enums
  - EmailMessage, ExtractedInvoice, ProcessingResult — core schemas
  - EmailProcessingService — lógica de escaneo, extracción, procesamiento
  - validate_email_address, validate_attachment_type, validate_cfdi_xml — validators
  - build_email_processing_router — FastAPI router (/api/v1/email/*)
"""
from b2b_ai.features.email_processing.models import (
    AttachmentType,
    EmailMessage,
    ExtractedInvoice,
    ProcessingResult,
    ProcessingStatus,
)
from b2b_ai.features.email_processing.service import EmailProcessingService
from b2b_ai.features.email_processing.validators import (
    validate_attachment_type,
    validate_cfdi_xml,
    validate_email_address,
)
from b2b_ai.features.email_processing.routes import build_email_processing_router

__all__ = [
    # Enums
    "AttachmentType",
    "ProcessingStatus",
    # Schemas
    "EmailMessage",
    "ExtractedInvoice",
    "ProcessingResult",
    # Service
    "EmailProcessingService",
    # Validators
    "validate_email_address",
    "validate_attachment_type",
    "validate_cfdi_xml",
    # Router
    "build_email_processing_router",
]
