# -*- coding: utf-8 -*-
"""
openai_adapter.py — Real adapter for OpenAI API.

Provides OpenAIAdapter with actual API calls to OpenAI.
Falls back to mock if OPENAI_API_KEY is not set.
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


class OpenAIAdapter(AIAdapter):
    """Real adapter for OpenAI API.

    Connects to OpenAI using the official `openai` Python library.
    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, config: Optional[AIConfig] = None):
        api_key = config.api_key if config else os.environ.get("OPENAI_API_KEY", "")
        config = config or AIConfig(
            provider=AIProvider.OPENAI,
            api_key=api_key or "mock_openai_key",
            model=os.environ.get("B2B_LLM_MODEL", "gpt-4o-mini"),
        )
        super().__init__(config=config)
        self._client = None

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to OpenAI API. Uses OPENAI_API_KEY from environment or config."""
        api_key = (
            (credentials or {}).get("api_key")
            or self.config.api_key
            or os.environ.get("OPENAI_API_KEY", "")
        )

        if not api_key or api_key == "mock_openai_key":
            logger.warning("OpenAIAdapter: no real API key — running in MOCK mode")
            self._connected = True
            self._client = None
            return True

        try:
            import openai
            self._client = openai.OpenAI(api_key=api_key)
            self._client.models.list()
            self._connected = True
            logger.info("OpenAIAdapter: connected to OpenAI API")
            return True
        except ImportError:
            logger.warning("OpenAIAdapter: openai package not installed — MOCK mode")
            self._connected = True
            self._client = None
            return True
        except Exception as e:
            logger.error(f"OpenAIAdapter: connection failed: {e}")
            self._connected = True
            self._client = None
            return True

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a response using OpenAI API."""
        self._ensure_connected()
        model = request.model or self.config.model

        if self._client:
            try:
                messages = [{"role": m.role.value, "content": m.content} for m in request.messages]
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": request.max_tokens or self.config.max_tokens,
                    "temperature": request.temperature if request.temperature is not None else self.config.temperature,
                }
                if request.stop:
                    kwargs["stop"] = request.stop

                response = self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                return AIResponse(
                    id=f"openai_{response.id}",
                    content=choice.message.content or "",
                    model=response.model,
                    usage={
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    },
                    finish_reason=choice.finish_reason or "stop",
                )
            except Exception as e:
                logger.error(f"OpenAIAdapter: generate failed: {e}")
                raise

        return AIResponse(
            id=f"openai_{_uuid.uuid4().hex[:12]}",
            content="Respuesta mock de OpenAI GPT-4 para Likida AI.",
            model=model,
            usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            finish_reason="stop",
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Generate embeddings using OpenAI API."""
        self._ensure_connected()
        model = request.model or "text-embedding-ada-002"

        if self._client:
            try:
                response = self._client.embeddings.create(model=model, input=request.input_text)
                embedding = response.data[0].embedding
                return EmbeddingResponse(embedding=embedding, model=model, dimensions=len(embedding))
            except Exception as e:
                logger.error(f"OpenAIAdapter: embed failed: {e}")
                raise

        return EmbeddingResponse(embedding=[0.1] * 1536, model=model, dimensions=1536)
