# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Fiscal Conciliation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent ERP vs SAT comparisons, omissions, discrepancies,
and fiscal reports used by contadores in Mexico.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TipoOmicion(str, Enum):
    """Tipo de omisión fiscal detectada."""
    FACTURA_SAT = "factura_no_en_erp"      # Factura en SAT pero no en ERP
    FACTURA_ERP = "factura_no_en_sat"      # Factura en ERP pero no en SAT
    DECLARACION = "declaracion_faltante"    # Declaración no presentada
    PAGO = "pago_no_registrado"            # Pago no registrado
    AJUSTE = "ajuste_no_reflejado"        # Ajuste no reflejado


class TipoDiscrepancia(str, Enum):
    """Tipo de discrepancia fiscal."""
    MONTO = "monto_diferente"
    FECHA = "fecha_diferente"
    RFC = "rfc_diferente"
    CONCEPTO = "concepto_diferente"
    IVA = "iva_diferente"
# ---------------------------------------------------------------------------
# Backward-compat enums used by tests and legacy service code
# ---------------------------------------------------------------------------

class DeclaracionTipo(str, Enum):
    """Tipo de declaración fiscal (used by ERP/SAT cross-reference)."""
    IVA = "iva"
    ISR = "isr"
    DIOT = "diot"
    CONTABILIDAD_ELECTRONICA = "contabilidad_electronica"


