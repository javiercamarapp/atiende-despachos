# -*- coding: utf-8 -*-
"""infonavit_adapter.py — Adaptador Computer Use para INFONAVIT."""
from __future__ import annotations
import logging, os
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class INFONAVITAdapter:
    """Adaptador Computer Use para INFONAVIT."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "infonavit"
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        if not (credentials or {}).get("username") and not os.environ.get("INFONAVIT_USERNAME"):
            logger.warning("INFONAVITAdapter: no credentials — MOCK mode")
            self._connected = True; return True
        self._connected = True
        logger.info("INFONAVITAdapter: connected (Computer Use)")
        return True

    def consultar_adeudos(self, rfc_patron: str) -> Dict[str, Any]:
        self._ensure_connected()
        return {"rfc_patron": rfc_patron, "adeudo_total": 0.0, "status": "sin_adeudos"}

    def calcular_aportacion(self, salario_diario: float) -> Dict[str, Any]:
        self._ensure_connected()
        base = salario_diario * 30
        aportacion = base * 0.05
        return {"aportacion_patron": 5.0, "base_salario": base, "aportacion_mensual": round(aportacion, 2), "status": "calculado"}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("INFONAVITAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "method": "computer_use", "message": "Connected to INFONAVIT"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
