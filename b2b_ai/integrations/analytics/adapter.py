# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base para integración de analytics.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.analytics.models import (
    AnalyticsConfig, AnalyticsEvent, AnalyticsEventResult, AnalyticsQuery, AnalyticsQueryResult,
)

logger = logging.getLogger(__name__)


class AnalyticsAdapterError(Exception):
    """Error genérico de adaptador analytics."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class AnalyticsAdapter(ABC):
    """Clase base abstracta para integración de analytics."""

    def __init__(self, config: AnalyticsConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        logger.info(f"AnalyticsAdapter '{self.name}' inicializado")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise AnalyticsAdapterError(
                f"Adaptador analytics '{self.name}' no está conectado. Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor de analytics."""
        ...

    @abstractmethod
    def track_event(self, event: AnalyticsEvent) -> AnalyticsEventResult:
        """Registra un evento."""
        ...

    @abstractmethod
    def query(self, query: AnalyticsQuery) -> AnalyticsQueryResult:
        """Ejecuta una consulta de analytics."""
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al proveedor."""
        try:
            self._ensure_connected()
            return {
                "adapter": self.name, "status": "connected",
                "message": f"Conectado a {self.name} correctamente",
            }
        except AnalyticsAdapterError as e:
            return {"adapter": self.name, "status": "error", "message": str(e), "code": e.code}
