# -*- coding: utf-8 -*-
"""
analytics.py — Dashboard Analytics API endpoint (cross-module aggregation).

Provides GET /api/v1/dashboard/analytics that aggregates data from:
  - CFDI processing stats (invoices, categories, amounts)
  - Payroll summaries (calculations performed)
  - Payment collections (aging, outstanding, collection events)
  - Accounting reconciliation status (asientos, balanzas)
  - Report generation metrics (audit log, notifications, reviews)

Returns JSON with:
  - Period-over-period comparison (current vs previous month)
  - Trending data (monthly series)
  - Actionable insights for a despacho contable
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Response models (Pydantic)
# ---------------------------------------------------------------------------

class ModuleMetrics(BaseModel):
    """Metrics for a single module (e.g. CFDI, payroll, collections)."""
    count: int = 0
    total_amount: float = 0.0
    valid_count: int = 0
    invalid_count: int = 0


class PeriodComparison(BaseModel):
    """Period-over-period comparison."""
    current_period: str
    previous_period: str
    current: Dict[str, Any] = {}
    previous: Dict[str, Any] = {}
    delta_pct: Dict[str, float] = {}


class TrendPoint(BaseModel):
    """A single point in a time series."""
    period: str
    count: int = 0
    amount: float = 0.0


class Insight(BaseModel):
    """An actionable insight for the despacho."""
    module: str
    severity: str  # info, warning, critical
    message: str


class AnalyticsResponse(BaseModel):
    """Full analytics dashboard response."""
    generated_at: str
    tenant_id: Optional[int] = None
    period_current: str = ""
    period_previous: str = ""
    cfdi: Dict[str, Any] = {}
    payroll: Dict[str, Any] = {}
    collections: Dict[str, Any] = {}
    reconciliation: Dict[str, Any] = {}
    reports: Dict[str, Any] = {}
    kpis: Dict[str, Any] = {}
    trends: List[Dict[str, Any]] = []
    comparison: Dict[str, Any] = {}
    insights: List[Dict[str, str]] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(v: Any) -> float:
    """Convert to float tolerantly (None/text → 0.0)."""
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _periodo(fecha: Any) -> str:
    """Extract 'YYYY-MM' from a date string."""
    return str(fecha or "")[:7] if fecha else "sin-fecha"


def _month_range(year: int, month: int):
    """Return (start_date, end_date) strings for a month."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    return start, end


