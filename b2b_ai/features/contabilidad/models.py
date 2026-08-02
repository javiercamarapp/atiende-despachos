"""
models.py — Modelos Pydantic del módulo de Contabilidad.

Modelos base para operaciones contables de despachos contables mexicanos:
  - ContabilidadEntry     : registro contable base (partida individual)
  - BalanceGeneral        : balance general (activos, pasivos, capital)
  - EstadoResultados     : estado de resultados (ingresos, costos, gastos)
  - AsientoContable       : asiento contable (partida con múltiples cuentas)
  - CatálogoCuentas       : catálogo de cuentas contables
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TipoCuenta(str, Enum):
    """Tipos de cuenta contable según catálogo SAT."""
    ACTIVO = "activo"
    PASIVO = "pasivo"
    CAPITAL = "capital"
    INGRESO = "ingreso"
    GASTO = "gasto"
    COSTO = "costo"


class GrupoCuenta(str, Enum):
    """Grupos de cuentas para clasificación."""
    ACTIVO_CORRIENTE = "activo_corriente"
    ACTIVO_NO_CORRIENTE = "activo_no_corriente"
    PASIVO_CORRIENTE = "pasivo_corriente"
    PASIVO_NO_CORRIENTE = "pasivo_no_corriente"
    CAPITAL_CONTABLE = "capital_contable"
    INGRESOS_OPERACIONALES = "ingresos_operacionales"
    INGRESOS_NO_OPERACIONALES = "ingresos_no_operacionales"
    COSTOS = "costos"
    GASTOS_OPERACIONALES = "gastos_operacionales"
    GASTOS_NO_OPERACIONALES = "gastos_no_operacionales"


class TipoAsiento(str, Enum):
    """Tipos de asiento contable."""
    DIARIO = "diario"
    INGRESO = "ingreso"
    EGRESO = "egreso"
    AJUSTE = "ajuste"
    APERTURA = "apertura"
    CIERRE = "cierre"


class NaturalezaCuenta(str, Enum):
    """Naturaleza de la cuenta: Deudora o Acreedora."""
    DEUDORA = "D"
    ACREEDORA = "A"


# ---------------------------------------------------------------------------
# Modelos principales
# ---------------------------------------------------------------------------

class ContabilidadEntry(BaseModel):
    """Registro contable base: una línea de una partida contable.

    Attributes:
        id: UUID del registro.
        empresa_id: Identificador de la empresa.
        cuenta_contable: Código de la cuenta contable (4-15 dígitos SAT).
        descripcion: Descripción del movimiento.
        debito: Monto en debito (>= 0).
        credito: Monto en credito (>= 0).
        fecha: Fecha del movimiento.
        periodo: Período contable (YYYY-MM).
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    empresa_id: str
    cuenta_contable: str
    descripcion: str
    debito: float = Field(ge=0.0, default=0.0)
    credito: float = Field(ge=0.0, default=0.0)
    fecha: date
    periodo: str  # YYYY-MM

    @field_validator("cuenta_contable")
    @classmethod
    def validate_cuenta_contable(cls, v: str) -> str:
        """Código de cuenta: solo dígitos, 4-15 caracteres."""
        if not re.match(r"^\d{4,15}$", v):
            raise ValueError(
                f"Código de cuenta '{v}' inválido. Debe ser 4-15 dígitos."
            )
        return v

    @field_validator("periodo")
    @classmethod
    def validate_periodo(cls, v: str) -> str:
        """Período en formato YYYY-MM."""
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Periodo '{v}' inválido. Formato: YYYY-MM.")
        return v


