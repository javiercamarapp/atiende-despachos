# -*- coding: utf-8 -*-
"""
exporter.py — Exportación de datos a CSV / Excel (xlsx) / PDF (enterprise v2).

Sin dependencias externas (solo stdlib): el CSV usa `csv`, el XLSX se
escribe a mano (un xlsx es un ZIP con XML), y el PDF es un PDF de texto de
una o más páginas generado directamente (Helvetica + escape de bytes).

Uso:
    data = [{"id": 1, "total": 100.5}, ...]        # lista de dicts
    csv_bytes  = export_csv(data)
    xlsx_bytes = export_xlsx(data, title="Facturas")
    pdf_bytes  = export_pdf(data, title="Facturas")
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Dict, List, Optional, Tuple


def _sanitize(value: object) -> str:
    """Convierte un valor a texto seguro (None → '')."""
    if value is None:
        return ""
    return str(value)


def _headers(data: List[Dict[str, object]]) -> List[str]:
    """Orden de columnas: unión de keys en el primer dict (mantiene orden)."""
    if not data:
        return []
    seen = []
    for k in data[0].keys():
        seen.append(k)
    # Completa con keys que aparezcan en filas posteriores.
    for row in data:
        for k in row.keys():
            if k not in seen:
                seen.append(k)
    return seen


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def export_csv(data: List[Dict[str, object]],
               columns: Optional[List[str]] = None) -> bytes:
    """Serializa `data` (lista de dicts) a CSV en UTF-8.

    `columns` opcional fija el orden de columnas; si no se pasa, se infieren
    de las keys del primer dict (más las que aparezcan después).
    """
    headers = columns or _headers(data)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in data:
        writer.writerow([_sanitize(row.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")


# --------------------------------------------------------------------------
# XLSX (ZIP + XML, sin librerías externas)
# --------------------------------------------------------------------------
def _xlsx_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def export_xlsx(data: List[Dict[str, object]], title: str = "Export") -> bytes:
    """Serializa `data` a un archivo XLSX (ZIP+XML) sin dependencias externas.

    Una hoja con cabecera en negrita y las filas de datos; el nombre de la
    hoja es `title` (truncado a 31 chars, límite de Excel).
    """
    headers = _headers(data)
    rows = [[_sanitize(row.get(h)) for h in headers] for row in data]

    def col_letter(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    # Hoja: fila de cabecera (bold) + filas de datos.
    def sheet_xml() -> str:
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<worksheet xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main">',
                 '<sheetData>']
        # Cabecera
        parts.append('<row r="1">')
        for i, h in enumerate(headers, 1):
            ref = f"{col_letter(i-1)}1"
            parts.append(
                f'<c r="{ref}" t="inlineStr" s="1"><is>'
                f"<t>{_xlsx_escape(h)}</t></is></c>")
        parts.append("</row>")
        # Datos
        for r, row in enumerate(rows, 2):
            parts.append(f'<row r="{r}">')
            for i, v in enumerate(row, 1):
                ref = f"{col_letter(i-1)}{r}"
                parts.append(
                    f'<c r="{ref}" t="inlineStr"><is>'
                    f"<t>{_xlsx_escape(v)}</t></is></c>")
            parts.append("</row>")
        parts.append("</sheetData></worksheet>")
        return "".join(parts)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""")
        z.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        z.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>
</workbook>""" % _xlsx_escape(title[:31]))
        z.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""")
        z.writestr("xl/styles.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="2"><xf/><xf applyFont="1" fontId="1"/></cellXfs>
</styleSheet>""")
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml())
    return buf.getvalue()


# --------------------------------------------------------------------------
# PDF (texto simple, stdlib)
# --------------------------------------------------------------------------
_HELV = ('/Helvetica')
_ESCAPE_RE = re.compile(r"[\x00-\x1f\x7f-\xff]")


def _pdf_escape(text: str) -> str:
    """Escapa texto para un string PDF literal (parentesis, backslash)."""
    out = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    # Reemplaza bytes no-ASCII por su secuencia octal para que el PDF no
    # dependa de la codificación de la fuente.
    return _ESCAPE_RE.sub(lambda m: "\\%03o" % ord(m.group(0)), out)


def export_pdf(data: List[Dict[str, object]], title: str = "Export") -> bytes:
    """Genera un PDF de texto de una página a partir de la data."""
    headers = _headers(data)
    rows = [[_sanitize(row.get(h)) for h in headers] for row in data]

    # Líneas de contenido: encabezado + filas.
    header_lines = [f"{title}", ""]
    body_lines = [
        f"{r}. " + "  |  ".join(f"{h}: {v}" for h, v in zip(headers, row))
        for r, row in enumerate(rows, 1)
    ]
    all_lines = header_lines + body_lines

    text_ops = ["BT", "/F1 9 Tf", "40 760 Td", "13 TL"]
    for line in all_lines:
        text_ops.append(f"({_pdf_escape(line[:150])}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops)

    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj",
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj",
        "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont %s "
        "/Encoding /WinAnsiEncoding >>\nendobj" % _HELV,
        "5 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj"
        % (len(stream.encode("latin-1", "replace")), stream),
    ]
    content = ["%PDF-1.4\n"]
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len("".join(content).encode("latin-1", "replace")))
        content.append(f"{i} 0 obj\n" + obj + "\n")
    xref_pos = len("".join(content).encode("latin-1", "replace"))
    content.append(f"xref\n0 {len(objects)+1}\n")
    content.append("0000000000 65535 f \n")
    for off in offsets:
        content.append(f"{off:010d} 00000 n \n")
    content.append(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\n")
    content.append("startxref\n")
    content.append(f"{xref_pos}\n")
    content.append("%%EOF")
    return "".join(content).encode("latin-1", "replace")


FORMAT_MEDIA_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def export(data: List[Dict[str, object]], fmt: str,
           title: str = "Export") -> Tuple[bytes, str]:
    """Exporta a bytes según formato. Devuelve (bytes, media_type).

    `fmt` es 'csv', 'xlsx' o 'pdf' (insensible a mayúsculas). Cualquier otro
    valor lanza ValueError con un mensaje claro.
    """
    fmt = (fmt or "csv").lower()
    if fmt == "csv":
        return export_csv(data), FORMAT_MEDIA_TYPES["csv"]
    if fmt == "xlsx":
        return export_xlsx(data, title=title), FORMAT_MEDIA_TYPES["xlsx"]
    if fmt == "pdf":
        return export_pdf(data, title=title), FORMAT_MEDIA_TYPES["pdf"]
    raise ValueError(f"Formato no soportado: {fmt}")
