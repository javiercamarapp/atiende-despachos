# -*- coding: utf-8 -*-
"""
serializers.py — Serializadores de reportes a JSON, CSV y HTML.

Cada serializer toma un ReportData y produce la representación correspondiente.
El HTML es un template profesional con estilos inline, listo para PDF (wkhtmltopdf
o weasyprint).

Uso:
    from b2b_ai.features.reportes.serializers import serialize_json, serialize_csv, serialize_html
    json_str = serialize_json(report)
    csv_str = serialize_csv(report)
    html_str = serialize_html(report)
"""
from __future__ import annotations

import csv
import io
import json
from html import escape as _html_escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from b2b_ai.features.reportes.generator import ReportData


def serialize_json(report: "ReportData", indent: int = 2) -> str:
    """Serializa un ReportData a JSON formateado.

    Returns:
        String JSON con indentación y formato legible.
    """
    return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False)


def serialize_csv(report: "ReportData") -> str:
    """Serializa un ReportData a CSV plano.

    Formato:
        Sección,Título,Concepto,Subconcepto,Importe
        (una fila por línea, con cabeceras de sección como filas de separación)

    Returns:
        String CSV con encoding UTF-8.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Cabecera
    writer.writerow(["Sección", "Concepto", "Subconcepto", "Importe"])

    for section in report.secciones:
        # Fila de separación de sección
        writer.writerow([section.titulo, "", "", ""])
        for line in section.lineas:
            writer.writerow([
                "",
                line.concepto,
                line.subconcepto,
                str(line.importe),
            ])
        # Subtotal de la sección
        writer.writerow(["", section.subtotal_label, "", str(section.subtotal)])
        writer.writerow(["", "", "", ""])

    # Totales
    if report.totales:
        writer.writerow(["TOTAL DEL REPORTE", "", "", ""])
        for key, val in report.totales.items():
            writer.writerow(["", key, "", val])

    return output.getvalue()


def serialize_html(report: "ReportData") -> str:
    """Serializa un ReportData a HTML profesional con estilos inline.

    Diseño limpio y profesional, listo para renderizar o convertir a PDF.
    Usa estilos inline para compatibilidad con weasyprint/wkhtmltopdf.

    Returns:
        String HTML completo (DOCTYPE + <html>).
    """
    def _h(text: str) -> str:
        """Escapa HTML."""
        return _html_escape(str(text))

    def _fmt_importe(val) -> str:
        """Formatea un importe para HTML."""
        try:
            from decimal import Decimal, ROUND_HALF_UP
            d = Decimal(str(val))
            return f"${d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
        except Exception:
            return f"${val}"

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>{_h(report.titulo)}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1a1a1a; }}
  .header {{ text-align: center; border-bottom: 3px solid #2563eb; padding-bottom: 20px; margin-bottom: 30px; }}
  .header h1 {{ color: #1e3a5f; font-size: 24px; margin: 0; }}
  .header h2 {{ color: #4a5568; font-size: 16px; margin: 5px 0 0 0; font-weight: normal; }}
  .header .meta {{ color: #718096; font-size: 12px; margin-top: 10px; }}
  .section {{ margin-bottom: 25px; page-break-inside: avoid; }}
  .section-title {{ background: #2563eb; color: white; padding: 8px 15px; font-size: 14px; font-weight: bold; margin: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0; }}
  th {{ background: #edf2f7; text-align: left; padding: 8px 12px; font-size: 12px; color: #4a5568; border-bottom: 1px solid #cbd5e0; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px; }}
  td.importe {{ text-align: right; font-family: 'Courier New', monospace; font-weight: bold; }}
  tr.subtotal {{ background: #f7fafc; font-weight: bold; }}
  tr.subtotal td {{ border-top: 2px solid #2563eb; }}
  .totals {{ background: #f7fafc; border: 2px solid #2563eb; padding: 15px; margin-top: 30px; }}
  .totals h3 {{ margin: 0 0 10px 0; color: #1e3a5f; font-size: 16px; }}
  .totals table {{ margin: 0; }}
  .totals td {{ border: none; padding: 4px 12px; }}
  .totals .label {{ color: #4a5568; }}
  .totals .value {{ text-align: right; font-family: 'Courier New', monospace; font-weight: bold; }}
  .footer {{ text-align: center; color: #a0aec0; font-size: 11px; margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 15px; }}
</style>
</head>
<body>
""")

    # Header
    html_parts.append(f"""<div class="header">
  <h1>{_h(report.titulo)}</h1>
  <h2>{_h(report.subtitulo)}</h2>
  <div class="meta">
    {_h(report.empresa_nombre)}{_h(f' — RFC: {report.empresa_rfc}') if report.empresa_rfc else ''}<br>
    Período: {_h(report.periodo_inicio or 'N/A')} al {_h(report.periodo_fin or 'N/A')}<br>
    Generado: {_h(report.fecha_generacion)}
  </div>
</div>
""")

    # Secciones
    for section in report.secciones:
        html_parts.append(f"""<div class="section">
<div class="section-title">{_h(section.titulo)}</div>
<table>
<thead><tr><th>Concepto</th><th>Subconcepto</th><th style="text-align:right">Importe</th></tr></thead>
<tbody>
""")
        for line in section.lineas:
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * line.nivel
            html_parts.append(f"""<tr>
  <td>{indent}{_h(line.concepto)}</td>
  <td>{_h(line.subconcepto)}</td>
  <td class="importe">{_h(line.importe_formatted)}</td>
</tr>
""")
        html_parts.append(f"""<tr class="subtotal">
  <td colspan="2">{_h(section.subtotal_label)}</td>
  <td class="importe">{_h(section.subtotal_formatted)}</td>
</tr>
</tbody></table>
</div>
""")

    # Totales
    if report.totales:
        html_parts.append("""<div class="totals">
<h3>Resumen del Reporte</h3>
<table>
""")
        for key, val in report.totales.items():
            label = key.replace("_", " ").title()
            formatted = val
            # Intentar formatear como dinero si parece numérico
            try:
                from decimal import Decimal
                d = Decimal(val)
                formatted = f"${d.quantize(Decimal('0.01')):,.2f}"
            except Exception:
                pass
            html_parts.append(f"""<tr>
  <td class="label">{_h(label)}</td>
  <td class="value">{_h(formatted)}</td>
</tr>
""")
        html_parts.append("</table></div>")

    # Footer
    meta_parts = [f"Tipo: {report.metadata.get('tipo_reporte', 'N/A')}"]
    if report.metadata.get("moneda"):
        meta_parts.append(f"Moneda: {report.metadata['moneda']}")
    html_parts.append(f"""<div class="footer">
  Likida AI Enterprise — Agente Contable Enterprise<br>
  {' | '.join(_h(p) for p in meta_parts)}
</div>
</body>
</html>""")

    return "".join(html_parts)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def serialize(report: "ReportData", fmt: str = "json") -> str:
    """Serializa un reporte al formato solicitado.

    Args:
        report: ReportData a serializar.
        fmt: 'json', 'csv' o 'html'.

    Returns:
        String con el reporte serializado.

    Raises:
        ValueError: Si el formato no es soportado.
    """
    serializers = {
        "json": serialize_json,
        "csv": serialize_csv,
        "html": serialize_html,
    }
    fn = serializers.get(fmt.lower())
    if fn is None:
        raise ValueError(
            f"Formato no soportado: {fmt}. Use: {', '.join(serializers.keys())}"
        )
    return fn(report)


SUPPORTED_FORMATS = ["json", "csv", "html"]
