# -*- coding: utf-8 -*-
"""models.py — Entidades de dominio del módulo de billing.

Define los cuatro tipos centrales del subsistema de cobros por suscripción:

    Subscription  — suscripción activa de un tenant (con su plan y ciclo).
    Invoice       — una factura emitida (periodo, monto, estado).
    PaymentMethod — un medio de pago registrado del cliente (tarjeta/SPEI/OXXO).
    PaymentEvent  — un evento de pago recibido del proveedor (webhook).

Sigue el patrón del proyecto (pydantic v2, Field con description, enums y
timestamps ISO UTC) usado por `bank_feeds`, `onboarding`, `batch`, etc.
El billing es por suscripción con Conekta como proveedor de pagos MX.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from b2b_ai.features.billing.plans import PlanCode


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SubscriptionStatus(str, Enum):
    """Ciclo de vida de una suscripción."""
    TRIALING = "trialing"            # piloto 30 días (sin cobro)
    ACTIVE = "active"                # pagando, al día
    PAST_DUE = "past_due"            # pago fallido, a la espera
    CANCELED = "canceled"            # cancelada
    UNPAID = "unpaid"                # sin poder cobrar, suspendida


class InvoiceStatus(str, Enum):
    """Estado de una factura."""
    OPEN = "open"                    # emitida, pendiente de pago
    PAID = "paid"                    # pagada
    VOID = "void"                    # cancelada/anulada
    PAST_DUE = "past_due"            # vencida sin pago


class PaymentMethodType(str, Enum):
    """Medios de pago soportados por Conekta."""
    CARD = "card"
    SPEI = "spei"
    OXXO = "oxxo"


class PaymentEventType(str, Enum):
    """Tipos de eventos de pago que el proveedor puede enviar."""
    PAYMENT_SUCCEEDED = "payment.succeeded"      # charge.paid / order.paid
    PAYMENT_FAILED = "payment.failed"            # charge.failed
    PAYMENT_PENDING = "payment.pending"          # spei/oxxo pending
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    SUBSCRIPTION_PAUSED = "subscription.paused"
    UNKNOWN = "unknown"


class Provider(str, Enum):
    """Proveedores de pago soportados."""
    CONEKTA = "conekta"


# ---------------------------------------------------------------------------
# Helpers de tiempo
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# Entidades
# ---------------------------------------------------------------------------

class Subscription(BaseModel):
    """Suscripción de un tenant a un plan de Likida AI."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno de la suscripción")
    tenant_id: str = Field(..., description="Tenant dueño de la suscripción")
    plan_code: PlanCode = Field(..., description="Plan contratado")
    provider: Provider = Field(default=Provider.CONEKTA,
                               description="Proveedor de pago")
    provider_customer_id: Optional[str] = Field(
        default=None, description="ID del cliente en Conekta")
    provider_subscription_id: Optional[str] = Field(
        default=None, description="ID de la suscripción en Conekta")
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.TRIALING, description="Estado de la suscripción")
    price_mxn: int = Field(0, ge=0, description="Precio mensual MXN")
    currency: str = Field("MXN", description="Moneda")
    trial_start: Optional[str] = Field(default=None, description="Inicio del trial ISO UTC")
    trial_end: Optional[str] = Field(default=None, description="Fin del trial ISO UTC")
    current_period_start: Optional[str] = Field(
        default=None, description="Inicio del periodo de cobro actual ISO UTC")
    current_period_end: Optional[str] = Field(
        default=None, description="Fin del periodo de cobro actual ISO UTC")
    created_at: str = Field(default_factory=_utcnow_iso, description="Fecha de creación ISO UTC")
    updated_at: Optional[str] = Field(default=None, description="Última actualización ISO UTC")
    canceled_at: Optional[str] = Field(default=None, description="Fecha de cancelación ISO UTC")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos extra")

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "plan_code": self.plan_code.value,
            "provider": self.provider.value,
            "provider_customer_id": self.provider_customer_id,
            "provider_subscription_id": self.provider_subscription_id,
            "status": self.status.value,
            "price_mxn": self.price_mxn,
            "currency": self.currency,
            "trial_start": self.trial_start,
            "trial_end": self.trial_end,
            "current_period_start": self.current_period_start,
            "current_period_end": self.current_period_end,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "canceled_at": self.canceled_at,
            "metadata": self.metadata,
        }


