# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración con ERPs.

ERPAdapter es la clase base abstracta que todos los adaptadores ERP
deben implementar (CONTPAQi, Aspel, QuickBooks, Xero).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion,
    ChartOfAccounts,
    ERPConfig,
    Invoice,
    Poliza,
)

logger = logging.getLogger(__name__)


class ERPAdapterError(Exception):
    """Error genérico de adaptador ERP."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class ERPAdapter(ABC):
    """Clase base abstracta para integración con ERPs contables.

    Todos los adaptadores ERP (CONTPAQi, Aspel, QuickBooks, Xero)
    deben implementar estos métodos.
    """

    def __init__(self, config: ERPConfig):
        self.config = config
        self.name = config.type.value
        self._connected = False
        self._empresa_info: Dict[str, Any] = {}
        logger.info(f"ERPAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado al ERP."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise ERPAdapterError(
                f"Adaptador ERP '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al ERP.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Desconecta del ERP."""
        ...

    @abstractmethod
    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas del ERP.

        Args:
            date_range: {"from": "2026-01-01", "to": "2026-01-31"}

        Returns:
            Lista de facturas del periodo.
        """
        ...

    @abstractmethod
    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas contables del ERP.

        Args:
            date_range: {"from": "2026-01-01", "to": "2026-01-31"}

        Returns:
            Lista de pólizas del periodo.
        """
        ...

    @abstractmethod
    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza contable al ERP.

        Args:
            poliza: Póliza a subir.

        Returns:
            Dict con el resultado de la operación.
        """
        ...

    @abstractmethod
    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene el catálogo de cuentas del ERP.

        Returns:
            ChartOfAccounts con todas las cuentas.
        """
        ...

    @abstractmethod
    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene la balanza de comprobación.

        Args:
            ejercicio: Año del ejercicio fiscal.
            mes: Mes (1-12).

        Returns:
            BalanzaComprobacion del periodo.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al ERP.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            self._ensure_connected()
            return {
                "adapter": self.name,
                "status": "connected",
                "empresa": self._empresa_info.get("nombre", "N/A"),
                "message": f"Conectado a {self.name} correctamente",
            }
        except ERPAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
