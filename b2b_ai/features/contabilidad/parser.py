# -*- coding: utf-8 -*-
"""
parser.py — Parser de Contabilidad Electrónica del SAT.

Extrae datos de los XML de contabilidad electrónica generados por el SAT:

  - Balanza de Comprobación: cuentas con código, descripción, Deudor, Acreedor,
    saldo Deudor/Acreedor.
  - Catálogo de Cuentas: catálogo de cuentas con código, descripción, nivel,
    naturaleza (D/A), código agrupador, estado de cuenta.
  - Estado de Resultados: líneas de ingresos, costos, gastos, resultado
    del ejercicio.

Soporta namespace URI del SAT para contabilidad electrónica. Maneja XML
ausentes/incompletos retornando None o data parcialmente llena.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from lxml import etree
from b2b_ai.cfdi.xml_security import safe_parse, safe_fromstring

# Namespace URIs del SAT para Contabilidad Electrónica
CONTABILIDAD_NS_URIS = [
    "http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/ContabilidadEducativa",
    "http://www.sat.gob.mx/esquemas/ContabilidadE/1_1/ContabilidadEducativa",
]

# Localnames que identifican el nodo raíz de contabilidad
CONTABILIDAD_ROOT_LOCALNAMES = {"ContabilidadEducativa"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AccountBalance:
    """Línea individual de la Balanza de Comprobación."""
    num_cuenta: str = ""
    desc: str = ""
    saldo_inicial: Optional[Decimal] = Decimal("0.00")
    debe: Optional[Decimal] = Decimal("0.00")
    haber: Optional[Decimal] = Decimal("0.00")
    saldo_deudor: Optional[Decimal] = Decimal("0.00")
    saldo_acreedor: Optional[Decimal] = Decimal("0.00")

    def to_dict(self) -> dict:
        return {
            "NumCta": self.num_cuenta,
            "Desc": self.desc,
            "SaldoIni": str(self.saldo_inicial) if self.saldo_inicial is not None else None,
            "Debe": str(self.debe) if self.debe is not None else None,
            "Haber": str(self.haber) if self.haber is not None else None,
            "SaldoDeudor": str(self.saldo_deudor) if self.saldo_deudor is not None else None,
            "SaldoAcreedor": str(self.saldo_acreedor) if self.saldo_acreedor is not None else None,
        }


@dataclass
class BalanzaData:
    """Datos extraídos de la Balanza de Comprobación."""
    version: Optional[str] = None
    rfc: Optional[str] = None
    mes: Optional[str] = None
    ejercicio: Optional[str] = None
    fecha_creacion: Optional[str] = None
    tipo_balance: Optional[str] = None
    cuentas: List[AccountBalance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "Version": self.version,
            "Rfc": self.rfc,
            "Mes": self.mes,
            "Ejercicio": self.ejercicio,
            "FechaCreacion": self.fecha_creacion,
            "TipoBalance": self.tipo_balance,
            "Cuentas": [c.to_dict() for c in self.cuentas],
        }


@dataclass
class AccountCatalogEntry:
    """Línea individual del Catálogo de Cuentas."""
    num_cuenta: str = ""
    desc: str = ""
    nivel: Optional[int] = None
    naturaleza: Optional[str] = None      # D=Deudor, A=Acreedor
    codigo_agrupador: Optional[str] = None
    estado_cuenta: Optional[str] = None   # A=Activa, I=Inactiva

    def to_dict(self) -> dict:
        return {
            "NumCta": self.num_cuenta,
            "Desc": self.desc,
            "Nivel": self.nivel,
            "Naturaleza": self.naturaleza,
            "CodigoAgrupador": self.codigo_agrupador,
            "EstadoCuenta": self.estado_cuenta,
        }


@dataclass
class CatalogoData:
    """Datos extraídos del Catálogo de Cuentas."""
    version: Optional[str] = None
    rfc: Optional[str] = None
    mes: Optional[str] = None
    ejercicio: Optional[str] = None
    fecha_creacion: Optional[str] = None
    cuentas: List[AccountCatalogEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "Version": self.version,
            "Rfc": self.rfc,
            "Mes": self.mes,
            "Ejercicio": self.ejercicio,
            "FechaCreacion": self.fecha_creacion,
            "Cuentas": [c.to_dict() for c in self.cuentas],
        }


@dataclass
class IncomeStatementLine:
    """Línea del Estado de Resultados."""
    concepto: str = ""
    importe: Optional[Decimal] = Decimal("0.00")

    def to_dict(self) -> dict:
        return {
            "Concepto": self.concepto,
            "Importe": str(self.importe) if self.importe is not None else None,
        }


@dataclass
class EstadoResultadosData:
    """Datos extraídos del Estado de Resultados."""
    version: Optional[str] = None
    rfc: Optional[str] = None
    mes: Optional[str] = None
    ejercicio: Optional[str] = None
    fecha_creacion: Optional[str] = None
    tipo_balanza: Optional[str] = None
    lineas: List[IncomeStatementLine] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "Version": self.version,
            "Rfc": self.rfc,
            "Mes": self.mes,
            "Ejercicio": self.ejercicio,
            "FechaCreacion": self.fecha_creacion,
            "TipoBalanza": self.tipo_balanza,
            "Lineas": [l.to_dict() for l in self.lineas],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _find_contabilidad_node(root: etree._Element) -> Optional[etree._Element]:
    """Localiza el nodo raíz de contabilidad dentro del XML."""
    for node in root.iter():
        tag = etree.QName(node).localname
        if tag in CONTABILIDAD_ROOT_LOCALNAMES:
            return node
    return None


# ---------------------------------------------------------------------------
# Parser de Balanza
# ---------------------------------------------------------------------------

def _parse_balanza_account(cuenta_node: etree._Element) -> AccountBalance:
    """Extrae una línea de cuenta de la Balanza de Comprobación."""
    return AccountBalance(
        num_cuenta=_attr_strip(cuenta_node, "NumCta") or "",
        desc=_attr_strip(cuenta_node, "Desc") or "",
        saldo_inicial=_dec(_attr_strip(cuenta_node, "SaldoIni")),
        debe=_dec(_attr_strip(cuenta_node, "Debe")),
        haber=_dec(_attr_strip(cuenta_node, "Haber")),
        saldo_deudor=_dec(_attr_strip(cuenta_node, "SaldoDeudor")),
        saldo_acreedor=_dec(_attr_strip(cuenta_node, "SaldoAcreedor")),
    )


def _parse_balanza_from_root(root: etree._Element) -> Optional[BalanzaData]:
    """Lógica compartida de parsing de Balanza desde un root XML."""
    cont_node = _find_contabilidad_node(root)
    if cont_node is None:
        return None

    balanza_node = None
    for child in cont_node:
        if etree.QName(child).localname == "Balanza":
            balanza_node = child
            break

    if balanza_node is None:
        return None

    data = BalanzaData(
        version=_attr_strip(balanza_node, "Version"),
        rfc=_attr_strip(balanza_node, "Rfc"),
        mes=_attr_strip(balanza_node, "Mes"),
        ejercicio=_attr_strip(balanza_node, "Ejercicio"),
        fecha_creacion=_attr_strip(balanza_node, "FechaCreacion"),
        tipo_balance=_attr_strip(balanza_node, "TipoBalance"),
    )

    for child in balanza_node:
        if etree.QName(child).localname == "Cuenta":
            data.cuentas.append(_parse_balanza_account(child))

    return data


def parse_balanza_xml(xml_path: str) -> Optional[BalanzaData]:
    """Parsea la Balanza de Comprobación desde un archivo XML del SAT.

    Args:
        xml_path: Ruta al archivo XML de contabilidad electrónica.

    Returns:
        BalanzaData con los campos extraídos, o None si no hay nodo Balanza.

    Raises:
        OSError: Si el archivo no existe.
        etree.XMLSyntaxError: Si el XML está mal formado.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    tree = safe_parse(xml_path)
    root = tree.getroot()
    return _parse_balanza_from_root(root)


