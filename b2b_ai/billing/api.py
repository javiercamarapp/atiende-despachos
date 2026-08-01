# -*- coding: utf-8 -*-
"""
api.py — Endpoints REST de facturación (/api/v1/billing/*).

Endpoints (todos requieren API key en el header `X-API-Key`):

    POST /api/v1/billing/checkout      inicia un checkout (crea cliente si
                                       no existe + procesa el pago).
    POST /api/v1/billing/subscription  crea/activa una suscripción a un plan.
    GET  /api/v1/billing/invoices      lista las facturas del tenant.
    GET  /api/v1/billing/plans         lista los planes y precios.
    POST /api/v1/billing/webhook       recibe eventos del proveedor.

El router se construye con `build_billing_router(db, require_api_key,
provider=None)`. Si no se inyecta un proveedor, se usa `get_default_provider()`
(base.py): en demo/tests devuelve el MockPaymentProvider (sin red); en
producción se resuelve por la config de entorno (B2B_STRIPE_KEY /
B2B_CONEXTA_KEY / B2B_PAYMENTS_PROVIDER).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from b2b_ai.billing.base import (
    PaymentError,
    PaymentProvider,
    get_default_provider,
)
from b2b_ai.billing.models import (
    CheckoutRequest,
    PaymentMethodType,
    Provider,
    WebhookPayload,
)
from b2b_ai.billing.pricing import get_plan, list_plans


def build_billing_router(db, require_api_key, provider: Optional[PaymentProvider] = None):
    """Devuelve un APIRouter de facturación.

    Args:
        db:              instancia de Database.
        require_api_key: dependencia de auth (Depends).
        provider:        PaymentProvider inyectable (tests usan el mock).
    """
    if provider is None:
        provider = get_default_provider()

    router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

    # ------------------------------------------------------------------ #
    # Webhook signature verification
    # ------------------------------------------------------------------ #
    def _verify_webhook_signature(payload_body: bytes, signature: str,
                                   secret: str, provider_name: str) -> bool:
        """Verifica la firma HMAC de un webhook (Stripe o Conekta).

        - Stripe: firma en header `Stripe-Signature` (formato v1=sha256=...)
        - Conekta: firma en header `Conekta-Signature`
        - Genérico: HMAC-SHA256

        Retorna True si la firma es válida o si no hay secret configurado
        (modo demo — en producción el secret DEBE estar configurado).
        """
        if not secret:
            # Sin secret configurado: modo demo. Log warning pero permite.
            return True
        expected = hmac.new(
            secret.encode("utf-8"), payload_body, hashlib.sha256
        ).hexdigest()
        # Normalizar: comparar sin prefijos de formato.
        clean_sig = signature.split("=")[-1] if "=" in signature else signature
        return hmac.compare_digest(clean_sig, expected)

    def _get_webhook_secret(provider_name: str) -> str:
        """Obtiene el secret del webhook para el proveedor."""
        env_map = {
            "stripe": "B2B_STRIPE_WEBHOOK_SECRET",
            "conekta": "B2B_CONEXTA_WEBHOOK_SECRET",
        }
        env_key = env_map.get(provider_name.lower(), "")
        return os.environ.get(env_key, "") if env_key else ""

    def _scope(auth_info) -> Optional[int]:
        return auth_info.get("tenant_id") if auth_info else None

    def _resolve_customer(tenant_id: int, email: str, name: str) -> dict:
        """Devuelve el cliente del tenant con ese email, creándolo si falta."""
        cust = db.get_billing_customer_by_email(tenant_id, email)
        if cust is None:
            provider_cust = provider.create_customer(email, name)
            cid = db.create_billing_customer(
                tenant_id, email, name, provider.provider.value,
                provider_cust.provider_customer_id)
            cust = {"id": cid, "email": email, "name": name,
                    "provider_customer_id": provider_cust.provider_customer_id}
        return cust

    # ------------------------------------------------------------------ #
    @router.post("/checkout", summary="Inicia un checkout y procesa el pago.")
    def checkout(req: CheckoutRequest,
                 auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        plan = get_plan(req.plan)
        if plan is None or plan.price_mxn <= 0:
            raise HTTPException(400, f"Plan inválido: {req.plan} (usa Enterprise "
                                     "solo por cotización).")
        try:
            cust = _resolve_customer(tenant, req.email, req.name)
            if req.payment_method_type in (PaymentMethodType.SPEI,
                                           PaymentMethodType.OXXO):
                # Los métodos offline requieren el cliente del proveedor.
                result = provider.process_payment(
                    cust["provider_customer_id"], plan.price_mxn,
                    currency=req.currency, method=req.payment_method_type)
            else:
                result = provider.process_payment(
                    req.payment_method_id or cust["provider_customer_id"],
                    plan.price_mxn, currency=req.currency)
        except PaymentError as exc:
            raise HTTPException(400, exc.message)

        # Persistimos la factura del checkout.
        inv_id = db.create_billing_invoice(
            tenant, cust["id"], plan.price_mxn, req.currency, result.status,
            result.reference)
        db.log_call("billing", "checkout", entity="invoice",
                    entity_id=str(inv_id), payload={"plan": req.plan},
                    status=result.status, tenant_id=tenant)
        return {"ok": result.ok, "checkout_id": inv_id,
                "plan": plan.to_dict(), "payment": result.model_dump(),
                "tenant_id": tenant}

    @router.post("/subscription", summary="Crea/activa una suscripción a un plan.")
    def subscribe(req: CheckoutRequest,
                  auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        plan = get_plan(req.plan)
        if plan is None:
            raise HTTPException(400, f"Plan inválido: {req.plan}")
        try:
            cust = _resolve_customer(tenant, req.email, req.name)
            sub = provider.create_subscription(
                cust["provider_customer_id"], plan.key,
                payment_method_id=req.payment_method_id)
        except PaymentError as exc:
            raise HTTPException(400, exc.message)
        sub_id = db.create_billing_subscription(
            tenant, cust["id"], plan.key, provider.provider.value,
            sub.provider_subscription_id, sub.status.value,
            sub.current_period_start, sub.current_period_end)
        db.log_call("billing", "subscribe", entity="subscription",
                    entity_id=str(sub_id), payload={"plan": req.plan},
                    status="ok", tenant_id=tenant)
        return {"ok": True, "subscription_id": sub_id,
                "plan": plan.to_dict(), "status": sub.status.value,
                "provider_subscription_id": sub.provider_subscription_id,
                "tenant_id": tenant}

    @router.get("/invoices", summary="Lista las facturas del tenant.")
    def list_invoices(limit: int = Query(default=100, le=1000),
                      auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        rows = db.list_billing_invoices(tenant_id=tenant, limit=limit)
        return {"count": len(rows), "invoices": rows, "tenant_id": tenant}

    @router.get("/plans", summary="Lista los planes y precios.")
    def plans(auth_info: dict = Depends(require_api_key)):
        return {"plans": list_plans()}

    @router.post("/webhook", summary="Recibe eventos del proveedor de pagos.")
    def webhook(payload: WebhookPayload, request: Request,
                auth_info: dict = Depends(require_api_key)):
        """Procesa un evento de webhook del proveedor.

        Verifica la firma HMAC del webhook antes de procesar. La firma se
        extrae del header correspondiente al proveedor (Stripe-Signature,
        Conekta-Signature). Si no hay secret configurado (modo demo), se
        permite sin verificación.
        """
        # Verificar firma del webhook.
        provider_name = payload.provider.value if payload.provider else ""
        secret = _get_webhook_secret(provider_name)
        if secret:
            # Obtener firma del header correspondiente.
            sig_header = ""
            if provider_name.lower() == "stripe":
                sig_header = request.headers.get("stripe-signature", "")
            elif provider_name.lower() == "conekta":
                sig_header = request.headers.get("conekta-signature", "")
            else:
                sig_header = request.headers.get("x-webhook-signature", "")
            # Leer el body raw para verificar la firma.
            # FastAPI ya parseó el body, pero necesitamos el raw bytes.
            # Re-serializamos para la verificación HMAC.
            import json as _json
            raw_body = _json.dumps(payload.model_dump(), default=str).encode("utf-8")
            if not _verify_webhook_signature(raw_body, sig_header, secret,
                                              provider_name):
                raise HTTPException(status_code=401,
                                    detail="Firma de webhook inválida.")

        result = provider.webhook_handler(payload.event_type, payload.data)
        if result.get("mark_paid") and result.get("invoice_id"):
            db.mark_billing_invoice_paid_by_ref(
                result["invoice_id"], provider.provider.value)
        db.log_call("billing", "webhook", entity="event",
                    entity_id=payload.event_type,
                    payload={"provider": payload.provider.value},
                    status="ok", tenant_id=_scope(auth_info))
        return {"received": True, "result": result}

    return router
