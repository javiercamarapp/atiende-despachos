# -*- coding: utf-8 -*-
"""
diot_validator.py — Validates DIOT XML files against SAT requirements.

The Declaración Informativa de Operaciones con Terceros (DIOT) is a
mandatory Mexican tax report (CFF Art. 85-A).  This module parses SAT-
format DIOT XML, validates every <Operacion> node, and returns a
structured validation result.

SAT XML structure expected:
  <DIOT>
    <Operacion>
      <RFC>...</RFC>                  # 13 chars, regex-validated
      <RazonSocial>...</RazonSocial> # non-empty
      <TipoOperacion>01</TipoOperacion>  # 01=IVA, 02=IEPS, 03=Exento
      <Monto>10000.00</Monto>        # > 0
      <IVATrasladado>1600.00</IVATrasladado>  # >= 0
      <IVAAcreditable>1600.00</IVAAcreditable> # >= 0
      <FechaOperacion>2024-01-15</FechaOperacion>
    </Operacion>
    ...
  </DIOT>
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RFC_REGEX = re.compile(r"^[A-Z&]{3,4}\d{6}[A-Z\d]{3}$")

VALID_TIPO_OPERACION = {"01", "02", "03"}  # IVA, IEPS, Exento
TIPO_OPERACION_LABELS = {
    "01": "IVA",
    "02": "IEPS",
    "03": "Exento",
}

REQUIRED_FIELDS = (
    "RFC",
    "RazonSocial",
    "TipoOperacion",
    "Monto",
    "IVATrasladado",
    "IVAAcreditable",
)

# Field names that must parse as non-negative floats
NON_NEGATIVE_FIELDS = ("Monto", "IVATrasladado", "IVAAcreditable")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation issue found in a DIOT XML file."""
    operacion_index: int  # 1-based index of the <Operacion>
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"

    def __repr__(self) -> str:
        return (
            f"ValidationError(op#{self.operacion_index}, "
            f"field={self.field}, severity={self.severity}): "
            f"{self.message}"
        )


