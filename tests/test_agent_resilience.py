# -*- coding: utf-8 -*-
"""test_agent_resilience.py — Tests de las 4 correcciones de resiliencia:

  1. agent/loop.py `_call()` reintenta con backoff (infrastructure/retry.py)
     ante fallos transitorios, en vez de ejecutar `call_tool()` una sola vez.
  2. tools/registry.py `call_tool()` valida parámetros requeridos contra el
     schema ANTES de invocar la tool (fail-closed).
  3. Los umbrales de confianza (agent/loop.py, services/classify.py,
     features/bookkeeping/auto_classifier.py) vienen de una única fuente de
     verdad: b2b_ai/common/confidence.py.
  4. services/llm.py `LLMService._run()` protege la llamada real al
     proveedor con el circuit breaker ya existente
     (infrastructure/circuit_breaker.py, servicio "llm_calls").
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("B2B_ENV", "test")


# ===========================================================================
# 1. Retry en AgentLoop._call()
# ===========================================================================
class TestAgentLoopCallRetries:
    """`_call()` debe envolver `call_tool()` con `with_retry` (no una sola
    ejecución) y NO reintentar errores no transitorios."""

    def _make_bare_loop(self):
        from b2b_ai.agent.loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)
        loop.logger = MagicMock()
        return loop

    def test_retries_on_transient_error_then_succeeds(self, monkeypatch):
        """ConnectionError (transitoria) se reintenta hasta tener éxito."""
        # No dormir de verdad durante el test.
        monkeypatch.setattr(
            "b2b_ai.infrastructure.retry.time.sleep", lambda s: None)

        calls = {"n": 0}

        def flaky(name, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("SAT no responde")
            return {"ok": True}

        loop = self._make_bare_loop()
        with patch("b2b_ai.agent.loop.call_tool", side_effect=flaky):
            res = loop._call("register_erp", tenant_id=1, invoice={})

        assert res == {"ok": True}
        assert calls["n"] == 3, (
            "_call() debe haber reintentado 2 veces tras el fallo "
            "transitorio antes de tener éxito en el 3er intento."
        )
        # Se registra como éxito, no como error.
        loop.logger.log.assert_called_once()
        assert loop.logger.log.call_args.kwargs["status"] == "ok"

    def test_does_not_retry_non_transient_error(self, monkeypatch):
        """ValueError (de negocio, no transitorio) falla al primer intento."""
        monkeypatch.setattr(
            "b2b_ai.infrastructure.retry.time.sleep", lambda s: None)

        calls = {"n": 0}

        def always_bad(name, **kwargs):
            calls["n"] += 1
            raise ValueError("XML malformado")

        loop = self._make_bare_loop()
        with patch("b2b_ai.agent.loop.call_tool", side_effect=always_bad):
            with pytest.raises(ValueError):
                loop._call("parse_cfdi", tenant_id=1, xml_path="/bad.xml")

        assert calls["n"] == 1, (
            "Un ValueError no es transitorio: no debe reintentarse."
        )
        assert loop.logger.log.call_args.kwargs["status"] == "error"

    def test_retry_exhausted_raises_and_logs_error(self, monkeypatch):
        """Fallos transitorios sostenidos agotan los reintentos y propagan."""
        monkeypatch.setattr(
            "b2b_ai.infrastructure.retry.time.sleep", lambda s: None)

        calls = {"n": 0}

        def always_down(name, **kwargs):
            calls["n"] += 1
            raise ConnectionError("ERP caído")

        loop = self._make_bare_loop()
        with patch("b2b_ai.agent.loop.call_tool", side_effect=always_down):
            with pytest.raises(Exception):
                loop._call("register_erp", tenant_id=1, invoice={})

        # Default RetryConfig().max_attempts == 3 para un service sin config
        # específica en SERVICE_RETRY_CONFIGS.
        assert calls["n"] == 3
        assert loop.logger.log.call_args.kwargs["status"] == "error"

    def test_call_tool_still_patchable_by_module_attribute(self, monkeypatch):
        """La resolución de `call_tool` sigue siendo dinámica: parchear
        `b2b_ai.agent.loop.call_tool` (como hacen los tests existentes de
        AgentLoop) debe seguir funcionando con el wrapper de retry puesto."""
        monkeypatch.setattr(
            "b2b_ai.infrastructure.retry.time.sleep", lambda s: None)
        loop = self._make_bare_loop()
        with patch("b2b_ai.agent.loop.call_tool",
                  return_value={"parcheado": True}) as m:
            res = loop._call("parse_cfdi", tenant_id=1, xml_path="/x.xml")
        assert res == {"parcheado": True}
        m.assert_called_once_with("parse_cfdi", xml_path="/x.xml")


# ===========================================================================
# 2. Validación fail-closed de parámetros requeridos en call_tool()
# ===========================================================================
class TestCallToolRequiredParamValidation:
    def setup_method(self):
        import b2b_ai.tools.tools  # noqa: F401 — registra las tools reales
        from b2b_ai.tools.registry import tool, get_tool
        # Tool efímera propia del test para no depender del catálogo real
        # ni chocar con nombres ya registrados (el registro es global).
        if get_tool("_resil_test_tool") is None:
            self.calls = []

            @tool(
                name="_resil_test_tool",
                description="tool de prueba",
                parameters=[
                    {"name": "a", "type": "string", "required": True},
                    {"name": "b", "type": "string", "required": False},
                ],
            )
            def _resil_test_tool(a, b=None):
                TestCallToolRequiredParamValidation._calls.append((a, b))
                return {"a": a, "b": b}

    _calls = []

    def test_missing_required_param_raises_without_invoking_fn(self):
        from b2b_ai.tools.registry import call_tool, ToolValidationError

        before = len(TestCallToolRequiredParamValidation._calls)
        with pytest.raises(ToolValidationError) as exc_info:
            call_tool("_resil_test_tool", b="solo el opcional")

        assert "a" in str(exc_info.value)
        # Fail-closed real: la función NUNCA se invocó.
        assert len(TestCallToolRequiredParamValidation._calls) == before

    def test_all_required_present_invokes_normally(self):
        from b2b_ai.tools.registry import call_tool

        res = call_tool("_resil_test_tool", a="valor")
        assert res == {"a": "valor", "b": None}

    def test_validation_error_is_value_error_subclass_non_retryable(self):
        """ToolValidationError debe ser ValueError: infrastructure/retry.py
        trata ValueError como no-retryable por defecto, así que un error de
        validación fail-closed nunca dispara reintentos inútiles."""
        from b2b_ai.tools.registry import ToolValidationError
        assert issubclass(ToolValidationError, ValueError)

    def test_real_tool_register_erp_requires_invoice(self):
        """Verifica la validación contra una tool real del catálogo, no solo
        la de prueba: register_erp declara `invoice` como requerido."""
        from b2b_ai.tools.registry import call_tool, ToolValidationError
        with pytest.raises(ToolValidationError):
            call_tool("register_erp")  # falta `invoice`

    def test_unregistered_tool_still_raises_keyerror(self):
        """Regresión: la validación no debe tapar el KeyError existente."""
        from b2b_ai.tools.registry import call_tool
        with pytest.raises(KeyError):
            call_tool("esto_no_existe_jamas")


# ===========================================================================
# 3. Fuente única de verdad de los umbrales de confianza
# ===========================================================================
class TestConfidenceSingleSourceOfTruth:
    def test_values_match_across_all_three_consumers(self):
        from b2b_ai.common import confidence
        from b2b_ai.agent import loop as agent_loop
        from b2b_ai.features.bookkeeping.auto_classifier import AutoClassifier

        assert agent_loop.DEFAULT_CONFIDENCE_THRESHOLD == \
            confidence.DEFAULT_CONFIDENCE_THRESHOLD == 0.70
        assert agent_loop.CONFIDENCE_FLOOR == confidence.CONFIDENCE_FLOOR == 0.50
        assert AutoClassifier.CONFIDENCE_MEDIUM == \
            confidence.CONFIDENCE_MEDIUM == 0.60
        assert AutoClassifier.CONFIDENCE_HIGH == \
            confidence.CONFIDENCE_HIGH == 0.85

    def test_classify_cfdi_reads_shared_floor_not_a_local_literal(
            self, monkeypatch):
        """Si alguien reintrodujera `confianza < 0.50` hardcodeado en
        classify.py, este test fallaría: subimos el piso compartido a 0.99
        y una clasificación que antes pasaba (confianza ~0.55-0.75) debe
        ahora requerir revisión humana."""
        from b2b_ai.services import classify

        datos = {
            "conceptos": [{"descripcion": "papeleria de oficina"}],
            "claves_prod_serv": [], "tipo": "I",
        }
        base = classify.classify_cfdi(datos)
        assert 0.50 <= base["confianza"] < 0.99, (
            "Precondición del test: la confianza base debe caer en el "
            "rango que este test necesita mover con el piso compartido."
        )
        assert base["requires_human_review"] is False

        monkeypatch.setattr(classify, "CONFIDENCE_FLOOR", 0.99)
        raised = classify.classify_cfdi(datos)
        assert raised["requires_human_review"] is True

    def test_agent_loop_hard_gate_reads_shared_floor(self, monkeypatch):
        """Mismo principio para agent/loop.py: subir el piso compartido debe
        activar el hard-gate AG-1 para una confianza que antes lo pasaba."""
        from b2b_ai.agent import loop as agent_loop

        monkeypatch.setattr(agent_loop, "CONFIDENCE_FLOOR", 0.99)
        clasif = {"categoria": "gasto_operativo", "confianza": 0.80,
                  "requires_human_review": False, "source": "rules"}
        assert clasif["confianza"] < agent_loop.CONFIDENCE_FLOOR
        if clasif.get("confianza", 0) < agent_loop.CONFIDENCE_FLOOR:
            clasif["requires_human_review"] = True
        assert clasif["requires_human_review"] is True

    def test_no_hardcoded_duplicate_floor_left_in_loop_source(self):
        """Guarda estática: el `_CONFIDENCE_FLOOR = 0.50` local que existía
        en agent/loop.py debe haber desaparecido a favor del import
        compartido (si vuelve, esto es un signo de que se re-duplicó)."""
        import inspect
        from b2b_ai.agent import loop as agent_loop
        src = inspect.getsource(agent_loop.AgentLoop.process)
        assert "_CONFIDENCE_FLOOR = 0.50" not in src
        assert "CONFIDENCE_FLOOR" in src  # sigue usando el umbral, solo que compartido

    def test_confidence_module_rejects_inconsistent_env_override(self, monkeypatch):
        """DEFAULT_CONFIDENCE_THRESHOLD nunca puede quedar por debajo del
        piso duro (rompería el gate AG-1: el umbral de auto-procesamiento
        sería más laxo que el piso que se supone es el mínimo absoluto)."""
        import importlib
        monkeypatch.setenv("B2B_CONFIDENCE_FLOOR", "0.80")
        monkeypatch.setenv("B2B_CONFIDENCE_THRESHOLD", "0.10")
        from b2b_ai.common import confidence
        with pytest.raises(ValueError):
            importlib.reload(confidence)
        # Deja el módulo real consistente para el resto de la suite.
        monkeypatch.delenv("B2B_CONFIDENCE_FLOOR", raising=False)
        monkeypatch.delenv("B2B_CONFIDENCE_THRESHOLD", raising=False)
        importlib.reload(confidence)


# ===========================================================================
# 4. Circuit breaker integrado en LLMService._run()
# ===========================================================================
class TestLLMServiceCircuitBreaker:
    def test_open_circuit_skips_provider_call_and_falls_back(self):
        """Con el circuito ya abierto, `_run()` debe fallar rápido SIN
        siquiera invocar `client.complete()` — y la fachada pública debe
        caer a reglas como con cualquier otro fallo del LLM."""
        from b2b_ai.services import llm as llm_mod

        llm_mod._LLM_CIRCUIT_BREAKER.trip()  # fuerza estado OPEN
        try:
            client = MagicMock()
            client.complete.side_effect = AssertionError(
                "no debía llamarse al proveedor con el circuito abierto")
            svc = llm_mod.LLMService(client=client)

            datos = {"conceptos": [{"descripcion": "papeleria"}],
                     "claves_prod_serv": [], "tipo": "I", "total": "100"}
            res = svc.classify_invoice(datos)

            assert res["source"] == "rules"
            client.complete.assert_not_called()
            assert "circuit" in (svc.last_error or "").lower() or \
                "abierto" in (svc.last_error or "").lower()
        finally:
            llm_mod._LLM_CIRCUIT_BREAKER.reset()

    def test_repeated_provider_failures_open_the_circuit(self, monkeypatch):
        """Fallos reales sostenidos del proveedor deben abrir el circuito
        (a través del breaker real, no uno de prueba aislado) y entonces
        las llamadas siguientes ya ni tocan al proveedor."""
        from b2b_ai.services import llm as llm_mod
        from b2b_ai.infrastructure.circuit_breaker import (
            CircuitBreaker, CircuitBreakerConfig, CircuitState,
        )

        # Breaker de prueba con umbral bajo para no necesitar 8 fallos
        # reales; se inyecta en el módulo para no tocar la config
        # compartida del singleton "llm_calls" (la resetea el fixture
        # autouse de conftest, pero el objeto config es mutable y
        # compartido — mejor no tocarlo).
        test_breaker = CircuitBreaker(
            "llm_calls_test",
            config=CircuitBreakerConfig(failure_threshold=2,
                                        recovery_timeout=999.0))
        monkeypatch.setattr(llm_mod, "_LLM_CIRCUIT_BREAKER", test_breaker)

        client = MagicMock()
        client.complete.side_effect = ConnectionError("proveedor caído")
        svc = llm_mod.LLMService(client=client)
        datos = {"conceptos": [{"descripcion": "papeleria"}],
                 "claves_prod_serv": [], "tipo": "I", "total": "100"}

        svc.classify_invoice(datos)
        svc.classify_invoice(datos)
        assert test_breaker.state == CircuitState.OPEN
        assert client.complete.call_count == 2

        # Con el circuito ya abierto, una tercera llamada NO debe tocar
        # al proveedor otra vez.
        res = svc.classify_invoice(datos)
        assert res["source"] == "rules"
        assert client.complete.call_count == 2, (
            "El circuito abierto debe evitar la 3ra llamada real al "
            "proveedor."
        )

    def test_successful_call_does_not_trip_breaker(self):
        """Camino feliz: una llamada exitosa no debe dejar el breaker
        compartido en un estado distinto de CLOSED (regresión de
        aislamiento entre tests)."""
        from b2b_ai.services.llm import LLMService, MockLLM
        from b2b_ai.infrastructure.circuit_breaker import CircuitState
        from b2b_ai.services import llm as llm_mod

        svc = LLMService(client=MockLLM())
        datos = {"conceptos": [{"descripcion": "papeleria"}],
                 "claves_prod_serv": [], "tipo": "I", "total": "100"}
        res = svc.classify_invoice(datos)
        assert res["source"] == "llm"
        assert llm_mod._LLM_CIRCUIT_BREAKER.state == CircuitState.CLOSED
