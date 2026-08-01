# -*- coding: utf-8 -*-
"""
Boost coverage for b2b_ai/services/llm.py.

Targets uncovered lines:
  - _http_post_json error paths (342-353)
  - OpenAIProvider.complete (370-376)
  - DeepSeekProvider.complete (393-399)
  - AnthropicProvider.complete (417-430)
  - MockLLM edge cases (488, 499, 509-512, 522, 527-530)
  - OpenRouterLLM._post + __repr__ (557, 572)
  - _rule_anomalies error path (610-611)
  - LLMService._run_json non-dict response (664)
  - LLMService.detect_anomaly non-list anomalias (743, 749-753)
  - main() (757-769, 773)
"""
from __future__ import annotations

import json
import sys
import os
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from b2b_ai.services.llm import (
    LLMService, MockLLM, LLMError,
    OpenAIProvider, AnthropicProvider, DeepSeekProvider, OpenRouterLLM,
    _http_post_json, _parse_json, _rule_anomalies, _extract_datos,
    _task_of, get_llm, CATEGORIA_NOMBRE,
    main as llm_main,
)


@pytest.fixture
def parsed_cfdi(sample_consultoria):
    from b2b_ai.cfdi.parser import parse_cfdi
    return parse_cfdi(sample_consultoria)


# ---------------------------------------------------------------------------
# _http_post_json error paths  (lines 342-353)
# ---------------------------------------------------------------------------
class TestHttpPostJson:
    def test_invalid_scheme_raises(self):
        """file:// scheme should be rejected (SSRF protection, line 340-341)."""
        with pytest.raises(LLMError, match="Esquema de URL no permitido"):
            _http_post_json(
                "file:///etc/passwd",
                {},
                {"test": 1}
            )

    def test_ftp_scheme_raises(self):
        with pytest.raises(LLMError, match="Esquema de URL no permitido"):
            _http_post_json("ftp://example.com", {}, {})


# ---------------------------------------------------------------------------
# OpenAIProvider.complete  (lines 370-376)
# ---------------------------------------------------------------------------
class TestOpenAIProvider:
    def test_complete_calls_http_post(self):
        """Exercise OpenAIProvider.complete with mocked _http_post_json."""
        provider = OpenAIProvider(api_key="test-key")
        fake_response = {
            "choices": [{"message": {"content": "hello from openai"}}]
        }
        with patch("b2b_ai.services.llm._http_post_json", return_value=fake_response) as mock_post:
            result = provider.complete(
                [{"role": "user", "content": "hi"}],
                temperature=0.5,
                max_tokens=100
            )
            assert result == "hello from openai"
            mock_post.assert_called_once()

    def test_init_raises_without_key(self):
        """OpenAIProvider requires API key."""
        env_backup = os.environ.pop("B2B_OPENAI_API_KEY", None)
        try:
            with pytest.raises(LLMError, match="requiere"):
                OpenAIProvider(api_key="")
        finally:
            if env_backup:
                os.environ["B2B_OPENAI_API_KEY"] = env_backup


# ---------------------------------------------------------------------------
# DeepSeekProvider.complete  (lines 393-399)
# ---------------------------------------------------------------------------
class TestDeepSeekProvider:
    def test_complete_calls_http_post(self):
        provider = DeepSeekProvider(api_key="test-key")
        fake_response = {
            "choices": [{"message": {"content": "hello from deepseek"}}]
        }
        with patch("b2b_ai.services.llm._http_post_json", return_value=fake_response) as mock_post:
            result = provider.complete(
                [{"role": "user", "content": "hi"}]
            )
            assert result == "hello from deepseek"
            mock_post.assert_called_once()

    def test_init_raises_without_key(self):
        env_backup = os.environ.pop("B2B_DEEPSEEK_API_KEY", None)
        try:
            with pytest.raises(LLMError, match="requiere"):
                DeepSeekProvider(api_key="")
        finally:
            if env_backup:
                os.environ["B2B_DEEPSEEK_API_KEY"] = env_backup


