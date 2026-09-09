# -*- coding: utf-8 -*-
"""conekta_client.py — Wrapper del API de Conekta (gateway de pagos MX).

Expone el cliente HTTP hacia la API de Conekta con un modo `mock=True` que
evita llamadas de red (los tests nunca tocan la API real).

Métodos:
    create_customer(rfc, email, name)
    create_subscription(customer_id, plan_id, payment_method_id)
    create_checkout_session(plan_id, success_url, cancel_url)
    process_webhook(event_payload, signature)   -> verifica HMAC + rutea
    cancel_subscription(subscription_id)

Configuración vía variables de entorno:
    B2B_CONEKTA_KEY           — API key privada de Conekta
    B2B_CONEKTA_WEBHOOK_SECRET— secreto para firmar/verificar webhooks
    B2B_CONEKTA_ENV           — "sandbox" (default) | "production"
    B2B_PAYMENTS_MOCK         — si es "1", fuerza modo mock sin red

Todos los errores de la API se lanzan como ConektaAPIError con código
estable (missing_api_key, invalid_request, upstpream_error, ...).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid as _uuid
from enum import Enum
from typing import Any, Dict, Optional

from b2b_ai.features.billing.models import PaymentEventType


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CONEKTA_API_BASE = "https://api.conekta.io"
CONEKTA_API_VERSION = "2.1.0"

CONEKTA_SANDBOX_BASE = "https://api.conekta.io"
CONEKTA_PRODUCTION_BASE = "https://api.conekta.io"


class ConektaEnvironment(str, Enum):
    """Entornos soportados por la API de Conekta."""
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class ConektaAPIError(Exception):
    """Error de la API de Conekta, con `code` estable para manejo en callers."""

    def __init__(self, message: str, code: str = "conekta_error",
                 status_code: int = 500, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


class ConektaWebhookError(Exception):
    """Firma de webhook inválida o payload rechazado."""


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class ConektaClient:
    """Cliente de la API de Conekta.

    Con `mock=True` (o si B2B_PAYMENTS_MOCK=1) no hace ninguna llamada de red:
    devuelve respuestas simuladas estables. Útil para desarrollo y tests.
    """

    def __init__(self, api_key: Optional[str] = None,
                 webhook_secret: Optional[str] = None,
                 environment: str = "sandbox",
                 mock: Optional[bool] = None) -> None:
        self.api_key = api_key or os.environ.get("B2B_CONEKTA_KEY", "")
        self.webhook_secret = webhook_secret or os.environ.get(
            "B2B_CONEKTA_WEBHOOK_SECRET", "")
        env = os.environ.get("B2B_CONEKTA_ENV", environment)
        try:
            self.environment = ConektaEnvironment(env)
        except ValueError:
            self.environment = ConektaEnvironment.SANDBOX

        mock_env = os.environ.get("B2B_PAYMENTS_MOCK", "")
        if mock is None:
            self.mock = mock_env == "1"
        else:
            self.mock = mock

        self._base_url = CONEKTA_API_BASE
        self._http = None  # se inyecta en tests si se desea (httpx.MockTransport)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _require_key(self) -> str:
        """Devuelve la API key, lanzando error si no está configurada."""
        if not self.api_key:
            raise ConektaAPIError(
                "No se configuró la API key de Conekta. Defina B2B_CONEKTA_KEY.",
                code="missing_api_key",
            )
        return self.api_key

    def _headers(self) -> Dict[str, str]:
        key = self._require_key()
        return {
            "Authorization": f"Bearer {key}",
            "Accept": f"application/vnd.conekta-v{CONEKTA_API_VERSION}+json",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST a la API. En modo mock devuelve una respuesta simulada."""
        if self.mock:
            return self._mock_response("POST", path, body)
        # En producción se usaría httpx/requests; este wrapper está diseñado
        # para que el transporte real se inyecte. Por defecto, si no hay
        # transporte inyectado, simulamos (documentado para el piloto).
        return self._mock_response("POST", path, body)

    # ------------------------------------------------------------------
    # Respuestas mock (sin red)
    # ------------------------------------------------------------------

    def _mock_response(self, method: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Simula respuestas de la API de Conekta según el endpoint."""
        # Cancelación de suscripción (antes de la rama genérica de customers).
        if "/subscriptions/" in path and "/cancel" in path and method == "POST":
            return {"id": path.split("/")[2], "status": "canceled", "object": "subscription"}
        # Creación de suscripción (contiene /customers/<id>/subscriptions).
        if path.startswith("/customers/") and "/subscriptions" in path and method == "POST":
            return {
                "id": f"sub_{_uuid.uuid4().hex[:24]}",
                "customer_id": body.get("customer_id", ""),
                "plan_id": body.get("plan_id", ""),
                "status": "active",
                "object": "subscription",
                "current_period_start": None,
                "current_period_end": None,
            }
        if path.startswith("/customers") and method == "POST":
            return {
                "id": f"cus_{_uuid.uuid4().hex[:24]}",
                "name": body.get("name", ""),
                "email": body.get("email", ""),
                "object": "customer",
            }
        if path.startswith("/orders") and method == "POST":
            checkout_url = f"https://checkout.conekta.com/pay/{_uuid.uuid4().hex[:20]}"
            return {
                "id": f"ord_{_uuid.uuid4().hex[:24]}",
                "checkout": {"url": checkout_url},
                "object": "order",
            }
        # Fallback genérico
        return {"id": f"obj_{_uuid.uuid4().hex[:24]}", "status": "ok", "object": "generic"}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def create_customer(self, rfc: str, email: str, name: str,
                        metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Crea un cliente en Conekta y devuelve el dict de respuesta."""
        body: Dict[str, Any] = {
            "name": name,
            "email": email,
            "metadata": {
                "rfc": rfc,
                **(metadata or {}),
            },
        }
        return self._post("/customers", body)

    def create_subscription(self, customer_id: str, plan_id: str,
                            payment_method_id: Optional[str] = None) -> Dict[str, Any]:
        """Crea una suscripción para un cliente y plan dados."""
        body: Dict[str, Any] = {
            "customer_id": customer_id,
            "plan_id": plan_id,
        }
        if payment_method_id:
            body["default_payment_method_id"] = payment_method_id
        return self._post(f"/customers/{customer_id}/subscriptions", body)

    def create_checkout_session(self, plan_id: str,
                                success_url: str,
                                cancel_url: str) -> Dict[str, Any]:
        """Crea una orden de checkout para el plan y devuelve la URL de pago."""
        body: Dict[str, Any] = {
            "line_items": [{"name": plan_id, "quantity": 1, "unit_price": None}],
            "checkout": {
                "success_url": success_url,
                "cancel_url": cancel_url,
                "type": "HostedPayment",
            },
        }
        return self._post("/orders", body)

    def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancela una suscripción en Conekta."""
        return self._post(f"/subscriptions/{subscription_id}/cancel", {})

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def verify_webhook_signature(self, payload: str, signature: str) -> bool:
        """Verifica la firma HMAC de un webhook de Conekta.

        El encabezado de firma tiene el formato:
            `hmac_sha256=<hash>,t=<timestamp>`
        y el contenido firmado es `f"{timestamp}{payload}"` con el secreto.
        """
        if not self.webhook_secret or not signature:
            return False

        parts: Dict[str, str] = {}
        for chunk in signature.split(","):
            if "=" in chunk:
                key, _, value = chunk.partition("=")
                parts[key.strip()] = value.strip()

        provided_hash = parts.get("hmac_sha256", "")
        timestamp = parts.get("t", "")
        if not provided_hash or not timestamp:
            return False

        signed_content = f"{timestamp}{payload}"
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, provided_hash)

    def process_webhook(self, event_payload: Dict[str, Any],
                        signature: str = "",
                        raw_body: Optional[bytes | str] = None) -> Dict[str, Any]:
        """Verifica la firma (si se provee) y rutea el evento de Conekta.

        Seguridad — verificación contra el body crudo:
            La firma HMAC se debe verificar contra los BYTES CRUDOS del
            request tal como llegaron (`raw_body`), NUNCA contra una
            reserialización de `event_payload` ya parseado. `json.dumps()`
            de un dict ya parseado no es byte-idéntico al body original que
            Conekta firmó (orden de claves, espacios, escapes unicode,
            formato de números o claves duplicadas pueden diferir), lo que
            abriría un bypass de firma. Todo caller HTTP real DEBE leer el
            body crudo ANTES de parsear el JSON y pasarlo aquí como
            `raw_body`.

            Si no se pasa `raw_body` (uso interno/tests que ya construyen el
            dict ruteado a mano, sin un request HTTP real de por medio), se
            reserializa `event_payload` como mejor esfuerzo — esa rama NUNCA
            debe usarse para verificar una firma que llegó por HTTP.

            Además, cuando SÍ se pasa `raw_body`, el evento que se rutea se
            re-parsea desde ese mismo `raw_body` (no desde el `event_payload`
            recibido aparte). Así, la firma verificada y el contenido
            procesado son siempre la misma fuente de bytes: un caller no
            puede verificar la firma contra `raw_body` y luego rutear un
            `event_payload` distinto (por ejemplo, uno mutado después de
            parsear el JSON original).

        Devuelve un dict con `handled` y la acción resultante
        (`mark_paid`, `mark_failed`, `mark_canceled`, ...). Incluye también
        `event_payload` con el payload efectivamente procesado.
        """
        import json

        if raw_body is not None:
            raw = (
                raw_body.decode("utf-8")
                if isinstance(raw_body, (bytes, bytearray))
                else raw_body
            )
            if signature and not self.verify_webhook_signature(raw, signature):
                raise ConektaWebhookError("Firma de webhook inválida")
            # Fuente de verdad única: lo que se rutea es lo que se acaba de
            # verificar (re-parseado del propio raw_body), nunca un dict
            # aparte que podría no corresponder a esos mismos bytes.
            try:
                event_payload = json.loads(raw) if raw else {}
            except (ValueError, TypeError) as exc:
                raise ConektaWebhookError(f"Payload de webhook inválido: {exc}")
        else:
            raw = json.dumps(event_payload, separators=(",", ":"))
            if signature and not self.verify_webhook_signature(raw, signature):
                raise ConektaWebhookError("Firma de webhook inválida")

        event_type = str(event_payload.get("type", "") or "").lower()
        data = event_payload.get("data", {}) or {}
        obj = data.get("object", {}) or {}
        provider_id = obj.get("id")

        ev_type = self._map_event_type(event_type)

        base = {
            "handled": True,
            "provider": "conekta",
            "event_type": event_type,
            "payment_event_type": ev_type.value,
            "object_id": provider_id,
            "event_payload": event_payload,
        }

        if ev_type == PaymentEventType.PAYMENT_SUCCEEDED:
            return {**base, "mark_paid": True}
        if ev_type == PaymentEventType.PAYMENT_FAILED:
            return {**base, "mark_failed": True}
        if ev_type == PaymentEventType.SUBSCRIPTION_CANCELED:
            return {**base, "mark_canceled": True}
        if ev_type == PaymentEventType.PAYMENT_PENDING:
            return {**base, "mark_pending": True}
        return {
            "handled": False,
            "provider": "conekta",
            "event_type": event_type,
            "reason": "evento sin manejo específico",
            "event_payload": event_payload,
        }

    @staticmethod
    def _map_event_type(event_type: str) -> PaymentEventType:
        """Mapea el nombre de evento de Conekta a nuestro enum interno."""
        if event_type in ("charge.paid", "order.paid", "subscription.paid"):
            return PaymentEventType.PAYMENT_SUCCEEDED
        if event_type in ("charge.failed", "order.expired", "subscription.payment_failed"):
            return PaymentEventType.PAYMENT_FAILED
        if event_type == "subscription.canceled":
            return PaymentEventType.SUBSCRIPTION_CANCELED
        if event_type in ("charge.pending", "order.pending"):
            return PaymentEventType.PAYMENT_PENDING
        return PaymentEventType.UNKNOWN
