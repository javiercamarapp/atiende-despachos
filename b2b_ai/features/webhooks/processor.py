# -*- coding: utf-8 -*-
"""
processor.py — Motor de entrega de webhooks.

Responsabilidades:
  - Firmar el payload con HMAC-SHA256 usando el secret de la suscripción.
  - Entregar el evento por HTTP POST al endpoint registrado.
  - Reintentar con exponential backoff (máx. ``max_attempts``, default 3).
  - Limitar el rate de entrega por suscripción (token bucket).
  - Registrar cada intento en el log.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from .models import (
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEvent,
    WebhookSubscription,
)

logger = logging.getLogger("b2b_ai.webhooks")

# Backoff base en segundos: intento 1 → 2s, intento 2 → 4s, intento 3 → 8s
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_FACTOR = 2.0

# Límite de rate por suscripción: default 60 entregas / 60s (token bucket)
RATE_DEFAULT_CAPACITY = 60
RATE_DEFAULT_REFILL = 60  # tokens por segundo


def sign_payload(payload: Dict[str, Any], secret: str) -> str:
    """Firma el payload canónico con HMAC-SHA256 (hex)."""
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return digest


def verify_signature(payload: Dict[str, Any], secret: str, signature: str) -> bool:
    """Verifica la firma recibida contra el payload y el secret."""
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


def _backoff_delay(attempt: int, base: float = BACKOFF_BASE_SECONDS) -> float:
    """Delay antes del siguiente intento tras ``attempt`` fallos."""
    return base * (BACKOFF_FACTOR ** max(attempt - 1, 0))


class TokenBucket:
    """Limita el número de entregas por segundo para una suscripción."""

    def __init__(self, capacity: int = RATE_DEFAULT_CAPACITY,
                 refill_per_second: float = RATE_DEFAULT_REFILL):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = float(capacity)
        self._last = time.monotonic()

    def try_consume(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.monotonic()
        elapsed = now - self._last
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class WebhookProcessor:
    """Procesa la entrega de eventos webhook con firma, retry y rate limit.

    ``http_post`` es inyectable para testear sin red real.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        rate_capacity: int = RATE_DEFAULT_CAPACITY,
        rate_refill: float = RATE_DEFAULT_REFILL,
        http_post: Optional[Callable[..., Dict[str, Any]]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.max_attempts = max_attempts
        self._buckets: Dict[str, TokenBucket] = {}
        self._bucket_capacity = rate_capacity
        self._bucket_refill = rate_refill
        self.http_post = http_post or self._default_http_post
        self.sleep = sleep or time.sleep

    def _bucket(self, subscription_id: str) -> TokenBucket:
        if subscription_id not in self._buckets:
            self._buckets[subscription_id] = TokenBucket(
                capacity=self._bucket_capacity,
                refill_per_second=self._bucket_refill,
            )
        return self._buckets[subscription_id]

    def _default_http_post(self, url: str, body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
        """Implementación por defecto con urllib (stdlib, sin deps extra)."""
        import urllib.request

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"ok": True, "status_code": resp.status}
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            return {"ok": e.code in (200, 201, 202, 204), "status_code": e.code}
        except Exception as e:  # noqa: BLE001 - red, timeout, DNS
            return {"ok": False, "status_code": None, "error": str(e)}

    def deliver(self, delivery: WebhookDelivery, subscription: WebhookSubscription,
                event: WebhookEvent) -> WebhookDelivery:
        """Entrega el evento con reintentos y rate limiting. Devuelve el delivery final."""
        # 1) Rate limit
        if not self._bucket(subscription.id).try_consume():
            delivery.status = WebhookDeliveryStatus.RATE_LIMITED
            delivery.last_error = "Rate limit excedido"
            logger.warning(
                "webhook rate_limited sub=%s event=%s url=%s",
                subscription.id, event.event_type.value, subscription.url,
            )
            return delivery

        body = json.dumps(
            {"event": event.event_type.value, "payload": event.payload},
            ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        signature = sign_payload(
            {"event": event.event_type.value, "payload": event.payload},
            subscription.secret,
        )
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LikidaAI-Webhook/1.0",
            "X-Likida-Signature": f"sha256={signature}",
            "X-Likida-Event": event.event_type.value,
            "X-Likida-Event-Id": event.id,
        }

        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            delivery.attempts = attempt
            delivery.signature = signature
            try:
                result = self.http_post(subscription.url, body, headers)
            except Exception as e:  # red/timeout/DNS — tratado como fallo de entrega
                logger.exception("webhook http error sub=%s attempt=%d", subscription.id, attempt)
                result = {"ok": False, "status_code": None, "error": str(e)}

            delivery.last_status_code = result.get("status_code")

            if result.get("ok"):
                delivery.status = WebhookDeliveryStatus.DELIVERED
                delivery.last_error = None
                logger.info(
                    "webhook delivered sub=%s event=%s attempt=%d status=%s",
                    subscription.id, event.event_type.value, attempt,
                    result.get("status_code"),
                )
                return delivery

            delivery.last_error = result.get("error") or f"HTTP {result.get('status_code')}"
            logger.warning(
                "webhook failed sub=%s event=%s attempt=%d/%d error=%s",
                subscription.id, event.event_type.value, attempt, self.max_attempts,
                delivery.last_error,
            )
            if attempt < self.max_attempts:
                delay = _backoff_delay(attempt)
                delivery.next_retry_at = datetime.utcnow().timestamp() + delay
                self.sleep(delay)

        delivery.status = WebhookDeliveryStatus.FAILED
        delivery.next_retry_at = None
        return delivery
