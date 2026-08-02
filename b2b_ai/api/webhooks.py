# -*- coding: utf-8 -*-
"""
webhooks.py — Sistema de webhooks (FASE 4).

Dos direcciones:

  1. INBOUND (recibir): webhook que recibe facturas por email. Simula el
     inbound parse de Mailgun / SendGrid: un payload con attachments (XML de
     CFDI) que el agente procesa de punta a punta. En producción Mailgun
     valida su propia firma; aquí el mock acepta el payload documentado.

  2. OUTBOUND (notificar): el agente entrega el resultado de una factura a
     la URL de webhook configurada por el tenant, con RETRY logic (backoff
     exponencial) y bitácora en `webhook_deliveries`.

Retry logic:
    retry_deliver(url, payload, max_attempts, base_delay) intenta el POST
    hasta max_attempts con backoff exponencial (base_delay * 2^(n-1)). El
    `post` es inyectable para pruebas sin red.

Sin API keys externas: el POST real usa stdlib urllib; por defecto nada sale
a la red salvo que un tenant tenga `webhook_url` configurada.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from b2b_ai.agent.loop import AgentLoop
from b2b_ai.db.db import Database
from b2b_ai.db.tenants import TenantManager
from pydantic import BaseModel, Field


# ==========================================================================
# Schemas de webhook (a nivel de módulo para que FastAPI los infiera como
# body, no como query — los modelos dinámicos no se infieren bien).
# ==========================================================================
class EmailInbound(BaseModel):
    model_config = {"populate_by_name": True}
    from_: str = Field(default="", alias="from")
    subject: str = ""
    text: str = ""
    xml: str = ""
    content: str = ""
    attachments: List[Any] = []
    tenant_id: Optional[int] = None


class NotifyRequest(BaseModel):
    event: str = "invoice_processed"
    invoice_id: Optional[int] = None


class Subscription(BaseModel):
    url: str


# ==========================================================================
# Retry logic
# ==========================================================================
def default_post(url: str, payload: Any, timeout: int = 15) -> int:
    """POST JSON vía stdlib. Devuelve status HTTP; lanza en error/no-2xx."""
    _assert_http_scheme(url)
    req = urllib.request.Request(
        url, data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        # nosec B310: esquema validado por _assert_http_scheme() justo arriba.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    if not (200 <= status < 300):
        raise RuntimeError(f"HTTP {status} desde {url}")
    return status


def _assert_http_scheme(url: str) -> None:
    """Rechaza esquemas que no sean http/https (bloquea file:, etc.) para
    prevenir SSRF cuando la URL llega de un Subscription (input del usuario).

    VULN-08: Also blocks private/internal IP ranges to prevent SSRF to
    cloud metadata (169.254.169.254), localhost, and RFC1918 addresses.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Esquema de URL no permitido: {scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL sin hostname.")
    # Block localhost and metadata endpoints
    _BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}
    if hostname in _BLOCKED_HOSTS:
        raise ValueError(f"Hostname bloqueado (SSRF): {hostname}")
    # Resolve hostname and check against private IP ranges
    _PRIVATE_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
    ]
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
    except (socket.gaierror, ValueError):
        raise ValueError(f"No se pudo resolver: {hostname}")
    for range_ in _PRIVATE_RANGES:
        if ip in range_:
            raise ValueError(f"URL en red privada no permitida: {url}")


def retry_deliver(url: str, payload: Any, max_attempts: int = 3,
                  base_delay: float = 0.5,
                  post: Optional[Callable[..., int]] = None,
                  delay_fn: Optional[Callable[[int], float]] = None) -> Dict[str, Any]:
    """
    Entrega con reintentos y backoff exponencial. Devuelve dict con
    {ok, attempts, last_status, last_error}. `post(url, payload)` es
    inyectable; `delay_fn(attempt)` devuelve los segundos de espera.
    """
    post = post or default_post
    delay_fn = delay_fn or (lambda a: base_delay * (2 ** (a - 1)))
    attempts = 0
    last_status = ""
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            post(url, payload)
            return {"ok": True, "attempts": attempts,
                    "last_status": "delivered", "last_error": ""}
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            last_status = "error"
            if attempt < max_attempts:
                time.sleep(delay_fn(attempt))
    return {"ok": False, "attempts": attempts, "last_status": last_status,
            "last_error": last_error}


