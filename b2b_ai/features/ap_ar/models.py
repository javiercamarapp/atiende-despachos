# -*- coding: utf-8 -*-
"""
models.py — Pydantic models for AP/AR End-to-End (Agente 4).

Data models for:
  - AP invoices (cuentas por pagar)
  - AR invoices (cuentas por cobrar)
  - Aging buckets
  - Payment orders (SPEI)
  - Credit notes (notas de crédito)
  - Retentions
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class InvoiceStatus(str, Enum):
    """Status of an AP/AR invoice."""
    PENDING = "pendiente"
    VALIDATED = "validada"
    REGISTERED = "registrada"
    SCHEDULED = "programada"
    PAID = "pagada"
    PARTIAL = "parcial"
    OVERDUE = "vencida"
    CANCELLED = "cancelada"
    COLLECTED = "cobrada"


class PaymentMethod(str, Enum):
    """CFDI payment methods."""
    PUE = "PUE"  # Pago en una sola exhibición
    PPD = "PPD"  # Pago en parcialidades o diferido


class AgingBucket(str, Enum):
    """Aging buckets for AP/AR."""
    CURRENT = "0-30"
    DAYS_31_60 = "31-60"
    DAYS_61_90 = "61-90"
    DAYS_90_PLUS = "90+"


class CreditNoteType(str, Enum):
    """Types of credit notes."""
    DEVOLUCION = "devolucion"
    DESCUENTO = "descuento"
    BONIFICACION = "bonificacion"


class RetentionType(str, Enum):
    """ISR retention types per LISR Art. 94-100."""
    ARRENDAMIENTO_PF = "arrendamiento_pf"
    HONORARIOS_PF = "honorarios_pf"
    SERVICIOS_PROFESIONALES = "servicios_profesionales"
    REGALIAS_NACIONAL = "regalias_nacional"
    REGALIAS_EXTRANJERO = "regalias_extranjero"
    SUBCONTRATACION = "subcontratacion"


# ---------------------------------------------------------------------------
# AP Invoice
# ---------------------------------------------------------------------------

class APInvoice(BaseModel):
    """Accounts Payable invoice (cuenta por pagar)."""
    id: Optional[int] = None
    tenant_id: Optional[int] = None
    uuid: str = Field(..., description="CFDI UUID")
    rfc_emisor: str = Field(..., description="Supplier RFC")
    nombre_emisor: str = Field(default="", description="Supplier name")
    rfc_receptor: str = Field(default="", description="Company RFC")
    subtotal: float = Field(..., ge=0)
    iva: float = Field(default=0.0, ge=0)
    total: float = Field(..., ge=0)
    fecha_emision: str = Field(..., description="Issue date YYYY-MM-DD")
    fecha_vencimiento: str = Field(..., description="Due date YYYY-MM-DD")
    metodo_pago: str = Field(default="PUE")
    forma_pago: str = Field(default="03")  # Transferencia electrónica
    status: InvoiceStatus = Field(default=InvoiceStatus.PENDING)
    monto_pagado: float = Field(default=0.0, ge=0)
    retencion_isr: float = Field(default=0.0, ge=0)
    concepto: str = Field(default="")
    cuenta_contable: str = Field(default="")
    notas: str = Field(default="")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class APInvoiceCreate(BaseModel):
    """Schema to create an AP invoice."""
    uuid: str
    rfc_emisor: str
    nombre_emisor: str = ""
    rfc_receptor: str = ""
    subtotal: float
    iva: float = 0.0
    total: float
    fecha_emision: str
    fecha_vencimiento: str
    metodo_pago: str = "PUE"
    forma_pago: str = "03"
    concepto: str = ""
    cuenta_contable: str = ""


# ---------------------------------------------------------------------------
# AR Invoice
# ---------------------------------------------------------------------------

class ARInvoice(BaseModel):
    """Accounts Receivable invoice (cuenta por cobrar)."""
    id: Optional[int] = None
    tenant_id: Optional[int] = None
    uuid: str = Field(..., description="CFDI UUID")
    rfc_emisor: str = Field(default="", description="Company RFC")
    rfc_receptor: str = Field(..., description="Client RFC")
    nombre_receptor: str = Field(default="", description="Client name")
    subtotal: float = Field(..., ge=0)
    iva: float = Field(default=0.0, ge=0)
    total: float = Field(..., ge=0)
    fecha_emision: str = Field(..., description="Issue date YYYY-MM-DD")
    fecha_vencimiento: str = Field(..., description="Due date YYYY-MM-DD")
    metodo_pago: str = Field(default="PUE")
    status: InvoiceStatus = Field(default=InvoiceStatus.PENDING)
    monto_cobrado: float = Field(default=0.0, ge=0)
    concepto: str = Field(default="")
    notas: str = Field(default="")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ARInvoiceCreate(BaseModel):
    """Schema to create an AR invoice."""
    uuid: str
    rfc_receptor: str
    nombre_receptor: str = ""
    rfc_emisor: str = ""
    subtotal: float
    iva: float = 0.0
    total: float
    fecha_emision: str
    fecha_vencimiento: str
    metodo_pago: str = "PUE"
    concepto: str = ""


# ---------------------------------------------------------------------------
# Aging Report
# ---------------------------------------------------------------------------

class AgingBucketData(BaseModel):
    """Data for a single aging bucket."""
    bucket: str
    count: int = 0
    monto: float = 0.0
    dias_promedio: float = 0.0


class AgingReport(BaseModel):
    """Aging report for AP or AR."""
    tipo: str = Field(..., description="'ap' or 'ar'")
    tenant_id: Optional[int] = None
    buckets: List[AgingBucketData] = Field(default_factory=list)
    total_facturas: int = 0
    total_monto: float = 0.0
    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


class AgingEntry(BaseModel):
    """Single entity (supplier/client) aging detail."""
    rfc: str
    nombre: str
    bucket_0_30: float = 0.0
    bucket_31_60: float = 0.0
    bucket_61_90: float = 0.0
    bucket_90_plus: float = 0.0
    total: float = 0.0


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class PaymentOrder(BaseModel):
    """A payment order for SPEI."""
    id: Optional[int] = None
    tenant_id: Optional[int] = None
    ap_invoice_id: Optional[int] = None
    clave_rastreo: str = Field(default="", description="SPEI tracking key")
    concepto_pago: str = Field(default="")
    cuenta_beneficiario: str = Field(..., description="CLABE beneficiario")
    cuenta_ordenante: str = Field(default="", description="CLABE ordenante")
    nombre_beneficiario: str = Field(default="")
    nombre_ordenante: str = Field(default="")
    rfc_beneficiario: str = Field(default="")
    rfc_ordenante: str = Field(default="")
    institucion_beneficiario: int = Field(default=0, description="SPEI bank code")
    institucion_ordenante: int = Field(default=0)
    empresa: str = Field(default="")
    monto: float = Field(..., gt=0)
    prioridad: int = Field(default=5, ge=1, le=10, description="1=highest")
    fecha_programada: str = Field(..., description="Scheduled date YYYY-MM-DD")
    status: str = Field(default="programado")
    stp_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None


class PaymentScheduleEntry(BaseModel):
    """A scheduled payment for the payment scheduler."""
    payment_order: PaymentOrder
    dias_para_vencimiento: int
    prioridad_efectiva: int


class CollectRequest(BaseModel):
    """Request to collect an AR invoice."""
    ar_invoice_id: int
    monto: float = Field(..., gt=0)
    fecha_cobro: str = Field(default_factory=lambda: date.today().isoformat())
    generar_complemento: bool = Field(default=False)


class CollectResult(BaseModel):
    """Result of an AR collection."""
    ar_invoice_id: int
    monto_cobrado: float
    nuevo_status: str
    complemento_generado: bool = False
    conekta_order_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Credit Notes
# ---------------------------------------------------------------------------

class CreditNoteCreate(BaseModel):
    """Schema to create a credit note."""
    cfdi_original_uuid: str
    monto: float = Field(..., gt=0)
    concepto: str
    tipo: CreditNoteType
    rfc_emisor: str = ""
    rfc_receptor: str = ""


class CreditNote(BaseModel):
    """A credit note (nota de crédito)."""
    id: Optional[int] = None
    tenant_id: Optional[int] = None
    uuid: Optional[str] = None
    cfdi_original_uuid: str
    monto: float
    concepto: str
    tipo: CreditNoteType
    rfc_emisor: str = ""
    rfc_receptor: str = ""
    status: str = Field(default="emitida")
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

class RetentionResult(BaseModel):
    """Result of a retention calculation."""
    proveedor_rfc: str
    tipo_retencion: Optional[RetentionType] = None
    tasa: float = 0.0
    fundamento: str = ""
    monto_factura: float = 0.0
    retencion: float = 0.0
    monto_neto: float = 0.0
    es_pf: bool = False
    aplica_retencion: bool = False
    motivo: str = ""
