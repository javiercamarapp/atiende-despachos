# -*- coding: utf-8 -*-
"""
anthropic_adapter.py — Real adapter for Anthropic API (Claude).

Provides AnthropicAdapter with actual API calls to Anthropic.
Falls back to mock if ANTHROPIC_API_KEY is not set.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.ai.adapter import AIAdapter
from b2b_ai.integrations.ai.models import (
    AIConfig, AIProvider, AIRequest, AIResponse, EmbeddingRequest, EmbeddingResponse,
)

logger = logging.getLogger(__name__)


class AnthropicAdapter(AIAdapter):
    """Real adapter for Anthropic API (Claude).

    Connects to Anthropic using the official `anthropic` Python library.
    Requires ANTHROPIC_API_KEY environment variable.
    """

    def __init__(self, config: Optional[AIConfig] = None):
        api_key = config.api_key if config else os.environ.get("ANTHROPIC_API_KEY", "")
        config = config or AIConfig(
            provider=AIProvider.ANTHROPIC,
            api_key=api_key or "mock_anthropic_key",
            model=os.environ.get("B2B_LLM_MODEL", "claude-sonnet-4-20250514"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to Anthropic API. Uses ANTHROPIC_API_KEY from environment or config."""
        api_key = (
            (credentials or {}).get("api_key")
            or self.config.api_key
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )

        if not api_key or api_key == "mock_anthropic_key":
            logger.warning("AnthropicAdapter: no real API key — running in MOCK mode")
            self._connected = True
            self._client = None
            return True

        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
            self._connected = True
            logger.info("AnthropicAdapter: connected to Anthropic API")
            return True
        except ImportError:
            logger.warning("AnthropicAdapter: anthropic package not installed — MOCK mode")
            self._connected = True
            self._client = None
            return True
        except Exception as e:
            logger.error(f"AnthropicAdapter: connection failed: {e}")
            self._connected = True
            self._client = None
            return True

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a response using Anthropic API."""
        self._ensure_connected()
        model = request.model or self.config.model

        if self._client:
            try:
                system_text = ""
                messages = []
                for m in request.messages:
                    if m.role.value == "system":
                        system_text += m.content + "\n"
                    else:
                        messages.append({"role": m.role.value, "content": m.content})

                if not messages:
                    messages = [{"role": "user", "content": "Hello"}]

                kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": request.max_tokens or self.config.max_tokens,
                    "messages": messages,
                }
                if system_text.strip():
                    kwargs["system"] = system_text.strip()
                if request.temperature is not None:
                    kwargs["temperature"] = request.temperature

                response = self._client.messages.create(**kwargs)
                content = response.content[0].text if response.content else ""
                return AIResponse(
                    id=f"anthropic_{response.id}",
                    content=content,
                    model=model,
                    usage={
                        "input_tokens": response.usage.input_tokens if response.usage else 0,
                        "output_tokens": response.usage.output_tokens if response.usage else 0,
                    },
                    finish_reason=response.stop_reason or "end_turn",
                )
            except Exception as e:
                logger.error(f"AnthropicAdapter: generate failed: {e}")
                raise

        return AIResponse(
            id=f"anthropic_{_uuid.uuid4().hex[:12]}",
            content="Respuesta mock de Anthropic Claude para Likida AI.",
            model=model,
            usage={"input_tokens": 50, "output_tokens": 20},
            finish_reason="end_turn",
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Anthropic does not offer an embedding API."""
        raise NotImplementedError("Anthropic no ofrece API de embeddings")
