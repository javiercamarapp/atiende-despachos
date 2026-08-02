# -*- coding: utf-8 -*-
"""adapter.py — Puente entre el formato de salida de `parse_cfdi_4` y el
formato plano que espera el pipeline de bookkeeping.

`parse_cfdi_4()` devuelve un dict con las partes del emisor/receptor anidadas:
    emisor:  {"rfc": "...", "nombre": "...", "regimen_fiscal": "..."}
    receptor:{"rfc": "...", "nombre": "...", "uso_cfdi": "..."}
    tipo_de_comprobante: "I" | "E" | ...

El pipeline de bookkeeping (PipelineOrchestrator._classify_cfdis) lee en la
RAÍZ del dict:
    rfc_emisor, rfc_receptor, tipo, total, subtotal, iva, descripcion,
    uso_cfdi, regimen_emisor, uuid, conceptos

Este adaptador normaliza ambos formatos para que los bloques se conecten
sin fricción (deliverable QA 220: wire end-to-end CFDI→bookkeeping→conciliación).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def to_bookkeeping_format(cfdi_parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte el output de `parse_cfdi_4` al formato plano de bookkeeping.

    Mapeos explícitos:
        emisor['rfc']            -> rfc_emisor
        receptor['rfc']          -> rfc_receptor
        tipo_de_comprobante      -> tipo (y tipo_cfdi)
        total / subtotal / fecha / uuid / conceptos  -> mismos campos

    Además propaga `uso_cfdi`, `regimen_emisor` y calcula `iva` desde los
    impuestos trasladados para que el clasificador tenga todos los inputs.

    Es idempotente y tolerante: si el dict ya está en formato plano (tiene
    `rfc_emisor` en la raíz), se devuelve tal cual.
    """
    if cfdi_parsed is None:
        return {}

    # Idempotencia: si ya es un CFDI adaptado, devolver sin tocar.
    if "rfc_emisor" in cfdi_parsed:
        return cfdi_parsed

    emisor = cfdi_parsed.get("emisor", {}) or {}
    receptor = cfdi_parsed.get("receptor", {}) or {}

    tipo = cfdi_parsed.get("tipo_de_comprobante") or "I"

    # Descripción: concatena las descripciones de los conceptos.
    conceptos = cfdi_parsed.get("conceptos", []) or []
    descripcion = " | ".join(
        str(c.get("descripcion", "")) for c in conceptos if c.get("descripcion")
    )

    iva = cfdi_parsed.get("total_impuestos_trasladados")

    return {
        "uuid": cfdi_parsed.get("uuid"),
        "cfdi_uuid": cfdi_parsed.get("uuid"),
        "rfc_emisor": emisor.get("rfc", ""),
        "rfc_receptor": receptor.get("rfc", ""),
        "tipo": tipo,
        "tipo_cfdi": tipo,
        "fecha": cfdi_parsed.get("fecha"),
        "total": cfdi_parsed.get("total"),
        "subtotal": cfdi_parsed.get("subtotal"),
        "iva": iva,
        "tasa_iva": 0.16 if iva else 0.0,
        "descripcion": descripcion,
        "conceptos": conceptos,
        "uso_cfdi": receptor.get("uso_cfdi", ""),
        "regimen_emisor": emisor.get("regimen_fiscal", ""),
        "emisor": emisor,
        "receptor": receptor,
        "moneda": cfdi_parsed.get("moneda"),
        "tipo_cambio": cfdi_parsed.get("tipo_cambio"),
    }


def adapt_batch(cfdis_parsed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adapta una lista de CFDIs parseados al formato de bookkeeping."""
    return [to_bookkeeping_format(c) for c in (cfdis_parsed or [])]


__all__ = ["to_bookkeeping_format", "adapt_batch"]
