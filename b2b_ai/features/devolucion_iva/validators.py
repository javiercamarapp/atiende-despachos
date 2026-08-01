# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for Devolución de IVA data.

Validates:
  - RFC format (personas morales 12 chars, físicas 13 chars)
  - IVA rates (0%, 8%, 16%)
  - Amounts (positive, within range)
  - Dates (valid format, not future)
  - DIOT consistency with CFDIs
  - Declaration consistency with DIOT
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_IVA_RATES = {0.0, 0.08, 0.16}

RFC_PERSONA_MORAL_PATTERN = re.compile(r"^[A-Z&Ñ]{3}\d{6}[A-Z\d]{3}$")
RFC_PERSONA_FISICA_PATTERN = re.compile(r"^[A-Z&Ñ]{4}\d{6}[A-Z\d]{3}$")


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_rfc(rfc: str) -> Optional[str]:
    """Validate a Mexican RFC. Returns None if valid, error message if invalid."""
    if not rfc or not rfc.strip():
        return "RFC no puede estar vacío."

    rfc = rfc.strip().upper()

    if len(rfc) < 12 or len(rfc) > 13:
        return f"RFC con longitud inválida ({len(rfc)} chars). Se esperaba 12-13."

    if len(rfc) == 12:
        if RFC_PERSONA_MORAL_PATTERN.match(rfc):
            return None
        return f"RFC de persona moral con formato inválido: '{rfc}'."

    if len(rfc) == 13:
        if RFC_PERSONA_FISICA_PATTERN.match(rfc):
            return None
        return f"RFC de persona física con formato inválido: '{rfc}'."

    return f"RFC con longitud inesperada: '{rfc}'."


def validate_iva_rate(rate: float) -> Tuple[bool, str]:
    """Validate an IVA rate. Accepted rates: 0%, 8%, 16%."""
    if rate not in VALID_IVA_RATES:
        return False, (
            f"Tasa de IVA inválida: {rate}. "
            f"Tasas aceptadas: 0%, 8%, 16%."
        )
    return True, ""


def validate_amount(
    amount: float,
    field_name: str = "monto",
    allow_zero: bool = True,
    max_value: float = 1_000_000_000.0,
) -> Optional[str]:
    """Validate a monetary amount. Returns None if valid, error message if invalid."""
    if not allow_zero and amount == 0:
        return f"{field_name} no puede ser cero."
    if amount < 0:
        return f"{field_name} no puede ser negativo ({amount})."
    if amount > max_value:
        return f"{field_name} excede el máximo permitido ({max_value})."
    return None


def validate_date_format(date_str: str, field_name: str = "fecha") -> Optional[str]:
    """Validate a date string in YYYY-MM-DD format. Returns None if valid."""
    if not date_str or not date_str.strip():
        return f"{field_name} no puede estar vacío."
    try:
        parsed = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return f"{field_name} tiene formato inválido: '{date_str}'. Se esperaba YYYY-MM-DD."
    if parsed > date.today():
        return f"{field_name} no puede ser una fecha futura: '{date_str}'."
    return None


def validate_clabe(clabe: str) -> Optional[str]:
    """Validate CLABE interbancaria (18 digits). Returns None if valid."""
    if not clabe or not clabe.strip():
        return "CLABE no puede estar vacío."
    clabe = clabe.strip()
    if len(clabe) != 18:
        return f"CLABE debe tener 18 dígitos, tiene {len(clabe)}."
    if not clabe.isdigit():
        return "CLABE solo debe contener dígitos."
    return None


def validate_periodo(periodo: str) -> Optional[str]:
    """Validate period format YYYY-MM. Returns None if valid."""
    if not periodo or not periodo.strip():
        return "Periodo no puede estar vacío."
    try:
        parts = periodo.strip().split("-")
        year = int(parts[0])
        month = int(parts[1])
        if year < 2014 or year > 2099:
            return f"Año inválido en periodo: {year}."
        if month < 1 or month > 12:
            return f"Mes inválido en periodo: {month}."
    except (ValueError, IndexError):
        return f"Periodo con formato inválido: '{periodo}'. Se esperaba YYYY-MM."
    return None


# ---------------------------------------------------------------------------
# Cross-reference validators
# ---------------------------------------------------------------------------

def validate_diot_consistency(
    facturas: list,
    diot_entries: list,
) -> List[str]:
    """Validate that DIOT entries are consistent with CFDI invoices.

    Returns a list of error messages (empty if consistent).
    """
    errors: List[str] = []

    if not facturas:
        errors.append("No hay facturas para validar contra DIOT.")
        return errors

    if not diot_entries:
        errors.append("No hay entradas DIOT para validar contra facturas.")
        return errors

    # Build DIOT lookup by UUID
    diot_uuids = set()
    for entry in diot_entries:
        folios = getattr(entry, "folios_fiscales", [])
        diot_uuids.update(folios)

    # Check each factura has a DIOT match
    for f in facturas:
        uuid_val = getattr(f, "uuid", None)
        if uuid_val and uuid_val not in diot_uuids:
            errors.append(
                f"Factura UUID '{uuid_val}' (RFC: {f.rfc_emisor}) "
                f"no tiene entrada en la DIOT."
            )

    # Check DIOT IVA totals vs sum of factura IVA
    diot_iva_total = sum(getattr(e, "iva_trasladado", 0) for e in diot_entries)
    factura_iva_total = sum(getattr(f, "iva", 0) for f in facturas)
    if abs(diot_iva_total - factura_iva_total) > 0.01:
        errors.append(
            f"DIOT IVA total ({diot_iva_total:.2f}) ≠ "
            f"suma facturas IVA ({factura_iva_total:.2f}). "
            f"Diferencia: {abs(diot_iva_total - factura_iva_total):.2f}"
        )

    return errors


def validate_declaration_consistency(
    diot_entries: list,
    declaraciones: list,
) -> List[str]:
    """Validate that declarations are consistent with DIOT data.

    Returns a list of error messages (empty if consistent).
    """
    errors: List[str] = []

    if not diot_entries:
        errors.append("No hay entradas DIOT para validar contra declaraciones.")
        return errors

    if not declaraciones:
        errors.append("No hay declaraciones mensuales para validar.")
        return errors

    diot_iva_acreditable = sum(
        getattr(e, "iva_acreditable", 0) for e in diot_entries
    )

    for decl in declaraciones:
        decl_iva_pagado = getattr(decl, "iva_pagado", 0)
        # The IVA pagado in the declaration should roughly match DIOT acreditable
        # (allowing for adjustments)
        if decl_iva_pagado > 0 and diot_iva_acreditable > 0:
            diff = abs(diot_iva_acreditable - decl_iva_pagado)
            pct = diff / decl_iva_pagado if decl_iva_pagado else 0
            if pct > 0.05:  # >5% difference
                errors.append(
                    f"Declaración {decl.mes}/{decl.año}: IVA pagado ({decl_iva_pagado:.2f}) "
                    f"difiere >5% del IVA acreditable DIOT ({diot_iva_acreditable:.2f}). "
                    f"Diferencia: {diff:.2f} ({pct:.1%})"
                )

    return errors
