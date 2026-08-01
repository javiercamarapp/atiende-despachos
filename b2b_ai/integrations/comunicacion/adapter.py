# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de comunicación.

CommunicationAdapter es la clase base abstracta que todos los adaptadores
de comunicación deben implementar (SendGrid, Twilio, WhatsApp Business).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from b2b_ai.integrations.comunicacion.models import (
    CommunicationConfig,
    EmailRequest,
    Message,
    NotificationRequest,
    SMSRequest,
    WhatsAppRequest,
)

logger = logging.getLogger(__name__)


class CommunicationAdapterError(Exception):
    """Error genérico de adaptador de comunicación."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class CommunicationAdapter(ABC):
    """Clase base abstracta para integración de comunicación.

    Todos los adaptadores (SendGrid, Twilio, WhatsApp Business)
    deben implementar estos métodos.
    """

    def __init__(self, config: CommunicationConfig):
        self.config = config
        self.name = config.provider
        self._connected = False
        logger.info(f"CommunicationAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise CommunicationAdapterError(
                f"Adaptador de comunicación '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de comunicación.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def send_email(self, request: EmailRequest) -> Message:
        """Envía un email.

        Args:
            request: Solicitud de email.

        Returns:
            Message con el resultado.
        """
        ...

    @abstractmethod
    def send_sms(self, request: SMSRequest) -> Message:
        """Envía un SMS.

        Args:
            request: Solicitud de SMS.

        Returns:
            Message con el resultado.
        """
        ...

    @abstractmethod
    def send_whatsapp(self, request: WhatsAppRequest) -> Message:
        """Envía un mensaje de WhatsApp.

        Args:
            request: Solicitud de WhatsApp.

        Returns:
            Message con el resultado.
        """
        ...

    @abstractmethod
    def send_notification(self, request: NotificationRequest) -> Message:
        """Envía una notificación multi-canal.

        Args:
            request: Solicitud de notificación.

        Returns:
            Message con el resultado.
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
        except CommunicationAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
