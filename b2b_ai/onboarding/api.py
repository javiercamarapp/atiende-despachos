# -*- coding: utf-8 -*-
"""
api.py — Endpoints REST del onboarding (/api/v1/onboarding/*).

Endpoints (requieren API key en el header `X-API-Key`):

    GET  /api/v1/onboarding/status        estado del wizard + score.
    PUT  /api/v1/onboarding/step/{step}   envía/valida/persiste un paso.
    POST /api/v1/onboarding/complete      cierra el onboarding.

El router se construye con `build_onboarding_router(db, require_api_key)`.
El `tenant_id` se resuelve del scope de la API key (como el resto de /api/v1);
si la key no tiene tenant, se rechaza (onboarding es por cliente).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from b2b_ai.onboarding.wizard import (
    OnboardingWizard, OnboardingError,
)
from b2b_ai.onboarding.checklist import OnboardingChecklist
from b2b_ai.db.tenants import TenantNotFoundError


def build_onboarding_router(db, require_api_key):
    """Devuelve un APIRouter del wizard de onboarding.

    Args:
        db:              instancia de Database.
        require_api_key: dependencia de auth (Depends).
    """
    router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

    def _scope(auth_info) -> Optional[int]:
        return auth_info.get("tenant_id") if auth_info else None

    def _ensure_tenant(tenant_id: Optional[int]) -> int:
        if not tenant_id:
            raise HTTPException(
                403, "Esta API key no está ligada a un tenant; "
                     "el onboarding requiere tenant.")
        return tenant_id

    @router.get("/status", summary="Estado del onboarding + score de readiness.")
    def onboarding_status(auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            wiz = OnboardingWizard(db, tenant_id=tenant_id).status()
            score = OnboardingChecklist(db, tenant_id=tenant_id).evaluate()
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"onboarding": wiz, "checklist": score}

    @router.put("/step/{step}",
                summary="Envía y valida un paso del wizard.")
    def onboarding_step(step: int,
                        data: Dict[str, Any] = Body(default={}),
                        auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            result = OnboardingWizard(db, tenant_id=tenant_id)\
                .set_step(step, dict(data or {}))
        except OnboardingError as exc:
            raise HTTPException(400, str(exc))
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "onboarding": result}

    @router.post("/complete", summary="Cierra el onboarding y crea usuarios.")
    def onboarding_complete(auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            wiz = OnboardingWizard(db, tenant_id=tenant_id)
            users_created = wiz.create_team_users()
            result = wiz.complete()
            checklist = OnboardingChecklist(db, tenant_id=tenant_id).evaluate()
        except OnboardingError as exc:
            raise HTTPException(400, str(exc))
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "users_created": users_created,
                "onboarding": result, "checklist": checklist}

    return router