# ---------------------------------------------------------------------------
# AnthropicProvider.complete  (lines 417-430)
# ---------------------------------------------------------------------------
class TestAnthropicProvider:
    def test_complete_separates_system_and_user(self):
        provider = AnthropicProvider(api_key="test-key")
        fake_response = {
            "content": [{"type": "text", "text": "hello from anthropic"}]
        }
        with patch("b2b_ai.services.llm._http_post_json", return_value=fake_response) as mock_post:
            messages = [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hi"},
            ]
            result = provider.complete(messages, max_tokens=200)
            assert result == "hello from anthropic"
            # Verify the call was made
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            # Check that the body contains system message
            body = call_args[0][2]  # third positional arg
            assert "system" in body

    def test_init_raises_without_key(self):
        env_backup = os.environ.pop("B2B_ANTHROPIC_API_KEY", None)
        try:
            with pytest.raises(LLMError, match="requiere"):
                AnthropicProvider(api_key="")
        finally:
            if env_backup:
                os.environ["B2B_ANTHROPIC_API_KEY"] = env_backup


# ---------------------------------------------------------------------------
# OpenRouterLLM._post + __repr__  (lines 557, 572)
# ---------------------------------------------------------------------------
class TestOpenRouterLLM:
    def test_post_delegates_to_http_post(self):
        """OpenRouterLLM._post should call _http_post_json (line 557)."""
        provider = OpenRouterLLM(api_key="test-key")
        fake_response = {
            "choices": [{"message": {"content": "hello from openrouter"}}]
        }
        with patch("b2b_ai.services.llm._http_post_json", return_value=fake_response) as mock_post:
            result = provider._post("http://example.com", {}, {})
            assert result == fake_response
            mock_post.assert_called_once()

    def test_repr(self):
        """__repr__ returns a string with the model name (line 572)."""
        provider = OpenRouterLLM(api_key="test-key")
        r = repr(provider)
        assert "OpenRouterLLM" in r
        assert provider.model in r

    def test_complete(self):
        provider = OpenRouterLLM(api_key="test-key")
        fake_response = {
            "choices": [{"message": {"content": "openrouter reply"}}]
        }
        with patch.object(provider, "_post", return_value=fake_response):
            result = provider.complete([{"role": "user", "content": "test"}])
            assert result == "openrouter reply"

    def test_init_raises_without_key(self):
        env_backup = os.environ.pop("B2B_OPENROUTER_API_KEY", None)
        try:
            with pytest.raises(LLMError, match="requiere"):
                OpenRouterLLM(api_key="")
        finally:
            if env_backup:
                os.environ["B2B_OPENROUTER_API_KEY"] = env_backup


# ---------------------------------------------------------------------------
# MockLLM edge cases  (lines 488, 499, 509-512, 522, 527-530)
# ---------------------------------------------------------------------------
class TestMockLLMEdgeCases:
    def test_respond_unknown_task(self):
        """Unknown task returns generic OK JSON (line 488)."""
        mock = MockLLM()
        result = mock._respond("unknown_task", {})
        data = json.loads(result)
        assert data == {"resultado": "ok"}

    def test_classify_invoice_invalid_category(self):
        """If classify returns unknown category, it becomes 'desconocido' (line 499)."""
        mock = MockLLM()
        # Override _respond to return invalid category
        original = mock._respond

        def bad_respond(task, datos):
            if task == "classify":
                return json.dumps({"categoria": "nonexistent_cat", "confianza": 0.9, "razon": "test"})
            return original(task, datos)

        mock._respond = bad_respond
        result = mock.classify_invoice({
            "conceptos": [{"descripcion": "test"}],
            "claves_prod_serv": [],
        })
        assert result["categoria"] == "desconocido"

    def test_classify_invoice_exception_fallback(self):
        """If _respond raises, classify_invoice catches and returns rules-based (lines 509-512)."""
        mock = MockLLM()
        mock._respond = MagicMock(side_effect=LLMError("boom"))
        result = mock.classify_invoice({
            "conceptos": [{"descripcion": "renta de oficina"}],
            "claves_prod_serv": [],
        })
        assert result["source"] == "rules"

    def test_detect_anomaly_non_list_anomalias(self):
        """When anomalias is not a list, wrap it in a list (line 522)."""
        mock = MockLLM()
        original = mock._respond

        def bad_respond(task, datos):
            if task == "anomaly":
                return json.dumps({"anomalias": "single_anomaly_string", "nivel": "alerta"})
            return original(task, datos)

        mock._respond = bad_respond
        result = mock.detect_anomaly({
            "tipo": "I", "subtotal": "100", "iva": "16", "total": "116"
        })
        assert isinstance(result["anomalias"], list)
        assert result["source"] == "llm"

    def test_detect_anomaly_exception_fallback(self):
        """If _respond raises, detect_anomaly catches and returns rules (lines 527-530)."""
        mock = MockLLM()
        mock._respond = MagicMock(side_effect=LLMError("boom"))
        result = mock.detect_anomaly({
            "tipo": "I", "subtotal": "100", "iva": "16", "total": "116"
        })
        assert result["source"] == "rules"
        assert "anomalias" in result


