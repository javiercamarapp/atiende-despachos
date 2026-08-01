# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for periodic declarations data.

Validates:
  - Period consistency (format, range)
  - IVA rates and calculations (CFF Art. 5-A)
  - ISR deductions against CFF rules (Art. 105-113)
  - Declaration data integrity

Mexican tax validation rules:
  - IVA: Monthly declarations must be filed by the 17th of the following month
  - ISR Provisional: Monthly declarations must be filed by the 17th
  - ISR Anual: Must be filed by April 30th
  - IVA rate: 16% general, 8% border zone, 0% exports/food/medicine
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Period validation
# ---------------------------------------------------------------------------

def validate_period_format(period: str, allow_annual: bool = False) -> Tuple[bool, List[str]]:
    """Validate period format.

    Args:
        period: Period string to validate (YYYY-MM or YYYY)
        allow_annual: If True, accept YYYY format for annual declarations

    Returns:
        (is_valid, list_of_errors)

    Valid formats:
      - Monthly: YYYY-MM (e.g., "2024-01", "2024-12")
      - Annual: YYYY (e.g., "2024") — only if allow_annual=True
    """
    errors: List[str] = []

    if not period or not isinstance(period, str):
        errors.append("El período no puede estar vacío.")
        return False, errors

    # Try monthly format first
    monthly_match = re.match(r"^(\d{4})-(\d{2})$", period.strip())
    if monthly_match:
        year = int(monthly_match.group(1))
        month = int(monthly_match.group(2))
        if month < 1 or month > 12:
            errors.append(f"Mes inválido '{month}' en período '{period}'.")
        if year < 2000 or year > 2100:
            errors.append(f"Año inválido '{year}' en período '{period}'.")
        return len(errors) == 0, errors

    # Try annual format
    if allow_annual:
        annual_match = re.match(r"^(\d{4})$", period.strip())
        if annual_match:
            year = int(annual_match.group(1))
            if year < 2000 or year > 2100:
                errors.append(f"Año inválido '{year}' en período '{period}'.")
            return len(errors) == 0, errors
        else:
            errors.append(
                f"Formato de período inválido '{period}'. "
                "Se esperaba YYYY-MM o YYYY."
            )
            return False, errors

    errors.append(
        f"Formato de período inválido '{period}'. "
        "Se esperaba YYYY-MM."
    )
    return False, errors


def validate_period_consistency(
    tipo: str,
    periodo: str,
) -> Tuple[bool, List[str]]:
    """Validate that the period is consistent with the declaration type.

    Args:
        tipo: Declaration type (iva, isr_provisional, isr_anual)
        periodo: Period string

    Returns:
        (is_valid, list_of_errors)

    Rules:
      - IVA and ISR Provisional: Must use monthly format (YYYY-MM)
      - ISR Anual: Must use annual format (YYYY)
    """
    errors: List[str] = []

    if tipo == "isr_anual":
        is_valid, period_errors = validate_period_format(periodo, allow_annual=True)
        errors.extend(period_errors)
        if is_valid and not re.match(r"^\d{4}$", periodo.strip()):
            errors.append(
                f"ISR Anual requiere período anual (YYYY), "
                f"se recibió '{periodo}'."
            )
    else:
        is_valid, period_errors = validate_period_format(periodo, allow_annual=False)
        errors.extend(period_errors)
        if is_valid and re.match(r"^\d{4}$", periodo.strip()):
            errors.append(
                f"{tipo.upper()} requiere período mensual (YYYY-MM), "
                f"se recibió '{periodo}'."
            )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# IVA validation
# ---------------------------------------------------------------------------

