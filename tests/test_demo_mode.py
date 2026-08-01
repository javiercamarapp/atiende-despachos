# -*- coding: utf-8 -*-
"""
test_demo_mode.py — Tests for Likida AI Enterprise demo mode.

10 tests covering:
  1. is_demo_mode() activation
  2. Demo health endpoint
  3. Demo status endpoint
  4. Demo process single CFDI
  5. Demo process-all batch
  6. Demo invoices list
  7. Demo stats endpoint
  8. Demo analytics endpoint
  9. Demo upload (simulated file)
 10. Demo dashboard summary KPIs
"""
from __future__ import annotations

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.demo.routes import is_demo_mode, mount_demo_routes
from b2b_ai.demo.mock_data import (
    DEMO_CFDI_SAMPLES,
    DEMO_INVOICES,
    DEMO_STATS,
    DEMO_ANALYTICS,
    DEMO_DASHBOARD_SUMMARY,
    demo_process_result,
)


# ------------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------------ #

def _make_demo_app() -> FastAPI:
    """Create a FastAPI app with demo routes mounted."""
    app = FastAPI(title="Likida AI Enterprise — Demo Test")
    mount_demo_routes(app)
    return app


@pytest.fixture()
def client():
    """TestClient for the demo app."""
    app = _make_demo_app()
    return TestClient(app)


# ------------------------------------------------------------------------ #
# Test 1: is_demo_mode() activation
# ------------------------------------------------------------------------ #

def test_is_demo_mode_detects_env(monkeypatch):
    """is_demo_mode() returns True when DEMO_MODE=true/1/yes."""
    monkeypatch.setenv("DEMO_MODE", "true")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "1")
    assert is_demo_mode() is True

    monkeypatch.setenv("DEMO_MODE", "yes")
    assert is_demo_mode() is True


