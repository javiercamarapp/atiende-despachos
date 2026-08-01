# -*- coding: utf-8 -*-
"""
base.py — Interfaz común de proveedores de pago + modo mock.

Todos los proveedores (Stripe, Conekta) implementan la misma interfaz
`PaymentProvider`. Esto permite cambiar de proveedor sin tocar la capa de
API: el router de billing recibe un proveedor inyectado (ver api.py).

Modo mock: cuando `B2B_PAYMENTS_MOCK=1` (o `mock=True`), los proveedores NO
hacen llamadas de red. Devuelven resultados deterministas con ids opacos
(`cus_mock_1`, `sub_mock_1`, etc.). Esto permite tests unitarios y la
demo sin credenciales reales. Es la base de los "Mock tests" del ticket.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional

from b2b_ai.billing.models import (
    Customer,
    Invoice,
    PaymentMethod,
    PaymentResult,
    PaymentMethodType,
    Provider,
    Subscription,
    SubscriptionStatus,
)

# Prefijos de ids opacos que usan los proveedores en modo mock.
_MOCK_IDS = {
    "customer": 0,
    "subscription": 0,
    "invoice": 0,
    "payment": 0,
    "payment_method": 0,
    "checkout": 0,
}


def _next_mock_id(kind: str) -> str:
    """Devuelve el siguiente id mock (`cus_1`, `cus_2`, ...)."""
    _MOCK_IDS[kind] += 1
    return f"{kind}_{_MOCK_IDS[kind]}"


def mock_mode_enabled() -> bool:
    """True si el modo mock está activo (B2B_PAYMENTS_MOCK=1)."""
    return os.environ.get("B2B_PAYMENTS_MOCK", "").strip() == "1"


class PaymentError(Exception):
    """Error de pago lanzado por un proveedor (rechazo, red, config)."""

    def __init__(self, message: str, provider: Provider, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.code = code or "payment_error"


class PaymentProvider(ABC):
    """Contrato común de un proveedor de pagos.

    Todos los métodos son síncronos por simplicidad del MVP; en producción
    con mucha carga conviene pasar los de red a `run_in_executor`/async.
    """

    provider: Provider

    @abstractmethod
    def create_customer(self, email: str, name: str) -> Customer:
        """Crea un cliente en el proveedor. Devuelve Customer con el
        `provider_customer_id` asignado."""

    @abstractmethod
    def create_subscription(self, customer_id: str, price_id: str,
                            payment_method_id: Optional[str] = None) -> Subscription:
        """Crea una suscripción para un cliente del proveedor."""

    @abstractmethod
    def create_invoice(self, customer_id: str, amount: float,
                       currency: str = "MXN") -> Invoice:
        """Crea/cobra una factura al cliente del proveedor."""

    @abstractmethod
    def process_payment(self, payment_method_id: str, amount: float,
                        currency: str = "MXN") -> PaymentResult:
        """Procesa un cargo único contra un método de pago."""

    @abstractmethod
    def webhook_handler(self, event_type: str, data: dict) -> dict:
        """Procesa un evento de webhook del proveedor y devuelve un resumen
        normalizado de lo que se hizo con él."""


class MockPaymentProvider(PaymentProvider):
    """Proveedor simulacro sin red. Se usa en tests y demos.

    No requiere API keys. Devuelve resultados deterministas con ids mock.
    Sirve de referencia del contrato que implementan los proveedores reales
    y como inyección por defecto en el router cuando no hay credenciales.
    """

    provider = Provider.STRIPE

    def __init__(self, provider: Provider = Provider.STRIPE):
        self.provider = provider

    def create_customer(self, email: str, name: str) -> Customer:
        return Customer(
            email=email,
            name=name,
            provider=self.provider,
            provider_customer_id=_next_mock_id("customer"),
        )

    def create_subscription(self, customer_id: str, price_id: str,
                            payment_method_id: Optional[str] = None) -> Subscription:
        return Subscription(
            customer_id=0,  # el router lo sobrescribe con el id local
            plan=price_id,
            provider=self.provider,
            provider_subscription_id=_next_mock_id("subscription"),
            status=SubscriptionStatus.ACTIVE,
            current_period_start="2026-08-01T00:00:00",
            current_period_end="2026-09-01T00:00:00",
        )

    def create_invoice(self, customer_id: str, amount: float,
                       currency: str = "MXN") -> Invoice:
        return Invoice(
            customer_id=0,
            amount=amount,
            currency=currency,
            provider=self.provider,
            provider_invoice_id=_next_mock_id("invoice"),
            status="open",
        )

    def process_payment(self, payment_method_id: str, amount: float,
                        currency: str = "MXN") -> PaymentResult:
        return PaymentResult(
            ok=True,
            provider=self.provider,
            reference=_next_mock_id("payment"),
            status="succeeded",
            amount=amount,
            currency=currency,
            payment_method_type=PaymentMethodType.CARD,
            message="Pago procesado (mock).",
        )

    def webhook_handler(self, event_type: str, data: dict) -> dict:
        return {
            "provider": self.provider.value,
            "event_type": event_type,
            "handled": True,
            "summary": f"Evento mock procesado: {event_type}",
        }


def get_default_provider() -> PaymentProvider:
    """Devuelve un proveedor por defecto según la config.

    Reglas (por orden):
      1. Si B2B_PAYMENTS_MOCK=1  → MockPaymentProvider.
      2. Si B2B_PAYMENTS_PROVIDER=conekta y hay B2B_CONEXTA_KEY → Conekta.
      3. Si hay B2B_STRIPE_KEY → Stripe.
      4. Fallback → MockPaymentProvider (demo segura, sin credenciales).
    """
    if mock_mode_enabled():
        return MockPaymentProvider()

    # Import local para evitar ciclos y coste de import si no se usa.
    if os.environ.get("B2B_PAYMENTS_PROVIDER", "").strip() == "conekta":
        from b2b_ai.billing.conekta_provider import ConektaProvider
        return ConektaProvider()

    if os.environ.get("B2B_STRIPE_KEY", "").strip():
        from b2b_ai.billing.stripe_provider import StripeProvider
        return StripeProvider()

    return MockPaymentProvider()
