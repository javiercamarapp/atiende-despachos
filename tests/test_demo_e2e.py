# -*- coding: utf-8 -*-
"""
test_demo_e2e.py — End-to-end tests for the Likida AI Enterprise demo module.

Tests the full pipeline: generate sample data → process → produce PDF report.
Covers firm generation, PDF report generation, HTTP routes, edge cases,
and integration with existing modules.

25+ tests organized by category:
  1. Firm Generator E2E (7 tests)
  2. Report PDF Generation E2E (6 tests)
  3. Demo Routes E2E via TestClient (8 tests)
  4. Edge Cases (5 tests)
  5. Integration with Existing Modules (3 tests)
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.demo.firm_generator import (
    generate_demo_firm,
    build_executive_summary,
    _CLIENT_SEEDS,
    _PROVIDER_SEEDS,
)
from b2b_ai.demo.report_pdf import generate_roi_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_demo_app() -> FastAPI:
    """Create a FastAPI app with demo routes mounted."""
    app = FastAPI(title="Likida AI Enterprise — E2E Test")
    from b2b_ai.demo.routes import mount_demo_routes
    mount_demo_routes(app)
    return app


@pytest.fixture()
def client():
    """TestClient for the demo app."""
    app = _make_demo_app()
    return TestClient(app)


@pytest.fixture()
def firm_data():
    """Default firm data for tests that need it."""
    return generate_demo_firm(month="2026-07", seed=42)


@pytest.fixture()
def firm_data_different_seed():
    """Firm data with a different seed for reproducibility comparison."""
    return generate_demo_firm(month="2026-07", seed=99)


@pytest.fixture()
def full_report_path(tmp_path, firm_data):
    """Generate a full PDF report and return its path."""
    return generate_roi_report(firm_data, str(tmp_path))


# =========================================================================
# 1. FIRM GENERATOR E2E
# =========================================================================

class TestFirmGeneratorE2E:
    """Tests for generate_demo_firm() — the data generation pipeline."""

    def test_generate_firm_returns_all_required_sections(self, firm_data):
        """Firm data must contain all expected top-level keys."""
        required_keys = [
            "firm", "clients", "cfdis", "nominas", "anomalies",
            "roi_metrics", "top_proveedores", "top_giros",
            "month", "generated_at",
        ]
        for key in required_keys:
            assert key in firm_data, f"Missing key: {key}"

    def test_generate_firm_client_count(self, firm_data):
        """Firm must have exactly 50 clients (matching _CLIENT_SEEDS)."""
        assert len(firm_data["clients"]) == 50
        assert len(firm_data["clients"]) == len(_CLIENT_SEEDS)

    def test_generate_firm_cfdi_count_matches_target(self, firm_data):
        """CFDI count must be ~500 (±20 tolerance for distribution logic)."""
        cfdi_count = len(firm_data["cfdis"])
        assert 480 <= cfdi_count <= 520, (
            f"Expected ~500 CFDIs, got {cfdi_count}"
        )

    def test_generate_firm_cfdi_fields_complete(self, firm_data):
        """Every CFDI must have all required fields."""
        required_cfdi_fields = [
            "id", "client_id", "version", "tipo", "fecha", "serie",
            "folio", "subtotal", "total", "iva", "moneda",
            "metodo_pago", "forma_pago", "emisor_rfc", "receptor_rfc",
            "folio_fiscal", "conceptos", "status",
        ]
        for i, cfdi in enumerate(firm_data["cfdis"][:10]):  # spot-check first 10
            for field in required_cfdi_fields:
                assert field in cfdi, f"CFDI #{i} missing field: {field}"

    def test_generate_firm_revenue_distribution_sums(self, firm_data):
        """Revenue across CFDIs must be mathematically consistent."""
        cfdis = firm_data["cfdis"]
        total_from_cfdis = sum(float(c["total"]) for c in cfdis)
        total_from_roi = firm_data["roi_metrics"]["resumen_firma"]["monto_total_procesado"]
        assert abs(total_from_cfdis - total_from_roi) < 0.01, (
            f"Revenue mismatch: cfdis sum={total_from_cfdis}, roi={total_from_roi}"
        )

    def test_generate_firm_roi_calculation_correct(self, firm_data):
        """ROI metrics must be mathematically sound."""
        roi = firm_data["roi_metrics"]
        ahorro = roi["ahorro_ia"]
        comp = roi["comparativa_roi"]

        # Hours saved = (4.5 - 0.8) * num_cfdis / 60
        expected_hours = (4.5 - 0.8) * roi["resumen_firma"]["total_cfdi_procesados"] / 60
        assert abs(ahorro["total_horas_ahorradas"] - expected_hours) < 0.2

        # Monthly savings = hours * 350
        expected_savings = ahorro["total_horas_ahorradas"] * 350
        assert abs(ahorro["ahorro_mensual_mx"] - expected_savings) < 1.0

        # Annual savings = monthly * 12
        assert abs(ahorro["ahorro_anual_mx"] - ahorro["ahorro_mensual_mx"] * 12) < 0.01

        # ROI monthly = (ahorro / inversion - 1) * 100
        inversion = comp["inversion_mensual_b2b_ai"]
        expected_roi = (ahorro["ahorro_mensual_mx"] / inversion - 1) * 100
        assert abs(comp["roi_mensual_pct"] - expected_roi) < 1.0

    def test_generate_firm_reproducible_with_seed(self, firm_data, firm_data_different_seed):
        """Same seed must produce identical results; different seed must differ."""
        same_seed = generate_demo_firm(month="2026-07", seed=42)
        assert len(same_seed["cfdis"]) == len(firm_data["cfdis"])

        # Same seed → same deterministic fields (totals, client list, amounts)
        # Note: folio_fiscal uses uuid4() which is not controlled by random.seed
        same_total = sum(float(c["total"]) for c in same_seed["cfdis"])
        original_total = sum(float(c["total"]) for c in firm_data["cfdis"])
        assert abs(same_total - original_total) < 0.01

        # Same seed → same client IDs and GIs
        assert same_seed["clients"][0]["nombre"] == firm_data["clients"][0]["nombre"]

        # Different seed → different totals (random amounts vary)
        diff_total = sum(float(c["total"]) for c in firm_data_different_seed["cfdis"])
        assert abs(diff_total - original_total) > 1000.0  # significant difference


# =========================================================================
# 2. REPORT PDF GENERATION E2E
# =========================================================================

class TestReportPdfE2E:
    """Tests for generate_roi_report() — the PDF report pipeline."""

    def test_report_pdf_created_and_valid(self, firm_data, tmp_path):
        """PDF must be created and start with PDF header."""
        pdf_path = generate_roi_report(firm_data, str(tmp_path))
        assert os.path.exists(pdf_path)
        assert pdf_path.endswith(".pdf")
        with open(pdf_path, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-", f"Invalid PDF header: {header}"

    def test_report_pdf_file_size_reasonable(self, firm_data, tmp_path):
        """Multi-page ROI report should be >10KB for a reasonable document."""
        pdf_path = generate_roi_report(firm_data, str(tmp_path))
        file_size = os.path.getsize(pdf_path)
        assert file_size > 10_000, f"PDF too small: {file_size} bytes"
        # Also sanity check it's not absurdly large (< 50MB)
        assert file_size < 50_000_000, f"PDF unreasonably large: {file_size} bytes"

    def test_report_pdf_named_correctly(self, firm_data, tmp_path):
        """PDF must have the expected filename."""
        pdf_path = generate_roi_report(firm_data, str(tmp_path))
        assert os.path.basename(pdf_path) == "Likida_AI_Reporte_ROI_Demo.pdf"

    def test_report_pdf_contains_roi_content(self, firm_data, tmp_path):
        """PDF must be a valid multi-page document with expected structure."""
        pdf_path = generate_roi_report(firm_data, str(tmp_path))
        with open(pdf_path, "rb") as f:
            content = f.read()

        # Verify PDF starts with correct header
        assert content[:5] == b"%PDF-"
        # Must contain page objects (multi-page report)
        assert content.count(b"/Type /Page") >= 5, "Report should have multiple pages"
        # Must reference Helvetica fonts (used by reportlab styles)
        assert b"Helvetica" in content
        # Must be a substantial document (>5KB for a real report)
        assert len(content) > 5_000, "PDF seems too small for a report"

    def test_report_with_different_month(self, tmp_path):
        """Report generation must work with different month parameters."""
        data = generate_demo_firm(month="2026-03", seed=42)
        assert data["month"] == "2026-03"
        pdf_path = generate_roi_report(data, str(tmp_path))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 10_000

    def test_report_with_executive_summary(self, firm_data, tmp_path):
        """Report must accept a custom executive summary."""
        summary = build_executive_summary(firm_data)
        assert "periodo" in summary
        assert "resumen" in summary
        pdf_path = generate_roi_report(firm_data, str(tmp_path), executive_summary=summary)
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 10_000

    def test_report_creates_output_directory(self, firm_data, tmp_path):
        """Report must create the output directory if it doesn't exist."""
        nested_dir = str(tmp_path / "subdir" / "reports")
        pdf_path = generate_roi_report(firm_data, nested_dir)
        assert os.path.exists(pdf_path)
        assert os.path.isdir(nested_dir)


