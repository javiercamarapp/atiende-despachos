# -*- coding: utf-8 -*-
"""Módulo de integración de Pagos — Stripe, Conekta, PayPal."""

from b2b_ai.integrations.pagos.adapter import PaymentAdapter, PaymentAdapterError
from b2b_ai.integrations.pagos.stripe_adapter import StripeAdapter
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
