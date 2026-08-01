# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración SAT.

SATAdapter es la clase base abstracta que todos los adaptadores SAT
deben implementar (Ecodex, Finkok, SAT Portal).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from b2b_ai.integrations.sat.models import (
    CancelacionRequest,
    CFDI,
    CFDIRequest,
    ContabilidadElectronica,
    RFCStatus,
    TimbradoResponse,
)

logger = logging.getLogger(__name__)


class SATAdapterError(Exception):
    """Error genérico de adaptador SAT."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class SATAdapter(ABC):
    """Clase base abstracta para integración con el SAT y PACs.

    Todos los adaptadores SAT (Ecodex, Finkok, SAT Portal) deben
    implementar estos métodos.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self._connected = False
        logger.info(f"SATAdapter '{name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def connect(self) -> bool:
        """Conecta al PAC o servicio SAT. Override en subclases."""
        self._connected = True
        logger.info(f"SATAdapter '{self.name}' conectado")
        return True

    def disconnect(self) -> None:
        """Desconecta del PAC o servicio SAT."""
        self._connected = False
        logger.info(f"SATAdapter '{self.name}' desconectado")

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise SATAdapterError(
                f"Adaptador '{self.name}' no está conectado. Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def timbrar_cfdi(self, cfdi_data: CFDIRequest) -> TimbradoResponse:
        """Timbra un CFDI a través del PAC.

        Args:
            cfdi_data: Datos del CFDI a timbrar.

        Returns:
            TimbradoResponse con el resultado del timbrado.
        """
        ...

    @abstractmethod
    def cancelar_cfdi(self, request: CancelacionRequest) -> Dict[str, Any]:
        """Cancela un CFDI previamente timbrado.

        Args:
            request: Datos de la solicitud de cancelación.

        Returns:
            Dict con el resultado de la cancelación.
        """
        ...

    @abstractmethod
    def consultar_cfdi(self, uuid: str) -> CFDI:
        """Consulta el estatus de un CFDI por UUID.

        Args:
            uuid: UUID del CFDI a consultar.

        Returns:
            CFDI con la información actualizada.
        """
        ...

    @abstractmethod
    def consultar_rfc(self, rfc: str) -> RFCStatus:
        """Consulta el estatus de un RFC ante el SAT.

        Args:
            rfc: RFC a consultar.

        Returns:
            RFCStatus con la información del RFC.
        """
        ...

    @abstractmethod
    def contabilidad_electronica(self, datos: ContabilidadElectronica) -> Dict[str, Any]:
        """Envía contabilidad electrónica al SAT.

        Args:
            datos: Datos de contabilidad electrónica.

        Returns:
            Dict con el resultado del envío.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al servicio SAT/PAC.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "message": f"Adaptador '{self.name}' conectado correctamente",
            }
        except SATAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
