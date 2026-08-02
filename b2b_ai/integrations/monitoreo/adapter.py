# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base y utilidades para integración de monitoreo.

MonitoringAdapter es la clase base abstracta que todos los adaptadores
de monitoreo deben implementar (Sentry, Console).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.monitoreo.models import (
    Breadcrumb,
    ErrorLevel,
    ErrorReport,
    MonitoringConfig,
    UserContext,
)

logger = logging.getLogger(__name__)


class MonitoringAdapterError(Exception):
    """Error genérico de adaptador de monitoreo."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class MonitoringAdapter(ABC):
    """Clase base abstracta para integración de monitoreo.

    Todos los adaptadores (Sentry, Console)
    deben implementar estos métodos.
    """

    def __init__(self, config: MonitoringConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        self._breadcrumbs: List[Breadcrumb] = []
        self._user_context: Optional[UserContext] = None
        logger.info(f"MonitoringAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        """Indica si el adaptador está conectado."""
        return self._connected

    def _ensure_connected(self) -> None:
        """Verifica que el adaptador esté conectado."""
        if not self._connected:
            raise MonitoringAdapterError(
                f"Adaptador de monitoreo '{self.name}' no está conectado. "
                "Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    # ------------------------------------------------------------------
    # Métodos abstractos
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de monitoreo.

        Args:
            credentials: Credenciales adicionales de conexión.

        Returns:
            True si la conexión fue exitosa.
        """
        ...

    @abstractmethod
    def capture_exception(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        level: ErrorLevel = ErrorLevel.ERROR,
    ) -> ErrorReport:
        """Captura y reporta una excepción.

        Args:
            error: Excepción a reportar.
            context: Contexto adicional.
            level: Nivel de severidad.

        Returns:
            ErrorReport con el resultado.
        """
        ...

    @abstractmethod
    def capture_message(
        self,
        message: str,
        level: ErrorLevel = ErrorLevel.INFO,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorReport:
        """Captura y reporta un mensaje.

        Args:
            message: Mensaje a reportar.
            level: Nivel de severidad.
            context: Contexto adicional.

        Returns:
            ErrorReport con el resultado.
        """
        ...

    def add_breadcrumb(
        self,
        message: str,
        category: str = "",
        level: ErrorLevel = ErrorLevel.INFO,
        data: Optional[Dict[str, Any]] = None,
    ) -> Breadcrumb:
        """Agrega un breadcrumb al historial.

        Args:
            message: Mensaje del breadcrumb.
            category: Categoría.
            level: Nivel.
            data: Datos adicionales.

        Returns:
            Breadcrumb creado.
        """
        breadcrumb = Breadcrumb(
            message=message,
            category=category,
            level=level,
            timestamp=datetime.now().isoformat(),
            data=data or {},
        )
        self._breadcrumbs.append(breadcrumb)
        logger.debug(f"Breadcrumb: [{category}] {message}")
        return breadcrumb

    def set_user(self, user_id: str, email: Optional[str] = None, **kwargs: Any) -> UserContext:
        """Establece el contexto de usuario.

        Args:
            user_id: ID del usuario.
            email: Email del usuario.
            **kwargs: Campos adicionales.

        Returns:
            UserContext establecido.
        """
        self._user_context = UserContext(
            user_id=user_id,
            email=email,
            **kwargs,
        )
        logger.debug(f"User context set: {user_id}")
        return self._user_context

    def clear_user(self) -> None:
        """Limpia el contexto de usuario."""
        self._user_context = None
        logger.debug("User context cleared")

    @property
    def breadcrumbs(self) -> List[Breadcrumb]:
        """Lista de breadcrumbs acumulados."""
        return self._breadcrumbs.copy()

    @property
    def user_context(self) -> Optional[UserContext]:
        """Contexto de usuario actual."""
        return self._user_context

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
                "environment": self.config.environment,
                "release": self.config.release,
                "message": f"Conectado a {self.name} correctamente",
            }
        except MonitoringAdapterError as e:
            return {
                "adapter": self.name,
                "status": "error",
                "message": str(e),
                "code": e.code,
            }
