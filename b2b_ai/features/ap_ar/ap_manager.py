# -*- coding: utf-8 -*-
"""
ap_manager.py — AP (Accounts Payable) End-to-End Manager.

Full AP flow:
  1. Receive supplier CFDI
  2. Validate (structure, UUID, RFC, EFOS)
  3. Register in accounting system
  4. Track aging
  5. Schedule payments
  6. Execute SPEI payments
  7. Post-payment reconciliation
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from b2b_ai.features.ap_ar.models import (
    APInvoice,
    APInvoiceCreate,
    InvoiceStatus,
    PaymentOrder,
    RetentionType,
)
from b2b_ai.features.ap_ar.aging_report import AgingReportGenerator
from b2b_ai.features.ap_ar.payment_scheduler import PaymentScheduler
from b2b_ai.features.ap_ar.retention_engine import RetentionEngine
from b2b_ai.features.ap_ar.spei_payment import SPEIPayment


class APManager:
    """Full Accounts Payable pipeline: CFDI receipt → validation →
    registration → aging → payment scheduling → SPEI execution."""

    def __init__(
        self,
        db=None,
        tenant_id: Optional[int] = None,
        scheduler: Optional[PaymentScheduler] = None,
        spei: Optional[SPEIPayment] = None,
        retention_engine: Optional[RetentionEngine] = None,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.scheduler = scheduler or PaymentScheduler()
        self.spei = spei or SPEIPayment()
        self.retention_engine = retention_engine or RetentionEngine()
        self.aging = AgingReportGenerator()
        self._invoices: List[APInvoice] = []

    # Step 1: Receive & validate CFDI
    def receive_invoice(self, data: APInvoiceCreate) -> APInvoice:
        """Receive and register a supplier CFDI.

        Validates structure and creates an AP invoice record.
        """
        self._validate_cfdi(data)

        now = datetime.utcnow().isoformat()
        inv = APInvoice(
            id=len(self._invoices) + 1,
            tenant_id=self.tenant_id,
            uuid=data.uuid,
            rfc_emisor=data.rfc_emisor,
            nombre_emisor=data.nombre_emisor,
            rfc_receptor=data.rfc_receptor,
            subtotal=data.subtotal,
            iva=data.iva,
            total=data.total,
            fecha_emision=data.fecha_emision,
            fecha_vencimiento=data.fecha_vencimiento,
            metodo_pago=data.metodo_pago,
            forma_pago=data.forma_pago,
            status=InvoiceStatus.VALIDATED,
            concepto=data.concepto,
            cuenta_contable=data.cuenta_contable,
            created_at=now,
            updated_at=now,
        )
        self._invoices.append(inv)

        # Calculate retention if applicable
        tipo_ret = self.retention_engine.detectar_tipo_retencion(
            data.rfc_emisor, data.concepto
        )
        if tipo_ret:
            result = self.retention_engine.calcular_retencion(
                data.rfc_emisor, tipo_ret, data.subtotal
            )
            if result.aplica_retencion:
                inv.retencion_isr = result.retencion

        return inv

    def _validate_cfdi(self, data: APInvoiceCreate) -> None:
        """Validate CFDI data (structure, amounts)."""
        if not data.uuid or len(data.uuid) < 10:
            raise ValueError("UUID inválido o faltante")
        if not data.rfc_emisor or len(data.rfc_emisor) < 12:
            raise ValueError("RFC emisor inválido")
        if data.subtotal < 0:
            raise ValueError("Subtotal no puede ser negativo")
        if data.total < 0:
            raise ValueError("Total no puede ser negativo")
        expected_total = round(data.subtotal + data.iva, 2)
        if abs(data.total - expected_total) > 0.02:
            raise ValueError(
                f"Total ({data.total}) no cuadra con subtotal + IVA "
                f"({expected_total})"
            )

    # Step 2: Register in accounting
    def register_invoice(self, invoice_id: int) -> APInvoice:
        """Mark invoice as registered in the accounting system."""
        inv = self._get_invoice(invoice_id)
        if inv is None:
            raise ValueError(f"AP invoice {invoice_id} not found")
        inv.status = InvoiceStatus.REGISTERED
        inv.updated_at = datetime.utcnow().isoformat()
        return inv

    # Step 3: Get aging report
    def get_aging_report(self) -> dict:
        """Get the AP aging report."""
        report = self.aging.generate_ap(self._invoices)
        return report.model_dump()

    def get_aging_by_supplier(self) -> List[dict]:
        """Get aging breakdown by supplier."""
        entries = self.aging.aging_by_entity_ap(self._invoices)
        return [e.model_dump() for e in entries]

    # Step 4: Schedule payments
    def schedule_payments(
        self, cash_available: float, max_payments: int = 50
    ) -> List[dict]:
        """Schedule payments for pending invoices."""
        schedule = self.scheduler.schedule_payments(
            self._invoices, cash_available, max_payments=max_payments
        )
        # Mark scheduled invoices
        for entry in schedule:
            for inv in self._invoices:
                if inv.id == entry.payment_order.ap_invoice_id:
                    inv.status = InvoiceStatus.SCHEDULED
                    inv.updated_at = datetime.utcnow().isoformat()
                    break

        return [s.model_dump() for s in schedule]

    # Step 5: Execute SPEI payment
    async def execute_payment(self, payment_order: PaymentOrder) -> dict:
        """Execute a SPEI payment via STP."""
        result = await self.spei.enviar_pago(payment_order)

        if result.get("status") == "LIQUIDACION":
            # Mark invoice as paid
            if payment_order.ap_invoice_id:
                for inv in self._invoices:
                    if inv.id == payment_order.ap_invoice_id:
                        inv.monto_pagado = inv.total - inv.retencion_isr
                        inv.status = InvoiceStatus.PAID
                        inv.updated_at = datetime.utcnow().isoformat()
                        break

        return result

    # Step 6: List invoices
    def list_invoices(
        self,
        status: Optional[InvoiceStatus] = None,
        rfc_emisor: Optional[str] = None,
    ) -> List[dict]:
        """List AP invoices with optional filters."""
        result = self._invoices
        if status:
            result = [i for i in result if i.status == status]
        if rfc_emisor:
            result = [i for i in result if i.rfc_emisor == rfc_emisor]
        return [i.model_dump() for i in result]

    def get_invoice(self, invoice_id: int) -> Optional[dict]:
        """Get a single AP invoice by ID."""
        inv = self._get_invoice(invoice_id)
        return inv.model_dump() if inv else None

    # Helpers
    def _get_invoice(self, invoice_id: int) -> Optional[APInvoice]:
        for inv in self._invoices:
            if inv.id == invoice_id:
                return inv
        return None

    def count_invoices(self) -> int:
        return len(self._invoices)

    def total_pending(self) -> float:
        """Total amount pending payment."""
        return round(sum(
            inv.total - inv.monto_pagado for inv in self._invoices
            if inv.status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED)
        ), 2)