class BalanceGeneral(BaseModel):
    """Balance general: snapshot de la posición financiera.

    Attributes:
        empresa_id: Identificador de la empresa.
        periodo: Período contable (YYYY-MM).
        activos: Total de activos.
        pasivos: Total de pasivos.
        capital: Capital contable (activos - pasivos).
        activos_corriente: Activos corrientes.
        activos_no_corriente: Activos no corrientes.
        pasivos_corriente: Pasivos corrientes.
        pasivos_no_corriente: Pasivos no corrientes.
        generado_en: Timestamp de generación.
    """
    empresa_id: str
    periodo: str
    activos: float = 0.0
    pasivos: float = 0.0
    capital: float = 0.0
    activos_corriente: float = 0.0
    activos_no_corriente: float = 0.0
    pasivos_corriente: float = 0.0
    pasivos_no_corriente: float = 0.0
    generado_en: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("periodo")
    @classmethod
    def validate_periodo(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Periodo '{v}' inválido. Formato: YYYY-MM.")
        return v


class EstadoResultados(BaseModel):
    """Estado de resultados: desempeño financiero del período.

    Attributes:
        empresa_id: Identificador de la empresa.
        periodo: Período contable (YYYY-MM).
        ingresos: Total de ingresos.
        costos: Total de costos de venta.
        utilidad_bruta: Ingresos - Costos.
        gastos: Total de gastos de operación.
        otros_ingresos: Otros ingresos no operacionales.
        otros_gastos: Otros gastos no operacionales.
        utilidad_antes_impuestos: Utilidad antes de impuestos.
        impuestos: ISR estimado.
        utilidad_neta: Utilidad neta del período.
        generado_en: Timestamp de generación.
    """
    empresa_id: str
    periodo: str
    ingresos: float = 0.0
    costos: float = 0.0
    utilidad_bruta: float = 0.0
    gastos: float = 0.0
    otros_ingresos: float = 0.0
    otros_gastos: float = 0.0
    utilidad_antes_impuestos: float = 0.0
    impuestos: float = 0.0
    utilidad_neta: float = 0.0
    generado_en: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("periodo")
    @classmethod
    def validate_periodo(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Periodo '{v}' inválido. Formato: YYYY-MM.")
        return v


class LineaAsiento(BaseModel):
    """Una línea dentro de un asiento contable.

    Attributes:
        cuenta_contable: Código de cuenta (4-15 dígitos).
        debito: Monto debito.
        credito: Monto credito.
        descripcion: Descripción de la línea.
    """
    cuenta_contable: str
    debito: float = Field(ge=0.0, default=0.0)
    credito: float = Field(ge=0.0, default=0.0)
    descripcion: str = ""

    @field_validator("cuenta_contable")
    @classmethod
    def validate_cuenta_contable(cls, v: str) -> str:
        if not re.match(r"^\d{4,15}$", v):
            raise ValueError(
                f"Código de cuenta '{v}' inválido. Debe ser 4-15 dígitos."
            )
        return v


class AsientoContable(BaseModel):
    """Asiento contable: grupo de líneas que cuadran (débito == crédito).

    Attributes:
        id: UUID del asiento.
        empresa_id: Identificador de la empresa.
        partida_id: ID de la partida contable.
        fecha: Fecha del asiento.
        periodo: Período contable (YYYY-MM).
        tipo: Tipo de asiento (diario, ingreso, egreso, ajuste, apertura, cierre).
        descripcion: Descripción general del asiento.
        lineas: Lista de líneas del asiento.
        creado_en: Timestamp de creación.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    empresa_id: str
    partida_id: str
    fecha: date
    periodo: str
    tipo: TipoAsiento
    descripcion: str
    lineas: List[LineaAsiento] = Field(min_length=2)
    creado_en: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("periodo")
    @classmethod
    def validate_periodo(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError(f"Periodo '{v}' inválido. Formato: YYYY-MM.")
        return v


class CuentaCatalogo(BaseModel):
    """Cuenta del catálogo de cuentas contables.

    Attributes:
        codigo: Código de la cuenta (4-15 dígitos).
        nombre: Nombre de la cuenta.
        tipo: Tipo de cuenta (activo, pasivo, capital, ingreso, gasto, costo).
        grupo: Grupo contable.
        nivel: Nivel jerárquico (1-5).
        naturaleza: Naturaleza de la cuenta (D=Deudora, A=Acreedora).
        activa: Si la cuenta está activa.
        empresa_id: Identificador de la empresa.
    """
    codigo: str
    nombre: str
    tipo: TipoCuenta
    grupo: GrupoCuenta
    nivel: int = Field(ge=1, le=5, default=1)
    naturaleza: NaturalezaCuenta = NaturalezaCuenta.DEUDORA
    activa: bool = True
    empresa_id: str

    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        if not re.match(r"^\d{4,15}$", v):
            raise ValueError(
                f"Código '{v}' inválido. Debe ser 4-15 dígitos."
            )
        return v