@dataclass
class DIOTValidationResult:
    """Aggregate result of validating an entire DIOT XML document."""
    valid: bool = True
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    total_operations: int = 0
    total_monto: float = 0.0
    total_iva_trasladado: float = 0.0
    total_iva_acreditable: float = 0.0
    declared_total_iva_trasladado: Optional[float] = None
    rfc_set: List[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def has_critical_errors(self) -> bool:
        return any(e.severity == "error" for e in self.errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "total_operations": self.total_operations,
            "total_monto": self.total_monto,
            "total_iva_trasladado": self.total_iva_trasladado,
            "total_iva_acreditable": self.total_iva_acreditable,
            "declared_total_iva_trasladado": self.declared_total_iva_trasladado,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "rfc_set": self.rfc_set,
        }


# ---------------------------------------------------------------------------
# Individual field validators
# ---------------------------------------------------------------------------

def validate_rfc_format(rfc: str) -> Optional[str]:
    """Validate a single RFC string against the SAT regex pattern.

    Returns ``None`` if valid, or an error message if invalid.
    """
    if not rfc or not isinstance(rfc, str) or not rfc.strip():
        return "RFC no puede estar vacío."

    rfc = rfc.strip().upper()

    if not RFC_REGEX.match(rfc):
        return (
            f"RFC '{rfc}' no cumple el patrón SAT "
            f"(3-4 letras/& + 6 dígitos + 3 alfanuméricos)."
        )

    if len(rfc) == 12:
        # Persona moral
        return None
    elif len(rfc) == 13:
        # Persona física
        return None
    else:
        return f"RFC '{rfc}' tiene longitud inválida ({len(rfc)})."


def validate_tipo_operacion(value: str) -> Optional[str]:
    """Validate the TipoOperacion field. Accepted: '01', '02', '03'."""
    if not value or not isinstance(value, str) or not value.strip():
        return "TipoOperacion no puede estar vacío."
    if value.strip() not in VALID_TIPO_OPERACION:
        return (
            f"TipoOperacion '{value}' inválido. "
            f"Valores aceptados: {', '.join(sorted(VALID_TIPO_OPERACION))}."
        )
    return None


def validate_non_negative_float(value: Any, field_name: str) -> Optional[str]:
    """Validate that a value parses as a non-negative float."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{field_name} es obligatorio."
    try:
        num = float(value)
    except (ValueError, TypeError):
        return f"{field_name} debe ser numérico, se recibió '{value}'."
    if num < 0:
        return f"{field_name} no puede ser negativo ({num})."
    return None


def validate_positive_float(value: Any, field_name: str) -> Optional[str]:
    """Validate that a value parses as a strictly positive float."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{field_name} es obligatorio."
    try:
        num = float(value)
    except (ValueError, TypeError):
        return f"{field_name} debe ser numérico, se recibió '{value}'."
    if num <= 0:
        return f"{field_name} debe ser mayor a cero ({num})."
    return None


def validate_razon_social(value: Any) -> Optional[str]:
    """Validate RazonSocial is present and non-empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "RazonSocial no puede estar vacío."
    return None


def validate_operation_xml(node: ET.Element, index: int) -> List[ValidationError]:
    """Validate a single <Operacion> XML node.

    Returns a list of ``ValidationError`` objects (empty if valid).
    """
    errors: List[ValidationError] = []
    prefix = f"Operación #{index}"

    # --- Required fields ---
    for fld in REQUIRED_FIELDS:
        el = node.find(fld)
        if el is None or el.text is None or (isinstance(el.text, str) and not el.text.strip()):
            errors.append(ValidationError(
                operacion_index=index,
                field=fld,
                message=f"{prefix}: campo '{fld}' es obligatorio y no está presente.",
            ))

    # --- RFC format ---
    rfc_el = node.find("RFC")
    if rfc_el is not None and rfc_el.text:
        err = validate_rfc_format(rfc_el.text)
        if err:
            errors.append(ValidationError(
                operacion_index=index,
                field="RFC",
                message=f"{prefix}: {err}",
            ))

    # --- RazonSocial ---
    rs_el = node.find("RazonSocial")
    if rs_el is not None and rs_el.text:
        err = validate_razon_social(rs_el.text)
        if err:
            errors.append(ValidationError(
                operacion_index=index,
                field="RazonSocial",
                message=f"{prefix}: {err}",
            ))

    # --- TipoOperacion ---
    to_el = node.find("TipoOperacion")
    if to_el is not None and to_el.text:
        err = validate_tipo_operacion(to_el.text.strip())
        if err:
            errors.append(ValidationError(
                operacion_index=index,
                field="TipoOperacion",
                message=f"{prefix}: {err}",
            ))

    # --- Numeric fields ---
    monto_el = node.find("Monto")
    if monto_el is not None and monto_el.text:
        err = validate_positive_float(monto_el.text.strip(), "Monto")
        if err:
            errors.append(ValidationError(
                operacion_index=index,
                field="Monto",
                message=f"{prefix}: {err}",
            ))

    for fld in ("IVATrasladado", "IVAAcreditable"):
        el = node.find(fld)
        if el is not None and el.text:
            err = validate_non_negative_float(el.text.strip(), fld)
            if err:
                errors.append(ValidationError(
                    operacion_index=index,
                    field=fld,
                    message=f"{prefix}: {err}",
                ))

    # --- IVA consistency warning ---
    monto_val = _safe_float(monto_el.text if monto_el is not None else None)
    iva_t_el = node.find("IVATrasladado")
    iva_t_val = _safe_float(iva_t_el.text if iva_t_el is not None else None)
    if monto_val and monto_val > 0 and iva_t_val and iva_t_val > 0:
        effective_rate = iva_t_val / monto_val
        valid_rates = (0.0, 0.08, 0.16)
        closest = min(valid_rates, key=lambda r: abs(r - effective_rate))
        if abs(closest - effective_rate) > 0.015:
            errors.append(ValidationError(
                operacion_index=index,
                field="IVATrasladado",
                message=(
                    f"{prefix}: tasa IVA efectiva {effective_rate:.2%} "
                    f"no coincide con tasas estándar (0%, 8%, 16%)."
                ),
                severity="warning",
            ))

    return errors


# ---------------------------------------------------------------------------
# XML parsing + full document validation
# ---------------------------------------------------------------------------

def parse_diot_xml(xml_source: str | Path) -> ET.Element:
    """Parse a DIOT XML file or string and return the root element.

    Raises ``ET.ParseError`` if the XML is malformed.
    """
    if isinstance(xml_source, Path):
        tree = ET.parse(str(xml_source))
        return tree.getroot()

    if isinstance(xml_source, str):
        # If it looks like XML content (starts with '<'), parse as string
        stripped = xml_source.strip()
        if stripped.startswith("<"):
            return ET.fromstring(stripped)
        # Otherwise treat as a file path
        tree = ET.parse(xml_source)
        return tree.getroot()

    raise TypeError(f"Expected str or Path, got {type(xml_source)}")


def validate_diot_xml(xml_source: str | Path) -> DIOTValidationResult:
    """Validate an entire DIOT XML document.

    Parameters
    ----------
    xml_source : str or Path
        Either a file path to an XML file or an XML string.

    Returns
    -------
    DIOTValidationResult
        Structured result with all errors, warnings, and computed totals.
    """
    result = DIOTValidationResult()

    try:
        root = parse_diot_xml(xml_source)
    except ET.ParseError as e:
        result.valid = False
        result.errors.append(ValidationError(
            operacion_index=0,
            field="XML",
            message=f"Error de parseo XML: {e}",
        ))
        return result
    except FileNotFoundError as e:
        result.valid = False
        result.errors.append(ValidationError(
            operacion_index=0,
            field="XML",
            message=f"Archivo no encontrado: {e}",
        ))
        return result

    # Find all <Operacion> nodes (support both <Operacion> and <Registro>)
    operations = root.findall(".//Operacion")
    if not operations:
        operations = root.findall(".//Registro")

    result.total_operations = len(operations)

    if not operations:
        result.valid = False
        result.errors.append(ValidationError(
            operacion_index=0,
            field="XML",
            message="No se encontraron nodos <Operacion> o <Registro> en el XML.",
            severity="error",
        ))
        return result

    all_errors: List[ValidationError] = []
    rfcs_seen: List[str] = []

    for idx, op_node in enumerate(operations, start=1):
        op_errors = validate_operation_xml(op_node, idx)
        all_errors.extend(op_errors)

        # Accumulate totals (only from fields that parse correctly)
        monto_el = op_node.find("Monto")
        iva_t_el = op_node.find("IVATrasladado")
        iva_a_el = op_node.find("IVAAcreditable")

        result.total_monto += _safe_float(monto_el.text if monto_el is not None else None)
        result.total_iva_trasladado += _safe_float(iva_t_el.text if iva_t_el is not None else None)
        result.total_iva_acreditable += _safe_float(iva_a_el.text if iva_a_el is not None else None)

        # Collect RFCs
        rfc_el = op_node.find("RFC")
        if rfc_el is not None and rfc_el.text:
            rfcs_seen.append(rfc_el.text.strip().upper())

    # Try to read declared total from header
    total_el = root.find(".//TotalIVATrasladado")
    if total_el is None:
        total_el = root.find(".//TotalIVATrasladado")
    if total_el is not None and total_el.text:
        try:
            result.declared_total_iva_trasladado = float(total_el.text.strip())
        except (ValueError, TypeError):
            pass

    # Cross-check: sum of iva_trasladado vs declared total
    if result.declared_total_iva_trasladado is not None:
        diff = abs(result.total_iva_trasladado - result.declared_total_iva_trasladado)
        if diff > 0.01:
            all_errors.append(ValidationError(
                operacion_index=0,
                field="TotalIVATrasladado",
                message=(
                    f"La suma de IVA trasladado ({result.total_iva_trasladado:.2f}) "
                    f"no coincide con el total declarado "
                    f"({result.declared_total_iva_trasladado:.2f}). "
                    f"Diferencia: {diff:.2f}"
                ),
                severity="error",
            ))

    # Separate errors vs warnings
    result.errors = [e for e in all_errors if e.severity == "error"]
    result.warnings = [e for e in all_errors if e.severity == "warning"]
    result.rfc_set = sorted(set(rfcs_seen))
    result.valid = len(result.errors) == 0

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(text: Optional[str], default: float = 0.0) -> float:
    """Parse a text value as float, returning *default* on failure."""
    if text is None:
        return default
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return default
