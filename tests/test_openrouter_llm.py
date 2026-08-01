# -*- coding: utf-8 -*-
"""Tests para OpenRouterLLM — LLM real via OpenRouter (DeepSeek V4 Flash por defecto).

Mockeamos HTTP para no depender de red real ni API keys.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from b2b_ai.services.llm import (
    LLMService, LLMError, OpenRouterLLM, get_llm, MockLLM,
)


class TestOpenRouterLLMUnit:
    """Tests unitarios directos sobre OpenRouterLLM (sin LLMService)."""

    def test_requiere_api_key(self):
        """Sin API key debe lanzar LLMError."""
        with pytest.raises(LLMError, match="OpenRouter"):
            OpenRouterLLM(api_key="")

    def test_url_y_modelo_default(self):
        """Default debe apuntar a OpenRouter con deepseek/deepseek-v4-flash."""
        llm = OpenRouterLLM(api_key="sk-test-or")
        assert "openrouter.ai" in llm.base_url
        assert "deepseek/deepseek-v4-flash" in llm.model

    def test_complete_exitoso(self):
        """complete() debe parsear la respuesta JSON correctamente."""
        fake_response = {
            "choices": [{"message": {"content": "{\"categoria\": \"inversion\", \"confianza\": 0.95}"}}]
        }
        llm = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(llm, "_post") as mock_post:
            mock_post.return_value = fake_response
            result = llm.complete([
                {"role": "system", "content": "Eres un contador."},
                {"role": "user", "content": "Clasifica esta factura."},
            ])
        assert result == '{"categoria": "inversion", "confianza": 0.95}'
        mock_post.assert_called_once()

    def test_complete_envia_model_correcto(self):
        """Debe enviar el modelo configurado en el body."""
        fake_response = {
            "choices": [{"message": {"content": "respuesta"}}]
        }
        llm = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(llm, "_post") as mock_post:
            mock_post.return_value = fake_response
            llm.complete([{"role": "user", "content": "hola"}])
            args, _ = mock_post.call_args
            body = args[2]
            assert body["model"] == "deepseek/deepseek-v4-flash"

    def test_complete_maneja_error_http(self):
        """HTTP error debe lanzar LLMError."""
        llm = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(llm, "_post") as mock_post:
            mock_post.side_effect = LLMError("HTTP 402 de OpenRouter: ...")
            with pytest.raises(LLMError, match="OpenRouter"):
                llm.complete([{"role": "user", "content": "x"}])

    def test_modelo_configurable_via_env(self, monkeypatch):
        """El modelo debe poder cambiarse via B2B_LLM_MODEL."""
        monkeypatch.setenv("B2B_LLM_MODEL", "anthropic/claude-sonnet-5")
        llm = OpenRouterLLM(api_key="sk-test-or")
        assert llm.model == "anthropic/claude-sonnet-5"

    def test_base_url_configurable_via_env(self, monkeypatch):
        """La base URL debe poder cambiarse via B2B_LLM_BASE_URL."""
        monkeypatch.setenv("B2B_LLM_BASE_URL", "https://proxy.mi-gateway.com/v1")
        llm = OpenRouterLLM(api_key="sk-test-or")
        assert "proxy.mi-gateway.com" in llm.base_url

    def test_headers_incluyen_referer(self):
        """Debe enviar HTTP-Referer y X-Title para OpenRouter."""
        fake_response = {"choices": [{"message": {"content": "ok"}}]}
        llm = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(llm, "_post") as mock_post:
            mock_post.return_value = fake_response
            llm.complete([{"role": "user", "content": "hola"}])
            args, _ = mock_post.call_args
            headers = args[1]
            assert "HTTP-Referer" in headers
            assert "X-Title" in headers


class TestOpenRouterLLMEnLLMService:
    """OpenRouterLLM integrado en LLMService (con mocking de HTTP)."""

    def test_classify_invoice(self):
        """classify_invoice debe retornar clasificación desde OpenRouter."""
        fake = {"choices": [{"message": {"content": json.dumps({
            "categoria": "inversion", "confianza": 0.95, "razon": "servicios profesionales"
        })}}]}
        client = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(client, "_post", return_value=fake):
            svc = LLMService(client=client)
            r = svc.classify_invoice({
                "emisor_nombre": "Consultoría SA",
                "total": "5000",
                "tipo": "I",
            })
        assert r["source"] == "llm"
        assert r["categoria"] == "inversion"
        assert r["confianza"] == 0.95
        assert svc.last_source == "llm"

    def test_fallback_a_rules_si_llm_falla(self):
        """Si OpenRouter falla, LLMService debe caer a reglas."""
        client = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(client, "_post", side_effect=LLMError("HTTP 500 de OpenRouter")):
            svc = LLMService(client=client)
            r = svc.classify_invoice({
                "emisor_nombre": "Consultoría SA",
                "total": "5000",
                "tipo": "I",
            })
        assert r["source"] == "rules"
        assert svc.last_source == "rules"

    def test_extract_data(self):
        """extract_data debe funcionar con OpenRouter."""
        fake = {"choices": [{"message": {"content": json.dumps({
            "emisor_rfc": "XAXX010101000", "total": "1000",
            "subtotal": "862.07", "iva": "137.93",
        })}}]}
        client = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(client, "_post", return_value=fake):
            svc = LLMService(client=client)
            r = svc.extract_data({"emisor_nombre": "Demo"})
        assert r["source"] == "llm"
        assert r["emisor_rfc"] == "XAXX010101000"

    def test_summarize(self):
        """summarize debe funcionar con OpenRouter."""
        fake = {"choices": [{"message": {"content": "Factura de Demo por 1000."}}]}
        client = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(client, "_post", return_value=fake):
            svc = LLMService(client=client)
            s = svc.summarize({"emisor_nombre": "Demo", "total": "1000"})
        assert "Demo" in s
        assert svc.last_source == "llm"

    def test_detect_anomaly(self):
        """detect_anomaly debe funcionar con OpenRouter."""
        fake = {"choices": [{"message": {"content": json.dumps({
            "anomalias": ["IVA no coincide con 16%"],
            "nivel": "alerta",
        })}}]}
        client = OpenRouterLLM(api_key="sk-test-or")
        with patch.object(client, "_post", return_value=fake):
            svc = LLMService(client=client)
            r = svc.detect_anomaly({"tipo": "I", "subtotal": "100", "iva": "0", "total": "100"})
        assert r["source"] == "llm"
        assert r["nivel"] == "alerta"
        assert len(r["anomalias"]) > 0


class TestGetLLM:
    """Tests para la fábrica get_llm con OpenRouter."""

    def test_get_llm_mock_por_defecto(self, monkeypatch):
        monkeypatch.delenv("B2B_LLM_PROVIDER", raising=False)
        assert isinstance(get_llm(), MockLLM)

    def test_get_llm_openrouter_por_env(self, monkeypatch):
        monkeypatch.setenv("B2B_LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("B2B_OPENROUTER_API_KEY", "sk-test-or")
        assert isinstance(get_llm(), OpenRouterLLM)

    def test_get_llm_openrouter_sin_key_cae_a_mock(self, monkeypatch):
        monkeypatch.setenv("B2B_LLM_PROVIDER", "openrouter")
        monkeypatch.delenv("B2B_OPENROUTER_API_KEY", raising=False)
        assert isinstance(get_llm(), MockLLM)