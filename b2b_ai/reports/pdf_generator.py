# -*- coding: utf-8 -*-
"""
pdf_generator.py — Generador de reportes PDF profesionales (reportlab).

`PDFGenerator` produce PDFs deterministicos, listos para impresión y
auditoría, con:
  - Logo del tenant (imagen embebida si está configurada; si no, un logo
    vectorial con las iniciales del despacho).
  - Gráficas vectoriales (barras y pastel) dibujadas con reportlab.graphics.
  - Tablas formateadas (estilo profesional, filas zebra, alineación).
  - Moneda MXN ("$1,234,567.89 MXN").
  - Fechas en formato MX ("31/07/2026").

Además de los PDFs, cada método puede renderizar la versión HTML (plantillas
con Chart.js en `templates/`) para exportación/impresión desde navegador
(pieza interactiva del dashboard).

Los métodos de "reporte" reciben datos ya agregados (dicts) o `tenant_id` +
`period` y tiran de la DB. Devuelven los bytes del PDF; `to_file()` los
persiste a disco.
"""
from __future__ import annotations

import io
import locale
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, Spacer, Table,
                                TableStyle, Image, HRFlowable, KeepTogether)
from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate
from reportlab.platypus.frames import Frame
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie

from b2b_ai.db.db import Database
from b2b_ai.services.report import generate_report
from b2b_ai.services import anomaly as anomaly_svc

# -------------------------------------------------------------------------- #
# Constantes
# -------------------------------------------------------------------------- #
BRAND = colors.HexColor("#2563EB")       # azul institucional
BRAND_DARK = colors.HexColor("#1D4ED8")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
ZEBRA = colors.HexColor("#F3F6FC")
RULE = colors.HexColor("#E5E7EB")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_DEFAULT_OUTPUT = Path(os.environ.get("B2B_REPORTS_DIR",
                                      "/tmp/b2b-reports")).expanduser()

_PALETTE = ["#2563EB", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
            "#06B6D4", "#F97316", "#EC4899", "#84CC16", "#6366F1"]

# Fecha "ahora" en MX para pie de página.
def _now_mx() -> str:
    return date.today().strftime("%d/%m/%Y")


def _dec(v: Any) -> float:
    """Convierte a float de forma tolerante (None/texto raro -> 0.0)."""
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def mxn(amount: Any) -> str:
    """Formatea un monto como moneda MXN: "$1,234,567.89 MXN"."""
    try:
        val = float(amount)
    except (TypeError, ValueError):
        val = 0.0
    neg = val < 0
    s = f"{abs(val):,.2f}"
    return f"${s} MXN" if not neg else f"-${s} MXN"


def fecha_mx(value: Any) -> str:
    """Convierte fecha a formato MX (dd/mm/aaaa). Acepta str/datetime/date."""
    if value is None or value == "":
        return ""
    s = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{d}/{mo}/{y}"
    m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m2:
        d, mo, y = m2.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    return s


def _periodo(fecha: Any) -> str:
    """Devuelve 'YYYY-MM' o 'sin-fecha'."""
    return str(fecha or "")[:7] or "sin-fecha"


