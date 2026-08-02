# -*- coding: utf-8 -*-
"""
report.py — Generador de reportes (mensuales, por categoría, por tenant).

Produce agregados sobre los registros de facturas (los que la DB expone vía
`list_invoices`). Salida orientada a consumo humano/analista con evidencia,
no a presentación fiscal.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _periodo(fecha: Any) -> str:
    return str(fecha)[:7] if fecha else "sin-fecha"


def generate_report(
    invoices: List[Dict[str, Any]],
    period: Optional[str] = None,
    tenant_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Genera un reporte agregado de facturas.

    invoices: lista de dicts con al menos {fecha, subtotal, iva, total,
    categoria, tenant_id, valido}.
    period: 'YYYY-MM' o None (todos). Devuelve dict con agregados:
    totales, conteos válidas/inválidas y desglose por categoría y por mes.
    """
    rows = list(invoices)
    if period:
        rows = [r for r in rows if _periodo(r.get("fecha")) == period]
    if tenant_id is not None:
        rows = [r for r in rows if str(r.get("tenant_id")) == str(tenant_id)]

    total = sum(_dec(r.get("total")) for r in rows)
    subtotal = sum(_dec(r.get("subtotal")) for r in rows)
    iva = sum(_dec(r.get("iva")) for r in rows)
    validas = sum(1 for r in rows if r.get("valido") in (1, True, "1", "SI"))
    invalidas = len(rows) - validas

    por_categoria = defaultdict(lambda: {"count": 0, "total": Decimal("0")})
    por_mes = defaultdict(lambda: {"count": 0, "total": Decimal("0")})
    for r in rows:
        cat = r.get("categoria", "desconocido")
        por_categoria[cat]["count"] += 1
        por_categoria[cat]["total"] += _dec(r.get("total"))
        mes = _periodo(r.get("fecha"))
        por_mes[mes]["count"] += 1
        por_mes[mes]["total"] += _dec(r.get("total"))

    def fmt(d):
        return {k: {"count": v["count"], "total": str(v["total"])}
                for k, v in d.items()}

    return {
        "period": period,
        "tenant_id": tenant_id,
        "facturas": len(rows),
        "validas": validas,
        "invalidas": invalidas,
        "subtotal": str(subtotal),
        "iva": str(iva),
        "total": str(total),
        "por_categoria": fmt(por_categoria),
        "por_mes": fmt(por_mes),
    }