def parse_balanza_bytes(xml_bytes: bytes) -> Optional[BalanzaData]:
    """Parsea la Balanza de Comprobación desde bytes XML en memoria."""
    root = safe_fromstring(xml_bytes)
    return _parse_balanza_from_root(root)


# ---------------------------------------------------------------------------
# Parser de Catálogo de Cuentas
# ---------------------------------------------------------------------------

def _parse_catalogo_account(cuenta_node: etree._Element) -> AccountCatalogEntry:
    """Extrae una línea de cuenta del Catálogo."""
    nivel_str = _attr_strip(cuenta_node, "Nivel")
    nivel = None
    if nivel_str is not None:
        try:
            nivel = int(nivel_str)
        except (ValueError, TypeError):
            nivel = None

    return AccountCatalogEntry(
        num_cuenta=_attr_strip(cuenta_node, "NumCta") or "",
        desc=_attr_strip(cuenta_node, "Desc") or "",
        nivel=nivel,
        naturaleza=_attr_strip(cuenta_node, "Naturaleza"),
        codigo_agrupador=_attr_strip(cuenta_node, "CodigoAgrupador"),
        estado_cuenta=_attr_strip(cuenta_node, "EstadoCuenta"),
    )


def _parse_catalogo_from_root(root: etree._Element) -> Optional[CatalogoData]:
    """Lógica compartida de parsing de Catálogo desde un root XML."""
    cont_node = _find_contabilidad_node(root)
    if cont_node is None:
        return None

    catalogo_node = None
    for child in cont_node:
        if etree.QName(child).localname == "Catalogo":
            catalogo_node = child
            break

    if catalogo_node is None:
        return None

    data = CatalogoData(
        version=_attr_strip(catalogo_node, "Version"),
        rfc=_attr_strip(catalogo_node, "Rfc"),
        mes=_attr_strip(catalogo_node, "Mes"),
        ejercicio=_attr_strip(catalogo_node, "Ejercicio"),
        fecha_creacion=_attr_strip(catalogo_node, "FechaCreacion"),
    )

    for child in catalogo_node:
        if etree.QName(child).localname == "Cuenta":
            data.cuentas.append(_parse_catalogo_account(child))

    return data


