# -*- coding: utf-8 -*-
"""
report_pdf.py — Generador de reporte PDF con métricas de ROI para demos.

Genera un PDF profesional con:
  - Portada con branding B&B AI
  - Resumen ejecutivo
  - Métricas de ROI y ahorro
  - Tabla de clientes principales
  - Distribución por giro
  - Anomalías detectadas
  - Conclusiones

Uso:
    from b2b_ai.demo.report_pdf import generate_roi_report
    pdf_path = generate_roi_report(data, output_path)
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm, cm, inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics import renderPDF


# ---------------------------------------------------------------------------
# Brand colors
# ---------------------------------------------------------------------------
BRAND_BLUE = colors.HexColor("#2563EB")
BRAND_BLUE_DARK = colors.HexColor("#1D4ED8")
BRAND_BLUE_LIGHT = colors.HexColor("#DBEAFE")
BRAND_GREEN = colors.HexColor("#16A34A")
BRAND_GREEN_LIGHT = colors.HexColor("#DCFCE7")
BRAND_AMBER = colors.HexColor("#D97706")
BRAND_AMBER_LIGHT = colors.HexColor("#FEF3C7")
BRAND_RED = colors.HexColor("#DC2626")
BRAND_RED_LIGHT = colors.HexColor("#FEE2E2")
BRAND_GRAY_50 = colors.HexColor("#F9FAFB")
BRAND_GRAY_100 = colors.HexColor("#F3F4F6")
BRAND_GRAY_200 = colors.HexColor("#E5E7EB")
BRAND_GRAY_400 = colors.HexColor("#9CA3AF")
BRAND_GRAY_600 = colors.HexColor("#4B5563")
BRAND_GRAY_800 = colors.HexColor("#1F2937")
BRAND_GRAY_900 = colors.HexColor("#111827")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _build_styles() -> Dict[str, ParagraphStyle]:
    """Build custom paragraph styles for the report."""
    base = getSampleStyleSheet()

    styles = {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontSize=28,
            leading=34,
            textColor=BRAND_BLUE_DARK,
            spaceAfter=6,
            alignment=TA_CENTER,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["Normal"],
            fontSize=14,
            leading=18,
            textColor=BRAND_GRAY_600,
            alignment=TA_CENTER,
            spaceAfter=20,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=base["Heading1"],
            fontSize=16,
            leading=20,
            textColor=BRAND_BLUE_DARK,
            spaceBefore=16,
            spaceAfter=8,
            borderWidth=0,
            borderPadding=0,
        ),
        "subsection": ParagraphStyle(
            "subsection",
            parent=base["Heading2"],
            fontSize=12,
            leading=15,
            textColor=BRAND_GRAY_800,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=BRAND_GRAY_800,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value",
            parent=base["Normal"],
            fontSize=20,
            leading=24,
            textColor=BRAND_BLUE,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_GRAY_400,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_GRAY_800,
        ),
        "table_cell_right": ParagraphStyle(
            "table_cell_right",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_GRAY_800,
            alignment=TA_RIGHT,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_GRAY_400,
            alignment=TA_CENTER,
        ),
        "anomaly_high": ParagraphStyle(
            "anomaly_high",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=BRAND_RED,
        ),
        "anomaly_medium": ParagraphStyle(
            "anomaly_medium",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=BRAND_AMBER,
        ),
        "anomaly_low": ParagraphStyle(
            "anomaly_low",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=BRAND_GRAY_400,
        ),
        "highlight_box": ParagraphStyle(
            "highlight_box",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=BRAND_BLUE_DARK,
            backColor=BRAND_BLUE_LIGHT,
            borderPadding=(8, 8, 8, 8),
            spaceAfter=8,
        ),
    }
    return styles


# ---------------------------------------------------------------------------
# KPI Card
# ---------------------------------------------------------------------------

def _make_kpi_card(label: str, value: str, color: colors.Color = BRAND_BLUE) -> Table:
    """Create a single KPI card as a mini table."""
    data = [
        [Paragraph(value, ParagraphStyle("kv", fontSize=18, leading=22, textColor=color, alignment=TA_CENTER))],
        [Paragraph(label, ParagraphStyle("kl", fontSize=7, leading=9, textColor=BRAND_GRAY_400, alignment=TA_CENTER))],
    ]
    t = Table(data, colWidths=[110])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_GRAY_50),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def _make_kpi_row(kpis: List[Dict[str, str]], colors_list: List[colors.Color]) -> Table:
    """Create a row of KPI cards."""
    cards = []
    for i, kpi in enumerate(kpis):
        c = colors_list[i % len(colors_list)]
        cards.append(_make_kpi_card(kpi["label"], kpi["value"], c))

    # Build as single-row table with cards
    inner_tables = []
    for card in cards:
        inner_tables.append([[card]])

    row = Table([inner_tables], colWidths=[120] * len(kpis))
    row.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return row


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_roi_report(
    data: Dict[str, Any],
    output_path: str,
    executive_summary: Dict[str, Any] | None = None,
) -> str:
    """Generate a professional ROI PDF report.

    Args:
        data: Full firm data from generate_demo_firm().
        output_path: Directory to save the PDF.
        executive_summary: Optional pre-built summary.

    Returns:
        Path to the generated PDF file.
    """
    os.makedirs(output_path, exist_ok=True)
    pdf_path = os.path.join(output_path, "B&B_AI_Reporte_ROI_Demo.pdf")

    styles = _build_styles()
    roi = data["roi_metrics"]
    firm = data["firm"]
    clients = data["clients"]
    anomalies = data["anomalies"]
    summary = executive_summary or _default_summary(data)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )

    elements = []
    w = A4[0] - 4 * cm  # usable width

    # -----------------------------------------------------------------------
    # PORTADA
    # -----------------------------------------------------------------------
    elements.append(Spacer(1, 60))
    elements.append(Paragraph("B&B AI", styles["cover_title"]))
    elements.append(Paragraph(
        "Reporte de ROI — Modo Demo",
        styles["cover_subtitle"],
    ))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="60%", thickness=2, color=BRAND_BLUE, spaceAfter=10))
    elements.append(Paragraph(
        firm["nombre"],
        ParagraphStyle("fn", fontSize=14, leading=18, textColor=BRAND_GRAY_800, alignment=TA_CENTER),
    ))
    elements.append(Paragraph(
        f"RFC: {firm['rfc']}  ·  {firm['ciudad']}",
        ParagraphStyle("fd", fontSize=10, leading=14, textColor=BRAND_GRAY_400, alignment=TA_CENTER),
    ))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        f"Periodo: {summary['periodo']}",
        ParagraphStyle("fp", fontSize=12, leading=16, textColor=BRAND_BLUE, alignment=TA_CENTER),
    ))
    elements.append(Paragraph(
        f"Generado: {summary['fecha_generacion']}",
        ParagraphStyle("fg", fontSize=9, leading=12, textColor=BRAND_GRAY_400, alignment=TA_CENTER),
    ))
    elements.append(Spacer(1, 30))
    elements.append(Paragraph(
        "Este reporte demuestra las capacidades del agente contable inteligente B&B AI "
        "en un escenario de firma contable con 50 clientes y ~500 CFDIs procesados mensualmente.",
        ParagraphStyle("fnote", fontSize=9, leading=13, textColor=BRAND_GRAY_600, alignment=TA_CENTER),
    ))
    elements.append(Paragraph(
        "<i>Los datos mostrados son simulados para fines de demostración.</i>",
        ParagraphStyle("fdisclaimer", fontSize=8, leading=10, textColor=BRAND_GRAY_400, alignment=TA_CENTER, spaceAfter=10),
    ))
    elements.append(PageBreak())

    # -----------------------------------------------------------------------
    # RESUMEN EJECUTIVO
    # -----------------------------------------------------------------------
    elements.append(Paragraph("1. Resumen Ejecutivo", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    # KPI Cards row 1
    kpi_row1 = _make_kpi_row(
        [
            {"label": "CFDIs Procesados", "value": f"{summary['resumen']['cfdis_procesados']}"},
            {"label": "Monto Total", "value": f"${summary['resumen']['monto_total']:,.0f}"},
            {"label": "IVA Total", "value": f"${summary['resumen']['iva_total']:,.0f}"},
        ],
        [BRAND_BLUE, BRAND_GREEN, BRAND_AMBER],
    )
    elements.append(kpi_row1)
    elements.append(Spacer(1, 10))

    # KPI Cards row 2
    kpi_row2 = _make_kpi_row(
        [
            {"label": "Anomalías Detectadas", "value": str(summary['resumen']['anomalias_detectadas'])},
            {"label": "Horas Ahorradas", "value": f"{summary['resumen']['horas_ahorradas_ia']}h"},
            {"label": "ROI Mensual", "value": f"{summary['resumen']['roi_mensual_pct']}%"},
        ],
        [BRAND_RED, BRAND_GREEN, BRAND_BLUE],
    )
    elements.append(kpi_row2)
    elements.append(Spacer(1, 10))

    # Resumen texto
    elements.append(Paragraph(
        f"Durante el periodo de <b>{summary['periodo']}</b>, el agente B&B AI procesó "
        f"<b>{summary['resumen']['cfdis_procesados']} CFDIs</b> de "
        f"<b>{summary['resumen']['clientes_activos']} clientes activos</b>, "
        f"con un monto total de <b>${summary['resumen']['monto_total']:,.2f} MXN</b>. "
        f"El sistema detectó <b>{summary['resumen']['anomalias_detectadas']} anomalías</b> "
        f"que habrían pasado desapercibidas en procesamiento manual.",
        styles["body"],
    ))
    elements.append(Paragraph(
        f"El ahorro operativo mensual es de <b>${summary['resumen']['ahorro_mensual']:,.0f} MXN</b> "
        f"({summary['resumen']['horas_ahorradas_ia']} horas de trabajo contable ahorradas), "
        f"con un payback de <b>{summary['resumen']['payback_dias']:.0f} días</b> "
        f"y un ROI mensual de <b>{summary['resumen']['roi_mensual_pct']}%</b>.",
        styles["body"],
    ))

    elements.append(PageBreak())

    # -----------------------------------------------------------------------
    # MÉTRICAS DE ROI DETALLADO
    # -----------------------------------------------------------------------
    elements.append(Paragraph("2. Métricas de ROI Detallado", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    # Ahorro IA
    ahorro = roi["ahorro_ia"]
    elements.append(Paragraph("2.1 Ahorro por Automatización IA", styles["subsection"]))
    ahorro_data = [
        [Paragraph("<b>Métrica</b>", styles["table_header"]),
         Paragraph("<b>Antes (Manual)</b>", styles["table_header"]),
         Paragraph("<b>Después (IA)</b>", styles["table_header"]),
         Paragraph("<b>Mejora</b>", styles["table_header"])],
        [Paragraph("Minutos por factura", styles["table_cell"]),
         Paragraph(f"{ahorro['minutos_por_factura_antes']:.1f} min", styles["table_cell"]),
         Paragraph(f"{ahorro['minutos_por_factura_despues']:.1f} min", styles["table_cell"]),
         Paragraph(f"{ahorro['eficiencia_porcentaje']}%", styles["table_cell"])],
        [Paragraph("Horas mensuales totales", styles["table_cell"]),
         Paragraph(f"{ahorro['minutos_por_factura_antes'] * roi['resumen_firma']['total_cfdi_procesados'] / 60:.0f}h", styles["table_cell"]),
         Paragraph(f"{ahorro['minutos_por_factura_despues'] * roi['resumen_firma']['total_cfdi_procesados'] / 60:.0f}h", styles["table_cell"]),
         Paragraph(f"{ahorro['total_horas_ahorradas']:.0f}h ahorradas", styles["table_cell"])],
        [Paragraph("Costo operativo mensual", styles["table_cell"]),
         Paragraph(f"${ahorro['minutos_por_factura_antes'] * roi['resumen_firma']['total_cfdi_procesados'] / 60 * 350:,.0f}", styles["table_cell"]),
         Paragraph(f"${ahorro['minutos_por_factura_despues'] * roi['resumen_firma']['total_cfdi_procesados'] / 60 * 350:,.0f}", styles["table_cell"]),
         Paragraph(f"${ahorro['ahorro_mensual_mx']:,.0f} ahorrados", styles["table_cell"])],
    ]
    ahorro_table = Table(ahorro_data, colWidths=[w * 0.30, w * 0.22, w * 0.22, w * 0.26])
    ahorro_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), BRAND_GRAY_50),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(ahorro_table)
    elements.append(Spacer(1, 12))

    # Calidad
    calidad = roi["calidad"]
    elements.append(Paragraph("2.2 Mejora en Calidad y Cumplimiento", styles["subsection"]))
    calidad_data = [
        [Paragraph("<b>Métrica</b>", styles["table_header"]),
         Paragraph("<b>Proceso Manual</b>", styles["table_header"]),
         Paragraph("<b>Con B&B AI</b>", styles["table_header"]),
         Paragraph("<b>Factor de mejora</b>", styles["table_header"])],
        [Paragraph("Tasa de error", styles["table_cell"]),
         Paragraph(f"{calidad['tasa_error_humano_pct']}%", styles["table_cell"]),
         Paragraph(f"{calidad['tasa_error_ai_pct']}%", styles["table_cell"]),
         Paragraph(f"{calidad['mejora_calidad_factor']}x mejor", styles["table_cell"])],
        [Paragraph("Anomalías detectadas", styles["table_cell"]),
         Paragraph("No se detectan", styles["table_cell"]),
         Paragraph(f"{calidad['anomalias_detectadas']}", styles["table_cell"]),
         Paragraph("100% cobertura", styles["table_cell"])],
        [Paragraph("Revisión fiscal", styles["table_cell"]),
         Paragraph("Muestreo manual", styles["table_cell"]),
         Paragraph("100% automática", styles["table_cell"]),
         Paragraph("Cobertura total", styles["table_cell"])],
    ]
    calidad_table = Table(calidad_data, colWidths=[w * 0.30, w * 0.22, w * 0.22, w * 0.26])
    calidad_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), BRAND_GRAY_50),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(calidad_table)
    elements.append(Spacer(1, 12))

    # Comparativa ROI
    comp = roi["comparativa_roi"]
    elements.append(Paragraph("2.3 Retorno de Inversión", styles["subsection"]))
    comp_data = [
        [Paragraph("<b>Concepto</b>", styles["table_header"]),
         Paragraph("<b>Valor</b>", styles["table_header"])],
        [Paragraph("Inversión mensual B&B AI", styles["table_cell"]),
         Paragraph(f"${comp['inversion_mensual_b2b_ai']:,.0f} MXN", styles["table_cell_right"])],
        [Paragraph("Ahorro operativo mensual", styles["table_cell"]),
         Paragraph(f"${ahorro['ahorro_mensual_mx']:,.0f} MXN", styles["table_cell_right"])],
        [Paragraph("Beneficio neto mensual", styles["table_cell"]),
         Paragraph(f"${ahorro['ahorro_mensual_mx'] - comp['inversion_mensual_b2b_ai']:,.0f} MXN", styles["table_cell_right"])],
        [Paragraph("ROI mensual", styles["table_cell"]),
         Paragraph(f"{comp['roi_mensual_pct']}%", styles["table_cell_right"])],
        [Paragraph("ROI anual", styles["table_cell"]),
         Paragraph(f"{comp['roi_anual_pct']}%", styles["table_cell_right"])],
        [Paragraph("Payback period", styles["table_cell"]),
         Paragraph(f"{comp['payback_dias']:.0f} días", styles["table_cell_right"])],
        [Paragraph("Ahorro anual proyectado", styles["table_cell"]),
         Paragraph(f"${ahorro['ahorro_anual_mx']:,.0f} MXN", styles["table_cell_right"])],
    ]
    comp_table = Table(comp_data, colWidths=[w * 0.55, w * 0.45])
    comp_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(comp_table)

    elements.append(PageBreak())

    # -----------------------------------------------------------------------
    # TOP CLIENTES
    # -----------------------------------------------------------------------
    elements.append(Paragraph("3. Top Clientes por Facturación", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    top5 = summary.get("clientes_top5", clients[:5])
    client_data = [
        [Paragraph("<b>#</b>", styles["table_header"]),
         Paragraph("<b>Cliente</b>", styles["table_header"]),
         Paragraph("<b>RFC</b>", styles["table_header"]),
         Paragraph("<b>Giro</b>", styles["table_header"]),
         Paragraph("<b>Ciudad</b>", styles["table_header"]),
         Paragraph("<b>Tamaño</b>", styles["table_header"]),
         Paragraph("<b>Mensualidad</b>", styles["table_header"])],
    ]
    for i, cl in enumerate(top5):
        client_data.append([
            Paragraph(str(i + 1), styles["table_cell"]),
            Paragraph(cl["nombre"][:35], styles["table_cell"]),
            Paragraph(cl["rfc"], styles["table_cell"]),
            Paragraph(cl["giro"].capitalize(), styles["table_cell"]),
            Paragraph(cl["ciudad"], styles["table_cell"]),
            Paragraph(cl["tamano"].capitalize(), styles["table_cell"]),
            Paragraph(f"${cl['mensualidad']:,.0f}", styles["table_cell_right"]),
        ])
    client_table = Table(client_data, colWidths=[w * 0.04, w * 0.28, w * 0.12, w * 0.1, w * 0.14, w * 0.12, w * 0.12])
    client_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(client_table)
    elements.append(Spacer(1, 12))

    # -----------------------------------------------------------------------
    # DISTRIBUCIÓN POR GIRO
    # -----------------------------------------------------------------------
    elements.append(Paragraph("4. Distribución por Giro Económico", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    giros = data.get("top_giros", [])
    if giros:
        giro_data = [
            [Paragraph("<b>Giro</b>", styles["table_header"]),
             Paragraph("<b>Facturas</b>", styles["table_header"]),
             Paragraph("<b>Monto Total</b>", styles["table_header"])],
        ]
        for g in giros[:10]:
            giro_data.append([
                Paragraph(g["giro"].capitalize(), styles["table_cell"]),
                Paragraph(str(g["facturas"]), styles["table_cell"]),
                Paragraph(f"${g['monto_total']:,.0f}", styles["table_cell_right"]),
            ])
        giro_table = Table(giro_data, colWidths=[w * 0.40, w * 0.25, w * 0.35])
        giro_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
            ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(giro_table)

    elements.append(PageBreak())

    # -----------------------------------------------------------------------
    # ANOMALÍAS DETECTADAS
    # -----------------------------------------------------------------------
    elements.append(Paragraph("5. Anomalías Detectadas", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    elements.append(Paragraph(
        f"Se detectaron <b>{len(anomalies)} anomalías</b> en el periodo analizado. "
        "Estas anomalías habrían pasado desapercibidas en un proceso manual sin herramientas de IA.",
        styles["body"],
    ))

    # Resumen de severidad
    from collections import Counter
    sev_counter = Counter(a["severity"] for a in anomalies)
    sev_data = [
        [Paragraph("<b>Severidad</b>", styles["table_header"]),
         Paragraph("<b>Cantidad</b>", styles["table_header"]),
         Paragraph("<b>Impacto</b>", styles["table_header"])],
        [Paragraph("Alta", styles["anomaly_high"]),
         Paragraph(str(sev_counter.get("alta", 0)), styles["table_cell"]),
         Paragraph("Requiere revisión inmediata", styles["table_cell"])],
        [Paragraph("Media", styles["anomaly_medium"]),
         Paragraph(str(sev_counter.get("media", 0)), styles["table_cell"]),
         Paragraph("Revisión antes del cierre", styles["table_cell"])],
        [Paragraph("Baja", styles["anomaly_low"]),
         Paragraph(str(sev_counter.get("baja", 0)), styles["table_cell"]),
         Paragraph("Seguimiento mensual", styles["table_cell"])],
    ]
    sev_table = Table(sev_data, colWidths=[w * 0.25, w * 0.20, w * 0.55])
    sev_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_RED),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(sev_table)
    elements.append(Spacer(1, 10))

    # Top anomalies
    elements.append(Paragraph("5.1 Detalle de Anomalías Principales", styles["subsection"]))
    for i, a in enumerate(anomalies[:8]):
        sev_style = styles.get(f"anomaly_{a['severity']}", styles["body"])
        anomaly_text = (
            f"<b>[{a['severity'].upper()}]</b> {a['tipo'].replace('_', ' ').title()}: "
            f"{a['descripcion']}"
        )
        if "referencia_legal" in a:
            anomaly_text += f"<br/><i>Ref: {a['referencia_legal']}</i>"
        elements.append(Paragraph(anomaly_text, sev_style))
        elements.append(Spacer(1, 4))

    elements.append(PageBreak())

    # -----------------------------------------------------------------------
    # SATISFACCIÓN Y MÉTRICAS DE SERVICIO
    # -----------------------------------------------------------------------
    elements.append(Paragraph("6. Métricas de Servicio y Satisfacción", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    sat = roi["satisfaccion"]
    sat_data = [
        [Paragraph("<b>Métrica</b>", styles["table_header"]),
         Paragraph("<b>Valor</b>", styles["table_header"])],
        [Paragraph("NPS Score", styles["table_cell"]),
         Paragraph(str(sat["nps_score"]), styles["table_cell_right"])],
        [Paragraph("Tiempo de respuesta promedio", styles["table_cell"]),
         Paragraph(f"{sat['tiempo_respuesta_avg_seg']}s", styles["table_cell_right"])],
        [Paragraph("Disponibilidad del sistema", styles["table_cell"]),
         Paragraph(f"{sat['disponibilidad_pct']}%", styles["table_cell_right"])],
        [Paragraph("Tickets de soporte al mes", styles["table_cell"]),
         Paragraph(str(sat["tickets_soporte_mes"]), styles["table_cell_right"])],
        [Paragraph("Clientes activos", styles["table_cell"]),
         Paragraph(str(roi["resumen_firma"]["total_clientes_activos"]), styles["table_cell_right"])],
    ]
    sat_table = Table(sat_data, colWidths=[w * 0.55, w * 0.45])
    sat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GRAY_50]),
        ("GRID", (0, 0), (-1, -1), 0.5, BRAND_GRAY_200),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(sat_table)

    elements.append(Spacer(1, 20))

    # -----------------------------------------------------------------------
    # CONCLUSIONES
    # -----------------------------------------------------------------------
    elements.append(Paragraph("7. Conclusiones y Recomendaciones", styles["section_title"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=BRAND_BLUE_LIGHT, spaceAfter=8))

    conclusions = [
        f"<b>Eficiencia operativa:</b> B&B AI reduce el tiempo de procesamiento de CFDIs en "
        f"{ahorro['eficiencia_porcentaje']}%, pasando de {ahorro['minutos_por_factura_antes']} min/factura "
        f"a {ahorro['minutos_por_factura_despues']} min/factura.",

        f"<b>Ahorro económico:</b> El ahorro mensual es de ${ahorro['ahorro_mensual_mx']:,.0f} MXN "
        f"(${ahorro['ahorro_anual_mx']:,.0f} anuales), con un ROI del {comp['roi_mensual_pct']}% mensual "
        f"y payback en {comp['payback_dias']:.0f} días.",

        f"<b>Calidad y cumplimiento:</b> La tasa de error se reduce de "
        f"{calidad['tasa_error_humano_pct']}% a {calidad['tasa_error_ai_pct']}% "
        f"(factor {calidad['mejora_calidad_factor']}x de mejora). Se detectaron "
        f"{calidad['anomalias_detectadas']} anomalías que habrían pasado inadvertidas.",

        f"<b>Cobertura total:</b> El 100% de los CFDIs pasan por revisión automática, "
        f"eliminando el riesgo de muestreo en auditorías fiscales.",

        f"<b>Escalabilidad:</b> La plataforma soporta actualmente {roi['resumen_firma']['total_clientes_activos']} "
        f"clientes con {roi['resumen_firma']['total_cfdi_procesados']} CFDIs/mes, "
        f"con capacidad de crecer sin incremento proporcional en costos.",
    ]

    for c in conclusions:
        elements.append(Paragraph(f"• {c}", styles["body"]))
        elements.append(Spacer(1, 4))

    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="40%", thickness=1, color=BRAND_GRAY_200, spaceAfter=10))
    elements.append(Paragraph(
        "Este reporte fue generado automáticamente por el agente contable inteligente B&B AI. "
        "Los datos son simulados para fines de demostración comercial.",
        styles["footer"],
    ))
    elements.append(Paragraph(
        f"B&B AI — {firm['nombre']} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["footer"],
    ))

    # -----------------------------------------------------------------------
    # Build PDF
    # -----------------------------------------------------------------------
    doc.build(elements)
    return pdf_path


# ---------------------------------------------------------------------------
# Default summary builder
# ---------------------------------------------------------------------------

def _default_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Build executive summary from raw data if not provided."""
    from b2b_ai.demo.firm_generator import build_executive_summary
    return build_executive_summary(data)
