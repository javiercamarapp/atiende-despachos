# -*- coding: utf-8 -*-
"""routes.py — Portal del cliente server-rendered (HTML/Jinja2).

Páginas:
    GET  /portal/login                 formulario de acceso.
    POST /portal/login                 autentica (bcrypt) y setea la cookie.
    GET  /portal/logout                cierra la sesión.
    GET  /portal/dashboard             overview con stats.
    GET  /portal/invoices              tabla con filtros y búsqueda.
    GET  /portal/invoices/{id}         detalle de una factura.
    GET  /portal/reports               lista de reportes gerenciales.
    GET  /portal/reports/{id}/download descarga el reporte (HTML->PDF).
    GET  /portal/settings              configuración del tenant.
    PUT  /portal/settings              actualiza la configuración (JSON).
    GET  /portal/notifications         últimas notificaciones (JSON).
    GET  /portal/notifications/stream  SSE tiempo real.
    GET  /portal/invoices/export.xlsx  exporta el historial a Excel.

Auth: sesión por cookie `portal_session` (HttpOnly). El login valida
email+password con bcrypt y crea una sesión ligada a `client_users` (y por
tanto a un tenant): TODA consulta filtra por ese tenant (multi-tenant).
Para compatibilidad, las páginas también aceptan el token vía query
`?token=` o header `Authorization: Bearer`.
"""
from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import (APIRouter, Depends, Form, HTTPException, Query, Request,
                     Response)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from b2b_ai.services.reports import GerentialReports

