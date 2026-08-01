# -*- coding: utf-8 -*-
"""
api.py — Router FastAPI de notificaciones WhatsApp.

Endpoints (todos requieren API key en el header `X-API-Key`):

    POST /api/v1/notifications/send      encola/envía una notificación.
    GET  /api/v1/notifications/history   historial persistido en la DB.
    POST /api/v1/notifications/config    guarda configuración del tenant.

El router se construye con `build_notifications_router(db, require_api_key)`
para poder inyectar una DB de prueba y un scheduler mockeado. El scheduler
procesa la cola cuando se llama a `scheduler.process_once()` (o `run()`);
si no se inyecta, se crea uno por defecto en modo simulado (sin credenciales
no hay envío real a Meta).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from b2b_ai.notifications.scheduler import NotificationScheduler
from b2b_ai.notifications.whatsapp import WhatsAppBusiness


class NotificationSendRequest(BaseModel):
    recipient: str
    message: str = ""
    template: Optional[str] = None
    type: str = "whatsapp"
    schedule_at: Optional[str] = None  # ISO 8601 (envío diferido)


class NotificationConfigRequest(BaseModel):
    recipient: Optional[str] = None
    whatsapp_token: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None
    notif_channel: Optional[str] = None


class EmailSendRequest(BaseModel):
    to: str
    subject: str = ""
    body: str = ""
    template: Optional[str] = None
    context: Optional[dict] = None
    html: Optional[str] = None
    attachments: Optional[list] = None
    schedule_at: Optional[str] = None  # ISO 8601 (envío diferido)


class NotificationPreferencesRequest(BaseModel):
    channel: Optional[str] = None            # "email" | "whatsapp" | "both"
    digest: Optional[str] = None             # "daily" | "weekly" | "off"
    digest_time: Optional[str] = None        # "HH:MM"
    weekly_weekday: Optional[int] = None     # 0=lunes ... 6=domingo
    email: Optional[str] = None              # destinatario por defecto


def build_notifications_router(db, require_api_key, scheduler=None,
                               email_provider=None, email_scheduler=None):
    """Devuelve un APIRouter de notificaciones.

    Args:
        db:              instancia de Database.
        require_api_key: dependencia de auth (Depends) que resuelve la key.
        scheduler:       NotificationScheduler opcional (tests inyectan uno
                         con WhatsApp mock).
        email_provider:  EmailProvider opcional para los endpoints de email.
        email_scheduler: EmailScheduler opcional (cola de email).
    """
    if scheduler is None:
        scheduler = NotificationScheduler(wa=WhatsAppBusiness())
    if email_provider is None:
        from b2b_ai.notifications.email_provider import EmailProvider
        email_provider = EmailProvider()
    if email_scheduler is None:
        from b2b_ai.notifications.scheduler import EmailScheduler
        email_scheduler = EmailScheduler(provider=email_provider)

    router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

    @router.post("/send", summary="Encola/envía una notificación WhatsApp.")
    def send_notification(req: NotificationSendRequest,
                          auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        if not req.recipient:
            raise HTTPException(422, "recipient es obligatorio (teléfono E.164).")

        body = req.message
        if not body and req.template:
            from b2b_ai.notifications.templates import render
            try:
                _, body = render(req.template, {})
            except KeyError:
                raise HTTPException(422, f"Plantilla desconocida: {req.template}")

        run_at = None
        if req.schedule_at:
            try:
                run_at = datetime.fromisoformat(req.schedule_at)
            except ValueError:
                raise HTTPException(422,
                                    "schedule_at debe ser ISO 8601 válido.")

        # Persistir en la DB (auditoría / historial).
        notif_id = db.insert_notification(
            tenant, req.type, "whatsapp", req.recipient,
            f"notificación {req.template or 'personalizada'}",
            body, status="queued")

        # Encolar en el scheduler (procesa con process_once/run).
        scheduler.enqueue(req.recipient, body, template=req.template,
                          run_at=run_at)
        return {
            "ok": True,
            "notification_id": notif_id,
            "queued": True,
            "pending": scheduler.pending(),
            "backend": getattr(scheduler.wa, "backend", "?"),
        }

    @router.get("/history", summary="Historial de notificaciones persistidas.")
    def notification_history(limit: int = Query(default=50, ge=1, le=500),
                             auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        rows = db.list_notifications(tenant_id=tenant, limit=limit)
        return {"count": len(rows), "notifications": rows}

    @router.post("/config", summary="Guarda configuración de WhatsApp del tenant.")
    def notification_config(req: NotificationConfigRequest,
                            auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        if tenant is None:
            raise HTTPException(
                400, "La configuración es por tenant y requiere una API key "
                     "de tenant (no la key de servicio sin tenant).")
        updated = []
        if req.recipient:
            db.set_tenant_config(tenant, "notif_recipient", req.recipient)
            updated.append("recipient")
        if req.whatsapp_token:
            db.set_tenant_config(tenant, "whatsapp_token", req.whatsapp_token)
            updated.append("whatsapp_token")
        if req.whatsapp_phone_number_id:
            db.set_tenant_config(tenant, "whatsapp_phone_number_id",
                                 req.whatsapp_phone_number_id)
            updated.append("whatsapp_phone_number_id")
        if req.notif_channel:
            db.set_tenant_config(tenant, "notif_channel", req.notif_channel)
            updated.append("notif_channel")
        if not updated:
            raise HTTPException(422, "No se envió ningún campo de configuración.")
        return {"ok": True, "updated": updated}

    @router.post("/email", summary="Envía un email (SMTP) o lo encola.")
    def send_email(req: EmailSendRequest,
                   auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        if not req.to:
            raise HTTPException(422, "to es obligatorio (email del destinatario).")

        subject, body, html = req.subject, req.body, req.html
        if req.template:
            from b2b_ai.notifications.templates import render_html
            try:
                subject, html = render_html(req.template, req.context or {})
            except KeyError:
                raise HTTPException(422, f"Plantilla desconocida: {req.template}")
            except ValueError as e:
                raise HTTPException(422, f"Contexto inválido: {e}")
            body = body or _html_to_text(html)

        run_at = None
        if req.schedule_at:
            try:
                run_at = datetime.fromisoformat(req.schedule_at)
            except ValueError:
                raise HTTPException(422, "schedule_at debe ser ISO 8601 válido.")

        # Persistir historial en la DB.
        notif_id = db.insert_notification(
            tenant, "email", "email", req.to, subject,
            body or html or "", status="queued" if run_at else "sent")

        if run_at:
            # Programado → a la cola del EmailScheduler.
            email_scheduler.enqueue(
                req.to, subject, body, html=html, run_at=run_at,
                template=req.template, context=req.context,
                attachments=req.attachments)
            queued = True
            sent = False
        else:
            # Envío inmediato.
            result = email_provider.send(req.to, subject, body, html=html,
                                         attachments=req.attachments)
            queued = False
            sent = result.get("status") in ("sent", "simulado")
            # Actualizar estado real en el historial.
            try:
                db.update_notification_status(notif_id, result.get("status", "error"))
            except Exception:  # noqa: BLE001 — método opcional
                pass

        return {
            "ok": True,
            "notification_id": notif_id,
            "subject": subject,
            "queued": queued,
            "sent": sent,
            "status": "queued" if run_at else
            (email_provider.sent[-1]["status"] if email_provider.sent else "sent"),
        }

    @router.put("/preferences",
                summary="Guarda preferencias de notificación del tenant.")
    def notification_preferences(req: NotificationPreferencesRequest,
                                 auth_info: dict = Depends(require_api_key)):
        tenant = auth_info.get("tenant_id")
        if tenant is None:
            raise HTTPException(
                400, "Las preferencias son por tenant y requieren una API key "
                     "de tenant (no la key de servicio sin tenant).")
        updated = []

        def _set(key, value):
            db.set_tenant_config(tenant, key, value)
            updated.append(key)

        if req.channel:
            if req.channel not in ("email", "whatsapp", "both"):
                raise HTTPException(422, "channel debe ser email|whatsapp|both.")
            _set("notif_pref_channel", req.channel)
        if req.digest:
            if req.digest not in ("daily", "weekly", "off"):
                raise HTTPException(422, "digest debe ser daily|weekly|off.")
            _set("notif_pref_digest", req.digest)
        if req.digest_time:
            try:
                h, m = req.digest_time.split(":")
                datetime.strptime(f"{int(h)}:{int(m)}", "%H:%M")
            except (ValueError, TypeError):
                raise HTTPException(422, "digest_time debe ser HH:MM.")
            _set("notif_pref_digest_time", req.digest_time)
        if req.weekly_weekday is not None:
            if not 0 <= int(req.weekly_weekday) <= 6:
                raise HTTPException(422, "weekly_weekday debe ser 0..6.")
            _set("notif_pref_weekly_weekday", str(int(req.weekly_weekday)))
        if req.email:
            _set("notif_pref_email", req.email)

        if not updated:
            raise HTTPException(422, "No se envió ningún campo de preferencia.")
        return {"ok": True, "updated": updated}

    return router


def _html_to_text(html: str) -> str:
    """Convierte un HTML simple a texto plano (para el cuerpo plain-text)."""
    import re
    text = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]
