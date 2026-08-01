# -*- coding: utf-8 -*-
"""
openai_adapter.py — Adaptador mock para OpenAI API.
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


class OpenAIAdapter(AIAdapter):
    """Adaptador mock para OpenAI API."""

    def __init__(self, config: Optional[AIConfig] = None):
        config = config or AIConfig(provider=AIProvider.OPENAI, api_key="mock_openai_key", model="gpt-4")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("OpenAIAdapter: conexión exitosa (mock)")
        return True

    def generate(self, request: AIRequest) -> AIResponse:
        self._ensure_connected()
        model = request.model or self.config.model
        return AIResponse(
            id=f"openai_{_uuid.uuid4().hex[:12]}", content="Respuesta mock de OpenAI GPT-4 para Likida AI.",
            model=model, usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            finish_reason="stop",
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self._ensure_connected()
        model = request.model or "text-embedding-ada-002"
        return EmbeddingResponse(embedding=[0.1] * 1536, model=model, dimensions=1536)