def _prev_month(year: int, month: int):
    """Return (year, month) for the previous month."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


# ---------------------------------------------------------------------------
# Core aggregation functions (pure — no side effects, easy to test)
# ---------------------------------------------------------------------------

def _cfdi_metrics(invoices: List[Dict[str, Any]],
                  fecha_desde: str = "", fecha_hasta: str = "") -> Dict[str, Any]:
    """Aggregate CFDI processing stats for a filtered set of invoices."""
    rows = invoices
    if fecha_desde:
        rows = [r for r in rows if (r.get("fecha") or "") >= fecha_desde]
    if fecha_hasta:
        rows = [r for r in rows if (r.get("fecha") or "") < fecha_hasta]

    total = len(rows)
    validas = sum(1 for r in rows if r.get("valido") in (1, True, "1", "SI"))
    invalidas = total - validas
    monto_total = sum(_dec(r.get("total")) for r in rows)
    iva_total = sum(_dec(r.get("iva")) for r in rows)
    subtotal_total = sum(_dec(r.get("subtotal")) for r in rows)

    # By category
    por_categoria = defaultdict(lambda: {"count": 0, "monto": 0.0})
    for r in rows:
        cat = r.get("categoria", "desconocido")
        por_categoria[cat]["count"] += 1
        por_categoria[cat]["monto"] += _dec(r.get("total"))

    # By month
    por_mes = defaultdict(lambda: {"count": 0, "monto": 0.0})
    for r in rows:
        mes = _periodo(r.get("fecha"))
        por_mes[mes]["count"] += 1
        por_mes[mes]["monto"] += _dec(r.get("total"))

    # Top emisores
    por_emisor = defaultdict(lambda: {"count": 0, "monto": 0.0})
    for r in rows:
        emisor = r.get("emisor_rfc") or r.get("emisor_nombre") or "desconocido"
        por_emisor[emisor]["count"] += 1
        por_emisor[emisor]["monto"] += _dec(r.get("total"))

    # Anomalies count
    con_anomalias = sum(1 for r in rows
                        if r.get("requires_human_review") in (1, True, "1", "SI"))

    return {
        "total_facturas": total,
        "validas": validas,
        "invalidas": invalidas,
        "tasa_validez": round(validas / total, 4) if total else 0.0,
        "monto_total": round(monto_total, 2),
        "iva_total": round(iva_total, 2),
        "subtotal_total": round(subtotal_total, 2),
        "monto_promedio": round(monto_total / total, 2) if total else 0.0,
        "por_categoria": {k: {"count": v["count"], "monto": round(v["monto"], 2)}
                          for k, v in sorted(por_categoria.items(),
                                             key=lambda x: -x[1]["count"])},
        "por_mes": {k: {"count": v["count"], "monto": round(v["monto"], 2)}
                    for k, v in sorted(por_mes.items())},
        "top_emisores": [{"rfc": k, "count": v["count"],
                          "monto": round(v["monto"], 2)}
                         for k, v in sorted(por_emisor.items(),
                                            key=lambda x: -x[1]["monto"])[:10]],
        "requieren_revision": con_anomalias,
    }


def _collections_metrics(db: Any, tenant_id: Optional[int],
                         today_str: str = "") -> Dict[str, Any]:
    """Aggregate payment collections data."""
    outstanding = db.list_outstanding_invoices(tenant_id=tenant_id)
    events = db.list_collection_events(tenant_id=tenant_id)

    total_outstanding = len(outstanding)
    monto_pendiente = sum(_dec(r.get("monto")) for r in outstanding)

    # Aging buckets
    from b2b_ai.services.collections import age_bucket, days_overdue
    buckets = {"0-30": {"count": 0, "monto": 0.0},
               "31-60": {"count": 0, "monto": 0.0},
               "61-90": {"count": 0, "monto": 0.0},
               "90+": {"count": 0, "monto": 0.0}}

    for r in outstanding:
        dias = days_overdue(r.get("fecha_vencimiento"))
        b = age_bucket(dias)
        buckets[b]["count"] += 1
        buckets[b]["monto"] += _dec(r.get("monto"))

    # Collection events by type
    eventos_por_tipo = defaultdict(int)
    for e in events:
        eventos_por_tipo[e.get("tipo_recordatorio", "otro")] += 1

    return {
        "facturas_pendientes": total_outstanding,
        "monto_pendiente_total": round(monto_pendiente, 2),
        "cartera_por_antiguedad": {
            k: {"count": v["count"], "monto": round(v["monto"], 2)}
            for k, v in buckets.items()
        },
        "total_intentos_cobranza": len(events),
        "eventos_por_tipo": dict(eventos_por_tipo),
    }


def _reconciliation_metrics(db: Any, tenant_id: Optional[int]) -> Dict[str, Any]:
    """Aggregate accounting/reconciliation data."""
    asientos = db.list_asientos_contables(tenant_id=tenant_id)
    cuentas = db.list_cuentas_contables(tenant_id=tenant_id)
    balanzas = db.list_balanzas_mensuales(tenant_id=tenant_id)

    total_asientos = len(asientos)
    monto_asientos = sum(_dec(a.get("monto")) for a in asientos)

    # Periodos con balanza
    periodos_balanza = set()
    for b in balanzas:
        p = b.get("periodo", "")
        if p:
            periodos_balanza.add(p)

    # Asientos por mes
    asientos_por_mes = defaultdict(int)
    for a in asientos:
        mes = _periodo(a.get("fecha"))
        asientos_por_mes[mes] += 1

    return {
        "total_asientos": total_asientos,
        "monto_total_asientos": round(monto_asientos, 2),
        "total_cuentas_catalogo": len(cuentas),
        "periodos_con_balanza": sorted(periodos_balanza),
        "asientos_por_mes": {k: v for k, v in sorted(asientos_por_mes.items())},
    }


def _payroll_metrics(db: Any, tenant_id: Optional[int]) -> Dict[str, Any]:
    """Aggregate payroll-related metrics.

    Payroll data in this project is calculated on-the-fly (no dedicated
    payroll table). We track payroll activity via audit_log entries.
    """
    payroll_calls = db.count_audit(tool_name="calcular_nomina")
    # Reviews related to payroll
    reviews = db.list_reviews(tenant_id=tenant_id)
    payroll_reviews = [r for r in reviews
                       if (r.get("reason") or "").lower().find("nómina") >= 0
                       or (r.get("reason") or "").lower().find("nomina") >= 0]

    return {
        "calculos_realizados": payroll_calls,
        "revisiones_pendientes": len([r for r in payroll_reviews
                                      if r.get("status") == "pending"]),
        "revisiones_resueltas": len([r for r in payroll_reviews
                                     if r.get("status") == "resolved"]),
    }


def _report_metrics(db: Any, tenant_id: Optional[int]) -> Dict[str, Any]:
    """Aggregate report generation and audit metrics."""
    total_audit = db.count_audit()
    notifications = db.list_notifications(tenant_id=tenant_id)
    reviews = db.list_reviews(tenant_id=tenant_id)
    pending_reviews = db.count_pending_reviews(tenant_id=tenant_id)

    # Notifications by channel
    notif_por_canal = defaultdict(int)
    notif_por_estado = defaultdict(int)
    for n in notifications:
        notif_por_canal[n.get("channel", "unknown")] += 1
        notif_por_estado[n.get("status", "unknown")] += 1

    # Reviews by status
    reviews_por_status = defaultdict(int)
    for r in reviews:
        reviews_por_status[r.get("status", "unknown")] += 1

    return {
        "total_audit_log": total_audit,
        "total_notificaciones": len(notifications),
        "notificaciones_por_canal": dict(notif_por_canal),
        "notificaciones_por_estado": dict(notif_por_estado),
        "total_revisiones": len(reviews),
        "revisiones_pendientes": pending_reviews,
        "revisiones_por_estado": dict(reviews_por_status),
    }


def _compute_kpis(cfdi: Dict, collections: Dict, reconciliation: Dict,
                  reports: Dict) -> Dict[str, Any]:
    """Compute high-level KPIs from module data."""
    total_facturas = cfdi.get("total_facturas", 0)
    validas = cfdi.get("validas", 0)
    pendientes = collections.get("facturas_pendientes", 0)
    asientos = reconciliation.get("total_asientos", 0)

    tasa_automatizacion = 0.0
    if total_facturas > 0:
        auto = total_facturas - cfdi.get("requieren_revision", 0)
        tasa_automatizacion = round(auto / total_facturas * 100, 1)

    return {
        "total_facturas_procesadas": total_facturas,
        "monto_total_procesado": cfdi.get("monto_total", 0.0),
        "tasa_validez_pct": round(cfdi.get("tasa_validez", 0) * 100, 1),
        "tasa_automatizacion_pct": tasa_automatizacion,
        "cartera_pendiente": pendientes,
        "monto_cartera_pendiente": collections.get("monto_pendiente_total", 0.0),
        "asientos_contables": asientos,
        "revisiones_pendientes": reports.get("revisiones_pendientes", 0),
        "audit_log_entries": reports.get("total_audit_log", 0),
    }


def _compute_comparison(current: Dict, previous: Dict) -> Dict[str, Any]:
    """Compute period-over-period delta percentages."""
    delta = {}
    for key in ("total_facturas", "monto_total", "validas", "invalidas"):
        cur = current.get(key, 0)
        prev = previous.get(key, 0)
        if prev and prev != 0:
            delta[key] = round((cur - prev) / abs(prev) * 100, 1)
        elif cur and cur != 0:
            delta[key] = 100.0 if prev == 0 else 0.0
        else:
            delta[key] = 0.0
    return delta


def _generate_insights(cfdi: Dict, collections: Dict, reconciliation: Dict,
                       reports: Dict) -> List[Dict[str, str]]:
    """Generate actionable insights for the despacho contable."""
    insights = []

    # CFDI insights
    if cfdi.get("total_facturas", 0) == 0:
        insights.append({
            "module": "cfdi",
            "severity": "info",
            "message": "No hay facturas procesadas en este periodo. "
                       "Asegúrate de que el pipeline está activo.",
        })
    else:
        tasa = cfdi.get("tasa_validez", 0)
        if tasa < 0.8:
            insights.append({
                "module": "cfdi",
                "severity": "warning",
                "message": f"Tasa de validez baja: {tasa * 100:.1f}%. "
                           "Revisa las facturas inválidas pendientes.",
            })
        rev = cfdi.get("requieren_revision", 0)
        if rev > 0:
            insights.append({
                "module": "cfdi",
                "severity": "warning",
                "message": f"{rev} factura(s) requieren revisión humana.",
            })

    # Collections insights
    monto_pend = collections.get("monto_pendiente_total", 0)
    if monto_pend > 0:
        aging = collections.get("cartera_por_antiguedad", {})
        criticas = aging.get("90+", {}).get("count", 0)
        if criticas > 0:
            insights.append({
                "module": "collections",
                "severity": "critical",
                "message": f"{criticas} factura(s) con 90+ días de atraso. "
                           "Se recomienda escalamiento inmediato.",
            })
        alto = aging.get("61-90", {}).get("count", 0)
        if alto > 0:
            insights.append({
                "module": "collections",
                "severity": "warning",
                "message": f"{alto} factura(s) con 61-90 días de atraso. "
                           "Enviar segundo recordatorio.",
            })

    # Reconciliation insights
    asientos = reconciliation.get("total_asientos", 0)
    cuentas = reconciliation.get("total_cuentas_catalogo", 0)
    if asientos > 0 and cuentas == 0:
        insights.append({
            "module": "reconciliation",
            "severity": "warning",
            "message": "Hay asientos contables pero no hay catálogo de cuentas. "
                       "Carga el catálogo SAT para contabilidad electrónica.",
        })

    # Report / review insights
    pending = reports.get("revisiones_pendientes", 0)
    if pending > 0:
        insights.append({
            "module": "reports",
            "severity": "warning",
            "message": f"{pending} revisión(es) pendiente(s) en la cola "
                       "de human-in-the-loop.",
        })

    if not insights:
        insights.append({
            "module": "general",
            "severity": "info",
            "message": "Todo está operando dentro de parámetros normales.",
        })

    return insights


def _build_trends(invoices: List[Dict[str, Any]],
                  collections_events: List[Dict[str, Any]],
                  asientos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build monthly trend data across all modules."""
    months = defaultdict(lambda: {
        "cfdi_count": 0, "cfdi_monto": 0.0,
        "collection_events": 0, "asientos": 0,
    })

    for inv in invoices:
        m = _periodo(inv.get("fecha"))
        if m == "sin-fecha":
            continue
        months[m]["cfdi_count"] += 1
        months[m]["cfdi_monto"] += _dec(inv.get("total"))

    for e in collections_events:
        m = _periodo(e.get("timestamp"))
        if m != "sin-fecha":
            months[m]["collection_events"] += 1

    for a in asientos:
        m = _periodo(a.get("fecha"))
        if m != "sin-fecha":
            months[m]["asientos"] += 1

    result = []
    for m in sorted(months.keys()):
        d = months[m]
        result.append({
            "period": m,
            "cfdi_count": d["cfdi_count"],
            "cfdi_monto": round(d["cfdi_monto"], 2),
            "collection_events": d["collection_events"],
            "asientos": d["asientos"],
        })
    return result


