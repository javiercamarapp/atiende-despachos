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
from datetime import datetime, timezone
from typing import List, Optional
from xml.dom import minidom

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


def _fmt_fecha_creacion() -> str:
    """Fecha de creación con formato ISO 8601 (AAAA-MM-DDThh:mm:ss).

    La FechaCreacion es un atributo obligatorio del XSD SAT de Contabilidad
    Electrónica y debe llevar marca de tiempo, no quedar vacía.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _validar_rfc(rfc: str) -> None:
    """Valida la presencia del RFC obligatorio en el XSD SAT.

    El RFC del emisor es un atributo obligatorio de los elementos Balanza y
    Catalogo. Si está vacío, el XML no pasaría la validación del SAT.
    """
    if not rfc or not str(rfc).strip():
        raise ValueError(
            "Contabilidad Electrónica: el RFC es obligatorio "
            "(atributo RFC del XSD SAT) y no puede quedar vacío."
        )


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

def generate_balanza_xml(balanza: BalanzaRequest,
                         rfc: Optional[str] = None) -> str:
    """Genera el XML de Balanza de Comprobación conforme al XSD del SAT.

    El RFC se toma del parámetro `rfc` si se provee; si no, del atributo
    opcional `balanza.rfc`; si ninguno, se deja el valor que tenga el modelo.
    La validación estricta de campos requeridos (RFC obligatorio) se realiza
    en `validators.validate_balanza()` antes de generar, conforme al XSD SAT.

    Args:
        balanza: Request con periodo, ejercicio, mes y líneas de la balanza.
        rfc: RFC del contribuyente (obligatorio en el XSD del SAT).

    Returns:
        Cadena XML formateada con namespace SAT, listo para envío.
    """
    # P1-7: poblar el RFC (obligatorio en el XSD) si está disponible.
    rfc = (rfc or getattr(balanza, "rfc", None) or "").strip() or ""
    rfc = str(rfc)

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
            "RFC": rfc,
            "Ejercicio": str(balanza.ejercicio),
            "Mes": f"{balanza.mes:02d}",
            # P1-9: FechaCreacion obligatoria con marca de tiempo ISO 8601.
            "FechaCreacion": _fmt_fecha_creacion(),
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
                "Desc": getattr(row, "descripcion", None) or row.codigo_cuenta,
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
    rfc: Optional[str] = None,
) -> str:
    """Genera el XML del Catálogo de Cuentas conforme al XSD del SAT.

    Args:
        cuentas: Lista de cuentas del catálogo.
        ejercicio: Año del ejercicio fiscal.
        rfc: RFC del contribuyente (obligatorio en el XSD del SAT).

    Returns:
        Cadena XML formateada con namespace SAT, listo para envío.
    """
    # P1-7: poblar el RFC (obligatorio en el XSD) si está disponible.
    rfc = (rfc or "").strip() or ""

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
            "RFC": rfc,
            "Ejercicio": str(ejercicio),
            # P1-9: FechaCreacion obligatoria con marca de tiempo ISO 8601.
            "FechaCreacion": _fmt_fecha_creacion(),
        },
    )

    # Líneas de cuentas
    for cta in cuentas:
        cuenta_el = ET.SubElement(
            catalogo_el,
            f"{{{_NS_URI}}}Cuenta",
            attrib={
                # P1-8: El XSD SAT usa "NumCta", no "CodAgrup".
                "NumCta": cta.codigo,
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
