# -*- coding: utf-8 -*-
"""
bulk_parser.py — Parser de CFDIs en lote (clase BulkCfdiParser).

Extrae múltiples documentos CFDI (XML) desde un ZIP de subida y los parsea
a una forma normalizada. A diferencia del parser monofunción ``parse_cfdi_4``
(del módulo ``b2b_ai.cfdi.parser``), esta clase es **agnóstica al namespace**:
detecta el namespace CFDI de la raíz (http://www.sat.gob.mx/cfd/3 para CFDI 3.3,
http://www.sat.gob.mx/cfd/4 para CFDI 4.0) y extrae los campos clave para
contabilidad:

  - RFC emisor, RFC receptor
  - total
  - UUID (TimbreFiscalDigital)
  - fecha
  - conceptos (partidas / line items)

El módulo es independiente del servicio batch (BatchService): no guarda
estado ni dispara webhooks. Solo es responsabilidad de extraer/parsear y
normalizar los datos, dejando la orquestación a los llamadores.

Error handling: un CFDI malformado se registra en el logger y se omite
(skip), nunca aborta el lote completo. Las funciones helper monofunción
(``extract_cfdi_pairs``, ``parse_cfdi_document``, ``parse_cfdi_pairs``)
se conservan por compatibilidad con el test existente.
"""
from __future__ import annotations

import io
import logging
import zipfile
from typing import Any, Dict, List, Optional, Tuple

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

from b2b_ai.cfdi.parser import CFDIError, parse_cfdi_4

logger = logging.getLogger("b2b_ai.batch.processors.bulk_parser")

ALLOWED_XML_EXTENSIONS = (".xml",)

# Namespace del TimbreFiscalDigital (complemento) — común a CFDI 3.3 y 4.0.
TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"
# Namespace CFDI 3.3 exigido por el entregable (además del 4.0 del repo).
CFDI_NS_33 = "http://www.sat.gob.mx/cfd/3"
CFDI_NS_40 = "http://www.sat.gob.mx/cfd/4"


# ---------------------------------------------------------------------------
# Helpers de bajo nivel (compartidos por funciones y clase)
# ---------------------------------------------------------------------------


def _cfdi_ns(root: ET.Element) -> str:
    """Detecta el namespace CFDI de la raíz del documento.

    El tag del elemento raíz tiene la forma ``{namespace}Comprobante``.
    Devuelve el namespace, o el 4.0 por defecto si no puede detectarlo.
    """
    tag = getattr(root, "tag", "") or ""
    if tag.startswith("{"):
        ns = tag.split("}")[0][1:]
        if ns.endswith(("/cfd/3", "/cfd/4")):
            return ns
    return CFDI_NS_40


def _q(ns: str, local: str) -> str:
    """Convierte un nombre local en un Clark-notation tag con namespace."""
    return f"{{{ns}}}{local}"


def _attr(el: Optional[ET.Element], *names: str) -> Optional[str]:
    """Devuelve el primer atributo no vacío de una lista de candidatos."""
    if el is None:
        return None
    for n in names:
        v = el.get(n)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Funciones helper (compatibilidad con test_batch_processors.py)
