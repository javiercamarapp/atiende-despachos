# -*- coding: utf-8 -*-
"""
service.py — Business logic for the Admin Dashboard.

Provides the DashboardService class that queries the database and
computes metrics, aggregations, and reports. All methods are synchronous
SQLite reads — no async needed for the current DB layer.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.features.dashboard.models import (
    ClientSummary,
    DailyMetric,
    DashboardOverview,
    RevenueReport,
    SystemHealth,
    UsageMetrics,
)


class DashboardService:
    """Service layer for admin dashboard queries.

    Accepts a Database instance and provides methods that return
    Pydantic-validated dashboard models.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Dashboard Overview
    # ------------------------------------------------------------------

    def get_dashboard_overview(self) -> DashboardOverview:
        """Top-level admin overview: clients, revenue, CFDI count."""
        tenants = self._db.list_tenants()
        all_usage = self._db.get_all_usage()
        usage_map = {u["tenant_id"]: u for u in all_usage}

        # Active clients: tenants with invoices in the last 30 days
        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        total_clients = len(tenants)
        active_clients = 0
        cfdi_count_month = 0
        total_invoices_all = 0

        for tenant in tenants:
            tid = tenant["id"]
            inv_count = self._db.count_invoices(tenant_id=tid)
            total_invoices_all += inv_count
            # Check for invoices in the last 30 days
            recent = self._db.list_invoices(tenant_id=tid, fecha_desde=thirty_days_ago)
            if recent:
                active_clients += 1
                cfdi_count_month += len(recent)

        # Revenue from subscriptions
        revenue_mrr = 0.0
        total_revenue = 0.0
        try:
            subs = self._db.list_billing_subscriptions()
            for sub in subs:
                if sub.get("status") == "active":
                    revenue_mrr += _plan_to_mrr(sub.get("plan", ""))
                    total_revenue += revenue_mrr  # approximation
        except Exception:  # noqa: BLE001
            pass

        # System status
        system_status = "healthy"
        try:
            audit_total = self._db.count_audit()
            audit_errors = self._db.count_audit(tool_name="error")
            if audit_total > 0 and audit_errors / max(audit_total, 1) > 0.1:
                system_status = "degraded"
        except Exception:  # noqa: BLE001
            pass

        return DashboardOverview(
            total_clients=total_clients,
            active_clients=active_clients,
            revenue_mrr=round(revenue_mrr, 2),
            cfdi_count_month=cfdi_count_month,
            total_invoices=total_invoices_all,
            total_revenue=round(total_revenue, 2),
            system_status=system_status,
            last_updated=now.isoformat(timespec="seconds"),
        )

    # ------------------------------------------------------------------
    # Client List
    # ------------------------------------------------------------------

    def get_client_list(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
        search: Optional[str] = None,
        active_only: bool = False,
    ) -> Dict[str, Any]:
        """Paginated, sortable, filterable list of clients.

        Returns: {clients: [...], total: N, page: P, page_size: S, pages: T}
        """
        tenants = self._db.list_tenants()
        all_usage = self._db.get_all_usage()
        usage_map = {u["tenant_id"]: u for u in all_usage}

        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        summaries: List[ClientSummary] = []
        for tenant in tenants:
            tid = tenant["id"]
            inv_count = self._db.count_invoices(tenant_id=tid)
            invoices = self._db.list_invoices(tenant_id=tid)
            monto = sum(_safe_float(i.get("total")) for i in invoices)
            usage = usage_map.get(tid, {})
            api_calls = usage.get("api_calls", 0)

            # Last activity: most recent invoice processed date
            last_activity = None
            for inv in invoices[:1]:
                last_activity = inv.get("procesado_en")

            is_active = any(
                (i.get("fecha") or "") >= thirty_days_ago for i in invoices
            )

            summaries.append(ClientSummary(
                id=tid,
                name=tenant.get("name", ""),
                rfc=tenant.get("rfc", ""),
                active=is_active,
                invoice_count=inv_count,
                monto_total=round(monto, 2),
                api_calls=api_calls,
                created_at=tenant.get("created_at"),
                last_activity=last_activity,
            ))

        # Filter
        if active_only:
            summaries = [s for s in summaries if s.active]
        if search:
            q = search.lower()
            summaries = [
                s for s in summaries
                if q in s.name.lower() or q in s.rfc.lower()
            ]

        # Sort
        reverse = sort_order.lower() == "desc"
        key_map = {
            "name": lambda s: s.name.lower(),
            "id": lambda s: s.id,
            "invoice_count": lambda s: s.invoice_count,
            "monto_total": lambda s: s.monto_total,
            "api_calls": lambda s: s.api_calls,
            "created_at": lambda s: s.created_at or "",
            "last_activity": lambda s: s.last_activity or "",
        }
        sort_fn = key_map.get(sort_by, key_map["name"])
        summaries.sort(key=sort_fn, reverse=reverse)

        # Paginate
        total = len(summaries)
        pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = summaries[start:end]

        return {
            "clients": [s.model_dump() for s in page_items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_client_detail(self, client_id: int) -> Optional[Dict[str, Any]]:
        """Detailed view of a single client."""
        tenant = self._db.get_tenant_by_id(client_id)
        if tenant is None:
            return None

        invoices = self._db.list_invoices(tenant_id=client_id)
        usage = self._db.get_usage(client_id)
        monto = sum(_safe_float(i.get("total")) for i in invoices)

        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        is_active = any(
            (i.get("fecha") or "") >= thirty_days_ago for i in invoices
        )

        # Category breakdown
        by_category = defaultdict(int)
        for inv in invoices:
            cat = inv.get("categoria", "other")
            by_category[cat] += 1

        return {
            "id": client_id,
            "name": tenant.get("name", ""),
            "rfc": tenant.get("rfc", ""),
            "active": is_active,
            "invoice_count": len(invoices),
            "monto_total": round(monto, 2),
            "api_calls": usage.get("api_calls", 0),
            "invoices_processed": usage.get("invoices_processed", 0),
            "created_at": tenant.get("created_at"),
            "category_breakdown": dict(by_category),
            "recent_invoices": [
                {
                    "id": inv.get("id"),
                    "folio_fiscal": inv.get("folio_fiscal"),
                    "fecha": inv.get("fecha"),
                    "total": _safe_float(inv.get("total")),
                    "categoria": inv.get("categoria"),
                    "status": inv.get("status"),
                }
                for inv in invoices[:10]
            ],
        }

    # ------------------------------------------------------------------
    # System Health
    # ------------------------------------------------------------------

    def get_system_health(self) -> SystemHealth:
        """System health check: uptime, DB size, queue depth, error rate."""
        now = datetime.utcnow()
        tenants = self._db.list_tenants()
        total_tenants = len(tenants)

        # Total invoices
        total_invoices = self._db.count_invoices()

        # DB size (approximate from file)
        db_size_mb = 0.0
        db_path = getattr(self._db, "path", "")
        if db_path and os.path.isfile(db_path):
            try:
                db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
            except OSError:
                pass

        # Error rate (last 24h): count audit errors vs total
        error_rate = 0.0
        queue_depth = 0
        try:
            audit_total = self._db.count_audit()
            audit_errors = self._db.count_audit(tool_name="error")
            if audit_total > 0:
                error_rate = round(audit_errors / audit_total, 4)
        except Exception:  # noqa: BLE001
            pass

        # API uptime: estimate from error rate (inverse)
        api_uptime = round(max(0, 1.0 - error_rate) * 100, 2)

        # Status determination
        if error_rate > 0.1:
            status = "degraded"
        elif error_rate > 0.05:
            status = "warning"
        else:
            status = "healthy"

        return SystemHealth(
            status=status,
            api_uptime_pct=api_uptime,
            total_invoices=total_invoices,
            total_tenants=total_tenants,
            db_size_mb=db_size_mb,
            queue_depth=queue_depth,
            error_rate_24h=error_rate,
            last_check=now.isoformat(timespec="seconds"),
            details={
                "audit_total": audit_total if 'audit_total' in dir() else 0,
                "db_path": db_path,
            },
        )

    # ------------------------------------------------------------------
    # Usage Metrics
    # ------------------------------------------------------------------

    def get_usage_metrics(self, days: int = 30) -> UsageMetrics:
        """Usage metrics for the last N days."""
        now = datetime.utcnow()
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        all_usage = self._db.get_all_usage()
        total_api_calls = sum(u.get("api_calls", 0) for u in all_usage)
        total_invoices = sum(u.get("invoices_processed", 0) for u in all_usage)

        # Build daily CFDI count
        all_invoices = self._db.list_invoices()
        daily: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "total": 0.0})
        processing_times = []

        for inv in all_invoices:
            fecha = (inv.get("fecha") or "")[:10]
            if fecha and fecha >= start_date:
                daily[fecha]["count"] += 1
                daily[fecha]["total"] += _safe_float(inv.get("total"))

            # Processing time
            created = inv.get("created_at")
            processed = inv.get("procesado_en")
            if created and processed and str(created) != str(processed):
                try:
                    t0 = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(str(processed).replace("Z", "+00:00"))
                    processing_times.append(max(0.0, (t1 - t0).total_seconds()))
                except (ValueError, TypeError):
                    pass

        # Fill in missing days with zeros
        cfdi_daily = []
        for i in range(days):
            d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            day_data = daily.get(d, {"count": 0, "total": 0.0})
            cfdi_daily.append(DailyMetric(
                date=d,
                count=int(day_data["count"]),
                total_amount=round(day_data["total"], 2),
            ))

        avg_proc_time = (
            round(sum(processing_times) / len(processing_times), 2)
            if processing_times else 0.0
        )

        # Error rate from audit log
        error_rate = 0.0
        llm_calls = 0
        try:
            audit_errors = self._db.count_audit(tool_name="error")
            audit_total = self._db.count_audit()
            if audit_total > 0:
                error_rate = round(audit_errors / audit_total, 4)
            # Count LLM calls from audit
            llm_calls = self._db.count_audit(tool_name="llm")
        except Exception:  # noqa: BLE001
            pass

        return UsageMetrics(
            total_api_calls=total_api_calls,
            total_invoices_processed=total_invoices,
            cfdi_daily=cfdi_daily,
            avg_processing_time_sec=avg_proc_time,
            llm_calls=llm_calls,
            error_rate=error_rate,
            period_start=start_date,
            period_end=end_date,
        )

    # ------------------------------------------------------------------
    # Revenue Report
    # ------------------------------------------------------------------

    def get_revenue_report(self) -> RevenueReport:
        """Revenue report: MRR, ARR, churn, per-client average."""
        now = datetime.utcnow()
        start_of_month = now.replace(day=1).strftime("%Y-%m-%d")
        end_of_month = now.strftime("%Y-%m-%d")

        tenants = self._db.list_tenants()
        active_subs = 0
        revenue_mrr = 0.0
        plan_breakdown: Dict[str, int] = defaultdict(int)

        try:
            subs = self._db.list_billing_subscriptions()
            for sub in subs:
                if sub.get("status") == "active":
                    active_subs += 1
                    plan = sub.get("plan", "unknown")
                    plan_breakdown[plan] += 1
                    revenue_mrr += _plan_to_mrr(plan)
        except Exception:  # noqa: BLE001
            pass

        arr = revenue_mrr * 12
        total_clients = len(tenants)
        avg_rev = round(revenue_mrr / max(total_clients, 1), 2)

        # Churn rate approximation: inactive tenants / total
        # (tenants with no invoices in last 30 days)
        thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        churned = 0
        for tenant in tenants:
            recent = self._db.list_invoices(tenant_id=tenant["id"], fecha_desde=thirty_days_ago)
            if not recent:
                churned += 1
        churn_rate = round(churned / max(total_clients, 1), 4)

        return RevenueReport(
            mrr=round(revenue_mrr, 2),
            arr=round(arr, 2),
            total_revenue=round(revenue_mrr * 12, 2),  # approximation
            active_subscriptions=active_subs,
            churn_rate=churn_rate,
            avg_revenue_per_client=avg_rev,
            plan_breakdown=dict(plan_breakdown),
            period_start=start_of_month,
            period_end=end_of_month,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _safe_float(v: Any) -> float:
    """Convert to float tolerantly."""
    if v is None or v == "":
        return 0.0
    # Booleans must be handled before str() conversion because
    # str(True) == "True" which float() cannot parse.
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _plan_to_mrr(plan: str) -> float:
    """Map a plan name to approximate monthly revenue."""
    plan_prices = {
        "starter": 2999.0,
        "professional": 7999.0,
        "enterprise": 19999.0,
        "basic": 1999.0,
        "pro": 5999.0,
        "enterprise_plus": 29999.0,
    }
    return plan_prices.get(plan.lower().replace("-", "_").replace(" ", "_"), 4999.0)
