# -*- coding: utf-8 -*-
"""
validators.py — Validation functions for Income/Expense Reconciliation data.

Validates:
  - Fiscal period format (YYYY-MM)
  - Deposit data integrity (amounts, dates, references)
  - Auxiliary accounting entries (account format, amounts)
  - Classification consistency
  - IVA balance calculations
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Tuple

from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    AuxiliarContable,
    BalanceIVA,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    DepositoBancario,
)


def validate_periodo(period: str) -> Tuple[bool, str]:
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

        datetime.strptime(period, "%Y-%m")
    except ValueError as e:
        return False, f"Período inválido: {e}"

    return True, ""


def validate_deposito(deposito: DepositoBancario) -> Tuple[bool, str]:
    """Validate a bank deposit record.

    Parameters
    ----------
    deposito : DepositoBancario
        Deposit to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not deposito.id or not deposito.id.strip():
        return False, "El ID del depósito no puede estar vacío."

    if deposito.monto <= 0:
        return False, f"El monto del depósito debe ser mayor a cero: {deposito.monto}."

    if not deposito.fecha or not deposito.fecha.strip():
        return False, "La fecha del depósito no puede estar vacía."

    # Validate date format YYYY-MM-DD
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", deposito.fecha):
        return False, f"Formato de fecha inválido: '{deposito.fecha}'. Se esperaba YYYY-MM-DD."

    try:
        datetime.strptime(deposito.fecha, "%Y-%m-%d")
    except ValueError:
        return False, f"Fecha inválida: '{deposito.fecha}'."

    return True, ""


def validate_auxiliar_contable(auxiliar: AuxiliarContable) -> Tuple[bool, str]:
    """Validate an auxiliary accounting entry.

    Parameters
    ----------
    auxiliar : AuxiliarContable
        Auxiliary to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not auxiliar.cuenta_id or not auxiliar.cuenta_id.strip():
        return False, "El ID de la cuenta auxiliar no puede estar vacío."

    if not auxiliar.cuenta_mayor or not auxiliar.cuenta_mayor.strip():
        return False, "La cuenta mayor no puede estar vacía."

    # Validate account format (at least 4 digits)
    cuenta = auxiliar.cuenta_mayor.strip()
    if not re.match(r"^\d{4,}$", cuenta):
        return False, f"Formato de cuenta mayor inválido: '{cuenta}'. Se esperaba al menos 4 dígitos."

    # Validate saldo_inicial is not negative
    if auxiliar.saldo_inicial < 0:
        return False, f"El saldo inicial no puede ser negativo: {auxiliar.saldo_inicial}."

    # Validate movements
    for i, mov in enumerate(auxiliar.movimientos):
        if mov.debe < 0:
            return False, f"Movimiento {i}: el debe no puede ser negativo ({mov.debe})."
        if mov.haber < 0:
            return False, f"Movimiento {i}: el haber no puede ser negativo ({mov.haber})."

    return True, ""


def validate_clasificacion(clasificacion: ClasificacionDepositoResult) -> Tuple[bool, str]:
    """Validate a deposit classification result.

    Parameters
    ----------
    clasificacion : ClasificacionDepositoResult
        Classification to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if not clasificacion.deposito_id or not clasificacion.deposito_id.strip():
        return False, "El ID del depósito en la clasificación no puede estar vacío."

    if clasificacion.confianza < 0.0 or clasificacion.confianza > 1.0:
        return False, f"La confianza debe estar entre 0 y 1: {clasificacion.confianza}."

    valid_classifications = [c.value for c in ClasificacionDeposito]
    if clasificacion.clasificacion.value not in valid_classifications:
        return False, f"Clasificación inválida: '{clasificacion.clasificacion}'."

    return True, ""


def validate_balance_iva(balance: BalanceIVA) -> Tuple[bool, str]:
    """Validate an IVA balance calculation.

    Parameters
    ----------
    balance : BalanceIVA
        IVA balance to validate.

    Returns
    -------
    (is_valid, error_message)
    """
    if balance.iva_cobrado < 0:
        return False, f"El IVA cobrado no puede ser negativo: {balance.iva_cobrado}."

    if balance.iva_pagado < 0:
        return False, f"El IVA pagado no puede ser negativo: {balance.iva_pagado}."

    if balance.declarado < 0:
        return False, f"El monto declarado no puede ser negativo: {balance.declarado}."

    # Validate consistency: saldo_favor should be iva_pagado - iva_cobrado if positive
    calculated_favor = max(0.0, balance.iva_pagado - balance.iva_cobrado)
    calculated_contra = max(0.0, balance.iva_cobrado - balance.iva_pagado)

    if abs(balance.saldo_favor - calculated_favor) > 0.01:
        return (
            False,
            f"Saldo a favor inconsistente: declarado {balance.saldo_favor}, "
            f"calculado {calculated_favor:.2f}.",
        )

    if abs(balance.saldo_contra - calculated_contra) > 0.01:
        return (
            False,
            f"Saldo en contra inconsistente: declarado {balance.saldo_contra}, "
            f"calculado {calculated_contra:.2f}.",
        )

    return True, ""
