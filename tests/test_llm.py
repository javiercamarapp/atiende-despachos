# -*- coding: utf-8 -*-
"""Tests del servicio LLM (FASE 4): clasificación, extracción, resumen,
anomalías, fallback a reglas y proveedores configurados por env."""
import os

import pytest

from b2b_ai.services.llm import (LLMService, MockLLM, LLMError,
                                  OpenAIProvider, AnthropicProvider,
                                  DeepSeekProvider, get_llm, PROMPTS)


@pytest.fixture
def datos(parsed_consultoria):
    return parsed_consultoria


# ---- tareas principales ------------------------------------------------
def test_classify_invoice_usando_llm(datos):
    svc = LLMService(client=MockLLM())
    r = svc.classify_invoice(datos)
    assert r["source"] == "llm"
    assert r["categoria"] == "inversion"
    assert 0 <= r["confianza"] <= 1
    assert "requires_human_review" in r
    assert svc.last_source == "llm"


def test_extract_data(datos):
    svc = LLMService(client=MockLLM())
    r = svc.extract_data(datos)
    assert r["source"] == "llm"
    assert r["total"] is not None
    assert r["emisor_rfc"]
    # los montos se normalizan a str
    assert isinstance(r["total"], str)


def test_summarize(datos):
    svc = LLMService(client=MockLLM())
    s = svc.summarize(datos)
    assert isinstance(s, str) and len(s) > 5
    assert svc.last_source == "llm"


def test_detect_anomaly_normal(datos):
    svc = LLMService(client=MockLLM())
    r = svc.detect_anomaly(datos)
    assert r["source"] == "llm"
    assert r["nivel"] in ("normal", "alerta")
    assert isinstance(r["anomalias"], list)


def test_detect_anomaly_alerta():
    from b2b_ai.services.llm import LLMService, MockLLM
    malo = {"tipo": "I", "subtotal": "100", "iva": "-5", "total": "95"}
    r = LLMService(client=MockLLM()).detect_anomaly(malo)
    assert r["nivel"] == "alerta"
    assert any("negativo" in a for a in r["anomalias"])


# ---- fallback a reglas --------------------------------------------------
def test_fallback_cuando_llm_falla(datos):
    m = MockLLM()
    m.fail_next = True
    svc = LLMService(client=m)
    r = svc.classify_invoice(datos)
    assert r["source"] == "rules"
    assert r["categoria"] == "inversion"
    assert svc.last_source == "rules"


def test_fallback_por_error_rate(datos):
    svc = LLMService(client=MockLLM(error_rate=1.0))
    r = svc.classify_invoice(datos)
    assert r["source"] == "rules"


def test_fallback_respuesta_no_json(datos):
    class Roto:
        def complete(self, messages, temperature=0.0, max_tokens=512):
            return "esto no es json"
    svc = LLMService(client=Roto())
    r = svc.classify_invoice(datos)
    assert r["source"] == "rules"


def test_fallback_respuesta_vacia(datos):
    class Vacio:
        def complete(self, messages, temperature=0.0, max_tokens=512):
            return ""
    svc = LLMService(client=Vacio())
    assert svc.summarize(datos)  # no lanza


# ---- categoría inválida se normaliza a desconocido ----------------------
def test_categoria_invalida_normaliza_a_desconocido(datos):
    class Raro:
        def complete(self, messages, temperature=0.0, max_tokens=512):
            import json
            return json.dumps({"categoria": "no-existe", "confianza": 0.9,
                               "razon": "x"})
    svc = LLMService(client=Raro())
    r = svc.classify_invoice(datos)
    assert r["categoria"] == "desconocido"
    assert r["requires_human_review"] is True


# ---- proveedores y fábrica ---------------------------------------------
def test_proveedores_requieren_key(monkeypatch):
    for env in ("B2B_OPENAI_API_KEY", "B2B_ANTHROPIC_API_KEY",
                "B2B_DEEPSEEK_API_KEY", "B2B_LLM_PROVIDER"):
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(LLMError):
        OpenAIProvider(api_key="")
    with pytest.raises(LLMError):
        AnthropicProvider(api_key="")
    with pytest.raises(LLMError):
        DeepSeekProvider(api_key="")


def test_get_llm_default_es_mock(monkeypatch):
    monkeypatch.delenv("B2B_LLM_PROVIDER", raising=False)
    assert isinstance(get_llm(), MockLLM)


def test_get_llm_respeta_env(monkeypatch):
    monkeypatch.setenv("B2B_LLM_PROVIDER", "openai")
    monkeypatch.setenv("B2B_OPENAI_API_KEY", "sk-test")
    assert isinstance(get_llm(), OpenAIProvider)


def test_prompt_templates_existen():
    for t in ("classify", "extract", "summarize", "anomaly"):
        assert "system" in PROMPTS[t] and "user" in PROMPTS[t]