# ---------------------------------------------------------------------------
# Router factory (follows build_*_router pattern)
# ---------------------------------------------------------------------------

def build_analytics_router(db: Any, require_api_key: Optional[Any] = None) -> APIRouter:
    """Build the analytics dashboard router.

    Args:
        db: Database instance.
        require_api_key: FastAPI dependency for API key auth (optional).
    """
    auth_dep = require_api_key or (lambda: None)
    router = APIRouter(tags=["analytics"])

    @router.get("/dashboard/analytics",
                summary="Analytics dashboard: cross-module aggregation "
                        "with period comparison and insights.",
                response_model=AnalyticsResponse)
    def analytics(
        auth_info: dict = Depends(auth_dep),
        year: Optional[int] = Query(default=None,
                                     description="Year (YYYY). Default: current."),
        month: Optional[int] = Query(default=None, ge=1, le=12,
                                      description="Month (1-12). Default: current."),
        tenant_id_q: Optional[int] = Query(default=None, alias="tenant_id",
                                             description="Tenant override (service key only)."),
    ):
        # Determine current period
        now = datetime.utcnow()
        cur_year = year or now.year
        cur_month = month or now.month
        cur_start, cur_end = _month_range(cur_year, cur_month)
        period_current = f"{cur_year:04d}-{cur_month:02d}"

        # Previous period
        prev_year, prev_month = _prev_month(cur_year, cur_month)
        prev_start, prev_end = _month_range(prev_year, prev_month)
        period_previous = f"{prev_year:04d}-{prev_month:02d}"

        # Resolve tenant
        tenant = (auth_info or {}).get("tenant_id") or tenant_id_q

        # Fetch all invoices (we filter by period in each metric)
        all_invoices = db.list_invoices(tenant_id=tenant)
        # Fetch audit/notification data
        asientos = db.list_asientos_contables(tenant_id=tenant)
        col_events = db.list_collection_events(tenant_id=tenant)

        # --- CFDI metrics ---
        cfdi_current = _cfdi_metrics(all_invoices, cur_start, cur_end)
        cfdi_previous = _cfdi_metrics(all_invoices, prev_start, prev_end)

        # --- Collections ---
        collections_data = _collections_metrics(db, tenant)

        # --- Reconciliation ---
        reconciliation_data = _reconciliation_metrics(db, tenant)

        # --- Payroll ---
        payroll_data = _payroll_metrics(db, tenant)

        # --- Reports ---
        reports_data = _report_metrics(db, tenant)

        # --- KPIs ---
        kpis = _compute_kpis(cfdi_current, collections_data,
                             reconciliation_data, reports_data)

        # --- Period comparison ---
        comparison = {
            "cfdi": {
                "current": cfdi_current,
                "previous": cfdi_previous,
                "delta_pct": _compute_comparison(cfdi_current, cfdi_previous),
            }
        }

        # --- Trends ---
        trends = _build_trends(all_invoices, col_events, asientos)

        # --- Insights ---
        insights = _generate_insights(cfdi_current, collections_data,
                                      reconciliation_data, reports_data)

        return AnalyticsResponse(
            generated_at=datetime.utcnow().isoformat(timespec="seconds"),
            tenant_id=tenant,
            period_current=period_current,
            period_previous=period_previous,
            cfdi=cfdi_current,
            payroll=payroll_data,
            collections=collections_data,
            reconciliation=reconciliation_data,
            reports=reports_data,
            kpis=kpis,
            trends=trends,
            comparison=comparison,
            insights=insights,
        )

    return router
