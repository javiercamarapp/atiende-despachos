# -*- coding: utf-8 -*-
"""
parser.py — Parser del complemento Pagos 1.1 del SAT.

Extrae los campos del complemento de pagos desde un archivo CFDI 4.0:

  - Version del complemento
  - Pago (.FechaPago, FormaPagoP, MonedaP, Monto, TipoCambioP,
           NumOperacion, RfcEmisorCtaOrd, NomBancoOrdExt, CtaEmisorCtaOrd,
           RfcEmisorCtaBen, CtaEmisorCtaBen, BancoBenef, TipoCadPago,
           CertPag, CadPago, SelloPago)
  - DoctoRelacionado(s) con sus atributos (IdDocumento, Serie, Folio,
           MonedaDR, EquivalenciaDR, MetodoDePagoDR, ParcialidadNo,
           ImpSaldoAnt, ImpPagado, ImpSaldoInsoluto, ObjetoImpDR)
  - Impuestos dentro de DoctoRelacionado (Retenciones y Traslados)

Maneja complementos ausentes/incompletos retornando None o parcialmente
llenos. Soporta namespace URI del SAT para Pagos 1.1.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from lxml import etree
from b2b_ai.cfdi.xml_security import safe_parse, safe_fromstring

# Namespace URIs del SAT para Pagos 1.1 (variantes conocidas).
PAGOS_NS_URIS = [
    "http://www.sat.gob.mx/pagos",
]

# Localnames que identifican el nodo raíz del complemento Pagos.
PAGOS_LOCALNAMES = {"Pagos"}


def _nsmap_for_pagos(root: etree._Element) -> dict:
    """Detecta el namespace de pagos disponible en el documento.

    Retorna dict {prefix: uri} listo para usar en XPath con namespaces,
    o dict vacío si no hay complemento de pagos.
    """
    nsmap = root.nsmap
    for prefix, uri in nsmap.items():
        if uri in PAGOS_NS_URIS:
            return {prefix: uri}
    return {}


def _find_pagos_node(root: etree._Element) -> Optional[etree._Element]:
    """Localiza el nodo Pagos dentro del Complemento del CFDI."""
    for node in root.iter():
        tag = etree.QName(node).localname
        if tag in PAGOS_LOCALNAMES:
            return node
    return None


def _dec(value: Optional[str]) -> Optional[Decimal]:
    """Convierte string a Decimal; retorna None si es vacío o inválido."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _attr_strip(node: Optional[etree._Element], name: str) -> Optional[str]:
    """Lee un atributo de un elemento XML, stripping whitespace."""
    if node is None:
        return None
    val = node.get(name)
    if val is not None:
        val = val.strip()
    return val if val else None


@dataclass
class Retencion:
    """Retención de impuestos dentro de un DoctoRelacionado."""
    base: Optional[Decimal] = None
    impuesto: Optional[str] = None
    tipo_factor: Optional[str] = None
    tasa_o_cuota: Optional[Decimal] = None
    importe: Optional[Decimal] = None

    def to_dict(self) -> dict:
        return {
            "base": str(self.base) if self.base is not None else None,
            "impuesto": self.impuesto,
            "tipo_factor": self.tipo_factor,
            "tasa_o_cuota": str(self.tasa_o_cuota) if self.tasa_o_cuota is not None else None,
            "importe": str(self.importe) if self.importe is not None else None,
        }


@dataclass
class Traslado:
    """Traslado de impuestos dentro de un DoctoRelacionado."""
    base: Optional[Decimal] = None
    impuesto: Optional[str] = None
    tipo_factor: Optional[str] = None
    tasa_o_cuota: Optional[Decimal] = None
    importe: Optional[Decimal] = None

    def to_dict(self) -> dict:
        return {
            "base": str(self.base) if self.base is not None else None,
            "impuesto": self.impuesto,
            "tipo_factor": self.tipo_factor,
            "tasa_o_cuota": str(self.tasa_o_cuota) if self.tasa_o_cuota is not None else None,
            "importe": str(self.importe) if self.importe is not None else None,
        }


@dataclass
class ImpuestosDR:
    """Impuestos de un DoctoRelacionado."""
    retenciones: List[Retencion] = field(default_factory=list)
    traslados: List[Traslado] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "retenciones": [r.to_dict() for r in self.retenciones],
            "traslados": [t.to_dict() for t in self.traslados],
        }


