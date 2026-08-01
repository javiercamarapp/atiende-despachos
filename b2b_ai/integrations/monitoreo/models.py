# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de monitoreo y error tracking.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ErrorLevel(str, Enum):
    """Nivel de severidad."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class MonitoringProvider(str, Enum):
    """Proveedores de monitoreo."""
    SENTRY = "sentry"
    CONSOLE = "console"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class MonitoringConfig(BaseModel):
    """Configuración del adaptador de monitoreo."""
    provider: MonitoringProvider = Field(..., description="Proveedor de monitoreo")
    dsn: Optional[str] = Field(default=None, description="Sentry DSN")
    environment: str = Field(default="development", description="Entorno (dev/staging/prod)")
    release: Optional[str] = Field(default=None, description="Versión de la aplicación")
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Tasa de muestreo")
    timeout: int = Field(default=10, description="Timeout en segundos")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ErrorReport(BaseModel):
    """Reporte de error."""
    id: str = Field(default="", description="ID del error")
    message: str = Field(default="", description="Mensaje de error")
    level: ErrorLevel = Field(default=ErrorLevel.ERROR, description="Nivel de severidad")
    stacktrace: Optional[str] = Field(default=None, description="Stacktrace")
    context: Dict[str, Any] = Field(default_factory=dict, description="Contexto adicional")
    environment: str = Field(default="development", description="Entorno")
    release: Optional[str] = Field(default=None, description="Versión")
    fingerprint: Optional[str] = Field(default=None, description="Fingerprint para agrupación")
    timestamp: str = Field(default="", description="Timestamp ISO")


class Breadcrumb(BaseModel):
    """Breadcrumb (pista de navegación)."""
    message: str = Field(default="", description="Mensaje del breadcrumb")
    category: str = Field(default="", description="Categoría")
    level: ErrorLevel = Field(default=ErrorLevel.INFO, description="Nivel")
    timestamp: str = Field(default="", description="Timestamp ISO")
    data: Dict[str, Any] = Field(default_factory=dict, description="Datos adicionales")


class UserContext(BaseModel):
    """Contexto de usuario para monitoreo."""
    user_id: str = Field(..., description="ID del usuario")
    email: Optional[str] = Field(default=None, description="Email")
    username: Optional[str] = Field(default=None, description="Nombre de usuario")
    ip_address: Optional[str] = Field(default=None, description="IP del usuario")
