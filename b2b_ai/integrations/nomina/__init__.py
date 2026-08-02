# -*- coding: utf-8 -*-
"""Módulo de integración de Nómina — ISR, IMSS, INFONAVIT, CFDI Nómina."""

from b2b_ai.integrations.nomina.adapter import NominaAdapter, NominaAdapterError
from b2b_ai.integrations.nomina.service import NominaService
from b2b_ai.integrations.nomina.models import (
    CalculoImpuestos,
    CFDINomina,
    Empleado,
    IMSSDetalle,
    NominaPeriodo,
    PeriodicidadPago,
    TipoNomina,
)

__all__ = [
    "NominaAdapter",
    "NominaAdapterError",
    "NominaService",
    "CalculoImpuestos",
    "CFDINomina",
    "Empleado",
    "IMSSDetalle",
    "NominaPeriodo",
    "PeriodicidadPago",
    "TipoNomina",
]
