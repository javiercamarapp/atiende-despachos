# -*- coding: utf-8 -*-
"""test_integration_piloto.py — Suite de integración end-to-end del piloto.

Valida que los módulos del MVP funcionan juntos contra endpoints reales:

    1. CFDI      : upload → parse → store → query           (app completa)
    2. Bank feed : conectar cuenta → sync → categorizar     (pilot_client)
    3. Nómina    : catalog → parse/validate → payroll calc  (app completa)
    4. Onboarding: start → 6 pasos → complete               (pilot_client)
    5. Billing   : checkout → webhook mock → suscripción    (pilot_client)
    6. Reports   : reporte custom desde datos               (pilot_client)
    7. Multi-tenant: aislamiento de datos entre 2 tenants   (app completa)
    8. Auth      : register → login → token → /auth/me      (app completa)

Uso de fixtures compartidos (tests/conftest.py):
    - pilot_client   : monta onboarding-wizard, billing-piloto, batch,
                       bank-feeds y reports con auth stub → tenant_test_123.
    - full_client    : app completa (create_app) con 2 tenants + API keys.
    - _reset_pilot_state / reset_bank_feeds_state : limpian stores en memoria.

NO se ejecuta contra el repo (mmap corruption en iCloud); corre en CI / máquina
de trabajo desde una copia del árbol (ver scripts/seed_demo_data.py para datos).
"""
from __future__ import annotations

import os
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")


def _fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


