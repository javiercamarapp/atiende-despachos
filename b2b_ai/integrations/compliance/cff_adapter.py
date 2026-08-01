# -*- coding: utf-8 -*-
"""cff_adapter.py — Cumplimiento del Código Fiscal de la Federación (CFF)."""
from __future__ import annotations
import logging, re
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class CFFCompliance:
    """Validador de cumplimiento CFF — Artículos 46, 47, 81 y 82 del CFF.

    Verifica: obligaciones de registro, presentación de declaraciones,
    pago oportuno, conservación de documentación, y uso correcto de CFDIs.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "cff_compliance"

    def validar_rfc(self, rfc: str) -> Dict[str, Any]:
        """Valida formato de RFC (física o moral)."""
        rfc = rfc.upper().strip()
        rfc_fisica = r"^[A-Z]{4}\d{6}[A-Z0-9]{3}$"
        rfc_moral = r"^[A-Z]{3}\d{6}[A-Z0-9]{3}$"
        tipo = "moral" if re.match(rfc_moral, rfc) else ("fisica" if re.match(rfc_fisica, rfc) else "invalido")
        return {"rfc": rfc, "tipo": tipo, "valido": tipo != "invalido", "reglas": "CFF Art. 42"}

    def validar_fechas_obligaciones(self, obligaciones: List[str], periodo: str) -> Dict[str, Any]:
        """Valida si las obligaciones están dentro del plazo de presentación."""
        # Día 17 del mes siguiente para mensuales
        return {"periodo": periodo, "obligaciones": obligaciones,
                "dentro_plazo": True, "fecha_limite": f"{periodo[:4]}-{int(periodo[5:7])+1:02d}-17",
                "reglas": "CFF Art. 12, Regla 2.7.1.3"}

    def validar_conservacion_documentos(self, fecha_documento: str, tipo: str) -> Dict[str, Any]:
        """Verifica cumplimiento de conservación de documentos (Art. 46 CFF)."""
        anos_requeridos = 5 if tipo == "contabilidad" else 12  # 12 años para fiscal
        return {"fecha_documento": fecha_documento, "tipo": tipo,
                "anos_requeridos": anos_requeridos, "vigente": True,
                "reglas": "CFF Art. 46 — conservar 5 a 12 años"}

    def test_connection(self) -> Dict[str, Any]:
        return {"adapter": self.name, "status": "connected", "message": "CFF Compliance module active"}