class DiscrepancySeverity(str, Enum):
    """Severity level for fiscal discrepancies."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ERPRecord(BaseModel):
    """A record from the ERP system for fiscal cross-reference."""
    id: str = Field(default="", description="ERP record identifier")
    concepto: str = Field(default="", description="Concept/type of record")
    monto: float = Field(default=0.0, ge=0, description="Amount in MXN")
    periodo: str = Field(default="", description="Period YYYY-MM")
    rfc: Optional[str] = Field(default=None, description="RFC associated")
    fecha: Optional[str] = Field(default=None, description="Date YYYY-MM-DD")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "ERP-001",
                "concepto": "iva",
                "monto": 50000.0,
                "periodo": "2026-06",
            }]
        }
    }


class SATRecord(BaseModel):
    """A record from SAT declarations for fiscal cross-reference."""
    id: str = Field(default="", description="SAT record identifier")
    tipo: DeclaracionTipo = Field(..., description="Declaration type")
    monto: float = Field(default=0.0, ge=0, description="Amount in MXN")
    periodo: str = Field(default="", description="Period YYYY-MM")
    rfc: Optional[str] = Field(default=None, description="RFC associated")
    fecha: Optional[str] = Field(default=None, description="Date YYYY-MM-DD")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "SAT-001",
                "tipo": "iva",
                "monto": 50000.0,
                "periodo": "2026-06",
            }]
        }
    }


# ---------------------------------------------------------------------------
# Omission schema
# ---------------------------------------------------------------------------
# Omission schema
# ---------------------------------------------------------------------------

class Omission(BaseModel):
    """Una omisión fiscal detectada entre ERP y SAT."""
    id: str = Field(default="", description="Identificador único de la omisión")
    tipo: TipoOmicion = Field(
        ...,
        description="Tipo de omisión",
    )
    periodo: str = Field(
        ...,
        description="Período de la omisión (YYYY-MM)",
    )
    monto: float = Field(
        default=0.0,
        description="Monto asociado a la omisión",
    )
    rfc: Optional[str] = Field(
        default=None,
        description="RFC relacionado (si aplica)",
    )
    uuid_cfdi: Optional[str] = Field(
        default=None,
        description="UUID del CFDI relacionado (si aplica)",
    )
    detalle: str = Field(
        default="",
        description="Detalle descriptivo de la omisión",
    )
    resuelta: bool = Field(
        default=False,
        description="Si la omisión ya fue resuelta",
    )


# ---------------------------------------------------------------------------
# Fiscal Discrepancy schema
# ---------------------------------------------------------------------------

class FiscalDiscrepancy(BaseModel):
    """Una discrepancia entre datos ERP y SAT."""
    id: str = Field(default="", description="Identificador único de la discrepancia")
    tipo: TipoDiscrepancia = Field(
        ...,
        description="Tipo de discrepancia",
    )
    erp_amount: float = Field(
        default=0.0,
        description="Monto registrado en ERP",
    )
    sat_amount: float = Field(
        default=0.0,
        description="Monto registrado en SAT",
    )
    diff: float = Field(
        default=0.0,
        description="Diferencia absoluta (ERP - SAT)",
    )
    explanation: str = Field(
        default="",
        description="Explicación o causa probable",
    )
    rfc: Optional[str] = Field(
        default=None,
        description="RFC relacionado",
    )
    periodo: Optional[str] = Field(
        default=None,
        description="Período (YYYY-MM)",
    )
    resuelta: bool = Field(
        default=False,
        description="Si la discrepancia ya fue resuelta",
    )


# ---------------------------------------------------------------------------
# Fiscal Comparison schema
# ---------------------------------------------------------------------------

class FiscalReport(BaseModel):
    """Reporte consolidado de conciliación fiscal."""
    id: str = Field(
        default="",
        description="ID del reporte",
    )
    referencia_legal: Optional[str] = Field(
        default=None,
        description="Referencia legal CFF Art. 89",
    )
    supuesto: Optional[str] = Field(
        default=None,
        description="Supuesto de aplicación",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Requiere revisión humana",
    )
    human_review_reason: Optional[str] = Field(
        default=None,
        description="Razón de revisión humana",
    )
    audit_trail: List[str] = Field(
        default_factory=list,
        description="Bitácora de acciones",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Clave de idempotencia",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )
    periodo: str = Field(
        default="",
        description="Período del reporte (YYYY-MM)",
    )
    erp_total: float = Field(
        default=0.0,
        description="Total declarado en ERP",
    )
    sat_total: float = Field(
        default=0.0,
        description="Total declarado en SAT",
    )
    diferencia: float = Field(
        default=0.0,
        description="Diferencia absoluta",
    )
    omisiones: List[Omission] = Field(
        default_factory=list,
        description="Omisiones detectadas",
    )
    discrepancias: List[FiscalDiscrepancy] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    comparison: Optional["FiscalComparison"] = Field(
        default=None,
        description="Comparación ERP vs SAT subyacente",
    )
    escalation_path: Optional[str] = Field(
        default=None,
        description="Ruta de escalamiento (review_by_contador, etc.)",
    )
    recomendaciones: List[str] = Field(
        default_factory=list,
        description="Recomendaciones generadas por el análisis",
    )
    total_omisiones: int = Field(
        default=0,
        description="Número total de omisiones",
    )
    total_discrepancias: int = Field(
        default=0,
        description="Número total de discrepancias",
    )
    monto_total_omisiones: float = Field(
        default=0.0,
        description="Monto total de omisiones",
    )
    monto_total_discrepancias: float = Field(
        default=0.0,
        description="Monto total de discrepancias",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Fecha de creación ISO format",
    )


class FiscalComparison(BaseModel):
    """Resultado de la comparación ERP vs SAT."""
    erp_total: float = Field(
        default=0.0,
        description="Total declarado en ERP",
    )
    sat_total: float = Field(
        default=0.0,
        description="Total declarado en SAT",
    )
    diferencia: float = Field(
        default=0.0,
        description="Diferencia absoluta (ERP - SAT)",
    )
    omisiones: List[Omission] = Field(
        default_factory=list,
        description="Omiciones detectadas",
    )
    discrepancias: List[FiscalDiscrepancy] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    periodo: str = Field(
        default="",
        description="Período comparado (YYYY-MM)",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant ID",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Fecha de creación ISO format",
    )


# ---------------------------------------------------------------------------
# Fiscal Report schema
# ---------------------------------------------------------------------------



# Add compliance fields to FiscalReport
FiscalReport.model_rebuild()
