# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for vencimientos data.

Validates:
  - Date format (YYYY-MM-DD)
  - Priority levels
  - Date range consistency
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Tuple

from b2b_ai.features.vencimientos.models import PrioridadVencimiento


def validate_date(
    date_str: str,
) -> Tuple[bool, str]:
    """Validate a date string in YYYY-MM-DD format.

    Parameters
    ----------
    date_str : str
        Date string to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not date_str or not date_str.strip():
        return False, "La fecha no puede estar vacía."

    date_str = date_str.strip()

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False, f"Formato de fecha inválido: '{date_str}'. Se esperaba YYYY-MM-DD."

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False, f"Fecha no válida: '{date_str}'."

    return True, ""


def validate_priority(
    priority: str,
) -> Tuple[bool, str]:
    """Validate a priority level string.

    Parameters
    ----------
    priority : str
        Priority to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    valid_priorities = {p.value for p in PrioridadVencimiento}
    if priority not in valid_priorities:
        return False, (
            f"Prioridad inválida: '{priority}'. "
            f"Valores permitidos: {', '.join(sorted(valid_priorities))}."
        )
    return True, ""


def validate_date_range_venc(
    start_date: str,
    end_date: str,
) -> Tuple[bool, str]:
    """Validate a date range (start <= end, valid format).

    Parameters
    ----------
    start_date : str
        Start date YYYY-MM-DD.
    end_date : str
        End date YYYY-MM-DD.

    Returns
    -------
    (is_valid, error_message)
    """
    is_valid_start, err_start = validate_date(start_date)
    if not is_valid_start:
        return False, f"Fecha de inicio: {err_start}"

    is_valid_end, err_end = validate_date(end_date)
    if not is_valid_end:
        return False, f"Fecha de fin: {err_end}"

    try:
        d_start = datetime.strptime(start_date.strip(), "%Y-%m-%d")
        d_end = datetime.strptime(end_date.strip(), "%Y-%m-%d")
        if d_start > d_end:
            return False, (
                f"Fecha de inicio ({start_date}) es posterior a fecha de fin ({end_date})."
            )
    except ValueError as e:
        return False, f"Error parseando fechas: {e}"

    return True, ""
