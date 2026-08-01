# -*- coding: utf-8 -*-
"""
anomaly.py — Detección de anomalías en facturas (FASE 2).

Señala facturas que presentan riesgos de operaciones simuladas, duplicidad,
inconsistencias de IVA o montos atípicos, para escalar a revisión humana.

Detecciones:
  1. Duplicado          : mismo monto + RFC + fecha dentro de 3 días.
  2. Monto atípico      : monto > 2 desviaciones estándar del promedio del
                          proveedor (requiere historial >= 3 facturas).
  3. IVA inconsistente  : montoIVA != subtotal * tasaIVA (tolerancia 0.01).
  4. Proveedor nuevo    : RFC sin historial previo (flag informativo).

Cada anomalía lleva `severity` (low/medium/high/critical), `supuestos`
documentados y `referencia_legal`. La detección NO decide por sí sola: marca
riesgo y delega la conclusión al humano (de `04-leyes-fiscales.md`).

Referencias legales:
  - Operaciones simuladas / comprobantes duplicados: CFF Arts. 5-A, 29-A
    fracc. V, 109 fracc. III y 113-Bis.
  - Inconsistencia de IVA: Ley del IVA Arts. 1, 5 y 6; CFF Art. 29-A fracc. V.
  - Monto atípico / proveedor nuevo: señales de riesgo (materialidad), sin
    presunción de infracción — criterio contable y fiscal del profesional.
"""
from __future__ import annotations

from datetime import datetime
from statistics import mean, pstdev

SEVERITIES = ("low", "medium", "high", "critical")


def _dec(v):
    """Convierte a float de forma tolerante (None -> None)."""
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _norm_fecha(f):
    """Devuelve la parte de fecha (YYYY-MM-DD) o None."""
    if not f:
        return None
    s = str(f)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _close(a, b, tol=0.01):
    """True si a y b (float o None) coinciden dentro de tolerancia."""
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _anomaly(tipo, severity, descripcion, supuestos, referencia_legal, detalle):
    return {
        "tipo": tipo,
        "severity": severity,
        "descripcion": descripcion,
        "supuestos": supuestos,
        "referencia_legal": referencia_legal,
        "detalle": detalle,
    }


def _check_duplicate(invoice, historical):
    """Mismo folio_fiscal + RFC + monto + fecha dentro de 3 días -> anomalía."""
    inv_total = _dec(invoice.get("total"))
    inv_rfc = invoice.get("emisor_rfc")
    inv_date = _norm_fecha(invoice.get("fecha"))
    inv_folio = invoice.get("folio_fiscal")
    if inv_total is None or not inv_rfc or inv_date is None:
        return []
    out = []
    for h in historical:
        if (h.get("emisor_rfc") or "") != inv_rfc:
            continue
        # Si ambos tienen folio_fiscal, debe coincidir para ser duplicado
        h_folio = h.get("folio_fiscal")
        if inv_folio and h_folio and inv_folio != h_folio:
            continue
        h_total = _dec(h.get("total"))
        h_date = _norm_fecha(h.get("fecha"))
        if h_total is None or h_date is None:
            continue
        if _close(inv_total, h_total) and abs((inv_date - h_date).days) <= 3:
            out.append(_anomaly(
                "duplicado", "high",
                "Posible factura duplicada: mismo monto, RFC y fecha (<=3 días).",
                ["Compara contra el historial de facturas del mismo RFC.",
                 "Requiere confirmar que no sea un doble cargo o una operación "
                 "simulada antes de registrar la póliza."],
                "CFF Arts. 5-A, 29-A fracc. V, 109 fracc. III y 113-Bis.",
                {"monto": inv_total, "rfc": inv_rfc, "fecha": invoice.get("fecha"),
                 "historico": h.get("folio_fiscal") or h.get("archivo", ""),
                 "dias_diferencia": abs((inv_date - h_date).days)},
            ))
    return out


