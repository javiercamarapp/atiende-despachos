# -*- coding: utf-8 -*-
"""test_sat_submit_rpa_bridge.py — Pruebas de contrato para la conexión entre
declaration_api.py, SATPortalRPADriver (sat_rpa_bridge.py) y
compliance_tracker.

Todas las pruebas que tocan un navegador corren EXCLUSIVAMENTE contra el
simulador local `tests/fixtures/sat_portal_simulator.py` (127.0.0.1). Ninguna
toca sat.gob.mx ni ningún otro dominio *.gob.mx — están marcadas
`computer_use_e2e` igual que `tests/test_sat_portal_rpa_driver.py`.

Cobertura (ver tarea):
  (a) modo 'stub' (default) sin cambios de comportamiento.
  (b) modo 'rpa' con el simulador de SAT + verificación de que
      compliance_tracker se actualiza.
  (c) modo 'rpa' cuando el driver falla -> compliance_tracker NO se marca
      como cumplida.
  + pruebas de configuración/gating sin navegador (rápidas, corren siempre).
"""
from __future__ import annotations

import base64
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.compliance_tracker.models import ObligationStatus, ObligationType
from b2b_ai.features.compliance_tracker.service import ComplianceService, _reset_state
from b2b_ai.features.declaraciones.declaration_api import build_declarations_api_router
from b2b_ai.features.declaraciones.diot_generator import DIOTGenerator
from b2b_ai.features.declaraciones.engine import DiotRecord, DiotResult
from b2b_ai.features.declaraciones.sat_rpa_bridge import (
    SATSubmitModeConfigurationError,
    get_sat_submit_mode,
    mark_diot_obligation_completed,
    rpa_execution_allowed,
)

PORT = 18767  # puerto distinto al de test_sat_portal_rpa_driver.py (18766)
PORTAL_URL = f"http://127.0.0.1:{PORT}"
TENANT = "tenant-rpa-bridge"


@pytest.fixture(autouse=True)
def _clean_compliance_state():
    _reset_state()
    yield
    _reset_state()


@pytest.fixture(autouse=True)
def _clean_sat_env(monkeypatch):
    """Asegura que cada test parte de env limpio para los flags nuevos."""
    for var in (
        "B2B_SAT_SUBMIT_MODE",
        "B2B_COMPUTER_USE_MODE",
        "B2B_COMPUTER_USE_ALLOW_WRITES",
        "B2B_COMPUTER_USE_HEADLESS",
        "SAT_PORTAL_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def _require_api_key():
    return {"tenant_id": TENANT, "key": "test-key"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_declarations_api_router(db=None, require_api_key=_require_api_key))
    return TestClient(app)


@pytest.fixture()
def cer_key_files(tmp_path):
    cer = tmp_path / "fake.cer"
    key = tmp_path / "fake.key"
    cer.write_bytes(b"-----FAKE CERTIFICATE-----")
    key.write_bytes(b"-----FAKE PRIVATE KEY-----")
    return str(cer), str(key)


def _diot_content(periodo: str = "2026-01") -> bytes:
    result = DiotResult(
        records=[
            DiotRecord(
                rfc_tercero="ABC010101AB1",
                nombre="Proveedor de Prueba SA de CV",
                tipo_operacion="03",
                monto_neto=10000.0,
                iva_trasladado_16=1600.0,
                fecha="2026-01-15",
            ),
        ],
        periodo=periodo,
        rfc_contribuyente="XYZ010101AB2",
    )
    gen = DIOTGenerator()
    content = gen.generate(result)
    assert gen.errors == []
    return content.encode("utf-8")


def _submit_payload(cer_path, key_path, password="correct-password", periodo="2026-01", tipo="diot"):
    return {
        "declaration_id": "decl-001",
        "tenant_id": TENANT,
        "rfc": "XYZ010101AB2",
        "periodo": periodo,
        "tipo": tipo,
        "xml_signed": base64.b64encode(_diot_content(periodo)).decode("ascii"),
        "cer_path": cer_path,
        "key_path": key_path,
        "password": password,
        "test_mode": True,
        "confirm": True,
    }


@pytest.fixture(scope="module")
def sat_simulator():
    from tests.fixtures.sat_portal_simulator import SATPortalHandler, start_sat_portal_server

    SATPortalHandler.SESSIONS = {}
    SATPortalHandler.SUBMISSIONS = {}
    server = start_sat_portal_server(port=PORT)
    yield PORTAL_URL
    server.shutdown()


# ---------------------------------------------------------------------------
# Configuración / gating — sin navegador, corren siempre
# ---------------------------------------------------------------------------
class TestModeConfig:
    def test_default_mode_is_stub(self):
        assert get_sat_submit_mode() == "stub"

    def test_explicit_stub_ok(self, monkeypatch):
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "STUB")
        assert get_sat_submit_mode() == "stub"

    def test_explicit_rpa_ok(self, monkeypatch):
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
        assert get_sat_submit_mode() == "rpa"

    def test_unknown_mode_raises(self, monkeypatch):
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "produccion-directa")
        with pytest.raises(SATSubmitModeConfigurationError):
            get_sat_submit_mode()


