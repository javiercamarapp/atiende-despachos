# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de pagos (Stripe, Conekta, PayPal).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PaymentStatus(str, Enum):
    """Estado de un pago."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentMethod(str, Enum):
    """Métodos de pago soportados."""
    CARD = "card"
    SPEI = "spei"
    OXXO = "oxxo"
    PAYPAL = "paypal"
    BANK_TRANSFER = "bank_transfer"


class Currency(str, Enum):
    """Monedas soportadas."""
    MXN = "MXN"
    USD = "USD"
    EUR = "EUR"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class PaymentConfig(BaseModel):
    """Configuración del adaptador de pagos."""
    provider: str = Field(..., description="Proveedor de pagos (stripe, conekta, paypal)")
    api_key: str = Field(default="", description="API key del proveedor")
    api_secret: str = Field(default="", description="API secret del proveedor")
    webhook_secret: Optional[str] = Field(default=None, description="Webhook signing secret")
    test_mode: bool = Field(default=True, description="Modo de pruebas")
    currency: Currency = Field(default=Currency.MXN, description="Moneda por defecto")
    timeout: int = Field(default=30, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class PaymentRequest(BaseModel):
    """Solicitud de creación de pago."""
    amount: float = Field(..., gt=0, description="Monto del pago")
    currency: Currency = Field(default=Currency.MXN, description="Moneda")
    method: PaymentMethod = Field(default=PaymentMethod.CARD, description="Método de pago")
    description: str = Field(default="", description="Descripción del pago")
    customer_id: Optional[str] = Field(default=None, description="ID del cliente")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos adicionales")


class Payment(BaseModel):
    """Pago registrado."""
    id: str = Field(default="", description="ID del pago")
    amount: float = Field(default=0.0, description="Monto")
    currency: Currency = Field(default=Currency.MXN, description="Moneda")
    status: PaymentStatus = Field(default=PaymentStatus.PENDING, description="Estado")
    method: PaymentMethod = Field(default=PaymentMethod.CARD, description="Método de pago")
    customer_id: Optional[str] = Field(default=None, description="ID del cliente")
    description: str = Field(default="", description="Descripción")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")
    created_at: str = Field(default="", description="Fecha de creación ISO")
    updated_at: str = Field(default="", description="Fecha de actualización ISO")


class RefundRequest(BaseModel):
    """Solicitud de reembolso."""
    payment_id: str = Field(..., description="ID del pago a reembolsar")
    amount: Optional[float] = Field(default=None, description="Monto a reembolsar (None = total)")
    reason: str = Field(default="", description="Motivo del reembolso")


class Refund(BaseModel):
    """Reembolso registrado."""
    id: str = Field(default="", description="ID del reembolso")
    payment_id: str = Field(default="", description="ID del pago original")
    amount: float = Field(default=0.0, description="Monto reembolsado")
    status: str = Field(default="pending", description="Estado del reembolso")
    reason: str = Field(default="", description="Motivo")
    created_at: str = Field(default="", description="Fecha de creación")


class Transaction(BaseModel):
    """Transacción en el historial."""
    id: str = Field(default="", description="ID de la transacción")
    type: str = Field(default="payment", description="Tipo (payment, refund, chargeback)")
    amount: float = Field(default=0.0, description="Monto")
    currency: Currency = Field(default=Currency.MXN, description="Moneda")
    status: PaymentStatus = Field(default=PaymentStatus.SUCCEEDED, description="Estado")
    description: str = Field(default="", description="Descripción")
    created_at: str = Field(default="", description="Fecha ISO")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")