def _check_atypical_amount(invoice, historical):
    """Monto > 2 desviaciones estándar del promedio del proveedor (>=3 datos)."""
    inv_total = _dec(invoice.get("total"))
    inv_rfc = invoice.get("emisor_rfc")
    if inv_total is None or not inv_rfc:
        return []
    totals = [_dec(h.get("total")) for h in historical
              if (h.get("emisor_rfc") or "") == inv_rfc]
    totals = [t for t in totals if t is not None]
    if len(totals) < 3:
        return []
    media = mean(totals)
    desv = pstdev(totals)
    if desv == 0:
        # Historial plano: cualquier monto distinto es atípico.
        atipico = not _close(inv_total, media, 0.01)
    else:
        atipico = abs(inv_total - media) > 2 * desv
    if not atipico:
        return []
    return [_anomaly(
        "monto_atipico", "medium",
        "Monto fuera de rango respecto al historial del proveedor "
        "(> 2 desviaciones estándar).",
        ["Se asume que el historial del proveedor es representativo.",
         "Señal de riesgo de materialidad, no presunción de infracción."],
        "Criterio contable/fiscal del profesional (CFF Art. 29-A fracc. V).",
        {"monto": inv_total, "promedio_proveedor": round(media, 2),
         "desviacion_estandar": round(desv, 2), "n_historial": len(totals)},
    )]


def _check_iva(invoice):
    """montoIVA != subtotal * tasaIVA (tolerancia 0.01)."""
    subtotal = _dec(invoice.get("subtotal"))
    iva = _dec(invoice.get("iva"))
    if subtotal is None or iva is None:
        return []
    tasa = None
    try:
        tasa = float(invoice.get("tasa_iva") or 0.16)
    except (TypeError, ValueError):
        tasa = 0.16
    esperado = subtotal * tasa
    if _close(iva, esperado, 0.01):
        return []
    return [_anomaly(
        "iva_inconsistente", "medium",
        "El IVA trasladado no coincide con subtotal * tasa.",
        ["Se asume tasa de IVA del 16% salvo que el comprobante indique otra.",
         "Puede haber retenciones o tasa distinta (LIVA); validar contra el CFDI."],
        "Ley del IVA Arts. 1, 5 y 6; CFF Art. 29-A fracc. V.",
        {"subtotal": subtotal, "iva_declarado": iva,
         "iva_esperado": round(esperado, 2), "tasa": tasa},
    )]


def _check_new_provider(invoice, historical):
    """RFC del emisor sin historial previo -> flag informativo low."""
    inv_rfc = invoice.get("emisor_rfc")
    if not inv_rfc:
        return []
    if any((h.get("emisor_rfc") or "") == inv_rfc for h in historical):
        return []
    return [_anomaly(
        "proveedor_nuevo", "low",
        "Proveedor nuevo sin historial de facturas previo.",
        ["No implica infracción: es un flag para validar el alta del proveedor "
         "y sus datos fiscales."],
        "Validación fiscal de identidad del emisor (CFF Art. 29-A).",
        {"rfc": inv_rfc},
    )]


def detect_anomalies(invoice, historical=None):
    """Detecta todas las anomalías de una factura contra su historial.

    historical: lista de dicts de facturas previas con al menos {emisor_rfc,
    total, fecha}. Devuelve lista de dicts de anomalías (vacía si no hay).
    """
    historical = historical or []
    checks = [
        _check_duplicate(invoice, historical),
        _check_atypical_amount(invoice, historical),
        _check_iva(invoice),
        _check_new_provider(invoice, historical),
    ]
    return [a for group in checks for a in group]


def summarize_anomalies(anomalies):
    """Resume una lista de anomalías: cuenta por tipo y severidad máxima.

    Devuelve {total, por_tipo, por_severidad, max_severity}.
    """
    if not anomalies:
        return {"total": 0, "por_tipo": {}, "por_severidad": {},
                "max_severity": None}
    por_tipo, por_sev = {}, {}
    for a in anomalies:
        por_tipo[a["tipo"]] = por_tipo.get(a["tipo"], 0) + 1
        por_sev[a["severity"]] = por_sev.get(a["severity"], 0) + 1
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    max_sev = max((a["severity"] for a in anomalies),
                  key=lambda s: rank[s])
    return {"total": len(anomalies), "por_tipo": por_tipo,
            "por_severidad": por_sev, "max_severity": max_sev}
