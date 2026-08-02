# -*- coding: utf-8 -*-
"""Minimal CFDI 4.0 XML parser — extracts comprobante, emisor, receptor, conceptos, impuestos."""
from __future__ import annotations

import re
from typing import Any, Optional

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

__all__ = ["CFDIError", "parse_cfdi_4"]


class CFDIError(Exception):
    """Raised when XML cannot be parsed as a CFDI 4.0 document."""
    pass


# Namespace map for CFDI 4.0
NS: dict[str, str] = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "nomina12": "http://www.sat.gob.mx/nomina12",
}

# Simple helper — strip namespace prefix from tag
def _tag(local: str) -> str:
    return f"{{{NS['cfdi']}}}{local}"


def _tfd(tag_local: str) -> str:
    return f"{{{NS['tfd']}}}{tag_local}"


def _float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _str(text: Optional[str]) -> Optional[str]:
    if text is None or not text.strip():
        return None
    return text.strip()


def _find_first(root: ET.Element, tag: str, ns: Optional[dict] = None) -> Optional[ET.Element]:
    ns = ns or NS
    result = root.find(_tag(tag), ns)
    if result is None:
        result = root.find(f".//{tag}", {})
    return result


def _find_text(root: ET.Element, tag: str, ns: Optional[dict] = None) -> Optional[str]:
    el = _find_first(root, tag, ns)
    return el.text.strip() if el is not None and el.text else None


def _children(parent: ET.Element, tag: str, ns: Optional[dict] = None) -> list[ET.Element]:
    ns = ns or NS
    return parent.findall(f"{{{ns['cfdi'] if '{' not in tag else ''}}}{tag.split('}')[-1]}", ns) or []


def _parse_concepto(c: ET.Element) -> dict[str, Any]:
    """Extract fields from a cfdi:Concepto element."""
    result: dict[str, Any] = {
        "descripcion": _str(c.get("Descripcion")) or _str(c.get("descripcion")) or "",
        "cantidad": _float(c.get("Cantidad")) or _float(c.get("cantidad")),
        "valor_unitario": _float(c.get("ValorUnitario")) or _float(c.get("valor_unitario")),
        "importe": _float(c.get("Importe")) or _float(c.get("importe")),
        "clave_prod_serv": _str(c.get("ClaveProdServ")) or _str(c.get("clave_prod_serv")),
        "unidad": _str(c.get("Unidad")) or _str(c.get("unidad")),
        "objeto_imp": _str(c.get("ObjetoImp")) or _str(c.get("objeto_imp")),
    }
    return result


def _parse_impuestos(root: ET.Element) -> dict[str, Any]:
    """Extract totals from cfdi:Impuestos."""
    imp_el = _find_first(root, "Impuestos")
    if imp_el is None:
        return {}

    def _total(tag: str) -> Optional[float]:
        t = imp_el.get(tag, imp_el.get(tag.lower(), None))
        return _float(t)

    result: dict[str, Any] = {
        "total_impuestos_trasladados": _total("TotalImpuestosTrasladados"),
        "total_impuestos_retenidos": _total("TotalImpuestosRetenidos"),
    }

    # ISR / IVA retenido
    retenciones = imp_el.findall(f"{{{NS['cfdi']}}}Retencion")
    isr_retenido: Optional[float] = None
    iva_retenido: Optional[float] = None
    for ret in retenciones:
        imp = ret.get("Impuesto", ret.get("impuesto", ""))
        imp_str = str(imp).strip()
        if imp_str == "001":
            v = _float(ret.get("Importe") or ret.get("importe"))
            if v is not None:
                isr_retenido = (isr_retenido or 0.0) + v
        elif imp_str == "002":
            v = _float(ret.get("Importe") or ret.get("importe"))
            if v is not None:
                iva_retenido = (iva_retenido or 0.0) + v

    result["total_impuestos_retenidos_isr"] = isr_retenido
    result["total_impuestos_retenidos_iva"] = iva_retenido

    # Sum traslados (IVA 002)
    traslados = imp_el.findall(f"{{{NS['cfdi']}}}Traslado")
    iva_trasladado: Optional[float] = None
    for tr in traslados:
        imp_code = str(imp_el.get("Impuesto", "") or imp_el.get("impuesto", "")).strip()
        # Per-tax individual traslado
        imp_code_tr = str(tr.get("Impuesto", tr.get("impuesto", ""))).strip()
        if imp_code_tr == "002" or imp_code == "002":
            v = _float(tr.get("Importe") or tr.get("importe"))
            if v is not None:
                iva_trasladado = (iva_trasladado or 0.0) + v

    # Also pull from the header attribute
    if result.get("total_impuestos_trasladados") is None:
        result["total_impuestos_trasladados"] = iva_trasladado

    return result


