# -*- coding: utf-8 -*-
"""
vertex_adapter.py — Adaptador mock para Google Vertex AI.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.ai.adapter import AIAdapter
from b2b_ai.integrations.ai.models import (
    AIConfig, AIProvider, AIRequest, AIResponse, EmbeddingRequest, EmbeddingResponse,
)

logger = logging.getLogger(__name__)


class VertexAIAdapter(AIAdapter):
    """Adaptador mock para Google Vertex AI."""

    def __init__(self, config: Optional[AIConfig] = None):
        config = config or AIConfig(provider=AIProvider.VERTEX_AI, api_key="mock_vertex_key",
                                    model="gemini-pro", project_id="mock-project", region="us-central1")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("VertexAIAdapter: conexión exitosa (mock)")
        return True

    def generate(self, request: AIRequest) -> AIResponse:
        self._ensure_connected()
        model = request.model or self.config.model
        return AIResponse(
            id=f"vertex_{_uuid.uuid4().hex[:12]}", content="Respuesta mock de Google Vertex AI para Likida AI.",
            model=model, usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            finish_reason="STOP",
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self._ensure_connected()
        model = request.model or "textembedding-gecko@latest"
        return EmbeddingResponse(embedding=[0.1] * 768, model=model, dimensions=768)
