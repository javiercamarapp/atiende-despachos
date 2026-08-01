# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de AI/ML (OpenAI, Anthropic, Vertex AI).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AIProvider(str, Enum):
    """Proveedores de AI/ML."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    VERTEX_AI = "vertex_ai"


class AIMessageRole(str, Enum):
    """Roles de mensaje en conversaciones."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class AIConfig(BaseModel):
    """Configuración de integración AI/ML."""
    provider: AIProvider = Field(..., description="Proveedor de AI/ML")
    api_key: str = Field(default="", description="API key")
    api_secret: Optional[str] = Field(default=None, description="API secret (si aplica)")
    model: str = Field(default="gpt-4", description="Modelo a utilizar")
    max_tokens: int = Field(default=4096, description="Máximo de tokens")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperatura")
    project_id: Optional[str] = Field(default=None, description="GCP Project ID (Vertex AI)")
    region: Optional[str] = Field(default=None, description="GCP Region (Vertex AI)")
    timeout: int = Field(default=60, description="Timeout en segundos")


class AIMessage(BaseModel):
    """Mensaje en una conversación AI."""
    role: AIMessageRole = Field(..., description="Rol del mensaje")
    content: str = Field(..., description="Contenido del mensaje")


class AIRequest(BaseModel):
    """Solicitud de generación AI."""
    messages: List[AIMessage] = Field(..., description="Historial de mensajes")
    model: Optional[str] = Field(default=None, description="Modelo (override)")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens (override)")
    temperature: Optional[float] = Field(default=None, description="Temperatura (override)")
    stop: Optional[List[str]] = Field(default=None, description="Secuencias de parada")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos")


class AIResponse(BaseModel):
    """Respuesta de generación AI."""
    id: str = Field(default="", description="ID de la respuesta")
    content: str = Field(default="", description="Contenido generado")
    model: str = Field(default="", description="Modelo utilizado")
    usage: Dict[str, int] = Field(default_factory=dict, description="Uso de tokens")
    finish_reason: str = Field(default="stop", description="Razón de finalización")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class EmbeddingRequest(BaseModel):
    """Solicitud de embedding."""
    input_text: str = Field(..., description="Texto a vectorizar")
    model: Optional[str] = Field(default=None, description="Modelo de embedding")


class EmbeddingResponse(BaseModel):
    """Respuesta de embedding."""
    embedding: List[float] = Field(default_factory=list, description="Vector de embedding")
    model: str = Field(default="", description="Modelo utilizado")
    dimensions: int = Field(default=0, description="Dimensiones del vector")