def test_is_demo_mode_off_by_default(monkeypatch):
    """is_demo_mode() returns False when DEMO_MODE is unset or empty."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert is_demo_mode() is False

    monkeypatch.setenv("DEMO_MODE", "")
    assert is_demo_mode() is False

    monkeypatch.setenv("DEMO_MODE", "false")
    assert is_demo_mode() is False


# ------------------------------------------------------------------------ #
# Test 2: Demo health endpoint
# ------------------------------------------------------------------------ #

def test_demo_health(client):
    """GET /api/demo/health returns healthy status."""
    resp = client.get("/api/demo/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "demo"
    assert "timestamp" in data


# ------------------------------------------------------------------------ #
# Test 3: Demo status endpoint
# ------------------------------------------------------------------------ #

def test_demo_status(client):
    """GET /api/demo/status returns processing stats."""
    resp = client.get("/api/demo/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "demo"
    assert data["total_processed"] == len(DEMO_CFDI_SAMPLES)
    assert data["results_count"] == len(DEMO_INVOICES)
    assert data["status"] == "running"


# ------------------------------------------------------------------------ #
# Test 4: Demo process single CFDI
# ------------------------------------------------------------------------ #

def test_demo_process_single(client):
    """POST /api/demo/process returns a single CFDI processing result."""
    resp = client.post("/api/demo/process?sample_index=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    result = data["result"]
    assert "datos" in result
    assert "clasificacion" in result
    assert "anomalias" in result
    assert result["datos"]["version"] == "4.0"
    assert result["datos"]["folio_fiscal"]  # UUID present


def test_demo_process_specific_index(client):
    """POST /api/demo/process with index=3 returns the high-amount invoice."""
    resp = client.post("/api/demo/process?sample_index=3")
    assert resp.status_code == 200
    data = resp.json()
    result = data["result"]
    # Invoice #3 (Finanzas y Seguros) should have an anomaly
    assert len(result["anomalias"]) > 0
    assert result["anomalias"][0]["tipo"] == "monto_atipico"


# ------------------------------------------------------------------------ #
# Test 5: Demo process-all batch
# ------------------------------------------------------------------------ #

def test_demo_process_all(client):
    """GET /api/demo/process-all returns all 10 CFDIs with summary."""
    resp = client.get("/api/demo/process-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["processed"] == len(DEMO_CFDI_SAMPLES)
    assert data["errors"] == []
    assert "summary" in data
    assert data["summary"]["monto_total"] > 0
    assert data["summary"]["iva_total"] > 0
    assert "por_categoria" in data["summary"]
    assert len(data["results"]) == len(DEMO_CFDI_SAMPLES)


# ------------------------------------------------------------------------ #
# Test 6: Demo invoices list
# ------------------------------------------------------------------------ #

def test_demo_invoices(client):
    """GET /api/demo/invoices returns a list of mock invoices."""
    resp = client.get("/api/demo/invoices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == len(DEMO_INVOICES)
    assert len(data["invoices"]) == len(DEMO_INVOICES)
    inv = data["invoices"][0]
    assert "emisor_rfc" in inv
    assert "total" in inv
    assert "categoria" in inv


def test_demo_invoice_detail(client):
    """GET /api/demo/invoices/{id} returns a single invoice."""
    resp = client.get("/api/demo/invoices/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert "folio_fiscal" in data

    # Non-existent invoice
    resp404 = client.get("/api/demo/invoices/9999")
    assert resp404.status_code == 404


# ------------------------------------------------------------------------ #
# Test 7: Demo stats endpoint
# ------------------------------------------------------------------------ #

def test_demo_stats(client):
    """GET /api/demo/stats returns global stats."""
    resp = client.get("/api/demo/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["invoices_total"] > 0
    assert "report" in data
    assert "audit_calls" in data
    assert data["report"]["monto_total"] > 0


# ------------------------------------------------------------------------ #
# Test 8: Demo analytics endpoint
# ------------------------------------------------------------------------ #

def test_demo_analytics(client):
    """GET /api/demo/analytics returns analytics data."""
    resp = client.get("/api/demo/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "resumen" in data
    assert "tendencia_mensual" in data
    assert "top_emisores" in data
    assert "anomalias" in data
    assert data["resumen"]["total_facturas"] > 0

    # With period override
    resp2 = client.get("/api/demo/analytics?periodo=2026-Q4")
    assert resp2.status_code == 200
    assert resp2.json()["periodo"] == "2026-Q4"


# ------------------------------------------------------------------------ #
# Test 9: Demo upload (simulated file)
# ------------------------------------------------------------------------ #

def test_demo_upload(client):
    """POST /api/demo/upload with XML file returns mock processing result."""
    xml_content = b'<?xml version="1.0"?><cfdi:Comprobante>demo</cfdi:Comprobante>'
    resp = client.post(
        "/api/demo/upload",
        files={"file": ("demo_test.xml", xml_content, "application/xml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["archivo"] == "demo_test.xml"
    assert "datos" in data
    assert "clasificacion" in data


def test_demo_upload_rejects_non_xml(client):
    """POST /api/demo/upload with non-XML file returns 400."""
    resp = client.post(
        "/api/demo/upload",
        files={"file": ("test.pdf", b"not xml", "application/pdf")},
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------------ #
# Test 10: Demo dashboard summary KPIs
# ------------------------------------------------------------------------ #

def test_demo_dashboard_summary(client):
    """GET /api/demo/dashboard/summary returns KPIs and trends."""
    resp = client.get("/api/demo/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "kpis" in data
    assert "top_categories" in data
    assert "monthly_trend" in data
    assert "recent_anomalies" in data
    kpis = data["kpis"]
    assert kpis["facturas_hoy"] > 0
    assert kpis["facturas_mes"] > 0
    assert kpis["monto_mes"] > 0
    assert len(data["monthly_trend"]) >= 6


def test_demo_dashboard_kpi(client):
    """GET /api/demo/dashboard/kpi returns KPI dict only."""
    resp = client.get("/api/demo/dashboard/kpi")
    assert resp.status_code == 200
    data = resp.json()
    assert "facturas_mes" in data
    assert "tasa_procesamiento" in data


# ------------------------------------------------------------------------ #
# Mock data unit tests
# ------------------------------------------------------------------------ #

def test_demo_process_result_structure():
    """demo_process_result returns correct structure."""
    result = demo_process_result(0)
    assert "id" in result
    assert "datos" in result
    assert "clasificacion" in result
    assert "anomalias" in result
    assert result["datos"]["version"] == "4.0"
    assert len(result["datos"]["conceptos"]) > 0


def test_demo_cfdi_samples_count():
    """DEMO_CFDI_SAMPLES contains 10 unique CFDI samples."""
    assert len(DEMO_CFDI_SAMPLES) == 10
    folio_fiscals = [s["folio_fiscal"] for s in DEMO_CFDI_SAMPLES]
    assert len(set(folio_fiscals)) == 10  # all unique


def test_demo_stats_consistency():
    """DEMO_STATS report totals are consistent with DEMO_INVOICES."""
    assert DEMO_STATS["invoices_total"] == len(DEMO_INVOICES)
    assert DEMO_STATS["report"]["total_facturas"] == len(DEMO_INVOICES)


def test_demo_analytics_has_anomalies():
    """DEMO_ANALYTICS includes anomaly data."""
    assert DEMO_ANALYTICS["anomalias_detectadas"] > 0
    assert len(DEMO_ANALYTICS["anomalias"]) == DEMO_ANALYTICS["anomalias_detectadas"]


def test_demo_dashboard_kpis_consistent():
    """DEMO_DASHBOARD_SUMMARY KPIs are reasonable values."""
    kpis = DEMO_DASHBOARD_SUMMARY["kpis"]
    assert kpis["facturas_mes"] > kpis["facturas_hoy"]
    assert kpis["monto_mes"] > kpis["iva_mes"]  # IVA < subtotal


def test_mount_demo_routes_adds_prefix():
    """mount_demo_routes adds /api/demo prefix to all routes."""
    app = FastAPI()
    mount_demo_routes(app)
    # Check OpenAPI schema for demo routes
    schema = app.openapi()
    paths = list(schema.get("paths", {}).keys())
    assert "/api/demo/health" in paths
    assert "/api/demo/process" in paths
    assert "/api/demo/invoices" in paths
    assert "/api/demo/stats" in paths
    assert "/api/demo/analytics" in paths
    assert "/api/demo/dashboard/summary" in paths
