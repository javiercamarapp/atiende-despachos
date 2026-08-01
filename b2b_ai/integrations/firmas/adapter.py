# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de firmas electrónicas.

SignatureAdapter es la clase base abstracta que todos los adaptadores
de firmas deben implementar (DocuSign, FIEL/SAT).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.firmas.models import (
    Envelope,
    SignatureConfig,
    SigningRequest,
    SigningStatus,
)

logger = logging.getLogger(__name__)


class SignatureAdapterError(Exception):
    """Error genérico de adaptador de firmas."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class SignatureAdapter(ABC):
    """Clase base abstracta para integración de firmas electrónicas.

    Todos los adaptadores (DocuSign, FIEL/SAT)
    deben implementar estos métodos.
    """

    def __init__(self, config: SignatureConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        logger.info(f"SignatureAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise SignatureAdapterError(
                f"Adaptador de firmas '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de firmas.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def create_envelope(self, request: SigningRequest) -> Envelope:
        """Crea un sobre de firma.

        Args:
            request: Solicitud de firma.

        Returns:
            Envelope con el resultado.
        """
        ...

    @abstractmethod
    def get_status(self, envelope_id: str) -> SigningStatus:
        """Obtiene el estado de un sobre.

        Args:
            envelope_id: ID del sobre.

        Returns:
            SigningStatus con el estado actual.
        """
        ...

    @abstractmethod
    def download_signed(self, envelope_id: str) -> bytes:
        """Descarga el documento firmado.

        Args:
            envelope_id: ID del sobre.

        Returns:
            Contenido del documento firmado en bytes.
        """
        ...

    @abstractmethod
    def cancel(self, envelope_id: str) -> bool:
        """Cancela un sobre de firma.

        Args:
            envelope_id: ID del sobre.

        Returns:
            True si se canceló correctamente.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al proveedor.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "message": f"Conectado a {self.name} correctamente",
            }
        except SignatureAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
