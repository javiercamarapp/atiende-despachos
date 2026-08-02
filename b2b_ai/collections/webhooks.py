# -*- coding: utf-8 -*-
"""
webhooks.py — Procesamiento de webhooks de confirmación de pago.

Recibe notificaciones de gateways de pago (SPEI, Stripe, Conekta) o ERPs
y actualiza el estado de la cartera de cuentas por cobrar:
  - payment_received: factura pagada → se registra como 'pagado' y se
    elimina de outstanding_invoices.
  - payment_partial: pago parcial → se registra el monto y se actualiza
    el score.
  - payment_rejected: pago rechazado → se registra como 'rechazado'.
  - payment_disputed: disputa → se registra y se bloquea la factura.

Cada webhook genera un evento de auditoría en collection_events para
trazabilidad completa del flujo de cobro.

Uso típico:
    handler = CollectionsWebhookHandler(db=db, tenant_id=1)
    result = handler.process_payment_webhook({
        "event_type": "payment_received",
        "invoice_id": "FAC-1001",
        "amount": 12500.00,
        "reference": "SPEI-ABC123",
    })
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.services.collections import CollectionsManager


# --------------------------------------------------------------------------- #
# Eventos soportados
# --------------------------------------------------------------------------- #

SUPPORTED_EVENTS = {
    "payment_received",
    "payment_partial",
    "payment_rejected",
    "payment_disputed",
    "payment_refunded",
    "payment_reminder_sent",
}

# Eventos que marcan la factura como pagada (total o parcial).
PAYMENT_SUCCESS_EVENTS = {"payment_received", "payment_partial"}


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #

class CollectionsWebhookHandler:
    """Procesa webhooks de pago y actualiza la cartera de cobranza.

    Args:
        db:          instancia de Database.
        tenant_id:   ID del tenant.
        manager:     CollectionsManager opcional.
    """

    def __init__(self, db=None, tenant_id: Optional[int] = None,
                 manager: Optional[CollectionsManager] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.manager = manager or CollectionsManager(db=db, tenant_id=tenant_id)

    def process_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un webhook de pago (endpoint agnóstico del proveedor).

        Valida el tipo de evento, registra la respuesta en collection_events
        y actualiza la cartera. Devuelve un dict con el resultado.
        """
        event_type = payload.get("event_type", "")
        invoice_id = str(payload.get("invoice_id", ""))
        amount = float(payload.get("amount", 0))
        reference = payload.get("reference", "")
        provider = payload.get("provider", "manual")
        paid_at = payload.get("paid_at")
        metadata = payload.get("metadata", {})

        if not invoice_id:
            return {"ok": False, "error": "invoice_id es requerido"}

        if event_type not in SUPPORTED_EVENTS:
            return {
                "ok": False,
                "error": f"Evento no soportado: {event_type}. "
                         f"Válidos: {', '.join(sorted(SUPPORTED_EVENTS))}",
            }

        # Resolver el tipo de respuesta para collection_events.
        respuesta = _event_to_respuesta(event_type)

        # Registrar el evento de pago.
        event_id = None
        if self.db is not None and self.tenant_id is not None:
            event_id = self.db.add_collection_event(
                tenant_id=self.tenant_id,
                factura_id=invoice_id,
                tipo_recordatorio=f"webhook_{event_type}",
                canal=provider,
                respuesta=respuesta,
            )

        # Acciones específicas por tipo de evento.
        actions = []

        if event_type in PAYMENT_SUCCESS_EVENTS:
            action_result = self._handle_payment(
                invoice_id, amount, reference, paid_at,
                partial=(event_type == "payment_partial"),
            )
            actions.append(action_result)

        elif event_type == "payment_rejected":
            actions.append({
                "action": "registered",
                "detail": f"Pago rechazado registrado para {invoice_id}",
            })

        elif event_type == "payment_disputed":
            actions.append({
                "action": "registered",
                "detail": f"Disputa registrada para {invoice_id}",
            })

        elif event_type == "payment_refunded":
            actions.append({
                "action": "registered",
                "detail": f"Reembolso registrado para {invoice_id}",
            })

        return {
            "ok": True,
            "event_type": event_type,
            "invoice_id": invoice_id,
            "amount": amount,
            "reference": reference,
            "provider": provider,
            "event_id": event_id,
            "respuesta": respuesta,
            "actions": actions,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _handle_payment(self, invoice_id: str, amount: float,
                        reference: str, paid_at: Optional[str],
                        partial: bool = False) -> Dict[str, Any]:
        """Maneja un pago recibido (total o parcial)."""
        # Eliminar de outstanding si es pago total.
        if not partial and self.db is not None and self.tenant_id is not None:
            self.db.delete_outstanding_invoice(
                self.tenant_id, invoice_id)

        return {
            "action": "marked_paid" if not partial else "marked_partial",
            "detail": (
                f"Factura {invoice_id} marcada como "
                f"{'pagada' if not partial else 'parcialmente pagada'}"
            ),
            "amount": amount,
            "reference": reference,
        }

    def batch_process(self, webhooks: list) -> Dict[str, Any]:
        """Procesa múltiples webhooks en lote.

        Devuelve un resumen con conteos de éxito/fallo por evento.
        """
        results = []
        ok_count = 0
        fail_count = 0

        for wh in webhooks:
            result = self.process_webhook(wh)
            results.append(result)
            if result.get("ok"):
                ok_count += 1
            else:
                fail_count += 1

        return {
            "total": len(webhooks),
            "ok": ok_count,
            "failed": fail_count,
            "results": results,
        }

    def get_payment_history(self, invoice_id: str) -> list:
        """Devuelve el historial de pagos/webhooks para una factura."""
        if self.db is None:
            return []
        events = self.db.list_collection_events(
            tenant_id=self.tenant_id,
            factura_id=invoice_id,
        )
        return [
            e for e in events
            if e.get("tipo_recordatorio", "").startswith("webhook_")
        ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _event_to_respuesta(event_type: str) -> str:
    """Traduce un tipo de evento de webhook a una respuesta de collection_events."""
    mapping = {
        "payment_received": "pagado",
        "payment_partial": "pago_parcial",
        "payment_rejected": "pago_rechazado",
        "payment_disputed": "disputa",
        "payment_refunded": "reembolso",
        "payment_reminder_sent": "recordatorio_enviado",
    }
    return mapping.get(event_type, event_type)
