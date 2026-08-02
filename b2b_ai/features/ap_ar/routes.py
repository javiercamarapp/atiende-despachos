# -*- coding: utf-8 -*-
"""
routes.py — FastAPI endpoints for AP/AR End-to-End (Agente 4).

Endpoints:
    POST /ap/invoices      — Receive & register a supplier CFDI
    GET  /ap/invoices      — List AP invoices with filters
    GET  /ap/aging         — AP aging report
    POST /ap/pay           — Schedule and/or execute AP payments
    GET  /ar/invoices      — List AR invoices with filters
    POST /ar/invoices      — Register an issued AR invoice
    POST /ar/collect       — Process AR collection
    GET  /ar/aging         — AR aging report
    POST /ar/complement    — Generate payment complement
    POST /notas-credito    — Create a credit note
    GET  /retenciones      — Calculate ISR retention

Router built with `build_ap_ar_router()` for DI.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from b2b_ai.features.ap_ar.ap_manager import APManager
from b2b_ai.features.ap_ar.ar_manager import ARManager
from b2b_ai.features.ap_ar.models import (
    APInvoiceCreate,
    ARInvoiceCreate,
    CollectRequest,
    CreditNoteCreate,
    InvoiceStatus,
    RetentionType,
)
from b2b_ai.features.ap_ar.notas_credito import NotasCredito
from b2b_ai.features.ap_ar.retention_engine import RetentionEngine
from b2b_ai.features.ap_ar.spei_payment import SPEIPayment
from b2b_ai.features.ap_ar.payment_scheduler import PaymentScheduler


class PayRequest(BaseModel):
    """Request to schedule/execute AP payments."""
    cash_available: float
    max_payments: int = 50
    execute: bool = False


class RetentionRequest(BaseModel):
    """Request to calculate retention."""
    proveedor_rfc: str
    tipo_servicio: str = "servicios_profesionales"
    monto_factura: float


# Singleton managers (injected via build_ap_ar_router)
_ap_manager: Optional[APManager] = None
_ar_manager: Optional[ARManager] = None
_notas_credito: Optional[NotasCredito] = None


def build_ap_ar_router(require_api_key=None) -> APIRouter:
    """Build and return the AP/AR router.

    Creates module-level managers for simplicity. In production,
    these would be injected per-tenant from the database.
    """
    global _ap_manager, _ar_manager, _notas_credito

    _ap_manager = _ap_manager or APManager()
    _ar_manager = _ar_manager or ARManager()
    _notas_credito = _notas_credito or NotasCredito()

    router = APIRouter(tags=["ap-ar"])
    if require_api_key:
        router.dependencies.append(Depends(require_api_key))

    # ------------------------------------------------------------------ #
    # AP endpoints
    # ------------------------------------------------------------------ #

    @router.post("/ap/invoices", summary="Receive & register a supplier CFDI")
    async def ap_receive_invoice(data: APInvoiceCreate):
        try:
            inv = _ap_manager.receive_invoice(data)
            return {"ok": True, "invoice": inv.model_dump()}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/ap/invoices", summary="List AP invoices")
    async def ap_list_invoices(
        status: Optional[str] = None,
        rfc_emisor: Optional[str] = None,
    ):
        st = None
        if status:
            try:
                st = InvoiceStatus(status)
            except ValueError:
                raise HTTPException(400, f"Status inválido: {status}")
        invoices = _ap_manager.list_invoices(status=st, rfc_emisor=rfc_emisor)
        return {"count": len(invoices), "invoices": invoices}

    @router.get("/ap/aging", summary="AP aging report")
    async def ap_aging(by_supplier: bool = False):
        if by_supplier:
            entries = _ap_manager.get_aging_by_supplier()
            return {"type": "ap_by_supplier", "entries": entries}
        return _ap_manager.get_aging_report()

    @router.post("/ap/pay", summary="Schedule and/or execute AP payments")
    async def ap_pay(request: PayRequest):
        schedule = _ap_manager.schedule_payments(
            cash_available=request.cash_available,
            max_payments=request.max_payments,
        )
        results = []
        if request.execute and schedule:
            import asyncio
            for entry in schedule:
                order_data = entry.get("payment_order", {})
                # Reconstruct PaymentOrder from dict
                from b2b_ai.features.ap_ar.models import PaymentOrder
                order = PaymentOrder(**order_data)
                result = await _ap_manager.execute_payment(order)
                results.append(result)
        return {
            "scheduled": len(schedule),
            "total": _ap_manager.scheduler.calculate_total_scheduled(
                _ap_manager.scheduler.schedule_payments(
                    _ap_manager._invoices, request.cash_available
                )
            ),
            "schedule": schedule,
            "executed": results if request.execute else None,
        }

    # ------------------------------------------------------------------ #
    # AR endpoints
    # ------------------------------------------------------------------ #

    @router.post("/ar/invoices", summary="Register an issued AR invoice")
    async def ar_register_invoice(data: ARInvoiceCreate):
        inv = _ar_manager.register_invoice(data)
        return {"ok": True, "invoice": inv.model_dump()}

    @router.get("/ar/invoices", summary="List AR invoices")
    async def ar_list_invoices(
        status: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
    ):
        st = None
        if status:
            try:
                st = InvoiceStatus(status)
            except ValueError:
                raise HTTPException(400, f"Status inválido: {status}")
        invoices = _ar_manager.list_invoices(status=st, rfc_receptor=rfc_receptor)
        return {"count": len(invoices), "invoices": invoices}

    @router.post("/ar/collect", summary="Process AR collection")
    async def ar_collect(request: CollectRequest):
        try:
            result = _ar_manager.collect(request)
            return {"ok": True, "result": result.model_dump()}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/ar/aging", summary="AR aging report")
    async def ar_aging(by_client: bool = False):
        if by_client:
            entries = _ar_manager.get_aging_by_client()
            return {"type": "ar_by_client", "entries": entries}
        return _ar_manager.get_aging_report()

    @router.post("/ar/complement", summary="Generate payment complement")
    async def ar_complement(invoice_id: int, monto: float):
        try:
            complement = _ar_manager.build_complemento_pago(invoice_id, monto)
            return {"ok": True, "complemento": complement}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # ------------------------------------------------------------------ #
    # Shared endpoints
    # ------------------------------------------------------------------ #

    @router.post("/notas-credito", summary="Create a credit note")
    async def crear_nota_credito(data: CreditNoteCreate):
        note = _notas_credito.crear_nota_credito(data)
        return {"ok": True, "nota": note.model_dump()}

    @router.get("/retenciones/calcular", summary="Calculate ISR retention")
    async def calcular_retencion(
        proveedor_rfc: str,
        tipo_servicio: str = "servicios_profesionales",
        monto_factura: float = 0.0,
    ):
        engine = RetentionEngine()
        try:
            tipo = RetentionType(tipo_servicio)
        except ValueError:
            raise HTTPException(400, f"Tipo de retención inválido: {tipo_servicio}")
        result = engine.calcular_retencion(proveedor_rfc, tipo, monto_factura)
        return result.model_dump()

    return router