def _html_escape(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# -------------------------------------------------------------------------- #
# Estilos de párrafo (reportlab)
# -------------------------------------------------------------------------- #
_ss = getSampleStyleSheet()
_S = {
    "title": ParagraphStyle("pt", parent=_ss["Title"], fontName="Helvetica-Bold",
                            fontSize=20, leading=24, textColor=INK,
                            spaceAfter=2),
    "subtitle": ParagraphStyle("ps", parent=_ss["Normal"], fontName="Helvetica",
                               fontSize=10, leading=13, textColor=MUTED,
                               spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=13, leading=16, textColor=BRAND_DARK,
                         spaceBefore=14, spaceAfter=6),
    "body": ParagraphStyle("body", parent=_ss["Normal"], fontName="Helvetica",
                           fontSize=10, leading=14, textColor=INK),
    "small": ParagraphStyle("small", parent=_ss["Normal"], fontName="Helvetica",
                            fontSize=8.5, leading=11, textColor=MUTED),
    "tablehead": ParagraphStyle("th", parent=_ss["Normal"], fontName="Helvetica-Bold",
                                fontSize=9.5, leading=12, textColor=colors.white),
    "tablecell": ParagraphStyle("td", parent=_ss["Normal"], fontName="Helvetica",
                                fontSize=9.5, leading=12, textColor=INK),
    "tablecell_right": ParagraphStyle("td_r", parent=_ss["Normal"],
                                      fontName="Helvetica", fontSize=9.5,
                                      leading=12, textColor=INK,
                                      alignment=TA_RIGHT),
    "tablecell_center": ParagraphStyle("td_c", parent=_ss["Normal"],
                                       fontName="Helvetica", fontSize=9.5,
                                       leading=12, textColor=INK,
                                       alignment=TA_CENTER),
    "kpi_label": ParagraphStyle("kpi_l", parent=_ss["Normal"], fontName="Helvetica",
                                fontSize=8, leading=10, textColor=MUTED),
    "kpi_value": ParagraphStyle("kpi_v", parent=_ss["Normal"], fontName="Helvetica-Bold",
                                fontSize=16, leading=19, textColor=INK),
    "center": ParagraphStyle("center", parent=_ss["Normal"], fontName="Helvetica",
                             fontSize=9.5, leading=12, alignment=TA_CENTER,
                             textColor=MUTED),
}


def _pd(text, style="body"):
    return Paragraph(text, _S[style])


def _styled_table(headers: List[str], rows: List[List[Any]],
                  col_widths: Optional[List[float]] = None,
                  align: Optional[Dict[int, str]] = None) -> Table:
    """Tabla profesional con cabecera azul y filas zebra.

    La alineación por columna se aplica con estilos de párrafo dedicados
    (reportlab rechaza la directiva ALIGN sobre celdas tipo Paragraph).
    """
    # Mapa de estilo de celda según columna (para alineación).
    cell_styles: Dict[int, str] = {}
    if align:
        for col, a in align.items():
            if a == "right":
                cell_styles[col] = "tablecell_right"
            elif a == "center":
                cell_styles[col] = "tablecell_center"
    head_cells = [_pd(h, "tablehead") for h in headers]
    data = [head_cells]
    for r in rows:
        data.append([_pd("" if c is None else str(c),
                         cell_styles.get(ci, "tablecell"))
                     for ci, c in enumerate(r)])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.8, BRAND),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    t.setStyle(TableStyle(style))
    return t


