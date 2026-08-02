# -*- coding: utf-8 -*-
"""api.py — Endpoints FastAPI de feature flags.

Endpoints:
    GET  /api/v1/features          lista todas las flags del tenant
    GET  /api/v1/features/{name}   estado de una flag específica
    PUT  /api/v1/features/{name}   crea/actualiza una flag
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.flags import FeatureFlags


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FeatureFlagUpdate(BaseModel):
    enabled: bool
    rollout_percentage: int = Field(100, ge=0, le=100)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_features_router(db, require_api_key):
    """Devuelve un APIRouter /api/v1/features/*."""
    router = APIRouter(prefix="/api/v1/features", tags=["features"])

    @router.get("", summary="Lista todas las feature flags del tenant.")
    def list_flags(auth_info: dict = Depends(require_api_key)):
        tenant_id = auth_info.get("tenant_id")
        ff = FeatureFlags(db)
        return ff.get_all_flags(tenant_id)

    @router.get("/{name}", summary="Estado de una feature flag.")
    def get_flag(
        name: str,
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = auth_info.get("tenant_id")
        ff = FeatureFlags(db)
        enabled = ff.is_enabled(name, tenant_id)
        return {
            "name": name,
            "tenant_id": tenant_id,
            "enabled": enabled,
        }

    @router.put("/{name}", summary="Crea o actualiza una feature flag.")
    def update_flag(
        name: str,
        req: FeatureFlagUpdate,
        auth_info: dict = Depends(require_api_key),
    ):
        tenant_id = auth_info.get("tenant_id")
        if tenant_id is None:
            raise HTTPException(400, "Se requiere tenant para actualizar flags.")
        ff = FeatureFlags(db)
        if req.enabled:
            ff.enable(name, tenant_id, rollout_percentage=req.rollout_percentage)
        else:
            ff.disable(name, tenant_id)
        return {
            "ok": True,
            "name": name,
            "enabled": req.enabled,
            "rollout_percentage": req.rollout_percentage,
        }

    return router
