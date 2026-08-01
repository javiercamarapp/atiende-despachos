# -*- coding: utf-8 -*-
"""
hub.py — IntegrationHub: Registro central de todos los adaptadores de integración.

Permite registrar, obtener, listar y probar la conexión de todos los
adaptadores del sistema (SAT, ERP, Bancos, Nómina).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from b2b_ai.integrations.sat.adapter import SATAdapter
from b2b_ai.integrations.erp.adapter import ERPAdapter
from b2b_ai.integrations.bancos.adapter import BankAdapter
from b2b_ai.integrations.nomina.adapter import NominaAdapter

logger = logging.getLogger(__name__)


class IntegrationHubError(Exception):
    """Error del IntegrationHub."""

    def __init__(self, message: str, code: str = ""):
        self.message = message
        self.code = code
        super().__init__(self.message)


# Type alias for any adapter
AnyAdapter = Union[SATAdapter, ERPAdapter, BankAdapter, NominaAdapter]


class IntegrationHub:
    """Hub central de integraciones.

    Registra y gestiona todos los adaptadores del sistema:
    - SAT (Ecodex, Finkok, SAT Portal)
    - ERP (CONTPAQi, Aspel, QuickBooks, Xero)
    - Bancos (BBVA, Banorte, Santander, OFX, CSV)
    - Nómina (NominaService)

    Uso:
        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("erp_quickbooks", QuickBooksOnlineAdapter(config))
        hub.get_adapter("sat_ecodex")
        hub.get_status()
    """

    def __init__(self):
        self._adapters: Dict[str, AnyAdapter] = {}
        logger.info("IntegrationHub inicializado")

    def register_adapter(self, name: str, adapter: AnyAdapter) -> None:
        """Registra un adaptador en el hub.

        Args:
            name: Nombre único del adaptador.
            adapter: Instancia del adaptador.

        Raises:
            IntegrationHubError: Si el nombre ya está registrado.
        """
        if name in self._adapters:
            raise IntegrationHubError(
                f"El adaptador '{name}' ya está registrado. "
                "Use unregister() primero o un nombre diferente.",
                code="ADAPTER_ALREADY_REGISTERED",
            )

        self._adapters[name] = adapter
        adapter_type = type(adapter).__name__
        logger.info(f"Adaptador '{name}' registrado ({adapter_type})")

    def unregister_adapter(self, name: str) -> bool:
        """Elimina un adaptador del hub.

        Args:
            name: Nombre del adaptador a eliminar.

        Returns:
            True si se eliminó, False si no existía.
        """
        if name in self._adapters:
            del self._adapters[name]
            logger.info(f"Adaptador '{name}' eliminado del hub")
            return True
        return False

    def get_adapter(self, name: str) -> AnyAdapter:
        """Obtiene un adaptador por nombre.

        Args:
            name: Nombre del adaptador.

        Returns:
            Instancia del adaptador.

        Raises:
            IntegrationHubError: Si el adaptador no existe.
        """
        if name not in self._adapters:
            available = ", ".join(self._adapters.keys()) or "ninguno"
            raise IntegrationHubError(
                f"Adaptador '{name}' no encontrado. "
                f"Disponibles: {available}",
                code="ADAPTER_NOT_FOUND",
            )
        return self._adapters[name]

    def list_adapters(self) -> Dict[str, Dict[str, Any]]:
        """Lista todos los adaptadores registrados.

        Returns:
            Dict con información de cada adaptador.
        """
        result = {}
        for name, adapter in self._adapters.items():
            adapter_type = type(adapter).__name__
            is_connected = getattr(adapter, "is_connected", False)
            result[name] = {
                "name": name,
                "type": adapter_type,
                "connected": is_connected,
                "category": self._get_category(adapter),
            }
        return result

    def _get_category(self, adapter: AnyAdapter) -> str:
        """Determina la categoría de un adaptador."""
        if isinstance(adapter, SATAdapter):
            return "sat"
        if isinstance(adapter, ERPAdapter):
            return "erp"
        if isinstance(adapter, BankAdapter):
            return "banco"
        if isinstance(adapter, NominaAdapter):
            return "nomina"
        return "desconocido"

    def test_connection(self, name: str) -> Dict[str, Any]:
        """Prueba la conexión de un adaptador específico.

        Args:
            name: Nombre del adaptador.

        Returns:
            Dict con el resultado de la prueba.
        """
        try:
            adapter = self.get_adapter(name)
            if hasattr(adapter, "test_connection"):
                return adapter.test_connection()
            return {
                "adapter": name,
                "status": "unknown",
                "message": "El adaptador no soporta test_connection()",
            }
        except IntegrationHubError as e:
            return {
                "adapter": name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }

    def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado de todos los adaptadores registrados.

        Returns:
            Dict con el estado de cada adaptador y un resumen general.
        """
        adapters_status = {}
        connected_count = 0
        error_count = 0

        for name, adapter in self._adapters.items():
            try:
                result = self.test_connection(name)
                adapters_status[name] = result
                if result.get("status") == "connected":
                    connected_count += 1
                elif result.get("status") == "error":
                    error_count += 1
            except Exception as e:
                adapters_status[name] = {
                    "adapter": name,
                    "status": "error",
                    "message": str(e),
                }
                error_count += 1

        return {
            "total_adapters": len(self._adapters),
            "connected": connected_count,
            "errors": error_count,
            "adapters": adapters_status,
        }

    def connect_all(self) -> Dict[str, bool]:
        """Intenta conectar todos los adaptadores registrados.

        Returns:
            Dict con el resultado de cada conexión.
        """
        results = {}
        for name, adapter in self._adapters.items():
            try:
                if hasattr(adapter, "connect"):
                    result = adapter.connect()
                    results[name] = result
                    logger.info(f"Conexión de '{name}': {'exitosa' if result else 'fallida'}")
                else:
                    results[name] = True
            except Exception as e:
                results[name] = False
                logger.error(f"Error conectando '{name}': {e}")
        return results

    def get_adapters_by_category(self, category: str) -> Dict[str, AnyAdapter]:
        """Obtiene adaptadores filtrados por categoría.

        Args:
            category: "sat", "erp", "banco", "nomina"

        Returns:
            Dict de adaptadores de la categoría.
        """
        result = {}
        for name, adapter in self._adapters.items():
            if self._get_category(adapter) == category:
                result[name] = adapter
        return result

    @property
    def count(self) -> int:
        """Número de adaptadores registrados."""
        return len(self._adapters)
