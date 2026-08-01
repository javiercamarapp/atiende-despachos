# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for Income/Expense Reconciliation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent bank deposits, auxiliary accounting entries, classifications,
discrepancies, IVA balance, and working papers used by despachos contables
in Mexico.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ClasificacionDeposito(str, Enum):
    """Clasificación fiscal de un depósito bancario."""
    INGRESO = "ingreso"
    FINANCIAMIENTO = "financiamiento"
    APORTACION_SOCIO = "aportacion_socio"
    GARANTIA = "garantia"
    OTRO_NO_GRAVABLE = "otro_no_gravable"


class TipoDiscrepancia(str, Enum):
    """Tipo de discrepancia fiscal o bancaria."""
    MONTO = "monto"
    FECHA = "fecha"
    CLASIFICACION = "clasificacion"
    FALTA_DOCUMENTACION = "falta_documentacion"


class Severidad(str, Enum):
    """Nivel de severidad de una discrepancia."""
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class TipoMovimientoAuxiliar(str, Enum):
    """Tipo de movimiento en auxiliar contable."""
    INGRESO = "ingreso"
    EGRESO = "egreso"
    CONSUMO = "consumo"
    ANTICIPO = "anticipo"
    DEVOLUCION = "devolucion"


# ---------------------------------------------------------------------------
# Bank deposit
# ---------------------------------------------------------------------------

class DepositoBancario(BaseModel):
    """Un depósito o abono bancario para un período dado."""
    id: str = Field(default="", description="Identificador único del depósito")
    fecha: str = Field(default="", description="Fecha del depósito (YYYY-MM-DD)")
    monto: float = Field(default=0.0, description="Monto del depósito en MXN")
    descripcion: str = Field(default="", description="Descripción o concepto del depósito")
    referencia: str = Field(default="", description="Referencia bancaria o UUID de CFDI")
    banco: str = Field(default="", description="Nombre del banco")
    cuenta: str = Field(default="", description="Número de cuenta bancaria")
    es_credito: bool = Field(default=True, description="True si es abono/crédito; False si es cargo/débito")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "DEP-001",
                "fecha": "2026-06-15",
                "monto": 125000.00,
                "descripcion": "Pago cliente ABC SA de CV",
                "referencia": "CFDI-ABC-001",
                "banco": "BBVA",
                "cuenta": "0123456789",
                "es_credito": True,
            }]
        }
    }


# ---------------------------------------------------------------------------
# Auxiliary accounting entry
# ---------------------------------------------------------------------------

class MovimientoAuxiliar(BaseModel):
    """Un movimiento individual dentro de una cuenta auxiliar."""
    fecha: str = Field(default="", description="Fecha del movimiento (YYYY-MM-DD)")
    concepto: str = Field(default="", description="Concepto del movimiento")
    debe: float = Field(default=0.0, ge=0, description="Monto en el debe (cargos)")
    haber: float = Field(default=0.0, ge=0, description="Monto en el haber (abonos)")
    referencia: str = Field(default="", description="Referencia del documento o CFDI")
    tipo: TipoMovimientoAuxiliar = Field(
        default=TipoMovimientoAuxiliar.INGRESO,
        description="Tipo de movimiento",
    )


class AuxiliarContable(BaseModel):
    """Una cuenta auxiliar contable con sus movimientos."""
    cuenta_id: str = Field(default="", description="Identificador de la cuenta auxiliar")
    cuenta_mayor: str = Field(default="", description="Cuenta mayor asociada")
    cuenta_auxiliar: str = Field(default="", description="Número de cuenta auxiliar")
    descripcion: str = Field(default="", description="Descripción de la cuenta")
    saldo_inicial: float = Field(default=0.0, description="Saldo inicial del período")
    movimientos: List[MovimientoAuxiliar] = Field(
        default_factory=list,
        description="Lista de movimientos de la cuenta auxiliar",
    )
    saldo_final: float = Field(default=0.0, description="Saldo final del período")


# ---------------------------------------------------------------------------
# Deposit classification result
# ---------------------------------------------------------------------------

