# -*- coding: utf-8 -*-
"""
models.py — Esquemas Pydantic para Contabilidad Electrónica del SAT.

Modelos:
  CuentaContable       — Cuenta individual del catálogo.
  BalanzaRow           — Línea de la balanza de comprobación.
  BalanzaRequest       — Request completo para generar balanza XML.
  CatalogoCuenta       — Cuenta del catálogo para generar XML.
  ContabilidadElectronicaResponse — Response estándar con UUID y XML.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TipoCuenta(str, Enum):
    """Tipos de cuenta contable según clasificación SAT."""
    ACTIVO = "Activo"
    PASIVO = "Pasivo"
    CAPITAL = "Capital"
    INGRESO = "Ingreso"
    GASTO = "Gasto"


class CuentaContable(BaseModel):
    """Cuenta individual del catálogo de cuentas SAT."""
    codigo: str = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Código de la cuenta (4-15 dígitos).",
        examples=["101.01.01"],
    )
    descripcion: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Descripción de la cuenta.",
    )
    tipo: TipoCuenta = Field(
        ...,
        description="Tipo de cuenta: Activo, Pasivo, Capital, Ingreso o Gasto.",
    )
    nivel: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Nivel jerárquico (1-5).",
    )
    padre: Optional[str] = Field(
        default=None,
        description="Código de la cuenta padre (None si es nivel 1).",
    )
    saldo: float = Field(
        default=0.0,
        description="Saldo actual de la cuenta.",
    )


class BalanzaRow(BaseModel):
    """Línea de la Balanza de Comprobación mensual."""
    codigo_cuenta: str = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Código de la cuenta contable.",
    )
    saldo_inicial: float = Field(
        default=0.0,
        description="Saldo al inicio del período.",
    )
    debe: float = Field(
        default=0.0,
        ge=0.0,
        description="Total de cargos (debe) del período.",
    )
    haber: float = Field(
        default=0.0,
        ge=0.0,
        description="Total de abonos (haber) del período.",
    )
    saldo_final: float = Field(
        default=0.0,
        description="Saldo al cierre del período.",
    )


class BalanzaRequest(BaseModel):
    """Request para generar la Balanza de Comprobación XML del SAT."""
    periodo: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Período en formato YYYY-MM.",
        examples=["2025-01"],
    )
    ejercicio: int = Field(
        ...,
        ge=2000,
        le=2100,
        description="Año del ejercicio fiscal.",
    )
    mes: int = Field(
        ...,
        ge=1,
        le=12,
        description="Mes del ejercicio (1-12).",
    )
    rfc: Optional[str] = Field(
        default=None,
        description="RFC del contribuyente (obligatorio en el XSD SAT).",
        examples=["ABC850101T1A"],
    )
    rows: List[BalanzaRow] = Field(
        default_factory=list,
        description="Líneas de la balanza de comprobación.",
    )


class CatalogoCuenta(BaseModel):
    """Cuenta del Catálogo de Cuentas para generar XML SAT."""
    codigo: str = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Código de la cuenta (4-15 dígitos o con puntos).",
    )
    descripcion: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Descripción de la cuenta.",
    )
    tipo: TipoCuenta = Field(
        ...,
        description="Tipo de cuenta.",
    )
    nivel: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Nivel jerárquico (1-5).",
    )
    subtipo_cuenta: Optional[str] = Field(
        default=None,
        description="Subtipo de cuenta (ej: Detallable, Agrupadora).",
    )
    padre: Optional[str] = Field(
        default=None,
        description="Código de la cuenta padre.",
    )
    status: str = Field(
        default="A",
        pattern=r"^[AI]$",
        description="Estado: A=Activa, I=Inactiva.",
    )


class ContabilidadElectronicaResponse(BaseModel):
    """Response estándar para generación de XML de contabilidad electrónica."""
    uuid: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único de la generación.",
    )
    fecha_generacion: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        description="Fecha y hora de generación (UTC).",
    )
    estado: str = Field(
        default="generado",
        description="Estado de la generación.",
    )
    xml_content: str = Field(
        default="",
        description="Contenido XML generado.",
    )
    errores: List[str] = Field(
        default_factory=list,
        description="Lista de errores encontrados (vacía si es válido).",
    )
