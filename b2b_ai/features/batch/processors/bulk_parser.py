# -*- coding: utf-8 -*-
"""
bulk_parser.py — Parser de CFDIs en lote.

Extrae múltiples documentos CFDI (XML) desde un ZIP de subida y los parsea
a la forma normalizada que devuelve ``parse_cfdi_4``, incluyendo los campos
clave para contabilidad: RFC emisor/receptor, total, UUID (folio fiscal),
fecha y conceptos.

El módulo es independiente del servicio batch (BatchService): no guarda
estado ni dispara webhooks. Solo es responsabilidad de extraer/parsear y
normalizar los datos, dejando la orquestación a los llamadores.
"""
from __future__ import annotations

import io
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.cfdi.parser import CFDIError, parse_cfdi_4

ALLOWED_XML_EXTENSIONS = (".xml",)


def extract_cfdi_pairs(data: bytes, filename: str = "lote.zip") -> List[Tuple[str, str]]:
    """Extrae pares (nombre, contenido_xml) desde un ZIP de XML.

    Solo considera archivos con extensión .xml dentro del ZIP (ignora
    directorios y otros archivos). El contenido se decodifica como UTF-8
    tolerante a errores.

    Raises:
        ValueError: si el ZIP es inválido o está vacío.
    """
    if not data:
        raise ValueError("Contenido vacío: no se recibió el archivo ZIP.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"ZIP inválido: {exc}") from exc

    names = sorted(
        n
        for n in zf.namelist()
        if n.lower().endswith(ALLOWED_XML_EXTENSIONS) and not n.endswith("/")
    )
    if not names:
        raise ValueError("El ZIP no contiene archivos .xml (CFDIs).")

    pairs: List[Tuple[str, str]] = []
    for n in names:
        raw = zf.read(n)
        pairs.append((n, raw.decode("utf-8", errors="replace")))
    return pairs


def parse_cfdi_document(xml_content: str) -> Dict[str, Any]:
    """Parsea un CFDI individual a su forma normalizada.

    Devuelve el dict de ``parse_cfdi_4`` con campos adicionales de alto
    nivel: ``rfc_emisor``, ``rfc_receptor`` y ``conceptos_resumen`` (lista
    de descripciones). Los campos de identificación (uuid, total, fecha,
    emisor/receptor) son de ``parse_cfdi_4``.

    Raises:
        CFDIError: si el XML no es un CFDI válido/parseable.
    """
    parsed = parse_cfdi_4(xml_content)
    emisor = parsed.get("emisor") or {}
    receptor = parsed.get("receptor") or {}
    conceptos = parsed.get("conceptos") or []

    parsed["rfc_emisor"] = (emisor.get("rfc") or "").strip()
    parsed["rfc_receptor"] = (receptor.get("rfc") or "").strip()
    parsed["conceptos_resumen"] = [
        (c.get("descripcion") or "") for c in conceptos
    ]
    return parsed


def parse_cfdi_pairs(
    pairs: List[Tuple[str, str]],
    on_error: str = "raise",
) -> List[Dict[str, Any]]:
    """Parsea una lista de pares (nombre, xml) a resultados normalizados.

    Params:
        pairs: lista de ``(filename, xml_content)`` (típicamente la salida
            de :func:`extract_cfdi_pairs`).
        on_error: ``"raise"`` para abortar ante el primer CFDI inválido;
            ``"skip"`` para registrar el error en ``error`` y continuar.

    Returns:
        Lista de dicts, uno por CFDI:
            {
                "filename": str,
                "ok": bool,
                "parsed": dict | None,      # forma de parse_cfdi_document
                "error": str | None,        # mensaje si falló el parseo
            }
    """
    results: List[Dict[str, Any]] = []
    if on_error not in ("raise", "skip"):
        raise ValueError(f"on_error debe ser 'raise' o 'skip', no {on_error!r}")
    for name, xml in pairs:
        entry: Dict[str, Any] = {"filename": name, "ok": False, "parsed": None, "error": None}
        try:
            entry["parsed"] = parse_cfdi_document(xml)
            entry["ok"] = True
        except (CFDIError, Exception) as exc:  # noqa: BLE001 — cada CFDI es independiente
            entry["error"] = f"{type(exc).__name__}: {exc}"
            if on_error == "raise":
                raise
        results.append(entry)
    return results