# =========================================================================
# 3. DEMO ROUTES E2E VIA TestClient
# =========================================================================

class TestDemoRoutesE2E:
    """End-to-end tests for the demo HTTP routes via TestClient."""

    def test_get_firm_returns_expected_structure(self, client):
        """GET /api/demo/firm returns full firm data with counts."""
        resp = client.get("/api/demo/firm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_count"] == 50
        assert data["cfdi_count"] >= 480
        assert "anomaly_count" in data
        assert data["anomaly_count"] > 0
        assert "month" in data
        assert "generated_at" in data

    def test_get_firm_clients_returns_client_list(self, client):
        """GET /api/demo/firm/clients returns clients with required fields."""
        resp = client.get("/api/demo/firm/clients")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 50
        assert len(data["clients"]) == 50
        c = data["clients"][0]
        for field in ["id", "nombre", "rfc", "ciudad", "giro", "tamano", "mensualidad"]:
            assert field in c, f"Client missing field: {field}"

    def test_get_firm_clients_filter_by_tamano(self, client):
        """GET /api/demo/firm/clients?tamano=grande filters correctly."""
        resp = client.get("/api/demo/firm/clients?tamano=grande")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert all(c["tamano"] == "grande" for c in data["clients"])

    def test_get_firm_cfdis_returns_cfdi_list(self, client):
        """GET /api/demo/firm/cfdi returns CFDIs with required fields."""
        resp = client.get("/api/demo/firm/cfdi?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 10
        assert data["total_in_firm"] >= 480
        c = data["cfdis"][0]
        assert "version" in c
        assert "tipo" in c
        assert "total" in c
        assert "folio_fiscal" in c

    def test_get_firm_cfdis_filter_by_tipo(self, client):
        """GET /api/demo/firm/cfdi?tipo=Nómina filters correctly."""
        resp = client.get("/api/demo/firm/cfdi?tipo=Nómina")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert all(c["tipo"] == "Nómina" for c in data["cfdis"])

    def test_get_firm_roi_returns_metrics(self, client):
        """GET /api/demo/firm/roi returns comprehensive ROI metrics."""
        resp = client.get("/api/demo/firm/roi")
        assert resp.status_code == 200
        data = resp.json()
        assert "resumen_firma" in data
        assert "ahorro_ia" in data
        assert "calidad" in data
        assert "comparativa_roi" in data
        assert "satisfaccion" in data
        assert data["ahorro_ia"]["ahorro_mensual_mx"] > 0
        assert data["calidad"]["tasa_error_ai_pct"] < data["calidad"]["tasa_error_humano_pct"]

    def test_get_firm_summary_returns_executive_summary(self, client):
        """GET /api/demo/firm/summary returns executive summary."""
        resp = client.get("/api/demo/firm/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "periodo" in data
        assert "resumen" in data
        assert data["resumen"]["cfdis_procesados"] >= 480
        assert data["resumen"]["ahorro_mensual"] > 0
        assert "kpi_cards" in data
        assert len(data["kpi_cards"]) >= 5

    def test_get_firm_report_pdf_returns_pdf(self, client):
        """GET /api/demo/firm/report-pdf returns a PDF response."""
        resp = client.get("/api/demo/firm/report-pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        # content-disposition contains the PDF filename (may be URL-encoded)
        cd = resp.headers.get("content-disposition", "")
        assert "pdf" in cd.lower(), f"Expected PDF in content-disposition: {cd}"
        # Verify the response body starts with PDF header
        assert resp.content[:5] == b"%PDF-"

    def test_get_firm_anomalies_returns_anomaly_list(self, client):
        """GET /api/demo/firm/anomalies returns anomalies with severity."""
        resp = client.get("/api/demo/firm/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert len(data["anomalies"]) == data["count"]
        a = data["anomalies"][0]
        assert "tipo" in a
        assert "severity" in a
        assert a["severity"] in ("alta", "media", "baja")

    def test_get_firm_anomalies_filter_by_severity(self, client):
        """GET /api/demo/firm/anomalies?severity=alta filters correctly."""
        resp = client.get("/api/demo/firm/anomalies?severity=alta")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert all(a["severity"] == "alta" for a in data["anomalies"])


# =========================================================================
# 4. EDGE CASES
# =========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions for the demo module."""

    def test_generate_with_different_month_days(self, tmp_path):
        """Report must handle different months (Feb=28 days, Apr=30 days, etc.)."""
        # February (28 days)
        feb_data = generate_demo_firm(month="2026-02", seed=42)
        assert feb_data["month"] == "2026-02"
        pdf_path = generate_roi_report(feb_data, str(tmp_path / "feb"))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 5_000

        # April (30 days)
        apr_data = generate_demo_firm(month="2026-04", seed=42)
        assert apr_data["month"] == "2026-04"
        pdf_path = generate_roi_report(apr_data, str(tmp_path / "apr"))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 5_000

    def test_generate_with_large_dataset(self, tmp_path):
        """Pipeline should handle a large CFDI dataset without errors."""
        data = generate_demo_firm(month="2026-07", seed=42)
        # Manually inflate the CFDI list to simulate 1000+ records
        original_cfdis = data["cfdis"]
        inflated = original_cfdis * 2
        for i, c in enumerate(inflated):
            c = dict(c)
            c["id"] = i + 1
            inflated[i] = c
        data["cfdis"] = inflated
        data["roi_metrics"]["resumen_firma"]["total_cfdi_procesados"] = len(inflated)

        pdf_path = generate_roi_report(data, str(tmp_path))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 10_000

    def test_report_with_minimal_data(self, tmp_path):
        """Report generation must handle a firm with minimal CFDI data."""
        # Create a minimal firm data structure
        minimal_data = {
            "firm": {
                "nombre": "Test Firm",
                "rfc": "TST010101AAA",
                "ciudad": "CDMX",
            },
            "clients": [
                {"id": 1, "nombre": "Client A", "rfc": "CLA010101AAA", "giro": "servicios",
                 "ciudad": "CDMX", "tamano": "pequena", "mensualidad": 3500, "status": "activo"}
            ],
            "cfdis": [
                {"id": 1, "client_id": 1, "client_nombre": "Client A", "client_rfc": "CLA010101AAA",
                 "version": "4.0", "tipo": "Ingreso", "fecha": "2026-07-01T10:00:00",
                 "serie": "A", "folio": "1", "subtotal": "1000.00", "descuento": "0.00",
                 "total": "1160.00", "iva": "160.00", "moneda": "MXN",
                 "metodo_pago": "PUE", "forma_pago": "01",
                 "emisor_rfc": "EPR010101AAA", "emisor_nombre": "Proveedor Test",
                 "emisor_regimen": "601", "receptor_rfc": "CLA010101AAA",
                 "receptor_nombre": "Client A", "folio_fiscal": "UUID-TEST-001",
                 "conceptos_count": 1,
                 "conceptos": [{"descripcion": "Servicio", "importe": "1000.00", "clave_prod_serv": "82111500"}],
                 "status": "procesado"},
            ],
            "nominas": [],
            "anomalies": [],
            "roi_metrics": {
                "periodo": "2026-07",
                "resumen_firma": {
                    "total_clientes_activos": 1,
                    "total_cfdi_procesados": 1,
                    "monto_total_procesado": 1160.0,
                    "iva_total": 160.0,
                    "ingresos_netos": 1160.0,
                    "egresos_netos": 0.0,
                    "nomina_total_firma": 0.0,
                },
                "ahorro_ia": {
                    "minutos_por_factura_antes": 4.5,
                    "minutos_por_factura_despues": 0.8,
                    "total_horas_ahorradas": 0.1,
                    "ahorro_mensual_mx": 26.25,
                    "ahorro_anual_mx": 315.0,
                    "eficiencia_porcentaje": 82.2,
                },
                "calidad": {
                    "tasa_error_humano_pct": 3.2,
                    "tasa_error_ai_pct": 0.4,
                    "mejora_calidad_factor": 8.0,
                    "anomalias_detectadas": 0,
                    "anomalias_criticas": 0,
                },
                "satisfaccion": {
                    "nps_score": 72,
                    "tiempo_respuesta_avg_seg": 1.2,
                    "disponibilidad_pct": 99.9,
                    "tickets_soporte_mes": 3,
                },
                "comparativa_roi": {
                    "inversion_mensual_b2b_ai": 8500,
                    "ahorro_operativo_mensual": 26.25,
                    "roi_mensual_pct": -99.7,
                    "payback_dias": 97.1,
                    "roi_anual_pct": -99.7,
                },
            },
            "top_proveedores": [
                {"nombre": "Proveedor Test", "facturas": 1, "monto_total": 1160.0}
            ],
            "top_giros": [
                {"giro": "servicios", "facturas": 1, "monto_total": 1160.0}
            ],
            "month": "2026-07",
            "generated_at": datetime.now().isoformat(),
        }

        pdf_path = generate_roi_report(minimal_data, str(tmp_path))
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 5_000

    def test_concurrent_report_generation(self, firm_data, tmp_path):
        """Multiple threads generating reports must not interfere with each other."""
        results = {}

        def generate_report(thread_id: int) -> str:
            subdir = str(tmp_path / f"thread_{thread_id}")
            path = generate_roi_report(firm_data, subdir)
            return path

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(generate_report, i): i for i in range(5)}
            for future in as_completed(futures):
                tid = futures[future]
                path = future.result()
                assert os.path.exists(path)
                assert os.path.getsize(path) > 10_000
                results[tid] = path

        assert len(results) == 5
        # All files should exist independently
        for path in results.values():
            assert os.path.isfile(path)

    def test_generate_firm_different_months_consistent_structure(self):
        """Different months must produce data with same structure."""
        for month in ["2026-01", "2026-06", "2026-12"]:
            data = generate_demo_firm(month=month, seed=42)
            assert data["month"] == month
            assert len(data["clients"]) == 50
            assert len(data["cfdis"]) >= 480
            assert len(data["nominas"]) == 5  # 5 employees
            assert len(data["anomalies"]) > 0
            assert "roi_metrics" in data
            assert "ahorro_ia" in data["roi_metrics"]


# =========================================================================
# 5. INTEGRATION WITH EXISTING MODULES
# =========================================================================

class TestIntegration:
    """Tests verifying compatibility with existing modules."""

    def test_generated_cfdis_match_cfdi_structure(self, firm_data):
        """Generated CFDIs must have the same structure as mock_data samples."""
        from b2b_ai.demo.mock_data import DEMO_CFDI_SAMPLES

        # Both should share these common fields
        common_fields = {
            "version", "tipo", "fecha", "folio", "subtotal", "total",
            "iva", "moneda", "metodo_pago", "forma_pago",
            "emisor_rfc", "emisor_nombre", "receptor_rfc", "receptor_nombre",
            "folio_fiscal", "conceptos",
        }

        mock_fields = set(DEMO_CFDI_SAMPLES[0].keys())
        generated_fields = set(firm_data["cfdis"][0].keys())

        # Mock data should be a subset of generated (generated has extra fields like client_id)
        assert common_fields.issubset(mock_fields), (
            f"Mock data missing: {common_fields - mock_fields}"
        )
        assert common_fields.issubset(generated_fields), (
            f"Generated data missing: {common_fields - generated_fields}"
        )

    def test_generated_cfdis_have_valid_rfcs(self, firm_data):
        """All generated RFCs must follow the 12-13 character Mexican format."""
        import re
        rfc_pattern = re.compile(r"^[A-Z]{3,4}\d{6}[A-Z0-9]{3}$")

        for cfdi in firm_data["cfdis"][:50]:  # Check first 50
            assert rfc_pattern.match(cfdi["emisor_rfc"]), (
                f"Invalid emisor RFC: {cfdi['emisor_rfc']}"
            )
            assert rfc_pattern.match(cfdi["receptor_rfc"]), (
                f"Invalid receptor RFC: {cfdi['receptor_rfc']}"
            )

    def test_generated_cfdis_concepts_match_cfdi_format(self, firm_data):
        """Each CFDI concept must have required CFDI concept fields."""
        for cfdi in firm_data["cfdis"][:20]:
            assert cfdi["conceptos_count"] >= 1
            for concepto in cfdi["conceptos"]:
                assert "descripcion" in concepto
                assert "importe" in concepto
                assert "clave_prod_serv" in concepto
                # Validate clave_prod_serv is a numeric string
                assert concepto["clave_prod_serv"].isdigit()

    def test_build_executive_summary_structure(self, firm_data):
        """Executive summary must have all required fields for the report."""
        summary = build_executive_summary(firm_data)
        assert "titulo" in summary
        assert "periodo" in summary
        assert "fecha_generacion" in summary
        assert "resumen" in summary
        assert "clientes_top5" in summary
        assert "kpi_cards" in summary

        resumen = summary["resumen"]
        for field in ["clientes_activos", "cfdis_procesados", "monto_total",
                       "iva_total", "anomalias_detectadas", "horas_ahorradas_ia",
                       "ahorro_mensual", "roi_mensual_pct", "payback_dias"]:
            assert field in resumen, f"Missing resumen field: {field}"
            assert resumen[field] is not None

    def test_full_pipeline_end_to_end(self, tmp_path):
        """Complete E2E: generate → build summary → produce PDF → verify."""
        # Step 1: Generate firm data
        data = generate_demo_firm(month="2026-07", seed=42)
        assert len(data["cfdis"]) >= 480

        # Step 2: Build executive summary
        summary = build_executive_summary(data)
        assert summary["resumen"]["cfdis_procesados"] >= 480

        # Step 3: Generate PDF report
        pdf_path = generate_roi_report(data, str(tmp_path), executive_summary=summary)
        assert os.path.exists(pdf_path)

        # Step 4: Verify PDF is valid and contains expected content
        with open(pdf_path, "rb") as f:
            content = f.read()

        assert content[:5] == b"%PDF-"
        assert len(content) > 10_000

        # Step 5: Verify data consistency
        assert data["roi_metrics"]["resumen_firma"]["total_cfdi_procesados"] == len(data["cfdis"])
        assert summary["resumen"]["cfdis_procesados"] == len(data["cfdis"])
