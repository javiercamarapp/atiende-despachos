# -*- coding: utf-8 -*-
"""Declaraciones Periódicas — IVA, ISR Provisional, ISR Anual.

Módulo para la generación y seguimiento de declaraciones fiscales
periódicas en México (CFF - Código Fiscal de la Federación).

Reglas fiscales:
  - IVA: Mensual, vence el 17 del mes siguiente
  - ISR Provisional: Mensual, vence el 17 del mes siguiente
  - ISR Anual: Anual, vence el 30 de abril del año siguiente
"""
from b2b_ai.features.declaraciones.service import DeclaracionesService
from b2b_ai.features.declaraciones.models import (
    Declaracion,
    DeclaracionStatus,
    DeclaracionType,
    Deadline,
    DeadlineStatus,
    IvaData,
    IsrData,
)

__all__ = [
    "DeclaracionesService",
    "Declaracion",
    "DeclaracionStatus",
    "DeclaracionType",
    "Deadline",
    "DeadlineStatus",
    "IvaData",
    "IsrData",
]
