# -*- coding: utf-8 -*-
"""
anthropic_adapter.py — Adaptador mock para Anthropic API (Claude).
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


class AnthropicAdapter(AIAdapter):
    """Adaptador mock para Anthropic API (Claude)."""

    def __init__(self, config: Optional[AIConfig] = None):
        config = config or AIConfig(provider=AIProvider.ANTHROPIC, api_key="mock_anthropic_key",
                                    model="claude-sonnet-4-20250514")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        logger.info("AnthropicAdapter: conexión exitosa (mock)")
        return True

    def generate(self, request: AIRequest) -> AIResponse:
        self._ensure_connected()
        model = request.model or self.config.model
        return AIResponse(
            id=f"anthropic_{_uuid.uuid4().hex[:12]}", content="Respuesta mock de Anthropic Claude para Likida AI.",
            model=model, usage={"input_tokens": 50, "output_tokens": 20},
            finish_reason="end_turn",
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self._ensure_connected()
        raise NotImplementedError("Anthropic no ofrece API de embeddings")
