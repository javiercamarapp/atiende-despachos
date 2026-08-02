# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Devolución de IVA module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent the complete data flow for IVA refund processing:
  CFDI invoices → DIOT entries → Declarations → Conciliation → Solicitud.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EstatusConciliacion(str, Enum):
    """Estado de una conciliación."""
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"


class EstatusDevolucion(str, Enum):
    """Estatus de una solicitud de devolución ante el SAT."""
    PENDIENTE = "pendiente"
    EN_REVISION = "en_revision"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    PAGADA = "pagada"


class TipoFactura(str, Enum):
    """Tipo de factura CFDI."""
    INGRESO = "Ingreso"
    EGRESO = "Egreso"
    TRASLADO = "Traslado"
    NOMINA = "Nómina"
    PAGO = "Pago"


class ClasificacionIVA(str, Enum):
    """Clasificación de acreditamiento de IVA."""
    CREDITABLE_100 = "acreditable_100"
    CREDITABLE_PROPORCIONAL = "acreditable_proporcional"
    NO_CREDITABLE = "no_acreditable"


# ---------------------------------------------------------------------------
# Core schemas — FacturaCFDI
# ---------------------------------------------------------------------------

class FacturaCFDI(BaseModel):
    """Representa una factura CFDI para el proceso de devolución de IVA."""
    uuid: str = Field(..., description="UUID del CFDI (folio fiscal)")
    rfc_emisor: str = Field(..., description="RFC del emisor")
    rfc_receptor: str = Field(..., description="RFC del receptor")
    fecha: str = Field(..., description="Fecha de la factura (YYYY-MM-DD)")
    subtotal: float = Field(..., description="Subtotal de la factura (sin IVA)")
    iva: float = Field(default=0.0, description="IVA trasladado")
    total: float = Field(default=0.0, description="Total de la factura")
    tipo: TipoFactura = Field(
        default=TipoFactura.INGRESO,
        description="Tipo de comprobante fiscal",
    )
    categoria: ClasificacionIVA = Field(
        default=ClasificacionIVA.CREDITABLE_100,
        description="Clasificación de acreditamiento del IVA",
    )
    banco_pago: Optional[str] = Field(
        default=None,
        description="Banco donde se efectuó el pago",
    )
    fecha_pago: Optional[str] = Field(
        default=None,
        description="Fecha en que se efectuó el pago (YYYY-MM-DD)",
    )
    proporcionalidad: float = Field(
        default=1.0,
        description="Proporción de acreditamiento (0.0 a 1.0)",
    )

    @field_validator("uuid")
    @classmethod
    def _uuid_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("uuid no puede estar vacío")
        return v.strip()

    @field_validator("rfc_emisor", "rfc_receptor")
    @classmethod
    def _rfc_upper(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("RFC no puede estar vacío")
        return v.strip().upper()

    @field_validator("subtotal", "iva", "total")
    @classmethod
    def _amount_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v


# ---------------------------------------------------------------------------
# Core schemas — DIOTEntry
# ---------------------------------------------------------------------------

class DIOTEntry(BaseModel):
    """Una entrada de la DIOT agrupada por RFC tercero."""
    rfc_tercero: str = Field(..., description="RFC del tercero")
    nombre: str = Field(default="", description="Nombre o razón social")
    tipo_operacion: str = Field(default="01", description="Tipo de operación DIOT")
    monto_neto: float = Field(default=0.0, description="Monto neto (sin IVA)")
    iva_trasladado: float = Field(default=0.0, description="IVA trasladado")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable")
    folios_fiscales: List[str] = Field(
        default_factory=list,
        description="UUIDs de facturas asociadas",
    )

    @field_validator("rfc_tercero")
    @classmethod
    def _rfc_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rfc_tercero no puede estar vacío")
        return v.strip().upper()

    @field_validator("monto_neto", "iva_trasladado", "iva_acreditable")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v


# ---------------------------------------------------------------------------
# Core schemas — DeclaracionMensual
# ---------------------------------------------------------------------------

class DeclaracionMensual(BaseModel):
    """Declaración mensual de IVA presentada ante el SAT."""
    mes: int = Field(..., ge=1, le=12, description="Mes (1-12)")
    año: int = Field(..., ge=2014, description="Año fiscal")
    iva_cobrado: float = Field(default=0.0, description="IVA causado (cobrado en ventas)")
    iva_pagado: float = Field(default=0.0, description="IVA pagado (acreditable en compras)")
    saldo_favor: float = Field(default=0.0, description="Saldo a favor del contribuyente")
    saldo_contra: float = Field(default=0.0, description="Saldo en contra del contribuyente")

    @field_validator("iva_cobrado", "iva_pagado", "saldo_favor", "saldo_contra")
    @classmethod
    def _amount_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v


# ---------------------------------------------------------------------------
# Conciliation schemas
# ---------------------------------------------------------------------------

class ConciliacionFacturasDIOT(BaseModel):
    """Resultado de conciliación entre una factura CFDI y la DIOT."""
    factura_uuid: str = Field(..., description="UUID de la factura")
    diot_match: bool = Field(default=False, description="¿Se encontró match en DIOT?")
    status: EstatusConciliacion = Field(
        default=EstatusConciliacion.MISSING,
        description="Estado de la conciliación",
    )
    detalles: str = Field(default="", description="Detalles de la conciliación")


class ConciliacionDIOTDeclaracion(BaseModel):
    """Resultado de conciliación entre DIOT y Declaración mensual."""
    diot_iva_total: float = Field(default=0.0, description="IVA total de DIOT")
    declaracion_iva_acreditable: float = Field(
        default=0.0,
        description="IVA acreditable declarado",
    )
    diferencia: float = Field(default=0.0, description="Diferencia entre DIOT y declaración")
    status: EstatusConciliacion = Field(
        default=EstatusConciliacion.MISSING,
        description="Estado de la conciliación",
    )


# ---------------------------------------------------------------------------
# Solicitud & Status schemas
# ---------------------------------------------------------------------------

class SolicitudDevolucion(BaseModel):
    """Solicitud de devolución de IVA ante el SAT."""
    solicitud_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="ID único de la solicitud",
    )
    periodo: str = Field(..., description="Periodo de la devolución (YYYY-MM)")
    monto_solicitado: float = Field(..., description="Monto solicitado en devolución")
    cuenta_banco: Optional[str] = Field(default=None, description="Nombre del banco")
    clabe: Optional[str] = Field(default=None, description="CLABE interbancaria (18 dígitos)")
    documentos: List[str] = Field(
        default_factory=list,
        description="Documentos adjuntos",
    )
    status: EstatusDevolucion = Field(
        default=EstatusDevolucion.PENDIENTE,
        description="Estatus actual de la solicitud",
    )
    created_at: Optional[str] = Field(default=None, description="Fecha de creación ISO")


