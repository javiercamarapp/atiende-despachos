# -*- coding: utf-8 -*-
"""routes.py — Endpoints REST del módulo de billing por suscripción (piloto).

Endpoints (todos exigen autenticación por API key, salvo el webhook que
verifica la firma de Conekta):

    POST /api/v1/billing-piloto/checkout     — crea sesión de checkout de Conekta
    POST /api/v1/billing-piloto/webhook      — recibe eventos de Conekta (firma HMAC)
    GET  /api/v1/billing-piloto/subscription — suscripción actual del tenant
    POST /api/v1/billing-piloto/cancel       — cancela la suscripción del tenant
    GET  /api/v1/billing-piloto/invoices     — historial de facturas del tenant

NOTA de ruteo: la plataforma ya monta un billing "comercial" (Stripe/Conekta,
DB-backed) bajo `/api/v1/billing`. Para evitar una colisión de rutas duplicadas
(FastAPI dejaría ganar a la primera registrada), este módulo del piloto se
monta bajo `/api/v1/billing-piloto`. Misma lógica y endpoints, distinto prefijo
(patrón onboarding-wizard vs onboarding).

Sigue el patrón `build_*_router(db, require_api_key)` del proyecto.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from b2b_ai.features.billing.conekta_client import ConektaClient
from b2b_ai.features.billing.models import _reset_state
from b2b_ai.features.billing.plans import list_plans, plan_to_dict
from b2b_ai.features.billing.service import (
    BillingError,
    BillingService,
    subscription_to_dict,
)

ROUTER_PREFIX = "/api/v1/billing-piloto"


# ---------------------------------------------------------------------------
# Schemas de request / response
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    """Solicitud de sesión de checkout de Conekta."""
    plan: str = Field(..., description="Código del plan (starter, pro, business, enterprise)")
    success_url: str = Field(..., description="URL a la que regresa tras pagar")
    cancel_url: str = Field(..., description="URL a la que regresa si cancela")


class CheckoutResponse(BaseModel):
    ok: bool
    checkout_url: str
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    plan_code: str
    amount_mxn: int
    currency: str = "MXN"


class CancelRequest(BaseModel):
    subscription_id: Optional[str] = Field(
        default=None, description="ID de la suscripción a cancelar (opcional; usa la del tenant)"
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_billing_router(db: Any = None,
                         require_api_key: Any = None,
                         require_permission: Any = None) -> APIRouter:
    """Construye el router /api/v1/billing/* del módulo de billing.

    Si se provee `require_permission` (fábrica RBAC de `features.roles`), los
    endpoints de escritura (`checkout`, `cancel`) exigen el permiso
    `billing:write`. Sin él, el router queda igual que antes (sin RBAC), para
    no romper los usos existentes del piloto.
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = BillingService(client=ConektaClient())
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["billing", "piloto"])

    # RBAC opcional: si hay fábrica de permisos, proteger los endpoints de
    # escritura con `billing:write`.
    if require_permission is not None:
        billing_write_dep = require_permission("billing:write")
    else:
        billing_write_dep = None

    def _deps() -> list:
        return [Depends(billing_write_dep)] if billing_write_dep is not None else []

    @router.post(
        "/checkout",
        summary="Crea una sesión de checkout de Conekta para un plan.",
        response_model=CheckoutResponse,
        dependencies=_deps(),
    )
    def create_checkout(
        req: CheckoutRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> CheckoutResponse:
        """Crea el checkout y devuelve la URL de pago (tarjeta/SPEI/OXXO)."""
        tenant_id = auth_info.get("tenant_id")
        try:
            result = service.create_checkout(
                tenant_id=tenant_id,
                plan=req.plan,
                success_url=req.success_url,
                cancel_url=req.cancel_url,
            )
        except BillingError as exc:
            raise HTTPException(
                status_code=400 if exc.code != "conekta_error" else 502,
                detail=exc.message,
            )
        return CheckoutResponse(
            ok=True,
            checkout_url=result["checkout_url"],
            order_id=result.get("order_id"),
            customer_id=result.get("customer_id"),
            plan_code=result["plan_code"],
            amount_mxn=result["amount_mxn"],
        )

    @router.post(
        "/webhook",
        summary="Recibe eventos de pago de Conekta (webhook firmado).",
    )
    async def webhook(request: Request):
        """Procesa un evento de Conekta. Verifica la firma HMAC si viene."""
        raw_body = await request.body()
        payload = await request.json()
        signature = request.headers.get("X-Conekta-Signature", "")

        try:
            result = service.handle_webhook_event(payload, signature)
        except BillingError as exc:
            raise HTTPException(status_code=401, detail=exc.message)

        return {"ok": True, **result}

    @router.get(
        "/subscription",
        summary="Devuelve la suscripción actual del tenant.",
    )
    def get_subscription(auth_info: dict = Depends(auth_dep)):
        """Suscripción actual del tenant autenticado (o null si no tiene)."""
        from b2b_ai.features.billing.models import get_subscription_by_tenant
        tenant_id = auth_info.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Se requiere tenant_id")
        sub = get_subscription_by_tenant(tenant_id)
        if sub is None:
            return {"ok": True, "subscription": None}
        return {"ok": True, "subscription": subscription_to_dict(sub)}

    @router.post(
        "/cancel",
        summary="Cancela la suscripción del tenant.",
        dependencies=_deps(),
    )
    def cancel_subscription(
        req: CancelRequest = CancelRequest(),
        auth_info: dict = Depends(auth_dep),
    ):
        """Cancela la suscripción (la del tenant por defecto)."""
        tenant_id = auth_info.get("tenant_id")
        from b2b_ai.features.billing.models import get_subscription_by_tenant
        sub = get_subscription_by_tenant(tenant_id) if tenant_id else None
        if sub is None:
            raise HTTPException(status_code=404, detail="No hay suscripción activa")
        try:
            canceled = service.cancel_subscription(sub.id)
        except BillingError as exc:
            raise HTTPException(status_code=400, detail=exc.message)
        return {"ok": True, "subscription": subscription_to_dict(canceled)}

    @router.get(
        "/invoices",
        summary="Historial de facturas del tenant.",
    )
    def get_invoices(auth_info: dict = Depends(auth_dep)):
        """Lista las facturas emitidas para el tenant (más recientes primero)."""
        tenant_id = auth_info.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Se requiere tenant_id")
        return {
            "ok": True,
            "invoices": service.get_invoice_history(tenant_id),
        }

    @router.get(
        "/plans",
        summary="Catálogo de planes de suscripción disponibles.",
    )
    def get_plans(auth_info: dict = Depends(auth_dep)):
        """Devuelve los planes de Likida AI con su pricing en MXN."""
        return {
            "ok": True,
            "currency": "MXN",
            "plans": [plan_to_dict(p) for p in list_plans()],
        }

    return router
