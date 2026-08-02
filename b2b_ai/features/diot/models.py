# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas para el módulo DIOT.

Declaración Informativa de Operaciones con Terceros (DIOT), cumplimiento
fiscal mexicano conforme al CFF Art. 32-H y reglas de la Resolución Miscelánea.

Modelos:
  - DIOTPeriod      : período trimestral (Q1-Q4)
  - DIOTRecord      : operación con un tercero (proveedor/servicio/importación)
  - DIOTSummary     : totales agregados (IVA trasladado vs acreditable)
  - DIOTDeclaration : declaración completa para un cliente + período
  - DIOTStatus      : ciclo de vida de la declaración
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Constantes de negocio DIOT
# ---------------------------------------------------------------------------

IVA_GENERAL = 0.16        # 16% IVA nacional
IVA_FRONTERA = 0.08       # 8% región fronteriza
IVA_EXENTO = 0.0          # 0% exento / tasa 0

PERIOD_MONTHS = {          # trimestre -> meses naturales
    1: (1, 2, 3),
    2: (4, 5, 6),
    3: (7, 8, 9),
    4: (10, 11, 12),
}

# Multa SAT por DIOT no presentada (CFF Art. 82 / RMF)
MULTA_SAT_MIN = 400.0
MULTA_SAT_MAX = 600.0


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DIOTStatus(str, Enum):
    """Ciclo de vida de una declaración DIOT."""
    BORRADOR = "BORRADOR"
    VALIDANDO = "VALIDANDO"
    VALIDADA = "VALIDADA"
    GENERADA = "GENERADA"
    EXPORTADA = "EXPORTADA"
    ERROR = "ERROR"


class TipoOperacion(str, Enum):
    """
    Tipo de operación reportada en la DIOT.

    A = Actividad empresarial (compras nacionales gravadas al 16%)
    D = Devoluciones / descuentos
    I = Importaciones
    S = Servicios recibidos
    """
    A = "A"   # Compras / adquisiciones
    D = "D"   # Devoluciones / descuentos y bonificaciones
    I = "I"   # Importaciones
    S = "S"   # Servicios recibidos


class TipoIVA(str, Enum):
    """Tasa de IVA aplicada a la operación."""
    IVA_16 = "16"
    IVA_08 = "8"
    IVA_00 = "0"


# ---------------------------------------------------------------------------
# DIOTPeriod — período trimestral
# ---------------------------------------------------------------------------

class DIOTPeriod(BaseModel):
    """Período trimestral de la DIOT.

    Campos:
      - year    : año fiscal
      - quarter : trimestre 1-4
      - month   : mes de corte dentro del trimestre (opcional; para
                  contribuyentes grandes la declaración es mensual)
    """
    year: int = Field(..., ge=2014, le=2099, description="Año fiscal")
    quarter: int = Field(..., ge=1, le=4, description="Trimestre (1-4)")
    month: Optional[int] = Field(
        default=None, ge=1, le=12,
        description="Mes de corte (mensual para grandes contribuyentes)",
    )

    @property
    def label(self) -> str:
        return f"{self.year}-Q{self.quarter}"

    @property
    def months(self) -> List[int]:
        return list(PERIOD_MONTHS[self.quarter])

    def __str__(self) -> str:
        return self.label

    @classmethod
    def from_string(cls, value: str) -> "DIOTPeriod":
        """Parse '2024-Q3' | '2024Q3' | '2024-3' | '2024-T3'."""
        import re
        s = value.strip().upper()
        # Normalize: capture 4-digit year + quarter (digit after Q/T or standalone)
        m = re.match(r"^(\d{4})[-_ ]*[QT]?[-_ ]*([1-4])$", s)
        if not m:
            raise ValueError(f"Período inválido: '{value}' (use YYYY-QN)")
        year, quarter = int(m.group(1)), int(m.group(2))
        return cls(year=year, quarter=quarter)


# ---------------------------------------------------------------------------
# DIOTRecord — operación con un tercero
# ---------------------------------------------------------------------------

