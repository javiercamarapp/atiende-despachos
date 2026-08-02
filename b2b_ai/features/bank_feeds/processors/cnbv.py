# -*- coding: utf-8 -*-
"""
cnbv.py — Parser de estados de cuenta en formato CNBV.

La CNBV (Comisión Nacional Bancaria y de Valores) no define un XML de estados
de cuenta; el "formato CNBV" en la práctica es un CSV/TSV exportado por las
plataformas bancarias mexicanas con columnas típicas:

    Fecha, Descripcion, Referencia, Cargo, Abono

Este parser es tolerante a encabezados en español (con/sin acentos) y a
separadores coma/tab/punto y coma. Devuelve RawMovement.

Reglas:
  - "Cargo" (débito) -> amount negativo
  - "Abono" (crédito) -> amount positivo
  - Si solo existe una columna de importe, usa el signo implícito (negativo
    si la descripción contiene DEPOSITO/ABONO/SPEI RECIBIDO, positivo en otro
    caso; mejor: usa la columna de monto tal cual).
"""
from __future__ import annotations

import csv
import io
import re
from typing import List, Optional

from b2b_ai.features.bank_feeds.processors.ofx import RawMovement

# Encabezados posibles (normalizados a minúsculas sin acentos)
_DATE_COLS = ("fecha", "fechamov", "fechaop", "fechamovimiento", "fecha mov")
_DESC_COLS = ("descripcion", "descripcion1", "concepto", "detalle", "detalle1", "narracion")
_REF_COLS = ("referencia", "claverastreo", "referenciaop", "rfc", "contraparte")
_CARGO_COLS = ("cargo", "debito", "debe", "retiro", "salida", "cargos")
_ABONO_COLS = ("abono", "credito", "haber", "deposito", "entrada", "abonos")
_AMT_COLS = ("importe", "monto", "cantidad", "importeoperacion", "montooperacion")


def parse_cnbv(text: str, delimiter: Optional[str] = None) -> List[RawMovement]:
    """Parsea texto CNBV (CSV/TSV) a lista de RawMovement.

    Lanza ValueError si no encuentra filas de datos válidas.
    """
    if not text or not text.strip():
        raise ValueError("Contenido CNBV vacío")

    sample = text.strip().splitlines()
    if delimiter is None:
        delimiter = _detect_delimiter(sample)

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ValueError("CNBV sin encabezado")

    headers = {_norm(h): h for h in reader.fieldnames}
    date_col = _pick_header(_DATE_COLS, headers)
    desc_col = _pick_header(_DESC_COLS, headers)
    ref_col = _pick_header(_REF_COLS, headers)
    cargo_col = _pick_header(_CARGO_COLS, headers)
    abono_col = _pick_header(_ABONO_COLS, headers)
    amt_col = _pick_header(_AMT_COLS, headers)

    if not amt_col and not cargo_col and not abono_col:
        raise ValueError("CNBV sin columna de importe (cargo/abono/importe)")

    movements: List[RawMovement] = []
    for idx, row in enumerate(reader, start=1):
        date = _cell(row, headers, date_col)
        desc = _cell(row, headers, desc_col)
        ref = _cell(row, headers, ref_col)
        amt = _amount_from_row(row, headers, cargo_col, abono_col, amt_col)
        if amt is None:
            continue  # fila sin importe: ignorar
        movements.append(
            RawMovement(
                external_id=f"cnbv:{idx}:{date}:{amt}",
                date=_norm_date(date),
                amount=f"{amt:.2f}",
                description=desc,
                memo="",
                type_raw="DEBIT" if amt < 0 else "CREDIT",
                bank_name="",
                extra={"source_row": idx},
            )
        )

    if not movements:
        raise ValueError("No se encontraron filas con importe en el CNBV")
    return movements


def _amount_from_row(row, headers, cargo_col, abono_col, amt_col) -> Optional[float]:
    """Devuelve el importe firmado (positivo=abono, negativo=cargo)."""
    if amt_col:
        raw = _cell(row, headers, amt_col)
        if raw:
            try:
                return float(_clean_amount(raw))
            except ValueError:
                return None
    cargo = _cell(row, headers, cargo_col)
    abono = _cell(row, headers, abono_col)
    if cargo:
        try:
            return -abs(float(_clean_amount(cargo)))
        except ValueError:
            pass
    if abono:
        try:
            return abs(float(_clean_amount(abono)))
        except ValueError:
            pass
    return None


def _cell(row, headers, col):
    if not col:
        return ""
    return (row.get(col) or "").strip()


def _pick_header(prefixes, headers):
    """Devuelve el encabezado real que coincide con alguno de los prefijos."""
    for p in prefixes:
        if p in headers:
            return headers[p]
    return None


def _clean_amount(raw: str) -> str:
    return (raw or "").replace(",", "").replace("$", "").strip()


def _norm_date(raw: str) -> str:
    """Acepta '2025-01-15', '15/01/2025', '20250115' -> 'YYYY-MM-DD'."""
    s = (raw or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return s


def _norm(h: str) -> str:
    """Normaliza un encabezado: minúsculas, sin acentos, sin espacios."""
    h = (h or "").lower().strip()
    h = h.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    return re.sub(r"\s+", "", h)


def _detect_delimiter(lines) -> str:
    """Detecta coma / tab / punto y coma contando su frecuencia en la 1ª línea."""
    first = lines[0] if lines else ""
    counts = {",": first.count(","), "\t": first.count("\t"), ";": first.count(";")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","
