# -*- coding: utf-8 -*-
"""test_conekta_webhook_rawbody_security.py — Regresión de seguridad:
verificación de firma del webhook de Conekta contra el RAW BODY.

Bug corregido: la firma HMAC se verificaba contra una reserialización
(`json.dumps(payload_ya_parseado, separators=(",", ":"))`) en vez de contra
los bytes crudos que realmente llegaron por HTTP. `json.dumps()` de un dict
ya parseado NO es byte-idéntico al body original: por ejemplo, un valor de
cadena escrito con un escape unicode (`"chg\\u005f1"`) y el mismo valor
escrito literal (`"chg_1"`) son bytes distintos en el wire pero parsean al
MISMO string Python y por tanto se re-serializan a la MISMA forma canónica.

Eso significa que, con el código viejo, un atacante que observa/reproduce
UNA firma válida de Conekta para un payload dado puede sustituir esos bytes
por una variante distinta byte a byte (con escapes unicode "invisibles",
espacios extra, etc.) que canonicaliza igual, y el servidor la acepta como
si fuera el body que Conekta realmente firmó — un bypass de firma.

Estos tests demuestran, contra el punto canónico donde existía el patrón
vulnerable en este repo:
    - b2b_ai/billing/webhook_receiver.py        (ConektaWebhookReceiver + su router)

que:

NOTA (consolidación de billing, fix/billing-consolidacion): este archivo
cubría el mismo patrón también en `b2b_ai/features/billing/` (el módulo
"piloto"). Ese módulo se eliminó — nunca estuvo montado en `create_app()`
(no servía tráfico real) y además tenía un bypass de firma DISTINTO y más
grave que este: `process_webhook()` solo verificaba la firma `if signature`
(truthy), así que una request SIN el header de firma en absoluto se
procesaba como pago válido sin verificar nada, en cualquier entorno
(sandbox o "production"). Ver el commit de consolidación para el repro.
Las clases que ejercitaban ese módulo (`TestConektaClientRawBodyVerification`,
`TestFeaturesBillingWebhookEndpointRawBody`) se eliminaron junto con él; la
cobertura del módulo canónico (`TestWebhookReceiverRawBody`) se conserva
íntegra abajo.
    1. Una firma calculada sobre el raw body PASA cuando se verifica contra
       ese mismo raw body.
    2. Una variante del body que difiere en bytes crudos pero canonicaliza
       igual (i.e., el ataque de re-serialización) es RECHAZADA, porque la
       verificación ahora ocurre contra los bytes crudos, antes de parsear.
    3. El contenido que se procesa/enruta es siempre el que se acaba de
       verificar (re-parseado del propio raw_body) — un `event_payload`
       manipulado después de parsear pero pasado aparte no se usa.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.billing.webhook_receiver import (
    ConektaWebhookReceiver,
    build_webhook_receiver_router,
)

WEBHOOK_SECRET = "test_webhook_secret_rawbody_check"

# Payload "legítimo" tal como lo firmaría Conekta, en forma canónica
# compacta (la que produce json.dumps(d, separators=(",", ":"))).
LEGIT_RAW = '{"type":"charge.paid","data":{"object":{"id":"chg_1"}}}'

# Variante byte-distinta del MISMO payload: "chg_1" se escribe con el
# guion bajo como escape unicode (_ == "_"). json.loads() de ambas
# variantes produce el MISMO dict de Python, y por tanto la MISMA forma
# canónica al reserializar -- pero los bytes crudos en el wire son
# distintos y NUNCA fueron firmados por Conekta.
TAMPERED_RAW = '{"type":"charge.paid","data":{"object":{"id":"chg\\u005f1"}}}'


def _assert_same_dict_different_bytes():
    assert LEGIT_RAW != TAMPERED_RAW
    assert json.loads(LEGIT_RAW) == json.loads(TAMPERED_RAW)
    assert (
        json.dumps(json.loads(TAMPERED_RAW), separators=(",", ":")) == LEGIT_RAW
    )


def _sign(raw: str, secret: str = WEBHOOK_SECRET, ts: str = "1700000000") -> str:
    digest = hmac.new(
        secret.encode("utf-8"), f"{ts}{raw}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"hmac_sha256={digest},t={ts}"


class TestCanonicalizationAssumption:
    """Confirma la premisa del ataque antes de probar la corrección."""

    def test_legit_and_tampered_are_different_bytes_same_canonical_dict(self):
        _assert_same_dict_different_bytes()


# ---------------------------------------------------------------------------
# Endpoint HTTP real: POST /api/v1/billing/webhook (standalone receiver)
#    (b2b_ai/billing/webhook_receiver.py) — módulo canónico, el único que
#    sirve tráfico de pagos en producción.
# ---------------------------------------------------------------------------

class _FakeDB:
    def __init__(self):
        self._audit_log: List[Dict[str, Any]] = []

    def log_call(self, tool_name, action, entity="", entity_id="",
                 payload=None, status="ok", tenant_id=None):
        self._audit_log.append({"status": status, "entity_id": entity_id})
        return len(self._audit_log)

    def mark_billing_invoice_paid_by_ref(self, *a, **kw):
        return True


class TestWebhookReceiverRawBody:
    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(
            build_webhook_receiver_router(_FakeDB(), webhook_secret=WEBHOOK_SECRET)
        )
        return TestClient(app)

    def test_valid_signature_over_actual_raw_body_is_accepted(self):
        client = self._client()
        sig = _sign(LEGIT_RAW)
        r = client.post(
            "/api/v1/billing/webhook",
            content=LEGIT_RAW.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig,
            },
        )
        # charge.paid no es uno de los 4 eventos soportados por este
        # receiver (payment.paid/failed, subscription.created/canceled),
        # pero eso ya es *después* de la verificación de firma: 200
        # "recibido, no procesado" confirma que la firma pasó.
        assert r.status_code == 200, r.text
        assert r.json()["received"] is True

    def test_tampered_raw_body_with_replayed_signature_is_rejected(self):
        _assert_same_dict_different_bytes()
        client = self._client()
        sig_for_legit = _sign(LEGIT_RAW)
        r = client.post(
            "/api/v1/billing/webhook",
            content=TAMPERED_RAW.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "conekta-signature": sig_for_legit,
            },
        )
        assert r.status_code == 401, r.text

    def test_forged_webhook_with_no_signature_header_is_rejected(self):
        """Regresión directa del bypass encontrado y eliminado en el módulo
        piloto (`b2b_ai/features/billing/conekta_client.py`): ahí,
        `if signature and not verify(...)` dejaba pasar SIN verificar nada
        cualquier request que simplemente omitiera el header de firma
        (`signature == ""` es falsy -> el `and` corta y nunca se llama a
        `verify_webhook_signature`). Un atacante podía forjar un pago
        exitoso con un POST sin firma. Aquí, `verify_signature()` es
        SIEMPRE llamada (nunca condicionada a que el header venga) y
        devuelve False si el header falta -> 401."""
        client = self._client()
        r = client.post(
            "/api/v1/billing/webhook",
            content=LEGIT_RAW.encode("utf-8"),
            headers={"Content-Type": "application/json"},  # sin conekta-signature
        )
        assert r.status_code == 401, r.text

    def test_forged_webhook_with_garbage_signature_is_rejected(self):
        """Firma con formato válido pero hash inventado (no calculado con el
        secreto real) -- simula un atacante que adivina el formato del
        header pero no conoce el secreto HMAC."""
        client = self._client()
        r = client.post(
            "/api/v1/billing/webhook",
            content=LEGIT_RAW.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "conekta-signature": "hmac_sha256=" + "0" * 64 + ",t=1700000000",
            },
        )
        assert r.status_code == 401, r.text

    def test_receiver_process_webhook_unit_level(self):
        """Mismo par legit/tampered directamente sobre
        ConektaWebhookReceiver.process_webhook (sin pasar por HTTP)."""
        receiver = ConektaWebhookReceiver(_FakeDB(), webhook_secret=WEBHOOK_SECRET)
        sig = _sign(LEGIT_RAW)

        ok = receiver.process_webhook(
            json.loads(LEGIT_RAW), sig, raw_body=LEGIT_RAW.encode("utf-8")
        )
        assert ok["received"] is True

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            receiver.process_webhook(
                json.loads(TAMPERED_RAW), sig, raw_body=TAMPERED_RAW.encode("utf-8")
            )
        assert exc_info.value.status_code == 401
