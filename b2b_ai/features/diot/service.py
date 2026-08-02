# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo DIOT.

DIOTService:
  - generate_diot(period, client_rfc, records) : agrupa operaciones del
    trimestre por tipo y construye la DIOTDeclaration.
  - validate_diot(records)                      : valida RFC, base gravable,
    IVA trasladado y IVA acreditable.
  - calculate_iva_summary(diot)                 : total IVA trasladado vs
    acreditable.
  - export_to_txt(records)                      : archivo TXT formato SAT.
  - export_to_xml(records)                      : XML según esquema SAT.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    DIOTDeclaration,
    DIOTPeriod,
    DIOTStatus,
    DIOTSummary,
    MULTA_SAT_MAX,
    MULTA_SAT_MIN,
)
from .validators import ValidationResult, coerce_record, validate_records

_declarations: Dict[str, DIOTDeclaration] = {}


def _store_key(client_rfc: str, period: DIOTPeriod) -> str:
    return f"{client_rfc}|{period.label}"


class DIOTService:
    """Servicio stateless para generar, validar y exportar la DIOT."""

    def generate_diot(
        self,
        period: DIOTPeriod,
        client_rfc: str,
        records: Optional[List[Any]] = None,
    ) -> DIOTDeclaration:
        """Genera una DIOT agrupando las operaciones del trimestre por tipo."""
        key = _store_key(client_rfc, period)
        if records is None:
            existing = _declarations.get(key)
            records = existing.records if existing else []
        typed_records = [coerce_record(r) for r in records]
        typed_records.sort(key=lambda r: r.tipo_operacion.value)
        declaration = DIOTDeclaration(
            client_rfc=client_rfc.strip().upper(),
            period=period,
            records=typed_records,
            status=DIOTStatus.VALIDANDO,
            created_at=datetime.utcnow(),
        )
        declaration.recompute_summary()
        validation = validate_records(typed_records)
        declaration.status = DIOTStatus.GENERADA if validation.valid else DIOTStatus.ERROR
        _declarations[key] = declaration
        return declaration

    def validate_diot(self, records: List[Any]) -> ValidationResult:
        """Valida RFC, base gravable, IVA trasladado y acreditable."""
        return validate_records([coerce_record(r) for r in records])

    def calculate_iva_summary(self, diot: DIOTDeclaration) -> DIOTSummary:
        """Calcula totales de IVA trasladado vs acreditable."""
        return diot.recompute_summary()

    def get_declaration(self, client_rfc: str, period: DIOTPeriod) -> Optional[DIOTDeclaration]:
        return _declarations.get(_store_key(client_rfc, period))

    def list_declarations(self, client_rfc: Optional[str] = None) -> List[DIOTDeclaration]:
        results = list(_declarations.values())
        if client_rfc:
            results = [d for d in results if d.client_rfc == client_rfc.upper()]
        return sorted(results, key=lambda d: (d.period.year, d.period.quarter), reverse=True)

    def export_to_txt(self, records: List[Any], output_dir: str = "/tmp/diot") -> str:
        """Genera un archivo TXT en formato de layout DIOT SAT."""
        typed_records = [coerce_record(r) for r in records]
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = out / f"DIOT_{ts}.txt"
        lines = ["RFC|NOMBRE|REGIMEN_FISCAL|TIPO_OPERACION|BASE_GRAVABLE|IVA_TRASLADADO|IVA_ACREDITABLE"]
        for r in typed_records:
            lines.append("|".join([
                r.rfc_tercero, r.nombre, r.regimen_fiscal or "",
                r.tipo_operacion.value, f"{r.base_gravable:.2f}",
                f"{r.iva_trasladado:.2f}", f"{r.iva_acreditable:.2f}",
            ]))
        filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(filepath)

    def export_to_xml(self, records: List[Any], output_dir: str = "/tmp/diot") -> str:
        """Genera un XML conforme al esquema DIOT del SAT."""
        typed_records = [coerce_record(r) for r in records]
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = out / f"DIOT_{ts}.xml"
        root = ET.Element("DIOT")
        encabezado = ET.SubElement(root, "Encabezado")
        ET.SubElement(encabezado, "TotalOperaciones").text = str(len(typed_records))
        ET.SubElement(encabezado, "TotalBaseGravable").text = str(
            round(sum(r.base_gravable for r in typed_records), 2))
        ET.SubElement(encabezado, "TotalIVATrasladado").text = str(
            round(sum(r.iva_trasladado for r in typed_records), 2))
        ET.SubElement(encabezado, "TotalIVAAcreditable").text = str(
            round(sum(r.iva_acreditable for r in typed_records), 2))
        for r in typed_records:
            reg = ET.SubElement(root, "Registro")
            reg.set("rfc", r.rfc_tercero)
            ET.SubElement(reg, "Nombre").text = r.nombre
            ET.SubElement(reg, "RegimenFiscal").text = r.regimen_fiscal or ""
            ET.SubElement(reg, "TipoOperacion").text = r.tipo_operacion.value
            ET.SubElement(reg, "BaseGravable").text = f"{r.base_gravable:.2f}"
            ET.SubElement(reg, "IVATrasladado").text = f"{r.iva_trasladado:.2f}"
            ET.SubElement(reg, "IVAAcreditable").text = f"{r.iva_acreditable:.2f}"
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(str(filepath), encoding="UTF-8", xml_declaration=True)
        return str(filepath)


def multa_por_no_presentar() -> tuple[float, float]:
    """Rango de multa SAT (CFF Art. 82) por DIOT no presentada."""
    return MULTA_SAT_MIN, MULTA_SAT_MAX