# ---------------------------------------------------------------------------
# _rule_anomalies error path  (lines 610-611)
# ---------------------------------------------------------------------------
class TestRuleAnomalies:
    def test_non_numeric_montos(self):
        """Non-numeric values trigger TypeError/ValueError catch (line 610-611)."""
        result = _rule_anomalies({
            "subtotal": "not_a_number",
            "iva": "also_not",
            "total": "still_not",
            "tipo": "I"
        })
        assert any("Montos no numéricos" in a for a in result["anomalias"])

    def test_atypical_tipo(self):
        """Atypical TipoDeComprobante triggers warning (line 612-613)."""
        result = _rule_anomalies({
            "subtotal": "100", "iva": "16", "total": "116", "tipo": "X"
        })
        assert any("atípico" in a for a in result["anomalias"])

    def test_nomina_no_iva_check(self):
        """TipoDeComprobante=N should not trigger IVA check (line 604-605)."""
        result = _rule_anomalies({
            "subtotal": "1000", "iva": "0", "total": "1000", "tipo": "N"
        })
        assert not any("IVA" in a for a in result["anomalias"])


# ---------------------------------------------------------------------------
# LLMService._run_json non-dict response  (line 664)
# ---------------------------------------------------------------------------
class TestLLMServiceRunJson:
    def test_non_dict_json_raises(self):
        """_run_json should raise LLMError if response is not a dict (line 664)."""

        class ListReturningLLM:
            name = "test"
            def complete(self, messages, temperature=0.0, max_tokens=512):
                return json.dumps([1, 2, 3])  # Returns a list, not dict

        svc = LLMService(client=ListReturningLLM())
        with pytest.raises(LLMError, match="no es objeto JSON"):
            svc._run_json("classify", {})

    def test_empty_response_raises(self):
        """Empty response should raise LLMError."""

        class EmptyLLM:
            name = "test"
            def complete(self, messages, temperature=0.0, max_tokens=512):
                return ""

        svc = LLMService(client=EmptyLLM())
        with pytest.raises(LLMError, match="vacía"):
            svc._run("classify", {})


# ---------------------------------------------------------------------------
# LLMService.detect_anomaly non-list anomalias  (line 743, 749-753)
# ---------------------------------------------------------------------------
class TestLLMServiceAnomaly:
    def test_non_list_anomalias_wrapped(self):
        """When LLM returns non-list anomalias, wrap in list (line 743)."""

        class WeirdAnomalyLLM:
            name = "test"
            def complete(self, messages, temperature=0.0, max_tokens=512):
                return json.dumps({"anomalias": "not_a_list", "nivel": "alerta"})

        svc = LLMService(client=WeirdAnomalyLLM())
        result = svc.detect_anomaly({
            "tipo": "I", "subtotal": "100", "iva": "16", "total": "116"
        })
        assert isinstance(result["anomalias"], list)
        assert result["source"] == "llm"

    def test_anomaly_exception_fallback(self):
        """LLMService.detect_anomaly falls back to rules on exception (lines 749-753)."""
        class FailingLLM:
            name = "test"
            def complete(self, messages, temperature=0.0, max_tokens=512):
                raise LLMError("test failure")

        svc = LLMService(client=FailingLLM())
        result = svc.detect_anomaly({
            "tipo": "I", "subtotal": "100", "iva": "16", "total": "116"
        })
        assert result["source"] == "rules"
        assert svc.last_source == "rules"

    def test_anomaly_level_inferred_from_anomalias(self):
        """When LLM returns invalid nivel, infer from anomalias list (line 744-745)."""

        class BadLevelLLM:
            name = "test"
            def complete(self, messages, temperature=0.0, max_tokens=512):
                return json.dumps({
                    "anomalias": ["something wrong"],
                    "nivel": "invalid_level"
                })

        svc = LLMService(client=BadLevelLLM())
        result = svc.detect_anomaly({
            "tipo": "I", "subtotal": "100", "iva": "16", "total": "116"
        })
        assert result["nivel"] == "alerta"  # inferred from non-empty anomalias


