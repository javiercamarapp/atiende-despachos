# -*- coding: utf-8 -*-
"""Tests del OnboardingWizard (7 pasos) y el OnboardingChecklist (score 0-100)."""
import pytest

from b2b_ai.db.db import Database
from b2b_ai.onboarding.wizard import (
    OnboardingWizard, OnboardingError, STEP_ORDER, STEP_NAMES,
)
from b2b_ai.onboarding.checklist import OnboardingChecklist
from b2b_ai.db.tenants import TenantNotFoundError


@pytest.fixture
def tenant_db(tmp_path):
    db = Database(str(tmp_path / "onboarding.db"))
    tid = db.create_tenant("Cliente Demo", rfc="XAXX010101000")
    return db, tid


# ------------------------------------------------------------------------- #
# Wizard — flujo de pasos
# ------------------------------------------------------------------------- #
def test_status_inicial_antes_de_pasos(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    s = wiz.status()
    assert s["tenant_id"] == tid
    assert s["current_step"] == 1
    assert s["complete"] is False
    assert s["completed_steps"] == []


def test_paso1_valida_rfc_invalido(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(1, {"name": "X", "rfc": "ABC", "industry": "comercio"})


def test_paso2_valida_erp(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    wiz.set_step(1, {"name": "X", "rfc": "XAXX010101000", "industry": "c"})
    with pytest.raises(OnboardingError):
        wiz.set_step(2, {"erp": "SAP"})
    # Normaliza a mayúsculas
    r = wiz.set_step(2, {"erp": "aspel"})
    assert wiz.get_step(2)["data"]["erp"] == "ASPEL"
    assert r["current_step"] == 3  # avanzó


def test_paso3_modo_credentials_obliga_campos(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(3, {"mode": "credentials", "credentials": {"host": "h"}})
    wiz.set_step(3, {"mode": "credentials",
                     "credentials": {"host": "h", "user": "u", "password": "p"}})


def test_paso3_modo_csv_obliga_archivo(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(3, {"mode": "csv"})
    wiz.set_step(3, {"mode": "csv", "csv_file": "cuentas.csv"})


def test_paso4_requiere_catalogo_o_template(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(4, {})
    wiz.set_step(4, {"catalog": [{"codigo": "1000", "descripcion": "Caja"}]})


def test_paso5_requiere_invoice_id(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(5, {})
    wiz.set_step(5, {"invoice_id": 1})


def test_paso6_requiere_invites(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(6, {"invites": []})
    wiz.set_step(6, {"invites": [{"name": "Ana", "email": "ana@x.com"}]})


def test_paso7_valida_plan(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    for step, data in [
        (1, {"name": "X", "rfc": "XAXX010101000", "industry": "comercio"}),
        (2, {"erp": "CONTPAQi"}),
        (3, {"mode": "csv", "csv_file": "c.csv"}),
        (4, {"catalog": [{"codigo": "1000"}]}),
        (5, {"invoice_id": 1}),
        (6, {"invites": [{"name": "Ana", "email": "ana@x.com"}]}),
    ]:
        wiz.set_step(step, data)
    with pytest.raises(OnboardingError):
        wiz.set_step(7, {"plan": "ultra"})
    r = wiz.set_step(7, {"plan": "growth"})
    # El paso 7 cierra el wizard
    assert r["complete"] is True
    assert wiz.status()["complete"] is True


def test_complete_con_pasos_faltantes_rechaza(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    wiz.set_step(1, {"name": "X", "rfc": "XAXX010101000",
                     "industry": "comercio"})
    with pytest.raises(OnboardingError):
        wiz.complete()


def test_complete_flujo_completo(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    for step, data in [
        (1, {"name": "X", "rfc": "XAXX010101000", "industry": "comercio"}),
        (2, {"erp": "CONTPAQi"}),
        (3, {"mode": "csv", "csv_file": "c.csv"}),
        (4, {"catalog": [{"codigo": "1000"}]}),
        (5, {"invoice_id": 1}),
        (6, {"invites": [{"name": "Ana", "email": "ana@x.com"}]}),
        (7, {"plan": "starter"}),
    ]:
        wiz.set_step(step, data)
    assert wiz.status()["complete"] is True


def test_paso_invalido_rechaza(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    with pytest.raises(OnboardingError):
        wiz.set_step(9, {})


def test_tenant_inexistente_rechaza(tmp_path):
    db = Database(str(tmp_path / "x.db"))
    wiz = OnboardingWizard(db, tenant_id=999)
    with pytest.raises(TenantNotFoundError):
        wiz.status()


# ------------------------------------------------------------------------- #
# Checklist — verificación y score 0-100
# ------------------------------------------------------------------------- #
def test_score_cero_sin_pasos(tenant_db):
    db, tid = tenant_db
    cl = OnboardingChecklist(db, tenant_id=tid)
    ev = cl.evaluate()
    assert ev["score"] == 0
    assert ev["complete"] is False
    assert set(ev["missing"]) == {
        "company_info", "erp_connected", "first_invoice", "team_member"}


def test_company_info_ok_sube_25(tenant_db):
    db, tid = tenant_db
    OnboardingWizard(db, tenant_id=tid).set_step(
        1, {"name": "X", "rfc": "XAXX010101000", "industry": "comercio"})
    cl = OnboardingChecklist(db, tenant_id=tid)
    assert cl.score() == 25
    assert "company_info" not in cl.evaluate()["missing"]


def test_erp_connected_ok_sube_50(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    wiz.set_step(1, {"name": "X", "rfc": "XAXX010101000", "industry": "c"})
    wiz.set_step(3, {"mode": "csv", "csv_file": "c.csv"})
    cl = OnboardingChecklist(db, tenant_id=tid)
    assert cl.score() == 50


def test_first_invoice_requiere_db(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    wiz.set_step(1, {"name": "X", "rfc": "XAXX010101000", "industry": "c"})
    wiz.set_step(5, {"invoice_id": 1})
    # Sin facturas en la DB, el chequeo de primera factura NO cuenta.
    cl = OnboardingChecklist(db, tenant_id=tid)
    assert cl.score() == 25
    assert "first_invoice" in cl.evaluate()["missing"]


def test_score_100_flujo_completo(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    for step, data in [
        (1, {"name": "X", "rfc": "XAXX010101000", "industry": "comercio"}),
        (2, {"erp": "CONTPAQi"}),
        (3, {"mode": "csv", "csv_file": "c.csv"}),
        (4, {"catalog": [{"codigo": "1000"}]}),
        (5, {"invoice_id": 1}),
        (6, {"invites": [{"name": "Ana", "email": "ana@x.com"}]}),
        (7, {"plan": "starter"}),
    ]:
        wiz.set_step(step, data)
    # Primera factura real en la DB (necesaria para el chequeo).
    db.insert_invoice(tid, {"archivo": "x.xml", "folio_fiscal": "F-1"},
                      {"categoria": "gasto"}, {"ok": True})
    # Miembro de equipo real en la DB.
    wiz.create_team_users()
    cl = OnboardingChecklist(db, tenant_id=tid)
    ev = cl.evaluate()
    assert ev["score"] == 100
    assert ev["complete"] is True
    assert ev["missing"] == []


def test_create_team_users_idempotente(tenant_db):
    db, tid = tenant_db
    wiz = OnboardingWizard(db, tenant_id=tid)
    wiz.set_step(6, {"invites": [
        {"name": "Ana", "email": "ana@x.com"},
        {"name": "Luis", "email": "luis@x.com"},
    ]})
    assert wiz.create_team_users() == 2
    assert wiz.create_team_users() == 0  # idempotente
    users = wiz._list_users()
    assert {u["email"] for u in users} == {"ana@x.com", "luis@x.com"}
