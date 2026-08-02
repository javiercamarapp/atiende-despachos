# -*- coding: utf-8 -*-
"""
test_fixes_p1.py — Regression tests for the three P1/P2 bugs found by Leonardo QA
(278-qa-conciliacion-module.md, grade C).

    BUG-1 [P1] double-counting of unreconciled transactions in the report
    BUG-2 [P1] exact float equality in AMOUNT_DATE pass (should use 0.01 tolerance)
    BUG-3 [P2] stores are in-memory only; they now persist to a JSON file
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.models import (
    BankTransaction,
    CFDIReference,
    PolizaContable,
    TransactionType,
    MatchStatus,
    MatchType,
)
from b2b_ai.features.conciliacion.routes import build_conciliacion_router


# ---------------------------------------------------------------------------
# BUG-1 — double counting of unreconciled transactions in the report
# ---------------------------------------------------------------------------

class TestBug1DoubleCounting:
    def test_report_total_is_transaction_count_not_plus_unmatched(self):
        svc = ConciliationService()
        txns = [
            BankTransaction(id="T1", date="2024-01-15", amount=1000.0,
                            type=TransactionType.INGRESO),
            BankTransaction(id="T2", date="2024-01-16", amount=500.0,
                            type=TransactionType.INGRESO),
        ]
        polizas = [
            PolizaContable(id="P1", fecha="2024-01-15", monto=1000.0),   # matches T1
            PolizaContable(id="P2", fecha="2024-01-16", monto=999.0),    # won't match T2
        ]
        results = svc.reconcile_bank_statement(txns, polizas)
        report = svc.generate_reconciliation_report(results, period="2024-01")

        # 1 matched + 1 unmatched = 2 transactions total.
        # Before the fix total was len(all_matches) + len(unmatched_bank) = 3,
        # and match_rate was 33.33% instead of 50%.
        assert report.total_transactions == 2
        assert report.matched == 1
        assert report.unmatched == 1
        assert report.match_rate == 50.0

    def test_reconcile_endpoint_summary_not_double_counted(self, tmp_path):
        client = _client(tmp_path, tenant="t-a")
        payload = {
            "bank_transactions": [
                {"id": "T1", "date": "2024-01-15", "amount": 1000.0, "type": "INGRESO",
                 "description": "", "reference": "", "bank_account": ""},
                {"id": "T2", "date": "2024-01-16", "amount": 500.0, "type": "INGRESO",
                 "description": "", "reference": "", "bank_account": ""},
            ],
            "polizas": [
                {"id": "P1", "fecha": "2024-01-15", "monto": 1000.0},
                {"id": "P2", "fecha": "2024-01-16", "monto": 999.0},
            ],
            "period": "2024-01",
            "tolerance_days": 3,
        }
        r = client.post("/api/v1/conciliacion/reconcile", json=payload)
        assert r.status_code == 200, r.text
        summary = r.json()["summary"]
        assert summary["total_transactions"] == 2
        assert summary["match_rate"] == 50.0


# ---------------------------------------------------------------------------
# BUG-2 — exact float equality in AMOUNT_DATE pass
# ---------------------------------------------------------------------------

class TestBug2FloatEquality:
    def test_amount_date_poliza_tolerates_epsilon(self):
        svc = ConciliationService(date_tolerance_days=3)
        txn = BankTransaction(id="T1", date="2024-01-15", amount=1000.0,
                              type=TransactionType.INGRESO)
        # amount differs by 0.005 (< 0.01); date differs by 1 day (within tolerance),
        # so the EXACT pass (same date) is skipped and AMOUNT_DATE must apply.
        pol = PolizaContable(id="P1", fecha="2024-01-16", monto=1000.005)
        results = svc.reconcile_bank_statement([txn], [pol])
        m = results["poliza_matches"][0]
        assert m.status == MatchStatus.MATCHED
        assert m.match_type == MatchType.AMOUNT_DATE

    def test_amount_date_cfdi_tolerates_epsilon(self):
        svc = ConciliationService(date_tolerance_days=3)
        txn = BankTransaction(id="T1", date="2024-01-15", amount=1000.0,
                              type=TransactionType.INGRESO)
        cfdi = CFDIReference(
            uuid="U1", fecha="2024-01-16", rfc_emisor="EMP850101AB1",
            rfc_receptor="REC900101CD2", total=999.995,  # epsilon difference
        )
        results = svc.reconcile_bank_statement([txn], cfdi_list=[cfdi])
        m = results["matches"][0]
        assert m.status == MatchStatus.MATCHED
        assert m.match_type == MatchType.AMOUNT_DATE

    def test_amount_date_still_rejects_large_difference(self):
        svc = ConciliationService(date_tolerance_days=3)
        txn = BankTransaction(id="T1", date="2024-01-15", amount=1000.0,
                              type=TransactionType.INGRESO)
        pol = PolizaContable(id="P1", fecha="2024-01-16", monto=1001.00)  # diff = 1.0
        results = svc.reconcile_bank_statement([txn], [pol])
        m = results["poliza_matches"][0]
        assert m.status == MatchStatus.UNMATCHED


# ---------------------------------------------------------------------------
# BUG-3 — persistence of the tenant-isolated stores
# ---------------------------------------------------------------------------

class TestBug3Persistence:
    def test_report_survives_router_rebuild(self, tmp_path):
        data_dir = str(tmp_path / "state")
        # First router instance writes a report.
        app1 = _app(data_dir, tenant="t-a")
        c1 = TestClient(app1)
        payload = _reconcile_payload()
        r1 = c1.post("/api/v1/conciliacion/reconcile", json=payload)
        assert r1.status_code == 200, r1.text

        # Simulate process restart: a brand new router reading the same JSON file.
        app2 = _app(data_dir, tenant="t-a")
        c2 = TestClient(app2)
        r2 = c2.get("/api/v1/conciliacion/report/2024-01")
        assert r2.status_code == 200, r2.text
        report = r2.json()["report"]
        assert report["period"] == "2024-01"
        assert report["total_transactions"] == 2

    def test_state_file_written(self, tmp_path):
        data_dir = str(tmp_path / "state")
        c1 = TestClient(_app(data_dir, tenant="t-b"))
        c1.post("/api/v1/conciliacion/reconcile", json=_reconcile_payload())
        state_file = os.path.join(data_dir, "conciliacion_state.json")
        assert os.path.exists(state_file), "state file not written"
        assert os.path.getsize(state_file) > 0

    def test_adjustments_persist_as_objects(self, tmp_path):
        # Rehydrated adjustments must be Pydantic objects so /adjustments works.
        data_dir = str(tmp_path / "state")
        TestClient(_app(data_dir, tenant="t-c")).post(
            "/api/v1/conciliacion/reconcile", json=_reconcile_payload()
        )
        # Rebuild and list adjustments; must not crash on rehydrated objects.
        client = TestClient(_app(data_dir, tenant="t-c"))
        r = client.get("/api/v1/conciliacion/adjustments")
        assert r.status_code == 200, r.text
        assert isinstance(r.json()["adjustments"], list)

    def test_tenant_isolation_preserved_after_reload(self, tmp_path):
        data_dir = str(tmp_path / "state")
        TestClient(_app(data_dir, tenant="tenant-alpha")).post(
            "/api/v1/conciliacion/reconcile", json=_reconcile_payload()
        )
        # A different tenant must not see alpha's report even after reload.
        client = TestClient(_app(data_dir, tenant="tenant-beta"))
        r = client.get("/api/v1/conciliacion/report/2024-01")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reconcile_payload() -> dict:
    return {
        "bank_transactions": [
            {"id": "T1", "date": "2024-01-15", "amount": 1000.0, "type": "INGRESO",
             "description": "", "reference": "", "bank_account": ""},
            {"id": "T2", "date": "2024-01-16", "amount": 500.0, "type": "INGRESO",
             "description": "", "reference": "", "bank_account": ""},
        ],
        "polizas": [
            {"id": "P1", "fecha": "2024-01-15", "monto": 1000.0},
            {"id": "P2", "fecha": "2024-01-16", "monto": 999.0},
        ],
        "period": "2024-01",
        "tolerance_days": 3,
    }


def _app(data_dir: str, tenant: str) -> FastAPI:
    """Build a minimal app hosting the conciliación router with a fixed tenant."""
    app = FastAPI()

    def _fake_auth():
        return {"key": "test-key", "tenant_id": tenant, "user_id": "u1"}

    router = build_conciliacion_router(
        db=None,
        require_api_key=_fake_auth,
        data_dir=data_dir,
    )
    app.include_router(router)
    return app


def _client(data_dir: str, tenant: str) -> TestClient:
    return TestClient(_app(data_dir, tenant))
