# -*- coding: utf-8 -*-
"""
payment_scheduler.py — Payment scheduling by due date, priority, and cash flow.

Schedules AP payments based on:
  - Due date proximity
  - Invoice priority
  - Available cash flow
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from b2b_ai.features.ap_ar.models import (
    APInvoice,
    InvoiceStatus,
    PaymentOrder,
    PaymentScheduleEntry,
)


def _days_until(date_str: str, today: Optional[date] = None) -> int:
    """Days until a date (negative = past due)."""
    today = today or date.today()
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (d - today).days
    except (ValueError, TypeError):
        return 0


class PaymentScheduler:
    """Schedules AP payments for optimal cash flow management."""

    def __init__(
        self,
        clabe_ordenante: str = "",
        nombre_ordenante: str = "",
        rfc_ordenante: str = "",
        institucion_ordenante: int = 0,
        empresa: str = "",
    ):
        self.clabe_ordenante = clabe_ordenante
        self.nombre_ordenante = nombre_ordenante
        self.rfc_ordenante = rfc_ordenante
        self.institucion_ordenante = institucion_ordenante
        self.empresa = empresa

    def schedule_payments(
        self,
        invoices: List[APInvoice],
        cash_available: float,
        today: Optional[date] = None,
        max_payments: int = 50,
    ) -> List[PaymentScheduleEntry]:
        """Schedule payments for pending AP invoices.

        Prioritizes by:
        1. Already overdue (highest priority)
        2. Days until due (soonest first)
        3. Larger amounts first (tiebreaker)

        Stops when cash is exhausted or max_payments reached.

        Args:
            invoices: List of AP invoices to consider.
            cash_available: Total cash available for payments.
            today: Reference date (defaults to today).
            max_payments: Max number of payments to schedule.

        Returns:
            List of PaymentScheduleEntry sorted by priority.
        """
        today = today or date.today()

        # Filter to schedulable invoices
        pending = [
            inv for inv in invoices
            if inv.status in (
                InvoiceStatus.PENDING,
                InvoiceStatus.VALIDATED,
                InvoiceStatus.REGISTERED,
                InvoiceStatus.OVERDUE,
                InvoiceStatus.SCHEDULED,
            )
        ]

        # Sort: overdue first (by days overdue desc), then by days until due
        def sort_key(inv: APInvoice):
            dias = _days_until(inv.fecha_vencimiento, today)
            # Overdue → negative days; sort so most overdue first
            return dias

        pending.sort(key=sort_key)

        schedule = []
        remaining_cash = cash_available

        for inv in pending:
            if len(schedule) >= max_payments:
                break

            monto_pagar = inv.total - inv.monto_pagado - inv.retencion_isr
            monto_pagar = round(max(0, monto_pagar), 2)

            if monto_pagar <= 0:
                continue

            if monto_pagar > remaining_cash:
                continue

            dias = _days_until(inv.fecha_vencimiento, today)
            dias_vencimiento = dias
            prioridad_efectiva = self._calculate_priority(dias)

            order = PaymentOrder(
                ap_invoice_id=inv.id,
                clave_rastreo=self._generate_tracking_key(inv),
                concepto_pago=inv.concepto or f"Pago factura {inv.uuid[:8]}",
                cuenta_beneficiario="",  # Would be populated from supplier DB
                cuenta_ordenante=self.clabe_ordenante,
                nombre_beneficiario=inv.nombre_emisor,
                nombre_ordenante=self.nombre_ordenante,
                rfc_beneficiario=inv.rfc_emisor,
                rfc_ordenante=self.rfc_ordenante,
                institucion_ordenante=self.institucion_ordenante,
                empresa=self.empresa,
                monto=monto_pagar,
                prioridad=prioridad_efectiva,
                fecha_programada=self._compute_payment_date(inv, today),
                status="programado",
            )

            schedule.append(PaymentScheduleEntry(
                payment_order=order,
                dias_para_vencimiento=dias_vencimiento,
                prioridad_efectiva=prioridad_efectiva,
            ))

            remaining_cash -= monto_pagar

        # Sort by effective priority (1 = highest)
        schedule.sort(key=lambda s: s.prioridad_efectiva)
        return schedule

    def _calculate_priority(self, days_until_due: int) -> int:
        """Calculate payment priority from days until due.

        1 = highest (overdue or due today)
        2 = due within 3 days
        3 = due within 7 days
        5 = due within 30 days
        7 = due within 60 days
        10 = due in 60+ days
        """
        if days_until_due <= 0:
            return 1
        if days_until_due <= 3:
            return 2
        if days_until_due <= 7:
            return 3
        if days_until_due <= 30:
            return 5
        if days_until_due <= 60:
            return 7
        return 10

    def _generate_tracking_key(self, inv: APInvoice) -> str:
        """Generate a SPEI tracking key (clave de rastreo)."""
        prefix = self.empresa[:4].upper() if self.empresa else "LIKA"
        date_part = datetime.now().strftime("%Y%m%d%H%M%S")
        uuid_part = inv.uuid[:8].replace("-", "").upper()
        return f"{prefix}{date_part}{uuid_part}"

    def _compute_payment_date(
        self, inv: APInvoice, today: date
    ) -> str:
        """Compute the optimal payment date.

        For overdue invoices: today (ASAP).
        For upcoming: 1 day before due date to optimize cash flow.
        """
        try:
            due = datetime.strptime(inv.fecha_vencimiento[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return today.isoformat()

        if due <= today:
            return today.isoformat()

        # Pay 1 day before due, but not before today
        from datetime import timedelta
        optimal = due - timedelta(days=1)
        return max(optimal, today).isoformat()

    def calculate_total_scheduled(
        self, schedule: List[PaymentScheduleEntry]
    ) -> float:
        """Sum of all scheduled payment amounts."""
        return round(
            sum(s.payment_order.monto for s in schedule), 2
        )
