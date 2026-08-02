# -*- coding: utf-8 -*-
"""
generator.py — PDFReportGenerator: genera reportes PDF profesionales para
clientes del despacho contable, usando reportlab.

Cada método construye un documento PDF (bytes) con:
  - Header: logo "Likida AI", datos del despacho y período.
  - Cuerpo: tablas con datos de los módulos existentes.
  - Footer: disclaimer legal.

Métodos públicos:
  - generate_monthly_tax_summary(tenant_id, year, month) -> bytes
  - generate_diot_report(tenant_id, year, month) -> bytes
  - generate_conciliacion_report(tenant_id, account_id, year, month) -> bytes
  - generate_nomina_summary(tenant_id, year, month) -> bytes
  - generate_balanza(tenant_id, year, month) -> bytes

Uso:
    gen = PDFReportGenerator(despacho_nombre="Despacho Contable S.C.")
    pdf_bytes = gen.generate_monthly_tax_summary("acme", 2024, 1)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ---------------------------------------------------------------------------
# Helpers de formato
# ---------------------------------------------------------------------------

def _fmt_money(value: Any) -> str:
    """Formatea un valor como moneda MXN (con signo $ y separadores)."""
    if value is None:
        return "$0.00"
    try:
        d = Decimal(str(value))
        return f"${d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    except (InvalidOperation, ValueError):
        return "$0.00"


def _fmt_num(value: Any) -> str:
    """Formatea un número con separadores de miles (sin signo)."""
    if value is None:
        return "0"
    try:
        d = Decimal(str(value))
        return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    except (InvalidOperation, ValueError):
        return "0"


def _period_label(year: int, month: int) -> str:
    """Devuelve 'Enero 2024' a partir de (year, month)."""
    meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    if not (1 <= month <= 12):
        month = 1
    return f"{meses[month - 1]} {year}"


# ---------------------------------------------------------------------------
# Despacho (datos por defecto)
# ---------------------------------------------------------------------------

DEFAULT_DESPACHO = {
    "nombre": "Likida AI · Despacho Contable Digital",
    "rfc": "LIA210101ABC",
    "calle": "Av. Insurgentes Sur 1234, Piso 8",
    "ciudad": "Ciudad de México, CDMX",
    "telefono": "+52 55 0000 0000",
    "correo": "contacto@likida.ai",
    "sitio": "likida.ai",
}

LEGAL_DISCLAIMER = (
    "Este documento fue generado automáticamente por Likida AI a partir de la "
    "información contable y fiscal proporcionada por el contribuyente. Los "
    "montos reflejan los registros cargados en el sistema al momento de la "
    "generación. El contenido no constituye asesoría fiscal o legal y no "
    "sustituye la revisión de un profesional contable. Verifique los datos "
    "antes de presentar cualquier declaración ante el SAT."
)


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------

class _Styles:
    """Fábrica de estilos reutilizables para los PDFs."""

    def __init__(self) -> None:
        self.ss = getSampleStyleSheet()
        self.title = ParagraphStyle(
            "Titulo",
            parent=self.ss["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#0F5EA8"),
            spaceAfter=2,
        )
        self.subtitle = ParagraphStyle(
            "Subtitulo",
            parent=self.ss["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#444444"),
            spaceAfter=8,
        )
        self.section = ParagraphStyle(
            "Seccion",
            parent=self.ss["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#0F5EA8"),
            spaceBefore=10,
            spaceAfter=4,
        )
        self.body = ParagraphStyle(
            "Body",
            parent=self.ss["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
        )
        self.cell = ParagraphStyle(
            "Cell",
            parent=self.ss["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
        )
        self.cell_bold = ParagraphStyle(
            "CellBold",
            parent=self.cell,
            fontName="Helvetica-Bold",
        )
        self.header_cell = ParagraphStyle(
            "HeaderCell",
            parent=self.cell_bold,
            fontSize=9,
            leading=11,
            textColor=colors.white,
        )
        self.total_row = ParagraphStyle(
            "TotalRow",
            parent=self.cell_bold,
            fontName="Helvetica-Bold",
            fontSize=9,
        )
        self.note = ParagraphStyle(
            "Nota",
            parent=self.ss["Italic"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#666666"),
            alignment=TA_LEFT,
        )
        self.disclaimer = ParagraphStyle(
            "Disclaimer",
            parent=self.ss["Italic"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#888888"),
            alignment=TA_CENTER,
        )


# ---------------------------------------------------------------------------
# Generador
# ---------------------------------------------------------------------------

class PDFReportGenerator:
    """Genera reportes PDF profesionales para clientes del despacho."""

    def __init__(
        self,
        despacho: Optional[Dict[str, str]] = None,
        legal_disclaimer: Optional[str] = None,
    ) -> None:
        self.despacho = {**DEFAULT_DESPACHO, **(despacho or {})}
        self.legal_disclaimer = legal_disclaimer or LEGAL_DISCLAIMER
        self._styles = _Styles()

    # ------------------------------------------------------------------
    # Construcción base del documento
    # ------------------------------------------------------------------

    def _new_doc(self) -> SimpleDocTemplate:
        """Crea un documento reportlab con header/footer en cada página."""
        doc = SimpleDocTemplate(
            None,  # buffered; se usa build con io.BytesIO
            pagesize=letter,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=20 * mm,
        )
        return doc

    def _draw_header_footer(self, canvas, doc):
        """Dibuja el header (logo + datos del despacho) y el footer (disclaimer)."""
        w, h = letter
        margin = 18 * mm

        # --- Header ---
        canvas.saveState()
        # Barra de color superior
        canvas.setFillColor(colors.HexColor("#0F5EA8"))
        canvas.rect(0, h - 4 * mm, w, 4 * mm, fill=1, stroke=0)
        # Logo (texto) y nombre del despacho
        canvas.setFillColor(colors.HexColor("#0F5EA8"))
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(margin, h - 15 * mm, "Likida AI")
        canvas.setFillColor(colors.HexColor("#333333"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(
            margin, h - 18 * mm,
            f"{self.despacho.get('nombre', '')}  |  RFC {self.despacho.get('rfc', '')}",
        )
        canvas.drawString(
            margin, h - 21 * mm,
            f"{self.despacho.get('calle', '')}  ·  {self.despacho.get('ciudad', '')}",
        )
        canvas.drawString(
            margin, h - 24 * mm,
            f"Tel {self.despacho.get('telefono', '')}  ·  {self.despacho.get('correo', '')}  ·  {self.despacho.get('sitio', '')}",
        )
        # Línea divisoria
        canvas.setStrokeColor(colors.HexColor("#0F5EA8"))
        canvas.setLineWidth(0.8)
        canvas.line(margin, h - 27 * mm, w - margin, h - 27 * mm)

        # --- Footer ---
        canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 15 * mm, w - margin, 15 * mm)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.setFont("Helvetica-Oblique", 6.5)
        # Texto del disclaimer envuelto en líneas manuales
        disclaimer = self.legal_disclaimer
        max_chars = 118
        lines = [disclaimer[i:i + max_chars] for i in range(0, len(disclaimer), max_chars)]
        y = 13 * mm
        for line in lines[:3]:
            canvas.drawString(margin, y, line)
            y -= 3.2 * mm
        # Número de página
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(
            w / 2, 5 * mm, f"Página {doc.page}   ·   Likida AI Reportes"
        )
        canvas.restoreState()

    def _build(
        self,
        story: List[Any],
    ) -> bytes:
        """Construye el PDF con header/footer y devuelve los bytes."""
        import io
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=letter,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=30 * mm,
            bottomMargin=24 * mm,
            title="Likida AI · Reporte",
            author="Likida AI",
        )
        doc.build(story, onFirstPage=self._draw_header_footer,
                  onLaterPages=self._draw_header_footer)
        buf.seek(0)
        return buf.getvalue()

    def _cover_block(
        self,
        title: str,
        subtitle: str,
        period_label: str,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> List[Any]:
        """Bloque de encabezado del reporte: título, cliente, período."""
        st = self._styles
        story: List[Any] = []
        story.append(Paragraph(title, st.title))
        story.append(Paragraph(subtitle, st.subtitle))
        story.append(Spacer(1, 4))
        # Tabla de encabezado (cliente / período / fecha generación)
        header_rows = [
            [
                Paragraph("<b>Cliente:</b>", st.cell_bold),
                Paragraph(tenant_name or "—", st.cell),
                Paragraph("<b>RFC:</b>", st.cell_bold),
                Paragraph(tenant_rfc or "—", st.cell),
            ],
            [
                Paragraph("<b>Período:</b>", st.cell_bold),
                Paragraph(period_label, st.cell),
                Paragraph("<b>Generado:</b>", st.cell_bold),
                Paragraph(datetime.now().strftime("%d/%m/%Y %H:%M"), st.cell),
            ],
        ]
        t = Table(header_rows, colWidths=[15 * mm, 55 * mm, 15 * mm, 60 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))
        return story

    def _make_table(
        self,
        headers: List[str],
        rows: List[List[str]],
        widths: List[Optional[float]],
        total_row: Optional[List[str]] = None,
    ) -> Table:
        """Construye una tabla estilizada con headers azules y filas alternadas."""
        st = self._styles
        styled_headers = [Paragraph(h, st.header_cell) for h in headers]
        data: List[Any] = [styled_headers]
        for r in rows:
            data.append([Paragraph(str(c), st.cell) for c in r])
        if total_row:
            data.append([Paragraph(str(c), st.total_row) for c in total_row])

        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F5EA8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F6FB")]),
        ]
        if total_row:
            n = len(data) - 1
            style += [
                ("BACKGROUND", (0, n), (-1, n), colors.HexColor("#DDE7F3")),
                ("FONTNAME", (0, n), (-1, n), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(style))
        return t

    # ------------------------------------------------------------------
    # 1. Resumen Fiscal Mensual (IVA + ISR)
    # ------------------------------------------------------------------

    def generate_monthly_tax_summary(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
        iva: Optional[Dict[str, Any]] = None,
        isr: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Resumen fiscal mensual: IVA cobrado/pagado y ISR provisional."""
        period_label = _period_label(year, month)
        iva = iva or {}
        isr = isr or {}
        st = self._styles

        iva_cobrado = iva.get("iva_cobrado", 0)
        iva_pagado = iva.get("iva_pagado", 0)
        saldo_favor = iva.get("saldo_favor", 0)
        saldo_contra = iva.get("saldo_contra", 0)
        isr_ingresos = isr.get("ingresos_acumulables", 0)
        isr_deducible = isr.get("deducciones", 0)
        base_gravable = isr.get("base_gravable", 0)
        isr_pagar = isr.get("isr_causado", 0)

        story = self._cover_block(
            "Resumen Fiscal Mensual",
            "IVA e ISR del período",
            period_label,
            tenant_name,
            tenant_rfc,
        )

        # --- IVA ---
        story.append(Paragraph("1. Impuesto al Valor Agregado (IVA)", st.section))
        iva_rows = [
            ["IVA acreditable (pagado)", _fmt_money(iva_pagado)],
            ["IVA trasladado (cobrado)", _fmt_money(iva_cobrado)],
        ]
        if saldo_favor:
            iva_rows.append(["Saldo a favor", _fmt_money(saldo_favor)])
        if saldo_contra:
            iva_rows.append(["A cargo (por pagar)", _fmt_money(saldo_contra)])
        dif_iva = float(iva_cobrado) - float(iva_pagado)
        iva_rows.append(["Diferencia IVA", _fmt_money(dif_iva)])
        story.append(self._make_table(
            ["Concepto", "Importe"],
            iva_rows,
            [100 * mm, 50 * mm],
        ))

        # --- ISR ---
        story.append(Paragraph("2. Impuesto Sobre la Renta (ISR provisional)", st.section))
        isr_rows = [
            ["Ingresos acumulables", _fmt_money(isr_ingresos)],
            ["Deducciones autorizadas", _fmt_money(isr_deducible)],
            ["Base gravable (utilidad fiscal)", _fmt_money(base_gravable)],
            ["ISR causado (a pagar)", _fmt_money(isr_pagar)],
        ]
        story.append(self._make_table(
            ["Concepto", "Importe"],
            isr_rows,
            [100 * mm, 50 * mm],
        ))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Nota: cifras con base en los registros contables del contribuyente "
            "al período indicado. Consulte las declaraciones IVA/ISR oficiales.",
            st.note,
        ))
        return self._build(story)

    # ------------------------------------------------------------------
    # 2. Resumen DIOT
    # ------------------------------------------------------------------

    def generate_diot_report(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
        summary: Optional[Dict[str, Any]] = None,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """Resumen DIOT (operaciones con terceros) del trimestre que incluye el mes."""
        period_label = _period_label(year, month)
        summary = summary or {}
        records = records or []
        st = self._styles

        story = self._cover_block(
            "Resumen DIOT",
            "Declaración Informativa de Operaciones con Terceros",
            period_label,
            tenant_name,
            tenant_rfc,
        )

        # Totales
        total_base = summary.get("total_base_gravable", 0)
        total_trasladado = summary.get("total_iva_trasladado", 0)
        total_acreditable = summary.get("total_iva_acreditable", 0)
        story.append(Paragraph("Totales del período", st.section))
        story.append(self._make_table(
            ["Concepto", "Importe"],
            [
                ["Base gravable", _fmt_money(total_base)],
                ["IVA trasladado", _fmt_money(total_trasladado)],
                ["IVA acreditable", _fmt_money(total_acreditable)],
            ],
            [100 * mm, 50 * mm],
        ))

        # Detalle por proveedor
        if records:
            story.append(Paragraph("Operaciones con terceros", st.section))
            rows = []
            for r in records:
                rows.append([
                    r.get("rfc_tercero", ""),
                    r.get("nombre", ""),
                    r.get("tipo_operacion", ""),
                    _fmt_money(r.get("base_gravable", 0)),
                    _fmt_money(r.get("iva_trasladado", 0)),
                ])
            story.append(self._make_table(
                ["RFC", "Proveedor / Nombre", "Tipo", "Base", "IVA trasladado"],
                rows,
                [28 * mm, 45 * mm, 16 * mm, 30 * mm, 31 * mm],
            ))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Nota: la DIOT se presenta trimestralmente. Este resumen refleja el "
            "acumulado de operaciones con terceros del período indicado.",
            st.note,
        ))
        return self._build(story)

    # ------------------------------------------------------------------
    # 3. Conciliación Bancaria
    # ------------------------------------------------------------------

    def generate_conciliacion_report(
        self,
        tenant_id: str,
        account_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
        conciliacion: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Reporte de conciliación bancaria por cuenta y período."""
        period_label = _period_label(year, month)
        conc = conciliacion or {}
        st = self._styles

        story = self._cover_block(
            "Conciliación Bancaria",
            f"Cuenta: {account_id or '—'}",
            period_label,
            tenant_name,
            tenant_rfc,
        )

        # Resumen de saldos
        saldo_banco = conc.get("saldo_banco", 0)
        saldo_contable = conc.get("saldo_contable", 0)
        diferencia = conc.get("diferencia", 0)
        conciliado = conc.get("conciliado", False)
        story.append(Paragraph("Saldos", st.section))
        story.append(self._make_table(
            ["Concepto", "Importe"],
            [
                ["Saldo según banco", _fmt_money(saldo_banco)],
                ["Saldo según contabilidad", _fmt_money(saldo_contable)],
                ["Diferencia", _fmt_money(diferencia)],
            ],
            [100 * mm, 50 * mm],
        ))

        # Estado
        estado_text = "CONCILIADO ✓" if conciliado else "CON DIFERENCIAS"
        story.append(Paragraph(f"Estado: {estado_text}", st.subtitle))

        # Detalle
        rows = []
        for m in conc.get("movimientos", []):
            rows.append([
                m.get("fecha", ""),
                m.get("descripcion", ""),
                _fmt_money(m.get("monto", 0)),
                "✓" if m.get("conciliado") else "—",
            ])
        if rows:
            story.append(Paragraph("Detalle de movimientos", st.section))
            story.append(self._make_table(
                ["Fecha", "Descripción", "Monto", "Conciliado"],
                rows,
                [22 * mm, 78 * mm, 30 * mm, 20 * mm],
            ))
        else:
            story.append(Paragraph(
                "Sin movimientos registrados para este período/cuenta.", st.body
            ))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Nota: la conciliación compara los movimientos del banco con los "
            "registros contables (pólizas) y señala diferencias no aclaradas.",
            st.note,
        ))
        return self._build(story)

    # ------------------------------------------------------------------
    # 4. Resumen de Nómina
    # ------------------------------------------------------------------

    def generate_nomina_summary(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
        nomina: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Resumen de nómina del período: percepciones, deducciones y provisiones."""
        period_label = _period_label(year, month)
        nom = nomina or {}
        st = self._styles

        story = self._cover_block(
            "Resumen de Nómina",
            "Percepciones, deducciones y provisiones del período",
            period_label,
            tenant_name,
            tenant_rfc,
        )

        total_percepciones = nom.get("total_percepciones", 0)
        total_deducciones = nom.get("total_deducciones", 0)
        total_neto = nom.get("total_neto", 0)
        num_empleados = nom.get("num_empleados", 0)

        story.append(Paragraph("Totales", st.section))
        story.append(self._make_table(
            ["Concepto", "Importe"],
            [
                ["Número de empleados", _fmt_num(num_empleados)],
                ["Total percepciones", _fmt_money(total_percepciones)],
                ["Total deducciones", _fmt_money(total_deducciones)],
                ["Total neto a pagar", _fmt_money(total_neto)],
            ],
            [100 * mm, 50 * mm],
        ))

        # Detalle por empleado
        empleados = nom.get("empleados", [])
        if empleados:
            story.append(Paragraph("Detalle por empleado", st.section))
            rows = []
            for e in empleados:
                rows.append([
                    e.get("nombre", ""),
                    e.get("puesto", ""),
                    _fmt_money(e.get("percepciones", 0)),
                    _fmt_money(e.get("deducciones", 0)),
                    _fmt_money(e.get("neto", 0)),
                ])
            story.append(self._make_table(
                ["Empleado", "Puesto", "Percepciones", "Deducciones", "Neto"],
                rows,
                [45 * mm, 30 * mm, 27 * mm, 27 * mm, 27 * mm],
            ))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Nota: cifras con base en los recibos de nómina del período. Las "
            "provisiones de ISR/IMSS/INFONAVIT deben conciliarse con los pagos.",
            st.note,
        ))
        return self._build(story)

    # ------------------------------------------------------------------
    # 5. Balanza de Comprobación
    # ------------------------------------------------------------------

    def generate_balanza(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
        cuentas: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """Balanza de comprobación: cuentas con saldos deudores/acreedores."""
        period_label = _period_label(year, month)
        cuentas = cuentas or []
        st = self._styles

        story = self._cover_block(
            "Balanza de Comprobación",
            "Saldos por cuenta contable",
            period_label,
            tenant_name,
            tenant_rfc,
        )

        rows = []
        total_deudor = Decimal("0")
        total_acreedor = Decimal("0")
        for c in cuentas:
            deudor = Decimal(str(c.get("saldo_deudor", 0) or 0))
            acreedor = Decimal(str(c.get("saldo_acreedor", 0) or 0))
            total_deudor += deudor
            total_acreedor += acreedor
            rows.append([
                c.get("cuenta", ""),
                c.get("nombre", ""),
                _fmt_money(deudor),
                _fmt_money(acreedor),
            ])
        rows.append([
            "TOTALES",
            "",
            _fmt_money(total_deudor),
            _fmt_money(total_acreedor),
        ])

        if rows:
            story.append(self._make_table(
                ["Cuenta", "Nombre", "Saldo deudor", "Saldo acreedor"],
                rows,
                [20 * mm, 50 * mm, 40 * mm, 40 * mm],
            ))
        else:
            story.append(Paragraph(
                "Sin cuentas registradas para este período.", st.body
            ))

        # Verificación de cuadre
        cuadra = total_deudor == total_acreedor
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Cuadre de la balanza: {'SÍ ✓ (deudor = acreedor)' if cuadra else 'NO — revisar asientos'}", st.section
        ))
        story.append(Paragraph(
            "Nota: la balanza de comprobación resume los saldos de todas las "
            "cuentas contables. La suma de deudores debe ser igual a la de "
            "acreedores.",
            st.note,
        ))
        return self._build(story)

    # ------------------------------------------------------------------
    # Despacho (utilidad para service / metadata)
    # ------------------------------------------------------------------

    def despacho_info(self) -> Dict[str, str]:
        """Devuelve los datos del despacho para inyectar en templates/metadata."""
        return dict(self.despacho)