class WebhookNotifier:
    """Entrega resultados a la URL de webhook del tenant, con bitácora."""

    def __init__(self, db: Optional[Database] = None,
                 post: Optional[Callable[..., int]] = None) -> None:
        self.db = db or Database()
        self.post = post

    def notify(self, tenant_id: int, event: str, payload: Any) -> Dict[str, Any]:
        """
        Notifica `event` con `payload` al webhook_url del tenant. Devuelve
        dict {ok, delivery_id, ...}. Si el tenant no tiene webhook_url,
        no entrega (ok=False, reason='no_webhook_url').
        """
        url = self.db.get_tenant_config(tenant_id, "webhook_url", "")
        if not url:
            return {"ok": False, "delivery_id": None,
                    "reason": "no_webhook_url",
                    "message": "El tenant no tiene webhook_url configurada."}
        delivery_id = self.db.record_webhook_delivery(
            tenant_id, event, url, payload)
        res = retry_deliver(url, payload, post=self.post)
        now = datetime.now().isoformat(timespec="seconds") if res["ok"] else None
        self.db.update_webhook_delivery(
            delivery_id, res["attempts"], res["last_status"],
            res.get("last_error", ""), completed_at=now)
        return {"ok": res["ok"], "delivery_id": delivery_id,
                "event": event, "url": url, **res}


