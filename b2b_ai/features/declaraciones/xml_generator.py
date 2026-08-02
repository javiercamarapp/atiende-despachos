# -*- coding: utf-8 -*-
"""xml_generator.py — XMLGenerator: SAT-compliant XML declaration generation.

Generates XML for:
  - Declaración mensual IVA (pago mensual)
  - Declaración provisional ISR (PM y PF)
  - Declaración anual ISR
  - DIOT informativa

Follows Anexo 24 RMF XML schemas.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from xml.dom import minidom

from .engine import IvaResult, IsrResult, IepsResult, DiotResult


# SAT namespace for declaraciones
SAT_NS = "http://www.sat.gob.mx/esquemas/DeclaracionInformativa"


def _pretty_xml(root: ET.Element) -> str:
    """Return pretty-printed XML string without xml declaration."""
    rough = ET.tostring(root, encoding="unicode", xml_declaration=False)
    parsed = minidom.parseString(rough)
    # toprettyxml adds its own xml declaration; strip it
    lines = parsed.toprettyxml(indent="  ", encoding=None).split("\n")
    # Remove the xml declaration line added by minidom
    clean_lines = [l for l in lines if not l.strip().startswith("<?xml")]
    return "\n".join(clean_lines)


class XMLGenerator:
    """Generate SAT-compliant XML for fiscal declarations.

    Usage:
        gen = XMLGenerator()
        xml_bytes = gen.generate_iva_declaration(iva_result, rfc, periodo)
        gen.save(xml_bytes, "/tmp/declaraciones/iva_202407.xml")
    """

    def __init__(self):
        self._errors: list[str] = []

    @property
    def errors(self) -> list[str]:
        return self._errors

    def generate_iva_declaration(
        self,
        rfc: str,
        periodo: str,  # YYYY-MM
        iva_result: IvaResult,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Generate XML for monthly IVA declaration.

        LIVA Art. 5 — Declaración mensual del impuesto al valor agregado.
        """
        year, month = periodo.split("-")

        root = ET.Element("DeclaracionInformativa")
        root.set("xmlns", SAT_NS)
        root.set("Version", "1.0")
        root.set("TipoDeclaracion", "Normal")

        # Encabezado
        header = ET.SubElement(root, "Encabezado")
        ET.SubElement(header, "RFC").text = rfc.upper()
        ET.SubElement(header, "Ejercicio").text = year
        ET.SubElement(header, "Periodo").text = month.zfill(2)
        ET.SubElement(header, "FechaPresentacion").text = (
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        )

        # Datos IVA
        datos = ET.SubElement(root, "DatosIVA")
        ET.SubElement(datos, "IVATrasladado").text = f"{iva_result.iva_trasladado:.2f}"
        ET.SubElement(datos, "IVAAcreditable").text = f"{iva_result.iva_acreditable:.2f}"
        ET.SubElement(datos, "IVANeto").text = f"{iva_result.iva_neto:.2f}"
        ET.SubElement(datos, "SaldoFavor").text = f"{iva_result.saldo_favor:.2f}"
        ET.SubElement(datos, "SaldoContra").text = f"{iva_result.saldo_contra:.2f}"
        ET.SubElement(datos, "ProporcionAcreditable").text = (
            f"{iva_result.proporcion_acreditable:.4f}"
        )

        # Metadata
        if metadata:
            meta = ET.SubElement(root, "Metadata")
            for k, v in metadata.items():
                ET.SubElement(meta, k).text = str(v)

        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_str += _pretty_xml(root)
        return xml_str.encode("utf-8")

    def generate_isr_declaration(
        self,
        rfc: str,
        periodo: str,
        isr_result: IsrResult,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Generate XML for ISR declaration (provisional or annual).

        LISR Art. 14 (PM) / Art. 116 (PF) — Pagos provisionales.
        """
        # Determine if annual or monthly
        is_annual = len(periodo) == 4
        if is_annual:
            year = periodo
            month = "13"  # SAT uses "13" for annual
        else:
            year, month = periodo.split("-")

        root = ET.Element("DeclaracionInformativa")
        root.set("xmlns", SAT_NS)
        root.set("Version", "1.0")

        if is_annual:
            root.set("TipoDeclaracion", "Anual")
        else:
            root.set("TipoDeclaracion", "Provisional")

        # Encabezado
        header = ET.SubElement(root, "Encabezado")
        ET.SubElement(header, "RFC").text = rfc.upper()
        ET.SubElement(header, "Ejercicio").text = year
        ET.SubElement(header, "Periodo").text = month.zfill(2)
        ET.SubElement(header, "TipoContribuyente").text = isr_result.tipo_contribuyente
        ET.SubElement(header, "FechaPresentacion").text = (
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        )

        # Datos ISR
        datos = ET.SubElement(root, "DatosISR")
        ET.SubElement(datos, "BaseGravable").text = f"{isr_result.base_gravable:.2f}"
        ET.SubElement(datos, "ISRBruto").text = f"{isr_result.isr_bruto:.2f}"
        ET.SubElement(datos, "TasaEfectiva").text = f"{isr_result.tasa_efectiva:.4f}"
        ET.SubElement(datos, "PagosProvisionales").text = (
            f"{isr_result.pagos_provisionales:.2f}"
        )
        ET.SubElement(datos, "ISRNeto").text = f"{isr_result.isr_neto:.2f}"
        ET.SubElement(datos, "TablaAplicada").text = isr_result.tabla_aplicada

        # Metadata
        if metadata:
            meta = ET.SubElement(root, "Metadata")
            for k, v in metadata.items():
                ET.SubElement(meta, k).text = str(v)

        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_str += _pretty_xml(root)
        return xml_str.encode("utf-8")

    def generate_diot_xml(
        self,
        diot_result: DiotResult,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Generate XML for DIOT (Declaración Informativa de Operaciones
        con Terceros).

        CFF Art. 85 / RMF 3.10.7.
        """
        year, month = diot_result.periodo.split("-")

        root = ET.Element("DeclaracionDIOT")
        root.set("xmlns", SAT_NS)
        root.set("Version", "1.0")

        # Encabezado
        header = ET.SubElement(root, "Encabezado")
        ET.SubElement(header, "RFC").text = diot_result.rfc_contribuyente.upper()
        ET.SubElement(header, "Ejercicio").text = year
        ET.SubElement(header, "Periodo").text = month.zfill(2)
        ET.SubElement(header, "FechaPresentacion").text = (
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        )

        # Resumen
        resumen = ET.SubElement(root, "Resumen")
        ET.SubElement(resumen, "TotalRegistros").text = str(diot_result.total_records)
        ET.SubElement(resumen, "TotalMontoNeto").text = f"{diot_result.total_monto_neto:.2f}"
        ET.SubElement(resumen, "TotalIVATrasladado").text = (
            f"{diot_result.total_iva_trasladado:.2f}"
        )
        ET.SubElement(resumen, "TotalIVAAcreditable").text = (
            f"{diot_result.total_iva_acreditable:.2f}"
        )

        # Registros
        registros = ET.SubElement(root, "Registros")
        for rec in diot_result.records:
            reg = ET.SubElement(registros, "Registro")
            reg.set("TipoOperacion", rec.tipo_operacion)
            reg.set("TipoTercero", rec.tipo_tercero)
            reg.set("TipoDocumento", rec.tipo_documento)
            ET.SubElement(reg, "RFC").text = rec.rfc_tercero
            ET.SubElement(reg, "Nombre").text = rec.nombre
            ET.SubElement(reg, "Moneda").text = rec.moneda
            ET.SubElement(reg, "TipoCambio").text = f"{rec.tipo_cambio:.4f}"
            ET.SubElement(reg, "Fecha").text = rec.fecha or ""
            ET.SubElement(reg, "MontoNeto").text = f"{rec.monto_neto:.2f}"
            ET.SubElement(reg, "IVATrasladado16").text = f"{rec.iva_trasladado_16:.2f}"
            ET.SubElement(reg, "IVATrasladado0").text = f"{rec.iva_trasladado_0:.2f}"
            ET.SubElement(reg, "IVAAcreditable16").text = f"{rec.iva_acreditable_16:.2f}"
            ET.SubElement(reg, "IVAAcreditable0").text = f"{rec.iva_acreditable_0:.2f}"
            ET.SubElement(reg, "IVAExento").text = f"{rec.iva_exento:.2f}"
            ET.SubElement(reg, "IVARetenido").text = f"{rec.iva_retenido:.2f}"

        # Metadata
        if metadata:
            meta = ET.SubElement(root, "Metadata")
            for k, v in metadata.items():
                ET.SubElement(meta, k).text = str(v)

        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_str += _pretty_xml(root)
        return xml_str.encode("utf-8")

    def save(self, xml_bytes: bytes, filepath: str) -> str:
        """Save XML to file. Returns the file path."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(xml_bytes)
        return str(p)

    def validate_xml_structure(self, xml_bytes: bytes) -> bool:
        """Basic XML well-formedness check."""
        try:
            ET.fromstring(xml_bytes)
            self._errors = []
            return True
        except ET.ParseError as e:
            self._errors = [f"XML mal formado: {e}"]
            return False
