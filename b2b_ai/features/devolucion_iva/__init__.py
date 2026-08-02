# -*- coding: utf-8 -*-
"""
Módulo de Devolución de IVA.

Gestiona el proceso completo de devolución de IVA para despachos contables:
  - Recopilación y clasificación de facturas CFDI
  - Generación de DIOT
  - Conciliación CFDI↔DIOT↔Declaraciones
  - Cálculo de saldo a favor y monto de devolución
  - Preparación de solicitud y papel de trabajo
  - Seguimiento de solicitudes ante el SAT

Expone:
  - Enums: EstatusConciliacion, EstatusDevolucion, TipoFactura
  - Models: FacturaCFDI, DIOTEntry, DeclaracionMensual, PapelTrabajo, ...
  - DevolucionIVAService — lógica completa del proceso
  - validate_rfc, validate_iva_rate, ... — validators
  - build_devolucion_iva_router() — FastAPI router
"""
from b2b_ai.features.devolucion_iva.models import (
    EstatusConciliacion,
    EstatusDevolucion,
    TipoFactura,
    FacturaCFDI,
    DIOTEntry,
    DeclaracionMensual,
    PapelTrabajo,
    ConciliacionFacturasDIOT,
    ConciliacionDIOTDeclaracion,
    SolicitudDevolucion,
    StatusDevolucion,
)
from b2b_ai.features.devolucion_iva.service import DevolucionIVAService
from b2b_ai.features.devolucion_iva.validators import (
    validate_rfc,
    validate_iva_rate,
    validate_amount,
    validate_date_format,
    validate_diot_consistency,
    validate_declaration_consistency,
)
from b2b_ai.features.devolucion_iva.workpaper import WorkpaperGenerator
from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router

__all__ = [
    "EstatusConciliacion",
    "EstatusDevolucion",
    "TipoFactura",
    "FacturaCFDI",
    "DIOTEntry",
    "DeclaracionMensual",
    "PapelTrabajo",
    "ConciliacionFacturasDIOT",
    "ConciliacionDIOTDeclaracion",
    "SolicitudDevolucion",
    "StatusDevolucion",
    "DevolucionIVAService",
    "validate_rfc",
    "validate_iva_rate",
    "validate_amount",
    "validate_date_format",
    "validate_diot_consistency",
    "validate_declaration_consistency",
    "WorkpaperGenerator",
    "build_devolucion_iva_router",
]
