# -*- coding: utf-8 -*-
"""routes.py — Endpoints REST del Onboarding Wizard del piloto (Día 1).

Todos los endpoints exigen autenticación por API key (require_api_key).

    POST /api/v1/onboarding-wizard/start                     crea sesión
    GET  /api/v1/onboarding-wizard/{session_id}              estado actual
    POST /api/v1/onboarding-wizard/{session_id}/step/{step}  avanza un paso
    POST /api/v1/onboarding-wizard/{session_id}/complete     marca completo

NOTA de ruteo: la plataforma ya monta un onboarding "comercial" (perfil de
empresa / plan / ERP) bajo `/api/v1/onboarding` con `POST /complete`. Para
evitar una colisión de rutas duplicadas (FastAPI dejaría ganar a la primera
registrada), este wizard del piloto se monta bajo `/api/v1/onboarding-wizard`.
La lógica es la misma del spec del task; sólo cambia el prefijo.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from b2b_ai.features.onboarding.models import (
    OnboardingSession,
    OnboardingStep,
)
from b2b_ai.features.onboarding.wizard import (
    OnboardingWizard,
    OnboardingWizardError,
    _reset_state,
)

ROUTER_PREFIX = "/api/v1/onboarding-wizard"


# ---------------------------------------------------------------------------
# Schemas de request / response
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    """Crea una sesión de onboarding. tenant_id opcional (si ya existe)."""
    tenant_id: Optional[str] = Field(
        default=None, description="ID de tenant ya creado (opcional)"
    )


class StepRequest(BaseModel):
    """Payload libre del paso a avanzar."""
    payload: Dict[str, Any] = Field(default_factory=dict, description="Datos del paso")


class StartResponse(BaseModel):
    ok: bool
    session: dict


class StepResponse(BaseModel):
    ok: bool
    session: dict


class CompleteResponse(BaseModel):
    ok: bool
    session: dict
    health: dict


class CheckoutRequest(BaseModel):
    """Inicia el checkout de Conekta para un plan del tenant."""
    plan: str = Field(..., description="Código del plan (starter, pro, business, enterprise)")
    success_url: str = Field(default="", description="URL de regreso tras pagar (opcional)")
    cancel_url: str = Field(default="", description="URL de regreso si cancela (opcional)")


class CheckoutResponse(BaseModel):
    ok: bool
    checkout_url: str
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    plan_code: str
    amount_mxn: int
    currency: str = "MXN"


class CheckoutCallbackRequest(BaseModel):
    """Resultado del pago reportado por Conekta / el proveedor."""
    status: str = Field(..., description="Estado del pago: paid | failed | canceled")
    plan: str = Field(default="", description="Plan contratado")
    payment_method_id: Optional[str] = Field(
        default=None, description="ID del método de pago usado (opcional)"
    )
    order_id: Optional[str] = Field(default=None, description="ID de la orden en Conekta (opcional)")


class CheckoutCallbackResponse(BaseModel):
    ok: bool
    status: str
    subscription: Optional[dict] = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_onboarding_wizard_router(
    db: Any = None,
    require_api_key: Any = None,
) -> APIRouter:
    """Construye el router del wizard de onboarding del piloto."""
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. Nunca construir el router sin auth."
        )
    auth_dep = require_api_key
    service = OnboardingWizard(db=db)
    router = APIRouter(prefix=ROUTER_PREFIX, tags=["onboarding-wizard", "piloto"])

    @router.post(
        "/start",
        summary="Crea una sesión de onboarding nueva.",
        response_model=StartResponse,
    )
    def start(
        req: StartRequest = StartRequest(),
        auth_info: dict = Depends(auth_dep),
    ) -> StartResponse:
        """Inicia el flujo del Día 1 para el primer cliente piloto."""
        session = service.start(tenant_id=req.tenant_id)
        return StartResponse(ok=True, session=session.to_dict())

    @router.get(
        "/{session_id}",
        summary="Devuelve el estado actual de una sesión de onboarding.",
        response_model=StepResponse,
    )
    def get_state(
        session_id: str = Path(..., description="ID de la sesión"),
        auth_info: dict = Depends(auth_dep),
    ) -> StepResponse:
        """Estado de la sesión; sirve para retomar donde quedó si se corta."""
        try:
            session = service.get_session(session_id)
        except OnboardingWizardError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return StepResponse(ok=True, session=session.to_dict())

    @router.post(
        "/{session_id}/step/{step}",
        summary="Valida y avanza un paso del onboarding.",
        response_model=StepResponse,
    )
    def advance(
        req: StepRequest = StepRequest(),
        session_id: str = Path(..., description="ID de la sesión"),
        step: str = Path(..., description="Nombre del paso (tenant, fiscal, ...)"),
        auth_info: dict = Depends(auth_dep),
    ) -> StepResponse:
        """Avanza el flujo ejecutando el siguiente paso con su payload."""
        try:
            session = service.advance_step(session_id, step, req.payload)
        except OnboardingWizardError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return StepResponse(ok=True, session=session.to_dict())

    @router.post(
        "/{session_id}/complete",
        summary="Cierra el onboarding y corre el health check completo.",
        response_model=CompleteResponse,
    )
    def complete(
        session_id: str = Path(..., description="ID de la sesión"),
        auth_info: dict = Depends(auth_dep),
    ) -> CompleteResponse:
        """Marca la sesión como completa y devuelve el checklist de salud."""
        try:
            result = service.complete(session_id)
        except OnboardingWizardError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return CompleteResponse(
            ok=True,
            session=result["session"],
            health=result["health"],
        )

    @router.post(
        "/{session_id}/checkout",
        summary="Inicia el checkout de Conekta para un plan del tenant.",
        response_model=CheckoutResponse,
    )
    def checkout(
        req: CheckoutRequest,
        session_id: str = Path(..., description="ID de la sesión"),
        auth_info: dict = Depends(auth_dep),
    ) -> CheckoutResponse:
        """Crea la sesión de pago de Conekta y devuelve la URL de checkout."""
        try:
            reference = service.start_checkout(
                session_id, req.plan,
                success_url=req.success_url,
                cancel_url=req.cancel_url,
            )
        except OnboardingWizardError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return CheckoutResponse(
            ok=True,
            checkout_url=reference["checkout_url"],
            order_id=reference.get("order_id"),
            customer_id=reference.get("customer_id"),
            plan_code=reference["plan"],
            amount_mxn=reference.get("amount_mxn") or 0,
            currency=reference.get("currency", "MXN"),
        )

    @router.post(
        "/{session_id}/checkout/callback",
        summary="Recibe el resultado del pago y activa/cancela la suscripción.",
        response_model=CheckoutCallbackResponse,
    )
    def checkout_callback(
        req: CheckoutCallbackRequest,
        session_id: str = Path(..., description="ID de la sesión"),
        auth_info: dict = Depends(auth_dep),
    ) -> CheckoutCallbackResponse:
        """Aplica el resultado del pago sobre el billing del tenant.

        - paid    -> activa el plan (activate_pilot) y cierra la sesión.
        - failed / canceled -> registra el fallo; no se activa nada.
        """
        try:
            session = service.get_session(session_id)
        except OnboardingWizardError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        from b2b_ai.features.billing.conekta_client import ConektaClient
        from b2b_ai.features.billing.service import (
            BillingError,
            BillingService,
            subscription_to_dict,
        )
        billing = BillingService(client=ConektaClient())
        status = (req.status or "").strip().lower()

        subscription = None
        if status == "paid":
            plan = (req.plan or "").strip().lower()
            if not plan:
                # Si no se indica plan, se usa el que se guardó en la sesión.
                saved = (session.data.get("checkout") or {})
                plan = (saved.get("plan") or "starter").lower()
            try:
                sub = billing.activate_pilot(
                    tenant_id=session.tenant_id,
                    plan=plan,
                    payment_method_id=req.payment_method_id,
                )
                subscription = subscription_to_dict(sub)
            except BillingError as exc:
                raise HTTPException(status_code=400, detail=exc.message)

        # Persiste el estado del pago en la sesión.
        if "checkout" not in session.data:
            session.data["checkout"] = {}
        session.data["checkout"].update({"status": status})
        session.touch()

        return CheckoutCallbackResponse(
            ok=True,
            status=status,
            subscription=subscription,
        )

    return router
