"""Módulo de integración de Pagos — Stripe, Conekta, PayPal, Kushki, MercadoPago, OpenPay."""
from b2b_ai.integrations.pagos.adapter import PaymentAdapter, PaymentAdapterError
from b2b_ai.integrations.pagos.stripe_adapter import StripeAdapter
from b2b_ai.integrations.pagos.conekta_adapter import ConektaAdapter
from b2b_ai.integrations.pagos.kushki_adapter import KushkiAdapter
from b2b_ai.integrations.pagos.mercadopago_adapter import MercadoPagoAdapter
from b2b_ai.integrations.pagos.paypal_adapter import PayPalAdapter
from b2b_ai.integrations.pagos.openpay_adapter import OpenPayAdapter
from b2b_ai.integrations.pagos.models import (
    Currency, Payment, PaymentConfig, PaymentMethod, PaymentRequest, PaymentStatus,
    Refund, RefundRequest, Transaction,
)

__all__ = [
    "PaymentAdapter", "PaymentAdapterError",
    "StripeAdapter", "ConektaAdapter", "KushkiAdapter", "MercadoPagoAdapter",
    "PayPalAdapter", "OpenPayAdapter",
    "Currency", "Payment", "PaymentConfig", "PaymentMethod", "PaymentRequest",
    "PaymentStatus", "Refund", "RefundRequest", "Transaction",
]