# ==========================================================================
# Inbound email (mock Mailgun / SendGrid)
# ==========================================================================
class EmailWebhook:
    """
    Recibe un payload de email (formato mock Mailgun/SendGrid) y extrae los
    CFDI XML adjuntos. Contrato del payload:

        {
          "from": "proveedor@x.com",
          "subject": "Factura CFDI",
          "text": "...",
          "attachments": [
            {"filename": "factura.xml",
             "content_base64": "<base64>"} | {"content": "<xml crudo>"}
          ]
        }
    """

    def extract_cfdi(self, payload: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Devuelve lista de {filename, xml} con los adjuntos XML de CFDI.
        Acepta contenido base64 o crudo; también admite xml embebido en
        el campo 'xml' o 'content' raíz.
        """
        found = []
        attachments = payload.get("attachments") or []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            name = att.get("filename", "adjunto.xml")
            content = att.get("content")
            if content is None:
                b64 = att.get("content_base64")
                if b64:
                    try:
                        content = base64.b64decode(b64).decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        continue
            if content and "<" in content and ("Comprobante" in content
                                                or "cfdi" in content.lower()):
                found.append({"filename": name, "xml": content})
        # XML embebido a nivel raíz
        root_xml = payload.get("xml") or payload.get("content")
        if isinstance(root_xml, str) and "<" in root_xml:
            found.append({"filename": payload.get("subject", "factura") + ".xml",
                          "xml": root_xml})
        return found


def process_email_inbound(db: Database, payload: Dict[str, Any], tenant_id: int,
                          loop: Optional[AgentLoop] = None,
                          send_notifications: bool = False) -> List[Dict[str, Any]]:
    """
    Procesa un email de facturas de punta a punta: extrae los CFDI, los
    escribe a archivos temporales y los corre por el AgentLoop. Devuelve
    lista de resultados (uno por CFDI).
    """
    tm = TenantManager(db)
    tm.get_tenant(tenant_id)  # valida scope
    eh = EmailWebhook()
    cfdis = eh.extract_cfdi(payload)
    loop = loop or AgentLoop(db=db)
    results = []
    for c in cfdis:
        fd, path = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(c["xml"])
            res = loop.process(path, tenant_id=tenant_id,
                               send_notifications=send_notifications)
        finally:
            os.unlink(path)
        res["adjunto"] = c["filename"]
        results.append(res)
    return results


# ==========================================================================
# Rutas FastAPI
# ==========================================================================
def register_webhook_routes(app: Any, db: Database, require_api_key: Any,
                            notifier: Optional[WebhookNotifier] = None) -> WebhookNotifier:
    """
    Monta los endpoints de webhook en la app. `require_api_key` es el
    depend de auth (para scoping por tenant). Devuelve el notifier creado.
    """
    from fastapi import Depends, HTTPException

    tm = TenantManager(db)
    notifier = notifier or WebhookNotifier(db)

    # ---- INBOUND: recibir factura por email -----------------------------
    @app.post("/api/v1/webhooks/email", summary="Recibe facturas por email "
              "(mock Mailgun/SendGrid).", tags=["webhooks"])
    def webhook_email(email: EmailInbound,
                      auth_info: dict = Depends(require_api_key)):
        # auth_info viene del Depends; FastAPI lo inyecta si es parámetro
        scope = auth_info.get("tenant_id")
        # Solo la key de servicio (tenant_id=None) puede fijar el tenant
        # auth_info viene del Depends; FastAPI lo inyecta si es parámetro
        scope = auth_info.get("tenant_id")
        # SECURITY: Never override scope from client-provided tenant_id.
        # Only the service key (tenant_id=None) may set a specific tenant.
        if scope is None:
            if email.tenant_id is not None:
                scope = email.tenant_id
            else:
                raise HTTPException(status_code=422,
                                    detail="No se pudo resolver el tenant.")
        payload = {
            "from": email.from_, "subject": email.subject,
            "text": email.text, "xml": email.xml, "content": email.content,
            "attachments": email.attachments,
        }
        results = process_email_inbound(db, payload, scope,
                                        send_notifications=True)
        if not results:
            raise HTTPException(status_code=422,
                                detail="No se encontraron CFDI XML adjuntos.")
        return {"procesadas": len(results),
                "results": [{"decision": r["decision"],
                             "invoice_id": r["invoice_id"],
                             "archivo": r["archivo"],
                             "adjunto": r["adjunto"],
                             "categoria": (r["clasificacion"] or {}).get(
                                 "categoria"),
                             "review_id": r["review_id"]}
                            for r in results]}

    # ---- OUTBOUND: notificar resultado a la URL del tenant --------------
    @app.post("/api/v1/webhooks/notify", summary="Entrega un resultado de "
              "factura al webhook del tenant.", tags=["webhooks"])
    def webhook_notify(req: NotifyRequest, auth_info: dict = Depends(require_api_key)):
        scope = auth_info.get("tenant_id")
        if scope is None:
            raise HTTPException(status_code=422, detail="Sin tenant.")
        inv = db.get_invoice(req.invoice_id,
                             tenant_id=scope) if req.invoice_id else None
        payload = {"event": req.event, "invoice": inv,
                   "notified_at": datetime.now().isoformat(timespec="seconds")}
        res = notifier.notify(scope, req.event, payload)
        if not res["ok"] and res.get("reason") == "no_webhook_url":
            raise HTTPException(status_code=409, detail=res["message"])
        return res

    # ---- Suscripciones ---------------------------------------------------
    @app.post("/api/v1/webhooks/subscriptions", summary="Registra la URL de "
              "webhook del tenant.", tags=["webhooks"])
    def webhook_subscribe(sub: Subscription, auth_info: dict = Depends(require_api_key)):
        scope = auth_info.get("tenant_id")
        if scope is None:
            raise HTTPException(status_code=422, detail="Sin tenant.")
        if not sub.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="URL inválida.")
        tm.set_config(scope, webhook_url=sub.url)
        return {"ok": True, "tenant_id": scope, "webhook_url": sub.url}

    @app.get("/api/v1/webhooks/subscriptions", summary="Lista la URL de "
             "webhook del tenant.", tags=["webhooks"])
    def webhook_list(auth_info: dict = Depends(require_api_key)):
        scope = auth_info.get("tenant_id")
        return {"tenant_id": scope,
                "webhook_url": db.get_tenant_config(scope, "webhook_url", "")}

    # ---- Retry worker ----------------------------------------------------
    @app.post("/api/v1/webhooks/retry", summary="Reintenta entregas de "
              "webhook pendientes (worker).", tags=["webhooks"])
    def webhook_retry(auth_info: dict = Depends(require_api_key)):
        scope = auth_info.get("tenant_id")
        pending = db.list_pending_webhook_deliveries(tenant_id=scope)
        renotified = []
        for d in pending:
            try:
                payload = json.loads(d["payload"])
            except Exception:  # noqa: BLE001
                payload = {}
            res = retry_deliver(d["url"], payload, post=notifier.post)
            now = datetime.now().isoformat(timespec="seconds") if res["ok"] else None
            db.update_webhook_delivery(
                d["id"], d["attempts"] + res["attempts"], res["last_status"],
                res.get("last_error", ""), completed_at=now)
            renotified.append({"delivery_id": d["id"], **res})
        return {"reintentadas": len(renotified), "results": renotified}

    return notifier
