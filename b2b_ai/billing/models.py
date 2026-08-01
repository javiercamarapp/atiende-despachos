# -*- coding: utf-8 -*-
"""
models.py — Modelos de datos del subsistema de cobros (billing).

Define las entidades de negocio de facturación como modelos Pydantic v2
para que se puedan usar tanto en la capa de proveedores (Stripe/Conekta)
como en los schemas de la API y en la capa de datos. Son independientes
del backend de pagos: un mismo `Customer` vale para Stripe (EE. UU.) o
para Conekta (México).

Entidades:
    Customer       — cliente que paga (mail, nombre, id del proveedor).
    Subscription   — suscripción a un plan (Starter/Growth/Enterprise).
    Invoice        — factura/cobro emitido (amount, status, paid_at).
    PaymentMethod  — método de pago (tarjeta, SPEI, OXXO).

Los `provider_*` ids guardan la referencia opaca que el proveedor devuelve
al crear el recurso (p. ej. `cus_xxx` en Stripe, `cus_yyy` en Conekta).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import List, Optional

from pydantic import BaseModel, Field

# Validador ligero de email (evita depender de email-validator). Se aplica
# en los campos de tipo `email` de los modelos de billing.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailField(str):
    """Cadena con validación básica de formato email en Pydantic v2."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        from pydantic_core import core_schema
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def _validate(cls, v):
        if not isinstance(v, str) or not _EMAIL_RE.match(v):
            raise ValueError("Formato de email inválido")
        return v


class Provider(str, Enum):
    """Proveedor de pagos soportado por el sistema."""
    STRIPE = "stripe"
    CONEKTA = "conekta"


class PaymentMethodType(str, Enum):
    """Tipos de método de pago soportados (Conekta amplía con MX)."""
    CARD = "card"
    SPEI = "spei"
    OXXO = "oxxo"
    CASH = "cash"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    UNPAID = "unpaid"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class Customer(BaseModel):
    """Cliente que factura. `provider_customer_id` es la referencia opaca
    que el proveedor de pagos asigna (p. ej. `cus_...` en Stripe)."""
    id: Optional[int] = None            # id local (DB)
    tenant_id: Optional[int] = None     # aislamiento multi-tenant
    email: EmailField
    name: str
    provider: Provider = Provider.STRIPE
    provider_customer_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Subscription(BaseModel):
    """Suscripción de un cliente a un plan."""
    id: Optional[int] = None
    customer_id: int
    plan: str                            # 'starter' | 'growth' | 'enterprise'
    provider: Provider = Provider.STRIPE
    provider_subscription_id: Optional[str] = None
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_period_start: Optional[str] = None   # ISO 8601
    current_period_end: Optional[str] = None     # ISO 8601
    created_at: Optional[datetime] = None


class Invoice(BaseModel):
    """Cobro emitido a un cliente."""
    id: Optional[int] = None
    customer_id: int
    amount: float                         # en MXN (moneda principal del producto)
    currency: str = "MXN"
    status: InvoiceStatus = InvoiceStatus.OPEN
    provider: Provider = Provider.STRIPE
    provider_invoice_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PaymentMethod(BaseModel):
    """Método de pago de un cliente (tarjeta, SPEI u OXXO)."""
    id: Optional[int] = None
    customer_id: int
    type: PaymentMethodType = PaymentMethodType.CARD
    provider: Provider = Provider.STRIPE
    provider_payment_method_id: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    created_at: Optional[datetime] = None


class PaymentResult(BaseModel):
    """Resultado normalizado de una operación de pago / checkout."""
    ok: bool
    provider: Provider
    reference: Optional[str] = None      # id del pago/intent en el proveedor
    status: str = "succeeded"
    amount: Optional[float] = None
    currency: str = "MXN"
    payment_method_type: Optional[PaymentMethodType] = None
    message: str = ""
    # Para SPEI / OXXO (Conekta), el proveedor devuelve instrucciones de pago
    # (clabe / referencia + vencimiento) que el cliente necesita ver.
    payment_instructions: Optional[dict] = None


class CheckoutRequest(BaseModel):
    """Cuerpo del POST /api/v1/billing/checkout."""
    email: EmailField
    name: str
    plan: str = "growth"
    payment_method_type: PaymentMethodType = PaymentMethodType.CARD
    payment_method_id: Optional[str] = None
    provider: Provider = Provider.STRIPE
    currency: str = "MXN"


class WebhookPayload(BaseModel):
    """Envoltorio genérico para eventos de webhook de proveedores."""
    provider: Provider
    event_type: str
    data: dict = Field(default_factory=dict)


def list_payment_method_types() -> List[str]:
    """Devuelve los tipos de método de pago soportados (para el OpenAPI)."""
    return [t.value for t in PaymentMethodType]
