# -*- coding: utf-8 -*-
"""lisr_adapter.py — Cumplimiento de la Ley del Impuesto Sobre la Renta (LISR)."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class LISRCompliance:
    """Validador de cumplimiento LISR — Tablas de ISR, retenciones, pagos provisionales."""

    # Tabla ISR 2026 (simplificada — tramos anuales)
    TABLA_ISR = [
        (0.01, 8059.83, 0.0, 0.0),
        (8059.84, 68282.43, 0.0, 1.92),
        (68282.44, 122081.47, 1177.19, 6.40),
        (122081.48, 136562.81, 4620.83, 10.88),
        (163131.69, 328484.33, 10045.83, 16.00),
        (328484.34, 985452.97, 36499.83, 21.36),
        (985452.98, 3149999.98, 177540.83, 30.00),
        (3149999.99, 6299999.95, 826769.17, 32.00),
        (6299999.96, 999999999.99, 1834769.17, 34.00),
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "lisr_compliance"

    def calcular_isr_anual(self, ingreso_anual: float, deducciones: float = 0.0) -> Dict[str, Any]:
        """Calcula ISR anual según tabla LISR Art. 96."""
        base_gravable = max(0, ingreso_anual - deducciones - 108608.25)  # Mínimo exento
        isr = 0.0
        for limite_inf, limite_sup, cuota_fija, tasa in self.TABLA_ISR:
            if base_gravable <= limite_sup:
                isr = cuota_fija + (base_gravable - limite_inf) * (tasa / 100)
                break
        isr = max(0, round(isr, 2))
        return {"ingreso_anual": ingreso_anual, "deducciones": deducciones,
                "base_gravable": round(base_gravable, 2), "isr": isr,
                "tasa_efectiva": round((isr / ingreso_anual * 100) if ingreso_anual > 0 else 0, 2),
                "reglas": "LISR Art. 96-97, tabla anual"}

    def validar_retencion_isr(self, monto: float, tipo: str = "honorarios") -> Dict[str, Any]:
        """Valida si aplica retención de ISR (Art. 76 LISR)."""
        retenciones = {"honorarios": 0.10, "arrendamiento": 0.10, "servicios_profesionales": 0.10,
                       "dividendos": 0.10, "intereses": 0.0}
        tasa = retenciones.get(tipo, 0.10)
        retencion = round(monto * tasa, 2)
        return {"monto": monto, "tipo": tipo, "tasa_retencion": tasa,
                "isr_retenido": retencion, "monto_neto": round(monto - retencion, 2),
                "reglas": f"LISR Art. 113 — Retención {tipo}"}

    def validar_pagos_provisionales(self, isr_acumulado: float, pagos_previos: float) -> Dict[str, Any]:
        """Calcula pago provisional mensual."""
        pago = max(0, isr_acumulado - pagos_previos)
        return {"isr_acumulado": isr_acumulado, "pagos_previos": pagos_previos,
                "pago_provisional": round(pago, 2), "reglas": "LISR Art. 14"}

    def test_connection(self) -> Dict[str, Any]:
        return {"adapter": self.name, "status": "connected", "message": "LISR Compliance module active"}
