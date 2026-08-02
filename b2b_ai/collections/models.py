# -*- coding: utf-8 -*-
"""
models.py — Modelos Pydantic para el módulo de cobranza automatizada.

Define los schemas de request/response para los endpoints REST y los
webhooks de confirmación de pago. Multi-tenant: todos los responses llevan
tenant_id para aislamiento.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #

class CollectionsAnalyzeRequest(BaseModel):
    """Cartera pendiente para analizar (clasificar por antigüedad y score)."""
    invoices: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de facturas pendientes: [{factura_id, monto, "
                    "fecha_vencimiento, nombre_empresa}]"
    )
    sync: bool = Field(
        default=False,
        description="Si True, persiste la cartera en outstanding_invoices"
    )


class CollectionsSendReminderRequest(BaseModel):
    """Genera (y opcionalmente registra) un recordatorio de cobranza."""
    invoice: Dict[str, Any] = Field(
        ...,
        description="Datos de la factura: {factura_id, monto, "
                    "fecha_vencimiento, nombre_empresa}"
    )
    stage: str = Field(
        ...,
        description="Etapa: pre_vencimiento|vencimiento|recordatorio_formal|"
                    "segundo_recordatorio|escalamiento"
    )
    channel: str = Field(
        default="email",
        description="Canal: email o whatsapp"
    )
    record: bool = Field(
        default=True,
        description="Registrar el intento en collection_events"
    )


class CollectionsScheduleRequest(BaseModel):
    """Programa recordatorios automáticos para la cartera pendiente."""
    invoices: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Cartera de facturas pendientes"
    )
    auto_send: bool = Field(
        default=False,
        description="Si True, genera y registra los recordatorios según "
                    "el stage que corresponda a cada factura"
    )
    channels: List[str] = Field(
        default=["email"],
        description="Canales para los recordatorios (email, whatsapp)"
    )


class CollectionWebhookPayload(BaseModel):
    """Webhook de confirmación de pago desde gateway/ERP."""
    event_type: str = Field(
        ...,
        description="Tipo de evento: payment_received, payment_partial, "
                    "payment_rejected, payment_disputed"
    )
    invoice_id: str = Field(
        ...,
        description="ID de la factura"
    )
    tenant_id: Optional[int] = Field(
        default=None,
        description="Tenant (requerido en multi-tenant)"
    )
    amount: float = Field(
        default=0.0,
        description="Monto del pago recibido"
    )
    currency: str = Field(default="MXN")
    reference: str = Field(
        default="",
        description="Referencia del pago (SPEI, CLABE, etc.)"
    )
    paid_at: Optional[str] = Field(
        default=None,
        description="Fecha/hora del pago ISO 8601"
    )
    provider: str = Field(
        default="spei",
        description="Gateway: spei|stripe|conekta|manual"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Datos adicionales del webhook"
    )


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #

class AgingReportResponse(BaseModel):
    """Reporte de antigüedad de la cartera."""
    buckets: Dict[str, Dict[str, Any]] = Field(
        ...,
        description="Facturas agrupadas por bucket de antigüedad"
    )
    total_count: int
    total_monto: str
    invoices: List[Dict[str, Any]]
    tenant_id: Optional[int] = None


class ProjectionResponse(BaseModel):
    """Proyección de cobro esperado por score de cobrabilidad."""
    total_cartera: str
    total_esperado: str
    tasa_recuperacion_esperada: float
    por_bucket: Dict[str, Dict[str, str]]
    por_score: Dict[str, Dict[str, Any]]
    tenant_id: Optional[int] = None


class CollectionsSummaryResponse(BaseModel):
    """Resumen ejecutivo de cobranza."""
    total_cartera: str
    total_count: int
    total_esperado: str
    tasa_recuperacion_esperada: float
    por_antiguedad: Dict[str, Dict[str, Any]]
    alertas: List[str]
    top_montos: List[Dict[str, Any]]
    tenant_id: Optional[int] = None


class CollectionEventResponse(BaseModel):
    """Evento de cobranza registrado."""
    id: int
    tenant_id: Optional[int]
    factura_id: str
    tipo_recordatorio: str
    canal: str
    timestamp: Optional[str]
    respuesta: Optional[str]


class OutstandingInvoiceResponse(BaseModel):
    """Factura en la cartera de cuentas por cobrar."""
    id: int
    tenant_id: Optional[int]
    factura_id: str
    monto: float
    fecha_vencimiento: str
    dias_vencido: int
    score: float
    created_at: Optional[str]
    updated_at: Optional[str]
