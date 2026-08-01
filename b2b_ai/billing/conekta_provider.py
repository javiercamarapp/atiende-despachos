# -*- coding: utf-8 -*-
"""
conekta_provider.py — Proveedor de pagos Conekta (para México).

Implementa la misma interfaz `PaymentProvider` que Stripe (base.py) y añade
soporte para los métodos de pago mexicanos: tarjeta, SPEI y OXXO. Conekta
es el proveedor recomendado para facturar en MXN dentro del país.

Config:
    B2B_CONEKTA_KEY       clave privada `key_...`.
    B2B_PAYMENTS_PROVIDER=conekta   usa Conekta por defecto.
    B2B_PAYMENTS_MOCK=1   modo mock (sin red).

Para SPEI y OXXO, `process_payment` devuelve `payment_instructions` con la
CLABE interbancaria (SPEI) o la referencia + vencimiento (OXXO) que el
cliente necesita para completar el pago.
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
    PaymentMethodType,
    PaymentResult,
    Provider,
    Subscription,
    SubscriptionStatus,
)

_CONEKTA_API = "https://api.conekta.io"


class ConektaProvider(PaymentProvider):
    """Cliente de la REST API de Conekta (api_key_private, API v2)."""

    provider = Provider.CONEKTA

    # Tipos de pago que Conekta soporta de forma nativa.
    SUPPORTED_METHODS = {t.value for t in PaymentMethodType}

    def __init__(self, api_key: Optional[str] = None, mock: Optional[bool] = None):
        self.api_key = api_key or os.environ.get("B2B_CONEKTA_KEY", "")
        self._mock = mock if mock is not None else mock_mode_enabled()

    # ---- helpers ---------------------------------------------------------
    def _headers(self) -> dict:
        if not self.api_key:
            raise PaymentError(
                "B2B_CONEKTA_KEY no configurada para el proveedor Conekta.",
                self.provider, code="missing_api_key")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.conekta-v2.1.0+json",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = httpx.post(f"{_CONEKTA_API}{path}", json=payload,
                           headers=self._headers(), timeout=30.0)
        except httpx.HTTPError as exc:
            raise PaymentError(f"Error de red con Conekta: {exc}",
                               self.provider, code="network")
        if r.status_code >= 400:
            msg = r.text[:300]
            try:
                msg = r.json().get("details") or msg
            except Exception:  # noqa: BLE001
                pass
            raise PaymentError(f"Conekta error {r.status_code}: {msg}",
                               self.provider)
        return r.json()

    def _validate_method(self, method: PaymentMethodType) -> None:
        value = method.value if hasattr(method, "value") else str(method)
        if value not in self.SUPPORTED_METHODS:
            raise PaymentError(
                f"Método de pago no soportado por Conekta: {value}",
                self.provider, code="unsupported_payment_method")

    # ---- interfaz --------------------------------------------------------
    def create_customer(self, email: str, name: str) -> Customer:
        if self._mock:
            return Customer(email=email, name=name, provider=self.provider,
                            provider_customer_id=_next_mock_id("customer"))
        body = self._post("/customers", {"name": name, "email": email})
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
        # Conekta usa "plans"; para suscripción se vincula el plan al cliente.
        payload = {"customer_id": customer_id, "plan_id": price_id}
        if payment_method_id:
            payload["card_id"] = payment_method_id
        body = self._post("/customers/{id}/subscription".format(id=customer_id),
                          payload)
        return Subscription(
            customer_id=0, plan=price_id, provider=self.provider,
            provider_subscription_id=body.get("id"),
            status=SubscriptionStatus(body.get("status", "active")),
            current_period_start=str(body.get("billing_cycle_start") or ""),
            current_period_end=str(body.get("billing_cycle_end") or ""))

    def create_invoice(self, customer_id: str, amount: float,
                       currency: str = "MXN") -> Invoice:
        if self._mock:
            return Invoice(customer_id=0, amount=amount, currency=currency,
                           provider=self.provider,
                           provider_invoice_id=_next_mock_id("invoice"),
                           status="open")
        body = self._post("/orders", {
            "currency": currency.lower(),
            "customer_info": {"customer_id": customer_id},
            "line_items": [{
                "name": "Cargo Likida AI Enterprise",
                "unit_price": int(round(amount * 100)),
                "quantity": 1,
            }],
        })
        return Invoice(customer_id=0, amount=amount, currency=currency,
                       provider=self.provider,
                       provider_invoice_id=body.get("id"), status="open")

    def process_payment(self, payment_method_id: str, amount: float,
                        currency: str = "MXN",
                        method: PaymentMethodType = PaymentMethodType.CARD,
                        capture: bool = True) -> PaymentResult:
        """Procesa un pago. `method` puede ser CARD, SPEI u OXXO.

        Para SPEI / OXXO el pago queda en estado `pending_payment` y el
        resultado incluye `payment_instructions` (CLABE / referencia).
        """
        self._validate_method(method)

        if self._mock:
            if method == PaymentMethodType.SPEI:
                return PaymentResult(
                    ok=True, provider=self.provider,
                    reference=_next_mock_id("payment"),
                    status="pending_payment", amount=amount,
                    currency=currency, payment_method_type=method,
                    message="Pago SPEI en espera de transferencia (mock).",
                    payment_instructions={
                        "type": "spei", "clabe": "012180015000000001",
                        "bank": "BBVA Bancomer", "reference": "B2B-MOCK-1",
                        "expires_at": "2026-08-02T00:00:00"})
            if method == PaymentMethodType.OXXO:
                return PaymentResult(
                    ok=True, provider=self.provider,
                    reference=_next_mock_id("payment"),
                    status="pending_payment", amount=amount,
                    currency=currency, payment_method_type=method,
                    message="Pago OXXO generado (mock).",
                    payment_instructions={
                        "type": "oxxo", "barcode": "01234567890123456789012345",
                        "reference": "B2B-MOCK-OXXO-1",
                        "expires_at": "2026-08-02T00:00:00"})
            return PaymentResult(
                ok=True, provider=self.provider,
                reference=_next_mock_id("payment"), status="succeeded",
                amount=amount, currency=currency,
                payment_method_type=PaymentMethodType.CARD,
                message="Pago con tarjeta procesado (mock).")

        if method in (PaymentMethodType.SPEI, PaymentMethodType.OXXO):
            # Conekta crea una orden con un charge de método offline.
            body = self._post("/orders", {
                "currency": currency.lower(),
                "customer_info": {"customer_id": payment_method_id},
                "charges": [{
                    "payment_method": {
                        "type": method.value,
                        "expires_at": "2026-08-02",
                    },
                }],
                "line_items": [{
                    "name": f"Cargo Likida AI Enterprise ({method.value})",
                    "unit_price": int(round(amount * 100)),
                    "quantity": 1,
                }],
            })
            charge = (body.get("charges") or [{}])[0]
            pm = charge.get("payment_method", {})
            instructions = {}
            if method == PaymentMethodType.SPEI:
                instructions = {"type": "spei",
                                "clabe": pm.get("clabe"),
                                "bank": pm.get("bank_name"),
                                "reference": pm.get("reference")}
            else:
                instructions = {"type": "oxxo",
                                "barcode": pm.get("barcode_url"),
                                "reference": pm.get("reference")}
            return PaymentResult(
                ok=True, provider=self.provider, reference=body.get("id"),
                status="pending_payment", amount=amount, currency=currency,
                payment_method_type=method,
                message="Pago pendiente por transferencia/efectivo.",
                payment_instructions=instructions)

        # Tarjeta: charge directo (captura o preautorización).
        body = self._post("/charges", {
            "amount": int(round(amount * 100)),
            "currency": currency.lower(),
            "payment_method": {"type": "default", "payment_method_id": payment_method_id},
            "capture": capture,
        })
        return PaymentResult(
            ok=body.get("status") in ("paid", "pending"),
            provider=self.provider, reference=body.get("id"),
            status=body.get("status", "unknown"), amount=amount,
            currency=currency, payment_method_type=PaymentMethodType.CARD,
            message=body.get("status", ""))

    def webhook_handler(self, event_type: str, data: dict) -> dict:
        """Traduce un evento de webhook de Conekta a un resumen normalizado."""
        resource = data.get("data", {}).get("object", {}) if isinstance(
            data, dict) else {}
        summary = {
            "customer_id": resource.get("customer_id"),
            "invoice_id": resource.get("invoice_id") or resource.get("id"),
            "amount": resource.get("amount"),
            "status": resource.get("status"),
        }
        if event_type == "order.paid" or "charge.paid" in event_type:
            return {"provider": self.provider.value, "event_type": event_type,
                    "handled": True, "mark_paid": True, **summary}
        if "charge" in event_type or "order" in event_type:
            return {"provider": self.provider.value, "event_type": event_type,
                    "handled": True, "mark_paid": False, **summary}
        return {"provider": self.provider.value, "event_type": event_type,
                "handled": False, "reason": "evento sin manejo específico"}
