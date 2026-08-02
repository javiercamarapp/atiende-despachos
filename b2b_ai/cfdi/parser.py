# -*- coding: utf-8 -*-
"""
parser.py — Parser completo de CFDI 4.0 (y tolerante a 3.3).

Extrae TODOS los campos relevantes: atributos del Comprobante, Emisor,
Receptor, Conceptos (con desglose de impuestos por concepto), Impuestos
globales (traslados y retenciones), complementos (TimbreFiscalDigital, Pago,
Nomina) y CfdiRelacionados.

Devuelve un dict JSON-serializable (Decimals convertidos a str en el dict
de salida de alto nivel, y también se exponen en Decimal en `_raw`).
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from datetime import datetime

from lxml import etree
from b2b_ai.cfdi.xml_security import safe_parse, safe_fromstring

NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "cfdi33": "http://www.sat.gob.mx/cfd/3",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "pago10": "http://www.sat.gob.mx/Pagos",
    "pago20": "http://www.sat.gob.mx/Pagos20",
    "nomina12": "http://www.sat.gob.mx/nomina12",
    "cartaporte31": "http://www.sat.gob.mx/CartaPorte31",  # FIS-01
    "cartaporte30": "http://www.sat.gob.mx/CartaPorte30",  # FIS-01
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

# Generic RFCs for CFDI Global detection (CFF Art. 29, Anexo 20) — FIS-02
_GENERIC_RFCS = {"XAXX010101000", "XEXX010101000", "XAXX010101001"}


class CFDIError(Exception):
    """Raised when the file is not a parseable CFDI."""


def _dec(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _localname(node):
    return etree.QName(node).localname


def _find_first(root, localname, start=None):
    """Devuelve el primer descendiente cuyo localname coincida, o None."""
    node = start or root
    for child in node.iter():
        if _localname(child) == localname:
            return child
    return None


def _iso_to_date(fecha_str):
    """Convierte una fecha ISO a datetime; None si no es válida."""
    if not fecha_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(fecha_str, fmt)
        except ValueError:
            continue
    return None


def _get_text(node, localname):
    child = _find_first(node, localname)
    return child.text.strip() if child is not None and child.text else ""


def _all_children(root, localname):
    return [c for c in root.iter() if _localname(c) == localname]


def parse_cfdi(xml_path):
    """Lee un CFDI XML y devuelve un dict normalizado con todos los campos."""
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    try:
        tree = safe_parse(xml_path)
    except etree.XMLSyntaxError as e:
        raise CFDIError(f"XML mal formado: {e}") from e
    except ValueError as e:
        raise CFDIError(str(e)) from e
    root = tree.getroot()

    if _localname(root) != "Comprobante":
        raise CFDIError(f"{os.path.basename(xml_path)} no es un CFDI "
                        "(root no es 'Comprobante')")

    # ---- Atributos del comprobante ----
    def attr(name):
        return root.get(name, "")

    version = attr("Version")
    tipo = attr("TipoDeComprobante")  # I, E, T, P, N
    fecha = attr("Fecha")
    serie, folio = attr("Serie"), attr("Folio")
    forma_pago = attr("FormaPago")
    metodo_pago = attr("MetodoPago")  # PUE / PPD
    moneda = attr("Moneda")
    tipo_cambio = attr("TipoCambio")
    lugar_expedicion = attr("LugarExpedicion")
    exportacion = attr("Exportacion")
    confirmacion = attr("Confirmacion")
    sello = attr("Sello")
    no_certificado = attr("NoCertificado")
    certificado = attr("Certificado")

    subtotal = _dec(attr("SubTotal"))
    descuento = _dec(attr("Descuento"))
    total = _dec(attr("Total"))

    # ---- Emisor / Receptor ----
    emisor = _find_first(root, "Emisor")
    receptor = _find_first(root, "Receptor")

    def party(node):
        if node is None:
            return {}
        return {
            "rfc": node.get("Rfc", ""),
            "nombre": node.get("Nombre", ""),
            "regimen_fiscal": node.get("RegimenFiscal", ""),
            "codigo_postal": node.get("DomicilioFiscalReceptor", "")
            if _localname(node) == "Receptor" else node.get("LugarExpedicion", ""),
        }

    emisor_d = party(emisor)
    receptor_d = party(receptor)
    if receptor is not None:
        receptor_d["uso_cfdi"] = receptor.get("UsoCFDI", "")

    # ---- Conceptos (con impuestos por concepto) ----
    conceptos = []
    claves_prod = []
    for conc in _all_children(root, "Concepto"):
        c = {
            "clave_prod_serv": conc.get("ClaveProdServ", ""),
            "no_identificacion": conc.get("NoIdentificacion", ""),
            "cantidad": _dec(conc.get("Cantidad")),
            "clave_unidad": conc.get("ClaveUnidad", ""),
            "unidad": conc.get("Unidad", ""),
            "descripcion": conc.get("Descripcion", ""),
            "valor_unitario": _dec(conc.get("ValorUnitario")),
            "importe": _dec(conc.get("Importe")),
            "descuento": _dec(conc.get("Descuento")),
            "objeto_imp": conc.get("ObjetoImp", ""),
            "traslados": [],
            "retenciones": [],
        }
        for tr in _all_children(conc, "Traslado"):
            c["traslados"].append({
                "base": _dec(tr.get("Base")),
                "impuesto": tr.get("Impuesto", ""),
                "tipo_factor": tr.get("TipoFactor", ""),
                "tasa_cuota": tr.get("TasaOCuota", ""),
                "importe": _dec(tr.get("Importe")),
            })
        for rt in _all_children(conc, "Retencion"):
            c["retenciones"].append({
                "base": _dec(rt.get("Base")),
                "impuesto": rt.get("Impuesto", ""),
                "tipo_factor": rt.get("TipoFactor", ""),
                "tasa_cuota": rt.get("TasaOCuota", ""),
                "importe": _dec(rt.get("Importe")),
            })
        if c["clave_prod_serv"]:
            claves_prod.append(c["clave_prod_serv"])
        conceptos.append(c)

    # ---- Impuestos globales (nodo Impuestos directo del Comprobante) ----
    traslados = []
    retenciones = []
    global_impuestos = None
    for child in root:
        if _localname(child) == "Impuestos":
            global_impuestos = child
            break
    if global_impuestos is not None:
        for node in global_impuestos.iter():
            ln = _localname(node)
            if ln == "Traslado":
                traslados.append({
                    "base": _dec(node.get("Base")),
                    "impuesto": node.get("Impuesto", ""),
                    "tipo_factor": node.get("TipoFactor", ""),
                    "tasa_cuota": node.get("TasaOCuota", ""),
                    "importe": _dec(node.get("Importe")),
                })
            elif ln == "Retencion":
                retenciones.append({
                    "base": _dec(node.get("Base")),
                    "impuesto": node.get("Impuesto", ""),
                    "tipo_factor": node.get("TipoFactor", ""),
                    "tasa_cuota": node.get("TasaOCuota", ""),
                    "importe": _dec(node.get("Importe")),
                })

    # Sum ALL IVA (002) transfers -- SAT groups by (Impuesto, TipoFactor, TasaOCuota)
    iva_list = [t["importe"] for t in traslados if t["impuesto"] == "002" and t["importe"] is not None]
    iva = sum(iva_list) if iva_list else None
    ieps_list = [t["importe"] for t in traslados if t["impuesto"] == "003" and t["importe"] is not None]
    ieps = sum(ieps_list) if ieps_list else None
    ret_isr = sum((r["importe"] or Decimal("0")) for r in retenciones if r["impuesto"] == "001") or None
    ret_iva = sum((r["importe"] or Decimal("0")) for r in retenciones if r["impuesto"] == "002") or None

    # ---- Complemento TimbreFiscalDigital ----
    folio_fiscal = ""
    fecha_timbrado = ""
    for node in root.iter():
        if _localname(node) == "TimbreFiscalDigital":
            folio_fiscal = node.get("UUID", "")
            fecha_timbrado = node.get("FechaTimbrado", "")
            break

    # ---- CfdiRelacionados ----
    # BUG-F5: Also extract TipoRelacion from parent CfdiRelacionados node
    relacionados = []
    tipo_relacion = ""
    for node in root.iter():
        if _localname(node) == "CfdiRelacionados":
            tipo_relacion = node.get("TipoRelacion", "")
        if _localname(node) == "CfdiRelacionado":
            relacionados.append(node.get("UUID", ""))

    # ---- Complemento de Pagos (PPD) ----
    pagos = []
    for node in root.iter():
        if _localname(node) == "Pago":
            pago = {
                "fecha_pago": node.get("FechaPago", ""),
                "forma_pago": node.get("FormaPago", ""),
                "moneda": node.get("Moneda", ""),
                "tipo_cambio": node.get("TipoCambio", ""),
                "monto": _dec(node.get("Monto")),
                "doctos_relacionados": [],
            }
            for doc in _all_children(node, "DoctoRelacionado"):
                pago["doctos_relacionados"].append({
                    "id_documento": doc.get("IdDocumento", ""),
                    "folio": doc.get("Folio", ""),
                    "moneda": doc.get("MonedaDR", ""),
                    "metodo_pago": doc.get("MetodoDePagoDR", ""),
                    "num_parcialidad": doc.get("NumParcialidad", ""),
                    "imp_saldo_ant": _dec(doc.get("ImpSaldoAnt")),
                    "imp_pagado": _dec(doc.get("ImpPagado")),
                    "imp_saldo_insoluto": _dec(doc.get("ImpSaldoInsoluto")),
                })
            pagos.append(pago)

    # ---- Complemento de Nómina ----
    nomina = None
    nom_node = _find_first(root, "Nomina")
    if nom_node is not None:
        nomina = {
            "tipo_nomina": nom_node.get("TipoNomina", ""),
            "fecha_pago": nom_node.get("FechaPago", ""),
            "fecha_inicial": nom_node.get("FechaInicialPago", ""),
            "fecha_final": nom_node.get("FechaFinalPago", ""),
            "num_dias_pagados": _dec(nom_node.get("NumDiasPagados")),
            "total_percepciones": _dec(nom_node.get("TotalPercepciones")),
            "total_deducciones": _dec(nom_node.get("TotalDeducciones")),
            "total_otros_pagos": _dec(nom_node.get("TotalOtrosPagos")),
        }
        curp_node = _find_first(nom_node, "Receptor")
        if curp_node is not None:
            nomina["curp"] = curp_node.get("Curp", "")
            nomina["num_empleado"] = curp_node.get("NumEmpleado", "")
            nomina["salario_diario"] = _dec(curp_node.get("SalarioDiarioIntegrado"))

    # ---- Relación de negocio / timbrado ----
    sello_ok = bool(sello)
    f_emi_dt = _iso_to_date(fecha)
    f_timb_dt = _iso_to_date(fecha_timbrado)
    fechas_validas = bool(
        f_emi_dt is not None and f_timb_dt is not None and f_timb_dt >= f_emi_dt
    )

    # ---- FIS-02: CFDI Global detection ----
    es_cfdi_global = receptor_d.get("rfc", "").strip().upper() in _GENERIC_RFCS

    # ---- FIS-01: Complemento Carta Porte ----
    carta_porte = None
    for cp_ns in ("cartaporte31", "cartaporte30"):
        cp_node = None
        for node in root.iter():
            if _localname(node) == "CartaPorte":
                cp_node = node
                break
        if cp_node is not None:
            carta_porte = {
                "version": cp_node.get("Version", ""),
                "transp_internac": cp_node.get("TranspInternac", ""),
                "total_distancia": cp_node.get("TotalDistRec", ""),
                "origenes": [],
                "destinos": [],
                "mercancias": [],
            }
            for ub in _all_children(cp_node, "Ubicacion"):
                tipo_ub = ub.get("TipoUbicacion", "")
                entry = {
                    "tipo": tipo_ub,
                    "rfc": ub.get("RFCRemitenteDestinatario", ""),
                    "nombre": ub.get("NombreRemitenteDestinatario", ""),
                    "fecha_salida_llegada": ub.get("FechaHoraSalidaLlegada", ""),
                    "distancia": ub.get("DistanciaRecorrida", ""),
                }
                domicilio = _find_first(ub, "Domicilio")
                if domicilio is not None:
                    entry["domicilio"] = {
                        "calle": domicilio.get("Calle", ""),
                        "codigo_postal": domicilio.get("CodigoPostal", ""),
                        "estado": domicilio.get("Estado", ""),
                        "pais": domicilio.get("Pais", ""),
                    }
                if tipo_ub == "Origen":
                    carta_porte["origenes"].append(entry)
                else:
                    carta_porte["destinos"].append(entry)
            for merc in _all_children(cp_node, "Mercancia"):
                carta_porte["mercancias"].append({
                    "bienes_transp": merc.get("BienesTransp", ""),
                    "descripcion": merc.get("Descripcion", ""),
                    "cantidad": merc.get("Cantidad", ""),
                    "clave_unidad": merc.get("ClaveUnidad", ""),
                    "peso_kg": merc.get("PesoEnKg", ""),
                })
            break  # found CartaPorte, stop searching

    return {
        # Identificación
        "archivo": os.path.basename(xml_path),
        "version": version,
        "tipo": tipo,
        "serie": serie,
        "folio": folio,
        "fecha": fecha,
        "fecha_dt": _iso_to_date(fecha).isoformat() if _iso_to_date(fecha) else None,
        "forma_pago": forma_pago,
        "metodo_pago": metodo_pago,
        "moneda": moneda,
        "tipo_cambio": tipo_cambio,
        "lugar_expedicion": lugar_expedicion,
        "exportacion": exportacion,
        "uso_cfdi": receptor_d.get("uso_cfdi", ""),
        # Partes
        "emisor": emisor_d,
        "emisor_rfc": emisor_d.get("rfc", ""),
        "emisor_nombre": emisor_d.get("nombre", ""),
        "receptor": receptor_d,
        "receptor_rfc": receptor_d.get("rfc", ""),
        "receptor_nombre": receptor_d.get("nombre", ""),
        # Montos
        "subtotal": subtotal,
        "descuento": descuento,
        "iva": iva,
        "ieps": ieps,
        "retenciones_isr": ret_isr,
        "retenciones_iva": ret_iva,
        "total": total,
        # Detalle
        "conceptos": conceptos,
        "descripcion": " | ".join(c["descripcion"] for c in conceptos if c["descripcion"]),
        "claves_prod_serv": claves_prod,
        "traslados": traslados,
        "retenciones": retenciones,
        "total_impuestos_trasladados": _dec(root.get("TotalImpuestosTrasladados")),
        "total_impuestos_retenidos": _dec(root.get("TotalImpuestosRetenidos")),
        # Complementos
        "no_certificado": no_certificado,
        "folio_fiscal": folio_fiscal,
        "fecha_timbrado": fecha_timbrado,
        "fecha_timbrado_dt": _iso_to_date(fecha_timbrado).isoformat()
        if _iso_to_date(fecha_timbrado) else None,
        "cfdi_relacionados": relacionados,
        "tipo_relacion": tipo_relacion,  # FIS-03: needed for credit note validation
        "pagos": pagos,
        "nomina": nomina,
        # Control de sellado
        "tiene_sello": sello_ok,
        "fechas_coherentes": fechas_validas,
        # FIS-01: Carta Porte complement
        "carta_porte": carta_porte,
        # FIS-02: CFDI Global flag
        "es_cfdi_global": es_cfdi_global,
    }


def main():
    import sys
    import json

    if len(sys.argv) < 2:
        print("Uso: python3 -m b2b_ai.cfdi.parser <archivo.xml>")
        sys.exit(1)

    def _ser(o):
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, dict):
            return {k: _ser(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_ser(v) for v in o]
        return o

    datos = parse_cfdi(sys.argv[1])
    print(json.dumps(_ser(datos), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]



# =====================================================================
# parse_cfdi_4 — minimal CFDI 4.0 parser (string input, nested output).
# Added in refactor 157f351; kept alongside the full parse_cfdi for back-compat.
# Private helpers prefixed _p4_ to avoid colliding with the full parser's helpers.
# =====================================================================
def _p4__tag(local: str) -> str:
    return f"{{{NS['cfdi']}}}{local}"


def _p4__tfd(tag_local: str) -> str:
    return f"{{{NS['tfd']}}}{tag_local}"


def _p4__float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _p4__str(text: Optional[str]) -> Optional[str]:
    if text is None or not text.strip():
        return None
    return text.strip()


def _p4__find_first(root: ET.Element, tag: str, ns: Optional[dict] = None) -> Optional[ET.Element]:
    ns = ns or NS
    result = root.find(_p4__tag(tag), ns)
    if result is None:
        result = root.find(f".//{tag}", {})
    return result


def _p4__find_text(root: ET.Element, tag: str, ns: Optional[dict] = None) -> Optional[str]:
    el = _p4__find_first(root, tag, ns)
    return el.text.strip() if el is not None and el.text else None


def _p4__children(parent: ET.Element, tag: str, ns: Optional[dict] = None) -> list[ET.Element]:
    ns = ns or NS
    return parent.findall(f"{{{ns['cfdi'] if '{' not in tag else ''}}}{tag.split('}')[-1]}", ns) or []


def _p4__parse_concepto(c: ET.Element) -> dict[str, Any]:
    """Extract fields from a cfdi:Concepto element."""
    result: dict[str, Any] = {
        "descripcion": _p4__str(c.get("Descripcion")) or _p4__str(c.get("descripcion")) or "",
        "cantidad": _p4__float(c.get("Cantidad")) or _p4__float(c.get("cantidad")),
        "valor_unitario": _p4__float(c.get("ValorUnitario")) or _p4__float(c.get("valor_unitario")),
        "importe": _p4__float(c.get("Importe")) or _p4__float(c.get("importe")),
        "clave_prod_serv": _p4__str(c.get("ClaveProdServ")) or _p4__str(c.get("clave_prod_serv")),
        "unidad": _p4__str(c.get("Unidad")) or _p4__str(c.get("unidad")),
        "objeto_imp": _p4__str(c.get("ObjetoImp")) or _p4__str(c.get("objeto_imp")),
    }
    return result


def _p4__parse_impuestos(root: ET.Element) -> dict[str, Any]:
    """Extract totals from cfdi:Impuestos."""
    imp_el = _p4__find_first(root, "Impuestos")
    if imp_el is None:
        return {}

    def _total(tag: str) -> Optional[float]:
        t = imp_el.get(tag, imp_el.get(tag.lower(), None))
        return _p4__float(t)

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
            v = _p4__float(ret.get("Importe") or ret.get("importe"))
            if v is not None:
                isr_retenido = (isr_retenido or 0.0) + v
        elif imp_str == "002":
            v = _p4__float(ret.get("Importe") or ret.get("importe"))
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
            v = _p4__float(tr.get("Importe") or tr.get("importe"))
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
        return _p4__str(root.get(key) or root.get(key.lower(), None))

    def _attrf(key: str) -> Optional[float]:
        v = root.get(key) or root.get(key.lower(), None)
        return _p4__float(v)

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
    emisor_el = _p4__find_first(root, "Emisor")
    if emisor_el is not None:
        result["emisor"] = {
            "rfc": _p4__str(emisor_el.get("Rfc") or emisor_el.get("rfc", "")) or "",
            "nombre": _p4__str(emisor_el.get("Nombre") or emisor_el.get("nombre")),
            "regimen_fiscal": (
                _p4__str(emisor_el.get("RegimenFiscal") or emisor_el.get("regimen_fiscal"))
            ),
        }
    else:
        result["emisor"] = {"rfc": "", "nombre": None, "regimen_fiscal": None}

    # Receptor
    receptor_el = _p4__find_first(root, "Receptor")
    if receptor_el is not None:
        result["receptor"] = {
            "rfc": _p4__str(receptor_el.get("Rfc") or receptor_el.get("rfc", "")) or "",
            "nombre": _p4__str(receptor_el.get("Nombre") or receptor_el.get("nombre")),
            "regimen_fiscal_receptor": (
                _p4__str(
                    receptor_el.get("RegimenFiscalReceptor")
                    or receptor_el.get("regimen_fiscal_receptor")
                )
            ),
            "uso_cfdi": _p4__str(
                receptor_el.get("UsoCFDI") or receptor_el.get("uso_cfdi")
            ),
            "domicilio_fiscal_receptor": _p4__str(
                receptor_el.get("DomicilioFiscalReceptor")
                or receptor_el.get("domicilio_fiscal_receptor")
            ),
            "residency": _p4__str(
                receptor_el.get("ResidenciaFiscal")
                or receptor_el.get("residency_fiscal")
            ),
            "num_reg_id_trib": _p4__str(
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
    conceptos_el = _p4__find_first(root, "Conceptos")
    if conceptos_el is not None:
        for c in conceptos_el.findall(f"{{{NS['cfdi']}}}Concepto"):
            conceptos.append(_p4__parse_concepto(c))
        # Also accept bare Concepto (no wrapper)
        if not conceptos:
            for c in root.findall(f"{{{NS['cfdi']}}}Concepto"):
                conceptos.append(_p4__parse_concepto(c))
    else:
        # Try bare Concepto elements
        for c in root.findall(f"{{{NS['cfdi']}}}Concepto"):
            conceptos.append(_p4__parse_concepto(c))

    result["conceptos"] = conceptos

    # Impuestos
    result.update(_p4__parse_impuestos(root))

    # TimbreFiscalDigital (Complemento)
    complemento = _p4__find_first(root, "Complemento")
    uuid: Optional[str] = None
    fecha_timbrado: Optional[str] = None
    if complemento is not None:
        timbre = complemento.find(f"{{{NS['tfd']}}}TimbreFiscalDigital")
        if timbre is None:
            timbre = complemento.find("TimbreFiscalDigital")
        if timbre is not None:
            uuid = _p4__str(timbre.get("UUID") or timbre.get("uuid"))
            fecha_timbrado = _p4__str(
                timbre.get("FechaTimbrado") or timbre.get("fecha_timbrado")
            )
            result["rfc_prov_certif"] = _p4__str(
                timbre.get("RfcProvCertif") or timbre.get("rfc_prov_certif")
            )
            result["sello_cfd"] = _p4__str(
                timbre.get("SelloCFD") or timbre.get("sello_cfd")
            )
            result["sello_sat"] = _p4__str(
                timbre.get("SelloSAT") or timbre.get("sello_sat")
            )
            result["no_certificado_sat"] = _p4__str(
                timbre.get("NoCertificadoSAT")
                or timbre.get("no_certificado_sat")
            )

    result["uuid"] = uuid
    result["fecha_timbrado"] = fecha_timbrado

    return result

__all__ = ["CFDIError", "parse_cfdi", "parse_cfdi_4", "main"]
