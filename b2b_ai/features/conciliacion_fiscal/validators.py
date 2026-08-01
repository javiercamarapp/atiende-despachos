# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for fiscal conciliation data.

Validates:
  - Fiscal period format (YYYY-MM)
  - Amount consistency and non-negative values
  - Cross-reference between ERP and SAT data
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple


def validate_fiscal_period(
    period: str,
) -> Tuple[bool, str]:
    """Validate a fiscal period string (YYYY-MM).

    Parameters
    ----------
    period : str
        Period string to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not period or not period.strip():
        return False, "El período no puede estar vacío."

    period = period.strip()

    if not re.match(r"^\d{4}-\d{2}$", period):
        return False, f"Formato de período inválido: '{period}'. Se esperaba YYYY-MM."

    try:
        year, month = period.split("-")
        year_int = int(year)
        month_int = int(month)

        if month_int < 1 or month_int > 12:
            return False, f"Mes inválido: {month_int}. Debe estar entre 1 y 12."

        if year_int < 2014:
            return False, f"Año inválido: {year_int}. Debe ser >= 2014."

        # Validate it's a real date
        datetime.strptime(period, "%Y-%m")
    except ValueError as e:
        return False, f"Período inválido: {e}"

    return True, ""


def validate_fiscal_amounts(
    erp_total: float,
    sat_total: float,
    tolerance: float = 0.01,
) -> Tuple[bool, str]:
    """Validate that ERP and SAT totals are reasonable.

    Parameters
    ----------
    erp_total : float
        Total declared in ERP.
    sat_total : float
        Total declared in SAT.
    tolerance : float
        Acceptable fractional tolerance (default 1%).

    Returns
    -------
    (is_valid, error_message)
    """
    if erp_total < 0:
        return False, f"Total ERP no puede ser negativo: {erp_total}."
    if sat_total < 0:
        return False, f"Total SAT no puede ser negativo: {sat_total}."

    return True, ""


def cross_reference_data(
    erp_records: List[dict],
    sat_records: List[dict],
) -> Tuple[bool, List[str]]:
    """Cross-reference ERP records against SAT records.

    Parameters
    ----------
    erp_records : List[dict]
        ERP records with keys: uuid, rfc, monto, fecha, concepto.
    sat_records : List[dict]
        SAT records with keys: uuid, rfc, monto, fecha, concepto.

    Returns
    -------
    (is_valid, list_of_issues)
    """
    issues: List[str] = []

    if not erp_records and not sat_records:
        issues.append("Ambas listas están vacías. No hay datos para comparar.")
        return False, issues

    if not erp_records:
        issues.append("La lista de registros ERP está vacía.")
        return False, issues

    if not sat_records:
        issues.append("La lista de registros SAT está vacía.")
        return False, issues

    # Build lookup maps by UUID
    erp_by_uuid: Dict[str, dict] = {}
    for r in erp_records:
        uuid = r.get("uuid", "")
        if uuid:
            erp_by_uuid[uuid] = r

    sat_by_uuid: Dict[str, dict] = {}
    for r in sat_records:
        uuid = r.get("uuid", "")
        if uuid:
            sat_by_uuid[uuid] = r

    # Check for ERP records not in SAT
    erp_only = set(erp_by_uuid.keys()) - set(sat_by_uuid.keys())
    for uuid in erp_only:
        rec = erp_by_uuid[uuid]
        issues.append(
            f"CFDI '{uuid}' (RFC={rec.get('rfc', '?')}, monto={rec.get('monto', '?')}) "
            "está en ERP pero no en SAT."
        )

    # Check for SAT records not in ERP
    sat_only = set(sat_by_uuid.keys()) - set(erp_by_uuid.keys())
    for uuid in sat_only:
        rec = sat_by_uuid[uuid]
        issues.append(
            f"CFDI '{uuid}' (RFC={rec.get('rfc', '?')}, monto={rec.get('monto', '?')}) "
            "está en SAT pero no en ERP."
        )

    # Check for matching records with discrepancies
    common_uuids = set(erp_by_uuid.keys()) & set(sat_by_uuid.keys())
    for uuid in common_uuids:
        erp_rec = erp_by_uuid[uuid]
        sat_rec = sat_by_uuid[uuid]

        erp_monto = float(erp_rec.get("monto", 0))
        sat_monto = float(sat_rec.get("monto", 0))

        if abs(erp_monto - sat_monto) > 0.01:
            issues.append(
                f"CFDI '{uuid}': monto ERP ({erp_monto}) != monto SAT ({sat_monto})."
            )

        erp_rfc = erp_rec.get("rfc", "").strip().upper()
        sat_rfc = sat_rec.get("rfc", "").strip().upper()
        if erp_rfc and sat_rfc and erp_rfc != sat_rfc:
            issues.append(
                f"CFDI '{uuid}': RFC ERP ({erp_rfc}) != RFC SAT ({sat_rfc})."
            )

    return len(issues) == 0, issues
