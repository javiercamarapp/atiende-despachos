# -*- coding: utf-8 -*-
"""
pdf_report.py — Generación de reportes PDF de cobranza.

Genera PDFs profesionales para:
  - Reporte de aging (antigüedad de la cartera)
  - Proyección de cobro esperado
  - Resumen ejecutivo de cobranza

Usa reportlab para generar PDFs nativos. Los reportes incluyen:
  - Encabezado con logo/branding del tenant
  - Tablas de datos con formato monetario MXN
  - Gráficas de barras para distribución por bucket
  - Alertas y indicadores destacados
  - Pie de página con fecha de generación

Uso típico:
    from b2b_ai.collections.pdf_report import generate_aging_pdf
    pdf_bytes = generate_aging_pdf(invoices, tenant_id=1)
    # pdf_bytes es un PDF listo para enviar como Response
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from b2b_ai.collections.models import AgingReportResponse
from b2b_ai.services.collections import age_bucket, days_overdue
from b2b_ai.services.collections_report import (
    aging_report,
    projection,
    summary,
)
from b2b_ai.services.collections_templates import format_monto


# --------------------------------------------------------------------------- #
# Generadores PDF
# --------------------------------------------------------------------------- #

def generate_aging_pdf(invoices: List[Dict[str, Any]],
                       tenant_id: Optional[int] = None,
                       today: Optional[date] = None) -> bytes:
    """Genera un PDF con el reporte de aging de la cartera.

    Incluye tabla de buckets (0-30, 31-60, 61-90, 90+), lista de facturas
    y distribución por monto.
    """
    today = today or date.today()
    data = aging_report(invoices, today=today)

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        # Fallback: generar un reporte HTML simple como texto
        return _aging_html_fallback(data, tenant_id).encode("utf-8")

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Título
    title_style = ParagraphStyle(
        "Title2", parent=styles["Title"], fontSize=18, spaceAfter=12)
    elements.append(Paragraph(
        "Reporte de Antigüedad de Cartera", title_style))
    elements.append(Paragraph(
        f"Fecha: {today.strftime('%d/%m/%Y')} | "
        f"Tenant: {tenant_id or 'N/A'}",
        styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # Resumen de buckets
    elements.append(Paragraph(
        "<b>Resumen por Antigüedad</b>", styles["Heading2"]))
    bucket_data = [["Bucket", "Facturas", "Monto"]]
    for bucket, vals in data["buckets"].items():
        bucket_data.append([
            bucket,
            str(vals["count"]),
            format_monto(float(vals["monto"])),
        ])
    bucket_data.append([
        "TOTAL",
        str(data["total_count"]),
        format_monto(float(data["total_monto"])),
    ])

    t = Table(bucket_data, colWidths=[2 * inch, 1.5 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecf0f1")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3 * inch))

    # Top facturas
    elements.append(Paragraph(
        "<b>Top Facturas por Monto</b>", styles["Heading2"]))
    inv_data = [["ID", "Empresa", "Monto", "Días Vencido", "Bucket", "Score"]]
    top = sorted(data["invoices"],
                 key=lambda i: float(str(i.get("monto", 0)).replace(",", "")),
                 reverse=True)[:20]
    for inv in top:
        inv_data.append([
            inv.get("factura_id", ""),
            inv.get("nombre_empresa", "")[:30],
            format_monto(float(str(inv.get("monto", 0)).replace(",", ""))),
            str(inv.get("dias_vencido", 0)),
            inv.get("bucket", ""),
            f"{inv.get('score', 0):.2f}",
        ])

    t2 = Table(inv_data, colWidths=[1 * inch, 1.8 * inch, 1.2 * inch,
                                     1 * inch, 0.8 * inch, 0.8 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8f9fa")]),
    ]))
    elements.append(t2)

    # Pie de página
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(
        f"<i>Generado automáticamente el {datetime.utcnow().isoformat()} "
        f"por Likida AI Enterprise — Cobranza Automatizada</i>",
        styles["Normal"]))

    doc.build(elements)
    return buf.getvalue()


def generate_projection_pdf(invoices: List[Dict[str, Any]],
                            tenant_id: Optional[int] = None,
                            today: Optional[date] = None) -> bytes:
    """Genera un PDF con la proyección de cobro esperado."""
    today = today or date.today()
    data = projection(invoices, today=today)

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        return _projection_html_fallback(data, tenant_id).encode("utf-8")

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(
        "Proyección de Cobro Esperado", styles["Title"]))
    elements.append(Paragraph(
        f"Fecha: {today.strftime('%d/%m/%Y')} | Tenant: {tenant_id or 'N/A'}",
        styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # KPIs
    kpi_data = [
        ["Cartera Total", "Esperado", "Tasa de Recuperación"],
        [format_monto(float(data["total_cartera"])),
         format_monto(float(data["total_esperado"])),
         f"{data['tasa_recuperacion_esperada']:.1f}%"],
    ]
    t = Table(kpi_data, colWidths=[2.2 * inch, 2.2 * inch, 2.2 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3 * inch))

    # Por bucket
    elements.append(Paragraph(
        "<b>Proyección por Antigüedad</b>", styles["Heading2"]))
    bucket_data = [["Bucket", "Monto Total", "Esperado"]]
    for bucket, vals in data["por_bucket"].items():
        bucket_data.append([
            bucket,
            format_monto(float(vals["monto_total"])),
            format_monto(float(vals["esperado"])),
        ])
    t2 = Table(bucket_data, colWidths=[2 * inch, 2.5 * inch, 2.5 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t2)

    # Por score
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(
        "<b>Proyección por Rango de Score</b>", styles["Heading2"]))
    score_data = [["Rango", "Facturas", "Monto Total", "Esperado"]]
    for rng, vals in data["por_score"].items():
        score_data.append([
            rng.capitalize(),
            str(vals["count"]),
            format_monto(float(vals["monto_total"])),
            format_monto(float(vals["esperado"])),
        ])
    t3 = Table(score_data, colWidths=[1.5 * inch, 1.2 * inch,
                                       2 * inch, 2 * inch])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8e44ad")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t3)

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(
        f"<i>Generado el {datetime.utcnow().isoformat()} por Likida AI Enterprise</i>",
        styles["Normal"]))

    doc.build(elements)
    return buf.getvalue()


def generate_summary_pdf(invoices: List[Dict[str, Any]],
                         tenant_id: Optional[int] = None,
                         today: Optional[date] = None) -> bytes:
    """Genera un PDF con el resumen ejecutivo de cobranza."""
    today = today or date.today()
    data = summary(invoices, today=today)

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
    except ImportError:
        return _summary_html_fallback(data, tenant_id).encode("utf-8")

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(
        "Resumen Ejecutivo de Cobranza", styles["Title"]))
    elements.append(Paragraph(
        f"Fecha: {today.strftime('%d/%m/%Y')} | Tenant: {tenant_id or 'N/A'}",
        styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # KPIs
    kpi_data = [
        ["Cartera Total", "Facturas", "Esperado", "Tasa"],
        [format_monto(float(data["total_cartera"])),
         str(data["total_count"]),
         format_monto(float(data["total_esperado"])),
         f"{data['tasa_recuperacion_esperada']:.1f}%"],
    ]
    t = Table(kpi_data, colWidths=[1.8 * inch, 1.2 * inch,
                                    1.8 * inch, 1.8 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e74c3c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.3 * inch))

    # Alertas
    if data.get("alertas"):
        elements.append(Paragraph(
            "<b>⚠ Alertas</b>", styles["Heading2"]))
        for alerta in data["alertas"]:
            elements.append(Paragraph(f"• {alerta}", styles["Normal"]))
        elements.append(Spacer(1, 0.2 * inch))

    # Por antigüedad
    elements.append(Paragraph(
        "<b>Distribución por Antigüedad</b>", styles["Heading2"]))
    age_data = [["Bucket", "Facturas", "Monto", "%"]]
    for bucket, vals in data["por_antiguedad"].items():
        age_data.append([
            bucket,
            str(vals["count"]),
            format_monto(float(vals["monto"])),
            f"{vals.get('porcentaje', 0):.1f}%",
        ])
    t2 = Table(age_data, colWidths=[1.5 * inch, 1.2 * inch,
                                     2.5 * inch, 1.5 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t2)

    # Top montos
    if data.get("top_montos"):
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph(
            "<b>Top Montos Pendientes</b>", styles["Heading2"]))
        top_data = [["ID", "Empresa", "Monto", "Días", "Score"]]
        for m in data["top_montos"]:
            top_data.append([
                m.get("factura_id", ""),
                m.get("nombre_empresa", "")[:25],
                format_monto(float(str(m.get("monto", 0)).replace(",", ""))),
                str(m.get("dias_vencido", 0)),
                f"{m.get('score', 0):.2f}",
            ])
        t3 = Table(top_data, colWidths=[1 * inch, 1.8 * inch,
                                         1.5 * inch, 0.8 * inch, 0.8 * inch])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        elements.append(t3)

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(
        f"<i>Generado el {datetime.utcnow().isoformat()} por Likida AI Enterprise</i>",
        styles["Normal"]))

    doc.build(elements)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# HTML fallbacks (cuando reportlab no está instalado)
# --------------------------------------------------------------------------- #

def _html_fallback_base(title: str, tenant_id: Optional[int]) -> str:
    return (
        f"<html><head><meta charset='utf-8'>"
        f"<style>body{{font-family:sans-serif;padding:20px}} "
        f"table{{border-collapse:collapse;width:100%}} "
        f"th,td{{border:1px solid #ddd;padding:8px;text-align:left}} "
        f"th{{background:#2c3e50;color:white}} "
        f".total{{background:#ecf0f1;font-weight:bold}}</style></head>"
        f"<body><h1>{title}</h1>"
        f"<p>Fecha: {date.today().strftime('%d/%m/%Y')} | "
        f"Tenant: {tenant_id or 'N/A'}</p>"
    )


def _aging_html_fallback(data: Dict, tenant_id: Optional[int]) -> str:
    html = _html_fallback_base("Reporte de Antigüedad de Cartera", tenant_id)
    html += "<h2>Resumen por Antigüedad</h2><table>"
    html += "<tr><th>Bucket</th><th>Facturas</th><th>Monto</th></tr>"
    for b, v in data["buckets"].items():
        html += (f"<tr><td>{b}</td><td>{v['count']}</td>"
                 f"<td>{format_monto(float(v['monto']))}</td></tr>")
    html += (f"<tr class='total'><td>TOTAL</td>"
             f"<td>{data['total_count']}</td>"
             f"<td>{format_monto(float(data['total_monto']))}</td></tr>")
    html += "</table></body></html>"
    return html


def _projection_html_fallback(data: Dict, tenant_id: Optional[int]) -> str:
    html = _html_fallback_base("Proyección de Cobro Esperado", tenant_id)
    html += "<table><tr><th>Cartera</th><th>Esperado</th><th>Tasa</th></tr>"
    html += (f"<tr><td>{format_monto(float(data['total_cartera']))}</td>"
             f"<td>{format_monto(float(data['total_esperado']))}</td>"
             f"<td>{data['tasa_recuperacion_esperada']:.1f}%</td></tr>")
    html += "</table></body></html>"
    return html


def _summary_html_fallback(data: Dict, tenant_id: Optional[int]) -> str:
    html = _html_fallback_base("Resumen Ejecutivo de Cobranza", tenant_id)
    if data.get("alertas"):
        html += "<h2>⚠ Alertas</h2><ul>"
        for a in data["alertas"]:
            html += f"<li>{a}</li>"
        html += "</ul>"
    html += "</body></html>"
    return html
