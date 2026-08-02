# -*- coding: utf-8 -*-
"""
ar_manager.py — AR (Accounts Receivable) End-to-End Manager.

Full AR flow:
  1. Generate/track issued invoices
  2. Send to client
  3. Track collections
  4. Generate payment complements (complemento de pago)
  5. Reconcile
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from b2b_ai.features.ap_ar.models import (
    ARInvoice,
    ARInvoiceCreate,
    CollectRequest,
    CollectResult,
    InvoiceStatus,
)
from b2b_ai.features.ap_ar.aging_report import AgingReportGenerator


class ARManager:
    """Full Accounts Receivable pipeline: invoice generation → sending →
    collection → payment complement → reconciliation."""

    def __init__(self, db=None, tenant_id: Optional[int] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.aging = AgingReportGenerator()
        self._invoices: List[ARInvoice] = []

    # Step 1: Register an issued invoice
    def register_invoice(self, data: ARInvoiceCreate) -> ARInvoice:
        """Register an issued AR invoice (CFDI type I - Ingreso)."""
        now = datetime.utcnow().isoformat()
        inv = ARInvoice(
            id=len(self._invoices) + 1,
            tenant_id=self.tenant_id,
            uuid=data.uuid,
            rfc_emisor=data.rfc_emisor,
            rfc_receptor=data.rfc_receptor,
            nombre_receptor=data.nombre_receptor,
            subtotal=data.subtotal,
            iva=data.iva,
            total=data.total,
            fecha_emision=data.fecha_emision,
            fecha_vencimiento=data.fecha_vencimiento,
            metodo_pago=data.metodo_pago,
            status=InvoiceStatus.PENDING,
            concepto=data.concepto,
            created_at=now,
            updated_at=now,
        )
        self._invoices.append(inv)
        return inv

    # Step 2: Mark as sent
    def mark_sent(self, invoice_id: int) -> ARInvoice:
        """Mark an invoice as sent to the client."""
        inv = self._get_invoice(invoice_id)
        if inv is None:
            raise ValueError(f"Invoice {invoice_id} not found")
        inv.status = InvoiceStatus.VALIDATED
        inv.updated_at = datetime.utcnow().isoformat()
        return inv

    # Step 3: Collect payment
    def collect(self, request: CollectRequest) -> CollectResult:
        """Process a collection for an AR invoice.

        Updates the invoice status based on collection amount.
        """
        inv = self._get_invoice(request.ar_invoice_id)
        if inv is None:
            raise ValueError(f"AR invoice {request.ar_invoice_id} not found")

        saldo_pendiente = inv.total - inv.monto_cobrado
        if request.monto > saldo_pendiente + 0.01:
            raise ValueError(
                f"Cobro ({request.monto}) excede saldo pendiente ({saldo_pendiente})"
            )

        inv.monto_cobrado = round(inv.monto_cobrado + request.monto, 2)
        inv.updated_at = datetime.utcnow().isoformat()

        if inv.monto_cobrado >= inv.total - 0.01:
            if inv.metodo_pago == "PPD":
                inv.status = InvoiceStatus.COLLECTED
            else:
                inv.status = InvoiceStatus.PAID
        else:
            inv.status = InvoiceStatus.PARTIAL

        return CollectResult(
            ar_invoice_id=request.ar_invoice_id,
            monto_cobrado=request.monto,
            nuevo_status=inv.status.value,
            generar_complemento=request.generar_complemento
            and inv.metodo_pago == "PPD",
        )

    # Step 4: Generate payment complement
    def build_complemento_pago(self, invoice_id: int, monto: float) -> dict:
        """Build a payment complement (CFDI type P) for a PPD invoice.

        Reference: Art. 29-A fracc. VII CFF.
        Must be issued within 5 business days of receiving payment.
        """
        inv = self._get_invoice(invoice_id)
        if inv is None:
            raise ValueError(f"Invoice {invoice_id} not found")
        if inv.metodo_pago != "PPD":
            raise ValueError(
                "Complemento de pago solo aplica a facturas con método PPD"
            )

        return {
            "type": "P",  # Pago
            "related_documents": [
                {
                    "id": inv.uuid,
                    "method": "PPD",
                    "partiality": 1,
                    "balance": round(inv.total - inv.monto_cobrado, 2),
                    "amount": monto,
                }
            ],
            "complement": {
                "payments": [
                    {
                        "date": datetime.now().strftime(
                            "%Y-%m-%dT%H:%M:%S"
                        ),
                        "payment_form": "03",  # Transferencia
                        "currency": "MXN",
                        "amount": monto,
                    }
                ]
            },
        }

    # Step 5: Aging report
    def get_aging_report(self) -> dict:
        """Get the AR aging report."""
        report = self.aging.generate_ar(self._invoices)
        return report.model_dump()

    def get_aging_by_client(self) -> List[dict]:
        """Get aging breakdown by client."""
        entries = self.aging.aging_by_entity_ar(self._invoices)
        return [e.model_dump() for e in entries]

    # Step 6: List invoices
    def list_invoices(
        self,
        status: Optional[InvoiceStatus] = None,
        rfc_receptor: Optional[str] = None,
    ) -> List[dict]:
        """List AR invoices with optional filters."""
        result = self._invoices
        if status:
            result = [i for i in result if i.status == status]
        if rfc_receptor:
            result = [i for i in result if i.rfc_receptor == rfc_receptor]
        return [i.model_dump() for i in result]

    def get_invoice(self, invoice_id: int) -> Optional[dict]:
        """Get a single AR invoice by ID."""
        inv = self._get_invoice(invoice_id)
        return inv.model_dump() if inv else None

    # Helpers
    def _get_invoice(self, invoice_id: int) -> Optional[ARInvoice]:
        for inv in self._invoices:
            if inv.id == invoice_id:
                return inv
        return None

    def count_invoices(self) -> int:
        return len(self._invoices)

    def total_outstanding(self) -> float:
        """Total amount outstanding (not fully collected)."""
        return round(sum(
            inv.total - inv.monto_cobrado for inv in self._invoices
            if inv.status not in (
                InvoiceStatus.PAID,
                InvoiceStatus.COLLECTED,
                InvoiceStatus.CANCELLED,
            )
        ), 2)
