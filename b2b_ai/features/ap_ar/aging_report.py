# -*- coding: utf-8 -*-
"""
aging_report.py — Aging report generator for AP/AR.

Generates aging dashboards with buckets: 0-30, 31-60, 61-90, 90+ days.
Can aggregate by supplier (AP) or client (AR).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

from b2b_ai.features.ap_ar.models import (
    AgingBucketData,
    AgingEntry,
    AgingReport,
    APInvoice,
    ARInvoice,
    InvoiceStatus,
)


def _days_since(date_str: str, today: Optional[date] = None) -> int:
    """Days elapsed since a date (positive = past, negative = future)."""
    today = today or date.today()
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (today - d).days
    except (ValueError, TypeError):
        return 0


def _bucket_for_days(days: int) -> str:
    """Map days overdue to an aging bucket."""
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


class AgingReportGenerator:
    """Generates aging reports for AP and AR invoices."""

    def generate_ap(
        self,
        invoices: List[APInvoice],
        today: Optional[date] = None,
    ) -> AgingReport:
        """Generate AP aging report from a list of AP invoices."""
        active = [
            inv for inv in invoices
            if inv.status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED)
        ]
        return self._build_report("ap", active, today, field="fecha_vencimiento")

    def generate_ar(
        self,
        invoices: List[ARInvoice],
        today: Optional[date] = None,
    ) -> AgingReport:
        """Generate AR aging report from a list of AR invoices."""
        active = [
            inv for inv in invoices
            if inv.status not in (
                InvoiceStatus.PAID, InvoiceStatus.COLLECTED, InvoiceStatus.CANCELLED
            )
        ]
        return self._build_report_ar("ar", active, today)

    def aging_by_entity_ap(
        self,
        invoices: List[APInvoice],
        today: Optional[date] = None,
    ) -> List[AgingEntry]:
        """Aging breakdown by supplier for AP."""
        today = today or date.today()
        entities: Dict[str, AgingEntry] = {}

        for inv in invoices:
            if inv.status in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED):
                continue

            key = inv.rfc_emisor
            if key not in entities:
                entities[key] = AgingEntry(
                    rfc=key, nombre=inv.nombre_emisor
                )
            entry = entities[key]
            saldo = inv.total - inv.monto_pagado
            dias = _days_since(inv.fecha_vencimiento, today)
            bucket = _bucket_for_days(dias)

            if bucket == "0-30":
                entry.bucket_0_30 += saldo
            elif bucket == "31-60":
                entry.bucket_31_60 += saldo
            elif bucket == "61-90":
                entry.bucket_61_90 += saldo
            else:
                entry.bucket_90_plus += saldo
            entry.total += saldo

        return sorted(entities.values(), key=lambda e: e.total, reverse=True)

    def aging_by_entity_ar(
        self,
        invoices: List[ARInvoice],
        today: Optional[date] = None,
    ) -> List[AgingEntry]:
        """Aging breakdown by client for AR."""
        today = today or date.today()
        entities: Dict[str, AgingEntry] = {}

        for inv in invoices:
            if inv.status in (
                InvoiceStatus.PAID, InvoiceStatus.COLLECTED, InvoiceStatus.CANCELLED
            ):
                continue

            key = inv.rfc_receptor
            if key not in entities:
                entities[key] = AgingEntry(
                    rfc=key, nombre=inv.nombre_receptor
                )
            entry = entities[key]
            saldo = inv.total - inv.monto_cobrado
            dias = _days_since(inv.fecha_vencimiento, today)
            bucket = _bucket_for_days(dias)

            if bucket == "0-30":
                entry.bucket_0_30 += saldo
            elif bucket == "31-60":
                entry.bucket_31_60 += saldo
            elif bucket == "61-90":
                entry.bucket_61_90 += saldo
            else:
                entry.bucket_90_plus += saldo
            entry.total += saldo

        return sorted(entities.values(), key=lambda e: e.total, reverse=True)

    # --- internal helpers ---------------------------------------------------

    def _build_report(
        self,
        tipo: str,
        invoices: List[APInvoice],
        today: Optional[date],
        field: str,
    ) -> AgingReport:
        today = today or date.today()
        bucket_data: Dict[str, Dict] = {
            "0-30": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "31-60": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "61-90": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "90+": {"count": 0, "monto": 0.0, "dias_sum": 0},
        }

        for inv in invoices:
            dias = _days_since(getattr(inv, field, inv.fecha_vencimiento), today)
            bucket = _bucket_for_days(dias)
            saldo = inv.total - inv.monto_pagado
            bucket_data[bucket]["count"] += 1
            bucket_data[bucket]["monto"] += saldo
            bucket_data[bucket]["dias_sum"] += max(0, dias)

        buckets = []
        total_facturas = 0
        total_monto = 0.0
        for name in ("0-30", "31-60", "61-90", "90+"):
            d = bucket_data[name]
            count = d["count"]
            monto = round(d["monto"], 2)
            avg_dias = round(d["dias_sum"] / count, 1) if count > 0 else 0.0
            buckets.append(AgingBucketData(
                bucket=name, count=count, monto=monto, dias_promedio=avg_dias
            ))
            total_facturas += count
            total_monto += monto

        return AgingReport(
            tipo=tipo,
            buckets=buckets,
            total_facturas=total_facturas,
            total_monto=round(total_monto, 2),
        )

    def _build_report_ar(
        self,
        tipo: str,
        invoices: List[ARInvoice],
        today: Optional[date],
    ) -> AgingReport:
        today = today or date.today()
        bucket_data: Dict[str, Dict] = {
            "0-30": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "31-60": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "61-90": {"count": 0, "monto": 0.0, "dias_sum": 0},
            "90+": {"count": 0, "monto": 0.0, "dias_sum": 0},
        }

        for inv in invoices:
            dias = _days_since(inv.fecha_vencimiento, today)
            bucket = _bucket_for_days(dias)
            saldo = inv.total - inv.monto_cobrado
            bucket_data[bucket]["count"] += 1
            bucket_data[bucket]["monto"] += saldo
            bucket_data[bucket]["dias_sum"] += max(0, dias)

        buckets = []
        total_facturas = 0
        total_monto = 0.0
        for name in ("0-30", "31-60", "61-90", "90+"):
            d = bucket_data[name]
            count = d["count"]
            monto = round(d["monto"], 2)
            avg_dias = round(d["dias_sum"] / count, 1) if count > 0 else 0.0
            buckets.append(AgingBucketData(
                bucket=name, count=count, monto=monto, dias_promedio=avg_dias
            ))
            total_facturas += count
            total_monto += monto

        return AgingReport(
            tipo=tipo,
            buckets=buckets,
            total_facturas=total_facturas,
            total_monto=round(total_monto, 2),
        )
