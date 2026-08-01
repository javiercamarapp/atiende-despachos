# -*- coding: utf-8 -*-
"""
adapter.py — Adapter base para integración AI/ML.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.ai.models import (
    AIConfig, AIRequest, AIResponse, EmbeddingRequest, EmbeddingResponse,
)

logger = logging.getLogger(__name__)


class AIAdapterError(Exception):
    """Error genérico de adaptador AI."""

    def __init__(self, message: str, code: str = "", details: Dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class AIAdapter(ABC):
    """Clase base abstracta para integración AI/ML."""

    def __init__(self, config: AIConfig):
        self.config = config
        self.name = config.provider.value
        self._connected = False
        logger.info(f"AIAdapter '{self.name}' inicializado (modelo: {config.model})")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise AIAdapterError(
                f"Adaptador AI '{self.name}' no está conectado. Llame connect() primero.",
                code="NOT_CONNECTED",
            )

    @abstractmethod
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta al proveedor AI."""
        ...

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """Genera una respuesta AI."""
        ...

    @abstractmethod
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Genera un embedding."""
        ...

    def test_connection(self) -> Dict[str, Any]:
        """Prueba la conexión al proveedor AI."""
        try:
            self._ensure_connected()
            return {
                "adapter": self.name, "status": "connected",
                "model": self.config.model,
                "message": f"Conectado a {self.name} correctamente",
            }
        except AIAdapterError as e:
            return {"adapter": self.name, "status": "error", "message": str(e), "code": e.code}
