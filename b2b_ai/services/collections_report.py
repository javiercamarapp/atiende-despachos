# -*- coding: utf-8 -*-
"""
collections_report.py — Reportes de cobranza (FASE 3).

Construye vistas de la cartera pendiente para el despacho:
  - aging_report():  cartera agrupada por antigüedad (buckets 0-30/31-60/61-90/90+).
  - projection():    proyección de cobro esperado ponderando cada factura por
                     su score de cobrabilidad (expectativa = monto × score).
  - summary():       resumen ejecutivo de cobranza (montos, indicadores, alertas).

Todos los reportes son JSON-serializables (montos como string) para servirse
por la API sin problemas de precisión.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from b2b_ai.services.collections import (AGE_BUCKETS, age_bucket,
                                         days_overdue)
from b2b_ai.services.collections_templates import format_monto


def _dec(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace(" ", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:  # noqa: BLE001
        return None


def _score_of(inv: Dict[str, Any]) -> float:
    """Score de cobrabilidad ya calculado o 0.0 si no existe."""
    try:
        return float(inv.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _monto_of(inv: Dict[str, Any]) -> Decimal:
    return _dec(inv.get("monto")) or Decimal("0")


# --------------------------------------------------------------------------- #
# aging_report
# --------------------------------------------------------------------------- #
def aging_report(invoices: List[dict], today: Optional[date] = None) -> Dict[str, Any]:
    """Cartera pendiente agrupada por antigüedad.

    `invoices`: lista de dicts con {factura_id, monto, fecha_vencimiento,
    nombre_empresa, score?}. Devuelve:
      - buckets: por bucket {count, monto}
      - total_count / total_monto
      - invoices: cada factura con dias_vencido, bucket y score (>=0).
    """
    today = today or date.today()
    buckets = {b: {"count": 0, "monto": Decimal("0")} for b in AGE_BUCKETS}
    rows = []
    for inv in invoices:
        dias = days_overdue(inv.get("fecha_vencimiento"), today)
        bucket = age_bucket(dias)
        monto = _monto_of(inv)
        score = _score_of(inv)
        buckets[bucket]["count"] += 1
        buckets[bucket]["monto"] += monto
        rows.append({
            "factura_id": inv.get("factura_id"),
            "nombre_empresa": inv.get("nombre_empresa", ""),
            "monto": str(monto),
            "fecha_vencimiento": str(inv.get("fecha_vencimiento", "")),
            "dias_vencido": dias,
            "bucket": bucket,
            "score": score,
        })
    total = sum(b["monto"] for b in buckets.values())
    return {
        "buckets": {b: {"count": v["count"], "monto": str(v["monto"])}
                    for b, v in buckets.items()},
        "total_count": sum(b["count"] for b in buckets.values()),
        "total_monto": str(total),
        "invoices": rows,
    }


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def projection(invoices: List[dict], today: Optional[date] = None) -> Dict[str, Any]:
    """Proyección de cobro esperado por score de cobrabilidad.

    Para cada factura, expectativa de recuperación = monto × score. Agrupa:
      - por bucket de antigüedad (esperado, monto total, tasa esperada).
      - por rango de score (alta >=0.7, media 0.4-0.7, baja <0.4).
    Devuelve montos proyectados como string.
    """
    today = today or date.today()
    por_bucket = {b: {"monto_total": Decimal("0"),
                      "esperado": Decimal("0")} for b in AGE_BUCKETS}
    por_score = {
        "alta": {"count": 0, "esperado": Decimal("0"), "monto_total": Decimal("0")},
        "media": {"count": 0, "esperado": Decimal("0"), "monto_total": Decimal("0")},
        "baja": {"count": 0, "esperado": Decimal("0"), "monto_total": Decimal("0")},
    }

    for inv in invoices:
        monto = _monto_of(inv)
        score = _score_of(inv)
        dias = days_overdue(inv.get("fecha_vencimiento"), today)
        bucket = age_bucket(dias)
        esperado = monto * Decimal(str(score))

        por_bucket[bucket]["monto_total"] += monto
        por_bucket[bucket]["esperado"] += esperado

        if score >= 0.7:
            key = "alta"
        elif score >= 0.4:
            key = "media"
        else:
            key = "baja"
        por_score[key]["count"] += 1
        por_score[key]["monto_total"] += monto
        por_score[key]["esperado"] += esperado

    total = sum(b["monto_total"] for b in por_bucket.values())
    total_esp = sum(b["esperado"] for b in por_bucket.values())

    return {
        "total_cartera": str(total),
        "total_esperado": str(total_esp),
        "tasa_recuperacion_esperada": round(
            float(total_esp / total * 100), 2) if total else 0.0,
        "por_bucket": {
            b: {"monto_total": str(v["monto_total"]),
                "esperado": str(v["esperado"])}
            for b, v in por_bucket.items()
        },
        "por_score": {
            k: {"count": v["count"], "monto_total": str(v["monto_total"]),
                "esperado": str(v["esperado"])}
            for k, v in por_score.items()
        },
    }


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def summary(invoices: List[dict], today: Optional[date] = None) -> Dict[str, Any]:
    """Resumen ejecutivo de cobranza para el despacho.

    Incluye montos por antigüedad, tasas, alertas (facturas en bucket 90+ o
    con score < 0.4) y los 5 montos pendientes más altos. JSON-serializable.
    """
    today = today or date.today()
    aging = aging_report(invoices, today=today)
    proj = projection(invoices, today=today)

    total = Decimal(aging["total_monto"])
    buck = aging["buckets"]

    def _ratio(k):
        t = Decimal(buck[k]["monto"])
        return round(float(t / total * 100), 2) if total else 0.0

    alertas = []
    vencido_90 = Decimal(buck["90+"]["monto"])
    if vencido_90 > 0:
        alertas.append(
            f"{buck['90+']['count']} factura(s) con más de 90 días "
            f"({format_monto(vencido_90)}) requieren escalamiento inmediato.")
    bajos = [i for i in aging["invoices"] if i["score"] < 0.4]
    if bajos:
        alertas.append(
            f"{len(bajos)} factura(s) con score de cobrabilidad bajo (<0.4) "
            f"acumulan {format_monto(sum((_dec(i['monto']) or Decimal('0')) for i in bajos))}.")

    top = sorted(aging["invoices"], key=lambda i: _dec(i["monto"]) or Decimal("0"),
                 reverse=True)[:5]

    return {
        "total_cartera": aging["total_monto"],
        "total_count": aging["total_count"],
        "total_esperado": proj["total_esperado"],
        "tasa_recuperacion_esperada": proj["tasa_recuperacion_esperada"],
        "por_antiguedad": {
            b: {"count": v["count"], "monto": v["monto"],
                "porcentaje": _ratio(b)}
            for b, v in buck.items()
        },
        "alertas": alertas,
        "top_montos": [
            {k: i[k] for k in ("factura_id", "nombre_empresa", "monto",
                               "dias_vencido", "bucket", "score")}
            for i in top
        ],
    }
