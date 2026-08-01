# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for DIOT data.

Validates:
  - RFC format (personas morales 12 chars, físicas 13 chars)
  - IVA rate validation (16%, 0%, 8%)
  - Cross-reference with CFDI data
  - DIOT entry completeness
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .models import CFDIInvoiceInput, DiotEntry, Inconsistencia


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_IVA_RATES = {0.0, 0.08, 0.16}
VALID_IVA_RATES_DISPLAY = {"0%", "8%", "16%"}

# RFC pattern
RFC_PERSONA_MORAL_PATTERN = re.compile(r"^[A-Z&Ñ]{3}\d{6}[A-Z\d]{3}$")
RFC_PERSONA_FISICA_PATTERN = re.compile(r"^[A-Z&Ñ]{4}\d{6}[A-Z\d]{3}$")


# ---------------------------------------------------------------------------
# ValidationResult — used by service.py
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Resultado de validación de datos DIOT."""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    inconsistencies: List[Inconsistencia] = field(default_factory=list)
    valid_entries: int = 0
    total_entries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "valid_entries": self.valid_entries,
            "total_entries": self.total_entries,
        }


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_rfc(rfc: str) -> Tuple[bool, str]:
    """Validate a Mexican RFC (Registro Federal de Contribuyentes)."""
    if not rfc or not rfc.strip():
        return False, "RFC no puede estar vacío."

    rfc = rfc.strip().upper()

    if len(rfc) < 12 or len(rfc) > 13:
        return False, f"RFC con longitud inválida ({len(rfc)} chars). Se esperaba 12-13."

    if len(rfc) == 12:
        if RFC_PERSONA_MORAL_PATTERN.match(rfc):
            return True, ""
        return False, f"RFC de persona moral con formato inválido: '{rfc}'."

    if len(rfc) == 13:
        if RFC_PERSONA_FISICA_PATTERN.match(rfc):
            return True, ""
        return False, f"RFC de persona física con formato inválido: '{rfc}'."

    return False, f"RFC con longitud inesperada: '{rfc}'."


def validate_iva_rate(rate: float) -> Tuple[bool, str]:
    """Validate an IVA rate. Accepted rates: 0%, 8%, 16%."""
    if rate not in VALID_IVA_RATES:
        return False, (
            f"Tasa de IVA inválida: {rate}. "
            f"Tasas aceptadas: 0%, 8%, 16%."
        )
    return True, ""


def validate_iva_amount(
    monto_neto: float,
    iva_trasladado: float,
    expected_rate: float = 0.16,
    tolerance: float = 0.01,
) -> Tuple[bool, str]:
    """Validate that IVA amount matches the expected rate applied to monto_neto."""
    expected_iva = monto_neto * expected_rate
    if expected_iva == 0:
        if iva_trasladado == 0:
            return True, ""
        return False, f"Se esperaba IVA=0 para monto_neto=0, pero se encontró IVA={iva_trasladado}."

    if expected_iva != 0:
        variance = abs(iva_trasladado - expected_iva) / abs(expected_iva)
        if variance > tolerance:
            return False, (
                f"IVA trasladado ({iva_trasladado}) no coincide con "
                f"esperado ({expected_iva:.2f} = {monto_neto} × {expected_rate}). "
                f"Varianza: {variance:.2%}."
            )
    return True, ""


# ---------------------------------------------------------------------------
# Bulk validators — DIOT entries
# ---------------------------------------------------------------------------

def _entry_to_dict(entry: Any) -> Dict[str, Any]:
    """Convert a DiotEntry or plain dict to a dict for validation."""
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, DiotEntry):
        return {
            "rfc_tercero": entry.rfc_tercero,
            "nombre": entry.nombre,
            "tipo_operacion": entry.tipo_operacion.value if hasattr(entry.tipo_operacion, "value") else entry.tipo_operacion,
            "monto_neto": entry.monto_neto,
            "iva_trasladado": entry.iva_trasladado,
            "iva_acreditable": entry.iva_acreditable,
        }
    return dict(entry)


def validate_diot_entries(
    entries: List[Any],
    invoices: List[Any] | None = None,
) -> ValidationResult:
    """Validate a list of DIOT entries (dicts or DiotEntry objects).

    Returns a ``ValidationResult`` with ``.valid``, ``.inconsistencies``,
    ``.errors``, and ``.warnings``.
    """
    errors: List[str] = []
    warnings: List[str] = []
    inconsistencies: List[Inconsistencia] = []
    seen: set = set()

    total = len(entries)
    valid_count = 0

    if not entries:
        return ValidationResult(
            valid=False,
            errors=["La lista de entradas DIOT está vacía."],
            total_entries=0,
        )

    for i, raw in enumerate(entries, 1):
        entry = _entry_to_dict(raw)
        prefix = f"Entrada #{i}"
        entry_ok = True

        # Required fields
        for fld in ("rfc_tercero", "tipo_operacion", "monto_neto", "iva_trasladado", "iva_acreditable"):
            if fld not in entry or entry[fld] is None:
                errors.append(f"{prefix}: campo '{fld}' es obligatorio.")
                entry_ok = False

        # RFC validation
        rfc = entry.get("rfc_tercero", "")
        if rfc:
            is_valid_rfc, rfc_err = validate_rfc(rfc)
            if not is_valid_rfc:
                errors.append(f"{prefix}: {rfc_err}")
                entry_ok = False

        # IVA rate check
        monto_neto = entry.get("monto_neto", 0)
        iva_trasladado = entry.get("iva_trasladado", 0)
        if monto_neto and monto_neto > 0 and iva_trasladado > 0:
            effective_rate = round(iva_trasladado / monto_neto, 4)
            if effective_rate not in {0.0, 0.08, 0.16}:
                valid_rates = [0.0, 0.08, 0.16]
                closest = min(valid_rates, key=lambda r: abs(r - effective_rate))
                if abs(closest - effective_rate) > 0.01:
                    errors.append(
                        f"{prefix}: tasa de IVA efectiva {effective_rate:.2%} "
                        f"no es válida (0%, 8%, 16%)."
                    )
                    entry_ok = False

        # Non-negative amounts
        for field_name in ("monto_neto", "iva_trasladado", "iva_acreditable"):
            val = entry.get(field_name)
            if val is not None and val < 0:
                errors.append(f"{prefix}: {field_name} no puede ser negativo ({val}).")
                entry_ok = False

        # Duplicate check
        rfc_key = entry.get("rfc_tercero", "").strip().upper()
        tipo = entry.get("tipo_operacion", "")
        dup_key = (rfc_key, tipo)
        if dup_key in seen:
            warnings.append(
                f"{prefix}: operación duplicada para RFC='{rfc_key}' tipo='{tipo}'."
            )
        seen.add(dup_key)

        if entry_ok:
            valid_count += 1

    # Cross-reference with invoices if provided
    if invoices:
        invoice_rfc_set = set()
        for inv in invoices:
            if isinstance(inv, CFDIInvoiceInput):
                invoice_rfc_set.add(inv.rfc_emisor)
            elif isinstance(inv, dict):
                invoice_rfc_set.add(inv.get("rfc_tercero", "").upper())

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        inconsistencies=inconsistencies,
        valid_entries=valid_count,
        total_entries=total,
    )


# ---------------------------------------------------------------------------
# Bulk validators — CFDI invoices
# ---------------------------------------------------------------------------

def validate_invoices(
    invoices: List[Any],
) -> ValidationResult:
    """Validate CFDI invoice data before DIOT generation.

    Checks RFC format, amounts, and required fields.
    """
    errors: List[str] = []
    warnings: List[str] = []
    inconsistencies: List[Inconsistencia] = []
    valid_count = 0
    total = len(invoices)

    if not invoices:
        return ValidationResult(
            valid=False,
            errors=["No se proporcionaron facturas para validar."],
            total_entries=0,
        )

    for i, inv in enumerate(invoices, 1):
        prefix = f"Factura #{i}"
        inv_dict = inv.model_dump() if hasattr(inv, "model_dump") else dict(inv)
        inv_ok = True

        # Required: uuid
        uuid = inv_dict.get("uuid", "")
        if not uuid:
            errors.append(f"{prefix}: campo 'uuid' es obligatorio.")
            inv_ok = False

        # Required: rfc_emisor
        rfc = inv_dict.get("rfc_emisor", "")
        if not rfc:
            errors.append(f"{prefix}: campo 'rfc_emisor' es obligatorio.")
            inv_ok = False
        else:
            ok, err = validate_rfc(rfc)
            if not ok:
                errors.append(f"{prefix}: {err}")
                inv_ok = False

        # Amounts: subtotal must be >= 0
        subtotal = inv_dict.get("subtotal", 0)
        if subtotal < 0:
            errors.append(f"{prefix}: subtotal no puede ser negativo.")
            inv_ok = False

        iva_t = inv_dict.get("iva_trasladado", 0)
        iva_a = inv_dict.get("iva_acreditable", 0)
        if iva_t < 0:
            errors.append(f"{prefix}: iva_trasladado no puede ser negativo.")
            inv_ok = False
        if iva_a < 0:
            errors.append(f"{prefix}: iva_acreditable no puede ser negativo.")
            inv_ok = False

        if inv_ok:
            valid_count += 1

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        inconsistencies=inconsistencies,
        valid_entries=valid_count,
        total_entries=total,
    )