# ---------------------------------------------------------------------------


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
    """Parsea un CFDI individual a su forma normalizada (helper).

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


# ---------------------------------------------------------------------------
# BulkCfdiParser — API de clase (entregable)
# ---------------------------------------------------------------------------


class BulkCfdiParser:
    """Parsea múltiples XML de CFDIs desde un ZIP (o lista de XMLs).

    Detecta el namespace CFDI de cada documento (3.3 o 4.0) y extrae:
    RFC emisor/receptor, total, UUID (TimbreFiscalDigital), fecha y conceptos
    (line items). Un documento malformado se registra en el logger y se omite;
    nunca aborta el lote.

    Uso:
        parser = BulkCfdiParser()
        parsed = parser.parse_zip(zip_bytes)          # -> List[dict]
        # o bien, para un solo XML:
        doc = parser.parse_xml(xml_str)               # -> dict
    """

    def __init__(self, on_error: str = "skip", logger_: Optional[logging.Logger] = None):
        self.on_error = on_error
        self.logger = logger_ or logger

    # ------------------------------------------------------------------
    # Extracción de XMLs desde ZIP
    # ------------------------------------------------------------------
    def extract_xmls(self, data: bytes) -> List[Tuple[str, str]]:
        """Extrae pares (nombre, contenido_xml) desde un ZIP de XML."""
        return extract_cfdi_pairs(data)

    # ------------------------------------------------------------------
    # Parseo de un documento individual
    # ------------------------------------------------------------------
    def parse_xml(self, xml_content: str) -> Dict[str, Any]:
        """Parsea un único CFDI a un dict normalizado.

        Returns:
            {
                "rfc_emisor": str,
                "rfc_receptor": str,
                "total": float | None,
                "uuid": str | None,          # UUID del TimbreFiscalDigital
                "fecha": str | None,
                "conceptos": [ {descripcion, cantidad, valor_unitario,
                                importe, clave_prod_serv, unidad, objeto_imp}, ... ],
                "namespace": str,            # namespace CFDI detectado
                # además conserva la forma completa de parse_cfdi_4 bajo
                # "_cfdi_4" para quien quiera los campos extendidos.
                "_cfdi_4": dict,
            }

        Raises:
            CFDIError: si el XML no es un CFDI válido/parseable.
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            raise CFDIError(f"XML malformado: {exc}") from exc

        if not (getattr(root, "tag", "").endswith("Comprobante")):
            raise CFDIError(
                "El elemento raíz no es 'Comprobante'. Esto no es un CFDI."
            )

        ns = _cfdi_ns(root)

        emisor = root.find(_q(ns, "Emisor"))
        receptor = root.find(_q(ns, "Receptor"))
        conceptos_el = root.find(_q(ns, "Conceptos"))
        complemento = root.find(_q(ns, "Complemento"))

        rfc_emisor = _attr(emisor, "Rfc", "rfc") or ""
        rfc_receptor = _attr(receptor, "Rfc", "rfc") or ""

        # UUID y FechaTimbrado desde el complemento TimbreFiscalDigital.
        uuid: Optional[str] = None
        fecha_timbrado: Optional[str] = None
        if complemento is not None:
            timbre = complemento.find(_q(TFD_NS, "TimbreFiscalDigital"))
            if timbre is None:
                # tolera timbre sin namespace declarado
                timbre = complemento.find("TimbreFiscalDigital")
            if timbre is not None:
                uuid = _attr(timbre, "UUID", "uuid")
                fecha_timbrado = _attr(timbre, "FechaTimbrado", "fecha_timbrado")

        # Conceptos (line items).
        conceptos: List[Dict[str, Any]] = []
        if conceptos_el is not None:
            for c in conceptos_el.findall(_q(ns, "Concepto")):
                conceptos.append(_parse_concepto_el(c))

        fecha = _attr(root, "Fecha", "fecha")
        total = _to_float(_attr(root, "Total", "total"))

        result = {
            "rfc_emisor": rfc_emisor,
            "rfc_receptor": rfc_receptor,
            "total": total,
            "uuid": uuid,
            "fecha": fecha,
            "fecha_timbrado": fecha_timbrado,
            "conceptos": conceptos,
            "conceptos_resumen": [c.get("descripcion") or "" for c in conceptos],
            "namespace": ns,
        }

        # Conservamos la forma completa de parse_cfdi_4 (si el doc es 4.0)
        # para no perder los campos extendidos del repo.
        try:
            result["_cfdi_4"] = parse_cfdi_4(xml_content)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("parse_cfdi_4 falló para un CFDI (%s); se usa forma ligera.", exc)

        return result

    # ------------------------------------------------------------------
    # Parseo en lote desde ZIP
    # ------------------------------------------------------------------
    def parse_zip(self, data: bytes) -> List[Dict[str, Any]]:
        """Parsea todos los XML de un ZIP subido y devuelve los parseados.

        Un CFDI malformado se registra en el logger (skip) y NO aparece en la
        lista devuelta; el lote nunca aborta.

        Returns:
            Lista de dicts normalizados (uno por CFDI parseado correctamente).
        """
        pairs = extract_cfdi_pairs(data)
        return self.parse_pairs(pairs)

    # ------------------------------------------------------------------
    # Parseo en lote desde pares (nombre, xml)
    # ------------------------------------------------------------------
    def parse_pairs(self, pairs: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        """Parsea una lista de pares (nombre, xml), saltando los malformados.

        Returns:
            Lista de dicts normalizados, sin incluir los que fallaron.
        """
        results: List[Dict[str, Any]] = []
        for name, xml in pairs:
            try:
                parsed = self.parse_xml(xml)
                parsed["filename"] = name
                results.append(parsed)
            except Exception as exc:  # noqa: BLE001 — cada CFDI es independiente
                self.logger.warning("Skip CFDI malformado %r: %s", name, exc)
                if self.on_error == "raise":
                    raise
        return results

    # ------------------------------------------------------------------
    # Método único (paridad con el entrypoint del test)
    # ------------------------------------------------------------------
    def parse(self, data: bytes) -> List[Dict[str, Any]]:
        """Alias de :meth:`parse_zip` — parsea un ZIP de CFDIs."""
        return self.parse_zip(data)


def _parse_concepto_el(c: ET.Element) -> Dict[str, Any]:
    """Extrae los campos de un elemento cfdi:Concepto."""
    return {
        "descripcion": _attr(c, "Descripcion", "descripcion") or "",
        "cantidad": _to_float(_attr(c, "Cantidad", "cantidad")),
        "valor_unitario": _to_float(_attr(c, "ValorUnitario", "valor_unitario")),
        "importe": _to_float(_attr(c, "Importe", "importe")),
        "clave_prod_serv": _attr(c, "ClaveProdServ", "clave_prod_serv"),
        "unidad": _attr(c, "Unidad", "unidad"),
        "objeto_imp": _attr(c, "ObjetoImp", "objeto_imp"),
    }
