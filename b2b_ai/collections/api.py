# -*- coding: utf-8 -*-
"""
api.py — Router FastAPI de cobranza automatizada (/api/v1/collections/*).

Endpoints:
    POST /api/v1/collections/analyze        Analiza la cartera y clasifica
                                            por antigüedad + score.
    POST /api/v1/collections/send-reminder  Genera (y registra) un
                                            recordatorio.
    GET  /api/v1/collections/aging          Reporte de antigüedad de la
                                            cartera persistida.
    GET  /api/v1/collections/projection     Proyección de cobro esperado.
    GET  /api/v1/collections/summary        Resumen ejecutivo de cobranza.
    GET  /api/v1/collections/score/{id}     Score de cobrabilidad de una
                                            factura.
    GET  /api/v1/collections/events         Historial de eventos de cobranza.
    GET  /api/v1/collections/outstanding    Lista la cartera pendiente.
    POST /api/v1/collections/schedule       Programa recordatorios automáticos.
    GET  /api/v1/collections/schedule       Lista recordatorios programados.
    POST /api/v1/collections/schedule/process  Procesa recordatorios vencidos.
    GET  /api/v1/collections/schedule/stats    Estadísticas de la cola.
    POST /api/v1/collections/webhook        Recibe webhook de pago.
    POST /api/v1/collections/webhook/batch  Webhooks en lote.
    GET  /api/v1/collections/webhook/history/{id}  Historial de pagos.
    GET  /api/v1/collections/pdf/{type}     Genera reporte PDF.

El router se construye con `build_collections_router(db, require_api_key)`.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from b2b_ai.collections.models import (
    CollectionsAnalyzeRequest,
    CollectionsScheduleRequest,
    CollectionsSendReminderRequest,
    CollectionWebhookPayload,
)
from b2b_ai.collections.scheduler import CollectionsScheduler
from b2b_ai.collections.webhooks import CollectionsWebhookHandler
from b2b_ai.services.collections import CollectionsManager, days_overdue
from b2b_ai.services.collections_report import aging_report, projection, summary


def build_collections_router(
    db,
    require_api_key: Callable[..., Dict],
) -> APIRouter:
    """Construye el APIRouter de cobranza automatizada.

    Args:
        db:              instancia de Database.
        require_api_key: dependencia de auth (Depends).
    """
    router = APIRouter(prefix="/api/v1/collections", tags=["collections"])

    # ------------------------------------------------------------------ #
    # Análisis
    # ------------------------------------------------------------------ #

    @router.post("/analyze",
                 summary="Analiza la cartera pendiente (clasifica por "
                         "antigüedad y calcula score).")
    def analyze(req: CollectionsAnalyzeRequest,
                auth_info: dict = Depends(require_api_key)):
        """Recibe la cartera de cuentas por cobrar y la clasifica por
        antigüedad (0-30, 31-60, 61-90, 90+), calculando el score de
        cobrabilidad por factura. Si `sync` es True, persiste la cartera
        en la tabla `outstanding_invoices`."""
        tenant = auth_info.get("tenant_id")
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        res = mgr.analyze(req.invoices)
        if req.sync:
            mgr.sync_outstanding(req.invoices, delete_paid=True)
        res["sync"] = req.sync
        return res

    # ------------------------------------------------------------------ #
    # Recordatorios
    # ------------------------------------------------------------------ #

    @router.post("/send-reminder",
                 summary="Genera (y opcionalmente registra) un recordatorio.")
    def send_reminder(req: CollectionsSendReminderRequest,
                      auth_info: dict = Depends(require_api_key)):
        """Genera el contenido del recordatorio para la etapa y canal dados.
        NO envía mensajes reales. Si `record` es True, registra el intento
        en `collection_events` con timestamp."""
        tenant = auth_info.get("tenant_id")
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        try:
            return mgr.send_reminder(req.invoice, stage=req.stage,
                                     channel=req.channel, record=req.record)
        except KeyError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # ------------------------------------------------------------------ #
    # Reportes
    # ------------------------------------------------------------------ #

    @router.get("/aging",
                summary="Reporte de antigüedad de la cartera.")
    def aging(auth_info: dict = Depends(require_api_key)):
        """Reporte de antigüedad de la cartera persistida en
        `outstanding_invoices` (requiere haber hecho un analyze con
        sync=True)."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(tenant_id=tenant)
        for r in rows:
            r["dias_vencido"] = days_overdue(r["fecha_vencimiento"])
        result = aging_report(rows)
        result["tenant_id"] = tenant
        return result

    @router.get("/projection",
                summary="Proyección de cobro esperado por score.")
    def projection_report(auth_info: dict = Depends(require_api_key)):
        """Proyección de cobro esperado ponderando cada factura por su score
        de cobrabilidad. Muestra montos proyectados por bucket y rango de
        score."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(tenant_id=tenant)
        for r in rows:
            r["dias_vencido"] = days_overdue(r["fecha_vencimiento"])
        result = projection(rows)
        result["tenant_id"] = tenant
        return result

    @router.get("/summary",
                summary="Resumen ejecutivo de cobranza.")
    def summary_report(auth_info: dict = Depends(require_api_key)):
        """Resumen ejecutivo de cobranza: montos, tasas, alertas y top 5
        montos pendientes más altos."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(tenant_id=tenant)
        for r in rows:
            r["dias_vencido"] = days_overdue(r["fecha_vencimiento"])
        result = summary(rows)
        result["tenant_id"] = tenant
        return result

    # ------------------------------------------------------------------ #
    # Score individual
    # ------------------------------------------------------------------ #

    @router.get("/score/{invoice_id}",
                summary="Score de cobrabilidad de una factura.")
    def score(invoice_id: str,
              auth_info: dict = Depends(require_api_key)):
        """Score de cobrabilidad (0..1) para una factura de la cartera
        persistida, junto con su historial de intentos de cobranza."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(
            tenant_id=tenant, factura_id=str(invoice_id))
        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Factura no encontrada en la cartera.")
        inv = rows[0]
        history = db.list_collection_events(
            tenant_id=tenant, factura_id=str(invoice_id))
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        return {
            "factura_id": inv["factura_id"],
            "monto": inv["monto"],
            "fecha_vencimiento": inv["fecha_vencimiento"],
            "dias_vencido": inv["dias_vencido"],
            "score": mgr.collectability_score(
                inv, dias_vencido=inv["dias_vencido"], history=history),
            "historial": history,
        }

    # ------------------------------------------------------------------ #
    # Eventos y cartera
    # ------------------------------------------------------------------ #

    @router.get("/events",
                summary="Historial de eventos de cobranza.")
    def list_events(
        factura_id: Optional[str] = Query(None),
        limit: int = Query(default=100, ge=1, le=500),
        auth_info: dict = Depends(require_api_key),
    ):
        """Lista el historial de eventos de cobranza (recordatorios,
        respuestas, webhooks de pago) para el tenant."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_collection_events(
            tenant_id=tenant,
            factura_id=factura_id,
            limit=limit,
        )
        return {"count": len(rows), "events": rows, "tenant_id": tenant}

    @router.get("/outstanding",
                summary="Lista la cartera de cuentas por cobrar.")
    def list_outstanding(
        limit: int = Query(default=200, ge=1, le=1000),
        auth_info: dict = Depends(require_api_key),
    ):
        """Lista todas las facturas pendientes de la cartera del tenant,
        ordenadas por días de atraso (mayor a menor)."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(tenant_id=tenant, limit=limit)
        return {"count": len(rows), "invoices": rows, "tenant_id": tenant}

    # ------------------------------------------------------------------ #
    # Scheduler
    # ------------------------------------------------------------------ #

    @router.post("/schedule",
                 summary="Programa recordatorios automáticos para la cartera.")
    def schedule_reminders(
        req: CollectionsScheduleRequest,
        auth_info: dict = Depends(require_api_key),
    ):
        """Programa la secuencia de recordatorios para la cartera dada.
        Cada factura recibe un recordatorio según el stage que le
        corresponda por su antigüedad."""
        tenant = auth_info.get("tenant_id")
        sched = CollectionsScheduler(db=db, tenant_id=tenant)
        result = sched.schedule_batch(
            req.invoices, channels=req.channels)
        if req.auto_send:
            sent = sched.process_pending()
            result["auto_send_result"] = sent
        return result

    @router.get("/schedule",
                summary="Lista recordatorios programados.")
    def list_scheduled(
        status: Optional[str] = Query(None),
        auth_info: dict = Depends(require_api_key),
    ):
        """Lista los recordatorios programados del tenant."""
        tenant = auth_info.get("tenant_id")
        sched = CollectionsScheduler(db=db, tenant_id=tenant)
        reminders = sched.list_all()
        if status:
            reminders = [r for r in reminders if r.get("status") == status]
        return {"count": len(reminders), "reminders": reminders}

    @router.post("/schedule/process",
                 summary="Procesa recordatorios vencidos.")
    def process_scheduled(
        auth_info: dict = Depends(require_api_key),
    ):
        """Procesa los recordatorios cuya fecha de envío ya llegó.
        Genera el contenido, lo registra en collection_events y marca
        los reminders como 'sent'."""
        tenant = auth_info.get("tenant_id")
        sched = CollectionsScheduler(db=db, tenant_id=tenant)
        return sched.process_pending()

    @router.get("/schedule/stats",
                summary="Estadísticas de la cola de recordatorios.")
    def schedule_stats(
        auth_info: dict = Depends(require_api_key),
    ):
        """Estadísticas de la cola: total, por status, por stage, por canal."""
        tenant = auth_info.get("tenant_id")
        sched = CollectionsScheduler(db=db, tenant_id=tenant)
        return sched.get_stats()

    @router.post("/schedule/{factura_id}/cancel",
                 summary="Cancela un recordatorio pendiente.")
    def cancel_scheduled(
        factura_id: str,
        stage: str = Query(...),
        channel: str = Query(default="email"),
        auth_info: dict = Depends(require_api_key),
    ):
        """Cancela un recordatorio pendiente para una factura/etapa/canal."""
        tenant = auth_info.get("tenant_id")
        sched = CollectionsScheduler(db=db, tenant_id=tenant)
        ok = sched.cancel_reminder(factura_id, stage, channel)
        if not ok:
            raise HTTPException(
                404, "Recordatorio no encontrado o no está pendiente.")
        return {"ok": True, "cancelled": True}

    # ------------------------------------------------------------------ #
    # Webhooks de pago
    # ------------------------------------------------------------------ #

    @router.post("/webhook",
                 summary="Recibe webhook de confirmación de pago.")
    def webhook(payload: CollectionWebhookPayload,
                auth_info: dict = Depends(require_api_key)):
        """Recibe un webhook de pago desde un gateway (SPEI, Stripe, Conekta)
        o un ERP, y actualiza la cartera de cuentas por cobrar."""
        tenant = auth_info.get("tenant_id")
        handler = CollectionsWebhookHandler(db=db, tenant_id=tenant)
        wh_data = payload.model_dump()
        if wh_data.get("tenant_id") is None:
            wh_data["tenant_id"] = tenant
        return handler.process_webhook(wh_data)

    @router.post("/webhook/batch",
                 summary="Procesa múltiples webhooks de pago en lote.")
    def webhook_batch(
        webhooks: List[CollectionWebhookPayload],
        auth_info: dict = Depends(require_api_key),
    ):
        """Procesa múltiples webhooks de pago en un solo request."""
        tenant = auth_info.get("tenant_id")
        handler = CollectionsWebhookHandler(db=db, tenant_id=tenant)
        payloads = []
        for wh in webhooks:
            d = wh.model_dump()
            if d.get("tenant_id") is None:
                d["tenant_id"] = tenant
            payloads.append(d)
        return handler.batch_process(payloads)

    @router.get("/webhook/history/{invoice_id}",
                summary="Historial de pagos/webhooks de una factura.")
    def webhook_history(
        invoice_id: str,
        auth_info: dict = Depends(require_api_key),
    ):
        """Devuelve el historial de webhooks de pago para una factura."""
        tenant = auth_info.get("tenant_id")
        handler = CollectionsWebhookHandler(db=db, tenant_id=tenant)
        history = handler.get_payment_history(invoice_id)
        return {"invoice_id": invoice_id, "payments": history}

    # ------------------------------------------------------------------ #
    # PDF reports
    # ------------------------------------------------------------------ #

    @router.get("/pdf/{report_type}",
                summary="Genera un reporte PDF de cobranza.")
    def collections_pdf(
        report_type: str,
        auth_info: dict = Depends(require_api_key),
    ):
        """Genera un reporte PDF de cobranza (aging, projection, summary)."""
        tenant = auth_info.get("tenant_id")
        rows = db.list_outstanding_invoices(tenant_id=tenant)
        for r in rows:
            r["dias_vencido"] = days_overdue(r["fecha_vencimiento"])

        if report_type == "aging":
            from b2b_ai.collections.pdf_report import generate_aging_pdf
            pdf_bytes = generate_aging_pdf(rows, tenant_id=tenant)
            filename = f"reporte_cobranza_aging_{_today_str()}.pdf"
        elif report_type == "projection":
            from b2b_ai.collections.pdf_report import generate_projection_pdf
            pdf_bytes = generate_projection_pdf(rows, tenant_id=tenant)
            filename = f"reporte_cobranza_proyeccion_{_today_str()}.pdf"
        elif report_type == "summary":
            from b2b_ai.collections.pdf_report import generate_summary_pdf
            pdf_bytes = generate_summary_pdf(rows, tenant_id=tenant)
            filename = f"reporte_cobranza_resumen_{_today_str()}.pdf"
        else:
            raise HTTPException(
                400,
                f"Tipo de reporte inválido: {report_type}. "
                "Válidos: aging, projection, summary")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    return router


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")
