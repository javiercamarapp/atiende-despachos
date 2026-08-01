# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for management reports.

Validates:
  - Period format (YYYY-MM)
  - Amount ranges (non-negative, reasonable bounds)
  - KPI thresholds and values
"""
from __future__ import annotations

import re
from typing import List, Tuple, Optional


def validate_period(period: str) -> Tuple[bool, List[str]]:
    """Validate a period string in YYYY-MM format.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if not period or not str(period).strip():
        errors.append("El período es obligatorio.")
        return False, errors

    period = str(period).strip()

    if not re.match(r"^\d{4}-\d{2}$", period):
        errors.append(
            f"Formato de período inválido '{period}'. Se esperaba YYYY-MM."
        )
        return False, errors

    # Validate year range
    year = int(period[:4])
    month = int(period[5:7])

    if year < 2020 or year > 2030:
        errors.append(f"Año fuera de rango: {year}. Se esperaba 2020-2030.")

    if month < 1 or month > 12:
        errors.append(f"Mes inválido: {month}. Se esperaba 1-12.")

    return len(errors) == 0, errors


def validate_amount_range(
    amount: float,
    min_val: float = 0.0,
    max_val: float = 1_000_000_000.0,
    field_name: str = "monto",
) -> Tuple[bool, List[str]]:
    """Validate that an amount is within a reasonable range.

    Parameters
    ----------
    amount : float
        The amount to validate.
    min_val : float
        Minimum allowed value (default 0).
    max_val : float
        Maximum allowed value (default 1 billion MXN).
    field_name : str
        Name of the field for error messages.

    Returns
    -------
    (is_valid, list_of_errors).
    """
    errors: List[str] = []

    if not isinstance(amount, (int, float)):
        errors.append(f"{field_name}: debe ser un número.")
        return False, errors

    if amount < min_val:
        errors.append(f"{field_name}: no puede ser menor a {min_val} (valor actual: {amount}).")

    if amount > max_val:
        errors.append(
            f"{field_name}: excede el máximo permitido de {max_val:,.2f} "
            f"(valor actual: {amount:,.2f})."
        )

    return len(errors) == 0, errors


def validate_kpi_threshold(
    value: float,
    target: Optional[float] = None,
    threshold_pct: float = 0.20,
    kpi_name: str = "KPI",
) -> Tuple[bool, str]:
    """Validate a KPI value against its target with a tolerance threshold.

    Parameters
    ----------
    value : float
        Current KPI value.
    target : Optional[float]
        Target value. If None, validation passes.
    threshold_pct : float
        Allowed deviation from target (default 20%).
    kpi_name : str
        Name for error messages.

    Returns
    -------
    (is_valid, message).
    """
    if target is None:
        return True, f"{kpi_name}: sin objetivo definido."

    if target == 0:
        if value == 0:
            return True, f"{kpi_name}: en el objetivo."
        return False, f"{kpi_name}: objetivo es 0 pero valor actual es {value}."

    deviation_pct = abs(value - target) / abs(target)

    if deviation_pct <= threshold_pct:
        return True, (
            f"{kpi_name}: dentro del umbral "
            f"({value:.2f} vs target {target:.2f}, "
            f"desviación {deviation_pct*100:.1f}%)"
        )

    direction = "por encima" if value > target else "por debajo"
    return False, (
        f"{kpi_name}: {direction} del umbral "
        f"({value:.2f} vs target {target:.2f}, "
        f"desviación {deviation_pct*100:.1f}% > {threshold_pct*100:.0f}%)"
    )


def validate_monthly_report_data(data: dict) -> Tuple[bool, List[str]]:
    """Validate raw monthly report data dict.

    Returns (is_valid, combined_list_of_errors).
    """
    all_errors: List[str] = []

    # Validate period
    period = data.get("period", "")
    is_valid_period, period_errors = validate_period(period)
    if not is_valid_period:
        all_errors.extend([f"[Período] {e}" for e in period_errors])

    # Validate amounts
    for field in ["revenue", "expenses", "taxes_paid"]:
        value = data.get(field, 0.0)
        is_valid, amount_errors = validate_amount_range(value, field_name=field)
        if not is_valid:
            all_errors.extend([f"[{field}] {e}" for e in amount_errors])

    return len(all_errors) == 0, all_errors
