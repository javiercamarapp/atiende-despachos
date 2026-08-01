# -*- coding: utf-8 -*-
"""Tests del loop de agente (FASE 4): arbol de decision, human-in-the-loop
y escalado por anomalia / baja confianza."""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.db.tenants import TenantManager
from b2b_ai.agent.loop import AgentLoop
from b2b_ai.services.llm import MockLLM


@pytest.fixture
def env(tmp_path):
    db = Database(str(tmp_path / "agent.db"))
    tm = TenantManager(db)
    t = tm.onboard_tenant("Cliente A", "XAXX010101000",
                          policy_human_review="hold")
    loop = AgentLoop(db=db, llm=MockLLM())
    return db, tm, t["id"], loop


def test_auto_processed(env, sample_papeleria):
    db, tm, tid, loop = env
    r = loop.process(sample_papeleria, tenant_id=tid, send_notifications=False)
    assert r["decision"] == "auto_processed"
    assert r["clasificacion"]["categoria"] == "gasto_operativo"
    assert r["erp"] is not None and r["erp"]["ok"]
    assert r["review_id"] is None
    assert db.count_pending_reviews(tid) == 0
    assert db.count_invoices(tid) == 1


def test_parse_failed_escala(env, tmp_path):
    db, tm, tid, loop = env
    bad = tmp_path / "no.xml"
    bad.write_text("esto no es xml")
    r = loop.process(str(bad), tenant_id=tid, send_notifications=False)
    assert r["decision"] == "parse_failed"
    assert r["review_id"] is not None
    assert db.count_pending_reviews(tid) == 1


def test_invalida_escala_y_no_registra_erp(env, tmp_path):
    db, tm, tid, loop = env
    bad = tmp_path / "invalida.xml"
    bad.write_text("<Comprobante></Comprobante>")
    r = loop.process(str(bad), tenant_id=tid, send_notifications=False)
    assert r["decision"] == "invalid"
    assert r["review_id"] is not None
    assert r["erp"] is None
    assert db.count_pending_reviews(tid) == 1


def test_politica_hold_no_registra_erp_con_baja_confianza(env):
    db, tm, tid, loop = env

    class BajaConfianza(MockLLM):
        def _respond(self, task, datos):
            if task == "classify":
                import json
                return json.dumps({"categoria": "desconocido",
                                   "confianza": 0.2, "razon": "baja"})
            return super()._respond(task, datos)

    loop.llm = BajaConfianza()
    r = loop.process("fixtures/cfdis/01_gasto_operativo_papeleria.xml",
                     tenant_id=tid, send_notifications=False)
    assert r["decision"] == "needs_review"
    assert r["erp"] is None
    assert r["review_id"] is not None
    assert db.count_pending_reviews(tid) == 1


def test_politica_auto_register_si_registra_erp_con_baja_confianza(env):
    db, tm, tid, loop = env
    tm.set_config(tid, policy_human_review="auto_register")

    class BajaConfianza(MockLLM):
        def _respond(self, task, datos):
            if task == "classify":
                import json
                return json.dumps({"categoria": "desconocido",
                                   "confianza": 0.2, "razon": "baja"})
            return super()._respond(task, datos)

    loop.llm = BajaConfianza()
    r = loop.process("fixtures/cfdis/01_gasto_operativo_papeleria.xml",
                     tenant_id=tid, send_notifications=False)
    assert r["decision"] == "needs_review"
    assert r["erp"] is not None
    assert r["review_id"] is not None


def test_anomalia_alerta_escala(env, sample_papeleria):
    db, tm, tid, loop = env

    class AnomaliaForzada(MockLLM):
        def _respond(self, task, datos):
            if task == "anomaly":
                import json
                return json.dumps({"anomalias": ["IVA irregular"],
                                   "nivel": "alerta"})
            return super()._respond(task, datos)

    loop.llm = AnomaliaForzada()
    r = loop.process(sample_papeleria, tenant_id=tid,
                     send_notifications=False)
    assert r["decision"] == "needs_review"
    assert r["anomalia"]["nivel"] == "alerta"
    assert r["review_id"] is not None


def test_loop_audita_llamadas(env, sample_papeleria):
    db, tm, tid, loop = env
    loop.process(sample_papeleria, tenant_id=tid, send_notifications=False)
    tools = {a["tool_name"] for a in db.list_audit(tenant_id=tid)}
    assert "parse_cfdi" in tools
    assert "validate_cfdi" in tools
    assert "register_erp" in tools


def test_resolucion_de_review(tmp_db):
    tm = TenantManager(tmp_db)
    t = tm.onboard_tenant("Cliente B", "ABC123")
    rid = tmp_db.create_review(t["id"], None, "motivo de prueba")
    resolved = tmp_db.resolve_review(rid, "approve", "todo ok", "contador")
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert tmp_db.count_pending_reviews(t["id"]) == 0
    assert tmp_db.resolve_review(rid, "reject") is None