class StatusDevolucion(BaseModel):
    """Estado de seguimiento de una solicitud de devolución."""
    solicitud_id: str = Field(..., description="ID de la solicitud")
    status: EstatusDevolucion = Field(
        default=EstatusDevolucion.PENDIENTE,
        description="Estatus actual",
    )
    fecha_presentacion: Optional[str] = Field(
        default=None,
        description="Fecha de presentación (YYYY-MM-DD)",
    )
    fecha_respuesta: Optional[str] = Field(
        default=None,
        description="Fecha de respuesta del SAT (YYYY-MM-DD)",
    )
    monto_aprobado: Optional[float] = Field(
        default=None,
        description="Monto aprobado por el SAT",
    )
    observaciones: Optional[str] = Field(
        default=None,
        description="Observaciones del SAT",
    )


# ---------------------------------------------------------------------------
# PapelTrabajo schema
# ---------------------------------------------------------------------------

class PapelTrabajo(BaseModel):
    """Papel de trabajo de conciliación para devolución de IVA."""
    periodo: str = Field(..., description="Periodo (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    facturas: List[FacturaCFDI] = Field(
        default_factory=list,
        description="Facturas del periodo",
    )
    diot_entries: List[DIOTEntry] = Field(
        default_factory=list,
        description="Entradas DIOT del periodo",
    )
    declaraciones: List[DeclaracionMensual] = Field(
        default_factory=list,
        description="Declaraciones mensuales",
    )
    saldo_a_favor: float = Field(default=0.0, description="Saldo a favor calculado")
    monto_solicitado: float = Field(default=0.0, description="Monto solicitado en devolución")
    status: str = Field(default="pendiente", description="Estado del papel de trabajo")
    created_at: Optional[str] = Field(default=None, description="Fecha de creación")