class ClasificacionDepositoResult(BaseModel):
    """Resultado de la clasificación de un depósito bancario."""
    deposito_id: str = Field(default="", description="ID del depósito clasificado")
    clasificacion: ClasificacionDeposito = Field(
        ...,
        description="Clasificación fiscal del depósito",
    )
    confianza: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Nivel de confianza de la clasificación (0-1)",
    )
    razon: str = Field(default="", description="Razón o justificación de la clasificación")
    articulo_cff: Optional[str] = Field(
        default=None,
        description="Artículo del CFF aplicable (si aplica)",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Si la clasificación requiere revisión humana",
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class ConciliacionIngresosEgresos(BaseModel):
    """Resultado de la conciliación entre depósitos bancarios y auxiliares contables."""
    periodo: str = Field(default="", description="Período conciliado (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    depositos: List[DepositoBancario] = Field(
        default_factory=list,
        description="Depósitos del período",
    )
    auxiliares: List[AuxiliarContable] = Field(
        default_factory=list,
        description="Auxiliares contables del período",
    )
    clasificaciones: List[ClasificacionDepositoResult] = Field(
        default_factory=list,
        description="Clasificaciones de depósitos",
    )
    discrepancias: List["DiscrepanciaFiscal"] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    saldo_bancario: float = Field(default=0.0, description="Saldo bancario total")
    saldo_contable: float = Field(default=0.0, description="Saldo contable total")
    diferencia: float = Field(default=0.0, description="Diferencia entre saldo bancario y contable")


# ---------------------------------------------------------------------------
# Fiscal discrepancy
# ---------------------------------------------------------------------------

class DiscrepanciaFiscal(BaseModel):
    """Una discrepancia detectada en la conciliación fiscal."""
    tipo: TipoDiscrepancia = Field(..., description="Tipo de discrepancia")
    deposito_id: Optional[str] = Field(default=None, description="ID del depósito relacionado")
    auxiliar_id: Optional[str] = Field(default=None, description="ID del auxiliar relacionado")
    monto_afectado: float = Field(default=0.0, description="Monto afectado por la discrepancia")
    descripcion: str = Field(default="", description="Descripción de la discrepancia")
    severidad: Severidad = Field(
        default=Severidad.MEDIA,
        description="Nivel de severidad",
    )
    resuelta: bool = Field(default=False, description="Si la discrepancia ya fue resuelta")


# ---------------------------------------------------------------------------
# IVA balance
# ---------------------------------------------------------------------------

class BalanceIVA(BaseModel):
    """Balance de IVA para un período fiscal."""
    iva_cobrado: float = Field(default=0.0, description="IVA cobrado a clientes")
    iva_pagado: float = Field(default=0.0, description="IVA pagado a proveedores")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable (pagado - cobrado)")
    saldo_favor: float = Field(default=0.0, description="Saldo a favor (IVA pagado > cobrado)")
    saldo_contra: float = Field(default=0.0, description="Saldo en contra (IVA cobrado > pagado)")
    declarado: float = Field(default=0.0, description="Monto declarado en la declaración SAT")
    discrepancia: float = Field(default=0.0, description="Discrepancia entre cálculo y declaración")


# ---------------------------------------------------------------------------
# Working paper
# ---------------------------------------------------------------------------

class SeccionResumen(BaseModel):
    """Sección de resumen del papel de trabajo."""
    titulo: str = Field(default="", description="Título de la sección")
    contenido: str = Field(default="", description="Contenido de la sección")
    total_depositos: int = Field(default=0, description="Total de depósitos analizados")
    total_auxiliares: int = Field(default=0, description="Total de auxiliares analizados")


class PapelTrabajoConciliacion(BaseModel):
    """Papel de trabajo de conciliación de ingresos y egresos."""
    periodo: str = Field(default="", description="Período del papel de trabajo (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    resumen: List[SeccionResumen] = Field(
        default_factory=list,
        description="Secciones de resumen",
    )
    clasificaciones: List[ClasificacionDepositoResult] = Field(
        default_factory=list,
        description="Clasificaciones de depósitos",
    )
    discrepancias: List[DiscrepanciaFiscal] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    balanceiva: List[BalanceIVA] = Field(
        default_factory=list,
        description="Balances de IVA",
    )
    conclusiones: List[str] = Field(
        default_factory=list,
        description="Conclusiones del análisis",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Si el papel de trabajo requiere revisión humana",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Fecha de creación ISO format",
    )
