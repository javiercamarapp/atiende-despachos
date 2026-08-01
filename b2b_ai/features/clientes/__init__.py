# -*- coding: utf-8 -*-
"""
Módulo Clientes: sistema de respuesta a consultas de clientes.

Expone:
  - QueryType, InvoiceStatusType — enums
  - ClientQuery, InvoiceStatus, FAQEntry — core schemas
  - ClientService — lógica de routing, FAQ, estado de facturas
  - validate_query_type, validate_cfdi_id, validate_concepto — validators
  - build_clientes_router — FastAPI router (/api/v1/clientes/*)
"""
from b2b_ai.features.clientes.models import (
    ClientQuery,
    FAQEntry,
    InvoiceStatus,
    QueryType,
    QueryCategory,
)
from b2b_ai.features.clientes.service import ClientService
from b2b_ai.features.clientes.validators import (
    validate_cfdi_id,
    validate_concepto,
    validate_query_type,
)
from b2b_ai.features.clientes.routes import build_clientes_router

__all__ = [
    # Enums
    "QueryType",
    "QueryCategory",
    # Schemas
    "ClientQuery",
    "InvoiceStatus",
    "FAQEntry",
    # Service
    "ClientService",
    # Validators
    "validate_query_type",
    "validate_cfdi_id",
    "validate_concepto",
    # Router
    "build_clientes_router",
]
