# -*- coding: utf-8 -*-
"""
sentry_adapter.py — Adaptador mock para Sentry error tracking.

Implementa la interfaz MonitoringAdapter con respuestas simuladas.
En producción, se conectaría a la Sentry SDK/REST API (https://docs.sentry.io/api/).
"""
from __future__ import annotations

import logging
import traceback
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


class SentryAdapter(MonitoringAdapter):
    """Adaptador mock para Sentry error tracking.

    En producción, usaría el Sentry SDK para Python
    (https://docs.sentry.io/platforms/python/).
    Captura excepciones, mensajes y breadcrumbs automáticamente.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None):
        config = config or MonitoringConfig(
            provider=MonitoringProvider.SENTRY,
            dsn="https://mockkey@sentry.io/1234567",
            environment="development",
            release="b2b-ai@1.0.0",
            sample_rate=1.0,
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Sentry.

        En producción:
        1. Inicializar Sentry SDK con dsn
        2. Configurar environment, release, sample_rate
        """
        logger.info("SentryAdapter: conectando a Sentry (mock)...")
        self._connected = True
        logger.info("SentryAdapter: conexión exitosa (mock)")
        return True

    def capture_exception(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        level: ErrorLevel = ErrorLevel.ERROR,
    ) -> ErrorReport:
        """Captura una excepción mock en Sentry.

        En producción: Sentry captura automáticamente o con capture_exception()
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"sentry_{_uuid.uuid4().hex[:16]}"

        stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        logger.error(f"SentryAdapter: capturando excepción '{type(error).__name__}: {error}'")

        return ErrorReport(
            id=error_id,
            message=f"{type(error).__name__}: {error}",
            level=level,
            stacktrace=stacktrace,
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
        """Captura un mensaje mock en Sentry.

        En producción: capture_message(message, level)
        """
        self._ensure_connected()
        now = datetime.now().isoformat()
        error_id = f"sentry_msg_{_uuid.uuid4().hex[:16]}"

        logger.info(f"SentryAdapter: capturando mensaje [{level.value}] '{message}'")

        return ErrorReport(
            id=error_id,
            message=message,
            level=level,
            context=context or {},
            environment=self.config.environment,
            release=self.config.release,
            timestamp=now,
        )
