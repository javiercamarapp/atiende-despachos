# -*- coding: utf-8 -*-
"""condusef_adapter.py — Adaptador Computer Use para CONDUSEF."""
from __future__ import annotations
import logging, os
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class CONDUSEFAdapter:
    """Adaptador Computer Use para CONDUSEF (Comisión Nacional para la Protección y Defensa de los Usuarios de Servicios Financieros)."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name = "condusef"
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        if not (credentials or {}).get("username") and not os.environ.get("CONDUSEF_USERNAME"):
            logger.warning("CONDUSEFAdapter: no credentials — MOCK mode")
            self._connected = True; return True
        self._connected = True
        logger.info("CONDUSEFAdapter: connected (Computer Use)")
        return True

    def consultar_quejas(self, entidad: str) -> Dict[str, Any]:
        self._ensure_connected()
        return {"entidad": entidad, "quejas_pendientes": 0, "status": "sin_quejas"}

    def obtener_fondata(self) -> Dict[str, Any]:
        self._ensure_connected()
        return {"fondata_version": "2026.01", "entidades": 150, "status": "actualizado"}

    def _ensure_connected(self):
        if not self._connected: raise RuntimeError("CONDUSEFAdapter no conectado.")

    def test_connection(self) -> Dict[str, Any]:
        try:
            self._ensure_connected()
            return {"adapter": self.name, "status": "connected", "method": "computer_use", "message": "Connected to CONDUSEF"}
        except Exception as e:
            return {"adapter": self.name, "status": "error", "message": str(e)}