def _kpi_card(label: str, value: str) -> Table:
    """Tarjeta KPI compacta (etiqueta + valor grande)."""
    t = Table([[_pd(label, "kpi_label")], [_pd(value, "kpi_value")]],
              colWidths=[46 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFBFF")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _bar_chart(labels: List[str], values: List[float], title: str = "",
               width: float = 180 * mm, height: float = 70 * mm) -> Drawing:
    d = Drawing(width, height)
    if title:
        d.add(String(width / 2, height - 8 * mm, title,
                     fontName="Helvetica-Bold", fontSize=10,
                     fillColor=INK, textAnchor="middle"))
        top = height - 14 * mm
    else:
        top = height - 4 * mm
    bc = VerticalBarChart()
    bc.x = 28 * mm
    bc.y = 8 * mm
    bc.width = width - 42 * mm
    bc.height = top - 14 * mm
    bc.data = [values]
    bc.categoryAxis.categoryNames = [str(l) for l in labels]
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 8
    bc.categoryAxis.labels.angle = 0
    bc.valueAxis.valueMin = 0
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 8
    bc.bars[0].fillColor = BRAND
    bc.bars[0].strokeColor = BRAND
    bc.barLabelFormat = "%.0f"
    bc.barLabels.fontName = "Helvetica"
    bc.barLabels.fontSize = 7
    bc.barLabels.fillColor = MUTED
    bc.barWidth = max(3.0, (bc.width / max(1, len(values))) * 0.55)
    d.add(bc)
    return d


def _pie_chart(labels: List[str], values: List[float], title: str = "",
               width: float = 180 * mm, height: float = 70 * mm) -> Drawing:
    d = Drawing(width, height)
    if title:
        d.add(String(width / 2, height - 8 * mm, title,
                     fontName="Helvetica-Bold", fontSize=10,
                     fillColor=INK, textAnchor="middle"))
        top = height - 14 * mm
    else:
        top = height - 4 * mm
    pie = Pie()
    pie.x = 30 * mm
    pie.y = 10 * mm
    pie.width = min(top - 20 * mm, 52 * mm)
    pie.height = min(top - 20 * mm, 52 * mm)
    pie.data = [max(0.0, float(v)) for v in values]
    pie.labels = [str(l) for l in labels]
    pie.slices.strokeWidth = 1
    pie.slices.strokeColor = colors.white
    for i, color in enumerate(_PALETTE):
        pie.slices[i].fillColor = colors.HexColor(color)
    pie.sideLabels = 0
    pie.simpleLabels = 0
    # Leyenda manual a la derecha.
    lx = 52 * mm + 18 * mm
    ly = top - 8 * mm
    for i, lab in enumerate(labels):
        y = ly - i * 6 * mm
        d.add(Rect(lx, y, 4 * mm, 4 * mm, fillColor=colors.HexColor(
            _PALETTE[i % len(_PALETTE)]), strokeColor=None))
        d.add(String(lx + 6 * mm, y - 1.4 * mm, str(lab),
                     fontName="Helvetica", fontSize=8, fillColor=INK))
    d.add(pie)
    return d


# -------------------------------------------------------------------------- #
# PDFGenerator
# -------------------------------------------------------------------------- #
class PDFGenerator:
    """Genera reportes PDF profesionales.

    Args:
        db:            capa de datos (inyectable para tests). Default Database().
        templates_dir: carpeta con las plantillas HTML (Chart.js).
        output_dir:    carpeta por defecto para to_file().
    """

    def __init__(self, db: Optional[Database] = None,
                 templates_dir: Optional[Path] = None,
                 output_dir: Optional[Path] = None):
        self.db = db or Database()
        self.templates_dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR
        self.output_dir = Path(output_dir) if output_dir else _DEFAULT_OUTPUT

    # ------------------------------------------------------------------ #
    # Formato público
    # ------------------------------------------------------------------ #
    @staticmethod
    def fmt_mxn(amount: Any) -> str:
        return mxn(amount)

    @staticmethod
    def fmt_fecha_mx(value: Any) -> str:
        return fecha_mx(value)

    # ------------------------------------------------------------------ #
    # Tenant / logo
    # ------------------------------------------------------------------ #
    def tenant(self, tenant_id: Optional[int]) -> Dict[str, Any]:
        """Datos del tenant: {id, name, rfc, logo_path, initials}."""
        name, rfc, logo = "Despacho Contable", "", None
        if tenant_id is not None:
            try:
                row = next((t for t in self.db.list_tenants()
                            if t["id"] == tenant_id), None)
                if row:
                    name = row.get("name") or name
                    rfc = row.get("rfc") or ""
            except Exception:  # noqa: BLE001 — best effort para header
                pass
            # Logo desde config del tenant o env.
            try:
                logo_cfg = self.db.get_tenant_config(tenant_id, "logo_path", "")
                if logo_cfg and Path(logo_cfg).is_file():
                    logo = str(Path(logo_cfg))
            except Exception:  # noqa: BLE001
                logo = None
        env_logo = os.environ.get("B2B_REPORTS_LOGO")
        if not logo and env_logo and Path(env_logo).is_file():
            logo = env_logo
        initials = "".join(w[0] for w in re.findall(r"\b\w", name))[:3].upper() \
            or "B&B"
        return {"id": tenant_id, "name": name, "rfc": rfc,
                "logo_path": logo, "initials": initials}

    def _tenant_from(self, tenant: Any, tenant_id: Optional[int]) -> Dict[str, Any]:
        """Normaliza: si se pasó dict de tenant lo usa; si no, resuelve por id."""
        if isinstance(tenant, dict):
            t = dict(tenant)
            t.setdefault("initials", "B&B")
            t.setdefault("name", "Despacho Contable")
            t.setdefault("rfc", "")
            return t
        return self.tenant(tenant_id)

    def _logo_flowable(self, tenant: Dict[str, Any]):
        """Flujo de logo: imagen embebida o logo vectorial de iniciales."""
        if tenant.get("logo_path"):
            try:
                return Image(tenant["logo_path"], width=16 * mm,
                             height=16 * mm, preserveAspectRatio=True)
            except Exception:  # noqa: BLE001 — imagen corrupta → fallback
                pass
        # Logo vectorial con iniciales.
        d = Drawing(16 * mm, 16 * mm)
        d.add(Rect(0, 0, 16 * mm, 16 * mm, rx=3 * mm, ry=3 * mm,
                   fillColor=BRAND, strokeColor=None))
        initials = tenant.get("initials") or "B&B"
        d.add(String(16 * mm / 2, 16 * mm / 2 - 3.2 * mm, initials,
                     fontName="Helvetica-Bold", fontSize=11,
                     fillColor=colors.white, textAnchor="middle"))
        return d

    # ------------------------------------------------------------------ #
    # Documento base
    # ------------------------------------------------------------------ #
    def _new_doc(self, title: str, tenant: Dict[str, Any],
                 subtitle: str = "") -> "BaseDocTemplate":
        """Crea un BaseDocTemplate A4 con plantilla de página (header/footer)."""
        buf = io.BytesIO()
        bt = BaseDocTemplate(
            buf, pagesize=A4,
            leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=30 * mm, bottomMargin=20 * mm,
            title=f"{title} — {tenant.get('name', '')}",
            author="B&B AI",
        )
        frame = Frame(bt.leftMargin, bt.bottomMargin, bt.width, bt.height,
                      id="main")
        t_name = tenant.get("name", "")
        t_rfc = tenant.get("rfc", "")
        t_logo = tenant.get("logo_path")
        t_initials = tenant.get("initials") or "B&B"

        def _draw_initials(cv, x, y):
            cv.setFillColor(BRAND)
            cv.roundRect(x, y - 16 * mm, 16 * mm, 16 * mm, 3, fill=1, stroke=0)
            cv.setFillColor(colors.white)
            cv.setFont("Helvetica-Bold", 11)
            cv.drawCentredString(x + 8 * mm, y - 12 * mm, t_initials[:3])

        def _decorate(canvas, doc_obj):
            canvas.saveState()
            w, h = A4
            # Logo: imagen embebida o iniciales.
            if t_logo and Path(t_logo).is_file():
                try:
                    from reportlab.lib.utils import ImageReader
                    ir = ImageReader(t_logo)
                    iw, ih = ir.getSize()
                    draw_w = 12 * mm
                    draw_h = draw_w * ih / max(1, iw)
                    if draw_h > 14 * mm:
                        draw_h, draw_w = 14 * mm, 14 * mm * iw / max(1, ih)
                    canvas.drawImage(t_logo, 20 * mm, h - 20 * mm - draw_h,
                                     width=draw_w, height=draw_h,
                                     preserveAspectRatio=True, mask="auto")
                except Exception:  # noqa: BLE001
                    _draw_initials(canvas, 20 * mm, h - 20 * mm)
            else:
                _draw_initials(canvas, 20 * mm, h - 20 * mm)
            # Nombre + RFC del tenant.
            canvas.setFillColor(INK)
            canvas.setFont("Helvetica-Bold", 10)
            canvas.drawString(34 * mm, h - 20 * mm, _html_escape(t_name)[:60])
            if t_rfc:
                canvas.setFillColor(MUTED)
                canvas.setFont("Helvetica", 8)
                canvas.drawString(34 * mm, h - 25 * mm, f"RFC {t_rfc}")
            # Título del reporte (derecha).
            canvas.setFillColor(MUTED)
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(w - 20 * mm, h - 20 * mm, title)
            # Línea divisoria del header.
            canvas.setStrokeColor(BRAND)
            canvas.setLineWidth(1.2)
            canvas.line(20 * mm, h - 30 * mm, w - 20 * mm, h - 30 * mm)
            # Footer: generado + página.
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.6)
            canvas.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
            canvas.setFillColor(MUTED)
            canvas.setFont("Helvetica", 8)
            foot = f"Generado por B&B AI · {_now_mx()}  ·  {subtitle}"[:110]
            canvas.drawString(20 * mm, 10 * mm, foot)
            canvas.drawRightString(w - 20 * mm, 10 * mm, f"Página {doc_obj.page}")
            canvas.restoreState()

        bt.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                          onPage=_decorate)])
        bt._buf = buf
        return bt

    def _story_title(self, story, title, subtitle=""):
        story.append(Paragraph(_html_escape(title), _S["title"]))
        if subtitle:
            story.append(Paragraph(_html_escape(subtitle), _S["subtitle"]))
        story.append(HRFlowable(width="100%", thickness=1, color=BRAND,
                                spaceBefore=4, spaceAfter=8))

    # ------------------------------------------------------------------ #
    # Renderizado PDF
    # ------------------------------------------------------------------ #
    def _write(self, doc, story) -> bytes:
        """Construye el PDF con el story y devuelve los bytes."""
        doc.build(story)
        return doc._buf.getvalue()


    # ------------------------------------------------------------------ #
    # Reportes
    # ------------------------------------------------------------------ #
    def invoice_report(self, invoice_data: Dict[str, Any],
                       tenant: Any = None, tenant_id: Optional[int] = None) -> bytes:
        """PDF de una factura individual (CFDI)."""
        inv = invoice_data or {}
        ten = self._tenant_from(tenant, tenant_id)
        doc = self._new_doc("Factura", ten, subtitle=f"Folio fiscal {inv.get('folio_fiscal', '')}")
        story = []
        self._story_title(
            story, f"Factura {inv.get('folio', '') or inv.get('id', '')}",
            f"Emisor: {inv.get('emisor_nombre', inv.get('emisor_rfc', ''))}   "
            f"·   Fecha: {fecha_mx(inv.get('fecha'))}")
        # Monto destacado.
        kpi = _kpi_card("TOTAL", mxn(inv.get("total")))
        story.append(KeepTogether([kpi, Spacer(1, 4)]))
        story.append(Spacer(1, 6))

        rows = [
            ("Folio fiscal", inv.get("folio_fiscal", "—")),
            ("Serie / Folio", f"{inv.get('serie', '')} {inv.get('folio', '')}".strip()),
            ("Fecha de emisión", fecha_mx(inv.get("fecha"))),
            ("Tipo", inv.get("tipo", "—")),
            ("Emisor RFC", inv.get("emisor_rfc", "—")),
            ("Emisor", inv.get("emisor_nombre", "—")),
            ("Receptor RFC", inv.get("receptor_rfc", "—")),
            ("Categoría", inv.get("categoria", "—")),
            ("Moneda", inv.get("moneda", "MXN")),
        ]
        story.append(_pd("Datos del comprobante", "h2"))
        story.append(_styled_table(
            ["Campo", "Valor"],
            [[_html_escape(k), _html_escape(v)] for k, v in rows],
            col_widths=[55 * mm, 120 * mm]))
        story.append(Spacer(1, 8))
        story.append(_pd("Importes", "h2"))
        story.append(_styled_table(
            ["Concepto", "Monto"],
            [["Subtotal", mxn(inv.get("subtotal"))],
             ["IVA", mxn(inv.get("iva"))],
             ["TOTAL", mxn(inv.get("total"))]],
            col_widths=[130 * mm, 45 * mm], align={1: "right"}))
        if inv.get("descripcion"):
            story.append(Spacer(1, 8))
            story.append(_pd(f"<b>Descripción:</b> {_html_escape(inv['descripcion'])}"))
        if inv.get("erp_poliza"):
            story.append(Spacer(1, 6))
            story.append(_pd(f"<b>Póliza ERP:</b> {_html_escape(inv['erp_poliza'])}", "small"))
        return self._write(doc, story)

    def monthly_summary(self, tenant_id: int, month: str,
                        tenant: Any = None) -> bytes:
        """Resumen ejecutivo mensual del tenant (facturas + anomalías)."""
        ten = self._tenant_from(tenant, tenant_id)
        invoices = self.db.list_invoices(tenant_id=tenant_id)
        rows = [i for i in invoices if _periodo(i.get("fecha")) == month]
        rep = generate_report(rows)
        anomalies = []
        for inv in rows:
            for a in anomaly_svc.detect_anomalies(inv, [x for x in rows if x is not inv]):
                a = dict(a)
                a.update({"invoice_id": inv.get("id"),
                          "emisor_rfc": inv.get("emisor_rfc", ""),
                          "fecha": inv.get("fecha", ""),
                          "monto": _dec(inv.get("total"))})
                anomalies.append(a)
        sev = {}
        for a in anomalies:
            sev[a["severity"]] = sev.get(a["severity"], 0) + 1

        doc = self._new_doc("Resumen Mensual", ten,
                            subtitle=f"Periodo {month}")
        story = []
        mes_nombre = self._mes_nombre(month)
        self._story_title(story, f"Resumen mensual — {mes_nombre} {month[:4]}",
                          f"Tenant: {ten['name']} · Periodo {month}")
        # KPIs.
        kpis = Table([[
            _kpi_card("Facturas", str(rep["facturas"])),
            _kpi_card("Monto total", mxn(rep["total"])),
            _kpi_card("IVA", mxn(rep["iva"])),
            _kpi_card("Anomalías", str(sum(sev.values()))),
        ]], colWidths=[46 * mm] * 4)
        kpis.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        story.append(kpis)
        story.append(Spacer(1, 6))

        if rows:
            cats = sorted(rep["por_categoria"].items(),
                          key=lambda kv: _dec(kv[1]["total"]), reverse=True)
            story.append(_pd("Desglose por categoría", "h2"))
            story.append(_styled_table(
                ["Categoría", "Facturas", "Monto"],
                [[_html_escape(c), str(d["count"]), mxn(d["total"])]
                 for c, d in cats],
                col_widths=[120 * mm, 35 * mm, 60 * mm], align={1: "center", 2: "right"}))
            story.append(Spacer(1, 6))
            if cats:
                story.append(_bar_chart(
                    [c for c, _ in cats][:10],
                    [_dec(d["total"]) for _, d in cats][:10],
                    "Monto por categoría"))
            story.append(Spacer(1, 6))
            if anomalies:
                story.append(_pd("Anomalías detectadas", "h2"))
                story.append(self._anomaly_table(anomalies))
                sev_list = [k for k in ("low", "medium", "high", "critical")
                            if sev.get(k)]
                if sev_list:
                    story.append(_pie_chart(
                        [f"{k} ({sev.get(k)})" for k in sev_list],
                        [sev[k] for k in sev_list], "Anomalías por severidad"))
        else:
            story.append(_pd("Sin facturas registradas en el periodo.", "body"))
        return self._write(doc, story)

    def reconciliation_report(self, reconciliation_data: Dict[str, Any],
                              tenant: Any = None,
                              tenant_id: Optional[int] = None) -> bytes:
        """PDF del estado de conciliación bancaria."""
        rep = reconciliation_data or {}
        ten = self._tenant_from(tenant, tenant_id)
        doc = self._new_doc("Conciliación Bancaria", ten,
                            subtitle=f"Periodo {rep.get('periodo', '—')}")
        story = []
        self._story_title(story, "Conciliación bancaria",
                          f"Tenant: {ten['name']} · "
                          f"Tasa de conciliación: {rep.get('tasa_conciliacion', 0)}%")
        kpis = Table([[
            _kpi_card("Conciliados", str(rep.get("conciliados", 0))),
            _kpi_card("Monto conciliado", mxn(rep.get("monto_conciliado"))),
            _kpi_card("Pend. banco", str(rep.get("pendientes_banco", 0))),
            _kpi_card("Pend. facturas", str(rep.get("pendientes_facturas", 0))),
        ]], colWidths=[46 * mm] * 4)
        kpis.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        story.append(kpis)
        story.append(Spacer(1, 6))
        story.append(_pd("Resumen", "h2"))
        story.append(_styled_table(
            ["Métrica", "Valor"],
            [["Facturas", rep.get("facturas", 0)],
             ["Movimientos banco", rep.get("movimientos_banco", 0)],
             ["Conciliados", rep.get("conciliados", 0)],
             ["Monto banco total", mxn(rep.get("monto_banco_total"))],
             ["Monto pendiente banco", mxn(rep.get("monto_pendiente_banco"))],
             ["Monto pendiente facturas", mxn(rep.get("monto_pendiente_facturas"))],
             ["Tasa de conciliación", f"{rep.get('tasa_conciliacion', 0)}%"]],
            col_widths=[110 * mm, 65 * mm], align={1: "right"}))
        matched = rep.get("matched", [])
        if matched:
            story.append(_pd("Movimientos conciliados", "h2"))
            story.append(_styled_table(
                ["Fecha banco", "Monto", "Referencia"],
                [[fecha_mx(m.get("fecha_banco", m.get("fecha"))),
                  mxn(m.get("monto")),
                  _html_escape(m.get("ref_banco", m.get("folio_fiscal", "—")))]
                 for m in matched[:50]],
                col_widths=[45 * mm, 45 * mm, 85 * mm],
                align={1: "right"}))
        um = rep.get("unmatched_bank", [])
        if um:
            story.append(_pd("Movimientos bancarios sin conciliar", "h2"))
            story.append(_styled_table(
                ["Fecha", "Monto", "Descripción"],
                [[fecha_mx(b.get("fecha")), mxn(b.get("monto")),
                  _html_escape(b.get("descripcion", "—"))] for b in um[:50]],
                col_widths=[45 * mm, 45 * mm, 85 * mm], align={1: "right"}))
        return self._write(doc, story)

    def anomaly_report(self, anomalies: List[Dict[str, Any]],
                       tenant: Any = None,
                       tenant_id: Optional[int] = None) -> bytes:
        """PDF con las anomalías detectadas, agrupadas por severidad."""
        items = list(anomalies or [])
        sev = {}
        for a in items:
            sev[a.get("severity", "low")] = sev.get(a.get("severity", "low"), 0) + 1
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        items.sort(key=lambda a: rank.get(a.get("severity", "low"), 0),
                   reverse=True)
        ten = self._tenant_from(tenant, tenant_id)
        doc = self._new_doc("Reporte de Anomalías", ten,
                            subtitle=f"{len(items)} anomalías")
        story = []
        self._story_title(story, "Reporte de anomalías",
                          f"Tenant: {ten['name']} · {len(items)} anomalía(s)")
        kpis = Table([[
            _kpi_card("Total", str(len(items))),
            _kpi_card("Críticas", str(sev.get("critical", 0))),
            _kpi_card("Altas", str(sev.get("high", 0))),
            _kpi_card("Medias", str(sev.get("medium", 0))),
        ]], colWidths=[46 * mm] * 4)
        kpis.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        story.append(kpis)
        story.append(Spacer(1, 6))
        if items:
            sev_list = [k for k in ("critical", "high", "medium", "low") if sev.get(k)]
            if sev_list:
                story.append(_pie_chart(
                    [f"{k} ({sev[k]})" for k in sev_list],
                    [sev[k] for k in sev_list], "Distribución por severidad"))
                story.append(Spacer(1, 6))
            story.append(_pd("Detalle", "h2"))
            story.append(_styled_table(
                ["Severidad", "Tipo", "Fecha", "Monto", "Descripción"],
                [[a.get("severity", ""), _html_escape(a.get("tipo", "")),
                  fecha_mx(a.get("fecha")), mxn(a.get("monto")),
                  _html_escape((a.get("descripcion") or "")[:60])]
                 for a in items],
                col_widths=[22 * mm, 30 * mm, 28 * mm, 38 * mm, 57 * mm],
                align={3: "right"}))
        else:
            story.append(_pd("No se detectaron anomalías.", "body"))
        return self._write(doc, story)

    def tax_report(self, tenant_id: int, period: str,
                   tenant: Any = None) -> bytes:
        """Reporte fiscal del periodo: IVA, subtotales, tipo I/E por categoría."""
        ten = self._tenant_from(tenant, tenant_id)
        invoices = self.db.list_invoices(tenant_id=tenant_id)
        rows = [i for i in invoices if _periodo(i.get("fecha")) == period]
        subtotal = sum(_dec(i.get("subtotal")) for i in rows)
        iva = sum(_dec(i.get("iva")) for i in rows)
        total = sum(_dec(i.get("total")) for i in rows)
        por_tipo = {}
        for i in rows:
            t = str(i.get("tipo") or "?")
            por_tipo[t] = por_tipo.get(t, 0.0) + _dec(i.get("total"))
        cats = {}
        for i in rows:
            c = i.get("categoria") or "sin-categoría"
            cats[c] = cats.get(c, 0.0) + _dec(i.get("total"))

        doc = self._new_doc("Reporte Fiscal", ten, subtitle=f"Periodo {period}")
        story = []
        self._story_title(story, f"Reporte fiscal — {period}",
                          f"Tenant: {ten['name']} · RFC {ten['rfc'] or '—'}")
        kpis = Table([[
            _kpi_card("Facturas", str(len(rows))),
            _kpi_card("Subtotal", mxn(subtotal)),
            _kpi_card("IVA", mxn(iva)),
            _kpi_card("Total", mxn(total)),
        ]], colWidths=[46 * mm] * 4)
        kpis.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        story.append(kpis)
        story.append(Spacer(1, 6))
        story.append(_pd("Importes del periodo", "h2"))
        story.append(_styled_table(
            ["Concepto", "Monto"],
            [["Subtotal", mxn(subtotal)], ["IVA trasladado", mxn(iva)],
             ["TOTAL", mxn(total)]],
            col_widths=[130 * mm, 45 * mm], align={1: "right"}))
        if por_tipo:
            story.append(Spacer(1, 4))
            story.append(_pd("Por tipo de comprobante", "h2"))
            story.append(_styled_table(
                ["Tipo", "Monto"],
                [[_html_escape(str(k)), mxn(v)] for k, v in por_tipo.items()],
                col_widths=[130 * mm, 45 * mm], align={1: "right"}))
        if cats:
            story.append(Spacer(1, 4))
            story.append(_pd("Por categoría", "h2"))
            story.append(_styled_table(
                ["Categoría", "Monto"],
                [[_html_escape(c), mxn(v)]
                 for c, v in sorted(cats.items(), key=lambda kv: kv[1], reverse=True)],
                col_widths=[130 * mm, 45 * mm], align={1: "right"}))
            story.append(Spacer(1, 6))
            story.append(_bar_chart(
                [c for c, _ in sorted(cats.items(), key=lambda kv: kv[1],
                                      reverse=True)[:10]],
                [v for _, v in sorted(cats.items(), key=lambda kv: kv[1],
                                      reverse=True)[:10]],
                "IVA/Total por categoría"))
        if not rows:
            story.append(_pd("Sin facturas registradas en el periodo.", "body"))
        return self._write(doc, story)

    def custom_report(self, data: Dict[str, Any],
                      template: Optional[str] = None,
                      title: str = "Reporte", tenant: Any = None,
                      tenant_id: Optional[int] = None) -> bytes:
        """PDF genérico a partir de un dict `data`.

        `data` puede incluir:
          - `title` / `subtitle`: cabecera.
          - `summary`: dict de pares clave/valor (tabla campo-valor).
          - `table`: dict con {headers: [...], rows: [[...]]} para una tabla.
          - `chart`: dict con {labels: [...], values: [...]} (barras).
          Cualquier otra clave plana se lista como "dato".
        """
        data = data or {}
        title = data.get("title") or title
        ten = self._tenant_from(tenant, tenant_id)
        doc = self._new_doc(title, ten, subtitle=data.get("subtitle", ""))
        story = []
        self._story_title(story, title, data.get("subtitle", ""))
        summary = data.get("summary") or {}
        table = data.get("table") or {}
        chart = data.get("chart") or {}
        flat = {k: v for k, v in data.items()
                if k not in ("title", "subtitle", "summary", "table", "chart")
                and not isinstance(v, (list, dict))}
        if summary or flat:
            rows = [[_html_escape(k), _html_escape(v)]
                    for k, v in list(summary.items()) + list(flat.items())]
            story.append(_pd("Datos", "h2"))
            story.append(_styled_table(["Campo", "Valor"], rows,
                                       col_widths=[70 * mm, 105 * mm]))
        if table:
            headers = table.get("headers") or []
            trows = table.get("rows") or []
            story.append(Spacer(1, 4))
            story.append(_styled_table(headers, [[_html_escape(c) for c in r]
                                                 for r in trows]))
        if chart:
            labels = chart.get("labels") or []
            values = [_dec(v) for v in (chart.get("values") or [])]
            if labels and values:
                story.append(Spacer(1, 6))
                story.append(_bar_chart(labels, values, chart.get("title", "")))
        if not (summary or flat or table or chart):
            story.append(_pd("Sin datos para el reporte.", "body"))
        return self._write(doc, story)

    # ------------------------------------------------------------------ #
    # HTML (Chart.js) — exportación/impresión desde navegador
    # ------------------------------------------------------------------ #
    def render_html(self, template_name: str, data: Dict[str, Any],
                    tenant: Any = None, tenant_id: Optional[int] = None) -> str:
        """Renderiza una plantilla HTML (templates/) embebiendo `data` como
        JSON para Chart.js. Devuelve el HTML listo para abrir/imprimir."""
        tpl = self.templates_dir / f"{template_name}.html"
        if not tpl.is_file():
            raise FileNotFoundError(f"Plantilla no existe: {tpl}")
        ten = self._tenant_from(tenant, tenant_id)
        import json
        data_json = json.dumps(data, ensure_ascii=False, default=str) \
            .replace("<", "\\u003c").replace(">", "\\u003e")
        # Logo: imagen embebida (base64) o iniciales del tenant.
        logo_html = _html_escape(ten.get("initials", "B&B"))
        lp = ten.get("logo_path")
        if lp and Path(lp).is_file():
            try:
                import base64, mimetypes
                mime = mimetypes.guess_type(lp)[0] or "image/png"
                b64 = base64.b64encode(Path(lp).read_bytes()).decode()
                logo_html = f'<img src="data:{mime};base64,{b64}" alt="logo">'
            except Exception:  # noqa: BLE001
                logo_html = _html_escape(ten.get("initials", "B&B"))
        html = tpl.read_text(encoding="utf-8")
        return (html
                .replace("{{LOGO_HTML}}", logo_html)
                .replace("{{DATA}}", data_json)
                .replace("{{TITLE}}", _html_escape(data.get("title", "Reporte")))
                .replace("{{TENANT_NAME}}", _html_escape(ten.get("name", "")))
                .replace("{{TENANT_RFC}}", _html_escape(ten.get("rfc", "")))
                .replace("{{TENANT_INITIALS}}", _html_escape(ten.get("initials", "B&B")))
                .replace("{{LOGO_PATH}}", _html_escape(ten.get("logo_path") or ""))
                .replace("{{GENERATED}}", _now_mx()))

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def to_file(self, pdf_bytes: bytes, filename: str,
                out_dir: Optional[Path] = None) -> Path:
        """Persiste bytes de PDF a disco y devuelve la ruta."""
        out_dir = Path(out_dir) if out_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename
        path.write_bytes(pdf_bytes)
        return path

    def _anomaly_table(self, anomalies: List[Dict[str, Any]]):
        return _styled_table(
            ["Severidad", "Tipo", "Monto", "Detalle"],
            [[a.get("severity", ""), _html_escape(a.get("tipo", "")),
              mxn(a.get("monto")),
              _html_escape((a.get("descripcion") or a.get("detalle") or "")[:55])]
             for a in anomalies],
            col_widths=[24 * mm, 30 * mm, 38 * mm, 83 * mm],
            align={2: "right"})

    @staticmethod
    def _mes_nombre(month: str) -> str:
        names = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                 "Diciembre"]
        try:
            return names[int(month[5:7]) - 1]
        except (ValueError, IndexError):
            return month
