# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de analytics (Google Analytics, Mixpanel, Amplitude).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnalyticsProvider(str, Enum):
    """Proveedores de analytics."""
    GOOGLE_ANALYTICS = "google_analytics"
    MIXPANEL = "mixpanel"
    AMPLITUDE = "amplitude"


class EventType(str, Enum):
    """Tipos de eventos."""
    PAGE_VIEW = "page_view"
    CLICK = "click"
    FORM_SUBMIT = "form_submit"
    PURCHASE = "purchase"
    CUSTOM = "custom"


class AnalyticsConfig(BaseModel):
    """Configuración de integración analytics."""
    provider: AnalyticsProvider = Field(..., description="Proveedor de analytics")
    api_key: str = Field(default="", description="API key / Tracking ID")
    api_secret: Optional[str] = Field(default=None, description="API secret (si aplica)")
    property_id: Optional[str] = Field(default=None, description="Property ID (GA4)")
    project_id: Optional[str] = Field(default=None, description="Project ID (Mixpanel/Amplitude)")
    environment: str = Field(default="production", description="Entorno")
    timeout: int = Field(default=30, description="Timeout en segundos")


class AnalyticsEvent(BaseModel):
    """Evento de analytics."""
    event_name: str = Field(..., description="Nombre del evento")
    event_type: EventType = Field(default=EventType.CUSTOM, description="Tipo de evento")
    user_id: Optional[str] = Field(default=None, description="ID del usuario")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Propiedades del evento")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class AnalyticsEventResult(BaseModel):
    """Resultado de envío de evento."""
    success: bool = Field(default=True, description="Si fue exitoso")
    event_id: str = Field(default="", description="ID del evento registrado")
    message: str = Field(default="", description="Mensaje")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class AnalyticsQuery(BaseModel):
    """Consulta de analytics."""
    metric: str = Field(..., description="Métrica a consultar")
    dimensions: List[str] = Field(default_factory=list, description="Dimensiones")
    date_range: Dict[str, str] = Field(default_factory=dict, description="Rango de fechas")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Filtros")
    limit: int = Field(default=100, description="Límite de resultados")


class AnalyticsQueryResult(BaseModel):
    """Resultado de consulta de analytics."""
    success: bool = Field(default=True, description="Si fue exitoso")
    data: List[Dict[str, Any]] = Field(default_factory=list, description="Datos de la consulta")
    totals: Dict[str, float] = Field(default_factory=dict, description="Totales")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos de la consulta")
    query_time_ms: float = Field(default=0.0, description="Tiempo de consulta")
