# -*- coding: utf-8 -*-
"""test_demo_integration.py — Test del flujo completo de demo.

Demo flow: seed data → pipeline → resultados. Un despacho contable debe poder
ver el sistema funcionando en una demo. Este test integra:

  1. scripts/seed_demo.py genera dataset determinista (seed=42) y puebla una BD
     SQLite temporal con datos contables mexicanos realistas (tenant isolation).
  2. EndToEndOrchestrator: parse → adapt → bookkeeping → conciliación funciona
     end-to-end con un CFDI de ejemplo + transacciones bancarias del seed.
  3. Consistencia: CFDI parseado (total/subtotal/iva) coincide con las pólizas
     contables generadas (cuadradas: debe == haber).
  4. Conciliación con transacciones bancarias de ejemplo produce matches.
  5. /api/v1/health reporta los módulos OK (db ok, tenants e invoices del seed).
  6. POST /api/v1/pipeline/run (router real con auth) procesa correctamente.
  7. Reportes gerenciales muestran datos del demo.
  8. Tenant isolation: la BD demo no mezcla datos entre tenants.

NOTA (limite del entorno): NO ejecutar via `pytest` (error mmap en este Mac).
Se verifica con el script standalone scripts/../verify_demo_flow.py que ejercita
los mismos caminos. Este archivo documenta y fija el contrato del demo flow.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_DIR = os.path.join(REPO, "scripts", "seed_data")

sys.path.insert(0, REPO)

from b2b_ai.api.routes_health import build_health_router  # noqa: E402
from b2b_ai.cfdi.adapter import to_bookkeeping_format  # noqa: E402
from b2b_ai.cfdi.parser import parse_cfdi_4  # noqa: E402
from b2b_ai.db.db import Database  # noqa: E402
from b2b_ai.features.pipeline.orchestrator import EndToEndOrchestrator  # noqa: E402
from b2b_ai.features.pipeline.routes import build_pipeline_router  # noqa: E402
from b2b_ai.features.reportes_gerenciales.routes import (  # noqa: E402
    build_reportes_gerenciales_router,
)

# --- Carga scripts/seed_demo.py como módulo (no es paquete) -----------------
_seed_path = os.path.join(REPO, "scripts", "seed_demo.py")
_spec = importlib.util.spec_from_file_location("seed_demo", _seed_path)
seed_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_demo)

# --- Fixtures ---------------------------------------------------------------
SAMPLE_CFDI = open(os.path.join(REPO, "fixtures", "cfdis",
                                "01_gasto_operativo_papeleria.xml")).read()

MATCHING_TXN = {
    "id": "SPEI-DEMO-1",
    "date": "2026-07-01",
    "description": "Pago papeleria",
    "amount": 1160.00,
    "type": "EGRESO",
    "reference": "9165172a-2af8-4469-84a3-c532c88d0dd3",
    "bank_account": "BBVA",
}


@pytest.fixture(scope="module")
def seed_db(tmp_path_factory):
    """Puebla una BD SQLite temporal con el dataset demo (seed=42)."""
    db_path = str(tmp_path_factory.mktemp("demo") / "demo.db")
    ds = seed_demo.generar_dataset(42)
    conn = sqlite3.connect(db_path)
    try:
        seed_demo.poblar_db(conn, ds)
    finally:
        conn.close()
    return db_path


@pytest.fixture(scope="module")
def seed_dataset():
    return seed_demo.generar_dataset(42)


# ---------------------------------------------------------------------------
# 1. Seed data
# ---------------------------------------------------------------------------
def test_seed_dataset_determinista_y_realista(seed_dataset):
    ds = seed_dataset
    assert len(ds["tenants"]) == 3
    assert len(ds["clientes"]) == 15  # 5/tenant
    assert len(ds["cfdis"]) == 300    # 100/tenant
    assert len(ds["transacciones"]) == 150  # 50/tenant
    assert len(ds["nominas"]) == 30   # 10/tenant
    assert len(ds["documents"]) == 15 # 5/tenant
    # Determinista
    ds2 = seed_demo.generar_dataset(42)
    assert ds["cfdis"] == ds2["cfdis"]
    # Un CFDI realista: total = subtotal + iva (16%)
    c = ds["cfdis"][0]
    assert abs(float(c["total"]) - (float(c["subtotal"]) + float(c["iva"]))) < 0.01


def test_seed_puebla_bd_con_tenant_isolation(seed_db):
    conn = sqlite3.connect(seed_db)
    try:
        tenants = dict(conn.execute(
            "SELECT id, name FROM tenants").fetchall())
        assert set(tenants) == {1, 2, 3}
        counts = dict(conn.execute(
            "SELECT tenant_id, COUNT(*) FROM invoices GROUP BY tenant_id").fetchall())
        assert set(counts.values()) == {100}
        tx = dict(conn.execute(
            "SELECT tenant_id, COUNT(*) FROM bank_transactions GROUP BY tenant_id").fetchall())
        assert set(tx.values()) == {50}
        bad = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE tenant_id NOT IN (1,2,3)").fetchone()[0]
        assert bad == 0
    finally:
        conn.close()


def test_seed_db_es_abrible_por_la_app(seed_db):
    """La app (Database + migraciones) debe poder abrir la BD del seed."""
    db = Database(seed_db, migrate=False)
    assert db.count_invoices() == 300
    assert len(db.list_tenants()) == 3


# ---------------------------------------------------------------------------
# 2 + 3 + 4. Pipeline end-to-end, consistencia y conciliación
# ---------------------------------------------------------------------------
def test_pipeline_end_to_end_con_seed(seed_dataset):
    # Transacciones bancarias de ejemplo tomadas del seed.
    bank = [{
        "id": t["tx_id"], "date": t["fecha"], "description": t["descripcion"],
        "amount": abs(float(t["monto"])),
        "type": "INGRESO" if t["tipo"] == "ingreso" else "EGRESO",
        "reference": t["referencia"], "bank_account": t["banco"],
    } for t in seed_dataset["transacciones"][:20]]

    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("cfdi_demo.xml", SAMPLE_CFDI)],
        tenant_id="1", periodo="2026-07",
        bank_transactions=[MATCHING_TXN] + bank,
    )
    assert result["status"] == "completed"
    assert result["cfdis_parsed"] == 1 and result["cfdis_adapted"] == 1
    assert result["polizas_count"] >= 1
    assert result["errors"] == []
    assert result["reconciliation"] is not None
    assert result["reconciliation"]["period"] == "2026-07"


def test_consistencia_cfdi_asientos():
    parsed = parse_cfdi_4(SAMPLE_CFDI)
    adapted = to_bookkeeping_format(parsed)
    assert abs(float(adapted["total"]) - 1160.0) < 0.01
    assert abs(float(adapted["subtotal"]) - 1000.0) < 0.01
    assert abs(float(adapted["iva"]) - 160.0) < 0.01

    orch = EndToEndOrchestrator()
    pjob = orch.bookkeeping.process_cfdis(
        cfdis=[adapted], tenant_id="1", periodo="2026-07",
        bank_transactions=[MATCHING_TXN],
    )
    assert pjob.stage.value == "completed"
    assert len(pjob.polizas) >= 1
    # Pólizas cuadradas y que reflejan el monto del CFDI.
    assert all(p.cuadrada for p in pjob.polizas)
    assert abs(float(pjob.polizas[0].total_debe) - 1160.0) < 0.01


def test_conciliacion_produce_matches():
    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("cfdi_demo.xml", SAMPLE_CFDI)],
        tenant_id="1", periodo="2026-07",
        bank_transactions=[MATCHING_TXN],
    )
    rec = result["reconciliation"]
    assert rec is not None
    assert "report" in rec
    assert len(rec.get("poliza_matches", [])) >= 1


# ---------------------------------------------------------------------------
# 5. Health endpoint
# ---------------------------------------------------------------------------
def test_health_endpoint_reporta_modulos_ok(seed_db):
    db = Database(seed_db, migrate=False)
    async def _auth():
        return {"key": "k", "tenant_id": "1", "user_id": "u"}
    app = FastAPI()
    app.include_router(build_health_router(db, _auth))
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["invoices"] == 300
    assert body["tenants"] == 3

    d = client.get("/health/detailed")
    assert d.status_code == 200
    assert d.json()["db"]["status"] == "ok"


# ---------------------------------------------------------------------------
# 6. POST /api/v1/pipeline/run
# ---------------------------------------------------------------------------
def _auth_factory(tenant: str):
    async def _dep():
        return {"key": "k", "tenant_id": tenant, "user_id": "u1"}
    return _dep


def test_pipeline_router_run_flujo_completo():
    app = FastAPI()
    app.include_router(build_pipeline_router(db=None, require_api_key=_auth_factory("1")))
    client = TestClient(app)

    resp = client.post("/api/v1/pipeline/run", json={
        "cfdis": [{"filename": "cfdi_demo.xml", "content": SAMPLE_CFDI}],
        "periodo": "2026-07",
        "bank_transactions": [MATCHING_TXN],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "completed"
    assert body["polizas_count"] >= 1
    assert body["reconciliation"] is not None


# ---------------------------------------------------------------------------
# 7. Reportes gerenciales con datos del demo
# ---------------------------------------------------------------------------
def test_reportes_gerenciales_muestran_datos_demo():
    app = FastAPI()
    app.include_router(build_reportes_gerenciales_router(
        db=None, require_api_key=_auth_factory("1")))
    client = TestClient(app)

    m = client.post("/api/v1/reportes/monthly", json={
        "tenant_id": "1", "month": 7, "year": 2026,
        "revenue": 1250000.0, "expenses": 680000.0, "taxes_paid": 95000.0,
        "invoices_count": 100,
    })
    assert m.status_code == 200
    report = m.json()["report"]
    assert report["tenant_id"] == "1"
    assert report["revenue"] == 1250000.0

    k = client.post("/api/v1/reportes/kpi", json={
        "tenant_id": "1", "period": "2026-07",
        "revenue": 1250000.0, "expenses": 680000.0, "profit": 570000.0,
        "invoices_count": 100, "avg_ticket": 12500.0, "days_to_collect": 30.0,
    })
    assert k.status_code == 200


# ---------------------------------------------------------------------------
# 8. Tenant isolation en el pipeline
# ---------------------------------------------------------------------------
def test_pipeline_tenant_isolation_no_mezcla():
    orch = EndToEndOrchestrator()
    orch.upload_cfdis(xml_files=[("a.xml", SAMPLE_CFDI)], tenant_id="TENANT_A",
                      periodo="2026-07", bank_transactions=[MATCHING_TXN])
    orch.upload_cfdis(xml_files=[("b.xml", SAMPLE_CFDI)], tenant_id="TENANT_B",
                      periodo="2026-07", bank_transactions=[MATCHING_TXN])
    jobs_a = orch.bookkeeping.get_jobs(tenant_id="TENANT_A")
    assert len(jobs_a) >= 1
    assert all(j.tenant_id == "TENANT_A" for j in jobs_a)
    jobs_b = orch.bookkeeping.get_jobs(tenant_id="TENANT_B")
    assert all(j.tenant_id == "TENANT_B" for j in jobs_b)
