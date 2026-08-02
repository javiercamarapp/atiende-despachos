# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración bancaria.

BankAdapter es la clase base abstracta que todos los adaptadores bancarios
deben implementar (BBVA, Banorte, Santander, parsers).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.bancos.models import (
    BankConfig,
    BankStatement,
    BankTransaction,
    FormatoEstado,
)

logger = logging.getLogger(__name__)


class BankAdapterError(Exception):
    """Error genérico de adaptador bancario."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class BankAdapter(ABC):
    """Clase base abstracta para integración bancaria.

    Todos los adaptadores bancarios (BBVA, Banorte, Santander, parsers)
    deben implementar estos métodos.
    """

    def __init__(self, config: BankConfig):
        self.config = config
        self.name = config.bank.value
        self._connected = False
        logger.info(f"BankAdapter '{self.name}' inicializado para cuenta {config.account_number}")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise BankAdapterError(
                f"Adaptador bancario '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al banco o carga datos.

        Args:
            credentials: Credenciales adicionales.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Desconecta del banco."""
        ...

    @abstractmethod
    def get_statement(self, date_range: Optional[Dict[str, str]] = None) -> BankStatement:
        """Obtiene el estado de cuenta.

        Args:
            date_range: {"from": "2026-01-01", "to": "2026-01-31"}

        Returns:
            BankStatement del periodo.
        """
        ...

    @abstractmethod
    def get_transactions(self, date_range: Optional[Dict[str, str]] = None) -> List[BankTransaction]:
        """Obtiene las transacciones del periodo.

        Args:
            date_range: {"from": "2026-01-01", "to": "2026-01-31"}

        Returns:
            Lista de transacciones.
        """
        ...

    @abstractmethod
    def download_statement(self, format: FormatoEstado = FormatoEstado.OFX) -> bytes:
        """Descarga el estado de cuenta en el formato especificado.

        Args:
            format: Formato de descarga (OFX, CSV, XLSX, PDF).

        Returns:
            Contenido del archivo en bytes.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al banco.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "account": self.config.account_number,
                "status": "connected",
                "message": f"Conectado a {self.name} correctamente",
            }
        except BankAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
