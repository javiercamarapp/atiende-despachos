# -*- coding: utf-8 -*-
"""
api.py — Endpoints REST del onboarding (/api/v1/onboarding/*).

Endpoints (requieren API key en el header `X-API-Key`):

    GET  /api/v1/onboarding/status            estado del wizard + score.
    GET  /api/v1/onboarding/steps             definiciones de todos los pasos.
    GET  /api/v1/onboarding/step/{step}       datos de un paso específico.
    PUT  /api/v1/onboarding/step/{step}       envía/valida/persiste un paso.
    POST /api/v1/onboarding/complete          cierra el onboarding.
    GET  /api/v1/onboarding/plans             opciones de planes con precios.
    GET  /api/v1/onboarding/erp-options       opciones de ERP disponibles.

El router se construye con `build_onboarding_router(db, require_api_key)`.
El `tenant_id` se resuelve del scope de la API key (como el resto de /api/v1);
si la key no tiene tenant, se rechaza (onboarding es por cliente).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from b2b_ai.onboarding.wizard import (
    OnboardingWizard, OnboardingError,
    STEP_ORDER, STEP_NAMES, PLAN_DETAILS, ERP_OPTIONS,
)
from b2b_ai.onboarding.checklist import OnboardingChecklist
from b2b_ai.db.tenants import TenantNotFoundError


# ----------------------------------------------------------------------- #
# Pydantic schemas para request bodies
# ----------------------------------------------------------------------- #

class CompanyProfileBody(BaseModel):
    """Paso 1: Perfil de la empresa."""
    name: str = Field(..., description="Nombre legal de la empresa")
    rfc: str = Field(..., description="RFC del SAT (12-13 caracteres)")
    address: str = Field(..., description="Domicilio fiscal completo")
    contact_name: str = Field(..., description="Nombre del contacto principal")
    contact_email: str = Field(..., description="Email del contacto principal")
    contact_phone: Optional[str] = Field(None, description="Teléfono de contacto")
    industry: Optional[str] = Field(None, description="Giro / industria")


class SATCredentialsBody(BaseModel):
    """Paso 2: Credenciales SAT."""
    ciec: str = Field(..., description="Clave CIEC del SAT (6+ caracteres)")
    efirma_certificado: Optional[str] = Field(
        None, description="Ruta o contenido del certificado (.cer) de e.firma")
    efirma_llave: Optional[str] = Field(
        None, description="Ruta o contenido de la llave privada (.key) de e.firma")
    efirma_password: Optional[str] = Field(
        None, description="Contraseña de la llave privada")


class ERPConnectionBody(BaseModel):
    """Paso 3: Conexión del ERP."""
    erp: str = Field(..., description="Nombre del ERP: ContPAQi, Aspel, o CSV")
    # Para ContPAQi / Aspel
    credentials_host: Optional[str] = Field(None, description="Host del ERP")
    credentials_user: Optional[str] = Field(None, description="Usuario del ERP")
    credentials_password: Optional[str] = Field(None, description="Contraseña del ERP")
    # Para CSV
    csv_file: Optional[str] = Field(None, description="Ruta del archivo CSV")
    csv_path: Optional[str] = Field(None, description="Ruta alternativa del CSV")


class BillingPlanBody(BaseModel):
    """Paso 4: Selección de plan de facturación."""
    plan: str = Field(..., description="Plan: basico, profesional, o enterprise")


class CFDIUploadBody(BaseModel):
    """Paso 5: Prueba de CFDI."""
    cfdi_xml: str = Field(..., description="Contenido XML del CFDI de prueba")


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

    # ------------------------------------------------------------------ #
    # Estado general
    # ------------------------------------------------------------------ #

    @router.get("/status",
                summary="Estado del onboarding + score de readiness.")
    def onboarding_status(auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            wiz = OnboardingWizard(db, tenant_id=tenant_id).status()
            score = OnboardingChecklist(db, tenant_id=tenant_id).evaluate()
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"onboarding": wiz, "checklist": score}

    # ------------------------------------------------------------------ #
    # Definiciones de pasos / planes / ERPs
    # ------------------------------------------------------------------ #

    @router.get("/steps",
                summary="Lista de definiciones de todos los pasos del wizard.")
    def onboarding_steps(auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            wiz = OnboardingWizard(db, tenant_id=tenant_id)
            return {"steps": wiz.get_step_definitions()}
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))

    @router.get("/plans",
                summary="Opciones de planes de facturación con precios.")
    def onboarding_plans():
        return {"plans": list(PLAN_DETAILS.values())}

    @router.get("/erp-options",
                summary="Opciones de ERP disponibles.")
    def onboarding_erp_options():
        return {"erp_options": ERP_OPTIONS}

    # ------------------------------------------------------------------ #
    # Operación sobre un paso
    # ------------------------------------------------------------------ #

    @router.get("/step/{step}",
                summary="Lee los datos de un paso específico.")
    def onboarding_get_step(step: int,
                            auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            result = OnboardingWizard(db, tenant_id=tenant_id).get_step(step)
        except OnboardingError as exc:
            raise HTTPException(400, str(exc))
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return result

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

    # ------------------------------------------------------------------ #
    # Compleción del onboarding
    # ------------------------------------------------------------------ #

    @router.post("/complete",
                 summary="Cierra el onboarding (valida que todos los pasos estén completos).")
    def onboarding_complete(auth_info: dict = Depends(require_api_key)):
        tenant_id = _ensure_tenant(_scope(auth_info))
        try:
            wiz = OnboardingWizard(db, tenant_id=tenant_id)
            result = wiz.complete()
            checklist = OnboardingChecklist(db, tenant_id=tenant_id).evaluate()
        except OnboardingError as exc:
            raise HTTPException(400, str(exc))
        except TenantNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "onboarding": result, "checklist": checklist}

    return router
