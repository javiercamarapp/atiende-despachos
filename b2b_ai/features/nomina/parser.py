# -*- coding: utf-8 -*-
"""
parser.py — Parser del complemento Nomina 1.2 del SAT.

Extrae los campos del complemento de nómina desde un archivo CFDI 4.0:

  - TipoNomina (O=Ordinaria, E=Extraordinaria)
  - FechaPago, FechaInicialPago, FechaFinalPago, NumDiasPagados
  - TotalPercepciones, TotalDeducciones, TotalOtrosPagos
  - Emisor: RegistroPatronal, RfcPatronOrigen
  - Receptor: Curp, NumEmpleado, TipoJornada, RiesgoPuesto,
              PeriodicidadPago, SalarioDiarioIntegrado

Maneja complmentos ausentes/incompletos retornando None o parcialmente
llenos. Soporta ambos namespace URIs del SAT para Nomina 1.2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree
from b2b_ai.cfdi.xml_security import safe_parse, safe_fromstring

# Namespace URIs del SAT para Nomina 1.2 (ambas variantes conocidas).
NOMINA_NS_URIS = [
    "http://www.sat.gob.mx/nomina12",
    "http://www.sat.gob.mx/nomina",
]

# Prefijos posibles para el complemento Nomina
NOMINA_LOCALNAMES = {"Nomina"}


def _nsmap_for_nomina(root: etree._Element) -> dict:
    """Detecta el namespace de nómina disponible en el documento.

    Retorna dict {prefix: uri} listo para usar enXPath con namespaces,
    o dict vacío si no hay complemento de nómina.
    """
    nsmap = root.nsmap
    for prefix, uri in nsmap.items():
        if uri in NOMINA_NS_URIS:
            return {prefix: uri}
    return {}


def _find_nomina_node(root: etree._Element) -> Optional[etree._Element]:
    """Localiza el nodo Nomina dentro del Complemento del CFDI."""
    # Estrategia 1: usar localname (tolerante a prefijos)
    for node in root.iter():
        tag = etree.QName(node).localname
        if tag in NOMINA_LOCALNAMES:
            return node
    return None


def _find_emisor_nomina(root: etree._Element) -> Optional[etree._Element]:
    """Localiza el nodo Emisor dentro del complemento Nomina."""
    nomina = _find_nomina_node(root)
    if nomina is None:
        return None
    for child in nomina:
        if etree.QName(child).localname == "Emisor":
            return child
    return None


def _find_receptor_nomina(root: etree._Element) -> Optional[etree._Element]:
    """Localiza el nodo Receptor dentro del complemento Nomina."""
    nomina = _find_nomina_node(root)
    if nomina is None:
        return None
    for child in nomina:
        if etree.QName(child).localname == "Receptor":
            return child
    return None


def _dec(value: Optional[str]) -> Optional[Decimal]:
    """Convierte string a Decimal; retorna None si es vacío o inválido."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


@dataclass
class NominaData:
    """Datos extraídos del complemento Nomina 1.2 de un CFDI."""

    # Tipo de nómina
    tipo_nomina: Optional[str] = None          # "O" (Ordinaria) / "E" (Extraordinaria)
    version: Optional[str] = None              # Versión del complemento

    # Fechas y días
    fecha_pago: Optional[str] = None           # YYYY-MM-DD
    fecha_inicial_pago: Optional[str] = None   # YYYY-MM-DD
    fecha_final_pago: Optional[str] = None     # YYYY-MM-DD
    num_dias_pagados: Optional[Decimal] = None

    # Totales
    total_percepciones: Optional[Decimal] = None
    total_deducciones: Optional[Decimal] = None
    total_otros_pagos: Optional[Decimal] = None

    # Emisor (patrón)
    registro_patronal: Optional[str] = None
    rfc_patron_origen: Optional[str] = None

    # Receptor (empleado)
    curp: Optional[str] = None
    num_empleado: Optional[str] = None
    tipo_jornada: Optional[str] = None
    riesgo_puesto: Optional[str] = None
    periodicidad_pago: Optional[str] = None
    salario_diario_integrado: Optional[Decimal] = None

    # CFDI-level context (emisor RFC del comprobante)
    cfdi_emisor_rfc: Optional[str] = None

    def to_dict(self) -> dict:
        """Serializa a dict JSON-friendly (Decimals como str)."""
        return {
            "tipo_nomina": self.tipo_nomina,
            "version": self.version,
            "fecha_pago": self.fecha_pago,
            "fecha_inicial_pago": self.fecha_inicial_pago,
            "fecha_final_pago": self.fecha_final_pago,
            "num_dias_pagados": str(self.num_dias_pagados) if self.num_dias_pagados is not None else None,
            "total_percepciones": str(self.total_percepciones) if self.total_percepciones is not None else None,
            "total_deducciones": str(self.total_deducciones) if self.total_deducciones is not None else None,
            "total_otros_pagos": str(self.total_otros_pagos) if self.total_otros_pagos is not None else None,
            "registro_patronal": self.registro_patronal,
            "rfc_patron_origen": self.rfc_patron_origen,
            "curp": self.curp,
            "num_empleado": self.num_empleado,
            "tipo_jornada": self.tipo_jornada,
            "riesgo_puesto": self.riesgo_puesto,
            "periodicidad_pago": self.periodicidad_pago,
            "salario_diario_integrado": str(self.salario_diario_integrado) if self.salario_diario_integrado is not None else None,
            "cfdi_emisor_rfc": self.cfdi_emisor_rfc,
        }


