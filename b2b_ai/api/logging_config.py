# -*- coding: utf-8 -*-
"""
logging_config.py — Configuración de logging estructurado (JSON) para la API.

Provee un punto único para configurar el logging de la aplicación, de modo que
todos los componentes (API, pipeline, jobs) emitan JSON estructurado con el
mismo formato y campos de correlación (request_id, tenant, user).

Reutiliza la infraestructura existente de `b2b_ai.monitoring.logger` (handler
JSON con PII masking) y `b2b_ai.infrastructure.structured_logging` (rotación de
archivos). Este módulo NO duplica lógica: expone la configuración y factories
canónicas para que la API los use de forma consistente.

Configuración por env:
    B2B_LOG_LEVEL       DEBUG|INFO|WARNING|ERROR (default: INFO)
    B2B_LOG_TO_FILE     "true" → habilita archivo rotativo (logs/b2b_ai.log)
    B2B_LOG_DIR         directorio de logs (default: "logs")

Usage:
    from b2b_ai.api.logging_config import configure_logging, get_logger
    configure_logging()
    log = get_logger("api")
    log.info("arrancando", extra={"detail": "ok"})
"""
from __future__ import annotations

import logging
import os
from typing import Optional

# Handler JSON + PII masking (estructura existente).
from b2b_ai.monitoring.logger import JsonFormatter, get_logger as _mon_get_logger

# Rotation (opcional, file-based) — estructura existente.
from b2b_ai.infrastructure.structured_logging import (
    create_rotating_handler,
)

_configured = False


def configure_logging(
    log_to_file: Optional[bool] = None,
    log_dir: str = "logs",
    module_levels: Optional[dict] = None,
) -> None:
    """Configura el logging estructurado (JSON) de la aplicación.

    Idempotente: solo configura la primera vez (evita duplicar handlers en
    recargas / tests). Establece el handler JSON en el root logger y,
    opcionalmente, un handler rotativo a archivo.

    Args:
        log_to_file: Si True, agrega rotación a archivo. Si None, usa la env
            B2B_LOG_TO_FILE ("true").
        log_dir: Directorio para logs rotativos.
        module_levels: Overrides de nivel por módulo (opcional).
    """
    global _configured
    if _configured:
        return

    level = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
             "WARNING": logging.WARNING, "ERROR": logging.ERROR,
             "CRITICAL": logging.CRITICAL}.get(
                 os.environ.get("B2B_LOG_LEVEL", "INFO").upper(), logging.INFO)

    root = logging.getLogger()
    if root.level > level:
        root.setLevel(level)

    # Asegura el handler JSON en el root (idempotente dentro de monitoring).
    _mon_get_logger("b2b_ai")

    # Opcional: rotación a archivo.
    want_file = log_to_file if log_to_file is not None else (
        os.environ.get("B2B_LOG_TO_FILE", "").lower() == "true")
    if want_file:
        if not any(getattr(h, "b2b_rotating", False)
                   for h in root.handlers):
            handler = create_rotating_handler(
                log_dir=os.environ.get("B2B_LOG_DIR", log_dir),
                formatter=JsonFormatter(),
            )
            root.addHandler(handler)

    _configured = True


def get_logger(name: str = "b2b_ai") -> logging.Logger:
    """Devuelve un logger con el formato JSON estructurado instalado."""
    return _mon_get_logger(name)


def reset_logging_config() -> None:
    """Resetea el flag de configurado (para tests aislados)."""
    global _configured
    _configured = False
