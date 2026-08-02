# -*- coding: utf-8 -*-
"""
dashboard.py — Dashboard web del agente contable (FASE 2).

Genera una página HTML con métricas en vivo, gráficas de facturas procesadas
y el estado de conciliación bancaria. Sin dependencias externas de frontend:
las gráficas se dibujan con SVG inline y los datos se sirven desde la DB.

Endpoints (montados bajo /api/v1 en app.py):
    GET /api/v1/dashboard       → HTML completo (métricas + gráficas + conciliación)
    GET /api/v1/dashboard/data  → JSON con los mismos datos (para refresh en vivo)

La conciliación mostrada es una MUESTRA: cruza las facturas reales de la DB
contra un estado de cuenta sintético derivado de ellas (más 2 movimientos
huérfanos) para que el panel siempre tenga algo que reportar. El estado real
depende del estado de cuenta del banco.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from b2b_ai.services.report import generate_report
from b2b_ai.services.reconcile import build_reconciliation_report
from b2b_ai.services import anomaly as anomaly_svc
from b2b_ai.services.reports import GerentialReports

# Datos del emisor que se muestran en el encabezado del panel.
EMISOR = {"rfc": "DESP820101AB1", "nombre": "Despacho Contable Likida"}


# Cache TTL para las lecturas agregadas del dashboard (/dashboard/data y
# /dashboard). Mismo contrato que el cache de /api/v1/stats en app.py: la key
# incluye la versión de datos de la DB, que sube en cada escritura de facturas,
# así el cache nunca sirve datos viejos tras una inserción.
class _DashboardCache:
    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def get(self, dbid, route, tenant, version):
        with self._lock:
            item = self._store.get((dbid, route, tenant, version))
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > self.ttl:
            with self._lock:
                self._store.pop((dbid, route, tenant, version), None)
            return None
        return value

    def set(self, dbid, route, tenant, version, value):
        with self._lock:
            self._store[(dbid, route, tenant, version)] = (time.monotonic(), value)


_dash_cache = _DashboardCache()


def _build_dashboard_data(db: Any, tenant_id: Optional[int] = None) -> Dict[str, Any]:
    """Reúne métricas, gráficas y estado de conciliación desde la DB."""
    invoices = db.list_invoices(tenant_id=tenant_id)
    report = generate_report(invoices)

    # Gráfica 1: por categoría
    por_categoria = [
        {"categoria": c, "count": v["count"], "monto": float(v["total"])}
        for c, v in sorted(report["por_categoria"].items(),
                           key=lambda kv: kv[1]["count"], reverse=True)
    ]
    # Gráfica 2: por mes
    por_mes = [
        {"mes": m, "count": v["count"], "monto": float(v["total"])}
        for m, v in sorted(report["por_mes"].items())
    ]

    # Conciliación (muestra): facturas reales vs estado de cuenta sintético.
    conciliacion = _demo_reconcile(invoices)

    return {
        "service": "Likida AI Enterprise — Enterprise",
        "emisor": EMISOR,
        "tenant_id": tenant_id,
        "metricas": {
            "total_facturas": len(invoices),
            "monto_total": float(report["total"]),
            "iva_total": float(report["iva"]),
            "subtotal": float(report["subtotal"]),
            "validas": report["validas"],
            "invalidas": report["invalidas"],
            "audit_calls": db.count_audit(),
        },
        "graficas": {
            "por_categoria": por_categoria,
            "por_mes": por_mes,
        },
        "conciliacion": conciliacion,
    }


def _demo_reconcile(invoices: List[Dict[str, Any]], max_invoices: int = 20) -> Dict[str, Any]:
    """Construye un estado de cuenta sintético y concilia contra facturas reales.

    Cada factura real (últimas `max_invoices`) genera un movimiento bancario
    con el mismo monto y fecha (±), más 2 movimientos sin pareja para mostrar
    pendientes. Resultado etiquetado como 'muestra'.
    """
    recent = invoices[:max_invoices]
    bank = []
    for inv in recent:
        bank.append({
            "fecha": (inv.get("fecha") or "")[:10],
            "monto": abs(float(inv.get("total") or 0)),
            "descripcion": "Transferencia",
            "ref": inv.get("folio_fiscal") or "",
        })
    # Movimientos huérfanos para ilustrar pendientes
    bank.append({"fecha": "2026-07-20", "monto": 3500.00,
                 "descripcion": "Cargo no identificado", "ref": "ORPHAN-1"})
    bank.append({"fecha": "2026-07-21", "monto": 1200.00,
                 "descripcion": "Abono sin factura", "ref": "ORPHAN-2"})

    inv_side = [{
        "folio_fiscal": i.get("folio_fiscal"),
        "fecha": i.get("fecha"),
        "total": i.get("total"),
        "emisor": i.get("emisor_rfc"),
    } for i in recent if i.get("folio_fiscal")]

    report = build_reconciliation_report(inv_side, bank)
    report["es_muestra"] = True
    return report


# ---------------------------------------------------------------------------
# FASE 3 — Agregados para el dashboard interactivo y reportes gerenciales
# ---------------------------------------------------------------------------

def _invoice_anomalies(invoices):
    """Detecta anomalías para todas las facturas (con contexto de factura).

    Optimizado para no ser O(n²): agrupa las facturas por RFC una sola vez y
    reutiliza el grupo como historial para cada factura, en lugar de reconstruir
    `hist = [x for x in invoices if x is not inv]` por cada una (que era O(n²)
    en el número de facturas).
    """
    from collections import defaultdict
    by_rfc = defaultdict(list)
    for inv in invoices:
        by_rfc[inv.get("emisor_rfc") or ""].append(inv)

    out = []
    for inv in invoices:
        # Historial = mismas facturas del mismo RFC, EXCLUYENDO la actual
        # (equivalente al `[x for x in invoices if x is not inv]` original).
        # Cada check de anomalía filtra por RFC de todos modos, así que el
        # resultado es idéntico, pero sin reconstruir la lista completa por
        # cada factura (de ahí el ahorro de O(n²) a O(n·k), k = facturas/RFC).
        hist = [x for x in by_rfc.get(inv.get("emisor_rfc") or "", [])
                if x is not inv]
        for a in anomaly_svc.detect_anomalies(inv, hist):
            a = dict(a)
            a["invoice_id"] = inv.get("id")
            a["emisor_rfc"] = inv.get("emisor_rfc", "")
            a["fecha"] = inv.get("fecha", "")
            a["folio_fiscal"] = inv.get("folio_fiscal")
            a["monto"] = _num(inv.get("total"))
            out.append(a)
    return out


def _num(v: Any) -> float:
    """Convierte a float de forma tolerante."""
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _group_monthly(invoices: List[Dict[str, Any]],
                   anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrupa facturas/anomalías por mes (YYYY-MM)."""
    from collections import defaultdict
    meses = defaultdict(lambda: {"facturas": 0, "monto": 0.0, "anomalias": 0})
    for inv in invoices:
        mes = str(inv.get("fecha") or "")[:7] or "sin-fecha"
        meses[mes]["facturas"] += 1
        meses[mes]["monto"] += _num(inv.get("total"))
    for a in anomalies:
        mes = str(a.get("fecha") or "")[:7] or "sin-fecha"
        meses[mes]["anomalias"] += 1
    return [{"mes": m, **meses[m]}
            for m in sorted(meses.keys())]


