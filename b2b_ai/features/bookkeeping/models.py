# -*- coding: utf-8 -*-
"""models.py — Data models for the Bookkeeping Agent (Agente 5).

Covers the full pipeline: CFDI classification, journal entries, ERP
registration, overrides, and pipeline orchestration.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# ---------------------------------------------------------------------------# Enums# ---------------------------------------------------------------------------#

class CFDICategory(str, Enum):
    """Common CFDI expense/income categories."""
    SERVICIOS_PROFESIONALES = "servicios_profesionales"
    RENTA_OFICINA = "renta_oficina"
    MATERIA_PRIMA = "materia_prima"
    PAPELERIA = "papeleria"
    PUBLICIDAD = "publicidad"
    HONORARIOS_LEGALES = "honorarios_legales"
    COMISION_BANCARIA = "comision_bancaria"
    INTERESES_BANCARIOS = "intereses_bancarios"
    VENTA_SERVICIOS = "venta_servicios"
    VENTA_MERCANCIA = "venta_mercancia"
    NOMINA = "nomina"
    ARRENDAMIENTO = "arrendamiento"
    SEGUROS = "seguros"
    TELEFONIA = "telefonia"
    TRANSPORTE = "transporte"
    EQUIPO_COMPUTO = "equipo_computo"
    MANTENIMIENTO = "mantenimiento"
    OTROS = "otros"


class PolizaType(str, Enum):
    """Journal entry types per NIF."""
    INGRESO = "ingreso"
    EGRESO = "egreso"
    DIARIO = "diario"


class PipelineStage(str, Enum):
    """Stages of the bookkeeping pipeline."""
    PENDING = "pending"
    CLASSIFYING = "classifying"
    GENERATING_POLIZA = "generating_poliza"
    REGISTERING_ERP = "registering_erp"
    RECONCILING = "reconciling"
    CLOSING = "closing"
    DECLARING = "declaring"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_OVERRIDE = "needs_override"


class OverrideAction(str, Enum):
    """Types of human overrides."""
    RECLASSIFY = "reclassify"
    APPROVE = "approve"
    REJECT = "reject"
    EDIT_POLIZA = "edit_poliza"


class ERPSystem(str, Enum):
    """Supported ERP systems."""
    CONTPAQI = "contpaqi"
    ASPEL = "aspel"
    SAP_B1 = "sap_b1"
    QUICKBOOKS = "quickbooks"
    ODOO = "odoo"
    MOCK = "mock"


# ---------------------------------------------------------------------------#
# Core models
# ---------------------------------------------------------------------------#

class CFDIClassification(BaseModel):
    """Result of classifying a CFDI."""
    cfdi_uuid: str = Field(..., description="CFDI UUID (Folio Fiscal)")
    rfc_emisor: str = Field(default="", description="Issuer RFC")
    rfc_receptor: str = Field(default="", description="Receiver RFC")
    descripcion: str = Field(default="", description="CFDI concept description")
    subtotal: float = Field(default=0.0, description="Subtotal amount")
    iva: float = Field(default=0.0, description="IVA amount")
    total: float = Field(default=0.0, description="Total amount")
    tasa_iva: float = Field(default=0.16, description="IVA rate")
    tipo_cfdi: str = Field(default="I", description="I=Ingreso, E=Egreso, T=Traslado, P=Pago")
    uso_cfdi: str = Field(default="", description="CFDI use code")
    regimen_emisor: str = Field(default="", description="Issuer tax regime")
    categoria: str = Field(default="otros", description="Assigned category")
    confidence: float = Field(default=0.0, description="Classification confidence 0-1")
    cuenta_cargo: str = Field(default="", description="Debit account SAT code")
    cuenta_abono: str = Field(default="", description="Credit account SAT code")
    needs_human_review: bool = Field(default=False, description="Flag if low confidence")


class LineaPoliza(BaseModel):
    """A single line in a journal entry."""
    cuenta: str = Field(..., description="SAT account code (6 digits)")
    concepto: str = Field(default="", description="Description")
    debe: float = Field(default=0.0, description="Debit amount")
    haber: float = Field(default=0.0, description="Credit amount")
    tipo: str = Field(default="cargo", description="cargo or abono")


class PolizaContable(BaseModel):
    """A complete journal entry (póliza contable)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    tipo: PolizaType = Field(default=PolizaType.DIARIO)
    fecha: str = Field(..., description="Date YYYY-MM-DD")
    concepto: str = Field(default="", description="Journal entry description")
    referencia: str = Field(default="", description="Reference (CFDI UUID, etc.)")
    lineas: List[LineaPoliza] = Field(default_factory=list)
    total_debe: float = Field(default=0.0)
    total_haber: float = Field(default=0.0)
    cuadrada: bool = Field(default=False, description="Is balanced (debe==haber)")
    erp_registered: bool = Field(default=False)
    erp_reference: Optional[str] = Field(default=None)
    tenant_id: str = Field(default="")


class OverrideRecord(BaseModel):
    """Record of a human override/correction."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    cfdi_uuid: str = Field(..., description="CFDI being corrected")
    action: OverrideAction
    original_categoria: str = Field(default="")
    new_categoria: str = Field(default="")
    new_cuenta_cargo: str = Field(default="")
    new_cuenta_abono: str = Field(default="")
    reason: str = Field(default="")
    corrected_by: str = Field(default="", description="User who made the correction")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tenant_id: str = Field(default="")


class PipelineJob(BaseModel):
    """Tracks the state of a bookkeeping pipeline execution."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    tenant_id: str = Field(default="")

    # Input
    cfdi_uuids: List[str] = Field(default_factory=list)
    periodo: str = Field(default="", description="Period YYYY-MM")

    # State
    stage: PipelineStage = Field(default=PipelineStage.PENDING)
    progress_pct: float = Field(default=0.0)

    # Results
    classifications: List[CFDIClassification] = Field(default_factory=list)
    polizas: List[PolizaContable] = Field(default_factory=list)
    erp_references: List[str] = Field(default_factory=list)
    overrides_needed: int = Field(default=0)

    # Error tracking
    errors: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Suggestion(BaseModel):
    """A classification suggestion for the accountant to review."""
    cfdi_uuid: str
    descripcion: str
    suggested_categoria: str
    suggested_cuenta_cargo: str
    suggested_cuenta_abono: str
    confidence: float
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