def _attr_strip(node: Optional[etree._Element], name: str) -> Optional[str]:
    """Lee un atributo de un elemento XML, stripping whitespace."""
    if node is None:
        return None
    val = node.get(name)
    if val is not None:
        val = val.strip()
    return val if val else None


def parse_nomina(xml_path: str) -> Optional[NominaData]:
    """Parsea el complemento Nomina 1.2 desde un archivo CFDI 4.0.

    Args:
        xml_path: Ruta al archivo XML del CFDI.

    Returns:
        NominaData con los campos extraídos, o None si no hay complemento
        de nómina en el XML.

    Raises:
        OSError: Si el archivo no existe.
        etree.XMLSyntaxError: Si el XML está mal formado.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    tree = safe_parse(xml_path)
    root = tree.getroot()

    # Extraer RFC del Emisor del comprobante (contexto para validación)
    emisor_cfdi = None
    for child in root:
        if etree.QName(child).localname == "Emisor":
            emisor_cfdi = child
            break
    cfdi_emisor_rfc = _attr_strip(emisor_cfdi, "Rfc")

    # Localizar nodo Nomina
    nomina_node = _find_nomina_node(root)
    if nomina_node is None:
        return None

    # Extraer atributos del nodo Nomina
    data = NominaData(
        tipo_nomina=_attr_strip(nomina_node, "TipoNomina"),
        version=_attr_strip(nomina_node, "Version"),
        fecha_pago=_attr_strip(nomina_node, "FechaPago"),
        fecha_inicial_pago=_attr_strip(nomina_node, "FechaInicialPago"),
        fecha_final_pago=_attr_strip(nomina_node, "FechaFinalPago"),
        num_dias_pagados=_dec(_attr_strip(nomina_node, "NumDiasPagados")),
        total_percepciones=_dec(_attr_strip(nomina_node, "TotalPercepciones")),
        total_deducciones=_dec(_attr_strip(nomina_node, "TotalDeducciones")),
        total_otros_pagos=_dec(_attr_strip(nomina_node, "TotalOtrosPagos")),
        cfdi_emisor_rfc=cfdi_emisor_rfc,
    )

    # Extraer Emisor (patrón)
    emisor_node = _find_emisor_nomina(root)
    data.registro_patronal = _attr_strip(emisor_node, "RegistroPatronal")
    data.rfc_patron_origen = _attr_strip(emisor_node, "RfcPatronOrigen")

    # Extraer Receptor (empleado)
    receptor_node = _find_receptor_nomina(root)
    data.curp = _attr_strip(receptor_node, "Curp")
    data.num_empleado = _attr_strip(receptor_node, "NumEmpleado")
    data.tipo_jornada = _attr_strip(receptor_node, "TipoJornada")
    data.riesgo_puesto = _attr_strip(receptor_node, "RiesgoPuesto")
    data.periodicidad_pago = _attr_strip(receptor_node, "PeriodicidadPago")
    data.salario_diario_integrado = _dec(_attr_strip(receptor_node, "SalarioDiarioIntegrado"))

    return data


def parse_nomina_bytes(xml_bytes: bytes) -> Optional[NominaData]:
    """Parsea el complemento Nomina 1.2 desde bytes XML en memoria.

    Útil para endpoints que reciben el XML como upload (sin escribir a disco).

    Returns:
        NominaData con los campos extraídos, o None si no hay complemento.
    """
    root = safe_fromstring(xml_bytes)

    # Extraer RFC del Emisor del comprobante
    emisor_cfdi = None
    for child in root:
        if etree.QName(child).localname == "Emisor":
            emisor_cfdi = child
            break
    cfdi_emisor_rfc = _attr_strip(emisor_cfdi, "Rfc")

    nomina_node = _find_nomina_node(root)
    if nomina_node is None:
        return None

    data = NominaData(
        tipo_nomina=_attr_strip(nomina_node, "TipoNomina"),
        version=_attr_strip(nomina_node, "Version"),
        fecha_pago=_attr_strip(nomina_node, "FechaPago"),
        fecha_inicial_pago=_attr_strip(nomina_node, "FechaInicialPago"),
        fecha_final_pago=_attr_strip(nomina_node, "FechaFinalPago"),
        num_dias_pagados=_dec(_attr_strip(nomina_node, "NumDiasPagados")),
        total_percepciones=_dec(_attr_strip(nomina_node, "TotalPercepciones")),
        total_deducciones=_dec(_attr_strip(nomina_node, "TotalDeducciones")),
        total_otros_pagos=_dec(_attr_strip(nomina_node, "TotalOtrosPagos")),
        cfdi_emisor_rfc=cfdi_emisor_rfc,
    )

    emisor_node = _find_emisor_nomina(root)
    data.registro_patronal = _attr_strip(emisor_node, "RegistroPatronal")
    data.rfc_patron_origen = _attr_strip(emisor_node, "RfcPatronOrigen")

    receptor_node = _find_receptor_nomina(root)
    data.curp = _attr_strip(receptor_node, "Curp")
    data.num_empleado = _attr_strip(receptor_node, "NumEmpleado")
    data.tipo_jornada = _attr_strip(receptor_node, "TipoJornada")
    data.riesgo_puesto = _attr_strip(receptor_node, "RiesgoPuesto")
    data.periodicidad_pago = _attr_strip(receptor_node, "PeriodicidadPago")
    data.salario_diario_integrado = _dec(_attr_strip(receptor_node, "SalarioDiarioIntegrado"))

    return data