@dataclass
class DoctoRelacionado:
    """Documento relacionado a un pago."""
    id_documento: Optional[str] = None
    serie: Optional[str] = None
    folio: Optional[str] = None
    moneda_dr: Optional[str] = None
    equivalencia_dr: Optional[Decimal] = None
    metodo_de_pago_dr: Optional[str] = None
    parcialidad_no: Optional[int] = None
    imp_saldo_ant: Optional[Decimal] = None
    imp_pagado: Optional[Decimal] = None
    imp_saldo_insoluto: Optional[Decimal] = None
    objeto_imp_dr: Optional[str] = None
    impuestos: Optional[ImpuestosDR] = None

    def to_dict(self) -> dict:
        return {
            "id_documento": self.id_documento,
            "serie": self.serie,
            "folio": self.folio,
            "moneda_dr": self.moneda_dr,
            "equivalencia_dr": str(self.equivalencia_dr) if self.equivalencia_dr is not None else None,
            "metodo_de_pago_dr": self.metodo_de_pago_dr,
            "parcialidad_no": self.parcialidad_no,
            "imp_saldo_ant": str(self.imp_saldo_ant) if self.imp_saldo_ant is not None else None,
            "imp_pagado": str(self.imp_pagado) if self.imp_pagado is not None else None,
            "imp_saldo_insoluto": str(self.imp_saldo_insoluto) if self.imp_saldo_insoluto is not None else None,
            "objeto_imp_dr": self.objeto_imp_dr,
            "impuestos": self.impuestos.to_dict() if self.impuestos is not None else None,
        }


@dataclass
class PagoInfo:
    """Información de un pago individual dentro del complemento Pagos."""
    fecha_pago: Optional[str] = None
    forma_pago_p: Optional[str] = None
    moneda_p: Optional[str] = None
    monto: Optional[Decimal] = None
    tipo_cambio_p: Optional[Decimal] = None
    num_operacion: Optional[str] = None
    rfc_emisor_cta_ord: Optional[str] = None
    nom_banco_ord_ext: Optional[str] = None
    cta_emisor_cta_ord: Optional[str] = None
    rfc_emisor_cta_ben: Optional[str] = None
    cta_emisor_cta_ben: Optional[str] = None
    banco_benef: Optional[str] = None
    tipo_cad_pago: Optional[str] = None
    cert_pag: Optional[str] = None
    cad_pago: Optional[str] = None
    sello_pago: Optional[str] = None
    documentos_relacionados: List[DoctoRelacionado] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fecha_pago": self.fecha_pago,
            "forma_pago_p": self.forma_pago_p,
            "moneda_p": self.moneda_p,
            "monto": str(self.monto) if self.monto is not None else None,
            "tipo_cambio_p": str(self.tipo_cambio_p) if self.tipo_cambio_p is not None else None,
            "num_operacion": self.num_operacion,
            "rfc_emisor_cta_ord": self.rfc_emisor_cta_ord,
            "nom_banco_ord_ext": self.nom_banco_ord_ext,
            "cta_emisor_cta_ord": self.cta_emisor_cta_ord,
            "rfc_emisor_cta_ben": self.rfc_emisor_cta_ben,
            "cta_emisor_cta_ben": self.cta_emisor_cta_ben,
            "banco_benef": self.banco_benef,
            "tipo_cad_pago": self.tipo_cad_pago,
            "cert_pag": self.cert_pag,
            "cad_pago": self.cad_pago,
            "sello_pago": self.sello_pago,
            "documentos_relacionados": [d.to_dict() for d in self.documentos_relacionados],
        }


@dataclass
class PagosData:
    """Datos extraídos del complemento Pagos 1.1 de un CFDI."""
    version: Optional[str] = None
    pagos: List[PagoInfo] = field(default_factory=list)

    # CFDI-level context
    cfdi_emisor_rfc: Optional[str] = None
    cfdi_receptor_rfc: Optional[str] = None

    def to_dict(self) -> dict:
        """Serializa a dict JSON-friendly (Decimals como str)."""
        return {
            "version": self.version,
            "pagos": [p.to_dict() for p in self.pagos],
            "cfdi_emisor_rfc": self.cfdi_emisor_rfc,
            "cfdi_receptor_rfc": self.cfdi_receptor_rfc,
        }


def _parse_retenciones(impuestos_node: etree._Element) -> List[Retencion]:
    """Extrae retenciones de impuestos de un nodo Impuestos DR."""
    retenciones = []
    for child in impuestos_node:
        localname = etree.QName(child).localname
        if localname == "Retencion":
            retenciones.append(Retencion(
                base=_dec(_attr_strip(child, "Base")),
                impuesto=_attr_strip(child, "Impuesto"),
                tipo_factor=_attr_strip(child, "TipoFactor"),
                tasa_o_cuota=_dec(_attr_strip(child, "TasaOCuota")),
                importe=_dec(_attr_strip(child, "Importe")),
            ))
    return retenciones


def _parse_traslados(impuestos_node: etree._Element) -> List[Traslado]:
    """Extrae traslados de impuestos de un nodo Impuestos DR."""
    traslados = []
    for child in impuestos_node:
        localname = etree.QName(child).localname
        if localname == "Traslado":
            traslados.append(Traslado(
                base=_dec(_attr_strip(child, "Base")),
                impuesto=_attr_strip(child, "Impuesto"),
                tipo_factor=_attr_strip(child, "TipoFactor"),
                tasa_o_cuota=_dec(_attr_strip(child, "TasaOCuota")),
                importe=_dec(_attr_strip(child, "Importe")),
            ))
    return traslados


