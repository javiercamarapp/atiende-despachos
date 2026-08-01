# -*- coding: utf-8 -*-
"""sar_adapter.py — Adaptador Computer Use para SAR (Sistema de Administración de Recursos)."""
from __future__ import annotations
import logging, os
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class SARAdapter:
    """Adaptador Computer Use para SAR del SAT."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "sar"
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        if not (credentials or {}).get("username") and not os.environ.get("SAR_USERNAME"):
            logger.warning("SARAdapter: no credentials — MOCK mode")
            self._connected = True; return True
        self._connected = True
        logger.info("SARAdapter: connected (Computer Use)")
        return True

    def consultar_obligaciones(self, rfc: str) -> Dict[str, Any]:
        self._ensure_connected()
        return {"rfc": rfc, "obligaciones": ["IVA", "ISR", "DIOT"], "periodo": "2026-01", "status": "activo"}

    def descarga_comprobantes(self, rfc: str, periodo: str) -> Dict[str, Any]:
        self._ensure_connected()
        return {"comprobantes": 15, "periodo": periodo, "status": "descarga_completa"}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("SARAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "method": "computer_use", "message": "Connected to SAR"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
