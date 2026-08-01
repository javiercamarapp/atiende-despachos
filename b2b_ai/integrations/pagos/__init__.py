# -*- coding: utf-8 -*-
"""Módulo de integración de Pagos — Stripe, Conekta, PayPal."""

from b2b_ai.integrations.pagos.adapter import PaymentAdapter, PaymentAdapterError
from b2b_ai.integrations.pagos.stripe_adapter import StripeAdapter
from b2b_ai.integrations.pagos.conekta_adapter import ConektaAdapter
from b2b_ai.integrations.pagos.paypal_adapter import PayPalAdapter
from b2b_ai.integrations.pagos.kushki_adapter import KushkiAdapter
from b2b_ai.integrations.pagos.mercadopago_adapter import MercadoPagoAdapter
from b2b_ai.integrations.pagos.paypal_mexico_adapter import PayPalMexicoAdapter
from b2b_ai.integrations.pagos.models import (
    Currency,
    Payment,
    PaymentConfig,
    PaymentMethod,
    PaymentRequest,
    PaymentStatus,
    Refund,
    RefundRequest,
    Transaction,
)

__all__ = [
    "PaymentAdapter",
    "PaymentAdapterError",
    "StripeAdapter",
    "ConektaAdapter",
    "PayPalAdapter",
    "KushkiAdapter",
    "MercadoPagoAdapter",
    "PayPalMexicoAdapter",
    "Currency",
    "Payment",
    "PaymentConfig",
    "PaymentMethod",
    "PaymentRequest",
    "PaymentStatus",
    "Refund",
    "RefundRequest",
    "Transaction",
]