def parse_cfdi_4(xml_str: str) -> dict[str, Any]:
    """Parse a CFDI 4.0 XML string and return a flat dict of extracted fields.

    Raises CFDIError if the document is not a valid CFDI Comprobante.
    """
    # Step 1: XML well-formedness
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        raise CFDIError(f"Malformed XML: {exc}")

    # Step 2: Root element must be Comprobante
    if root.tag.endswith("Comprobante") or root.tag == "Comprobante":
        pass  # OK
    elif "{" in root.tag:
        local = root.tag.split("}")[1]
        if local != "Comprobante":
            raise CFDIError(
                f"Root element is '{local}', expected 'Comprobante'. "
                "This may not be a CFDI 4.0 document."
            )
    else:
        raise CFDIError(
            f"Root element is '{root.tag}', expected 'Comprobante'. "
            "This may not be a CFDI document."
        )

    # Step 3: Version attribute
    version = root.get("Version", root.get("version", ""))
    if not version:
        raise CFDIError("Missing Version attribute on Comprobante element.")

    # Step 4: Extract fields
    def _attr(key: str) -> Optional[str]:
        return _str(root.get(key) or root.get(key.lower(), None))

    def _attrf(key: str) -> Optional[float]:
        v = root.get(key) or root.get(key.lower(), None)
        return _float(v)

    result: dict[str, Any] = {
        "version": version,
        "serie": _attr("Serie"),
        "folio": _attr("Folio"),
        "fecha": _attr("Fecha"),
        "forma_pago": _attr("FormaPago") or _attr("forma_pago"),
        "metodo_pago": _attr("MetodoPago") or _attr("metodo_pago"),
        "moneda": _attr("Moneda") or _attr("moneda"),
        "tipo_cambio": _attr("TipoCambio") or _attr("tipo_cambio"),
        "tipo_de_comprobante": _attr("TipoDeComprobante") or _attr("tipo_de_comprobante"),
        "lugar_expedicion": _attr("LugarExpedicion") or _attr("lugar_expedicion"),
        "exportacion": _attr("Exportacion") or _attr("exportacion"),
        "subtotal": _attrf("SubTotal"),
        "descuento": _attrf("Descuento"),
        "total": _attrf("Total"),
        "no_certificado": _attr("NoCertificado"),
        "certificado": _attr("Certificado"),
        "sello": _attr("Sello"),
    }

    # Emisor
    emisor_el = _find_first(root, "Emisor")
    if emisor_el is not None:
        result["emisor"] = {
            "rfc": _str(emisor_el.get("Rfc") or emisor_el.get("rfc", "")) or "",
            "nombre": _str(emisor_el.get("Nombre") or emisor_el.get("nombre")),
            "regimen_fiscal": (
                _str(emisor_el.get("RegimenFiscal") or emisor_el.get("regimen_fiscal"))
            ),
        }
    else:
        result["emisor"] = {"rfc": "", "nombre": None, "regimen_fiscal": None}

    # Receptor
    receptor_el = _find_first(root, "Receptor")
    if receptor_el is not None:
        result["receptor"] = {
            "rfc": _str(receptor_el.get("Rfc") or receptor_el.get("rfc", "")) or "",
            "nombre": _str(receptor_el.get("Nombre") or receptor_el.get("nombre")),
            "regimen_fiscal_receptor": (
                _str(
                    receptor_el.get("RegimenFiscalReceptor")
                    or receptor_el.get("regimen_fiscal_receptor")
                )
            ),
            "uso_cfdi": _str(
                receptor_el.get("UsoCFDI") or receptor_el.get("uso_cfdi")
            ),
            "domicilio_fiscal_receptor": _str(
                receptor_el.get("DomicilioFiscalReceptor")
                or receptor_el.get("domicilio_fiscal_receptor")
            ),
            "residency": _str(
                receptor_el.get("ResidenciaFiscal")
                or receptor_el.get("residency_fiscal")
            ),
            "num_reg_id_trib": _str(
                receptor_el.get("NumRegIdTrib")
                or receptor_el.get("num_reg_id_trib")
            ),
        }
    else:
        result["receptor"] = {
            "rfc": "",
            "nombre": None,
            "regimen_fiscal_receptor": None,
            "uso_cfdi": None,
            "domicilio_fiscal_receptor": None,
        }

    # Conceptos
    conceptos: list[dict[str, Any]] = []
    conceptos_el = _find_first(root, "Conceptos")
    if conceptos_el is not None:
        for c in conceptos_el.findall(f"{{{NS['cfdi']}}}Concepto"):
            conceptos.append(_parse_concepto(c))
        # Also accept bare Concepto (no wrapper)
        if not conceptos:
            for c in root.findall(f"{{{NS['cfdi']}}}Concepto"):
                conceptos.append(_parse_concepto(c))
    else:
        # Try bare Concepto elements
        for c in root.findall(f"{{{NS['cfdi']}}}Concepto"):
            conceptos.append(_parse_concepto(c))

    result["conceptos"] = conceptos

    # Impuestos
    result.update(_parse_impuestos(root))

    # TimbreFiscalDigital (Complemento)
    complemento = _find_first(root, "Complemento")
    uuid: Optional[str] = None
    fecha_timbrado: Optional[str] = None
    if complemento is not None:
        timbre = complemento.find(f"{{{NS['tfd']}}}TimbreFiscalDigital")
        if timbre is None:
            timbre = complemento.find("TimbreFiscalDigital")
        if timbre is not None:
            uuid = _str(timbre.get("UUID") or timbre.get("uuid"))
            fecha_timbrado = _str(
                timbre.get("FechaTimbrado") or timbre.get("fecha_timbrado")
            )
            result["rfc_prov_certif"] = _str(
                timbre.get("RfcProvCertif") or timbre.get("rfc_prov_certif")
            )
            result["sello_cfd"] = _str(
                timbre.get("SelloCFD") or timbre.get("sello_cfd")
            )
            result["sello_sat"] = _str(
                timbre.get("SelloSAT") or timbre.get("sello_sat")
            )
            result["no_certificado_sat"] = _str(
                timbre.get("NoCertificadoSAT")
                or timbre.get("no_certificado_sat")
            )

    result["uuid"] = uuid
    result["fecha_timbrado"] = fecha_timbrado

    return result