class TestRpaExecutionGate:
    def test_disabled_by_default(self):
        allowed, reason = rpa_execution_allowed()
        assert allowed is False
        assert "B2B_COMPUTER_USE_MODE" in reason

    def test_disabled_when_writes_not_allowed(self, monkeypatch):
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
        allowed, reason = rpa_execution_allowed()
        assert allowed is False
        assert "ALLOW_WRITES" in reason

    def test_allowed_when_both_gates_set(self, monkeypatch):
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        allowed, _ = rpa_execution_allowed()
        assert allowed is True

    def test_mock_mode_does_not_count_as_playwright(self, monkeypatch):
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "mock")
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        allowed, reason = rpa_execution_allowed()
        assert allowed is False
        assert "playwright" in reason


# ---------------------------------------------------------------------------
# (a) Modo 'stub' (default) — comportamiento sin cambios
# ---------------------------------------------------------------------------
class TestStubModeUnchanged:
    def test_submit_default_mode_uses_stub_never_touches_compliance(self, cer_key_files):
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key)
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        # Comportamiento histórico del stub: nunca ACCEPTED, siempre simulado.
        assert body["simulado"] is True
        assert body["status"] != "accepted"
        # compliance_tracker jamás se toca en modo stub.
        service = ComplianceService()
        assert service.get_obligations(TENANT) == []

    def test_submit_explicit_stub_mode_same_as_default(self, monkeypatch, cer_key_files):
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "stub")
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key)
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        assert resp.json()["simulado"] is True

    def test_rpa_mode_non_diot_type_still_uses_stub(self, monkeypatch, cer_key_files):
        """El driver RPA solo sabe presentar DIOT; para otros tipos, modo
        'rpa' sigue usando SATSubmitter (limitación documentada, no fallback
        silencioso: el stub ya es honesto por sí mismo)."""
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key, tipo="iva")
        payload["xml_signed"] = base64.b64encode(
            b"<declaracion Sello='x'>fake</declaracion>"
        ).decode("ascii")
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["simulado"] is True
        assert body["status"] != "accepted"


# ---------------------------------------------------------------------------
# Config inválida -> 500 explícito (nunca silencioso)
# ---------------------------------------------------------------------------
def test_invalid_submit_mode_returns_explicit_500(monkeypatch, cer_key_files):
    monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "algo-raro")
    cer, key = cer_key_files
    client = _client()
    resp = client.post("/api/v1/declarations/submit", json=_submit_payload(cer, key))
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Modo 'rpa' sin gates de computer_use -> falla explícito, nunca finge éxito
# ---------------------------------------------------------------------------
def test_rpa_mode_without_gates_fails_explicit_no_browser_needed(monkeypatch, cer_key_files):
    monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
    # SAT_PORTAL_URL ni siquiera se configura: si el gate funciona, nunca
    # debería intentarse abrir el navegador.
    cer, key = cer_key_files
    client = _client()
    resp = client.post("/api/v1/declarations/submit", json=_submit_payload(cer, key))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "rpa_disabled"
    assert body["simulado"] is True
    service = ComplianceService()
    assert service.get_obligations(TENANT) == []


def test_rpa_mode_missing_portal_url_fails_explicit(monkeypatch, cer_key_files):
    monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
    monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
    monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
    cer, key = cer_key_files
    client = _client()
    resp = client.post("/api/v1/declarations/submit", json=_submit_payload(cer, key))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "rpa_misconfigured"


