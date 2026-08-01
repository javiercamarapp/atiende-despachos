# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the DIOT module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent DIOT entries, summaries, and reports used by
contadores in Mexico for the Declaración Informativa de Operaciones
con Terceros.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OperacionType(str, Enum):
    """Tipo de operación DIOT."""
    COMPRA = "01"       # Compra
    DEVOLUCION = "02"   # Devolución de compra
    GASTOS = "03"       # Gastos
    INTERESES = "04"    # Intereses
    OTROS = "05"        # Otros


# Alias used by service.py
TipoOperacion = OperacionType


class TipoIva(str, Enum):
    """Tipo de IVA aplicable."""
    GENERAL = "16"
    REDUCIDO = "8"
    EXENTO = "0"


class EstatusDIOT(str, Enum):
    """Estatus de la DIOT generada."""
    PENDIENTE = "PENDIENTE"
    VALIDANDO = "VALIDANDO"
    GENERADA = "GENERADA"
    VALIDADA = "VALIDADA"
    EXPORTADA = "EXPORTADA"
    ENVIADA = "ENVIADA"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class CFDIInvoiceInput(BaseModel):
    """Representa una factura CFDI de entrada para generación de DIOT."""
    uuid: str = Field(..., description="UUID del CFDI")
    rfc_emisor: str = Field(..., description="RFC del emisor")
    nombre_emisor: str = Field(default="", description="Nombre del emisor")
    subtotal: float = Field(..., description="Subtotal de la factura (sin IVA)")
    iva_trasladado: float = Field(default=0.0, description="IVA trasladado")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable")
    tipo_cambio: float = Field(default=1.0, description="Tipo de cambio a MXN")
    tipo_operacion: OperacionType = Field(
        default=OperacionType.COMPRA,
        description="Tipo de operación DIOT",
    )
    tipo_iva: TipoIva = Field(
        default=TipoIva.GENERAL,
        description="Tasa de IVA aplicada",
    )


# ---------------------------------------------------------------------------
# Inconsistencia schema
# ---------------------------------------------------------------------------

class Inconsistencia(BaseModel):
    """Una inconsistencia detectada en los datos de la DIOT."""
    tipo: str = Field(..., description="Tipo de inconsistencia")
    severidad: str = Field(default="warning", description="Severidad: info, warning, critical")
    descripcion: str = Field(default="", description="Descripción de la inconsistencia")


# ---------------------------------------------------------------------------
# Core schemas — DIOT Entry
# ---------------------------------------------------------------------------

class DiotEntry(BaseModel):
    """Una entrada individual de la DIOT (operación con un tercero)."""
    rfc_tercero: str = Field(
        ...,
        description="RFC del tercero (emisor o receptor según tipo)",
    )
    nombre: str = Field(
        default="",
        description="Nombre o razón social del tercero",
    )
    tipo_operacion: OperacionType = Field(
        ...,
        description="Tipo de operación: 01=Compra, 02=Devolución, 03=Gastos, 04=Intereses, 05=Otros",
    )
    tipo_iva: TipoIva = Field(
        default=TipoIva.GENERAL,
        description="Tasa de IVA del tercero",
    )
    monto_neto: float = Field(
        ...,
        description="Monto neto de la operación (sin IVA)",
    )
    iva_trasladado: float = Field(
        ...,
        description="IVA trasladado por el tercero",
    )
    iva_acreditable: float = Field(
        ...,
        description="IVA acreditable del tercero",
    )
    numero_facturas: int = Field(
        default=1,
        description="Número de facturas agrupadas",
    )
    uuids: List[str] = Field(
        default_factory=list,
        description="UUIDs de las facturas asociadas",
    )
    uuid_cfdi: Optional[str] = Field(
        default=None,
        description="UUID del CFDI asociado (compatibilidad)",
    )
    fecha: Optional[str] = Field(
        default=None,
        description="Fecha de la operación YYYY-MM-DD (opcional)",
    )

    @field_validator("rfc_tercero")
    @classmethod
    def _rfc_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rfc_tercero no puede estar vacío")
        return v.strip().upper()

    @field_validator("monto_neto")
    @classmethod
    def _monto_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("monto_neto no puede ser negativo")
        return v

    @field_validator("iva_trasladado")
    @classmethod
    def _iva_trasladado_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("iva_trasladado no puede ser negativo")
        return v

    @field_validator("iva_acreditable")
    @classmethod
    def _iva_acreditable_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("iva_acreditable no puede ser negativo")
        return v


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------

class DiotSummary(BaseModel):
    """Resumen de la DIOT para un período dado."""
    total_operaciones: int = Field(
        default=0,
        description="Número total de operaciones",
    )
    total_iva_trasladado: float = Field(
        default=0.0,
        description="Suma total de IVA trasladado",
    )
    total_iva_acreditable: float = Field(
        default=0.0,
        description="Suma total de IVA acreditable",
    )
    diferencias: float = Field(
        default=0.0,
        description="Diferencia entre IVA trasladado y acreditable",
    )
    total_monto_neto: float = Field(
        default=0.0,
        description="Suma total de montos netos",
    )


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------

class DiotReport(BaseModel):
    """Reporte completo de la DIOT para un período."""
    id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Identificador único del reporte",
    )
    month: int = Field(
        ...,
        description="Mes de la DIOT (1-12)",
    )
    year: int = Field(
        ...,
        description="Año de la DIOT",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )
    entries: List[DiotEntry] = Field(
        default_factory=list,
        description="Lista de entradas DIOT",
    )
    summary: DiotSummary = Field(
        default_factory=DiotSummary,
        description="Resumen de la DIOT",
    )
    inconsistencies: List[Inconsistencia] = Field(
        default_factory=list,
        description="Lista de inconsistencias detectadas",
    )
    estatus: EstatusDIOT = Field(
        default=EstatusDIOT.PENDIENTE,
        description="Estatus actual de la DIOT",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Fecha de creación ISO format",
    )
    generated_at: Optional[datetime] = Field(
        default=None,
        description="Fecha de generación del reporte",
    )

    @field_validator("month")
    @classmethod
    def _month_valid(cls, v: int) -> int:
        if v < 1 or v > 12:
            raise ValueError("month debe estar entre 1 y 12")
        return v

    def recompute_summary(self) -> None:
        """Recalcular el resumen a partir de las entradas."""
        self.summary = DiotSummary(
            total_operaciones=len(self.entries),
            total_iva_trasladado=sum(e.iva_trasladado for e in self.entries),
            total_iva_acreditable=sum(e.iva_acreditable for e in self.entries),
            total_monto_neto=sum(e.monto_neto for e in self.entries),
        )
        self.summary.diferencias = (
            self.summary.total_iva_trasladado - self.summary.total_iva_acreditable
        )
