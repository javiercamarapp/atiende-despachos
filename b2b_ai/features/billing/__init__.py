# -*- coding: utf-8 -*-
"""billing — Módulo de cobros por suscripción (checkout + billing) con Conekta.

Integra el gateway de pagos mexicano Conekta para el checkout y el billing
por suscripción del piloto de Likida AI.

Expone:
  - PlanCode, BillingCycle, Plan, get_plan, list_plans — planes y pricing
  - SubscriptionStatus, InvoiceStatus, PaymentMethodType, PaymentEventType —
    enums de dominio
  - Subscription, Invoice, PaymentMethod, PaymentEvent — entidades
  - ConektaClient — wrapper de la API de Conekta (con modo mock sin red)
  - BillingService — lógica de negocio (trial, conversión, facturas, webhooks)
  - build_billing_router() — router FastAPI /api/v1/billing/*

Proveedor: Conekta (tarjetas, SPEI, OXXO). El billing es mensual en MXN.
"""
from __future__ import annotations

from b2b_ai.features.billing.models import (
    Invoice,
    InvoiceStatus,
    PaymentEvent,
    PaymentEventType,
    PaymentMethod,
    PaymentMethodType,
    Subscription,
    SubscriptionStatus,
    _reset_state,
)
from b2b_ai.features.billing.plans import (
    BillingCycle,
    Plan,
    PlanCode,
    get_plan,
    list_plans,
)
from b2b_ai.features.billing.conekta_client import (
    CONEKTA_API_BASE,
    ConektaAPIError,
    ConektaClient,
    ConektaEnvironment,
    ConektaWebhookError,
)
from b2b_ai.features.billing.service import (
    BillingError,
    BillingService,
    subscription_to_dict,
)
from b2b_ai.features.billing.routes import build_billing_router

__all__ = [
    "BillingCycle",
    "Plan",
    "PlanCode",
    "get_plan",
    "list_plans",
    "Subscription",
    "SubscriptionStatus",
    "Invoice",
    "InvoiceStatus",
    "PaymentMethod",
    "PaymentMethodType",
    "PaymentEvent",
    "PaymentEventType",
    "CONEKTA_API_BASE",
    "ConektaAPIError",
    "ConektaClient",
    "ConektaEnvironment",
    "ConektaWebhookError",
    "BillingError",
    "BillingService",
    "subscription_to_dict",
    "build_billing_router",
    "_reset_state",
]