def test_rpa_mode_without_confirm_never_touches_browser(monkeypatch, cer_key_files):
    monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
    monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
    monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
    monkeypatch.setenv("SAT_PORTAL_URL", "http://127.0.0.1:1")  # puerto muerto: si se
    # llegara a intentar conectar, el test fallaría con un error de conexión
    # en vez de CONFIRMATION_REQUIRED.
    cer, key = cer_key_files
    client = _client()
    payload = _submit_payload(cer, key)
    payload["confirm"] = False
    resp = client.post("/api/v1/declarations/submit", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "confirmation_required"


# ---------------------------------------------------------------------------
# mark_diot_obligation_completed — lógica pura, sin navegador
# ---------------------------------------------------------------------------
class TestMarkDiotObligationCompleted:
    def test_creates_and_completes_when_no_prior_calendar(self):
        detail = mark_diot_obligation_completed(TENANT, "2026-01", user_id="rpa-bot")
        assert detail["updated"] is True
        service = ComplianceService()
        obl = service.get_obligation(detail["obligation_id"])
        assert obl.obligation_type == ObligationType.DIOT
        assert obl.status == ObligationStatus.COMPLETED
        assert obl.completed_by == "rpa-bot"

    def test_completes_existing_pending_obligation(self):
        service = ComplianceService()
        from datetime import date
        existing = service.create_obligation(
            tenant_id=TENANT, obligation_type=ObligationType.DIOT,
            due_date=date(2026, 1, 17),
        )
        detail = mark_diot_obligation_completed(TENANT, "2026-01")
        assert detail["updated"] is True
        assert detail["obligation_id"] == existing.id
        assert service.get_obligation(existing.id).status == ObligationStatus.COMPLETED

    def test_already_completed_is_not_an_error(self):
        mark_diot_obligation_completed(TENANT, "2026-01")
        detail = mark_diot_obligation_completed(TENANT, "2026-01")
        assert detail["updated"] is False

    def test_bad_periodo_format_reports_not_updated(self):
        detail = mark_diot_obligation_completed(TENANT, "2026", user_id="x")
        assert detail["updated"] is False

    def test_empty_tenant_reports_not_updated(self):
        detail = mark_diot_obligation_completed("", "2026-01")
        assert detail["updated"] is False


# ---------------------------------------------------------------------------
# (b) / (c) Flujo completo contra el simulador — requiere Chromium real
# ---------------------------------------------------------------------------
@pytest.mark.computer_use_e2e
class TestRpaFlowAgainstSimulator:
    def _enable_rpa(self, monkeypatch, portal_url):
        monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
        monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
        monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
        monkeypatch.setenv("SAT_PORTAL_URL", portal_url)

    def test_success_confirms_and_updates_compliance_tracker(
        self, monkeypatch, sat_simulator, cer_key_files
    ):
        self._enable_rpa(monkeypatch, sat_simulator)
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key, password="correct-password", periodo="2026-01")
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True, body
        assert body["folio"] is not None
        assert body["folio"].startswith("ACUSE-2026-01-")
        assert body["simulado"] is True  # honestidad: nunca se afirma verificado contra el SAT real
        assert "compliance_tracker" in body["mensaje"]

        service = ComplianceService()
        obligations = [
            o for o in service.get_obligations(TENANT, year=2026, month=1)
            if o.obligation_type == ObligationType.DIOT
        ]
        assert len(obligations) == 1
        assert obligations[0].status == ObligationStatus.COMPLETED

    def test_invalid_credentials_does_not_touch_compliance_tracker(
        self, monkeypatch, sat_simulator, cer_key_files
    ):
        self._enable_rpa(monkeypatch, sat_simulator)
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key, password="wrong", periodo="2026-02")
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["status"] == "invalid_credentials"
        assert body["folio"] is None

        service = ComplianceService()
        obligations = [
            o for o in service.get_obligations(TENANT, year=2026, month=2)
            if o.obligation_type == ObligationType.DIOT
        ]
        assert obligations == []

    def test_captcha_blocked_does_not_touch_compliance_tracker(
        self, monkeypatch, sat_simulator, cer_key_files
    ):
        self._enable_rpa(monkeypatch, sat_simulator)
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key, password="captcha-trigger", periodo="2026-03")
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["status"] == "captcha_blocked"

        service = ComplianceService()
        obligations = [
            o for o in service.get_obligations(TENANT, year=2026, month=3)
            if o.obligation_type == ObligationType.DIOT
        ]
        assert obligations == []

    def test_portal_never_contacted_at_real_gob_mx_domain(self, monkeypatch, cer_key_files):
        """Aunque alguien configure SAT_PORTAL_URL a un dominio real por error,
        el candado de sat_portal_rpa_driver bloquea el intento — este puente
        NUNCA lo debilita ni lo pasa por alto."""
        self._enable_rpa(monkeypatch, "https://declara.sat.gob.mx/algo")
        cer, key = cer_key_files
        client = _client()
        payload = _submit_payload(cer, key, periodo="2026-04")
        resp = client.post("/api/v1/declarations/submit", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["status"] == "blocked_real_sat_domain"

        service = ComplianceService()
        obligations = [
            o for o in service.get_obligations(TENANT, year=2026, month=4)
            if o.obligation_type == ObligationType.DIOT
        ]
        assert obligations == []
