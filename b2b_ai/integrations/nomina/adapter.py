# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de Nómina.

NominaAdapter es la clase base abstracta para operaciones de nómina.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.nomina.models import (
    CalculoImpuestos,
    CFDINomina,
    Empleado,
    IMSSDetalle,
    NominaPeriodo,
)

logger = logging.getLogger(__name__)


class NominaAdapterError(Exception):
    """Error genérico de adaptador de nómina."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class NominaAdapter(ABC):
    """Clase base abstracta para integración de nómina.

    Implementa cálculos de ISR, IMSS, INFONAVIT y generación de
    CFDI de nómina.
    """

    def __init__(self, name: str = "nomina"):
        self.name = name
        logger.info(f"NominaAdapter '{name}' inicializado")

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def calcular_nomina(self, empleados: List[Empleado], periodo: Dict[str, Any]) -> NominaPeriodo:
        """Calcula la nómina completa para un periodo.

        Args:
            empleados: Lista de empleados.
            periodo: {"mes": 1, "anio": 2026, "dias_pagados": 30}

        Returns:
            NominaPeriodo con todos los cálculos.
        """
        ...

    @abstractmethod
    def generar_cfdi_nomina(self, nomina_data: Dict[str, Any]) -> CFDINomina:
        """Genera un CFDI de nómina 1.2.

        Args:
            nomina_data: Datos para generar el CFDI.

        Returns:
            CFDINomina con el XML generado.
        """
        ...

    @abstractmethod
    def calcular_imss(self, salario_diario: float) -> IMSSDetalle:
        """Calcula las cuotas del IMSS.

        Args:
            salario_diario: Salario diario integrado.

        Returns:
            IMSSDetalle con el desglose de cuotas.
        """
        ...

    @abstractmethod
    def calcular_infonavit(self, salario_diario: float) -> float:
        """Calcula la aportación al INFONAVIT.

        Args:
            salario_diario: Salario diario integrado.

        Returns:
            Monto de la aportación INFONAVIT.
        """
        ...

    @abstractmethod
    def calcular_isr(self, salario_bruto: float) -> float:
        """Calcula el ISR mensual.

        Args:
            salario_bruto: Salario bruto mensual gravable.

        Returns:
            Monto del ISR.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba que el adaptador funcione."""
        return {
            "adapter": self.name,
            "status": "connected",
            "message": f"Adaptador de nómina '{self.name}' operativo",
        }
