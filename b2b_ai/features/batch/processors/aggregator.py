# -*- coding: utf-8 -*-
"""
aggregator.py — Agregación de resultados batch de CFDIs (clase BatchAggregator).

Convierte una colección de resultados individuales (parseos de CFDIs) en un
resumen agregado: total procesado, fallidos, suma de montos y un desglose por
RFC emisor (items_by_rfc) con conteos y totales. Opcionalmente acepta un
desglose por categoría si los resultados llevan la clave ``category``.

La clase ``BatchAggregator`` es la API principal (entregable):

    agg = BatchAggregator()
    report = agg.aggregate(results)   # results: list[dict]

Las funciones helper (``aggregate_results``, ``summarize_batch_job``) se
conservan por compatibilidad con el test existente.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from b2b_ai.features.batch.models import BatchItem, BatchItemStatus

logger = logging.getLogger("b2b_ai.batch.processors.aggregator")

DEFAULT_EMPTY_RFC = "(sin rfc)"
DEFAULT_EMPTY_CATEGORY = "(sin categoría)"


# ---------------------------------------------------------------------------
# Helpers de extracción (compartidos)
# ---------------------------------------------------------------------------


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


def _category_from_result(result: Optional[dict]) -> str:
    """Extrae la categoría de un resultado (o el bucket vacío)."""
    if not isinstance(result, dict):
        return DEFAULT_EMPTY_CATEGORY
    cat = result.get("category")
    if cat is None or str(cat).strip() == "":
        return DEFAULT_EMPTY_CATEGORY
    return str(cat).strip()


def _is_success(entry: dict, key: str = "parsed") -> bool:
    """Determina si una entrada del lote se cuenta como procesada OK."""
    ok = entry.get("ok")
    if ok is not None:
        return bool(ok)
    # Entrada "desnuda": es un resultado parseado directamente.
    return isinstance(entry.get(key), dict) or _total_from_result(entry) != 0.0 \
        or bool(entry.get("rfc_emisor"))


# ---------------------------------------------------------------------------
# Funciones helper (compatibilidad con test_batch_processors.py)
# ---------------------------------------------------------------------------


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
        parsed = item.result if isinstance(item.result, dict) else None
        if ok and item.total is not None:
            entries.append({"ok": True, "parsed": {**_rfc_fill(parsed), "total": item.total}})
        else:
            entries.append({"ok": ok, "parsed": parsed, "error": item.error})

    summary = aggregate_results(entries, key="parsed")
    if hasattr(job, "success_count"):
        summary["processed"] = job.success_count
    if hasattr(job, "failed_count"):
        summary["failed"] = job.failed_count
    return summary


# ---------------------------------------------------------------------------
# BatchAggregator — API de clase (entregable)
# ---------------------------------------------------------------------------


class BatchAggregator:
    """Agrega resultados individuales de CFDIs en un resumen agregado.

    Trabaja sobre dicts normalizados (la salida de :class:`BulkCfdiParser`)
    o sobre la forma ``{ok, parsed, error}`` del lote. Soporta un desglose
    opcional por categoría si los resultados llevan la clave ``category``.
    """

    def aggregate(
        self,
        results: List[Dict[str, Any]],
        key: str = "parsed",
    ) -> Dict[str, Any]:
        """Agrega una lista de resultados a un reporte agregado.

        Params:
            results: lista de dicts. Cada entrada puede ser:
                - la forma desnuda del parseo (con rfc_emisor/total/category),
                  contada como procesada, o
                - la forma ``{ok, parsed, error}`` del lote (con
                  ``ok=False`` se cuenta como fallida).
            key: campo que contiene el parseo normalizado (para la forma
                ``{ok, parsed}``).

        Returns:
            dict:
                {
                    "total_processed": int,
                    "total_failed": int,
                    "items_by_rfc": {rfc: {"count": int, "total": float}},
                    "summary": {
                        "total": int,
                        "processed": int,
                        "failed": int,
                        "total_amount": float,
                    },
                }
            Si algún resultado trae la clave ``category``, además incluye:
                {
                    "items_by_category": {cat: {"count": int, "total": float}},
                }
        """
        total_processed = 0
        total_failed = 0
        total_amount = 0.0

        items_by_rfc: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "total": 0.0})
        has_category = any(
            isinstance(r, dict)
            and (
                "category" in r
                or (
                    isinstance(r.get(key), dict)
                    and "category" in r.get(key)
                )
            )
            for r in results
        )
        items_by_category: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "total": 0.0}
        )

        for entry in results:
            if not isinstance(entry, dict):
                total_failed += 1
                continue

            ok = _is_success(entry, key=key)
            if not ok:
                total_failed += 1
                continue

            total_processed += 1
            parsed = entry.get(key) if isinstance(entry.get(key), dict) else entry
            rfc = _rfc_from_result(parsed)
            amount = _total_from_result(parsed)
            total_amount += amount

            items_by_rfc[rfc]["count"] += 1
            items_by_rfc[rfc]["total"] += amount

            if has_category:
                cat = _category_from_result(parsed)
                items_by_category[cat]["count"] += 1
                items_by_category[cat]["total"] += amount

        report: Dict[str, Any] = {
            "total_processed": total_processed,
            "total_failed": total_failed,
            "items_by_rfc": dict(items_by_rfc),
            "summary": {
                "total": total_processed + total_failed,
                "processed": total_processed,
                "failed": total_failed,
                "total_amount": round(total_amount, 2),
            },
        }
        if has_category:
            report["items_by_category"] = dict(items_by_category)

        return report
