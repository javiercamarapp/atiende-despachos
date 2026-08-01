# -*- coding: utf-8 -*-
"""
reports.py — Reportes gerenciales del agente contable (FASE 3).

Reportes de alto nivel pensados para la dirección de un despacho/cliente,
consumidos por el dashboard web interactivo y exportables a CSV / PDF.

Reutiliza los servicios existentes:
  - report.generate_report    → agregados de montos/validez por periodo.
  - anomaly.detect_anomalies  → detección de riesgos por factura.
  - reconcile.build_reconciliation_report → estado de conciliación bancaria.

La clase `GerentialReports` trabaja sobre las facturas tal como las expone
la capa de datos (`db.list_invoices`): lista de dicts con al menos los campos
{fecha, total, subtotal, iva, tipo, emisor_rfc, emisor_nombre, categoria,
valido, requires_human_review, erp_status, status}. Es agnóstica al
transporte (DB / mocks) y devuelve dicts JSON-serializable.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime

from b2b_ai.services.report import generate_report
from b2b_ai.services import anomaly
from b2b_ai.services import reconcile

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
CRITICAL_SEVERITIES = ("high", "critical")


def _dec(v):
    """Convierte a float de forma tolerante (None/texto raro -> 0.0)."""
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _periodo(fecha):
    """Devuelve 'YYYY-MM' o 'sin-fecha'."""
    return str(fecha or "")[:7] or "sin-fecha"


def _bool(v):
    """Normaliza un flag de validez / revisión a booleano."""
    return v in (1, True, "1", "true", "SI", "si", "True")


class GerentialReports:
    """Reportes gerenciales sobre un conjunto de facturas.

    Parámetros:
        invoices:      lista de dicts (campos de la capa de datos).
        anomalies:     lista opcional de anomalías ya detectadas (si se
                       omite, se detectan internamente con anomaly service).
        reconciliation: reporte de conciliación opcional (dict). Si se omite
                        y se pide el dato, se construye una muestra derivada
                        de las facturas (para que el panel siempre tenga qué
                        reportar).
    """

    def __init__(self, invoices, anomalies=None, reconciliation=None):
        self.invoices = list(invoices)
        self._anomalies = anomalies if anomalies is not None else self._detect_all()
        self._reconciliation = reconciliation

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _detect_all(self):
        """Detecta anomalías para cada factura contra el resto del conjunto."""
        out = []
        for inv in self.invoices:
            hist = [x for x in self.invoices if x is not inv]
            for a in anomaly.detect_anomalies(inv, hist):
                a = dict(a)
                a["invoice_id"] = inv.get("id")
                a["emisor_rfc"] = inv.get("emisor_rfc", "")
                a["fecha"] = inv.get("fecha", "")
                a["folio_fiscal"] = inv.get("folio_fiscal")
                a["monto"] = _dec(inv.get("total"))
                out.append(a)
        return out

    def _by_period(self, period=None):
        if not period:
            return self.invoices
        return [i for i in self.invoices if _periodo(i.get("fecha")) == period]

    def reconciliation(self):
        """Devuelve el estado de conciliación (real o muestra derivada)."""
        if self._reconciliation is not None:
            return self._reconciliation
        inv_side = [{
            "folio_fiscal": i.get("folio_fiscal"),
            "fecha": i.get("fecha"),
            "total": i.get("total"),
            "emisor": i.get("emisor_rfc"),
        } for i in self.invoices if i.get("folio_fiscal")]
        bank = []
        for inv in inv_side[:20]:
            bank.append({
                "fecha": (inv.get("fecha") or "")[:10],
                "monto": abs(_dec(inv.get("total"))),
                "descripcion": "Transferencia",
                "ref": inv.get("folio_fiscal") or "",
            })
        rep = reconcile.build_reconciliation_report(inv_side, bank)
        rep["es_muestra"] = True
        return rep

    # ------------------------------------------------------------------ #
    # Reportes
    # ------------------------------------------------------------------ #
    def resumen_ejecutivo(self, period=None):
        """Totales del mes/periodo: facturas, montos, anomalías, tasa error."""
        rows = self._by_period(period)
        rep = generate_report(rows)
        total = _dec(rep["total"])
        invalidas = int(rep["invalidas"])
        facturas = len(rows)
        por_sev = defaultdict(int)
        for a in self._anomalies:
            if period and _periodo(a.get("fecha")) != period:
                continue
            por_sev[a["severity"]] += 1
        tasa_error = round(invalidas / facturas * 100, 2) if facturas else 0.0
        return {
            "periodo": period,
            "facturas": facturas,
            "validas": int(rep["validas"]),
            "invalidas": invalidas,
            "subtotal": _dec(rep["subtotal"]),
            "iva": _dec(rep["iva"]),
            "monto_total": round(total, 2),
            "tasa_error": tasa_error,
            "anomalias": {"total": sum(por_sev.values()),
                          "por_severidad": dict(por_sev)},
            "reconciliacion": self.reconciliation() if facturas else None,
        }

    def analisis_proveedores(self, limit=10):
        """Top proveedores por monto: frecuencia, monto, anomalías."""
        agg = defaultdict(lambda: {"count": 0, "monto": 0.0, "anomalias": 0})
        for inv in self.invoices:
            rfc = inv.get("emisor_rfc") or inv.get("emisor_nombre") or "desconocido"
            nombre = inv.get("emisor_nombre") or rfc
            agg[rfc]["count"] += 1
            agg[rfc]["monto"] += _dec(inv.get("total"))
            agg[rfc]["nombre"] = nombre
        for a in self._anomalies:
            rfc = a.get("emisor_rfc")
            if rfc and rfc in agg:
                agg[rfc]["anomalias"] += 1
        proveedores = [{
            "rfc": rfc,
            "nombre": data["nombre"],
            "count": data["count"],
            "monto": round(data["monto"], 2),
            "promedio": round(data["monto"] / data["count"], 2) if data["count"] else 0.0,
            "anomalias": data["anomalias"],
        } for rfc, data in agg.items()]
        proveedores.sort(key=lambda p: p["monto"], reverse=True)
        return {"total_proveedores": len(proveedores),
                "proveedores": proveedores[:max(1, limit)]}

    def flujo_caja(self, months=6):
        """Ingresos vs egresos por mes + proyección del siguiente mes."""
        por_mes = defaultdict(lambda: {"ingresos": 0.0, "egresos": 0.0, "facturas": 0})
        for inv in self.invoices:
            mes = _periodo(inv.get("fecha"))
            tipo = str(inv.get("tipo") or "").upper()
            total = _dec(inv.get("total"))
            por_mes[mes]["facturas"] += 1
            if tipo == "I":
                por_mes[mes]["ingresos"] += total
            else:
                por_mes[mes]["egresos"] += total
        meses = sorted(por_mes.keys())
        flujo = [{
            "mes": m,
            "ingresos": round(por_mes[m]["ingresos"], 2),
            "egresos": round(por_mes[m]["egresos"], 2),
            "neto": round(por_mes[m]["ingresos"] - por_mes[m]["egresos"], 2),
            "facturas": por_mes[m]["facturas"],
        } for m in meses]

        # Proyección simple: promedio mensual de los `months` periodos previos.
        proyeccion = None
        if flujo:
            ventana = flujo[-months:]
            n = len(ventana) or 1
            prom_ing = sum(f["ingresos"] for f in ventana) / n
            prom_egr = sum(f["egresos"] for f in ventana) / n
            proyeccion = {
                "mes": _proximo_mes(meses[-1]),
                "ingresos_proyectados": round(prom_ing, 2),
                "egresos_proyectados": round(prom_egr, 2),
                "neto_proyectado": round(prom_ing - prom_egr, 2),
            }
        return {"flujo": flujo, "proyeccion": proyeccion}

    def alertas(self):
        """Facturas pendientes, anomalías críticas y conciliación incompleta."""
        alertas = []

        pendientes = [i for i in self.invoices
                      if _bool(i.get("requires_human_review"))
                      or str(i.get("erp_status") or "").lower() in ("pendiente", "error")
                      or str(i.get("status") or "").lower() not in ("procesado", "aprobado")]
        if pendientes:
            alertas.append({
                "tipo": "facturas_pendientes",
                "severity": "medium",
                "titulo": f"{len(pendientes)} factura(s) requieren atención",
                "detalle": "Facturas con revisión humana pendiente o póliza ERP "
                           "no confirmada.",
                "conteo": len(pendientes),
            })

        criticas = [a for a in self._anomalies
                    if a["severity"] in CRITICAL_SEVERITIES]
        if criticas:
            alertas.append({
                "tipo": "anomalias_criticas",
                "severity": "high",
                "titulo": f"{len(criticas)} anomalía(s) de severidad alta/crítica",
                "detalle": "Posibles duplicados u operaciones de riesgo requieren "
                           "revisión antes de registrar la póliza.",
                "conteo": len(criticas),
            })

        conc = self.reconciliation()
        if conc and (conc.get("pendientes_banco") or conc.get("pendientes_facturas")):
            alertas.append({
                "tipo": "conciliacion_incompleta",
                "severity": "medium",
                "titulo": "Conciliación bancaria incompleta",
                "detalle": f"{conc.get('pendientes_banco', 0)} movimientos de banco y "
                           f"{conc.get('pendientes_facturas', 0)} facturas sin pareja.",
                "conteo": conc.get("pendientes_banco", 0) + conc.get("pendientes_facturas", 0),
            })

        alertas.sort(key=lambda a: SEVERITY_RANK.get(a["severity"], 0), reverse=True)
        return {"total": len(alertas), "alertas": alertas}

    # ------------------------------------------------------------------ #
    # Exportación
    # ------------------------------------------------------------------ #
    def export_csv(self, report, filename=None):
        """Exporta un reporte (dict) a CSV.

        Devuelve el CSV como string. Si `filename` se indica, además lo
        escribe a disco y devuelve la ruta. Rows: usa la primera lista de
        dicts del reporte como tabla; si no hay, una tabla campo/valor.
        """
        rows = self._extract_rows(report)
        buf = io.StringIO()
        writer = csv.writer(buf)
        if rows and isinstance(rows[0], dict):
            header = list(rows[0].keys())
            writer.writerow(header)
            for r in rows:
                writer.writerow([r.get(h, "") for h in header])
        else:
            writer.writerow(["campo", "valor"])
            for k, v in report.items():
                if not isinstance(v, (list, dict)):
                    writer.writerow([k, v])
        text = buf.getvalue()
        if filename:
            with open(filename, "w", newline="", encoding="utf-8-sig") as fh:
                fh.write(text)
            return filename
        return text

    def export_pdf(self, report, title="Reporte gerencial", filename=None):
        """Exporta un reporte a HTML listo para imprimir/guardar como PDF."""
        rows = self._extract_rows(report)
        if rows and isinstance(rows[0], dict):
            header = list(rows[0].keys())
            thead = "".join(f"<th>{h}</th>" for h in header)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{r.get(h, '')}</td>" for h in header) + "</tr>"
                for r in rows)
        else:
            thead = "<th>Campo</th><th>Valor</th>"
            tbody = "".join(
                f"<tr><td>{k}</td><td>{v}</td></tr>"
                for k, v in report.items() if not isinstance(v, (list, dict)))

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:#111; background:#fff; margin:32px; }}
  h1 {{ color:#111; font-size:22px; border-bottom:2px solid #2563EB;
       padding-bottom:8px; }}
  .meta {{ color:#555; font-size:12px; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }}
  th,td {{ border:1px solid #ddd; padding:6px 8px; text-align:left; }}
  th {{ background:#2563EB; color:#fff; font-weight:600; }}
  tr:nth-child(even) {{ background:#f6f8fc; }}
  @media print {{ body {{ margin:0; }} }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">Generado por Likida AI Enterprise — Dashboard gerencial · {datetime.now().isoformat(timespec='minutes')}</div>
<table>
  <thead><tr>{thead}</tr></thead>
  <tbody>{tbody}</tbody>
</table>
</body>
</html>
"""
        if filename:
            with open(filename, "w", encoding="utf-8") as fh:
                fh.write(html)
            return filename
        return html

    @staticmethod
    def _extract_rows(report):
        """Primera lista de dicts del reporte (o [])."""
        if not isinstance(report, dict):
            return []
        for v in report.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        return []


def _proximo_mes(ultimo_mes):
    """Devuelve el 'YYYY-MM' siguiente a un 'YYYY-MM' dado."""
    if not ultimo_mes or len(ultimo_mes) != 7:
        return ""
    try:
        d = datetime.strptime(ultimo_mes, "%Y-%m")
        y, m = d.year, d.month
        m += 1
        if m > 12:
            m, y = 1, y + 1
        return f"{y:04d}-{m:02d}"
    except ValueError:
        return ""