# ---------------------------------------------------------------------------
# get_llm factory  (lines 575-589)
# ---------------------------------------------------------------------------
class TestGetLLM:
    def test_get_llm_openai(self):
        with patch.dict(os.environ, {"B2B_OPENAI_API_KEY": "key"}):
            llm = get_llm("openai")
            assert isinstance(llm, OpenAIProvider)

    def test_get_llm_anthropic(self):
        with patch.dict(os.environ, {"B2B_ANTHROPIC_API_KEY": "key"}):
            llm = get_llm("anthropic")
            assert isinstance(llm, AnthropicProvider)

    def test_get_llm_deepseek(self):
        with patch.dict(os.environ, {"B2B_DEEPSEEK_API_KEY": "key"}):
            llm = get_llm("deepseek")
            assert isinstance(llm, DeepSeekProvider)

    def test_get_llm_openrouter(self):
        with patch.dict(os.environ, {"B2B_OPENROUTER_API_KEY": "key"}):
            llm = get_llm("openrouter")
            assert isinstance(llm, OpenRouterLLM)

    def test_get_llm_openrouter_fallback(self):
        """If OpenRouter fails (no key), falls back to MockLLM."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("B2B_OPENROUTER_API_KEY", None)
            llm = get_llm("openrouter")
            assert isinstance(llm, MockLLM)

    def test_get_llm_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("B2B_LLM_PROVIDER", None)
            llm = get_llm()
            assert isinstance(llm, MockLLM)

    def test_get_llm_case_insensitive(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("B2B_LLM_PROVIDER", None)
            llm = get_llm("Mock")
            assert isinstance(llm, MockLLM)


# ---------------------------------------------------------------------------
# main()  (lines 757-769, 773)
# ---------------------------------------------------------------------------
class TestLLMMain:
    def test_main_with_fixture(self, fixture_dir, parsed_cfdi):
        """main() with a CFDI file."""
        xml_path = os.path.join(fixture_dir, "01_gasto_operativo_papeleria.xml")
        with patch("sys.argv", ["llm", xml_path]):
            captured = StringIO()
            sys.stdout = captured
            try:
                llm_main()
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            assert "Cliente" in output
            assert "Clasif" in output

    def test_main_without_args(self):
        """main() without args uses demo data."""
        with patch("sys.argv", ["llm"]):
            captured = StringIO()
            sys.stdout = captured
            try:
                llm_main()
            finally:
                sys.stdout = sys.__stdout__
            output = captured.getvalue()
            assert "Cliente" in output


# ---------------------------------------------------------------------------
# _parse_json and _extract_datos helpers
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_parse_json_dict(self):
        result = _parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_json_bytes(self):
        result = _parse_json(b'{"a": 1}')
        assert result == {"a": 1}

    def test_parse_json_non_dict(self):
        result = _parse_json('[1,2,3]')
        assert result == {}

    def test_parse_json_invalid(self):
        result = _parse_json("not json")
        assert result == {}

    def test_extract_datos(self):
        prompt = "[TASK:classify]\n[DATOS]{\"total\": \"100\"}[/DATOS]"
        result = _extract_datos(prompt)
        assert result["total"] == "100"

    def test_extract_datos_no_match(self):
        result = _extract_datos("no datos here")
        assert result == {}

    def test_extract_datos_invalid_json(self):
        result = _extract_datos("[DATOS]not-json[/DATOS]")
        assert "_raw" in result

    def test_task_of(self):
        assert _task_of("[TASK:classify]") == "classify"
        assert _task_of("no task") == "unknown"
