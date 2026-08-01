# -*- coding: utf-8 -*-
"""Módulo de integración AI/ML — OpenAI, Anthropic, Google Vertex AI."""

from b2b_ai.integrations.ai.adapter import AIAdapter, AIAdapterError
from b2b_ai.integrations.ai.openai_adapter import OpenAIAdapter
from b2b_ai.integrations.ai.anthropic_adapter import AnthropicAdapter
from b2b_ai.integrations.ai.vertex_adapter import VertexAIAdapter
from b2b_ai.integrations.ai.models import (
    AIConfig, AIMessage, AIMessageRole, AIProvider, AIRequest, AIResponse,
    EmbeddingRequest, EmbeddingResponse,
)

__all__ = [
    "AIAdapter", "AIAdapterError",
    "OpenAIAdapter", "AnthropicAdapter", "VertexAIAdapter",
    "AIConfig", "AIMessage", "AIMessageRole", "AIProvider",
    "AIRequest", "AIResponse", "EmbeddingRequest", "EmbeddingResponse",
]
