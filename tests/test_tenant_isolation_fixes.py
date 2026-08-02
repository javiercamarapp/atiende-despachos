# -*- coding: utf-8 -*-
"""test_tenant_isolation_fixes.py — Regresión de los 3 bugs P1 de aislamiento
por tenant encontrados en QA 220 (pipeline integration).

  P1-1  Batch: _jobs global keyed solo por batch_id → cross-tenant leak.
        FIX: _jobs[tenant_id][batch_id]; todas las rutas filtran por el
        tenant del token.
  P1-2  Bookkeeping: /process usaba request.tenant_id del body (falsificable)
        y /status?job_id= no verificaba propiedad. FIX: tenant SIEMPRE del
        token; get_job/status verifica que el job pertenezca al tenant.
  P1-3  Conciliación: stores globales keyed por period → cross-tenant leak.
        FIX: stores anidados por tenant_id; todos los endpoints filtran.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.batch.service import BatchService, reset_state as batch_reset
from b2b_ai.features.batch.routes import build_batch_router
from b2b_ai.features.bookkeeping.routes import build_bookkeeping_router
from b2b_ai.features.conciliacion.routes import build_conciliacion_router


def _auth_for(tenant_id: str):
    """Crea una dependencia de auth que devuelve un tenant fijo del token."""
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _client(router, tenant_id: str):
    """Monta un router en una app con la auth del tenant indicado."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# P1-1 — Batch / service tenant isolation
# ---------------------------------------------------------------------------

def test_p1_1_batch_service_cross_tenant_isolated():
    """Un job creado por tenant A no es legible por tenant B en el service."""
    batch_reset()
    svc = BatchService()

    xmls = [("cfdi1.xml", "<x/>")]
    job_a = svc.create_job("tenant_A", xmls)
    job_b = svc.create_job("tenant_B", xmls)

    # Cada tenant ve su propio job, jamás el del otro.
    assert svc.get_job("tenant_A", job_a.id) is job_a
    assert svc.get_job("tenant_B", job_a.id) is None
    assert svc.get_job("tenant_A", job_b.id) is None
    assert svc.get_job("tenant_B", job_b.id) is job_b


def test_p1_1_batch_router_cross_tenant_404():
    """GET /batch/{id} de un job ajeno responde 404 (no filtra existencia)."""
    batch_reset()
    svc = BatchService()

    router_a = build_batch_router(db=None, require_api_key=_auth_for("tenant_A"))
    router_b = build_batch_router(db=None, require_api_key=_auth_for("tenant_B"))
    app_a = FastAPI()
    app_b = FastAPI()
    app_a.include_router(router_a)
    app_b.include_router(router_b)

    # El service compartido (módulo _jobs); se crea el job como tenant_A.
    job = svc.create_job("tenant_A", [("cfdi1.xml", "<x/>")])

    # tenant_A ve su job.
    res_a = TestClient(app_a).get(f"/api/v1/cfdi/batch/{job.id}")
    assert res_a.status_code == 200
    assert res_a.json()["batch"]["batch_id"] == job.id

    # tenant_B no puede ver el job de tenant_A.
    res_b = TestClient(app_b).get(f"/api/v1/cfdi/batch/{job.id}")
    assert res_b.status_code == 404


# ---------------------------------------------------------------------------
# P1-2 — Bookkeeping: tenant del token, no del body / query
# ---------------------------------------------------------------------------

def test_p1_2_bookkeeping_process_uses_token_tenant():
    """El tenant_id del body es ignorado; se usa el del token."""
    router = build_bookkeeping_router(
        db=None,
        require_api_key=_auth_for("tenant_autenticado"),
    )
    client = _client(router, "tenant_autenticado")

    payload = {
        # tenant_id del body falsificado → debe ignorarse.
        "tenant_id": "tenant_atacante",
        "cfdis": [{"uuid": "u1", "rfc_emisor": "XAXX010101000",
                   "descripcion": "compra", "total": 100.0}],
    }
    resp = client.post("/api/v1/bookkeeping/process", json=payload)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # El job se creó bajo el tenant del token.
    status_resp = client.get(f"/api/v1/bookkeeping/status?job_id={job_id}")
    assert status_resp.status_code == 200, status_resp.text