def _top_providers(invoices: List[Dict[str, Any]],
                   anomalies: List[Dict[str, Any]],
                   limit: int = 10) -> List[Dict[str, Any]]:
    """Top proveedores por monto con frecuencia y anomalías."""
    from collections import defaultdict
    agg = defaultdict(lambda: {"count": 0, "monto": 0.0, "anomalias": 0})
    for inv in invoices:
        rfc = inv.get("emisor_rfc") or inv.get("emisor_nombre") or "desconocido"
        agg[rfc]["count"] += 1
        agg[rfc]["monto"] += _num(inv.get("total"))
        agg[rfc]["nombre"] = inv.get("emisor_nombre") or rfc
    for a in anomalies:
        rfc = a.get("emisor_rfc")
        if rfc and rfc in agg:
            agg[rfc]["anomalias"] += 1
    provs = [{"rfc": r, "nombre": d["nombre"], "count": d["count"],
              "monto": round(d["monto"], 2), "anomalias": d["anomalias"]}
             for r, d in agg.items()]
    provs.sort(key=lambda p: p["monto"], reverse=True)
    return provs[:limit]


def _kpi_metrics(invoices: List[Dict[str, Any]],
                 anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Métricas clave: tiempo promedio, tasa de error, % automático."""
    total = len(invoices)
    if total == 0:
        return {
            "total_facturas": 0, "monto_total": 0.0,
            "tiempo_promedio_procesamiento_seg": 0.0,
            "tasa_error_pct": 0.0, "porcentaje_automatico_pct": 0.0,
            "anomalias_total": 0,
        }

    invalidas = sum(1 for i in invoices if not _bool_valid(i.get("valido")))
    # Procesamiento: diferencia procesado_en - created_at cuando difieren.
    tiempos = []
    for i in invoices:
        a, b = i.get("created_at"), i.get("procesado_en")
        if a and b and str(a) != str(b):
            t0, t1 = _iso_ts(a), _iso_ts(b)
            if t0 is not None and t1 is not None:
                tiempos.append(max(0.0, (t1 - t0).total_seconds()))
    tiempo = round(sum(tiempos) / len(tiempos), 2) if tiempos else 0.0

    auto = sum(1 for i in invoices if not _bool_valid(i.get("requires_human_review")))
    return {
        "total_facturas": total,
        "monto_total": round(sum(_num(i.get("total")) for i in invoices), 2),
        "tiempo_promedio_procesamiento_seg": tiempo,
        "tasa_error_pct": round(invalidas / total * 100, 2),
        "porcentaje_automatico_pct": round(auto / total * 100, 2),
        "anomalias_total": len(anomalies),
    }


def _bool_valid(v: Any) -> bool:
    return v in (1, True, "1", "true", "SI", "si", "True")


def _iso_ts(v: Any) -> Optional[datetime]:
    """Convierte un timestamp ISO a datetime o None."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# HTML (vanilla, sin build)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Dashboard</title>
<style>
  :root {{
    --bg:#0f172a; --card:#1e293b; --line:#334155; --txt:#e2e8f0;
    --mut:#94a3b8; --acc:#38bdf8; --ok:#34d399; --warn:#fbbf24; --err:#f87171;
  }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         background:var(--bg); color:var(--txt); padding:24px; }}
  .wrap {{ max-width:1100px; margin:0 auto; }}
  header {{ display:flex; justify-content:space-between; align-items:center;
            border-bottom:1px solid var(--line); padding-bottom:14px; margin-bottom:20px; }}
  h1 {{ font-size:22px; }} .sub {{ color:var(--mut); font-size:13px; margin-top:4px; }}
  .badge {{ background:var(--acc); color:#04222f; border-radius:20px; padding:4px 10px;
            font-size:12px; font-weight:700; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
          gap:14px; margin-bottom:20px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:16px; }}
  .kpi {{ font-size:26px; font-weight:800; margin-top:6px; }}
  .kpi .lbl {{ font-size:12px; color:var(--mut); display:block; font-weight:600; }}
  h2 {{ font-size:16px; margin-bottom:12px; }}
  .row {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  @media (max-width:760px) {{ .row {{ grid-template-columns:1fr; }} }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--mut); font-weight:600; }}
  .ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }} .err {{ color:var(--err); }}
  .mut {{ color:var(--mut); font-size:12px; }}
  .pill {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px;
           font-weight:700; }}
  .p-ok {{ background:#064e3b; color:var(--ok); }}
  .p-warn {{ background:#713f12; color:var(--warn); }}
  .bar {{ background:var(--acc); border-radius:4px; height:18px; }}
  .legend {{ font-size:12px; color:var(--mut); }}
  #refreshing {{ opacity:.5; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>🧾 {title} <span class="badge">Dashboard en vivo</span></h1>
      <div class="sub">{emisor_rfc} · {emisor_nombre} · Tenant {tenant}</div>
    </div>
    <button id="refresh" onclick="refresh()">↻ Refrescar</button>
  </header>

  <div class="grid" id="kpis"></div>

  <div class="row">
    <div class="card">
      <h2>Facturas por categoría</h2>
      <div id="ch-cat"></div>
    </div>
    <div class="card">
      <h2>Facturas por mes</h2>
      <div id="ch-mes"></div>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>Estado de conciliación bancaria <span class="mut">(muestra demo)</span></h2>
    <div id="conc"></div>
  </div>
</div>

<script>
let DATA = {data};

// Escape HTML en cualquier cadena que se vaya a inyectar vía innerHTML.
// Previene XSS almacenado si un campo (categoría, emisor, folio, mes...)
// llega con contenido malicioso. Regresión de auditoría de seguridad.
function esc(v){{
  return String(v == null ? '' : v)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

function kpi(id, lbl, val, extra){{
  document.getElementById(id).innerHTML =
    '<div class="kpi"><span class="lbl">'+esc(lbl)+'</span>'+val+'</div>'+(extra||'');
}}

function bars(elId, rows, valKey, lblKey){{
  const max = Math.max(...rows.map(r=>r[valKey]||0), 1);
  let h = '';
  rows.slice(0,8).forEach(r=>{{
    const w = Math.round((r[valKey]||0)/max*100);
    h += '<div style="margin-bottom:8px">'+
         '<div class="legend">'+esc(r[lblKey])+' — $'+Number(r[valKey]).toLocaleString('es-MX')+
         ' ('+r.count+')</div>'+
         '<div class="bar" style="width:'+w+'%"></div></div>';
  }});
  document.getElementById(elId).innerHTML = h || '<div class="mut">Sin datos</div>';
}}

function render(){{
  const m = DATA.metricas;
  kpi('kpis','Facturas procesadas', m.total_facturas);
  const wrap = document.getElementById('kpis');
  wrap.innerHTML +=
    '<div class="card"><div class="kpi"><span class="lbl">Monto total</span>$'+
      Number(m.monto_total).toLocaleString('es-MX')+'</div></div>'+
    '<div class="card"><div class="kpi"><span class="lbl">IVA total</span>$'+
      Number(m.iva_total).toLocaleString('es-MX')+'</div></div>'+
    '<div class="card"><div class="kpi"><span class="lbl">Válidas</span>'+
      m.validas+' <span class="mut">/ '+m.total_facturas+'</span></div></div>'+
    '<div class="card"><div class="kpi"><span class="lbl">Conciliados</span>'+
      DATA.conciliacion.conciliados+'<span class="mut"> / '+DATA.conciliacion.movimientos_banco+'</span></div></div>';

  bars('ch-cat', DATA.graficas.por_categoria, 'monto', 'categoria');
  bars('ch-mes', DATA.graficas.por_mes, 'monto', 'mes');

  // Estado de conciliación
  const c = DATA.conciliacion;
  const tasa = c.tasa_conciliacion;
  const clase = tasa >= 80 ? 'p-ok' : (tasa >= 50 ? 'p-warn' : 'p-err');
  let html =
    '<div style="margin-bottom:10px"><span class="pill '+clase+'">Tasa: '+tasa+'%</span>'+
    ' <span class="mut">conciliados '+c.conciliados+' · pendientes banco '+c.pendientes_banco+
    ' · pendientes facturas '+c.pendientes_facturas+'</span></div>'+
    '<table><tr><th>Folio</th><th>Emisor</th><th>Monto</th><th>Fecha factura</th><th>Fecha banco</th><th>Vía</th></tr>';
  c.matched.slice(0,10).forEach(x=>{{
    html += '<tr><td>'+esc(x.folio_fiscal)+'</td><td>'+esc(x.emisor)+'</td><td>$'+esc(x.monto)+
            '</td><td>'+esc(x.fecha_factura)+'</td><td>'+esc(x.fecha_banco)+'</td><td>'+esc(x.via)+'</td></tr>';
  }});
  html += '</table>';
  if (c.matched.length === 0) html += '<div class="mut">Sin facturas conciliadas.</div>';
  document.getElementById('conc').innerHTML = html;
}}

async function refresh(){{
  const btn = document.getElementById('refresh');
  btn.id = 'refreshing';
  try {{
    const r = await fetch('/api/v1/dashboard/data');
    DATA = await r.json();
    render();
  }} catch(e) {{ alert('No se pudo refrescar: '+e); }}
  btn.id = 'refresh';
}}
render();
</script>
</body>
</html>
"""


def build_dashboard_router(db: Any, require_api_key: Optional[Any] = None,
                           tenant_id: Optional[int] = None) -> APIRouter:
    """Construye el APIRouter del dashboard para una DB inyectada.

    `require_api_key` es la dependency FastAPI de auth (se inyecta desde
    app.py para que el panel use la misma protección que el resto de /api/v1).
    """
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key
    router = APIRouter(tags=["dashboard"])

    @router.get("/dashboard", response_class=HTMLResponse,
                summary="Dashboard web con métricas en vivo.")
    def dashboard(auth_info: dict = Depends(auth_dep)):
        tenant = (auth_info or {}).get("tenant_id") or tenant_id
        data = _build_dashboard_data(db, tenant_id=tenant)
        # Escapa < y > en el JSON embebido en <script> para impedir un
        # 'breakout' de `</script>` con datos almacenados (XSS). El navegador
        # lo decodifica igual: `\u003cscript>` == `<script>` como string JS,
        # pero nunca como cierre del bloque script.
        data_json = json.dumps(data, ensure_ascii=False, default=str)\
            .replace("<", "\\u003c").replace(">", "\\u003e")
        html = _HTML.format(
            title="Likida AI Enterprise",
            data=data_json,
            emisor_rfc=EMISOR["rfc"],
            emisor_nombre=EMISOR["nombre"],
            tenant=tenant if tenant is not None else "—",
        )
        return HTMLResponse(html)

    @router.get("/dashboard/data",
                summary="Datos del dashboard en JSON (refresh en vivo).")
    def dashboard_data(auth_info: dict = Depends(auth_dep)):
        tenant = (auth_info or {}).get("tenant_id") or tenant_id
        # Cache TTL por (db, ruta, tenant, versión de datos). Si no hubo
        # escrituras, se sirve del cache (evita recomputar reconcile+report
        # por cada refresh). Al insertar, data_version sube y se recalcula.
        cached = _dash_cache.get(id(db), "dashboard_data", tenant,
                                 db.data_version())
        if cached is not None:
            return cached
        data = _build_dashboard_data(db, tenant_id=tenant)
        _dash_cache.set(id(db), "dashboard_data", tenant,
                        db.data_version(), data)
        return data

    # ------------------------------------------------------------------ #
    # FASE 3 — Endpoints JSON para el dashboard interactivo y reportes
    # ------------------------------------------------------------------ #
    def _scope_and_invoices(auth_info, query_tenant=None,
                            fecha_desde=None, fecha_hasta=None):
        """Resuelve tenant efectivo y trae facturas filtradas por fecha."""
        tenant = (auth_info or {}).get("tenant_id") or query_tenant or tenant_id
        invoices = db.list_invoices(tenant_id=tenant,
                                    fecha_desde=fecha_desde,
                                    fecha_hasta=fecha_hasta)
        return tenant, invoices

    @router.get("/dashboard/summary",
                summary="Totales de facturas procesadas, monto total y estado.")
    def dashboard_summary(auth_info: dict = Depends(auth_dep),
                          tenant_id_q: Optional[int] = Query(
                              default=None, alias="tenant_id",
                              description="Tenant (solo key de servicio).")):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q)
        rep = GerentialReports(invoices)
        resumen = rep.resumen_ejecutivo()
        estados = {}
        for i in invoices:
            k = i.get("status") or "procesado"
            estados[k] = estados.get(k, 0) + 1
        return {
            "tenant_id": tenant,
            "total_facturas": len(invoices),
            "monto_total": resumen["monto_total"],
            "validas": resumen["validas"],
            "invalidas": resumen["invalidas"],
            "por_estado": estados,
        }

    @router.get("/dashboard/monthly",
                summary="Facturas, montos y anomalías agrupados por mes.")
    def dashboard_monthly(auth_info: dict = Depends(auth_dep),
                          tenant_id_q: Optional[int] = Query(
                              default=None, alias="tenant_id"),
                          fecha_desde: Optional[str] = Query(default=None),
                          fecha_hasta: Optional[str] = Query(default=None)):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q,
                                               fecha_desde, fecha_hasta)
        anomalies = _invoice_anomalies(invoices)
        return {"tenant_id": tenant, "meses": _group_monthly(invoices, anomalies)}

    @router.get("/dashboard/by-provider",
                summary="Facturas por proveedor (top 10 por monto).")
    def dashboard_by_provider(auth_info: dict = Depends(auth_dep),
                              tenant_id_q: Optional[int] = Query(
                                  default=None, alias="tenant_id"),
                              limit: int = Query(default=10, ge=1, le=100)):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q)
        anomalies = _invoice_anomalies(invoices)
        return {"tenant_id": tenant,
                "proveedores": _top_providers(invoices, anomalies, limit)}

    @router.get("/dashboard/anomalies",
                summary="Anomalías detectadas por severidad y tipo.")
    def dashboard_anomalies(auth_info: dict = Depends(auth_dep),
                            tenant_id_q: Optional[int] = Query(
                                default=None, alias="tenant_id")):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q)
        anomalies = _invoice_anomalies(invoices)
        por_sev, por_tipo = {}, {}
        for a in anomalies:
            por_sev[a["severity"]] = por_sev.get(a["severity"], 0) + 1
            por_tipo[a["tipo"]] = por_tipo.get(a["tipo"], 0) + 1
        return {"tenant_id": tenant, "total": len(anomalies),
                "por_severidad": por_sev, "por_tipo": por_tipo}

    @router.get("/dashboard/reconciliation",
                summary="Estado de la conciliación bancaria.")
    def dashboard_reconciliation(auth_info: dict = Depends(auth_dep),
                                 tenant_id_q: Optional[int] = Query(
                                     default=None, alias="tenant_id")):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q)
        rep = GerentialReports(invoices)
        return {"tenant_id": tenant, "reconciliacion": rep.reconciliation()}

    @router.get("/dashboard/kpi",
                summary="Métricas clave (tiempo, error, % automático).")
    def dashboard_kpi(auth_info: dict = Depends(auth_dep),
                      tenant_id_q: Optional[int] = Query(
                          default=None, alias="tenant_id")):
        tenant, invoices = _scope_and_invoices(auth_info, tenant_id_q)
        anomalies = _invoice_anomalies(invoices)
        return {"tenant_id": tenant, "kpi": _kpi_metrics(invoices, anomalies)}

    return router
