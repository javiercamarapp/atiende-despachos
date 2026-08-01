# -*- coding: utf-8 -*-
"""
webhook_receiver.py — Recepción y procesamiento de webhooks de Conekta.

Endpoint independiente que recibe POST /api/v1/billing/webhook y:
  1. Verifica firma HMAC-SHA256 contra el secret de Conekta.
  2. Parsea eventos soportados (payment.paid, payment.failed,
     subscription.created, subscription.canceled).
  3. Actualiza estado de suscripción / factura en la DB.
  4. Registra cada evento en audit_log con logging estructurado.

Eventos soportados:
    payment.paid          → marca factura como pagada
    payment.failed        → marca factura como failed + log
    subscription.created  → crea/actualiza suscripción en DB
    subscription.canceled → cancela suscripción en DB

Uso desde la API:
    from b2b_ai.billing.webhook_receiver import build_webhook_router
    app.include_router(build_webhook_router(db))

O integración con router existente (api.py):
    from b2b_ai.billing.webhook_receiver import ConektaWebhookReceiver
    receiver = ConektaWebhookReceiver(db, webhook_secret=secret)
    result = receiver.process_webhook(payload, signature_header)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("billing.webhook_receiver")

# ---------------------------------------------------------------------------
# Supported event types
# ---------------------------------------------------------------------------

class ConektaEventType(str, Enum):
    """Eventos de webhook de Conekta que el sistema procesa."""
    PAYMENT_PAID = "payment.paid"
    PAYMENT_FAILED = "payment.failed"
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_CANCELED = "subscription.canceled"


SUPPORTED_EVENTS: Set[str] = {e.value for e in ConektaEventType}

# Mapping de evento → nuevo estado de suscripción
_SUBSCRIPTION_STATUS_MAP: Dict[str, str] = {
    ConektaEventType.SUBSCRIPTION_CREATED.value: "active",
    ConektaEventType.SUBSCRIPTION_CANCELED.value: "canceled",
}

# Mapping de evento → estado de factura
_INVOICE_STATUS_MAP: Dict[str, str] = {
    ConektaEventType.PAYMENT_PAID.value: "paid",
    ConektaEventType.PAYMENT_FAILED.value: "failed",
}


# ---------------------------------------------------------------------------
# ConektaWebhookReceiver
# ---------------------------------------------------------------------------

class ConektaWebhookReceiver:
    """Procesador de webhooks de Conekta con verificación de firma HMAC.

    Lifecycle:
        1. FastAPI recibe POST /api/v1/billing/webhook.
        2. Se pasa el body crudo + header 'conekta-signature'.
        3. process_webhook() verifica firma → parsea → actualiza DB → log.

    Attributes:
        db:             Instancia de Database (capa de persistencia).
        webhook_secret: Secreto HMAC para verificar firmas (env B2B_CONEKTA_WEBHOOK_SECRET).
    """

    def __init__(self, db: Any, webhook_secret: Optional[str] = None):
        """Inicializa el receiver.

        Args:
            db:             Instancia de Database con métodos de billing.
            webhook_secret: Secreto HMAC. Si es None, se lee de B2B_CONEKTA_WEBHOOK_SECRET.
        """
        self.db = db
        self.webhook_secret = (
            webhook_secret
            or os.environ.get("B2B_CONEKTA_WEBHOOK_SECRET", "")
        )

    # -------------------------------------------------------------------
    # Signature verification
    # -------------------------------------------------------------------

    def verify_signature(self, payload_body: str, signature_header: str) -> bool:
        """Verifica la firma HMAC-SHA256 de un webhook de Conekta.

        Conekta envía: ``conekta-signature: hmac_sha256=<hash>,t=<timestamp>``
        El contenido firmado es: ``{timestamp}{payload_body}``

        Args:
            payload_body:     Body raw del request (string UTF-8).
            signature_header: Valor del header 'conekta-signature'.

        Returns:
            True si la firma es válida, False en caso contrario.

        Security:
            - Si no hay secret configurado, SIEMPRE retorna False (nunca bypass).
            - Usa hmac.compare_digest para prevenir timing attacks.
        """
        if not self.webhook_secret:
            logger.warning(
                "Webhook signature check skipped: no secret configured"
            )
            return False

        if not signature_header:
            logger.warning("Webhook signature header empty")
            return False

        try:
            # Conekta format: "hmac_sha256=<hash>,t=<timestamp>"
            parts: Dict[str, str] = {}
            for item in signature_header.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    parts[k.strip()] = v.strip()

            received_hash = parts.get("hmac_sha256", "")
            timestamp = parts.get("t", "")

            if not received_hash or not timestamp:
                logger.warning(
                    "Malformed signature header: missing hash or timestamp"
                )
                return False

            # Rebuild the signed content: timestamp + payload
            signed_content = f"{timestamp}{payload_body}"
            expected = hmac.new(
                self.webhook_secret.encode("utf-8"),
                signed_content.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            valid = hmac.compare_digest(received_hash, expected)
            if not valid:
                logger.warning("Webhook signature mismatch")
            return valid

        except (ValueError, KeyError) as exc:
            logger.error("Signature verification error: %s", exc)
            return False

    # -------------------------------------------------------------------
    # Event parsing
    # -------------------------------------------------------------------

    @staticmethod
    def parse_event(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae información normalizada de un evento de Conekta.

        Args:
            payload: JSON payload del webhook.

        Returns:
            Dict con event_type, data_object, invoice_id, subscription_id,
            customer_id, amount, etc.

        Raises:
            ValueError: Si el payload no tiene la estructura esperada.
        """
        event_type = payload.get("type", "")
        if not event_type:
            raise ValueError("Missing 'type' in webhook payload")

        # Conekta envía datos en data.object
        data = payload.get("data", {})
        data_object = data.get("object", {}) if isinstance(data, dict) else {}

        # Extraer ids relevantes
        subscription_id = (
            data_object.get("subscription_id")
            or data_object.get("id", "")
        )
        customer_id = data_object.get("customer_id", "")
        invoice_id = data_object.get("invoice_id") or data_object.get("id", "")
        amount = data_object.get("amount")
        status = data_object.get("status", "")

        return {
            "event_type": event_type,
            "is_supported": event_type in SUPPORTED_EVENTS,
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "amount": amount,
            "status": status,
            "raw_data_object": data_object,
        }

    # -------------------------------------------------------------------
    # DB updates
    # -------------------------------------------------------------------

    def _update_invoice_status(self, invoice_id: str, status: str) -> bool:
        """Actualiza el estado de una factura por su referencia del proveedor.

        Args:
            invoice_id: ID de la factura en el proveedor (provider_invoice_id).
            status:     Nuevo estado ('paid' o 'failed').

        Returns:
            True si se actualizó al menos una fila.
        """
        if status == "paid":
            return self.db.mark_billing_invoice_paid_by_ref(
                invoice_id, "conekta"
            )
        # Para 'failed' o estados intermedios: update directo
        from datetime import datetime as _dt
        now = _dt.now().isoformat(timespec="seconds")
        cur = self.db.conn.execute(
            """
            UPDATE billing_invoices
            SET status=?, updated_at=?
            WHERE provider_invoice_id=? AND provider=?
            """,
            (status, now, invoice_id, "conekta"),
        )
        self.db.conn.commit()
        return cur.rowcount > 0

    def _update_subscription_status(
        self, subscription_id: str, status: str
    ) -> bool:
        """Actualiza el estado de una suscripción por su ID del proveedor.

        Args:
            subscription_id: ID de la suscripción en el proveedor.
            status:          Nuevo estado ('active', 'canceled', etc.).

        Returns:
            True si se actualizó al menos una fila.
        """
        from datetime import datetime as _dt
        now = _dt.now().isoformat(timespec="seconds")
        cur = self.db.conn.execute(
            """
            UPDATE billing_subscriptions
            SET status=?, updated_at=?
            WHERE provider_subscription_id=? AND provider=?
            """,
            (status, now, subscription_id, "conekta"),
        )
        self.db.conn.commit()
        return cur.rowcount > 0

    def _log_event(
        self,
        event_type: str,
        parsed: Dict[str, Any],
        result: str,
        tenant_id: Optional[int] = None,
    ) -> None:
        """Registra el evento de webhook en audit_log.

        Args:
            event_type: Tipo del evento Conekta.
            parsed:     Datos parseados del evento.
            result:     Resultado del procesamiento ('ok', 'unsupported', etc.).
            tenant_id:  ID del tenant (puede ser None para eventos globales).
        """
        payload = {
            "provider": "conekta",
            "event_type": event_type,
            "subscription_id": parsed.get("subscription_id", ""),
            "customer_id": parsed.get("customer_id", ""),
            "invoice_id": parsed.get("invoice_id", ""),
            "amount": parsed.get("amount"),
            "result": result,
        }
        self.db.log_call(
            "billing",
            "webhook",
            entity="conekta_event",
            entity_id=event_type,
            payload=payload,
            status=result,
            tenant_id=tenant_id,
        )

    # -------------------------------------------------------------------
    # Main processing
    # -------------------------------------------------------------------

    def process_webhook(
        self,
        payload: Dict[str, Any],
        signature_header: str = "",
    ) -> Dict[str, Any]:
        """Procesa un evento de webhook de Conekta de punta a punta.

        Steps:
            1. Verificar firma HMAC-SHA256.
            2. Parsear evento.
            3. Actualizar DB según tipo de evento.
            4. Loggear en audit_log.

        Args:
            payload:          JSON body del webhook (ya parseado).
            signature_header: Header 'conekta-signature' del request.

        Returns:
            Dict con el resultado del procesamiento.

        Raises:
            HTTPException 401: Firma inválida o ausente.
            HTTPException 400: Payload inválido.
        """
        # 1. Verificar firma
        payload_body = json.dumps(payload, separators=(",", ":"))
        if not self.verify_signature(payload_body, signature_header):
            logger.warning(
                "Webhook rejected: invalid signature (type=%s)",
                payload.get("type", "unknown"),
            )
            raise HTTPException(
                status_code=401,
                detail="Firma de webhook inválida o ausente.",
            )

        # 2. Parsear evento
        try:
            parsed = self.parse_event(payload)
        except ValueError as exc:
            logger.error("Webhook parse error: %s", exc)
            raise HTTPException(
                status_code=400,
                detail=f"Payload inválido: {exc}",
            )

        event_type = parsed["event_type"]

        if not parsed["is_supported"]:
            logger.info(
                "Webhook event ignored (unsupported): %s", event_type
            )
            self._log_event(event_type, parsed, "unsupported")
            return {
                "received": True,
                "processed": False,
                "event_type": event_type,
                "reason": "evento no soportado",
            }

        # 3. Actualizar DB según tipo de evento
        updated_invoice = False
        updated_subscription = False

        # Invoices (payment events)
        if event_type in _INVOICE_STATUS_MAP:
            invoice_status = _INVOICE_STATUS_MAP[event_type]
            if parsed["invoice_id"]:
                updated_invoice = self._update_invoice_status(
                    parsed["invoice_id"], invoice_status
                )
                logger.info(
                    "Invoice %s updated to %s (updated=%s)",
                    parsed["invoice_id"],
                    invoice_status,
                    updated_invoice,
                )

        # Subscriptions (subscription events)
        if event_type in _SUBSCRIPTION_STATUS_MAP:
            sub_status = _SUBSCRIPTION_STATUS_MAP[event_type]
            if parsed["subscription_id"]:
                updated_subscription = self._update_subscription_status(
                    parsed["subscription_id"], sub_status
                )
                logger.info(
                    "Subscription %s updated to %s (updated=%s)",
                    parsed["subscription_id"],
                    sub_status,
                    updated_subscription,
                )

        # 4. Loggear
        self._log_event(event_type, parsed, "ok")

        result = {
            "received": True,
            "processed": True,
            "event_type": event_type,
            "invoice_updated": updated_invoice,
            "subscription_updated": updated_subscription,
        }

        logger.info(
            "Webhook processed successfully: type=%s invoice=%s sub=%s",
            event_type,
            updated_invoice,
            updated_subscription,
        )

        return result