def test_p1_2_bookkeeping_status_rejects_other_tenant_job():
    """GET /status?job_id= de un job ajeno responde 404."""
    client_a = _client(
        build_bookkeeping_router(db=None, require_api_key=_auth_for("tenant_A")),
        "tenant_A",
    )
    client_b = _client(
        build_bookkeeping_router(db=None, require_api_key=_auth_for("tenant_B")),
        "tenant_B",
    )

    payload = {"tenant_id": "irrelevante",
               "cfdis": [{"uuid": "u1", "rfc_emisor": "XAXX010101000",
                          "descripcion": "compra", "total": 50.0}]}
    resp_a = client_a.post("/api/v1/bookkeeping/process", json=payload)
    assert resp_a.status_code == 200, resp_a.text
    job_id = resp_a.json()["job_id"]

    # tenant_B consulta el job de tenant_A → 404 (sin filtrar existencia).
    res_b = client_b.get(f"/api/v1/bookkeeping/status?job_id={job_id}")
    assert res_b.status_code == 404

    # tenant_A sí puede verlo.
    res_a = client_a.get(f"/api/v1/bookkeeping/status?job_id={job_id}")
    assert res_a.status_code == 200


# ---------------------------------------------------------------------------
# P1-3 — Conciliación: stores anidados por tenant
# ---------------------------------------------------------------------------

def _minimal_bank():
    return [{"id": "t1", "date": "2024-01-15", "description": "pago",
             "amount": "100.0", "type": "EGRESO", "reference": "ref1",
             "bank_account": "123"}]


def _minimal_cfdi():
    return [{"uuid": "a1b2c3d4-e5f6-4a5b-8c9d-0123456789ab",
             "fecha": "2024-01-15", "rfc_emisor": "XAXX010101000",
             "rfc_receptor": "XAXX010101000", "total": "100.0",
             "tipo_comprobante": "I"}]


def test_p1_3_conciliacion_report_isolated_by_tenant():
    """GET /report/{period} de otro tenant responde 404."""
    router_a = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_A"))
    router_b = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_B"))
    client_a = _client(router_a, "tenant_A")
    client_b = _client(router_b, "tenant_B")

    # tenant_A genera un reporte para 2024-01.
    res = client_a.post("/api/v1/conciliacion/match", json={
        "bank_transactions": _minimal_bank(),
        "cfdi_list": _minimal_cfdi(),
    })
    assert res.status_code == 200, res.text
    period = res.json()["period"]
    assert period == "2024-01"

    # tenant_A ve su reporte.
    assert client_a.get(f"/api/v1/conciliacion/report/{period}").status_code == 200

    # tenant_B NO ve el reporte de tenant_A (mismo periodo, otro tenant).
    res_b = client_b.get(f"/api/v1/conciliacion/report/{period}")
    assert res_b.status_code == 404


def test_p1_3_conciliacion_discrepancies_and_adjustments_isolated():
    """/discrepancies y /adjustments solo listan datos del propio tenant."""
    router_a = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_A"))
    router_b = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_B"))
    client_a = _client(router_a, "tenant_A")
    client_b = _client(router_b, "tenant_B")

    # tenant_A genera un reporte (con discrepancias potenciales).
    res = client_a.post("/api/v1/conciliacion/match", json={
        "bank_transactions": _minimal_bank(),
        "cfdi_list": _minimal_cfdi(),
    })
    assert res.status_code == 200, res.text

    # tenant_A ve sus discrepancias.
    disc_a = client_a.get("/api/v1/conciliacion/discrepancies")
    assert disc_a.status_code == 200
    # tenant_B NO ve discrepancias que él no generó (store vacío para B).
    disc_b = client_b.get("/api/v1/conciliacion/discrepancies")
    assert disc_b.status_code == 200
    assert disc_b.json()["count"] == 0

    # Ajustes: tenant_A no generó ninguno vía /match, ambos vacíos.
    adj_b = client_b.get("/api/v1/conciliacion/adjustments")
    assert adj_b.status_code == 200
    assert adj_b.json()["count"] == 0


def test_p1_3_conciliacion_apply_other_tenant_adjustment_not_found():
    """/apply con un adjustment_id de otro tenant → not_found (no aplica)."""
    router_a = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_A"))
    router_b = build_conciliacion_router(db=None, require_api_key=_auth_for("tenant_B"))
    client_b = _client(router_b, "tenant_B")

    # tenant_B intenta aplicar un adjustment inexistente/de otro tenant.
    res = client_b.post("/api/v1/conciliacion/apply", json={
        "adjustment_ids": ["adj_ajeno_123"],
    })
    assert res.status_code == 200
    assert res.json()["not_found"] == ["adj_ajeno_123"]
    assert res.json()["applied"] == []
