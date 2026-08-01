# -*- coding: utf-8 -*-
"""lft_adapter.py — Cumplimiento de la Ley Federal del Trabajo (LFT)."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class LFTCompliance:
    """Validador de cumplimiento LFT — Salario mínimo, prima vacacional, aguinaldo, PTU."""

    SALARIO_MINIMO_2026 = 278.40  # Salario mínimo general 2026 (referencia)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "lft_compliance"

    def validar_salario_minimo(self, salario_diario: float) -> Dict[str, Any]:
        """Valida que el salario sea al menos el mínimo."""
        cumple = salario_diario >= self.SALARIO_MINIMO_2026
        return {"salario_diario": salario_diario, "salario_minimo": self.SALARIO_MINIMO_2026,
                "cumple": cumple, "diferencia": round(salario_diario - self.SALARIO_MINIMO_2026, 2),
                "reglas": "LFT Art. 86-87"}

    def calcular_aguinaldo(self, salario_diario: float, dias_trabajados: int = 365) -> Dict[str, Any]:
        """Calcula aguinaldo (mínimo 15 días según LFT Art. 87)."""
        dias_aguinaldo = max(15, int(dias_trabajados / 365 * 15))
        monto = round(salario_diario * dias_aguinaldo, 2)
        return {"salario_diario": salario_diario, "dias_aguinaldo": dias_aguinaldo,
                "monto": monto, "reglas": "LFT Art. 87"}

    def calcular_prima_vacacional(self, salario_diario: float, dias_vacaciones: int) -> Dict[str, Any]:
        """Calcula prima vacacional (mínimo 25% según LFT Art. 80)."""
        prima = round(salario_diario * dias_vacaciones * 0.25, 2)
        return {"salario_diario": salario_diario, "dias_vacaciones": dias_vacaciones,
                "prima_vacacional": prima, "tasa": 0.25, "reglas": "LFT Art. 80"}

    def calcular_ptu(self, utilidad_neta: float, porcentaje: float = 0.10) -> Dict[str, Any]:
        """Calcula Participación de los Trabajadores en las Utilidades (PTU)."""
        monto_total = round(utilidad_neta * porcentaje, 2)
        return {"utilidad_neta": utilidad_neta, "porcentaje": porcentaje,
                "ptu_total": monto_total, "reglas": "LFT Art. 117-131"}

    def test_connection(self) -> Dict[str, Any]:
        return {"adapter": self.name, "status": "connected", "message": "LFT Compliance module active"}
