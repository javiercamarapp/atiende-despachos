# -*- coding: utf-8 -*-
"""
aggregator.py — Agregación de resultados batch de CFDIs.

Convierte una colección de resultados individuales (parseos o BatchItems)
en un resumen agregado: total procesado, fallidos, suma de montos y un
desglose por RFC emisor/receptor.

Es independiente del servicio batch: trabaja sobre dicts normalizados
(la salida de :mod:`bulk_parser`) o sobre objetos :class:`BatchItem`.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from b2b_ai.features.batch.models import BatchItem, BatchItemStatus

DEFAULT_EMPTY_RFC = "(sin rfc)"


def _rfc_from_result(result: Optional[dict]) -> str:
    """Extrae el RFC emisor de un resultado normalizado de CFDI."""
    if not isinstance(result, dict):
        return DEFAULT_EMPTY_RFC
    rfc = result.get("rfc_emisor") or ""
    if not rfc:
        emisor = result.get("emisor") or {}
        rfc = (emisor.get("rfc") or "").strip()
    return rfc or DEFAULT_EMPTY_RFC


def _rfc_fill(result: Optional[dict]) -> dict:
    """Devuelve el dict manteniendo rfc_emisor en el resultado (no-op safe)."""
    if not isinstance(result, dict):
        return {}
    # Ya incluye rfc_emisor en la forma de bulk_parser; de lo contrario lo
    # derivamos de emisor.rfc para que _rfc_from_result lo encuentre.
    out = dict(result)
    if not out.get("rfc_emisor"):
        emisor = out.get("emisor") or {}
        out["rfc_emisor"] = (emisor.get("rfc") or "").strip()
    return out


def _total_from_result(result: Optional[dict]) -> float:
    """Extrae el total de un resultado normalizado de CFDI (0.0 si falta)."""
    if not isinstance(result, dict):
        return 0.0
    total = result.get("total")
    try:
        return float(total) if total is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def aggregate_results(
    results: List[Dict[str, Any]],
    key: str = "parsed",
) -> Dict[str, Any]:
    """Agrega una lista de resultados de :func:`parse_cfdi_pairs`.

    Params:
        results: lista de dicts con ``{ok, parsed, error}``.
        key: nombre del campo que contiene el parseo normalizado.

    Returns:
        dict:
            {
                "total": int, "processed": int, "failed": int,
                "total_amount": float, "by_rfc": {rfc: {"count", "amount"}},
            }
    """
    total = len(results)
    processed = 0
    failed = 0
    total_amount = 0.0
    by_rfc: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "amount": 0.0})

    for entry in results:
        ok = bool(entry.get("ok"))
        if not ok:
            failed += 1
            continue
        processed += 1
        parsed = entry.get(key) if isinstance(entry.get(key), dict) else None
        rfc = _rfc_from_result(parsed)
        amount = _total_from_result(parsed)
        total_amount += amount
        by_rfc[rfc]["count"] += 1
        by_rfc[rfc]["amount"] += amount

    return {
        "total": total,
        "processed": processed,
        "failed": failed,
        "total_amount": round(total_amount, 2),
        "by_rfc": dict(by_rfc),
    }


def summarize_batch_job(job: Any) -> Dict[str, Any]:
    """Genera un resumen por RFC a partir de un BatchJob.

    Recorre los :class:`BatchItem` del job y construye un agregado que
    complementa a :meth:`BatchJob.summary` con un desglose ``by_rfc``.

    Params:
        job: un objeto con atributos ``items`` (BatchItem[]) y, opcionalmente,
            ``success_count`` / ``failed_count``.

    Returns:
        dict con total, processed, failed, total_amount y by_rfc.
    """
    entries: List[Dict[str, Any]] = []
    for item in getattr(job, "items", []) or []:
        if not isinstance(item, BatchItem):
            continue
        ok = item.status in (BatchItemStatus.SUCCESS,)
        # El resultado normalizado (item.result) no expone "total" a nivel raíz
        # (vive en comprobante.total); usamos item.total para el monto.
        parsed = item.result if isinstance(item.result, dict) else None
        if ok and item.total is not None:
            entries.append({"ok": True, "parsed": {**_rfc_fill(parsed), "total": item.total}})
        else:
            entries.append({"ok": ok, "parsed": parsed, "error": item.error})

    summary = aggregate_results(entries, key="parsed")
    # Reconciliar con contadores oficiales del job si los tiene.
    if hasattr(job, "success_count"):
        summary["processed"] = job.success_count
    if hasattr(job, "failed_count"):
        summary["failed"] = job.failed_count
    return summary