class Invoice(BaseModel):
    """Factura emitida para un tenant (periodo mensual)."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno de la factura")
    tenant_id: str = Field(..., description="Tenant al que se factura")
    subscription_id: str = Field(..., description="Suscripción que genera la factura")
    provider_invoice_id: Optional[str] = Field(
        default=None, description="ID de la factura en Conekta")
    amount_mxn: int = Field(0, ge=0, description="Monto de la factura en MXN")
    currency: str = Field("MXN", description="Moneda")
    status: InvoiceStatus = Field(default=InvoiceStatus.OPEN, description="Estado")
    period_start: Optional[str] = Field(default=None, description="Inicio del periodo ISO UTC")
    period_end: Optional[str] = Field(default=None, description="Fin del periodo ISO UTC")
    created_at: str = Field(default_factory=_utcnow_iso, description="Fecha de emisión ISO UTC")
    paid_at: Optional[str] = Field(default=None, description="Fecha de pago ISO UTC")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos extra")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "subscription_id": self.subscription_id,
            "provider_invoice_id": self.provider_invoice_id,
            "amount_mxn": self.amount_mxn,
            "currency": self.currency,
            "status": self.status.value,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "created_at": self.created_at,
            "paid_at": self.paid_at,
        }


class PaymentMethod(BaseModel):
    """Medio de pago registrado de un tenant en el proveedor."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno del método de pago")
    tenant_id: str = Field(..., description="Tenant dueño del método")
    provider_customer_id: Optional[str] = Field(
        default=None, description="ID del cliente en Conekta")
    provider_payment_method_id: Optional[str] = Field(
        default=None, description="ID del método en Conekta")
    method_type: PaymentMethodType = Field(..., description="Tipo (card/spei/oxxo)")
    last4: Optional[str] = Field(default=None, description="Últimos 4 dígitos (tarjeta)")
    brand: Optional[str] = Field(default=None, description="Marca (visa, mastercard, ...)")
    is_default: bool = Field(default=False, description="Si es el método por defecto")
    created_at: str = Field(default_factory=_utcnow_iso, description="Fecha de alta ISO UTC")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "provider_customer_id": self.provider_customer_id,
            "provider_payment_method_id": self.provider_payment_method_id,
            "method_type": self.method_type.value,
            "last4": self.last4,
            "brand": self.brand,
            "is_default": self.is_default,
            "created_at": self.created_at,
        }


class PaymentEvent(BaseModel):
    """Evento de pago recibido del proveedor (webhook), ya procesado."""
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()),
                    description="ID interno del evento")
    event_type: PaymentEventType = Field(..., description="Tipo de evento")
    provider_event_id: Optional[str] = Field(
        default=None, description="ID del evento en el proveedor")
    subscription_id: Optional[str] = Field(
        default=None, description="Suscripción asociada (si aplica)")
    tenant_id: Optional[str] = Field(
        default=None, description="Tenant asociado (si aplica)")
    payload: Dict[str, Any] = Field(default_factory=dict,
                                    description="Payload crudo del evento")
    processed_at: str = Field(default_factory=_utcnow_iso,
                              description="Fecha de procesamiento ISO UTC")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "provider_event_id": self.provider_event_id,
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "processed_at": self.processed_at,
        }


# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / onboarding)
# ---------------------------------------------------------------------------

# tenant_id -> Subscription activa
_subscriptions: Dict[str, Subscription] = {}
# subscription_id -> lista de Invoice (más reciente primero)
_invoices: Dict[str, List[Invoice]] = {}
# tenant_id -> lista de PaymentMethod
_payment_methods: Dict[str, List[PaymentMethod]] = {}
# lista global de PaymentEvent
_payment_events: List[PaymentEvent] = []
# subscription_id -> Subscription (por ID, para lookup directo)
_subscriptions_by_id: Dict[str, Subscription] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _subscriptions.clear()
    _invoices.clear()
    _payment_methods.clear()
    _payment_events.clear()
    _subscriptions_by_id.clear()


def save_subscription(sub: Subscription) -> Subscription:
    sub.touch()
    _subscriptions[sub.tenant_id] = sub
    _subscriptions_by_id[sub.id] = sub
    return sub


def get_subscription_by_tenant(tenant_id: str) -> Optional[Subscription]:
    return _subscriptions.get(tenant_id)


def get_subscription_by_id(subscription_id: str) -> Optional[Subscription]:
    return _subscriptions_by_id.get(subscription_id)


def add_invoice(invoice: Invoice) -> Invoice:
    lst = _invoices.setdefault(invoice.subscription_id, [])
    lst.insert(0, invoice)
    return invoice


def get_invoices(subscription_id: str) -> List[Invoice]:
    return list(_invoices.get(subscription_id, []))


def add_payment_method(pm: PaymentMethod) -> PaymentMethod:
    lst = _payment_methods.setdefault(pm.tenant_id, [])
    lst.append(pm)
    return pm


def get_payment_methods(tenant_id: str) -> List[PaymentMethod]:
    return list(_payment_methods.get(tenant_id, []))


def add_payment_event(event: PaymentEvent) -> PaymentEvent:
    _payment_events.append(event)
    return event


def get_payment_events(limit: int = 100) -> List[PaymentEvent]:
    return list(reversed(_payment_events[-limit:]))