def parse_catalogo_xml(xml_path: str) -> Optional[CatalogoData]:
    """Parsea el Catálogo de Cuentas desde un archivo XML del SAT.

    Args:
        xml_path: Ruta al archivo XML de contabilidad electrónica.

    Returns:
        CatalogoData con los campos extraídos, o None si no hay nodo Catalogo.

    Raises:
        OSError: Si el archivo no existe.
        etree.XMLSyntaxError: Si el XML está mal formado.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    tree = safe_parse(xml_path)
    root = tree.getroot()
    return _parse_catalogo_from_root(root)


def parse_catalogo_bytes(xml_bytes: bytes) -> Optional[CatalogoData]:
    """Parsea el Catálogo de Cuentas desde bytes XML en memoria."""
    root = safe_fromstring(xml_bytes)
    return _parse_catalogo_from_root(root)


# ---------------------------------------------------------------------------
# Parser de Estado de Resultados
# ---------------------------------------------------------------------------

def _parse_estado_resultados_line(line_node: etree._Element) -> IncomeStatementLine:
    """Extrae una línea del Estado de Resultados."""
    return IncomeStatementLine(
        concepto=_attr_strip(line_node, "Concepto") or "",
        importe=_dec(_attr_strip(line_node, "Importe")),
    )


def _parse_estado_resultados_from_root(
    root: etree._Element,
) -> Optional[EstadoResultadosData]:
    """Lógica compartida de parsing de Estado de Resultados desde root XML."""
    cont_node = _find_contabilidad_node(root)
    if cont_node is None:
        return None

    er_node = None
    for child in cont_node:
        if etree.QName(child).localname == "EstadoResultados":
            er_node = child
            break

    if er_node is None:
        return None

    data = EstadoResultadosData(
        version=_attr_strip(er_node, "Version"),
        rfc=_attr_strip(er_node, "Rfc"),
        mes=_attr_strip(er_node, "Mes"),
        ejercicio=_attr_strip(er_node, "Ejercicio"),
        fecha_creacion=_attr_strip(er_node, "FechaCreacion"),
        tipo_balanza=_attr_strip(er_node, "TipoBalanza"),
    )

    for child in er_node:
        if etree.QName(child).localname in ("Ingresos", "Costos", "Gastos",
                                              "Resultados"):
            for sub in child:
                if etree.QName(sub).localname in ("Concepto", "ConceptoIngresos",
                                                    "ConceptoCostos",
                                                    "ConceptoGastos"):
                    data.lineas.append(_parse_estado_resultados_line(sub))
                elif etree.QName(sub).localname in ("MontoIngresos",
                                                      "MontoCostos",
                                                      "MontoGastos",
                                                      "Utilidad",
                                                      "Perdida"):
                    data.lineas.append(_parse_estado_resultados_line(sub))
        else:
            # Concepto directo bajo EstadoResultados
            localname = etree.QName(child).localname
            if localname in ("Concepto", "ConceptoIngresos", "ConceptoCostos",
                             "ConceptoGastos", "MontoIngresos", "MontoCostos",
                             "MontoGastos", "Utilidad", "Perdida"):
                data.lineas.append(_parse_estado_resultados_line(child))

    return data


def parse_estado_resultados_xml(xml_path: str) -> Optional[EstadoResultadosData]:
    """Parsea el Estado de Resultados desde un archivo XML del SAT.

    Args:
        xml_path: Ruta al archivo XML de contabilidad electrónica.

    Returns:
        EstadoResultadosData con los campos extraídos, o None si no hay nodo
        EstadoResultados.

    Raises:
        OSError: Si el archivo no existe.
        etree.XMLSyntaxError: Si el XML está mal formado.
    """
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")

    tree = safe_parse(xml_path)
    root = tree.getroot()
    return _parse_estado_resultados_from_root(root)


def parse_estado_resultados_bytes(
    xml_bytes: bytes,
) -> Optional[EstadoResultadosData]:
    """Parsea el Estado de Resultados desde bytes XML en memoria."""
    root = etree.fromstring(xml_bytes)
    return _parse_estado_resultados_from_root(root)