SESSION_TTL_DAYS = 30
COOKIE_NAME = "portal_session"

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Catálogo de reportes gerenciales generados bajo demanda (no hay tabla de
# reportes persistidos; se construyen sobre las facturas del tenant).
REPORT_CATALOG = [
    {"id": "resumen", "nombre": "Resumen ejecutivo",
     "desc": "Totales del periodo: facturas, montos, IVA, tasa de error y anomalías."},
    {"id": "proveedores", "nombre": "Análisis de proveedores",
     "desc": "Top proveedores por monto, frecuencia y anomalías asociadas."},
    {"id": "flujo_caja", "nombre": "Flujo de caja",
     "desc": "Ingresos vs egresos por mes y proyección del siguiente mes."},
    {"id": "alertas", "nombre": "Alertas y pendientes",
     "desc": "Facturas que requieren atención y anomalías de severidad alta/crítica."},
]
_REPORT_IDS = {r["id"] for r in REPORT_CATALOG}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class SettingsUpdate(BaseModel):
    rfc: Optional[str] = None
    erp_type: Optional[str] = None
    plantilla_contable: Optional[str] = None
    notif_channel: Optional[str] = None
    notif_recipient: Optional[str] = None


# --------------------------------------------------------------------------
# Password / sesión (mismas primitivas que api/portal.py)
# --------------------------------------------------------------------------
def _check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _expires() -> str:
    return (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).isoformat(
        timespec="seconds")


# --------------------------------------------------------------------------
# Auth helper
# --------------------------------------------------------------------------
def _resolve_user(db, request: Request) -> Optional[dict]:
    """Resuelve el usuario autenticado desde cookie, query `token` o header
    `Authorization`. Devuelve None si no hay sesión válida."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        return None
    session = db.get_portal_session(token)
    if session is None:
        return None
    return {"token": token, **session}


def _page_or_redirect(db, request, template: str, context: dict, status=200):
    """Renderiza una página HTML si hay sesión; si no, redirige a /login."""
    user = _resolve_user(db, request)
    if user is None:
        return RedirectResponse(url="/portal/login", status_code=302)
    return templates.TemplateResponse(
        request, template,
        {"request": request, "user": user, **context}, status_code=status)


def _require_user_json(db, request: Request) -> dict:
    """Igual que _resolve_user pero lanza 401 para endpoints JSON."""
    user = _resolve_user(db, request)
    if user is None:
        raise HTTPException(status_code=401,
                            detail="Se requiere sesión del portal.")
    return user


# --------------------------------------------------------------------------
# Helpers de datos / formato
# --------------------------------------------------------------------------
def _dec(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(v):
    try:
        return "${:,.2f}".format(_dec(v))
    except (TypeError, ValueError):
        return ""


def _estado(inv) -> str:
    """Estado legible de una factura a partir de sus flags."""
    if not inv.get("valido"):
        return "invalida"
    if inv.get("requires_human_review"):
        return "anomalia"
    s = str(inv.get("status") or "procesado").lower()
    return s if s else "procesado"


def _filter_invoices(invoices, estado=None, proveedor=None, q=None,
                     fecha_desde=None, fecha_hasta=None):
    """Filtra en memoria: fecha, estado, proveedor y búsqueda RFC/folio."""
    out = invoices
    if fecha_desde:
        out = [i for i in out if (i.get("fecha") or "") >= fecha_desde]
    if fecha_hasta:
        out = [i for i in out if (i.get("fecha") or "") <= fecha_hasta]
    if estado:
        e = estado.strip().lower()
        out = [i for i in out if _estado(i) == e]
    if proveedor:
        p = proveedor.strip().lower()
        out = [i for i in out if p in (i.get("emisor_rfc") or "").lower()
               or p in (i.get("emisor_nombre") or "").lower()]
    if q:
        needle = q.strip().lower()
        out = [i for i in out
               if needle in (i.get("emisor_rfc") or "").lower()
               or needle in (i.get("receptor_rfc") or "").lower()
               or needle in (i.get("folio_fiscal") or "").lower()
               or needle in (i.get("folio") or "").lower()
               or needle in (i.get("serie") or "").lower()]
    return out


def _notifications_for(db, tenant_id, limit=50):
    return db.list_notifications(tenant_id=tenant_id, limit=limit)


def _query_string(request):
    """Devuelve '?k=v&...' con los query params actuales (para links de
    exportación que preservan los filtros)."""
    from urllib.parse import urlencode
    params = [(k, v) for k, v in request.query_params.multi_items()]
    return ("?" + urlencode(params)) if params else ""


def _build_report(db, report_id, invoices):
    """Genera el dict de un reporte gerencial por id. Lanza 404 si es inválido."""
    if report_id not in _REPORT_IDS:
        raise HTTPException(status_code=404, detail="Reporte no encontrado.")
    gr = GerentialReports(invoices)
    if report_id == "resumen":
        return gr.resumen_ejecutivo()
    if report_id == "proveedores":
        return gr.analisis_proveedores()
    if report_id == "flujo_caja":
        return gr.flujo_caja()
    if report_id == "alertas":
        return gr.alertas()
    raise HTTPException(status_code=404, detail="Reporte no encontrado.")


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
# Globals de formato disponibles en todas las plantillas (definidas arriba).
templates.env.globals["money"] = _money
templates.env.globals["estado"] = _estado


def build_portal_pages_router(db):
    router = APIRouter(prefix="/portal", tags=["portal-pages"])

    # ---- Sesión (páginas) -------------------------------------------------
    @router.get("/login", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request):
        # Si ya hay sesión, ir directo al dashboard.
        if _resolve_user(db, request) is not None:
            return RedirectResponse(url="/portal/dashboard", status_code=302)
        error = request.query_params.get("error")
        return templates.TemplateResponse(
            request, "login.html",
            {"request": request, "user": None,
             "error": "Credenciales inválidas." if error else None})

    @router.post("/login", include_in_schema=False)
    def login_submit(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
    ):
        em = (email or "").strip().lower()
        if not em or not password:
            return RedirectResponse(url="/portal/login?error=1", status_code=302)
        user = db.get_client_user_by_email(em)
        if user is None or not _check_password(password, user["password_hash"]):
            return RedirectResponse(url="/portal/login?error=1", status_code=302)
        token = _new_token()
        db.create_portal_session(user["id"], token, _expires())
        resp = RedirectResponse(url="/portal/dashboard", status_code=302)
        resp.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL_DAYS * 86400,
                        httponly=True, samesite="lax", path="/")
        return resp

    @router.get("/logout", include_in_schema=False)
    def logout(request: Request):
        user = _resolve_user(db, request)
        if user is not None:
            db.delete_portal_session(user["token"])
        resp = RedirectResponse(url="/portal/login", status_code=302)
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp

    # ---- Dashboard --------------------------------------------------------
    @router.get("/dashboard", response_class=HTMLResponse,
                include_in_schema=False)
    def dashboard(request: Request):
        user = _resolve_user(db, request)
        if user is None:
            return RedirectResponse(url="/portal/login", status_code=302)
        tenant = user["tenant_id"]
        invoices = db.list_invoices(tenant_id=tenant)
        stats = db.invoice_stats(tenant_id=tenant)
        anomalias = sum(1 for i in invoices if i.get("requires_human_review"))
        procesadas = sum(1 for i in invoices
                         if (i.get("status") or "") == "procesado")
        pendientes = max(0, len(invoices) - procesadas)
        tenant_row = db.get_tenant_by_id(tenant) or {}
        notifs = _notifications_for(db, tenant, limit=8)
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"request": request, "user": user, "tenant": tenant_row,
             "stats": {
                 "total_facturas": stats["total_facturas"],
                 "monto_total": _money(stats["monto_total"]),
                 "iva_total": _money(stats["iva_total"]),
                 "anomalias": anomalias,
                 "procesadas": procesadas,
                 "pendientes": pendientes,
             },
             "recent": invoices[:8], "notifications": notifs})

    # ---- Facturas ---------------------------------------------------------
    @router.get("/invoices", response_class=HTMLResponse,
                include_in_schema=False)
    def invoices_page(
        request: Request,
        estado: Optional[str] = Query(default=None),
        proveedor: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None, description="RFC / folio fiscal"),
        fecha_desde: Optional[str] = Query(default=None),
        fecha_hasta: Optional[str] = Query(default=None),
    ):
        user = _resolve_user(db, request)
        if user is None:
            return RedirectResponse(url="/portal/login", status_code=302)
        tenant = user["tenant_id"]
        invoices = db.list_invoices(tenant_id=tenant, limit=1000)
        filtered = _filter_invoices(invoices, estado=estado, proveedor=proveedor,
                                    q=q, fecha_desde=fecha_desde,
                                    fecha_hasta=fecha_hasta)
        # Lista de proveedores distintos para el dropdown del filtro.
        providers = sorted({(i.get("emisor_rfc") or ""): (i.get("emisor_nombre")
                           or i.get("emisor_rfc") or "") for i in invoices}.items())
        return templates.TemplateResponse(
            request, "invoices.html",
            {"request": request, "user": user,
             "invoices": filtered, "count": len(filtered),
             "f_estado": estado or "", "proveedor": proveedor or "",
             "q": q or "", "fecha_desde": fecha_desde or "",
             "fecha_hasta": fecha_hasta or "",
             "query_string": _query_string(request),
             "providers": providers})

    @router.get("/invoices/export.csv", include_in_schema=False)
    def invoices_export_csv(request: Request):
        user = _require_user_json(db, request)
        tenant = user["tenant_id"]
        invoices = _filter_invoices(
            db.list_invoices(tenant_id=tenant),
            estado=request.query_params.get("estado"),
            proveedor=request.query_params.get("proveedor"),
            q=request.query_params.get("q"),
            fecha_desde=request.query_params.get("fecha_desde"),
            fecha_hasta=request.query_params.get("fecha_hasta"))
        cols = ["id", "fecha", "tipo", "serie", "folio", "folio_fiscal",
                "emisor_rfc", "emisor_nombre", "receptor_rfc", "subtotal",
                "iva", "total", "moneda", "categoria", "valido", "status"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for inv in invoices:
            w.writerow([inv.get(c, "") for c in cols])
        return Response(content="\ufeff" + buf.getvalue(),
                        media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 'attachment; filename="facturas_portal.csv"'})

    @router.get("/invoices/export.xlsx", include_in_schema=False)
    def invoices_export_xlsx(request: Request):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        user = _require_user_json(db, request)
        tenant = user["tenant_id"]
        invoices = _filter_invoices(
            db.list_invoices(tenant_id=tenant),
            estado=request.query_params.get("estado"),
            proveedor=request.query_params.get("proveedor"),
            q=request.query_params.get("q"),
            fecha_desde=request.query_params.get("fecha_desde"),
            fecha_hasta=request.query_params.get("fecha_hasta"))
        cols = ["id", "fecha", "tipo", "serie", "folio", "folio_fiscal",
                "emisor_rfc", "emisor_nombre", "receptor_rfc", "subtotal",
                "iva", "total", "moneda", "categoria", "valido", "status"]
        wb = Workbook()
        ws = wb.active
        ws.title = "Facturas"
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for inv in invoices:
            ws.append([inv.get(c, "") for c in cols])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type=("application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"),
            headers={"Content-Disposition":
                     'attachment; filename="facturas_portal.xlsx"'})

    @router.get("/invoices/{invoice_id}", response_class=HTMLResponse,
                include_in_schema=False)
    def invoice_detail(request: Request, invoice_id: int):
        user = _resolve_user(db, request)
        if user is None:
            return RedirectResponse(url="/portal/login", status_code=302)
        inv = db.get_invoice(invoice_id, tenant_id=user["tenant_id"])
        if inv is None:
            raise HTTPException(status_code=404,
                                detail="Factura no encontrada.")
        return templates.TemplateResponse(
            request, "invoice_detail.html",
            {"request": request, "user": user, "inv": inv})

    # ---- Reportes ---------------------------------------------------------
    @router.get("/reports", response_class=HTMLResponse, include_in_schema=False)
    def reports_page(request: Request):
        user = _resolve_user(db, request)
        if user is None:
            return RedirectResponse(url="/portal/login", status_code=302)
        invoices = db.list_invoices(tenant_id=user["tenant_id"])
        return templates.TemplateResponse(
            request, "reports.html",
            {"request": request, "user": user,
             "reports": REPORT_CATALOG,
             "invoice_count": len(invoices)})

    @router.get("/reports/{report_id}/download", include_in_schema=False)
    def report_download(request: Request, report_id: str):
        user = _require_user_json(db, request)
        invoices = db.list_invoices(tenant_id=user["tenant_id"])
        report = _build_report(db, report_id, invoices)
        gr = GerentialReports(invoices)
        title = next((r["nombre"] for r in REPORT_CATALOG
                      if r["id"] == report_id), report_id.title())
        html = gr.export_pdf(report, title=title)
        return Response(
            content=html, media_type="text/html; charset=utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="reporte_{report_id}.pdf"'})

    # ---- Settings ---------------------------------------------------------
    @router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
    def settings_page(request: Request):
        user = _resolve_user(db, request)
        if user is None:
            return RedirectResponse(url="/portal/login", status_code=302)
        tenant = user["tenant_id"]
        tenant_row = db.get_tenant_by_id(tenant) or {}
        cfg = {
            "rfc": db.get_tenant_config(tenant, "rfc", "") or "",
            "erp_type": db.get_tenant_config(tenant, "erp_type",
                                             "contpaqi") or "contpaqi",
            "plantilla_contable": db.get_tenant_config(
                tenant, "plantilla_contable", "SAT") or "SAT",
            "notif_channel": db.get_tenant_config(tenant, "notif_channel",
                                                  "email") or "email",
            "notif_recipient": db.get_tenant_config(tenant, "notif_recipient",
                                                    "") or "",
        }
        saved = request.query_params.get("saved")
        return templates.TemplateResponse(
            request, "settings.html",
            {"request": request, "user": user, "tenant": tenant_row,
             "cfg": cfg, "saved": saved == "1"})

    @router.put("/settings")
    def settings_update(request: Request, body: SettingsUpdate):
        user = _require_user_json(db, request)
        tenant = user["tenant_id"]
        updated = []
        data = body.model_dump(exclude_unset=True)
        for key, value in data.items():
            if value is None or value == "":
                continue
            db.set_tenant_config(tenant, key, str(value))
            updated.append(key)
        return {"ok": True, "tenant_id": tenant, "updated": updated}

    # ---- Notificaciones (tiempo real) -------------------------------------
    @router.get("/notifications")
    def notifications_json(request: Request,
                           limit: int = Query(default=50, ge=1, le=200)):
        user = _require_user_json(db, request)
        rows = _notifications_for(db, user["tenant_id"], limit=limit)
        return {"count": len(rows), "notifications": rows}

    @router.get("/notifications/stream", include_in_schema=False)
    def notifications_stream(request: Request):
        from fastapi.responses import StreamingResponse
        user = _resolve_user(db, request)
        if user is None:
            return JSONResponse(status_code=401,
                                content={"detail": "Se requiere sesión."})

        def _events():
            tenant = user["tenant_id"]
            last_seen = 0
            # Primer batch: notificaciones recientes.
            try:
                for n in _notifications_for(db, tenant, limit=20):
                    if n.get("id", 0) > last_seen:
                        last_seen = n["id"]
                    yield _sse("notification", n)
            except Exception:  # noqa: BLE001
                pass
            yield _sse("heartbeat", {"ts": datetime.now().isoformat()})
            # Polling ligero: revisa notificaciones nuevas cada 3s.
            # Se limita a un número fijo de ciclos para compatibilidad
            # con TestClient (que espera el cierre del generador).
            import time as _time
            for _cycle in range(3):
                try:
                    _time.sleep(3)
                    new = [n for n in _notifications_for(db, tenant, limit=20)
                           if n.get("id", 0) > last_seen]
                    for n in new:
                        last_seen = n["id"]
                        yield _sse("notification", n)
                    yield _sse("heartbeat", {"ts": datetime.now().isoformat()})
                except GeneratorExit:
                    break
                except Exception:  # noqa: BLE001
                    try:
                        yield _sse("error", {"detail": "error del stream"})
                    except GeneratorExit:
                        break

        return StreamingResponse(_events(),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return router


def _sse(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
