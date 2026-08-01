# -*- coding: utf-8 -*-
"""
console_adapter.py — Adaptador de monitoreo para consola (desarrollo).

Implementa la interfaz MonitoringAdapter con logging a consola.
Útil para desarrollo local donde Sentry no está configurado.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.monitoreo.adapter import MonitoringAdapter
from b2b_ai.integrations.monitoreo.models import (
    ErrorLevel,
    ErrorReport,
    MonitoringConfig,
    MonitoringProvider,
)

logger = logging.getLogger(__name__)


class ConsoleAdapter(MonitoringAdapter):
    """Adaptador de monitoreo para consola de desarrollo.

    Registra errores y mensajes usando el logger de Python.
    Ideal para entornos de desarrollo donde no hay servicio externo.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.CONSOLE,
            environment="development",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Conecta el adaptador de consola (siempre exitoso)."""
        logger.info("ConsoleAdapter: adaptador de consola activado (mock)...")
        self._connected = True
        logger.info("ConsoleAdapter: listo para monitoreo en consola (mock)")
        return True

    def capture_exception(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        level: ErrorLevel = ErrorLevel.ERROR,
    ) -> ErrorReport:
        """Registra una excepción en consola.

        En producción real: log a stdout/stderr con formato estructurado.
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"console_{_uuid.uuid4().hex[:16]}"

        logger.error(f"[CONSOLE] Exception: {type(error).__name__}: {error}")
        if context:
            logger.error(f"[CONSOLE] Context: {context}")

        return ErrorReport(
            id=error_id,
            message=f"{type(error).__name__}: {error}",
            level=level,
            stacktrace=None,
            context=context or {},
            environment=self.config.environment,
            release=self.config.release,
            timestamp=now,
        )

    def capture_message(
        self,
        message: str,
        level: ErrorLevel = ErrorLevel.INFO,
        context: Optional[Dict[str, Any]] = None,
    ) -> ErrorReport:
        """Registra un mensaje en consola.

        En producción real: log estructurado según el nivel.
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"console_msg_{_uuid.uuid4().hex[:16]}"

        log_func = {
            ErrorLevel.DEBUG: logger.debug,
            ErrorLevel.INFO: logger.info,
            ErrorLevel.WARNING: logger.warning,
            ErrorLevel.ERROR: logger.error,
            ErrorLevel.FATAL: logger.critical,
        }.get(level, logger.info)

        log_func(f"[CONSOLE] [{level.value.upper()}] {message}")
        if context:
            log_func(f"[CONSOLE] Context: {context}")

        return ErrorReport(
            id=error_id,
            message=message,
            level=level,
            context=context or {},
            environment=self.config.environment,
            release=self.config.release,
            timestamp=now,
        )
