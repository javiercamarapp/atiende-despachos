# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo de Webhooks.

WebhookService:
  - register_subscription  : alta de un endpoint (con validación de URL/secret)
  - list_subscriptions     : lista suscripciones (opcional por tenant)
  - get_subscription       : obtiene una por id
  - delete_subscription    : baja de una suscripción
  - publish                : publica un evento y lo entrega a los suscriptores que
                            aplican (con retry + rate limiting vía processor)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    WebhookDelivery,
    WebhookEvent,
    WebhookEventType,
    WebhookSubscription,
)
from .processor import WebhookProcessor

logger = logging.getLogger("b2b_ai.webhooks")

_subscriptions: Dict[str, WebhookSubscription] = {}
_deliveries: List[WebhookDelivery] = []


class WebhookService:
    """Servicio stateless-ish para registrar suscripciones y publicar eventos."""

    def __init__(self, processor: Optional[WebhookProcessor] = None):
        self.processor = processor or WebhookProcessor()

    # ------------------------------------------------------------------
    # Suscripciones
    # ------------------------------------------------------------------
    def register_subscription(
        self,
        url: str,
        secret: str,
        event_types: Optional[List[str]] = None,
        active: bool = True,
    ) -> WebhookSubscription:
        sub = WebhookSubscription(
            url=url,
            secret=secret,
            event_types=[WebhookEventType(e) for e in (event_types or [])],
            active=active,
        )
        _subscriptions[sub.id] = sub
        logger.info("webhook registered id=%s url=%s events=%s",
                    sub.id, sub.url, [e.value for e in sub.event_types])
        return sub

    def list_subscriptions(self, active_only: bool = False) -> List[WebhookSubscription]:
        subs = list(_subscriptions.values())
        if active_only:
            subs = [s for s in subs if s.active]
        return sorted(subs, key=lambda s: s.created_at, reverse=True)

    def get_subscription(self, sub_id: str) -> Optional[WebhookSubscription]:
        return _subscriptions.get(sub_id)

    def delete_subscription(self, sub_id: str) -> bool:
        if sub_id in _subscriptions:
            del _subscriptions[sub_id]
            logger.info("webhook removed id=%s", sub_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Publicación de eventos
    # ------------------------------------------------------------------
    def publish(
        self,
        event_type: WebhookEventType,
        payload: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        sync: bool = True,
    ) -> WebhookEvent:
        """Publica un evento y lo entrega a los suscriptores aplicables.

        Devuelve el evento creado. Los deliveries se almacenan para auditoría.
        """
        event = WebhookEvent(
            event_type=WebhookEventType(event_type) if isinstance(event_type, str) else event_type,
            payload=payload or {},
            tenant_id=tenant_id,
        )
        logger.info("webhook publish event=%s id=%s", event.event_type.value, event.id)

        for sub in self.list_subscriptions():
            if not sub.accepts(event.event_type):
                continue
            delivery = WebhookDelivery(
                subscription_id=sub.id,
                event_id=event.id,
                event_type=event.event_type,
                max_attempts=self.processor.max_attempts,
            )
            _deliveries.append(delivery)
            if sync:
                self.processor.deliver(delivery, sub, event)
        return event

    def get_event_deliveries(self, event_id: str) -> List[WebhookDelivery]:
        return [d for d in _deliveries if d.event_id == event_id]

    def list_deliveries(self, subscription_id: Optional[str] = None,
                        limit: int = 100) -> List[WebhookDelivery]:
        dels = _deliveries
        if subscription_id:
            dels = [d for d in dels if d.subscription_id == subscription_id]
        return sorted(dels, key=lambda d: d.created_at, reverse=True)[:limit]


def reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _subscriptions.clear()
    _deliveries.clear()
