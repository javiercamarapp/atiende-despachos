# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base para integración directa con SAT.
SATDirectAdapter es la clase base abstracta para integraciones SAT directas.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from b2b_ai.integrations.sat_direct.models import (
    ContabilidadElectronicaDirect,
    DIOTSubmission,
    SATDirectConfig,
    SATDirectTimbradoResponse,
)

logger = logging.getLogger(__name__)


class SATDirectAdapterError(Exception):
    """Error genérico de adaptador SAT directo."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class SATDirectAdapter(ABC):
    """Clase base abstracta para integración directa con SAT.

    Cubre: CFDI 4.0 timbrado, cancelación, consulta RFC,
    contabilidad electrónica y DIOT.
    """

    def __init__(self, config: SATDirectConfig):
        self.config = config
        self.name = type(self).__name__
        self._connected = False
        logger.info(f"SATDirectAdapter '{self.name}' inicializado para RFC {config.rfc}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise SATDirectAdapterError(
                f"Adaptador SAT '{self.name}' no está conectado. Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al SAT o PAC."""
        ...

    @abstractmethod
    def timbrar_cfdi(self, cfdi_data: Dict[str, Any]) -> SATDirectTimbradoResponse:
        """Timbra un CFDI 4.0."""
        ...

    @abstractmethod
    def cancelar_cfdi(self, uuid: str, motivo: str, rfc: str) -> Dict[str, Any]:
        """Cancela un CFDI previamente timbrado."""
        ...

    @abstractmethod
    def consultar_cfdi(self, uuid: str) -> Dict[str, Any]:
        """Consulta el estatus de un CFDI por UUID."""
        ...

    @abstractmethod
    def consultar_rfc(self, rfc: str) -> Dict[str, Any]:
        """Consulta el estatus de un RFC ante el SAT."""
        ...

    @abstractmethod
    def contabilidad_electronica(self, datos: ContabilidadElectronicaDirect) -> Dict[str, Any]:
        """Envía contabilidad electrónica al SAT."""
        ...

    @abstractmethod
    def enviar_diot(self, diot: DIOTSubmission) -> Dict[str, Any]:
        """Envía la DIOT (Determinación de Impuestos Operaciones con Terceros)."""
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al SAT."""
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "rfc": self.config.rfc,
                "cfdi_version": self.config.cfdi_version.value,
                "message": f"Conectado al SAT ({self.name}) correctamente",
            }
        except SATDirectAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
