# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de pagos.

PaymentAdapter es la clase base abstracta que todos los adaptadores de pagos
deben implementar (Stripe, Conekta, PayPal).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.pagos.models import (
    Payment,
    PaymentConfig,
    PaymentRequest,
    Refund,
    RefundRequest,
    Transaction,
)

logger = logging.getLogger(__name__)


class PaymentAdapterError(Exception):
    """Error genérico de adaptador de pagos."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class PaymentAdapter(ABC):
    """Clase base abstracta para integración de pagos.

    Todos los adaptadores de pagos (Stripe, Conekta, PayPal)
    deben implementar estos métodos.
    """

    def __init__(self, config: PaymentConfig):
        self.config = config
        self.name = config.provider
        self._connected = False
        logger.info(f"PaymentAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise PaymentAdapterError(
                f"Adaptador de pagos '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de pagos.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def create_payment(self, request: PaymentRequest) -> Payment:
        """Crea un pago.

        Args:
            request: Solicitud de pago.

        Returns:
            Payment con el resultado.
        """
        ...

    @abstractmethod
    def verify_payment(self, payment_id: str) -> Payment:
        """Verifica el estado de un pago.

        Args:
            payment_id: ID del pago.

        Returns:
            Payment con el estado actualizado.
        """
        ...

    @abstractmethod
    def refund(self, request: RefundRequest) -> Refund:
        """Realiza un reembolso.

        Args:
            request: Solicitud de reembolso.

        Returns:
            Refund con el resultado.
        """
        ...

    @abstractmethod
    def get_transactions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Transaction]:
        """Obtiene el historial de transacciones.

        Args:
            date_from: Fecha inicio (YYYY-MM-DD).
            date_to: Fecha fin (YYYY-MM-DD).

        Returns:
            Lista de transacciones.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al proveedor de pagos.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "test_mode": self.config.test_mode,
                "currency": self.config.currency.value,
                "message": f"Conectado a {self.name} correctamente",
            }
        except PaymentAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