def _parse_docto_relacionado(dr_node: etree._Element) -> DoctoRelacionado:
    """Extrae un DoctoRelacionado y sus impuestos."""
    dr = DoctoRelacionado(
        id_documento=_attr_strip(dr_node, "IdDocumento"),
        serie=_attr_strip(dr_node, "Serie"),
        folio=_attr_strip(dr_node, "Folio"),
        moneda_dr=_attr_strip(dr_node, "MonedaDR"),
        equivalencia_dr=_dec(_attr_strip(dr_node, "EquivalenciaDR")),
        metodo_de_pago_dr=_attr_strip(dr_node, "MetodoDePagoDR"),
        parcialidad_no=int(_attr_strip(dr_node, "ParcialidadNo") or "0") or None,
        imp_saldo_ant=_dec(_attr_strip(dr_node, "ImpSaldoAnt")),
        imp_pagado=_dec(_attr_strip(dr_node, "ImpPagado")),
        imp_saldo_insoluto=_dec(_attr_strip(dr_node, "ImpSaldoInsoluto")),
        objeto_imp_dr=_attr_strip(dr_node, "ObjetoImpDR"),
    )

    # Buscar nodo Impuestos dentro del DoctoRelacionado
    for child in dr_node:
        if etree.QName(child).localname == "Impuestos":
            retenciones = _parse_retenciones(child)
            traslados = _parse_traslados(child)
            if retenciones or traslados:
                dr.impuestos = ImpuestosDR(
                    retenciones=retenciones,
                    traslados=traslados,
                )
            break

    return dr


def _parse_pago(pago_node: etree._Element) -> PagoInfo:
    """Extrae un nodo Pago y sus documentos relacionados."""
    pago = PagoInfo(
        fecha_pago=_attr_strip(pago_node, "FechaPago"),
        forma_pago_p=_attr_strip(pago_node, "FormaPagoP"),
        moneda_p=_attr_strip(pago_node, "MonedaP"),
        monto=_dec(_attr_strip(pago_node, "Monto")),
        tipo_cambio_p=_dec(_attr_strip(pago_node, "TipoCambioP")),
        num_operacion=_attr_strip(pago_node, "NumOperacion"),
        rfc_emisor_cta_ord=_attr_strip(pago_node, "RfcEmisorCtaOrd"),
        nom_banco_ord_ext=_attr_strip(pago_node, "NomBancoOrdExt"),
        cta_emisor_cta_ord=_attr_strip(pago_node, "CtaEmisorCtaOrd"),
        rfc_emisor_cta_ben=_attr_strip(pago_node, "RfcEmisorCtaBen"),
        cta_emisor_cta_ben=_attr_strip(pago_node, "CtaEmisorCtaBen"),
        banco_benef=_attr_strip(pago_node, "BancoBenef"),
        tipo_cad_pago=_attr_strip(pago_node, "TipoCadPago"),
        cert_pag=_attr_strip(pago_node, "CertPag"),
        cad_pago=_attr_strip(pago_node, "CadPago"),
        sello_pago=_attr_strip(pago_node, "SelloPago"),
    )

    # Buscar documentos relacionados
    for child in pago_node:
        if etree.QName(child).localname == "DoctoRelacionado":
            pago.documentos_relacionados.append(_parse_docto_relacionado(child))

    return pago


def parse_pagos(xml_path: str) -> Optional[PagosData]:
    """Parsea el complemento Pagos 1.1 desde un archivo CFDI 4.0.

    Args:
        xml_path: Ruta al archivo XML del CFDI.

    Returns:
        PagosData con los campos extraídos, o None si no hay complemento
        de pagos en el XML.

    Raises:
        OSError: Si el archivo no existe.
        etree.XMLSyntaxError: Si el XML está mal formado.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    tree = safe_parse(xml_path)
    root = tree.getroot()

    return _parse_from_root(root)


def parse_pagos_bytes(xml_bytes: bytes) -> Optional[PagosData]:
    """Parsea el complemento Pagos 1.1 desde bytes XML en memoria.

    Útil para endpoints que reciben el XML como upload (sin escribir a disco).

    Returns:
        PagosData con los campos extraídos, o None si no hay complemento.
    """
    root = safe_fromstring(xml_bytes)
    return _parse_from_root(root)


def _parse_from_root(root: etree._Element) -> Optional[PagosData]:
    """Lógica compartida de parsing para file y bytes."""
    # Extraer RFCs del Emisor y Receptor del comprobante
    emisor_cfdi = None
    receptor_cfdi = None
    for child in root:
        localname = etree.QName(child).localname
        if localname == "Emisor":
            emisor_cfdi = child
        elif localname == "Receptor":
            receptor_cfdi = child

    cfdi_emisor_rfc = _attr_strip(emisor_cfdi, "Rfc")
    cfdi_receptor_rfc = _attr_strip(receptor_cfdi, "Rfc")

    # Localizar nodo Pagos
    pagos_node = _find_pagos_node(root)
    if pagos_node is None:
        return None

    data = PagosData(
        version=_attr_strip(pagos_node, "Version"),
        cfdi_emisor_rfc=cfdi_emisor_rfc,
        cfdi_receptor_rfc=cfdi_receptor_rfc,
    )

    # Extraer pagos
    for child in pagos_node:
        localname = etree.QName(child).localname
        if localname == "Pago":
            data.pagos.append(_parse_pago(child))

    return data