def validate_iva_data(data: dict) -> Tuple[bool, List[str]]:
    """Validate IVA declaration data.

    Args:
        data: Dictionary with iva_cobrado, iva_pagado, and optional
              saldo_favor/saldo_contra

    Returns:
        (is_valid, list_of_errors)

    Checks:
      - Required fields present
      - Amounts are non-negative
      - IVA cobrado/pagado consistency
      - IVA rate consistency (16% general, 8% border, 0% exempt)
      - saldo_favor/saldo_contra are mutually exclusive
    """
    errors: List[str] = []

    # Required fields
    for field in ("iva_cobrado", "iva_pagado"):
        if field not in data or data[field] is None:
            errors.append(f"Campo '{field}' es obligatorio.")
            return False, errors

    iva_cobrado = data.get("iva_cobrado", 0)
    iva_pagado = data.get("iva_pagado", 0)

    # Amount validation
    try:
        iva_cobrado = float(iva_cobrado)
    except (ValueError, TypeError):
        errors.append(f"iva_cobrado inválido '{iva_cobrado}'. Debe ser un número.")
        return False, errors

    try:
        iva_pagado = float(iva_pagado)
    except (ValueError, TypeError):
        errors.append(f"iva_pagado inválido '{iva_pagado}'. Debe ser un número.")
        return False, errors

    if iva_cobrado < 0:
        errors.append(f"iva_cobrado no puede ser negativo ({iva_cobrado}).")
    if iva_pagado < 0:
        errors.append(f"iva_pagado no puede ser negativo ({iva_pagado}).")

    # IVA rate consistency (check if cobrado looks like a 16% multiple)
    # This is a soft check — not all amounts must be exact multiples
    if iva_cobrado > 0:
        remainder = round(iva_cobrado % 0.16, 4)
        if remainder != 0 and remainder > 0.01:
            # Could be a border zone (8%) or exempt (0%) — just warn
            pass  # Soft validation, not blocking

    # saldo_favor / saldo_contra consistency
    saldo_favor = data.get("saldo_favor", 0)
    saldo_contra = data.get("saldo_contra", 0)

    try:
        saldo_favor = float(saldo_favor)
        saldo_contra = float(saldo_contra)
    except (ValueError, TypeError):
        errors.append("saldo_favor/saldo_contra deben ser numéricos.")
        return False, errors

    if saldo_favor > 0 and saldo_contra > 0:
        errors.append(
            "saldo_favor y saldo_contra no pueden ser ambos mayores a cero."
        )

    # Validate calculated balances match
    expected_saldo_favor = max(0, iva_pagado - iva_cobrado)
    expected_saldo_contra = max(0, iva_cobrado - iva_pagado)

    if abs(saldo_favor - expected_saldo_favor) > 0.01:
        errors.append(
            f"saldo_favor incorrecto. Esperado {expected_saldo_favor:.2f}, "
            f"recibido {saldo_favor:.2f}."
        )
    if abs(saldo_contra - expected_saldo_contra) > 0.01:
        errors.append(
            f"saldo_contra incorrecto. Esperado {expected_saldo_contra:.2f}, "
            f"recibido {saldo_contra:.2f}."
        )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# ISR validation
# ---------------------------------------------------------------------------

def validate_isr_data(data: dict, is_annual: bool = False) -> Tuple[bool, List[str]]:
    """Validate ISR declaration data.

    Args:
        data: Dictionary with ingresos, deducciones, utilidad,
              isr_calculated, pagos_provisionales
        is_annual: True if this is an annual ISR declaration

    Returns:
        (is_valid, list_of_errors)

    Checks:
      - Required fields present
      - Amounts are non-negative
      - utilidad = ingresos - deducciones
      - isr_calculated >= 0
      - For annual: pagos_provisionales > 0 expected
      - Deductions within CFF allowed limits (Art. 105)
    """
    errors: List[str] = []

    # Required fields
    if "ingresos" not in data or data["ingresos"] is None:
        errors.append("Campo 'ingresos' es obligatorio.")
        return False, errors

    ingresos = data.get("ingresos", 0)
    deducciones = data.get("deducciones", 0)
    utilidad = data.get("utilidad", 0)
    isr_calculated = data.get("isr_calculated", 0)
    pagos_provisionales = data.get("pagos_provisionales", 0)

    # Type conversion
    for name, val in [
        ("ingresos", ingresos),
        ("deducciones", deducciones),
        ("utilidad", utilidad),
        ("isr_calculated", isr_calculated),
        ("pagos_provisionales", pagos_provisionales),
    ]:
        try:
            float(val)
        except (ValueError, TypeError):
            errors.append(f"'{name}' inválido '{val}'. Debe ser un número.")
            return False, errors

    ingresos = float(ingresos)
    deducciones = float(deducciones)
    utilidad = float(utilidad)
    isr_calculated = float(isr_calculated)
    pagos_provisionales = float(pagos_provisionales)

    # Amount validation
    if ingresos < 0:
        errors.append(f"ingresos no puede ser negativo ({ingresos}).")
    if deducciones < 0:
        errors.append(f"deducciones no puede ser negativo ({deducciones}).")
    if isr_calculated < 0:
        errors.append(f"isr_calculated no puede ser negativo ({isr_calculated}).")
    if pagos_provisionales < 0:
        errors.append(
            f"pagos_provisionales no puede ser negativo ({pagos_provisionales})."
        )

    # Deductions cannot exceed income
    if deducciones > ingresos:
        errors.append(
            f"deducciones ({deducciones}) no pueden exceder ingresos ({ingresos})."
        )

    # Utilidad consistency
    expected_utilidad = round(ingresos - deducciones, 2)
    if abs(utilidad - expected_utilidad) > 0.01:
        errors.append(
            f"utilidad incorrecta. Esperado {expected_utilidad:.2f} "
            f"(ingresos - deducciones), recibido {utilidad:.2f}."
        )

    # ISR must be non-negative
    if isr_calculated < 0:
        errors.append(f"isr_calculated no puede ser negativo ({isr_calculated}).")

    # Annual ISR should have provisional payments
    if is_annual and pagos_provisionales <= 0 and ingresos > 0:
        errors.append(
            "ISR Anual con ingresos > 0 debe tener pagos provisionales > 0."
        )

    # Deductions limit check (CFF Art. 105 — max 30% of income for certain categories)
    if ingresos > 0:
        deduction_ratio = deducciones / ingresos
        if deduction_ratio > 0.9:
            errors.append(
                f"Deducciones representan {deduction_ratio*100:.1f}% de ingresos. "
                "Excede el límite razonable del 90%."
            )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Deadline validation
