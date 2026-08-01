# -*- coding: utf-8 -*-
"""
diot_service.py — Process DIOT files, generate summary reports, and
calculate totals by RFC.

This service layer sits on top of ``diot_validator`` and provides
higher-level operations:

  • parse_diot_file()      — parse XML and extract operation records
  • generate_summary()     — aggregate totals for the whole document
  • calculate_totals_by_rfc() — per-RFC breakdown
  • process_diot()         — full pipeline: parse → validate → summarize
  • generate_report()      — human-readable summary report (dict)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from b2b_ai.services.diot_validator import (
    DIOTValidationResult,
    TIPO_OPERACION_LABELS,
    _safe_float,
    validate_diot_xml,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DIOTOperation:
    """A single parsed DIOT operation."""
    rfc: str
    razon_social: str
    tipo_operacion: str
    monto: float
    iva_trasladado: float
    iva_acreditable: float
    fecha_operacion: Optional[str] = None

    @property
    def tipo_operacion_label(self) -> str:
        return TIPO_OPERACION_LABELS.get(self.tipo_operacion, f"Desconocido({self.tipo_operacion})")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rfc": self.rfc,
            "razon_social": self.razon_social,
            "tipo_operacion": self.tipo_operacion,
            "tipo_operacion_label": self.tipo_operacion_label,
            "monto": self.monto,
            "iva_trasladado": self.iva_trasladado,
            "iva_acreditable": self.iva_acreditable,
            "fecha_operacion": self.fecha_operacion,
        }


@dataclass
class RFCSummary:
    """Aggregated totals for a single RFC across all operations."""
    rfc: str
    razon_social: str = ""
    total_monto: float = 0.0
    total_iva_trasladado: float = 0.0
    total_iva_acreditable: float = 0.0
    num_operations: int = 0
    operation_types: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rfc": self.rfc,
            "razon_social": self.razon_social,
            "total_monto": self.total_monto,
            "total_iva_trasladado": self.total_iva_trasladado,
            "total_iva_acreditable": self.total_iva_acreditable,
            "num_operations": self.num_operations,
            "operation_types": self.operation_types,
        }


@dataclass
class DIOTSummary:
    """Summary of the entire DIOT document."""
    total_operations: int = 0
    unique_rfcs: int = 0
    total_monto: float = 0.0
    total_iva_trasladado: float = 0.0
    total_iva_acreditable: float = 0.0
    declared_total_iva_trasladado: Optional[float] = None
    iva_balance: float = 0.0  # trasladado - acreditable
    by_rfc: Dict[str, RFCSummary] = field(default_factory=dict)
    by_tipo_operacion: Dict[str, int] = field(default_factory=dict)
    validation: Optional[DIOTValidationResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_operations": self.total_operations,
            "unique_rfcs": self.unique_rfcs,
            "total_monto": self.total_monto,
            "total_iva_trasladado": self.total_iva_trasladado,
            "total_iva_acreditable": self.total_iva_acreditable,
            "declared_total_iva_trasladado": self.declared_total_iva_trasladado,
            "iva_balance": self.iva_balance,
            "by_rfc": {k: v.to_dict() for k, v in self.by_rfc.items()},
            "by_tipo_operacion": self.by_tipo_operacion,
            "is_valid": self.validation.valid if self.validation else True,
            "error_count": self.validation.error_count if self.validation else 0,
        }


@dataclass
class DIOTReport:
    """Full processing result: parsed operations + summary + validation."""
    operations: List[DIOTOperation] = field(default_factory=list)
    summary: Optional[DIOTSummary] = None
    validation: Optional[DIOTValidationResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operations": [op.to_dict() for op in self.operations],
            "summary": self.summary.to_dict() if self.summary else None,
            "validation": self.validation.to_dict() if self.validation else None,
        }


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def parse_diot_file(xml_source: str | Path) -> List[DIOTOperation]:
    """Parse a DIOT XML file and extract all operations.

    Parameters
    ----------
    xml_source : str or Path
        File path or XML string.

    Returns
    -------
    list of DIOTOperation
    """
    if isinstance(xml_source, Path):
        tree = ET.parse(str(xml_source))
        root = tree.getroot()
    elif isinstance(xml_source, str):
        stripped = xml_source.strip()
        if stripped.startswith("<"):
            root = ET.fromstring(stripped)
        else:
            tree = ET.parse(xml_source)
            root = tree.getroot()
    else:
        raise TypeError(f"Expected str or Path, got {type(xml_source)}")

    # Support both <Operacion> and <Registro> node names
    nodes = root.findall(".//Operacion")
    if not nodes:
        nodes = root.findall(".//Registro")

    operations: List[DIOTOperation] = []
    for node in nodes:
        op = _parse_operation_node(node)
        if op is not None:
            operations.append(op)

    return operations


def _parse_operation_node(node: ET.Element) -> Optional[DIOTOperation]:
    """Extract a DIOTOperation from an XML element, skipping malformed nodes."""
    def _text(tag: str) -> str:
        el = node.find(tag)
        return (el.text or "").strip() if el is not None else ""

    rfc = _text("RFC")
    if not rfc:
        return None

    return DIOTOperation(
        rfc=rfc.upper(),
        razon_social=_text("RazonSocial"),
        tipo_operacion=_text("TipoOperacion"),
        monto=_safe_float(_text("Monto")),
        iva_trasladado=_safe_float(_text("IVATrasladado")),
        iva_acreditable=_safe_float(_text("IVAAcreditable")),
        fecha_operacion=_text("FechaOperacion") or None,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def calculate_totals_by_rfc(operations: List[DIOTOperation]) -> Dict[str, RFCSummary]:
    """Aggregate totals per RFC from a list of operations.

    Returns a dict keyed by RFC with RFCSummary values.
    """
    by_rfc: Dict[str, RFCSummary] = {}

    for op in operations:
        if op.rfc not in by_rfc:
            by_rfc[op.rfc] = RFCSummary(rfc=op.rfc, razon_social=op.razon_social)

        s = by_rfc[op.rfc]
        s.total_monto += op.monto
        s.total_iva_trasladado += op.iva_trasladado
        s.total_iva_acreditable += op.iva_acreditable
        s.num_operations += 1

        label = op.tipo_operacion_label
        if label not in s.operation_types:
            s.operation_types.append(label)

    return by_rfc


def calculate_tipo_operacion_counts(operations: List[DIOTOperation]) -> Dict[str, int]:
    """Count operations by tipo_operacion."""
    counts: Dict[str, int] = defaultdict(int)
    for op in operations:
        counts[op.tipo_operacion] += 1
    return dict(counts)


def generate_summary(
    operations: List[DIOTOperation],
    validation: Optional[DIOTValidationResult] = None,
) -> DIOTSummary:
    """Build a complete DIOTSummary from parsed operations."""
    summary = DIOTSummary()

    if not operations:
        summary.validation = validation
        if validation and validation.declared_total_iva_trasladado is not None:
            summary.declared_total_iva_trasladado = validation.declared_total_iva_trasladado
        return summary

    summary.total_operations = len(operations)
    summary.unique_rfcs = len(set(op.rfc for op in operations))
    summary.total_monto = round(sum(op.monto for op in operations), 2)
    summary.total_iva_trasladado = round(sum(op.iva_trasladado for op in operations), 2)
    summary.total_iva_acreditable = round(sum(op.iva_acreditable for op in operations), 2)
    summary.iva_balance = round(summary.total_iva_trasladado - summary.total_iva_acreditable, 2)
    summary.by_rfc = calculate_totals_by_rfc(operations)
    summary.by_tipo_operacion = calculate_tipo_operacion_counts(operations)
    summary.validation = validation

    if validation and validation.declared_total_iva_trasladado is not None:
        summary.declared_total_iva_trasladado = validation.declared_total_iva_trasladado

    return summary


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def process_diot(xml_source: str | Path) -> DIOTReport:
    """Full processing pipeline: parse → validate → summarize.

    Parameters
    ----------
    xml_source : str or Path
        DIOT XML file path or string.

    Returns
    -------
    DIOTReport
        Contains parsed operations, summary, and validation result.
    """
    report = DIOTReport()

    # 1. Parse
    try:
        report.operations = parse_diot_file(xml_source)
    except ET.ParseError as e:
        report.validation = DIOTValidationResult(
            valid=False,
            total_operations=0,
        )
        report.validation.errors.append(
            __import__("b2b_ai.services.diot_validator", fromlist=["ValidationError"]).ValidationError(
                operacion_index=0, field="XML", message=f"Error de parseo: {e}",
            )
        )
        return report

    # 2. Validate
    report.validation = validate_diot_xml(xml_source)

    # 3. Summarize
    report.summary = generate_summary(report.operations, report.validation)

    return report


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(report: DIOTReport) -> Dict[str, Any]:
    """Generate a human-readable summary report dict.

    The dict contains sections for overview, per-RFC breakdown,
    tipo_operacion distribution, and any validation issues.
    """
    result: Dict[str, Any] = {
        "overview": {},
        "by_rfc": {},
        "by_tipo_operacion": {},
        "validation_summary": {},
    }

    if report.summary:
        s = report.summary
        result["overview"] = {
            "total_operations": s.total_operations,
            "unique_rfcs": s.unique_rfcs,
            "total_monto": s.total_monto,
            "total_iva_trasladado": s.total_iva_trasladado,
            "total_iva_acreditable": s.total_iva_acreditable,
            "iva_balance": s.iva_balance,
            "declared_total_iva_trasladado": s.declared_total_iva_trasladado,
        }
        result["by_rfc"] = {
            rfc: s_data.to_dict()
            for rfc, s_data in s.by_rfc.items()
        }
        result["by_tipo_operacion"] = {
            TIPO_OPERACION_LABELS.get(k, k): v
            for k, v in s.by_tipo_operacion.items()
        }

    if report.validation:
        v = report.validation
        result["validation_summary"] = {
            "valid": v.valid,
            "error_count": v.error_count,
            "warning_count": v.warning_count,
            "errors": [
                {"operacion": e.operacion_index, "field": e.field, "message": e.message}
                for e in v.errors
            ],
            "warnings": [
                {"operacion": e.operacion_index, "field": e.field, "message": e.message}
                for e in v.warnings
            ],
        }

    return result


# ---------------------------------------------------------------------------
# Convenience: list of operations from XML string
# ---------------------------------------------------------------------------

def operations_from_xml_string(xml_str: str) -> List[DIOTOperation]:
    """Convenience wrapper: parse operations directly from an XML string."""
    return parse_diot_file(xml_str)
