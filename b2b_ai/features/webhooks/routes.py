# -*- coding: utf-8 -*-
"""
routes.py — Router FastAPI del módulo de Webhooks.

Endpoints:
    POST   /api/v1/webhooks/subscriptions   Crear una suscripción
    GET    /api/v1/webhooks/subscriptions   Listar suscripciones
    GET    /api/v1/webhooks/subscriptions/{id}   Obtener una suscripción
    DELETE /api/v1/webhooks/subscriptions/{id}   Eliminar una suscripción
    POST   /api/v1/webhooks/publish         Publicar un evento (test/trigger)
    GET    /api/v1/webhooks/deliveries      Listar entregas (auditoría)

Todos los endpoints exigen autenticación por API key (require_api_key).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from b2b_ai.features.webhooks.models import (
    WebhookEvent,
    WebhookEventType,
)
from b2b_ai.features.webhooks.service import WebhookService


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------

class CreateSubscriptionRequest(BaseModel):
    url: str = Field(..., description="Endpoint HTTPS que recibirá los POST")
    secret: str = Field(..., description="Secreto compartido para firmar (min 8 chars)")
    event_types: List[str] = Field(
        default_factory=list, description="Eventos a recibir (vacío = todos)"
    )
    active: bool = Field(default=True)

    @field_validator("event_types")
    @classmethod
    def _valid_types(cls, v: List[str]) -> List[str]:
        valid = {e.value for e in WebhookEventType}
        for item in v:
            if item not in valid:
                raise ValueError(f"Tipo de evento inválido: {item}. Válidos: {sorted(valid)}")
        return list(v)


class PublishEventRequest(BaseModel):
    event_type: str = Field(..., description="Uno de los eventos soportados")
    payload: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = Field(default=None)

    @field_validator("event_type")
    @classmethod
    def _valid_event(cls, v: str) -> str:
        valid = {e.value for e in WebhookEventType}
        if v not in valid:
            raise ValueError(f"Tipo de evento inválido: {v}. Válidos: {sorted(valid)}")
        return v


class ApiResponse(BaseModel):
    ok: bool
    message: str = ""
    data: Optional[dict] = None


def build_webhooks_router(db: Any = None, require_api_key: Any = None) -> APIRouter:
    """Construye el router de Webhooks (/api/v1/webhooks/*)."""
    if require_api_key is None:
        raise ValueError("require_api_key es obligatorio. Nunca construir el router sin auth.")
    auth_dep = require_api_key
    service = WebhookService()
    router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

    @router.post("/subscriptions", summary="Crea una suscripción de webhook.",
                 response_model=None)
    def create_subscription(req: CreateSubscriptionRequest,
                            auth_info: dict = Depends(auth_dep)) -> dict:
        try:
            sub = service.register_subscription(
                url=req.url, secret=req.secret,
                event_types=req.event_types, active=req.active,
            )
        except Exception as e:  # noqa: BLE001 - validación pydantic falló en service
            raise HTTPException(status_code=422, detail=str(e))
        return {"ok": True, "message": "Suscripción creada.", "subscription": sub.to_dict()}

    @router.get("/subscriptions", summary="Lista las suscripciones.", response_model=None)
    def list_subscriptions(auth_info: dict = Depends(auth_dep)) -> dict:
        subs = service.list_subscriptions()
        return {"ok": True, "subscriptions": [s.to_dict() for s in subs]}

    @router.get("/subscriptions/{sub_id}", summary="Obtiene una suscripción.",
                response_model=None)
    def get_subscription(sub_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        sub = service.get_subscription(sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Suscripción no encontrada.")
        return {"ok": True, "subscription": sub.to_dict()}

    @router.delete("/subscriptions/{sub_id}", summary="Elimina una suscripción.",
                   response_model=None)
    def delete_subscription(sub_id: str, auth_info: dict = Depends(auth_dep)) -> dict:
        if not service.delete_subscription(sub_id):
            raise HTTPException(status_code=404, detail="Suscripción no encontrada.")
        return {"ok": True, "message": "Suscripción eliminada."}

    @router.post("/publish", summary="Publica un evento (trigger/test).",
                 response_model=None)
    def publish_event(req: PublishEventRequest, auth_info: dict = Depends(auth_dep)) -> dict:
        event: WebhookEvent = service.publish(
            event_type=req.event_type, payload=req.payload, tenant_id=req.tenant_id,
        )
        return {"ok": True, "message": "Evento publicado.",
                "data": {"event_id": event.id, "event_type": event.event_type.value}}

    @router.get("/deliveries", summary="Lista las entregas (auditoría).",
                response_model=None)
    def list_deliveries(subscription_id: Optional[str] = None,
                        auth_info: dict = Depends(auth_dep)) -> dict:
        dels = service.list_deliveries(subscription_id=subscription_id)
        return {"ok": True, "deliveries": [d.to_dict() for d in dels]}

    return router