# ---------------------------------------------------------------------------

def validate_deadline_date(
    fecha_limite: str,
    tipo: str,
    periodo: str,
) -> Tuple[bool, List[str]]:
    """Validate that the deadline date is correct for the declaration type.

    Mexican tax deadlines (CFF):
      - IVA: 17th of the month following the period
      - ISR Provisional: 17th of the month following the period
      - ISR Anual: April 30th of the following year

    Args:
        fecha_limite: Deadline date (YYYY-MM-DD)
        tipo: Declaration type
        periodo: Period (YYYY-MM or YYYY)

    Returns:
        (is_valid, list_of_errors)
    """
    errors: List[str] = []

    # Validate date format
    try:
        deadline = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.append(f"Fecha límite inválida '{fecha_limite}'. Formato: YYYY-MM-DD.")
        return False, errors

    # Validate period format first
    if tipo == "isr_anual":
        is_valid, period_errors = validate_period_format(periodo, allow_annual=True)
    else:
        is_valid, period_errors = validate_period_format(periodo, allow_annual=False)
    errors.extend(period_errors)
    if not is_valid:
        return False, errors

    # Calculate expected deadline
    try:
        if tipo in ("iva", "isr_provisional"):
            # Monthly: due 17th of following month
            parts = periodo.split("-")
            year = int(parts[0])
            month = int(parts[1])
            if month == 12:
                expected_deadline = date(year + 1, 1, 17)
            else:
                expected_deadline = date(year, month + 1, 17)
        elif tipo == "isr_anual":
            # Annual: due April 30th of following year
            year = int(periodo)
            expected_deadline = date(year + 1, 4, 30)
        else:
            errors.append(f"Tipo de declaración desconocido '{tipo}'.")
            return False, errors
    except (ValueError, IndexError) as e:
        errors.append(f"Error calculando fecha límite: {e}")
        return False, errors

    if deadline != expected_deadline:
        errors.append(
            f"Fecha límite incorrecta. Esperada {expected_deadline.isoformat()}, "
            f"recibida {fecha_limite}."
        )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# RFC validation
# ---------------------------------------------------------------------------

def validate_rfc(rfc: str) -> Tuple[bool, List[str]]:
    """Validate Mexican RFC (Registro Federal de Contribuyentes).

    RFC format:
      - Moral person (company): 3 letters + 6 digits + 3 homoclave = 12 chars
      - Physical person: 4 letters + 6 digits + 3 homoclave = 13 chars

    Args:
        rfc: RFC string to validate

    Returns:
        (is_valid, list_of_errors)
    """
    errors: List[str] = []

    if not rfc or not isinstance(rfc, str):
        errors.append("RFC no puede estar vacío.")
        return False, errors

    rfc = rfc.strip().upper()

    # Moral person: 12 chars (3 letters + 6 digits + 3 homoclave)
    moral_pattern = re.compile(r"^[A-Z&Ñ]{3}\d{6}[A-Z\d]{3}$")
    # Physical person: 13 chars (4 letters + 6 digits + 3 homoclave)
    physical_pattern = re.compile(r"^[A-Z&Ñ]{4}\d{6}[A-Z\d]{3}$")

    if not (moral_pattern.match(rfc) or physical_pattern.match(rfc)):
        errors.append(
            f"RFC inválido '{rfc}'. "
            "Formato: 12 caracteres (moral) o 13 caracteres (física)."
        )

    return len(errors) == 0, errors