class DIOTRecord(BaseModel):
    """
    Una operación reportable con un tercero.

    Campos obligatorios según el Anexo de la DIOT:
      - rfc_tercero       : RFC del proveedor/tercero
      - nombre            : nombre o razón social del tercero
      - regimen_fiscal    : clave de régimen fiscal del tercero
      - tipo_operacion    : A / D / I / S
      - base_gravable     : importe gravado de la operación
      - iva_trasladado    : IVA trasladado por el tercero
      - iva_acreditable   : IVA acreditable para el contribuyente
    """
    rfc_tercero: str = Field(..., description="RFC del tercero/proveedor")
    nombre: str = Field(default="", description="Nombre o razón social")
    regimen_fiscal: Optional[str] = Field(
        default=None, description="Clave de régimen fiscal del tercero",
    )
    tipo_operacion: TipoOperacion = Field(..., description="Tipo A/D/I/S")
    base_gravable: float = Field(..., ge=0, description="Base gravable")
    iva_trasladado: float = Field(default=0.0, ge=0, description="IVA trasladado")
    iva_acreditable: float = Field(default=0.0, ge=0, description="IVA acreditable")
    tasa_iva: TipoIVA = Field(
        default=TipoIVA.IVA_16, description="Tasa de IVA aplicada (16/8/0)",
    )

    @field_validator("rfc_tercero")
    @classmethod
    def _rfc_normalize(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("rfc_tercero no puede estar vacío")
        return v

    @field_validator("tipo_operacion")
    @classmethod
    def _tipo_validate(cls, v: TipoOperacion) -> TipoOperacion:
        if isinstance(v, str):
            v = TipoOperacion(v)
        return v

    @field_validator("iva_trasladado")
    @classmethod
    def _iva_t_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError("iva_trasladado no puede ser negativo")
        return round(v, 2)

    @field_validator("iva_acreditable")
    @classmethod
    def _iva_a_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError("iva_acreditable no puede ser negativo")
        return round(v, 2)

    @field_validator("base_gravable")
    @classmethod
    def _base_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError("base_gravable no puede ser negativo")
        return round(v, 2)

    @property
    def diferencia_iva(self) -> float:
        """Diferencia IVA trasladado vs acreditable."""
        return round(self.iva_trasladado - self.iva_acreditable, 2)

    def to_dict(self) -> Dict:
        return {
            "rfc_tercero": self.rfc_tercero,
            "nombre": self.nombre,
            "regimen_fiscal": self.regimen_fiscal,
            "tipo_operacion": self.tipo_operacion.value,
            "base_gravable": self.base_gravable,
            "iva_trasladado": self.iva_trasladado,
            "iva_acreditable": self.iva_acreditable,
            "tasa_iva": self.tasa_iva.value,
        }


# ---------------------------------------------------------------------------
# DIOTSummary — totales agregados
# ---------------------------------------------------------------------------

class DIOTSummary(BaseModel):
    """Resumen de totales de una declaración DIOT."""
    total_operaciones: int = Field(default=0, description="Número de operaciones")
    total_base_gravable: float = Field(default=0.0, description="Suma base gravable")
    total_iva_trasladado: float = Field(default=0.0, description="Suma IVA trasladado")
    total_iva_acreditable: float = Field(default=0.0, description="Suma IVA acreditable")
    diferencia_iva: float = Field(default=0.0, description="Trasladado - acreditable")
    por_tipo: Dict[str, int] = Field(default_factory=dict, description="Conteo por tipo")

    def to_dict(self) -> Dict:
        return {
            "total_operaciones": self.total_operaciones,
            "total_base_gravable": self.total_base_gravable,
            "total_iva_trasladado": self.total_iva_trasladado,
            "total_iva_acreditable": self.total_iva_acreditable,
            "diferencia_iva": self.diferencia_iva,
            "por_tipo": self.por_tipo,
        }


# ---------------------------------------------------------------------------
# DIOTDeclaration — declaración completa
# ---------------------------------------------------------------------------

class DIOTDeclaration(BaseModel):
    """Declaración DIOT completa para un cliente y período."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()), description="UUID")
    client_rfc: str = Field(..., description="RFC del contribuyente que declara")
    period: DIOTPeriod = Field(..., description="Período trimestral")
    records: List[DIOTRecord] = Field(default_factory=list, description="Operaciones")
    summary: DIOTSummary = Field(default_factory=DIOTSummary, description="Totales")
    status: DIOTStatus = Field(default=DIOTStatus.BORRADOR, description="Estado")
    created_at: Optional[datetime] = Field(default=None, description="Fecha de creación")

    @property
    def period_label(self) -> str:
        return self.period.label

    def recompute_summary(self) -> DIOTSummary:
        """Recalcula el resumen a partir de los registros."""
        por_tipo: Dict[str, int] = {}
        for r in self.records:
            por_tipo[r.tipo_operacion.value] = por_tipo.get(r.tipo_operacion.value, 0) + 1
        self.summary = DIOTSummary(
            total_operaciones=len(self.records),
            total_base_gravable=round(sum(r.base_gravable for r in self.records), 2),
            total_iva_trasladado=round(sum(r.iva_trasladado for r in self.records), 2),
            total_iva_acreditable=round(sum(r.iva_acreditable for r in self.records), 2),
            por_tipo=por_tipo,
        )
        self.summary.diferencia_iva = round(
            self.summary.total_iva_trasladado - self.summary.total_iva_acreditable, 2
        )
        return self.summary

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "client_rfc": self.client_rfc,
            "period": self.period_label,
            "year": self.period.year,
            "quarter": self.period.quarter,
            "status": self.status.value,
            "records": [r.to_dict() for r in self.records],
            "summary": self.summary.to_dict(),
        }
