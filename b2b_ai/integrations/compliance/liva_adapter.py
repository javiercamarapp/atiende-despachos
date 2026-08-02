# -*- coding: utf-8 -*-
"""liva_adapter.py — Cumplimiento de la Ley del Impuesto al Valor Agregado (LIVA)."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class LIVACompliance:
    """Validador de cumplimiento LIVA — Tasa, acreditable, DIOT."""

    TASA_GENERAL = 0.16
    TASA_FRONTERA = 0.08

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "liva_compliance"

    def calcular_iva(self, subtotal: float, tasa: float = 0.16, zona: str = "general") -> Dict[str, Any]:
        """Calcula IVA sobre un monto."""
        tasa_aplicada = self.TASA_FRONTERA if zona == "frontera" else tasa
        iva = round(subtotal * tasa_aplicada, 2)
        return {"subtotal": subtotal, "tasa": tasa_aplicada, "zona": zona,
                "iva": iva, "total": round(subtotal + iva, 2),
                "reglas": "LIVA Art. 1-A, Art. 28"}

    def validar_acreditamiento_iva(self, iva_trasladado: float, iva_acreditable: float) -> Dict[str, Any]:
        """Valida acredamiento de IVA."""
        saldo = round(iva_trasladado - iva_acreditable, 2)
        return {"iva_trasladado": iva_trasladado, "iva_acreditable": iva_acreditable,
                "saldo_a_favor" if saldo >= 0 else "saldo_contra": abs(saldo),
                "reglas": "LIVA Art. 4-5, 25"}

    def generar_diot(self, proveedores: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Genera datos para DIOT (Declaración Informativa Operaciones con Terceros)."""
        total_acreditable = sum(p.get("iva_acreditable", 0) for p in proveedores)
        total_trasladado = sum(p.get("iva_trasladado", 0) for p in proveedores)
        return {"num_proveedores": len(proveedores), "total_acreditable": round(total_acreditable, 2),
                "total_trasladado": round(total_trasladado, 2), "formato": "DIOT 23/54 columnas",
                "reglas": "LIVA Art. 32, Regla 2.7.3.1"}

    def test_connection(self) -> Dict[str, Any]:
        return {"adapter": self.name, "status": "connected", "message": "LIVA Compliance module active"}
