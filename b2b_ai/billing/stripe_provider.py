# -*- coding: utf-8 -*-
"""
stripe_provider.py — Proveedor de pagos Stripe (para EE. UU. / tarjetas).

Implementa la interfaz `PaymentProvider` (ver base.py) usando la REST API
de Stripe vía httpx. No depende del SDK oficial: usa los endpoints REST
estándar (`/v1/customers`, `/v1/subscriptions`, `/v1/invoices`,
`/v1/payment_intents`).

Config:
    B2B_STRIPE_KEY        clave secreta `sk_...` (o `sk_test_...`).
    B2B_PAYMENTS_MOCK=1   activa el modo mock (sin red, ver base.py).

En modo mock devuelve resultados deterministas; en modo real hace las
llamadas HTTP y traduce los objetos de Stripe a los modelos locales.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from b2b_ai.billing.base import (
    PaymentError,
    PaymentProvider,
    _next_mock_id,
    mock_mode_enabled,
)
from b2b_ai.billing.models import (
    Customer,
    Invoice,
    PaymentResult,
    PaymentMethodType,
    Provider,
    Subscription,
    SubscriptionStatus,
)

_STRIPE_API = "https://api.stripe.com"


class StripeProvider(PaymentProvider):
    """Cliente de la REST API de Stripe."""

    provider = Provider.STRIPE

    def __init__(self, api_key: Optional[str] = None, mock: Optional[bool] = None):
        self.api_key = api_key or os.environ.get("B2B_STRIPE_KEY", "")
        # mock: explícito > env. Los tests inyectan mock=True.
        self._mock = mock if mock is not None else mock_mode_enabled()

    # ---- helpers ---------------------------------------------------------
    def _headers(self) -> dict:
        if not self.api_key:
            raise PaymentError(
                "B2B_STRIPE_KEY no configurada para el proveedor Stripe.",
                self.provider, code="missing_api_key")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _post(self, path: str, data: dict) -> dict:
        try:
            r = httpx.post(f"{_STRIPE_API}{path}", data=data,
                           headers=self._headers(), timeout=30.0)
        except httpx.HTTPError as exc:
            raise PaymentError(f"Error de red con Stripe: {exc}",
                               self.provider, code="network")
        if r.status_code >= 400:
            msg = r.text[:300]
            code = None
            try:
                code = r.json().get("error", {}).get("code")
            except Exception:  # noqa: BLE001
                pass
            raise PaymentError(f"Stripe error {r.status_code}: {msg}",
                               self.provider, code=code)
        return r.json()

    # ---- interfaz --------------------------------------------------------
    def create_customer(self, email: str, name: str) -> Customer:
        if self._mock:
            return Customer(email=email, name=name, provider=self.provider,
                            provider_customer_id=_next_mock_id("customer"))
        body = self._post("/v1/customers", {"email": email, "name": name})
        return Customer(email=email, name=name, provider=self.provider,
                        provider_customer_id=body.get("id"))

    def create_subscription(self, customer_id: str, price_id: str,
                            payment_method_id: Optional[str] = None) -> Subscription:
        if self._mock:
            return Subscription(
                customer_id=0, plan=price_id, provider=self.provider,
                provider_subscription_id=_next_mock_id("subscription"),
                status=SubscriptionStatus.ACTIVE,
                current_period_start="2026-08-01T00:00:00",
                current_period_end="2026-09-01T00:00:00")
        data = {
            "customer": customer_id,
            "items[0][price]": price_id,
        }
        if payment_method_id:
            data["default_payment_method"] = payment_method_id
        body = self._post("/v1/subscriptions", data)
        status = SubscriptionStatus(body.get("status", "active"))
        period = (body.get("current_period") or {})
        return Subscription(
            customer_id=0, plan=price_id, provider=self.provider,
            provider_subscription_id=body.get("id"),
            status=status,
            current_period_start=str(period.get("start") or ""),
            current_period_end=str(period.get("end") or ""))

    def create_invoice(self, customer_id: str, amount: float,
                       currency: str = "MXN") -> Invoice:
        if self._mock:
            return Invoice(customer_id=0, amount=amount, currency=currency,
                           provider=self.provider,
                           provider_invoice_id=_next_mock_id("invoice"),
                           status="open")
        # Stripe crea facturas a partir de line items; para un cobro único
        # se crea el invoice + line item + finaliza.
        inv = self._post("/v1/invoices", {"customer": customer_id,
                                          "currency": currency.lower()})
        inv_id = inv.get("id")
        self._post("/v1/invoices/{id}/lines".format(id=inv_id), {
            "amount": int(round(amount * 100)), "currency": currency.lower(),
            "description": "Cargo Likida AI Enterprise"})
        self._post(f"/v1/invoices/{inv_id}/finalize", {})
        return Invoice(customer_id=0, amount=amount, currency=currency,
                       provider=self.provider, provider_invoice_id=inv_id,
                       status="open")

    def process_payment(self, payment_method_id: str, amount: float,
                        currency: str = "MXN") -> PaymentResult:
        if self._mock:
            return PaymentResult(ok=True, provider=self.provider,
                                 reference=_next_mock_id("payment"),
                                 status="succeeded", amount=amount,
                                 currency=currency,
                                 payment_method_type=PaymentMethodType.CARD,
                                 message="Pago procesado (mock).")
        pi = self._post("/v1/payment_intents", {
            "amount": int(round(amount * 100)),
            "currency": currency.lower(),
            "payment_method": payment_method_id,
            "confirm": "true",
        })
        return PaymentResult(
            ok=pi.get("status") == "succeeded", provider=self.provider,
            reference=pi.get("id"), status=pi.get("status", "unknown"),
            amount=amount, currency=currency,
            payment_method_type=PaymentMethodType.CARD,
            message=pi.get("status", ""))

    def webhook_handler(self, event_type: str, data: dict) -> dict:
        """Traduce un evento de Stripe a un resumen normalizado.

        En producción la firma del webhook se debe verificar con el header
        `Stripe-Signature` (vía la librería `stripe`) antes de confiar en el
        payload; aquí se procesa el tipo de evento y se extrae el recurso.
        """
        resource = data.get("data", {}).get("object", {}) if isinstance(
            data, dict) else {}
        summary = {
            "customer_id": resource.get("customer"),
            "invoice_id": resource.get("invoice") or resource.get("id"),
            "amount": resource.get("amount"),
            "status": resource.get("status"),
        }
        if event_type.startswith("invoice.paid"):
            return {"provider": self.provider.value, "event_type": event_type,
                    "handled": True, "mark_paid": True, **summary}
        if event_type.startswith("invoice."):
            return {"provider": self.provider.value, "event_type": event_type,
                    "handled": True, "mark_paid": False, **summary}
        if event_type.startswith("customer.subscription."):
            return {"provider": self.provider.value, "event_type": event_type,
                    "handled": True, "mark_paid": False, **summary}
        return {"provider": self.provider.value, "event_type": event_type,
                "handled": False, "reason": "evento sin manejo específico"}