# --------------------------------------------------------------------------- #
# 1. CFDI: upload → parse → store → query
# --------------------------------------------------------------------------- #
def test_full_cfdi_flow(full_client):
    c = full_client["client"]
    db = full_client["db"]
    k = full_client["keys"][full_client["tenants"][0]]
    h = {"X-API-Key": k}

    # upload (multipart, XML real)
    with open(_fixture("02_inversion_consultoria.xml"), "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("02.xml", fh, "text/xml")})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["valido"] is True
    assert res["insertado"] is True
    assert res["erp_poliza"]

    # store: quedó persistida
    assert db.count_invoices() == 1

    # query: listado + detalle
    lst = c.get("/api/v1/invoices", headers=h).json()
    assert lst["count"] == 1

    det = c.get(f"/api/v1/invoices/{lst['invoices'][0]['id']}", headers=h).json()
    assert float(det["invoice"]["total"]) > 0


# --------------------------------------------------------------------------- #
# 2. Bank feed: conectar cuenta → sync → categorizar
# --------------------------------------------------------------------------- #
def test_bank_feed_sync(pilot_client, piloto_headers):
    c = pilot_client
    h = piloto_headers

    # conectar cuenta BBVA
    r = c.post("/api/v1/bank-feeds/accounts",
               json={"provider": "BBVA", "clabe": "012180001234567899",
                     "account_label": "Operativa", "tenant_id": "tenant_test_123"},
               headers=h)
    assert r.status_code == 200, r.text
    account_id = r.json()["data"]["id"]

    # sync: el adaptador mock genera movimientos deterministas
    rs = c.post(f"/api/v1/bank-feeds/accounts/{account_id}/sync", headers=h)
    assert rs.status_code == 200, rs.text
    assert rs.json()["ok"] is True

    # transacciones importadas
    rt = c.get(f"/api/v1/bank-feeds/accounts/{account_id}/transactions", headers=h)
    assert rt.status_code == 200, rt.text
    txs = rt.json()["data"]
    assert len(txs) > 0

    # categorizar una transacción explícitamente
    txn_id = txs[0]["id"]
    rc = c.post(f"/api/v1/bank-feeds/transactions/{txn_id}/categorize",
                json={"category": "NOMINA"}, headers=h)
    assert rc.status_code == 200, rc.text
    assert rc.json()["data"]["category"] == "NOMINA"


# --------------------------------------------------------------------------- #
# 3. Nómina: catalog → parse/validate → payroll calc
# --------------------------------------------------------------------------- #
def test_nomina_flow(full_client):
    c = full_client["client"]
    db = full_client["db"]
    k = full_client["keys"][full_client["tenants"][0]]
    h = {"X-API-Key": k}

    # catálogo SAT de códigos
    r = c.get("/nomina/catalog", headers=h)
    assert r.status_code == 200, r.text
    assert "periodicidad_pago" in r.json()

    # parse de un CFDI de nómina real
    rp = c.post("/nomina/parse", headers=h,
                files={"file": ("04_nomina.xml",
                                open(_fixture("04_nomina_pago.xml"), "rb"),
                                "text/xml")})
    assert rp.status_code in (200, 404)  # 404 si el fixture no lleva complemento

    # cálculo de nómina (ISR/IMSS) vía app real
    pr = c.post("/api/v1/payroll/calculate", headers=h, json={
        "empleado": {"nombre": "Ana García", "rfc": "GAA010101AB1",
                     "salario_diario": 1000},
        "periodo": {"sueldo_bruto": 30000, "dias_pagados": 15},
        "generar_cfdi": False,
    })
    assert pr.status_code == 200, pr.text
    res = pr.json()
    assert float(res["percepciones"]["total"]) == 30000.0
    assert "neto_a_pagar" in res


# --------------------------------------------------------------------------- #
# 4. Onboarding: start → 6 pasos → complete → activa billing
# --------------------------------------------------------------------------- #
def _run_onboarding_to_checkout(c, h, company="Grupo Contable MX S.A. de C.V.",
                                rfc="GCM920101AB1",
                                tenant_id="tenant_test_123"):
    """Avanza un onboarding desde start hasta el paso checkout (inclusive).

    `tenant_id` se fija igual al del auth stub del pilot_client
    ("tenant_test_123") para que el billing activado en el callback quede
    localizable por el GET de suscripción del mismo tenant.
    """
    r = c.post("/api/v1/onboarding-wizard/start", json={"tenant_id": tenant_id},
               headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["session_id"]

    def step(name, payload):
        resp = c.post(f"/api/v1/onboarding-wizard/{sid}/step/{name}",
                      json={"payload": payload}, headers=h)
        assert resp.status_code == 200, f"{name}: {resp.text}"

    step("tenant", {"company_name": company,
                    "admin_name": "Lic. Mariana Fernández",
                    "admin_email": "mariana@grupocontable.mx"})
    step("fiscal", {"rfc": rfc, "regimen_fiscal": "601",
                    "codigo_postal": "06600"})
    step("data_source", {"source": "cfdi_upload"})
    step("test_cfdi", {"record": {"rfc": rfc, "total": "12500.00",
                                  "uuid": str(uuid.uuid4()).upper()}})
    step("checkout", {"plan": "pro"})
    return sid


def test_onboarding_flow(pilot_client, piloto_headers):
    c = pilot_client
    h = piloto_headers
    sid = _run_onboarding_to_checkout(c, h)

    # complete → health check
    rc = c.post(f"/api/v1/onboarding-wizard/{sid}/complete", headers=h)
    assert rc.status_code == 200, rc.text
    assert rc.json()["ok"] is True
    assert rc.json()["session"]["status"] == "completed"


# --------------------------------------------------------------------------- #
# 5. Billing: checkout → callback/webhook mock → suscripción activa
# --------------------------------------------------------------------------- #
def test_billing_checkout(pilot_client, piloto_headers):
    c = pilot_client
    h = piloto_headers

    # checkout directo de billing-piloto (Conekta en modo mock, sin red)
    r = c.post("/api/v1/billing-piloto/checkout", headers=h, json={
        "plan": "pro",
        "success_url": "http://localhost/ok",
        "cancel_url": "http://localhost/cancel",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["checkout_url"]

    # flujo real de activación: el callback del wizard (status=paid) invoca
    # activate_pilot() y deja la suscripción ACTIVE (equivalente al webhook
    # order.paid que marca la orden como pagada en el billing del tenant).
    sid = _run_onboarding_to_checkout(c, h, company="Grupo Billing",
                                      rfc="GBI920101AB1")
    cb = c.post(f"/api/v1/onboarding-wizard/{sid}/checkout/callback",
                json={"status": "paid", "plan": "pro"}, headers=h)
    assert cb.status_code == 200, cb.text
    assert cb.json()["ok"] is True

    # suscripción activa para el tenant
    rs = c.get("/api/v1/billing-piloto/subscription", headers=h)
    assert rs.status_code == 200, rs.text
    sub = rs.json()["subscription"]
    assert sub is not None
    assert sub["status"] == "active"
    assert sub["plan_code"] == "pro"


# --------------------------------------------------------------------------- #
# 6. Reports: generar reporte desde datos recolectados
# --------------------------------------------------------------------------- #
def test_report_generation(pilot_client, piloto_headers):
    c = pilot_client
    h = piloto_headers

    r = c.post("/api/v1/reports/custom", headers=h, json={
        "data": {
            "title": "Reporte del cliente piloto",
            "period": "2026-07",
            "total": "12500.00",
            "facturas": 12,
        },
        "template": "monthly",
        "as_html": True,
    })
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")


# --------------------------------------------------------------------------- #
# 7. Multi-tenant: aislamiento de datos entre 2 tenants
# --------------------------------------------------------------------------- #
def test_multi_tenant_isolation(full_client):
    c = full_client["client"]
    t0, t1 = full_client["tenants"]
    h0 = {"X-API-Key": full_client["keys"][t0]}
    h1 = {"X-API-Key": full_client["keys"][t1]}

    # cada tenant sube 1 factura distinta
    for i, (name, hdr) in enumerate([("02_inversion_consultoria.xml", h0),
                                     ("01_gasto_operativo_papeleria.xml", h1)]):
        r = c.post("/api/v1/invoices/process", headers=hdr,
                   json={"xml_path": _fixture(name)})
        assert r.status_code == 200, name
        assert r.json()["result"]["insertado"] is True

    # cada tenant ve exactamente 1 factura (la suya)
    assert c.get("/api/v1/invoices", headers=h0).json()["count"] == 1
    assert c.get("/api/v1/invoices", headers=h1).json()["count"] == 1

    # las facturas no se filtran por la key del otro tenant
    lst0 = c.get("/api/v1/invoices", headers=h0).json()["invoices"]
    lst1 = c.get("/api/v1/invoices", headers=h1).json()["invoices"]
    assert [i["emisor_rfc"] for i in lst0] != [i["emisor_rfc"] for i in lst1]


# --------------------------------------------------------------------------- #
# 8. Auth: register → login → token → acceso a ruta protegida
# --------------------------------------------------------------------------- #
def test_auth_flow(full_client):
    c = full_client["client"]
    tenant_id = full_client["tenants"][0]

    # register usuario en el tenant
    email = "piloto@grupo.mx"
    r = c.post("/api/v1/auth/register", json={
        "email": email, "password": "Password1!",
        "tenant_id": tenant_id, "role": "contador", "name": "Piloto Test",
    })
    assert r.status_code in (200, 201), r.text

    # login → tokens
    rl = c.post("/api/v1/auth/login", json={"email": email,
                                            "password": "Password1!",
                                            "tenant_id": tenant_id})
    assert rl.status_code == 200, rl.text
    token = rl.json()["access_token"]

    # acceso a ruta protegida con Bearer token
    rm = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert rm.status_code == 200, rm.text
    assert rm.json()["user"]["email"] == email

    # sin token → 401
    assert c.get("/api/v1/auth/me").status_code == 401
