# -*- coding: utf-8 -*-
"""
generator.py — Generadores de XML para Contabilidad Electrónica del SAT.

Genera:
  - Balanza de Comprobación (mensual) conforme al XSD del SAT.
  - Catálogo de Cuentas (anual) conforme al XSD del SAT.

Referencia:
  http://www.sat.gob.mx/esquemas/ContabilidadE/1_1/ContabilidadEducativa
  http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List

from b2b_ai.features.contabilidad_electronica.models import (
    BalanzaRequest,
    BalanzaRow,
    CatalogoCuenta,
)

# --------------------------------------------------------------------------- #
# Namespace SAT Contabilidad Electrónica v1.3
# --------------------------------------------------------------------------- #
_NS_URI = "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa"
_NS_PREFIX = "ce"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_XSI_SCHEMALOC = (
    "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa "
    "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa.xsd"
)

_BALANZA_VERSION = "1.3"
_CATALOGO_VERSION = "1.3"


def _indent_xml(xml_str: str) -> str:
    """Indenta un XML de una sola línea para legibilidad."""
    try:
        dom = minidom.parseString(xml_str)
        lines = dom.toprettyxml(indent="  ", encoding=None).split("\n")
        # minidom agrega <?xml ...?> y líneas vacías — las limpiamos.
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                if stripped.startswith("<?xml"):
                    cleaned.append(stripped)
                else:
                    cleaned.append("  " + stripped)
        return "\n".join(cleaned) + "\n"
    except Exception:
        return xml_str


# --------------------------------------------------------------------------- #
# Generador de Balanza de Comprobación
# --------------------------------------------------------------------------- #

def generate_balanza_xml(balanza: BalanzaRequest) -> str:
    """Genera el XML de Balanza de Comprobación conforme al XSD del SAT.

    Args:
        balanza: Request con periodo, ejercicio, mes y líneas de la balanza.

    Returns:
        Cadena XML formateada con namespace SAT, listo para envío.
    """
    # Registrar namespace para que lxml y minidom lo rendericen correctamente.
    ET.register_namespace(_NS_PREFIX, _NS_URI)
    ET.register_namespace("xsi", _XSI_NS)

    # Elemento raíz: ce:ContabilidadEducativa
    root = ET.Element(
        f"{{{_NS_URI}}}ContabilidadEducativa",
        attrib={
            f"{{{_XSI_NS}}}schemaLocation": _XSI_SCHEMALOC,
        },
    )

    # Subelemento: ce:Balanza
    balanza_el = ET.SubElement(
        root,
        f"{{{_NS_URI}}}Balanza",
        attrib={
            "Version": _BALANZA_VERSION,
            "RFC": "",  # Se puede inyectar desde el caller
            "Ejercicio": str(balanza.ejercicio),
            "Mes": f"{balanza.mes:02d}",
            "FechaCreacion": "",  # Se llena al timbrar
            "TipoBalance": "C",  # Comprobación
        },
    )

    # Líneas de cuentas
    for row in balanza.rows:
        cuenta_el = ET.SubElement(
            balanza_el,
            f"{{{_NS_URI}}}Cuenta",
            attrib={
                "NumCta": row.codigo_cuenta,
                "Desc": "",
                "SaldoIni": _fmt_amount(row.saldo_inicial),
                "Debe": _fmt_amount(row.debe),
                "Haber": _fmt_amount(row.haber),
                "SaldoDeudor": _fmt_deudor_acreedor(row, "deudor"),
                "SaldoAcreedor": _fmt_deudor_acreedor(row, "acreedor"),
            },
        )

    return _serialize(root)


def _fmt_amount(value: float) -> str:
    """Formatea un monto como string con 2 decimales."""
    return f"{value:.2f}"


def _fmt_deudor_acreedor(row: BalanzaRow, tipo: str) -> str:
    """Calcula y formatea saldo deudor o acreedor.

    Deudor: saldo_final > 0  (debe > haber + saldo_inicial)
    Acreedor: saldo_final < 0 (haber > debe + saldo_inicial)
    """
    saldo = row.saldo_final
    if tipo == "deudor":
        return _fmt_amount(saldo) if saldo > 0 else "0.00"
    else:
        return _fmt_amount(abs(saldo)) if saldo < 0 else "0.00"


# --------------------------------------------------------------------------- #
# Generador de Catálogo de Cuentas
# --------------------------------------------------------------------------- #

def generate_catalogo_xml(
    cuentas: List[CatalogoCuenta],
    ejercicio: int,
) -> str:
    """Genera el XML del Catálogo de Cuentas conforme al XSD del SAT.

    Args:
        cuentas: Lista de cuentas del catálogo.
        ejercicio: Año del ejercicio fiscal.

    Returns:
        Cadena XML formateada con namespace SAT, listo para envío.
    """
    ET.register_namespace(_NS_PREFIX, _NS_URI)
    ET.register_namespace("xsi", _XSI_NS)

    # Elemento raíz: ce:ContabilidadEducativa
    root = ET.Element(
        f"{{{_NS_URI}}}ContabilidadEducativa",
        attrib={
            f"{{{_XSI_NS}}}schemaLocation": _XSI_SCHEMALOC,
        },
    )

    # Subelemento: ce:Catalogo
    catalogo_el = ET.SubElement(
        root,
        f"{{{_NS_URI}}}Catalogo",
        attrib={
            "Version": _CATALOGO_VERSION,
            "RFC": "",  # Se puede inyectar desde el caller
            "Ejercicio": str(ejercicio),
            "FechaCreacion": "",
        },
    )

    # Líneas de cuentas
    for cta in cuentas:
        cuenta_el = ET.SubElement(
            catalogo_el,
            f"{{{_NS_URI}}}Cuenta",
            attrib={
                "CodAgrup": cta.codigo,
                "Desc": cta.descripcion,
                "Nivel": str(cta.nivel),
                "Naturaleza": _naturaleza_from_tipo(cta.tipo.value),
                "TipoCta": cta.tipo.value,
                "SubCtaDe": cta.subtipo_cuenta or "",
                "CtaPadre": cta.padre or "",
                "Estado": cta.status,
            },
        )

    return _serialize(root)


def _naturaleza_from_tipo(tipo: str) -> str:
    """Convierte tipo de cuenta a naturaleza SAT (D/A)."""
    if tipo in ("Activo", "Gasto"):
        return "D"
    elif tipo in ("Pasivo", "Capital", "Ingreso"):
        return "A"
    return "D"


# --------------------------------------------------------------------------- #
# Serialización
# --------------------------------------------------------------------------- #

def _serialize(root: ET.Element) -> str:
    """Serializa un ElementTree a string XML indentado."""
    ET.indent(root, space="  ")
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    # Agregar declaración XML al inicio
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration + raw
