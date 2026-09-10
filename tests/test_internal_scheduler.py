# -*- coding: utf-8 -*-
"""test_internal_scheduler.py — Pruebas del scheduler interno (asyncio) que
reemplaza la invocación manual por HTTP de SATScheduler.run_daily/run_weekly
y del registro de CFDIs pendientes en CONTPAQi.

Cobertura:
  - flag maestro B2B_SCHEDULER_ENABLED (default true, apaga con false).
  - gate `_real_erp_write_allowed` (los 3 flags de escritura real).
  - tick(): dispara SATScheduler cuando compliance_tracker tiene obligaciones
    vencidas/por vencer; NO dispara si no hay nada pendiente o falta RFC.
  - tick(): registro de CFDIs pendientes vía orchestrator.upload_cfdis
    -- omitido por default seguro, ejecutado cuando los flags lo permiten,
    y los archivos se archivan solo tras un registro exitoso.
  - run_forever(): repite tick() con el `sleep_fn` inyectado (sin sleep real)
    y se detiene limpiamente al cancelar la task.
  - no revienta si no hay tenants ni CFDIs pendientes.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import date, timedelta

import pytest

from b2b_ai.db.db import Database
from b2b_ai.features.compliance_tracker.models import ObligationType
from b2b_ai.features.compliance_tracker.service import ComplianceService, _reset_state
from b2b_ai.features.pipeline.orchestrator import EndToEndPipelineError
from b2b_ai.scheduler.internal_scheduler import (
    InternalScheduler,
    _real_erp_write_allowed,
    scheduler_enabled_from_env,
)

RFC = "XAXX010101000"

SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="D" Folio="100"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="0.00" Total="1160.00">
    <cfdi:Emisor Rfc="PAP850101JKL" Nombre="PAPELERIA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR TEST"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Papeleria y articulos de oficina"
            ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="550e8400-e29b-41d4-a716-446655440000"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""


@pytest.fixture(autouse=True)
def _clean_compliance_state():
    _reset_state()
    yield
    _reset_state()


class _FakeComplianceService:
    """Doble de ComplianceService con listas fijas (sin depender de la fecha
    real ni de generate_calendar) para probar el disparo de SATScheduler de
    forma determinista."""

    def __init__(self, overdue=None, upcoming=None):
        self._overdue = overdue or []
        self._upcoming = upcoming or []
        self.generate_calendar_calls = []

    def generate_calendar(self, tenant_id, year):
        self.generate_calendar_calls.append((tenant_id, year))
        return []

    def get_overdue(self, tenant_id):
        return self._overdue

    def get_upcoming(self, tenant_id, days=7):
        return self._upcoming


class _FakeSATScheduler:
    def __init__(self, result=None, raise_exc=None):
        self._result = result if result is not None else {"ok": True, "task": "daily"}
        self._raise = raise_exc
        self.processed = False

    def process(self):
        self.processed = True
        if self._raise:
            raise self._raise
        return self._result


# --------------------------------------------------------------------------#
# Flag maestro
# --------------------------------------------------------------------------#
def test_scheduler_enabled_default_true(monkeypatch):
    monkeypatch.delenv("B2B_SCHEDULER_ENABLED", raising=False)
    assert scheduler_enabled_from_env() is True


@pytest.mark.parametrize("raw,expected", [
    ("false", False), ("0", False), ("no", False),
    ("true", True), ("1", True), ("YES", True),
])
def test_scheduler_enabled_env_values(monkeypatch, raw, expected):
    monkeypatch.setenv("B2B_SCHEDULER_ENABLED", raw)
    assert scheduler_enabled_from_env() is expected


# --------------------------------------------------------------------------#
# Gate de escritura real (los 3 flags)
# --------------------------------------------------------------------------#
def test_real_erp_write_blocked_por_default(monkeypatch):
    monkeypatch.delenv("B2B_COMPUTER_USE_MODE", raising=False)
    monkeypatch.delenv("B2B_COMPUTER_USE_ALLOW_WRITES", raising=False)
    monkeypatch.delenv("B2B_SAT_SUBMIT_MODE", raising=False)
    allowed, reason = _real_erp_write_allowed()
    assert allowed is False
    assert "B2B_COMPUTER_USE_MODE" in reason


def test_real_erp_write_blocked_si_falta_sat_submit_mode(monkeypatch):
    monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
    monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
    monkeypatch.delenv("B2B_SAT_SUBMIT_MODE", raising=False)  # default stub
    allowed, reason = _real_erp_write_allowed()
    assert allowed is False
    assert "B2B_SAT_SUBMIT_MODE" in reason


def test_real_erp_write_allowed_con_los_3_flags(monkeypatch):
    monkeypatch.setenv("B2B_COMPUTER_USE_MODE", "playwright")
    monkeypatch.setenv("B2B_COMPUTER_USE_ALLOW_WRITES", "true")
    monkeypatch.setenv("B2B_SAT_SUBMIT_MODE", "rpa")
    allowed, reason = _real_erp_write_allowed()
    assert allowed is True


# --------------------------------------------------------------------------#
# tick(): compliance_tracker -> SATScheduler
# --------------------------------------------------------------------------#
def test_tick_sin_tenants_no_revienta(tmp_path):
    db = Database(str(tmp_path / "empty.db"))
    sched = InternalScheduler(db=db, cfdi_inbox_dir=str(tmp_path / "inbox"))
    summary = sched.tick()
    assert summary == {"tenants_checked": 0, "sat": [], "cfdi_erp": []}


def test_tick_no_dispara_sat_sin_obligaciones_pendientes(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho A", rfc=RFC)
    fake_compliance = _FakeComplianceService(overdue=[], upcoming=[])
    fake_sat = _FakeSATScheduler()
    sched = InternalScheduler(
        db=db,
        cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=lambda tenant_id, rfc, ciec: fake_sat,
    )
    summary = sched.tick()
    assert summary["tenants_checked"] == 1
    sat_result = summary["sat"][0]
    assert sat_result["tenant_id"] == tid
    assert sat_result["triggered"] is False
    assert "sin obligaciones" in sat_result["reason"]
    assert fake_sat.processed is False
    # El calendario sí se intenta generar (idempotente) aunque no dispare nada.
    assert fake_compliance.generate_calendar_calls == [(str(tid), date.today().year)]


def test_tick_dispara_sat_con_obligacion_vencida(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho B", rfc=RFC)
    fake_compliance = _FakeComplianceService(
        overdue=[object()], upcoming=[])
    fake_sat = _FakeSATScheduler(result={"ok": True, "task": "daily", "count": 2})
    captured = {}

    def factory(tenant_id, rfc, ciec):
        captured["args"] = (tenant_id, rfc, ciec)
        return fake_sat

    sched = InternalScheduler(
        db=db,
        cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=factory,
    )
    summary = sched.tick()
    sat_result = summary["sat"][0]
    assert sat_result["triggered"] is True
    assert sat_result["ok"] is True
    assert sat_result["overdue"] == 1
    assert fake_sat.processed is True
    # El RFC de la tabla tenants se usó como fallback (no hay sat_rfc en config).
    assert captured["args"] == (tid, RFC, "")


def test_tick_dispara_sat_prefiere_sat_rfc_de_tenant_config(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho C", rfc="RFC-DE-LA-TABLA")
    db.set_tenant_config(tid, "sat_rfc", "RFC-DE-CONFIG")
    db.set_tenant_config(tid, "sat_ciec", "ciec-secreta")
    fake_compliance = _FakeComplianceService(overdue=[object()])
    captured = {}

    def factory(tenant_id, rfc, ciec):
        captured["args"] = (tenant_id, rfc, ciec)
        return _FakeSATScheduler()

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=factory,
    )
    sched.tick()
    assert captured["args"] == (tid, "RFC-DE-CONFIG", "ciec-secreta")


def test_tick_no_dispara_sat_sin_rfc_configurado(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho Sin RFC", rfc="")
    fake_compliance = _FakeComplianceService(overdue=[object()])
    fake_sat = _FakeSATScheduler()
    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=lambda tenant_id, rfc, ciec: fake_sat,
    )
    summary = sched.tick()
    sat_result = summary["sat"][0]
    assert sat_result["triggered"] is False
    assert "sat_rfc" in sat_result["reason"]
    assert fake_sat.processed is False


def test_tick_tenant_bloqueado_se_omite(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho Bloqueado", rfc=RFC)
    db.set_tenant_blocked(tid, True)
    fake_compliance = _FakeComplianceService(overdue=[object()])
    fake_sat = _FakeSATScheduler()
    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=lambda tenant_id, rfc, ciec: fake_sat,
    )
    summary = sched.tick()
    assert summary["tenants_checked"] == 0
    assert summary["sat"] == []
    assert fake_sat.processed is False


def test_tick_sat_scheduler_lanza_no_tumba_el_tick(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.create_tenant("Despacho Roto", rfc=RFC)
    fake_compliance = _FakeComplianceService(overdue=[object()])
    fake_sat = _FakeSATScheduler(raise_exc=RuntimeError("SAT caído"))
    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: fake_compliance,
        sat_scheduler_factory=lambda tenant_id, rfc, ciec: fake_sat,
    )
    summary = sched.tick()  # no debe lanzar
    sat_result = summary["sat"][0]
    assert sat_result["triggered"] is True
    assert sat_result["ok"] is False
    assert "SAT caído" in sat_result["error"]


def test_tick_integra_con_compliance_service_real(tmp_path):
    """Con el ComplianceService real (no doble): una obligación vencida
    creada a mano dispara SATScheduler.process(), sin depender de la fecha
    en que corra el test (se usa una fecha fija en el pasado)."""
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho Real", rfc=RFC)
    svc = ComplianceService()
    svc.create_obligation(
        tenant_id=str(tid),
        obligation_type=ObligationType.DIOT,
        due_date=date(2000, 1, 17),  # muy vencida, siempre en el pasado
    )
    fake_sat = _FakeSATScheduler()
    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        sat_scheduler_factory=lambda tenant_id, rfc, ciec: fake_sat,
    )
    summary = sched.tick()
    sat_result = summary["sat"][0]
    assert sat_result["triggered"] is True
    assert sat_result["overdue"] >= 1
    assert fake_sat.processed is True


# --------------------------------------------------------------------------#
# tick(): inbox de CFDIs pendientes -> orchestrator.upload_cfdis
# --------------------------------------------------------------------------#
def test_tick_sin_cfdis_pendientes_no_intenta_nada(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.create_tenant("Despacho D", rfc=RFC)
    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: _FakeComplianceService(),
    )
    summary = sched.tick()
    cfdi_result = summary["cfdi_erp"][0]
    assert cfdi_result["pending_files"] == 0
    assert cfdi_result["attempted"] is False


def test_tick_cfdis_pendientes_omitidos_por_flags_default(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho E", rfc=RFC)
    inbox = tmp_path / "inbox" / str(tid)
    inbox.mkdir(parents=True)
    (inbox / "cfdi1.xml").write_text(SAMPLE_CFDI, encoding="utf-8")

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: _FakeComplianceService(),
        real_erp_write_allowed_fn=lambda: (False, "flags en default seguro"),
    )
    summary = sched.tick()
    cfdi_result = summary["cfdi_erp"][0]
    assert cfdi_result["pending_files"] == 1
    assert cfdi_result["attempted"] is False
    assert "omitido por configuración" in cfdi_result["reason"]
    # El archivo NUNCA se toca/mueve cuando se omite.
    assert (inbox / "cfdi1.xml").exists()
    assert not (inbox / "procesados").exists()


def test_tick_cfdis_pendientes_se_registran_cuando_flags_lo_permiten(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho F", rfc=RFC)
    inbox = tmp_path / "inbox" / str(tid)
    inbox.mkdir(parents=True)
    (inbox / "cfdi1.xml").write_text(SAMPLE_CFDI, encoding="utf-8")

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: _FakeComplianceService(),
        real_erp_write_allowed_fn=lambda: (True, "ok"),
    )
    summary = sched.tick()
    cfdi_result = summary["cfdi_erp"][0]
    assert cfdi_result["attempted"] is True
    assert cfdi_result["ok"] is True
    assert cfdi_result["result"]["status"] == "completed"
    # El archivo se archivó (no se borró, no quedó en el inbox).
    assert not (inbox / "cfdi1.xml").exists()
    assert (inbox / "procesados" / "cfdi1.xml").exists()


def test_tick_cfdis_error_del_orquestador_no_archiva_ni_revienta(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    tid = db.create_tenant("Despacho G", rfc=RFC)
    inbox = tmp_path / "inbox" / str(tid)
    inbox.mkdir(parents=True)
    (inbox / "roto.xml").write_text("<xml>no es un cfdi</xml>", encoding="utf-8")

    class _BoomOrchestrator:
        def upload_cfdis(self, **kwargs):
            raise EndToEndPipelineError("parse falló")

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"),
        compliance_service_factory=lambda: _FakeComplianceService(),
        orchestrator=_BoomOrchestrator(),
        real_erp_write_allowed_fn=lambda: (True, "ok"),
    )
    summary = sched.tick()  # no debe lanzar
    cfdi_result = summary["cfdi_erp"][0]
    assert cfdi_result["attempted"] is True
    assert cfdi_result["ok"] is False
    assert "parse falló" in cfdi_result["error"]
    assert (inbox / "roto.xml").exists()  # queda para el próximo tick


# --------------------------------------------------------------------------#
# run_forever(): loop asyncio sin sleep real
# --------------------------------------------------------------------------#
@pytest.mark.asyncio
async def test_run_forever_respeta_flag_deshabilitado(tmp_path, monkeypatch):
    monkeypatch.setenv("B2B_SCHEDULER_ENABLED", "false")
    db = Database(str(tmp_path / "t.db"))
    calls = {"n": 0}
    sched = InternalScheduler(db=db, cfdi_inbox_dir=str(tmp_path / "inbox"))
    sched.tick = lambda: calls.__setitem__("n", calls["n"] + 1) or {}
    await asyncio.wait_for(sched.run_forever(), timeout=2)
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_run_forever_repite_tick_y_se_cancela_limpio(tmp_path, monkeypatch):
    monkeypatch.setenv("B2B_SCHEDULER_ENABLED", "true")
    db = Database(str(tmp_path / "t.db"))
    calls = {"n": 0}

    async def instant_sleep(_seconds):
        return None

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"), sleep_fn=instant_sleep)
    sched.tick = lambda: calls.__setitem__("n", calls["n"] + 1) or {}

    task = asyncio.create_task(sched.run_forever())
    for _ in range(400):
        if calls["n"] >= 3:
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["n"] >= 3


@pytest.mark.asyncio
async def test_run_forever_no_muere_si_un_tick_lanza(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    calls = {"n": 0}

    async def instant_sleep(_seconds):
        return None

    def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {}

    sched = InternalScheduler(
        db=db, cfdi_inbox_dir=str(tmp_path / "inbox"), sleep_fn=instant_sleep)
    sched.tick = flaky_tick

    task = asyncio.create_task(sched.run_forever())
    for _ in range(400):
        if calls["n"] >= 3:
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls["n"] >= 3
