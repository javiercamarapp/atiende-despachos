# -*- coding: utf-8 -*-
"""
conekta_gateway.py — Gateway completo de Conekta para Likida AI Enterprise.

Extiende el proveedor base con funcionalidad avanzada:
  1. API client para crear clientes, suscripciones y cargos
  2. SPEI como método de pago principal (costo $12.50 flat vs $680 card)
  3. Card como fallback secundario
  4. Webhook handler con verificación de firma
  5. Subscription management (create, update, cancel)
  6. Invoice generation con line items detallados

Config:
    B2B_CONEKTA_KEY         clave privada `key_...`
    B2B_CONEKTA_WEBHOOK_SECRET  secreto para verificar webhooks
    B2B_PAYMENTS_MOCK=1     modo mock (sin red)

Estrategia de cobro:
    SPEI primario por defecto ($12.50 flat) → Card fallback ($680 ~3.4% de $20K).
    SPEI = transferencia bancaria via CLABE interbancaria.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

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
    InvoiceStatus,
    PaymentMethodType,
    PaymentResult,
    Provider,
    Subscription,
    SubscriptionStatus,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONEKTA_API_BASE = "https://api.conekta.io"
CONEKTA_API_VERSION = "2.1.0"

# Costos por método (MXN) — SPEI es ~95% más barato que tarjeta
SPEI_FLAT_FEE = 12.50       # Costo fijo por transferencia SPEI
CARD_PERCENT_FEE = 0.034    # ~3.4% para tarjeta
CARD_FLAT_FEE = 3.50        # Comisión fija adicional en tarjeta

# Planes con precios (MXN/mes) — alineados con pricing.py
PLAN_PRICES = {
    "starter": 4999.00,
    "growth": 9999.00,
    "enterprise": 0.00,  # cotización custom
}


class ConektaEnvironment(str, Enum):
    """Entorno de la API de Conekta."""
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class PaymentMethodPriority(str, Enum):
    """Prioridad de métodos de pago (SPEI primero por costo)."""
    SPEI_PRIMARY = "spei_primary"    # SPEI first, card fallback
    CARD_ONLY = "card_only"          # Solo tarjeta
    SPEI_ONLY = "spei_only"          # Solo SPEI


# ---------------------------------------------------------------------------
# Conekta API Client
# ---------------------------------------------------------------------------
class ConektaAPIClient:
    """Cliente HTTP para la REST API de Conekta.

    Handles autenticación, headers, retry logic y manejo de errores.
    API docs: https://developers.conekta.com/reference
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        environment: ConektaEnvironment = ConektaEnvironment.PRODUCTION,
    ):
        self.api_key = api_key or os.environ.get("B2B_CONEKTA_KEY", "")
        self.webhook_secret = webhook_secret or os.environ.get(
            "B2B_CONEKTA_WEBHOOK_SECRET", ""
        )
        self.environment = environment
        self._base_url = CONEKTA_API_BASE
        self._client = httpx.Client(timeout=30.0)

    def _headers(self) -> Dict[str, str]:
        """Headers requeridos por la API de Conekta v2."""
        if not self.api_key:
            raise PaymentError(
                "B2B_CONEKTA_KEY no configurada para Conekta API client.",
                Provider.CONEKTA, code="missing_api_key",
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": f"application/vnd.conekta-v{CONEKTA_API_VERSION}+json",
            "Content-Type": "application/json",
        }

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Realiza un POST a la API de Conekta con retry."""
        url = f"{self._base_url}{path}"
        last_error = None

        for attempt in range(3):
            try:
                r = self._client.post(url, json=payload, headers=self._headers())
                if r.status_code >= 500 and attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise PaymentError(
                    f"Error de red con Conekta: {exc}",
                    Provider.CONEKTA, code="network",
                )
        else:
            raise PaymentError(
                f"Error de red con Conekta: {last_error}",
                Provider.CONEKTA, code="network",
            )

        if r.status_code >= 400:
            msg = r.text[:300]
            try:
                details = r.json().get("details") or []
                if details:
                    msg = details[0].get("message", msg)
            except Exception:  # noqa: BLE001
                pass
            raise PaymentError(
                f"Conekta API error {r.status_code}: {msg}",
                Provider.CONEKTA, code="api_error",
            )
        return r.json()

    def get(self, path: str) -> Dict[str, Any]:
        """Realiza un GET a la API de Conekta."""
        url = f"{self._base_url}{path}"
        try:
            r = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise PaymentError(
                f"Error de red con Conekta: {exc}",
                Provider.CONEKTA, code="network",
            )
        if r.status_code >= 400:
            raise PaymentError(
                f"Conekta API error {r.status_code}: {r.text[:200]}",
                Provider.CONEKTA, code="api_error",
            )
        return r.json()

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._client.close()


# ---------------------------------------------------------------------------
# Conekta Gateway
# ---------------------------------------------------------------------------
class ConektaGateway:
    """Gateway completo de pagos Conekta para Likida AI Enterprise.

    Proporciona:
      - Creación de clientes
      - Subscription management (create, update, cancel)
      - Charges (SPEI primario, card fallback)
      - Invoice generation
      - Webhook handling con verificación de firma
      - Cost optimization (SPEI vs card)

    Uso:
        gateway = ConektaGateway()
        customer = gateway.create_customer("firma@contadores.mx", "ABC Contadores")
        result = gateway.process_charge(customer.id, 20000, method=PaymentMethodType.SPEI)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        mock: Optional[bool] = None,
    ):
        self.api_key = api_key or os.environ.get("B2B_CONEKTA_KEY", "")
        self.webhook_secret = webhook_secret or os.environ.get(
            "B2B_CONEKTA_WEBHOOK_SECRET", ""
        )
        self._mock = mock if mock is not None else mock_mode_enabled()
        self._client = ConektaAPIClient(
            api_key=self.api_key,
            webhook_secret=self.webhook_secret,
        )

    # ------------------------------------------------------------------
    # Customer Management
    # ------------------------------------------------------------------
    def create_customer(
        self,
        email: str,
        name: str,
        phone: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Customer:
        """Crea un cliente en Conekta.

        Args:
            email: Email del despacho contable.
            name: Nombre del despacho.
            phone: Teléfono (opcional).
            metadata: Datos adicionales del cliente.

        Returns:
            Customer con provider_customer_id asignado.
        """
        if self._mock:
            return Customer(
                email=email, name=name, provider=Provider.CONEKTA,
                provider_customer_id=_next_mock_id("customer"),
            )

        payload: Dict[str, Any] = {"name": name, "email": email}
        if phone:
            payload["phone"] = phone
        if metadata:
            payload["metadata"] = metadata

        body = self._client.post("/customers", payload)
        return Customer(
            email=email, name=name, provider=Provider.CONEKTA,
            provider_customer_id=body.get("id"),
        )

    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """Obtiene un cliente por su ID de Conekta."""
        if self._mock:
            return {"id": customer_id, "name": "Mock Customer", "email": "mock@test.com"}
        return self._client.get(f"/customers/{customer_id}")

    # ------------------------------------------------------------------
    # Subscription Management
    # ------------------------------------------------------------------
    def create_subscription(
        self,
        customer_id: str,
        plan_id: str,
        payment_method_id: Optional[str] = None,
        trial_days: int = 0,
    ) -> Subscription:
        """Crea una suscripción para un cliente.

        Args:
            customer_id: ID del cliente en Conekta.
            plan_id: ID del plan (starter/growth/enterprise).
            payment_method_id: ID del método de pago registrado.
            trial_days: Días de prueba (0 = sin prueba).

        Returns:
            Subscription con estado activo.
        """
        if self._mock:
            return Subscription(
                customer_id=0, plan=plan_id, provider=Provider.CONEKTA,
                provider_subscription_id=_next_mock_id("subscription"),
                status=SubscriptionStatus.ACTIVE,
                current_period_start="2026-08-01T00:00:00",
                current_period_end="2026-09-01T00:00:00",
            )

        payload: Dict[str, Any] = {
            "customer_id": customer_id,
            "plan_id": plan_id,
        }
        if payment_method_id:
            payload["card_id"] = payment_method_id
        if trial_days > 0:
            payload["trial_period_days"] = trial_days

        body = self._client.post(
            f"/customers/{customer_id}/subscription", payload
        )
        return Subscription(
            customer_id=0, plan=plan_id, provider=Provider.CONEKTA,
            provider_subscription_id=body.get("id"),
            status=SubscriptionStatus(body.get("status", "active")),
            current_period_start=str(body.get("billing_cycle_start") or ""),
            current_period_end=str(body.get("billing_cycle_end") or ""),
        )

    def update_subscription(
        self,
        customer_id: str,
        subscription_id: str,
        new_plan_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
    ) -> Subscription:
        """Actualiza una suscripción existente (cambio de plan o método de pago).

        Args:
            customer_id: ID del cliente en Conekta.
            subscription_id: ID de la suscripción.
            new_plan_id: Nuevo plan (None = sin cambio).
            payment_method_id: Nuevo método de pago (None = sin cambio).

        Returns:
            Subscription actualizada.
        """
        if self._mock:
            plan = new_plan_id or "growth"
            return Subscription(
                customer_id=0, plan=plan, provider=Provider.CONEKTA,
                provider_subscription_id=subscription_id,
                status=SubscriptionStatus.ACTIVE,
                current_period_start="2026-08-01T00:00:00",
                current_period_end="2026-09-01T00:00:00",
            )

        payload: Dict[str, Any] = {}
        if new_plan_id:
            payload["plan_id"] = new_plan_id
        if payment_method_id:
            payload["card_id"] = payment_method_id

        if not payload:
            raise PaymentError(
                "No se especificaron cambios para la suscripción.",
                Provider.CONEKTA, code="no_changes",
            )

        body = self._client.post(
            f"/customers/{customer_id}/subscription", payload
        )
        plan_used = new_plan_id or body.get("plan_id", "")
        return Subscription(
            customer_id=0, plan=plan_used, provider=Provider.CONEKTA,
            provider_subscription_id=subscription_id,
            status=SubscriptionStatus(body.get("status", "active")),
            current_period_start=str(body.get("billing_cycle_start") or ""),
            current_period_end=str(body.get("billing_cycle_end") or ""),
        )

    def cancel_subscription(
        self,
        customer_id: str,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> Subscription:
        """Cancela una suscripción.

        Args:
            customer_id: ID del cliente en Conekta.
            subscription_id: ID de la suscripción.
            at_period_end: Si True, cancela al final del periodo.
                          Si False, cancela inmediatamente.

        Returns:
            Subscription con estado canceled.
        """
        if self._mock:
            return Subscription(
                customer_id=0, plan="growth", provider=Provider.CONEKTA,
                provider_subscription_id=subscription_id,
                status=SubscriptionStatus.CANCELED,
                current_period_start="2026-08-01T00:00:00",
                current_period_end="2026-09-01T00:00:00",
            )

        payload: Dict[str, Any] = {"status": "canceled"}
        if at_period_end:
            payload["at_period_end"] = True

        body = self._client.post(
            f"/customers/{customer_id}/subscription", payload
        )
        return Subscription(
            customer_id=0, plan=body.get("plan_id", ""),
            provider=Provider.CONEKTA,
            provider_subscription_id=subscription_id,
            status=SubscriptionStatus.CANCELED,
            current_period_start=str(body.get("billing_cycle_start") or ""),
            current_period_end=str(body.get("billing_cycle_end") or ""),
        )

    def get_subscription_status(
        self, customer_id: str, subscription_id: str
    ) -> Dict[str, Any]:
        """Obtiene el estado actual de una suscripción."""
        if self._mock:
            return {
                "id": subscription_id, "status": "active",
                "plan_id": "growth",
                "billing_cycle_start": "2026-08-01T00:00:00",
                "billing_cycle_end": "2026-09-01T00:00:00",
            }
        body = self._client.get(
            f"/customers/{customer_id}/subscription"
        )
        return body

    # ------------------------------------------------------------------
    # Payment Processing (SPEI primary, Card fallback)
    # ------------------------------------------------------------------
    def process_charge(
        self,
        customer_id: str,
        amount: float,
        currency: str = "MXN",
        method: PaymentMethodType = PaymentMethodType.SPEI,
        capture: bool = True,
        description: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> PaymentResult:
        """Procesa un cargo contra un cliente.

        SPEI es el método principal por defecto (costo $12.50 flat).
        Card es fallback para clientes que no pueden usar SPEI.

        Args:
            customer_id: ID del cliente en Conekta.
            amount: Monto en MXN.
            currency: Moneda (default MXN).
            method: Método de pago (SPEI por defecto).
            capture: Si True, captura inmediatamente (solo card).
            description: Descripción del cargo.
            expires_at: Fecha de expiración para SPEI/OXXO.

        Returns:
            PaymentResult con instrucciones de pago si aplica.
        """
        # Validate method
        valid_methods = {m.value for m in PaymentMethodType}
        if method.value not in valid_methods:
            raise PaymentError(
                f"Método de pago no soportado: {method.value}",
                Provider.CONEKTA, code="unsupported_payment_method",
            )

        if self._mock:
            return self._mock_charge(amount, currency, method)

        if method in (PaymentMethodType.SPEI, PaymentMethodType.OXXO):
            return self._process_offline_charge(
                customer_id, amount, currency, method, description, expires_at
            )

        # Card charge
        return self._process_card_charge(
            customer_id, amount, currency, capture, description
        )

    def _process_offline_charge(
        self,
        customer_id: str,
        amount: float,
        currency: str,
        method: PaymentMethodType,
        description: Optional[str],
        expires_at: Optional[str],
    ) -> PaymentResult:
        """Procesa pago offline (SPEI/OXXO) via Conekta orders."""
        desc = description or f"Cargo Likida AI ({method.value})"
        payload: Dict[str, Any] = {
            "currency": currency.lower(),
            "customer_info": {"customer_id": customer_id},
            "charges": [{
                "payment_method": {
                    "type": method.value,
                    "expires_at": expires_at or "2026-12-31",
                },
            }],
            "line_items": [{
                "name": desc,
                "unit_price": int(round(amount * 100)),
                "quantity": 1,
            }],
        }

        body = self._client.post("/orders", payload)
        charge = (body.get("charges") or [{}])[0]
        pm = charge.get("payment_method", {})

        instructions: Dict[str, str] = {}
        if method == PaymentMethodType.SPEI:
            instructions = {
                "type": "spei",
                "clabe": pm.get("clabe", ""),
                "bank": pm.get("bank_name", ""),
                "reference": pm.get("reference", ""),
                "bank_name": pm.get("bank_name", ""),
            }
        elif method == PaymentMethodType.OXXO:
            instructions = {
                "type": "oxxo",
                "barcode": pm.get("barcode_url", ""),
                "reference": pm.get("reference", ""),
            }

        return PaymentResult(
            ok=True, provider=Provider.CONEKTA,
            reference=body.get("id"), status="pending_payment",
            amount=amount, currency=currency,
            payment_method_type=method,
            message="Pago pendiente por transferencia/efectivo.",
            payment_instructions=instructions,
        )

    def _process_card_charge(
        self,
        customer_id: str,
        amount: float,
        currency: str,
        capture: bool,
        description: Optional[str],
    ) -> PaymentResult:
        """Procesa cargo con tarjeta via Conekta charges."""
        payload: Dict[str, Any] = {
            "amount": int(round(amount * 100)),
            "currency": currency.lower(),
            "payment_method": {
                "type": "default",
                "payment_method_id": customer_id,
            },
            "capture": capture,
        }
        if description:
            payload["description"] = description

        body = self._client.post("/charges", payload)
        return PaymentResult(
            ok=body.get("status") in ("paid", "pending"),
            provider=Provider.CONEKTA,
            reference=body.get("id"),
            status=body.get("status", "unknown"),
            amount=amount, currency=currency,
            payment_method_type=PaymentMethodType.CARD,
            message=body.get("status", ""),
        )

    def _mock_charge(
        self, amount: float, currency: str, method: PaymentMethodType
    ) -> PaymentResult:
        """Resultado mock para pruebas sin red."""
        if method == PaymentMethodType.SPEI:
            return PaymentResult(
                ok=True, provider=Provider.CONEKTA,
                reference=_next_mock_id("payment"),
                status="pending_payment", amount=amount, currency=currency,
                payment_method_type=method,
                message="Pago SPEI en espera de transferencia (mock).",
                payment_instructions={
                    "type": "spei",
                    "clabe": "012180015000000001",
                    "bank": "BBVA Bancomer",
                    "reference": "B2B-MOCK-1",
                    "bank_name": "BBVA Bancomer",
                },
            )
        if method == PaymentMethodType.OXXO:
            return PaymentResult(
                ok=True, provider=Provider.CONEKTA,
                reference=_next_mock_id("payment"),
                status="pending_payment", amount=amount, currency=currency,
                payment_method_type=method,
                message="Pago OXXO generado (mock).",
                payment_instructions={
                    "type": "oxxo",
                    "barcode": "01234567890123456789012345",
                    "reference": "B2B-MOCK-OXXO-1",
                },
            )
        # Card
        return PaymentResult(
            ok=True, provider=Provider.CONEKTA,
            reference=_next_mock_id("payment"),
            status="succeeded", amount=amount, currency=currency,
            payment_method_type=PaymentMethodType.CARD,
            message="Pago con tarjeta procesado (mock).",
        )

    # ------------------------------------------------------------------
    # Invoice Generation
    # ------------------------------------------------------------------
    def create_invoice(
        self,
        customer_id: str,
        amount: float,
        currency: str = "MXN",
        description: Optional[str] = None,
        line_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Invoice:
        """Genera una factura (order) en Conekta.

        Args:
            customer_id: ID del cliente en Conekta.
            amount: Monto total en MXN.
            currency: Moneda.
            description: Descripción de la factura.
            line_items: Items detallados (override del auto-generado).

        Returns:
            Invoice con provider_invoice_id.
        """
        if self._mock:
            return Invoice(
                customer_id=0, amount=amount, currency=currency,
                provider=Provider.CONEKTA,
                provider_invoice_id=_next_mock_id("invoice"),
                status=InvoiceStatus.OPEN,
            )

        desc = description or "Cargo Likida AI Enterprise"
        items = line_items or [{
            "name": desc,
            "unit_price": int(round(amount * 100)),
            "quantity": 1,
        }]

        payload: Dict[str, Any] = {
            "currency": currency.lower(),
            "customer_info": {"customer_id": customer_id},
            "line_items": items,
        }

        body = self._client.post("/orders", payload)
        return Invoice(
            customer_id=0, amount=amount, currency=currency,
            provider=Provider.CONEKTA,
            provider_invoice_id=body.get("id"),
            status=InvoiceStatus.OPEN,
        )

    def create_subscription_invoice(
        self,
        customer_id: str,
        plan_id: str,
        amount: Optional[float] = None,
    ) -> Invoice:
        """Genera una factura para una suscripción.

        Usa el precio del plan si no se especifica monto.
        """
        final_amount = amount or PLAN_PRICES.get(plan_id, 0)
        if final_amount == 0:
            raise PaymentError(
                f"Plan '{plan_id}' requiere cotización manual.",
                Provider.CONEKTA, code="requires_quote",
            )
        return self.create_invoice(
            customer_id=customer_id,
            amount=final_amount,
            description=f"Likida AI {plan_id.title()} — mensualidad",
        )

    # ------------------------------------------------------------------
    # Webhook Handling
    # ------------------------------------------------------------------
    def verify_webhook_signature(
        self,
        payload: str,
        signature_header: str,
    ) -> bool:
        """Verifica la firma HMAC-SHA256 de un webhook de Conekta.

        Args:
            payload: Body raw del request (string).
            signature_header: Header 'conekta-signature' del request.

        Returns:
            True si la firma es válida.
        """
        if not self.webhook_secret:
            # Sin secreto configurado, no verificamos (modo dev)
            return True

        if not signature_header:
            return False

        try:
            # Conekta format: "hmac_sha256=<hash>,t=<timestamp>"
            parts = dict(
                item.split("=", 1) for item in signature_header.split(",")
            )
            received_hash = parts.get("hmac_sha256", "")
            timestamp = parts.get("t", "")

            if not received_hash or not timestamp:
                return False

            # Rebuild the signed content: timestamp + payload
            signed_content = f"{timestamp}{payload}"
            expected = hmac.new(
                self.webhook_secret.encode("utf-8"),
                signed_content.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(received_hash, expected)
        except (ValueError, KeyError):
            return False

    def handle_webhook(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Procesa un evento de webhook de Conekta y retorna un resumen normalizado.

        Eventos soportados:
            - order.paid / charge.paid → mark_paid=True
            - order.created / charge.created → mark_paid=False
            - customer.created → handled=False
            - subscription.paid → mark_paid=True
            - subscription.canceled → mark_paid=False

        Args:
            event_type: Tipo del evento (e.g. "order.paid").
            data: Datos del evento.

        Returns:
            Dict con resumen normalizado del evento.
        """
        resource = data.get("data", {}).get("object", {}) if isinstance(data, dict) else {}
        summary: Dict[str, Any] = {
            "customer_id": resource.get("customer_id"),
            "invoice_id": resource.get("invoice_id") or resource.get("id"),
            "amount": resource.get("amount"),
            "status": resource.get("status"),
        }

        # Paid events
        if event_type in ("order.paid", "subscription.paid") or "charge.paid" in event_type:
            return {
                "provider": Provider.CONEKTA.value,
                "event_type": event_type,
                "handled": True,
                "mark_paid": True,
                **summary,
            }

        # Order/charge created (pending)
        if "charge" in event_type or "order" in event_type:
            return {
                "provider": Provider.CONEKTA.value,
                "event_type": event_type,
                "handled": True,
                "mark_paid": False,
                **summary,
            }

        # Subscription events
        if "subscription" in event_type:
            return {
                "provider": Provider.CONEKTA.value,
                "event_type": event_type,
                "handled": True,
                "mark_paid": False,
                **summary,
            }

        # Unhandled
        return {
            "provider": Provider.CONEKTA.value,
            "event_type": event_type,
            "handled": False,
            "reason": "evento sin manejo específico",
        }

    # ------------------------------------------------------------------
    # Cost Analysis
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_fee(method: PaymentMethodType, amount: float) -> Dict[str, float]:
        """Calcula el costo del método de pago para un monto dado.

        Args:
            method: Método de pago.
            amount: Monto en MXN.

        Returns:
            Dict con fee, net_amount y effective_rate.
        """
        if method == PaymentMethodType.SPEI:
            return {
                "fee": SPEI_FLAT_FEE,
                "net_amount": amount - SPEI_FLAT_FEE,
                "effective_rate": SPEI_FLAT_FEE / amount if amount > 0 else 0,
            }
        # Card
        fee = (amount * CARD_PERCENT_FEE) + CARD_FLAT_FEE
        return {
            "fee": round(fee, 2),
            "net_amount": round(amount - fee, 2),
            "effective_rate": round(fee / amount, 4) if amount > 0 else 0,
        }

    @staticmethod
    def recommend_payment_method(amount: float) -> PaymentMethodType:
        """Recomienda el mejor método de pago por costo.

        SPEI es más barato para todos los montos (flat $12.50 vs ~3.4% card).
        """
        return PaymentMethodType.SPEI  # Siempre SPEI por costo

    def close(self) -> None:
        """Cierra el cliente HTTP del gateway."""
        self._client.close()
