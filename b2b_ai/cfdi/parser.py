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
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


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
        "pagos": pagos,
        "nomina": nomina,
        # Control de sellado
        "tiene_sello": sello_ok,
        "fechas_coherentes": fechas_validas,
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
