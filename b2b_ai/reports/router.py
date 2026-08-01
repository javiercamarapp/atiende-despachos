# -*- coding: utf-8 -*-
"""
router.py — Endpoints /api/v1/reports/* de generación y descarga de PDF.

Endpoints:
    GET  /api/v1/reports/{type}/{period}   genera un reporte (tipo en
                                           invoices|monthly|reconciliation|
                                           anomaly|tax) para el periodo
                                           'YYYY-MM' y devuelve el PDF.
                                           Cabecera X-Report-Id con el id
                                           para descargarlo después.
    GET  /api/v1/reports/{id}/download     descarga un reporte ya generado.
    POST /api/v1/reports/custom            genera un reporte personalizado a
                                           partir de un JSON {data, template}.

Aislamiento multi-tenant: el tenant efectivo se resuelve de la API key
(auth_info.tenant_id) o, si la key es global (sin tenant), del parámetro
tenant_id. Los reportes monthly/tax/anomaly/reconciliation tiran de la DB
filtrada por ese tenant.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from b2b_ai.reports.pdf_generator import PDFGenerator, _periodo, mxn, fecha_mx
from b2b_ai.services import anomaly as anomaly_svc
from b2b_ai.services.reconcile import build_reconciliation_report

_REPORT_TYPES = {"invoices", "monthly", "reconciliation", "anomaly", "tax"}

# Registro en memoria de reportes generados (id -> metadatos + bytes). Thread-
# safe. Suficiente para el MVP single-node; en multi-replica convendría
# persistirlo (DB / Redis / S3).
_REGISTRY: Dict[str, Dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


class CustomReportRequest(BaseModel):
    """Cuerpo de POST /api/v1/reports/custom."""
    data: Dict[str, Any] = {}
    template: str = "custom_report"
    tenant_id: Optional[int] = None
    as_html: bool = False


def _register(report_type: str, tenant_id: Optional[int], period: str,
              filename: str, pdf_bytes: bytes) -> str:
    rid = uuid.uuid4().hex[:12]
    entry = {
        "id": rid,
        "type": report_type,
        "tenant_id": tenant_id,
        "period": period,
        "filename": filename,
        "bytes": pdf_bytes,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    with _REGISTRY_LOCK:
        _REGISTRY[rid] = entry
    return rid


def _pdf_response(pdf_bytes: bytes, filename: str, rid: str = "") -> Response:
    """Devuelve el PDF como descarga con cabecera X-Report-Id."""
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Id": rid,
            "Cache-Control": "no-store",
        },
    )


def _tenant_from_request(auth_info: Dict[str, Any],
                         query_tenant: Optional[int],
                         fallback_tenant: Optional[int]) -> Optional[int]:
    """Tenant efectivo: API key > query > default del router."""
    return (auth_info or {}).get("tenant_id") or query_tenant or fallback_tenant


def _derive_reconciliation(rows, period):
    """Conciliación derivada de las facturas del periodo (banco = espejo)."""
    inv_side = [{
        "folio_fiscal": i.get("folio_fiscal"),
        "fecha": i.get("fecha"),
        "total": i.get("total"),
        "emisor": i.get("emisor_rfc"),
    } for i in rows if i.get("folio_fiscal")]
    bank = [{
        "fecha": (i.get("fecha") or "")[:10],
        "monto": abs(float(str(i.get("total") or 0).replace(",", "")) or 0),
        "descripcion": "Transferencia",
        "ref": i.get("folio_fiscal") or "",
    } for i in rows[:200]]
    rep = build_reconciliation_report(inv_side, bank, period=period)
    rep["es_muestra"] = True
    return rep


def _detect_anomalies(rows):
    out = []
    for inv in rows:
        hist = [x for x in rows if x is not inv]
        for a in anomaly_svc.detect_anomalies(inv, hist):
            a = dict(a)
            a.update({"invoice_id": inv.get("id"),
                      "emisor_rfc": inv.get("emisor_rfc", ""),
                      "fecha": inv.get("fecha", ""),
                      "folio_fiscal": inv.get("folio_fiscal"),
                      "monto": abs(float(str(inv.get("total") or 0)
                                         .replace(",", "")) or 0)})
            out.append(a)
    return out


def build_reports_router(db: Any, require_api_key: Optional[Any] = None,
                         tenant_id: Optional[int] = None) -> APIRouter:
    """Construye el APIRouter de reportes para una DB inyectada.

    `require_api_key` es la dependency FastAPI de auth (se inyecta desde
    app.py para usar la misma protección que el resto de /api/v1).
    """
    auth_dep = require_api_key or (lambda: None)
    router = APIRouter(prefix="/reports", tags=["reports"])
    gen = PDFGenerator(db=db)

    @router.get("/{report_type}/{period}",
                summary="Genera un reporte PDF del periodo (tipo en "
                        "invoices|monthly|reconciliation|anomaly|tax).")
    def get_report(report_type: str, period: str,
                   tenant_id_q: Optional[int] = Query(None, alias="tenant_id"),
                   auth_info: dict = Depends(auth_dep)):
        """Genera y devuelve el PDF de un reporte. Cabecera X-Report-Id."""
        if report_type not in _REPORT_TYPES:
            raise HTTPException(400, "Tipo de reporte inválido. Válidos: "
                                     + ", ".join(sorted(_REPORT_TYPES)))
        if not _valid_period(period):
            raise HTTPException(422, "Periodo debe ser YYYY-MM.")
        tid = _tenant_from_request(auth_info, tenant_id_q, tenant_id)
        if report_type in ("monthly", "tax") and tid is None:
            raise HTTPException(422, "Se requiere tenant_id (monthly/tax).")

        pdf_bytes, filename = _build_report(report_type, period, tid, gen)
        rid = _register(report_type, tid, period, filename, pdf_bytes)
        return _pdf_response(pdf_bytes, filename, rid)

    @router.get("/{report_id}/download",
                summary="Descarga un reporte previamente generado por id.")
    def download_report(report_id: str,
                        auth_info: dict = Depends(auth_dep)):
        with _REGISTRY_LOCK:
            entry = _REGISTRY.get(report_id)
        if entry is None:
            raise HTTPException(404, "Reporte no encontrado.")
        # Aislamiento: solo el tenant dueño (si aplica) puede descargar.
        caller_tid = (auth_info or {}).get("tenant_id")
        if caller_tid is not None and entry["tenant_id"] not in (None, caller_tid):
            raise HTTPException(403, "No autorizado para este reporte.")
        return _pdf_response(entry["bytes"], entry["filename"], entry["id"])

    @router.post("/custom",
                 summary="Genera un reporte personalizado a partir de JSON "
                         "(data + template). Devuelve PDF por defecto.")
    def custom_report(req: CustomReportRequest,
                      auth_info: dict = Depends(auth_dep)):
        tid = _tenant_from_request(auth_info, req.tenant_id, tenant_id)
        data = req.data or {}
        title = data.get("title", "Reporte personalizado")
        if req.as_html:
            from fastapi.responses import HTMLResponse
            html = gen.render_html(_html_template_name(req.template), data,
                                   tenant_id=tid)
            return HTMLResponse(html)
        pdf_bytes = gen.custom_report(data, title=title, tenant_id=tid)
        filename = f"custom_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        rid = _register("custom", tid, data.get("period", ""), filename,
                        pdf_bytes)
        return _pdf_response(pdf_bytes, filename, rid)

    return router


def _valid_period(period: str) -> bool:
    if len(period) != 7 or period[4] != "-":
        return False
    try:
        datetime.strptime(period, "%Y-%m")
        return True
    except ValueError:
        return False


def _html_template_name(template: str) -> str:
    """Traduce un template arbitrario a una plantilla HTML conocida."""
    mapping = {
        "monthly": "monthly_summary", "monthly_summary": "monthly_summary",
        "invoices": "invoices_report", "invoices_report": "invoices_report",
        "reconciliation": "reconciliation",
        "anomaly": "anomaly_report", "anomaly_report": "anomaly_report",
        "tax": "tax_report", "tax_report": "tax_report",
    }
    return mapping.get(template, "monthly_summary")


def _build_report(report_type: str, period: str,
                  tid: Optional[int], gen: PDFGenerator):
    """Devuelve (pdf_bytes, filename) para un tipo de reporte."""
    if report_type == "monthly":
        return (gen.monthly_summary(tid, period),
                f"resumen_mensual_{period}.pdf")
    if report_type == "tax":
        return (gen.tax_report(tid, period),
                f"reporte_fiscal_{period}.pdf")

    # Tipos que derivan sus datos de las facturas del periodo.
    rows = db_rows(gen.db, tid, period)
    if report_type == "invoices":
        data = _invoices_data(rows, period)
        return (gen.custom_report(data, title=data.get("title", "Facturas")),
                f"facturas_{period}.pdf")
    if report_type == "anomaly":
        anomalies = _detect_anomalies(rows)
        return (gen.anomaly_report(anomalies, tenant_id=tid),
                f"anomalias_{period}.pdf")
    if report_type == "reconciliation":
        rep = _derive_reconciliation(rows, period)
        return (gen.reconciliation_report(rep, tenant_id=tid),
                f"conciliacion_{period}.pdf")
    raise HTTPException(400, "Tipo de reporte inválido.")


def db_rows(db, tid: Optional[int], period: str):
    """Facturas del tenant filtradas por periodo."""
    invoices = db.list_invoices(tenant_id=tid) if tid is not None else []
    return [i for i in invoices if _periodo(i.get("fecha")) == period]


def _invoices_data(rows, period: str) -> Dict[str, Any]:
    """Dict genérico (kpis/summary/table/chart) para el reporte de facturas."""
    total = sum(_f(i.get("total")) for i in rows)
    iva = sum(_f(i.get("iva")) for i in rows)
    validas = sum(1 for i in rows if i.get("valido") in (1, True, "1"))
    cats: Dict[str, float] = {}
    for i in rows:
        c = i.get("categoria") or "sin-categoría"
        cats[c] = cats.get(c, 0.0) + _f(i.get("total"))
    return {
        "title": "Reporte de Facturas",
        "subtitle": f"Periodo {period} · {len(rows)} factura(s)",
        "period": period,
        "kpis": [
            {"label": "Facturas", "value": str(len(rows))},
            {"label": "Monto total", "value": mxn(total)},
            {"label": "IVA", "value": mxn(iva)},
            {"label": "Válidas", "value": str(validas)},
        ],
        "table": {
            "headers": ["Folio", "Fecha", "Emisor", "Categoría", "Total"],
            "rows": [[i.get("folio_fiscal", "—"),
                      fecha_mx(i.get("fecha")),
                      (i.get("emisor_rfc") or "—"),
                      (i.get("categoria") or "—"),
                      mxn(i.get("total"))] for i in rows[:200]],
            "numCols": [4],
        },
        "chart": {
            "type": "bar",
            "title": "Monto por categoría",
            "labels": [c for c, _ in sorted(cats.items(), key=lambda kv: kv[1],
                                            reverse=True)[:10]],
            "values": [round(v, 2) for _, v in
                       sorted(cats.items(), key=lambda kv: kv[1],
                              reverse=True)[:10]],
        },
    }


def _f(v: Any) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0
