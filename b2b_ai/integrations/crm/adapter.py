# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de CRM.

CRMAdapter es la clase base abstracta que todos los adaptadores
de CRM deben implementar (HubSpot, Pipedrive).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.crm.models import (
    CRMConfig,
    Contact,
    ContactCreateRequest,
    Deal,
    DealCreateRequest,
)

logger = logging.getLogger(__name__)


class CRMAdapterError(Exception):
    """Error genérico de adaptador de CRM."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class CRMAdapter(ABC):
    """Clase base abstracta para integración de CRM.

    Todos los adaptadores (HubSpot, Pipedrive)
    deben implementar estos métodos.
    """

    def __init__(self, config: CRMConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        logger.info(f"CRMAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise CRMAdapterError(
                f"Adaptador de CRM '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al CRM.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def create_contact(self, request: ContactCreateRequest) -> Contact:
        """Crea un contacto.

        Args:
            request: Solicitud de creación.

        Returns:
            Contact con el ID asignado.
        """
        ...

    @abstractmethod
    def get_contact(self, contact_id: str) -> Contact:
        """Obtiene un contacto por ID.

        Args:
            contact_id: ID del contacto.

        Returns:
            Contact con los datos actualizados.
        """
        ...

    @abstractmethod
    def update_contact(self, contact_id: str, data: Dict[str, Any]) -> Contact:
        """Actualiza un contacto.

        Args:
            contact_id: ID del contacto.
            data: Campos a actualizar.

        Returns:
            Contact con los datos actualizados.
        """
        ...

    @abstractmethod
    def list_contacts(self, filters: Optional[Dict[str, Any]] = None) -> List[Contact]:
        """Lista contactos.

        Args:
            filters: Filtros de búsqueda (email, company, tags, etc.)

        Returns:
            Lista de contactos.
        """
        ...

    @abstractmethod
    def create_deal(self, contact_id: str, request: DealCreateRequest) -> Deal:
        """Crea una oportunidad asociada a un contacto.

        Args:
            contact_id: ID del contacto.
            request: Solicitud de creación de oportunidad.

        Returns:
            Deal con el ID asignado.
        """
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al CRM.

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
        except CRMAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