# ---------------------------------------------------------------------------
# FastAPI Router (standalone endpoint)
# ---------------------------------------------------------------------------

def build_webhook_receiver_router(
    db: Any,
    webhook_secret: Optional[str] = None,
) -> APIRouter:
    """Crea un APIRouter con el endpoint de webhook de Conekta.

    Endpoint: POST /api/v1/billing/webhook

    El receiver se instancia por cada request para permitir
    inyección de dependencias y testing limpio.

    Args:
        db:             Instancia de Database.
        webhook_secret: Secret HMAC (override para tests).

    Returns:
        APIRouter con el endpoint registrado.
    """
    router = APIRouter(tags=["billing", "webhooks"])

    @router.post(
        "/api/v1/billing/webhook",
        summary="Recibe eventos de webhook de Conekta.",
    )
    async def conekta_webhook(request: Request):
        """Endpoint de recepción de webhooks de Conekta.

        Recibe POST con JSON body y header 'conekta-signature'.
        Verifica firma HMAC-SHA256, parsea el evento, actualiza DB
        y registra en audit_log.

        Returns:
            JSON con el resultado del procesamiento.
        """
        # Leer body crudo ANTES de que FastAPI lo descarte
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(
                status_code=400, detail="Body vacío."
            )

        # Parsear JSON
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"JSON inválido: {exc}",
            )

        # Extraer signature
        signature_header = request.headers.get("conekta-signature", "")

        # Procesar
        receiver = ConektaWebhookReceiver(db, webhook_secret)
        return receiver.process_webhook(payload, signature_header)

    return router
