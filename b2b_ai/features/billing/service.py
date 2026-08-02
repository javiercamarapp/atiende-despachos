# -*- coding: utf-8 -*-
"""service.py — BillingService: orquesta la lógica de negocio de billing.

Depende de `ConektaClient` (wrapper de la API) y de las entidades de
`models.py`. Sigue el patrón de servicio del proyecto (clase con métodos de
dominio que mutan el store en memoria, con `_reset_state()` para tests).

Operaciones:
    start_trial(tenant_id, plan)              — inicia piloto 30 días
    convert_trial_to_paid(subscription_id)    — convierte trial -> activo
    get_invoice_history(tenant_id)            — historial de facturas
    handle_payment_failed(subscription_id)    — marca pago fallido
    create_checkout(tenant_id, plan, success, cancel) — URL de checkout
    handle_webhook_event(payload, signature)  — procesa evento de proveedor
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from b2b_ai.features.billing import models as store
from b2b_ai.features.billing.conekta_client import (
    ConektaAPIError,
    ConektaClient,
    ConektaWebhookError,
)
from b2b_ai.features.billing.models import (
    Invoice,
    InvoiceStatus,
    PaymentEvent,
    PaymentEventType,
    PaymentMethod,
    PaymentMethodType,
    Subscription,
    SubscriptionStatus,
    _utcnow,
    _utcnow_iso,
)
from b2b_ai.features.billing.plans import (
    DEFAULT_TRIAL_PLAN,
    TRIAL_DAYS,
    get_plan,
    get_plan_or_none,
    plan_to_dict,
)


class BillingError(Exception):
    """Error de dominio del billing, con código estable."""
    def __init__(self, message: str, code: str = "billing_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class BillingService:
    """Lógica de negocio del subsistema de cobros por suscripción."""

    def __init__(self, client: Optional[ConektaClient] = None) -> None:
        self.client = client or ConektaClient()

    # ------------------------------------------------------------------
    # Ciclo de vida de la suscripción
    # ------------------------------------------------------------------

    def start_trial(self, tenant_id: str, plan: Optional[str] = None) -> Subscription:
        """Inicia el piloto de 30 días para un tenant.

        Crea la suscripción en estado TRIALING con trial_start/end a 30 días.
        Si el tenant ya tiene una suscripción activa o en trial, se rechaza.
        """
        if not tenant_id:
            raise BillingError("tenant_id es obligatorio", code="missing_tenant")
        existing = store.get_subscription_by_tenant(tenant_id)
        if existing and existing.status in (
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
        ):
            raise BillingError(
                "El tenant ya tiene una suscripción activa o en prueba.",
                code="subscription_exists",
            )

        plan_code = (plan or DEFAULT_TRIAL_PLAN).lower()
        plan_obj = get_plan_or_none(plan_code)
        if plan_obj is None:
            raise BillingError(
                f"Plan inválido '{plan_code}'", code="invalid_plan"
            )

        now = _utcnow()
        trial_end = now + timedelta(days=TRIAL_DAYS)

        sub = Subscription(
            tenant_id=tenant_id,
            plan_code=plan_obj.code,
            status=SubscriptionStatus.TRIALING,
            price_mxn=plan_obj.price_mxn,
            trial_start=_utcnow_iso(),
            trial_end=trial_end.isoformat(),
            current_period_start=_utcnow_iso(),
            current_period_end=trial_end.isoformat(),
            metadata={"trial_days": TRIAL_DAYS, "source": "onboarding_piloto"},
        )
        store.save_subscription(sub)
        return sub

    def create_trial(self, tenant_id: str) -> Subscription:
        """Crea una suscripción de prueba de 30 días gratis para el tenant.

        Alias de `start_trial` con el plan por defecto del piloto; si el
        tenant ya tiene una suscripción activa o en trial, se rechaza.
        """
        return self.start_trial(tenant_id, plan=DEFAULT_TRIAL_PLAN)

    def activate_pilot(self, tenant_id: str, plan: str,
                       payment_method_id: Optional[str] = None) -> Subscription:
        """Activa el plan del piloto de pago para un tenant.

        Crea la suscripción en estado ACTIVE para el plan dado, registra el
        método de pago (si se provee) y crea el cliente/suscripción en Conekta
        (modo mock en tests). Emite la primera factura del periodo.

        Reglas:
          - tenant_id obligatorio;
          - plan debe existir en el catálogo;
          - si el tenant ya tiene una suscripción activa o en trial, se rechaza.
        """
        if not tenant_id:
            raise BillingError("tenant_id es obligatorio", code="missing_tenant")
        existing = store.get_subscription_by_tenant(tenant_id)
        if existing and existing.status in (
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
        ):
            raise BillingError(
                "El tenant ya tiene una suscripción activa o en prueba.",
                code="subscription_exists",
            )

        plan_code = (plan or "").lower()
        plan_obj = get_plan_or_none(plan_code)
        if plan_obj is None:
            raise BillingError(f"Plan inválido '{plan_code}'", code="invalid_plan")

        # Crea el cliente y la suscripción en Conekta (mock en tests).
        try:
            customer = self.client.create_customer(
                rfc=plan_obj.code.value,
                email=f"billing+{tenant_id}@likida.ai",
                name=f"Tenant {tenant_id}",
            )
            customer_id = customer.get("id")
        except ConektaAPIError as exc:
            raise BillingError(f"Conekta: {exc.message}", code="conekta_error")

        try:
            provider_sub = self.client.create_subscription(
                customer_id=customer_id,
                plan_id=plan_obj.code.value,
                payment_method_id=payment_method_id,
            )
            provider_sub_id = provider_sub.get("id")
        except ConektaAPIError as exc:
            raise BillingError(f"Conekta: {exc.message}", code="conekta_error")

        now = _utcnow()
        period_end = now + timedelta(days=30)

        sub = Subscription(
            tenant_id=tenant_id,
            plan_code=plan_obj.code,
            status=SubscriptionStatus.ACTIVE,
            price_mxn=plan_obj.price_mxn,
            provider_customer_id=customer_id,
            provider_subscription_id=provider_sub_id,
            current_period_start=_utcnow_iso(),
            current_period_end=period_end.isoformat(),
            metadata={"source": "pilot_activation", "payment_method_id": payment_method_id},
        )
        store.save_subscription(sub)

        # Registra el medio de pago si viene.
        if payment_method_id:
            store.add_payment_method(PaymentMethod(
                tenant_id=tenant_id,
                provider_customer_id=customer_id,
                provider_payment_method_id=payment_method_id,
                method_type=PaymentMethodType.CARD,
                is_default=True,
            ))

        # Emite la primera factura del periodo.
        invoice = Invoice(
            tenant_id=tenant_id,
            subscription_id=sub.id,
            amount_mxn=plan_obj.price_mxn,
            status=InvoiceStatus.PAID,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
            paid_at=_utcnow_iso(),
            metadata={"source": "pilot_activation"},
        )
        store.add_invoice(invoice)
        return sub

    def convert_trial_to_paid(self, subscription_id: str) -> Subscription:
        """Convierte una suscripción en trial a activa (pago confirmado)."""
        sub = store.get_subscription_by_id(subscription_id)
        if sub is None:
            raise BillingError(
                f"Suscripción no encontrada: {subscription_id}",
                code="subscription_not_found",
            )
        if sub.status != SubscriptionStatus.TRIALING:
            raise BillingError(
                f"No se puede convertir: estado actual '{sub.status.value}'.",
                code="invalid_status",
            )

        sub.status = SubscriptionStatus.ACTIVE
        # Periodo de cobro mensual a partir de la conversión.
        now = _utcnow()
        period_end = now + timedelta(days=30)
        sub.current_period_start = now.isoformat()
        sub.current_period_end = period_end.isoformat()

        # Crea la suscripción en Conekta (modo mock en tests) y guarda el id.
        try:
            provider_sub = self.client.create_subscription(
                customer_id=sub.provider_customer_id or f"cus_{sub.tenant_id}",
                plan_id=sub.plan_code.value,
            )
            sub.provider_subscription_id = provider_sub.get("id")
        except ConektaAPIError:
            # Sin proveedor disponible: la suscripción queda activa localmente.
            pass

        store.save_subscription(sub)

        # Emite la primera factura del periodo.
        invoice = Invoice(
            tenant_id=sub.tenant_id,
            subscription_id=sub.id,
            amount_mxn=sub.price_mxn,
            status=InvoiceStatus.PAID,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
            paid_at=_utcnow_iso(),
            metadata={"source": "trial_to_paid"},
        )
        store.add_invoice(invoice)
        return sub

    def cancel_subscription(self, subscription_id: str) -> Subscription:
        """Cancela una suscripción (idempotente)."""
        sub = store.get_subscription_by_id(subscription_id)
        if sub is None:
            raise BillingError(
                f"Suscripción no encontrada: {subscription_id}",
                code="subscription_not_found",
            )
        if sub.status == SubscriptionStatus.CANCELED:
            return sub
        sub.status = SubscriptionStatus.CANCELED
        sub.canceled_at = _utcnow_iso()
        store.save_subscription(sub)
        return sub

    # ------------------------------------------------------------------
    # Facturas
    # ------------------------------------------------------------------

    def get_invoice_history(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Historial de facturas del tenant (más recientes primero)."""
        sub = store.get_subscription_by_tenant(tenant_id)
        if sub is None:
            return []
        return [inv.to_dict() for inv in store.get_invoices(sub.id)]

    # ------------------------------------------------------------------
    # Manejo de pagos
    # ------------------------------------------------------------------

    def handle_payment_failed(self, subscription_id: str) -> Subscription:
        """Marca una suscripción como past_due tras un pago fallido."""
        sub = store.get_subscription_by_id(subscription_id)
        if sub is None:
            raise BillingError(
                f"Suscripción no encontrada: {subscription_id}",
                code="subscription_not_found",
            )
        if sub.status in (SubscriptionStatus.CANCELED, SubscriptionStatus.UNPAID):
            return sub
        sub.status = SubscriptionStatus.PAST_DUE
        store.save_subscription(sub)
        return sub

    def mark_paid(self, subscription_id: str) -> Subscription:
        """Marca una suscripción como activa tras un pago exitoso."""
        sub = store.get_subscription_by_id(subscription_id)
        if sub is None:
            raise BillingError(
                f"Suscripción no encontrada: {subscription_id}",
                code="subscription_not_found",
            )
        if sub.status == SubscriptionStatus.CANCELED:
            return sub
        was_past_due = sub.status == SubscriptionStatus.PAST_DUE
        sub.status = SubscriptionStatus.ACTIVE
        now = _utcnow()
        sub.current_period_start = now.isoformat()
        sub.current_period_end = (now + timedelta(days=30)).isoformat()
        store.save_subscription(sub)
        if was_past_due:
            # Emite factura del periodo reiniciado.
            invoice = Invoice(
                tenant_id=sub.tenant_id,
                subscription_id=sub.id,
                amount_mxn=sub.price_mxn,
                status=InvoiceStatus.PAID,
                period_start=sub.current_period_start,
                period_end=sub.current_period_end,
                paid_at=_utcnow_iso(),
                metadata={"source": "recovery"},
            )
            store.add_invoice(invoice)
        return sub

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    def create_checkout(self, tenant_id: str, plan: str,
                        success_url: str, cancel_url: str) -> Dict[str, Any]:
        """Crea una sesión de checkout en Conekta y devuelve la URL de pago."""
        if not tenant_id:
            raise BillingError("tenant_id es obligatorio", code="missing_tenant")
        plan_obj = get_plan_or_none(plan)
        if plan_obj is None:
            raise BillingError(f"Plan inválido '{plan}'", code="invalid_plan")

        # Asegura cliente en Conekta (mock en tests).
        try:
            customer = self.client.create_customer(
                rfc=str(plan_obj.code.value),
                email=f"billing+{tenant_id}@likida.ai",
                name=f"Tenant {tenant_id}",
            )
        except ConektaAPIError as exc:
            raise BillingError(f"Conekta: {exc.message}", code="conekta_error")

        # Crea la sesión de checkout para el plan.
        try:
            order = self.client.create_checkout_session(
                plan_id=plan_obj.code.value,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except ConektaAPIError as exc:
            raise BillingError(f"Conekta: {exc.message}", code="conekta_error")

        checkout = order.get("checkout") or {}
        return {
            "checkout_url": checkout.get("url") or "",
            "order_id": order.get("id"),
            "customer_id": customer.get("id"),
            "plan_code": plan_obj.code.value,
            "amount_mxn": plan_obj.price_mxn,
            "currency": "MXN",
        }

    # ------------------------------------------------------------------
    # Webhooks del proveedor
    # ------------------------------------------------------------------

    def handle_webhook_event(self, event_payload: Dict[str, Any],
                             signature: str = "") -> Dict[str, Any]:
        """Valida la firma y aplica el efecto del evento sobre el billing."""
        try:
            routed = self.client.process_webhook(event_payload, signature)
        except ConektaWebhookError as exc:
            raise BillingError(str(exc), code="invalid_webhook_signature")

        ev_type = PaymentEventType(routed.get("payment_event_type", "unknown"))
        object_id = routed.get("object_id")
        # Buscar la suscripción por object_id del proveedor o dejar None.
        sub_id = self._find_subscription_by_provider_id(object_id)

        event = PaymentEvent(
            event_type=ev_type,
            provider_event_id=object_id,
            subscription_id=sub_id,
            payload=event_payload,
        )
        store.add_payment_event(event)

        if not routed.get("handled"):
            return {**routed, "subscription_id": sub_id}

        # Aplicar efecto según el tipo de evento.
        if routed.get("mark_paid"):
            if sub_id:
                self.mark_paid(sub_id)
            return {**routed, "subscription_id": sub_id}
        if routed.get("mark_failed"):
            if sub_id:
                self.handle_payment_failed(sub_id)
            return {**routed, "subscription_id": sub_id}
        if routed.get("mark_canceled"):
            if sub_id:
                self.cancel_subscription(sub_id)
            return {**routed, "subscription_id": sub_id}
        return {**routed, "subscription_id": sub_id}

    @staticmethod
    def _find_subscription_by_provider_id(provider_id: Optional[str]) -> Optional[str]:
        """Busca el id interno de una suscripción por su id de proveedor."""
        if not provider_id:
            return None
        for sub in store._subscriptions_by_id.values():
            if sub.provider_subscription_id == provider_id:
                return sub.id
        return None


# ---------------------------------------------------------------------------
# Helper de serialización
# ---------------------------------------------------------------------------

def subscription_to_dict(sub: Subscription) -> Dict[str, Any]:
    """Serializa una suscripción con datos del plan embebidos."""
    data = sub.to_dict()
    plan = get_plan_or_none(sub.plan_code.value)
    if plan:
        data["plan"] = plan_to_dict(plan)
    return data
