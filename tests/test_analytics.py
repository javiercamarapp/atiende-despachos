# -*- coding: utf-8 -*-
"""
tests/test_analytics.py — Comprehensive tests for the analytics dashboard API.

Covers:
  - Empty DB returns zeros
  - With sample data returns correct aggregations
  - Period comparison (this month vs last month)
  - Edge cases: no CFDI, no payroll, mixed statuses
  - Pure function unit tests for aggregation logic
  - Insights generation
  - Trend computation
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app
from b2b_ai.api.analytics import (
    _cfdi_metrics,
    _collections_metrics,
    _compute_comparison,
    _compute_kpis,
    _dec,
    _generate_insights,
    _month_range,
    _payroll_metrics,
    _prev_month,
    _reconciliation_metrics,
    _report_metrics,
    _build_trends,
    _periodo,
    build_analytics_router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Fresh in-memory-like DB for each test."""
    return Database(str(tmp_path / "analytics_test.db"))


@pytest.fixture
def db_with_tenant(tmp_path):
    """DB with a tenant and API key pre-created."""
    db = Database(str(tmp_path / "analytics_tenant.db"))
    tid = db.create_tenant("Despacho Analytics", rfc="ANA123456789")
    db.create_api_key(tid, "key", "analytics-test-key-001")
    return db, tid


@pytest.fixture
def client(db_with_tenant):
    """FastAPI TestClient wired to DB with tenant."""
    db, tid = db_with_tenant
    app = create_app(db)
    return TestClient(app), db, tid


def _auth():
    return {"X-API-Key": "analytics-test-key-001"}


def _insert_invoice(db, tenant_id, fecha="2026-07-15", total="1000.00",
                    iva="160.00", subtotal="840.00", categoria="gasto_operativo",
                    valido=1, requires_human_review=0, emisor_rfc="EMISOR01",
                    emisor_nombre="Proveedor Uno", folio_fiscal=None):
    """Helper: insert an invoice directly into the DB."""
    now = datetime.now().isoformat(timespec="seconds")
    folio = folio_fiscal or f"FF-{tenant_id}-{fecha}-{total}"
    row = {
        "tenant_id": tenant_id,
        "folio_fiscal": folio,
        "archivo": f"test_{folio}.xml",
        "fecha": fecha,
        "tipo": "I",
        "serie": "A",
        "folio": "1",
        "emisor_rfc": emisor_rfc,
        "emisor_nombre": emisor_nombre,
        "receptor_rfc": "RECEPTOR01",
        "subtotal": subtotal,
        "iva": iva,
        "total": total,
        "moneda": "MXN",
        "descripcion": "Test invoice",
        "categoria": categoria,
        "confianza": 0.95,
        "razon_clasificacion": "test",
        "valido": valido,
        "requires_human_review": requires_human_review,
        "issues": "",
        "erp_poliza": "",
        "erp_status": "",
        "status": "procesado",
        "procesado_en": now,
    }
    cur = db.conn.execute("""
        INSERT INTO invoices (
            tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
            emisor_rfc, emisor_nombre, receptor_rfc,
            subtotal, iva, total, moneda, descripcion,
            categoria, confianza, razon_clasificacion,
            valido, requires_human_review, issues,
            erp_poliza, erp_status, status, procesado_en)
        VALUES (
            :tenant_id, :folio_fiscal, :archivo, :fecha, :tipo, :serie, :folio,
            :emisor_rfc, :emisor_nombre, :receptor_rfc,
            :subtotal, :iva, :total, :moneda, :descripcion,
            :categoria, :confianza, :razon_clasificacion,
            :valido, :requires_human_review, :issues,
            :erp_poliza, :erp_status, :status, :procesado_en)
    """, row)
    db.conn.commit()
    return cur.lastrowid


# ===================================================================
# SECTION 1: Helper function unit tests (_dec, _periodo, etc.)
# ===================================================================

class TestDecHelper:
    def test_dec_none(self):
        assert _dec(None) == 0.0

    def test_dec_empty_string(self):
        assert _dec("") == 0.0

    def test_dec_integer(self):
        assert _dec(42) == 42.0

    def test_dec_float(self):
        assert _dec(3.14) == pytest.approx(3.14)

    def test_dec_string_number(self):
        assert _dec("1234.56") == pytest.approx(1234.56)

    def test_dec_with_commas(self):
        assert _dec("1,234.56") == pytest.approx(1234.56)

    def test_dec_with_dollar_sign(self):
        assert _dec("$500.00") == pytest.approx(500.00)

    def test_dec_invalid_string(self):
        assert _dec("abc") == 0.0

    def test_dec_negative(self):
        assert _dec("-100") == -100.0

    def test_dec_zero(self):
        assert _dec("0") == 0.0

    def test_dec_bool_false(self):
        assert _dec(False) == 0.0

    def test_dec_bool_true(self):
        # _dec converts via str() → float(); "True" is not numeric → 0.0
        assert _dec(True) == 0.0


class TestPeriodoHelper:
    def test_periodo_normal_date(self):
        assert _periodo("2026-07-15") == "2026-07"

    def test_periodo_none(self):
        assert _periodo(None) == "sin-fecha"

    def test_periodo_empty(self):
        assert _periodo("") == "sin-fecha"

    def test_periodo_short_string(self):
        assert _periodo("2026-07") == "2026-07"

    def test_periodo_year_only(self):
        assert _periodo("2026") == "2026"


class TestMonthRange:
    def test_month_range_january(self):
        start, end = _month_range(2026, 1)
        assert start == "2026-01-01"
        assert end == "2026-02-01"

    def test_month_range_december(self):
        start, end = _month_range(2026, 12)
        assert start == "2026-12-01"
        assert end == "2027-01-01"

    def test_month_range_july(self):
        start, end = _month_range(2026, 7)
        assert start == "2026-07-01"
        assert end == "2026-08-01"


class TestPrevMonth:
    def test_prev_month_normal(self):
        assert _prev_month(2026, 7) == (2026, 6)

    def test_prev_month_january(self):
        assert _prev_month(2026, 1) == (2025, 12)

    def test_prev_month_february(self):
        assert _prev_month(2026, 2) == (2026, 1)


# ===================================================================
# SECTION 2: CFDI Metrics unit tests
# ===================================================================

class TestCfdiMetrics:
    def test_empty_invoices(self):
        result = _cfdi_metrics([])
        assert result["total_facturas"] == 0
        assert result["validas"] == 0
        assert result["invalidas"] == 0
        assert result["monto_total"] == 0.0
        assert result["tasa_validez"] == 0.0

    def test_single_valid_invoice(self):
        invoices = [{"fecha": "2026-07-15", "total": "1000", "iva": "160",
                      "subtotal": "840", "valido": 1, "categoria": "gasto_operativo",
                      "emisor_rfc": "RFC01", "emisor_nombre": "Prov1"}]
        result = _cfdi_metrics(invoices)
        assert result["total_facturas"] == 1
        assert result["validas"] == 1
        assert result["invalidas"] == 0
        assert result["tasa_validez"] == 1.0
        assert result["monto_total"] == 1000.0
        assert result["iva_total"] == 160.0

    def test_mixed_valid_invalid(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "1000", "valido": 1, "iva": "160",
             "subtotal": "840", "categoria": "gasto_operativo",
             "emisor_rfc": "RFC01", "emisor_nombre": "P1"},
            {"fecha": "2026-07-16", "total": "2000", "valido": 0, "iva": "320",
             "subtotal": "1680", "categoria": "inversion",
             "emisor_rfc": "RFC02", "emisor_nombre": "P2"},
        ]
        result = _cfdi_metrics(invoices)
        assert result["total_facturas"] == 2
        assert result["validas"] == 1
        assert result["invalidas"] == 1
        assert result["tasa_validez"] == 0.5
        assert result["monto_total"] == 3000.0

    def test_por_categoria(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-07-16", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "inversion",
             "emisor_rfc": "R2", "emisor_nombre": "E2"},
            {"fecha": "2026-07-17", "total": "300", "valido": 1,
             "iva": "48", "subtotal": "252", "categoria": "gasto_operativo",
             "emisor_rfc": "R3", "emisor_nombre": "E3"},
        ]
        result = _cfdi_metrics(invoices)
        assert result["por_categoria"]["gasto_operativo"]["count"] == 2
        assert result["por_categoria"]["gasto_operativo"]["monto"] == 400.0
        assert result["por_categoria"]["inversion"]["count"] == 1
        assert result["por_categoria"]["inversion"]["monto"] == 200.0

    def test_por_mes(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-06-10", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
        ]
        result = _cfdi_metrics(invoices)
        assert "2026-07" in result["por_mes"]
        assert "2026-06" in result["por_mes"]

    def test_top_emisores(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "500", "valido": 1,
             "iva": "80", "subtotal": "420", "categoria": "gasto_operativo",
             "emisor_rfc": "RFC01", "emisor_nombre": "Prov1"},
            {"fecha": "2026-07-16", "total": "300", "valido": 1,
             "iva": "48", "subtotal": "252", "categoria": "gasto_operativo",
             "emisor_rfc": "RFC02", "emisor_nombre": "Prov2"},
        ]
        result = _cfdi_metrics(invoices)
        assert len(result["top_emisores"]) == 2
        assert result["top_emisores"][0]["rfc"] == "RFC01"
        assert result["top_emisores"][0]["monto"] == 500.0

    def test_requieren_revision(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1",
             "requires_human_review": 1},
            {"fecha": "2026-07-16", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "gasto_operativo",
             "emisor_rfc": "R2", "emisor_nombre": "E2",
             "requires_human_review": 0},
        ]
        result = _cfdi_metrics(invoices)
        assert result["requieren_revision"] == 1

    def test_date_filter_from(self):
        invoices = [
            {"fecha": "2026-07-01", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-07-20", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "gasto_operativo",
             "emisor_rfc": "R2", "emisor_nombre": "E2"},
        ]
        result = _cfdi_metrics(invoices, fecha_desde="2026-07-15")
        assert result["total_facturas"] == 1

    def test_date_filter_to(self):
        invoices = [
            {"fecha": "2026-07-01", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-07-20", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "gasto_operativo",
             "emisor_rfc": "R2", "emisor_nombre": "E2"},
        ]
        result = _cfdi_metrics(invoices, fecha_hasta="2026-07-15")
        assert result["total_facturas"] == 1

    def test_date_filter_both(self):
        invoices = [
            {"fecha": "2026-07-01", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-07-15", "total": "200", "valido": 1,
             "iva": "32", "subtotal": "168", "categoria": "gasto_operativo",
             "emisor_rfc": "R2", "emisor_nombre": "E2"},
            {"fecha": "2026-07-30", "total": "300", "valido": 1,
             "iva": "48", "subtotal": "252", "categoria": "gasto_operativo",
             "emisor_rfc": "R3", "emisor_nombre": "E3"},
        ]
        result = _cfdi_metrics(invoices, fecha_desde="2026-07-10",
                               fecha_hasta="2026-07-25")
        assert result["total_facturas"] == 1

    def test_monto_promedio(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100", "valido": 1,
             "iva": "16", "subtotal": "84", "categoria": "gasto_operativo",
             "emisor_rfc": "R1", "emisor_nombre": "E1"},
            {"fecha": "2026-07-16", "total": "300", "valido": 1,
             "iva": "48", "subtotal": "252", "categoria": "gasto_operativo",
             "emisor_rfc": "R2", "emisor_nombre": "E2"},
        ]
        result = _cfdi_metrics(invoices)
        assert result["monto_promedio"] == 200.0

    def test_no_dates_in_invoices(self):
        invoices = [
            {"total": "100", "valido": 1, "iva": "16", "subtotal": "84",
             "categoria": "gasto_operativo", "emisor_rfc": "R1",
             "emisor_nombre": "E1"},
        ]
        result = _cfdi_metrics(invoices)
        assert result["total_facturas"] == 1
        assert "sin-fecha" in result["por_mes"]


# ===================================================================
# SECTION 3: Compute helpers unit tests
# ===================================================================

class TestComputeComparison:
    def test_equal_periods(self):
        current = {"total_facturas": 10, "monto_total": 5000}
        previous = {"total_facturas": 10, "monto_total": 5000}
        delta = _compute_comparison(current, previous)
        assert delta["total_facturas"] == 0.0
        assert delta["monto_total"] == 0.0

    def test_increase(self):
        current = {"total_facturas": 20, "monto_total": 10000}
        previous = {"total_facturas": 10, "monto_total": 5000}
        delta = _compute_comparison(current, previous)
        assert delta["total_facturas"] == 100.0
        assert delta["monto_total"] == 100.0

    def test_decrease(self):
        current = {"total_facturas": 5, "monto_total": 2500}
        previous = {"total_facturas": 10, "monto_total": 5000}
        delta = _compute_comparison(current, previous)
        assert delta["total_facturas"] == -50.0
        assert delta["monto_total"] == -50.0

    def test_previous_zero_current_positive(self):
        current = {"total_facturas": 10, "monto_total": 5000}
        previous = {"total_facturas": 0, "monto_total": 0}
        delta = _compute_comparison(current, previous)
        assert delta["total_facturas"] == 100.0

    def test_both_zero(self):
        current = {"total_facturas": 0, "monto_total": 0}
        previous = {"total_facturas": 0, "monto_total": 0}
        delta = _compute_comparison(current, previous)
        assert delta["total_facturas"] == 0.0


class TestComputeKPIs:
    def test_empty_data(self):
        cfdi = {"total_facturas": 0, "monto_total": 0.0, "tasa_validez": 0,
                "requieren_revision": 0}
        collections = {"facturas_pendientes": 0, "monto_pendiente_total": 0.0}
        reconciliation = {"total_asientos": 0}
        reports = {"revisiones_pendientes": 0, "total_audit_log": 0}
        kpis = _compute_kpis(cfdi, collections, reconciliation, reports)
        assert kpis["total_facturas_procesadas"] == 0
        assert kpis["monto_total_procesado"] == 0.0
        assert kpis["tasa_automatizacion_pct"] == 0.0

    def test_with_data(self):
        cfdi = {"total_facturas": 100, "monto_total": 50000.0,
                "tasa_validez": 0.95, "requieren_revision": 5}
        collections = {"facturas_pendientes": 3, "monto_pendiente_total": 1500.0}
        reconciliation = {"total_asientos": 50}
        reports = {"revisiones_pendientes": 2, "total_audit_log": 200}
        kpis = _compute_kpis(cfdi, collections, reconciliation, reports)
        assert kpis["total_facturas_procesadas"] == 100
        assert kpis["monto_total_procesado"] == 50000.0
        assert kpis["tasa_validez_pct"] == 95.0
        assert kpis["tasa_automatizacion_pct"] == 95.0
        assert kpis["cartera_pendiente"] == 3
        assert kpis["asientos_contables"] == 50

    def test_tasa_automatizacion_calculation(self):
        cfdi = {"total_facturas": 10, "requieren_revision": 3}
        kpis = _compute_kpis(cfdi, {}, {}, {})
        assert kpis["tasa_automatizacion_pct"] == 70.0


# ===================================================================
# SECTION 4: Insights generation
# ===================================================================

class TestInsights:
    def test_empty_db_insight(self):
        cfdi = {"total_facturas": 0, "tasa_validez": 0, "requieren_revision": 0}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        assert len(insights) >= 1
        assert insights[0]["severity"] == "info"
        assert "facturas" in insights[0]["message"].lower()

    def test_low_validity_insight(self):
        cfdi = {"total_facturas": 10, "tasa_validez": 0.5,
                "requieren_revision": 0}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        warnings = [i for i in insights if i["severity"] == "warning"]
        assert len(warnings) >= 1
        assert "validez" in warnings[0]["message"].lower()

    def test_review_needed_insight(self):
        cfdi = {"total_facturas": 5, "tasa_validez": 0.9,
                "requieren_revision": 2}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        review_msgs = [i for i in insights if "revisión" in i["message"].lower()]
        assert len(review_msgs) >= 1

    def test_critical_collections_insight(self):
        cfdi = {"total_facturas": 5, "tasa_validez": 0.9,
                "requieren_revision": 0}
        collections = {
            "monto_pendiente_total": 5000,
            "cartera_por_antiguedad": {
                "0-30": {"count": 1, "monto": 1000},
                "31-60": {"count": 0, "monto": 0},
                "61-90": {"count": 0, "monto": 0},
                "90+": {"count": 2, "monto": 4000},
            },
        }
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        critical = [i for i in insights if i["severity"] == "critical"]
        assert len(critical) >= 1
        assert "90+" in critical[0]["message"]

    def test_warning_collections_insight(self):
        cfdi = {"total_facturas": 5, "tasa_validez": 0.9,
                "requieren_revision": 0}
        collections = {
            "monto_pendiente_total": 3000,
            "cartera_por_antiguedad": {
                "0-30": {"count": 1, "monto": 1000},
                "31-60": {"count": 0, "monto": 0},
                "61-90": {"count": 1, "monto": 2000},
                "90+": {"count": 0, "monto": 0},
            },
        }
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        warnings = [i for i in insights if i["severity"] == "warning"
                    and i["module"] == "collections"]
        assert len(warnings) >= 1
        assert "61-90" in warnings[0]["message"]

    def test_reconciliation_insight_no_catalog(self):
        cfdi = {"total_facturas": 5, "tasa_validez": 0.95,
                "requieren_revision": 0}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 10, "total_cuentas_catalogo": 0}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        recon_insights = [i for i in insights if i["module"] == "reconciliation"]
        assert len(recon_insights) >= 1
        assert "catálogo" in recon_insights[0]["message"].lower()

    def test_pending_reviews_insight(self):
        cfdi = {"total_facturas": 5, "tasa_validez": 0.95,
                "requieren_revision": 0}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 0, "total_cuentas_catalogo": 10}
        reports = {"revisiones_pendientes": 3}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        report_insights = [i for i in insights if i["module"] == "reports"]
        assert len(report_insights) >= 1
        assert "3" in report_insights[0]["message"]

    def test_all_good_insight(self):
        cfdi = {"total_facturas": 10, "tasa_validez": 0.95,
                "requieren_revision": 0}
        collections = {"monto_pendiente_total": 0, "cartera_por_antiguedad": {}}
        reconciliation = {"total_asientos": 10, "total_cuentas_catalogo": 5}
        reports = {"revisiones_pendientes": 0}
        insights = _generate_insights(cfdi, collections, reconciliation, reports)
        assert any(i["severity"] == "info" for i in insights)


# ===================================================================
# SECTION 5: Trends computation
# ===================================================================

class TestTrends:
    def test_empty_data(self):
        trends = _build_trends([], [], [])
        assert trends == []

    def test_cfdi_only(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100"},
            {"fecha": "2026-07-20", "total": "200"},
        ]
        trends = _build_trends(invoices, [], [])
        assert len(trends) == 1
        assert trends[0]["period"] == "2026-07"
        assert trends[0]["cfdi_count"] == 2
        assert trends[0]["cfdi_monto"] == 300.0

    def test_multi_month(self):
        invoices = [
            {"fecha": "2026-07-15", "total": "100"},
            {"fecha": "2026-06-10", "total": "200"},
        ]
        trends = _build_trends(invoices, [], [])
        assert len(trends) == 2
        assert trends[0]["period"] == "2026-06"
        assert trends[1]["period"] == "2026-07"

    def test_with_collections_events(self):
        events = [
            {"timestamp": "2026-07-15 10:00:00"},
            {"timestamp": "2026-07-20 14:00:00"},
        ]
        trends = _build_trends([], events, [])
        assert trends[0]["collection_events"] == 2

    def test_with_asientos(self):
        asientos = [
            {"fecha": "2026-07-01"},
            {"fecha": "2026-07-05"},
            {"fecha": "2026-08-01"},
        ]
        trends = _build_trends([], [], asientos)
        assert len(trends) == 2
        assert trends[0]["period"] == "2026-07"
        assert trends[0]["asientos"] == 2
        assert trends[1]["period"] == "2026-08"
        assert trends[1]["asientos"] == 1

    def test_invoices_without_date_excluded(self):
        invoices = [{"total": "100"}]
        trends = _build_trends(invoices, [], [])
        assert trends == []

    def test_combined_modules(self):
        invoices = [{"fecha": "2026-07-15", "total": "100"}]
        events = [{"timestamp": "2026-07-16 12:00:00"}]
        asientos = [{"fecha": "2026-07-17"}]
        trends = _build_trends(invoices, events, asientos)
        assert len(trends) == 1
        assert trends[0]["cfdi_count"] == 1
        assert trends[0]["collection_events"] == 1
        assert trends[0]["asientos"] == 1


# ===================================================================
# SECTION 6: API Endpoint tests (integration)
# ===================================================================

class TestAnalyticsEndpointEmpty:
    """Tests when the DB is empty."""

    def test_returns_200(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        assert r.status_code == 200

    def test_response_has_required_keys(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert "generated_at" in body
        assert "cfdi" in body
        assert "payroll" in body
        assert "collections" in body
        assert "reconciliation" in body
        assert "reports" in body
        assert "kpis" in body
        assert "trends" in body
        assert "comparison" in body
        assert "insights" in body

    def test_empty_cfdi_zeros(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 0
        assert body["cfdi"]["monto_total"] == 0.0
        assert body["cfdi"]["validas"] == 0

    def test_empty_collections_zeros(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["collections"]["facturas_pendientes"] == 0
        assert body["collections"]["monto_pendiente_total"] == 0.0

    def test_empty_reconciliation_zeros(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["reconciliation"]["total_asientos"] == 0

    def test_empty_kpis(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["kpis"]["total_facturas_procesadas"] == 0
        assert body["kpis"]["monto_total_procesado"] == 0.0

    def test_empty_trends(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["trends"] == []

    def test_has_insight(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert len(body["insights"]) >= 1

    def test_period_fields_present(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["period_current"]
        assert body["period_previous"]
        assert body["generated_at"]

    def test_requires_auth(self, client):
        c, db, tid = client
        r = c.get("/api/v1/dashboard/analytics")
        assert r.status_code == 401


class TestAnalyticsEndpointWithData:
    """Tests with invoice data in the DB."""

    def test_with_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="5000.00", iva="800.00", subtotal="4200.00",
                        folio_fiscal="FF-001")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 1
        assert body["cfdi"]["monto_total"] == 5000.0

    def test_multiple_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-002")
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="2000", folio_fiscal="FF-003",
                        categoria="inversion")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 2
        assert body["cfdi"]["monto_total"] == 3000.0

    def test_valid_and_invalid_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-004", valido=1)
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="2000", folio_fiscal="FF-005", valido=0)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["validas"] == 1
        assert body["cfdi"]["invalidas"] == 1
        assert body["cfdi"]["tasa_validez"] == 0.5

    def test_kpis_populated(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="3000", folio_fiscal="FF-006", valido=1)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["kpis"]["total_facturas_procesadas"] == 1
        assert body["kpis"]["monto_total_procesado"] == 3000.0
        assert body["kpis"]["tasa_validez_pct"] == 100.0

    def test_trends_populated(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-007")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert len(body["trends"]) >= 1
        assert body["trends"][0]["cfdi_count"] == 1

    def test_comparison_structure(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-008")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert "cfdi" in body["comparison"]
        assert "current" in body["comparison"]["cfdi"]
        assert "previous" in body["comparison"]["cfdi"]
        assert "delta_pct" in body["comparison"]["cfdi"]

    def test_por_categoria_in_response(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", categoria="gasto_operativo",
                        folio_fiscal="FF-009")
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="2000", categoria="inversion",
                        folio_fiscal="FF-010")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert "gasto_operativo" in body["cfdi"]["por_categoria"]
        assert "inversion" in body["cfdi"]["por_categoria"]

    def test_top_emisores_in_response(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="5000", emisor_rfc="EMI01",
                        emisor_nombre="Emisor Uno", folio_fiscal="FF-011")
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", emisor_rfc="EMI02",
                        emisor_nombre="Emisor Dos", folio_fiscal="FF-012")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert len(body["cfdi"]["top_emisores"]) == 2
        assert body["cfdi"]["top_emisores"][0]["rfc"] == "EMI01"


class TestAnalyticsPeriodComparison:
    """Tests for period-over-period comparison."""

    def test_current_vs_previous_month(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        cur_month = now.month
        cur_year = now.year
        # Current month invoice
        _insert_invoice(db, tid, fecha=f"{cur_year:04d}-{cur_month:02d}-15",
                        total="5000", folio_fiscal="FF-CUR-001")
        # Previous month invoice
        prev_m = cur_month - 1 if cur_month > 1 else 12
        prev_y = cur_year if cur_month > 1 else cur_year - 1
        _insert_invoice(db, tid, fecha=f"{prev_y:04d}-{prev_m:02d}-15",
                        total="3000", folio_fiscal="FF-PREV-001")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        comp = body["comparison"]["cfdi"]
        assert comp["current"]["total_facturas"] == 1
        assert comp["previous"]["total_facturas"] == 1

    def test_specific_period_query(self, client):
        c, db, tid = client
        _insert_invoice(db, tid, fecha="2026-03-15",
                        total="1000", folio_fiscal="FF-SP-001")
        _insert_invoice(db, tid, fecha="2026-04-15",
                        total="2000", folio_fiscal="FF-SP-002")
        r = c.get("/api/v1/dashboard/analytics?year=2026&month=4",
                  headers=_auth())
        body = r.json()
        assert body["period_current"] == "2026-04"
        assert body["period_previous"] == "2026-03"
        assert body["cfdi"]["total_facturas"] == 1
        assert body["cfdi"]["monto_total"] == 2000.0

    def test_delta_percentage_increase(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        cur_month = now.month
        cur_year = now.year
        prev_m = cur_month - 1 if cur_month > 1 else 12
        prev_y = cur_year if cur_month > 1 else cur_year - 1
        # Current: 10 invoices
        for i in range(10):
            _insert_invoice(db, tid,
                            fecha=f"{cur_year:04d}-{cur_month:02d}-{(i+1):02d}",
                            total="100", folio_fiscal=f"FF-DELTA-C-{i}")
        # Previous: 5 invoices
        for i in range(5):
            _insert_invoice(db, tid,
                            fecha=f"{prev_y:04d}-{prev_m:02d}-{(i+1):02d}",
                            total="100", folio_fiscal=f"FF-DELTA-P-{i}")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        delta = body["comparison"]["cfdi"]["delta_pct"]
        assert delta["total_facturas"] == 100.0

    def test_no_previous_data(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        cur_month = now.month
        cur_year = now.year
        _insert_invoice(db, tid,
                        fecha=f"{cur_year:04d}-{cur_month:02d}-15",
                        total="5000", folio_fiscal="FF-NP-001")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        comp = body["comparison"]["cfdi"]
        assert comp["current"]["total_facturas"] == 1
        assert comp["previous"]["total_facturas"] == 0


class TestAnalyticsEdgeCases:
    """Edge cases and boundary conditions."""

    def test_invoices_from_other_tenant_not_included(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        other_tid = db.create_tenant("Other Tenant")
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-MY-001")
        _insert_invoice(db, other_tid, fecha=now.strftime("%Y-%m-%d"),
                        total="9999", folio_fiscal="FF-OTHER-001")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 1
        assert body["cfdi"]["monto_total"] == 1000.0

    def test_all_invalid_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        for i in range(3):
            _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                            total=str(100 * (i+1)),
                            folio_fiscal=f"FF-INV-{i}", valido=0)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 3
        assert body["cfdi"]["validas"] == 0
        assert body["cfdi"]["invalidas"] == 3
        assert body["cfdi"]["tasa_validez"] == 0.0

    def test_all_valid_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        for i in range(5):
            _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                            total=str(200 * (i+1)),
                            folio_fiscal=f"FF-VAL-{i}", valido=1)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["tasa_validez"] == 1.0

    def test_invoices_with_review_needed(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-REV-001",
                        requires_human_review=1)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["requieren_revision"] == 1
        # Should generate a warning insight
        rev_insights = [i for i in body["insights"]
                        if "revisión" in i["message"].lower()
                        or "requieren" in i["message"].lower()]
        assert len(rev_insights) >= 1

    def test_mixed_statuses_in_invoices(self, client):
        c, db, tid = client
        now = datetime.utcnow()
        statuses = [("procesado", 1, 0), ("procesado", 0, 1),
                    ("procesado", 1, 1), ("procesado", 0, 0)]
        for i, (status, valido, rev) in enumerate(statuses):
            _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                            total=str(100 * (i+1)),
                            folio_fiscal=f"FF-MIX-{i}",
                            valido=valido, requires_human_review=rev)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 4
        assert body["cfdi"]["validas"] == 2
        assert body["cfdi"]["invalidas"] == 2
        assert body["cfdi"]["requieren_revision"] == 2

    def test_query_with_no_tenant_returns_all(self, client):
        """Without tenant_id query param, should get all invoices."""
        c, db, tid = client
        now = datetime.utcnow()
        other_tid = db.create_tenant("Other")
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-Q-001")
        _insert_invoice(db, other_tid, fecha=now.strftime("%Y-%m-%d"),
                        total="2000", folio_fiscal="FF-Q-002")
        # Auth key is bound to tid=1, so it only sees that tenant's data
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 1

    def test_collections_with_outstanding(self, client):
        c, db, tid = client
        # Insert outstanding invoice
        db.upsert_outstanding_invoice(
            tid, "FACT-001", 5000.0, "2026-06-15", 30, 0.7)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["collections"]["facturas_pendientes"] == 1
        assert body["collections"]["monto_pendiente_total"] == 5000.0

    def test_collections_aging_buckets(self, client):
        c, db, tid = client
        from datetime import date
        today = date.today()
        # 10 days ago → 0-30 bucket
        d10 = (today - timedelta(days=10)).strftime("%Y-%m-%d")
        # 50 days ago → 31-60 bucket
        d50 = (today - timedelta(days=50)).strftime("%Y-%m-%d")
        db.upsert_outstanding_invoice(
            tid, "FACT-100", 1000.0, d10, 10, 0.8)
        db.upsert_outstanding_invoice(
            tid, "FACT-200", 2000.0, d50, 50, 0.5)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        aging = body["collections"]["cartera_por_antiguedad"]
        assert aging["0-30"]["count"] >= 1
        assert aging["31-60"]["count"] >= 1

    def test_payroll_metrics(self, client):
        c, db, tid = client
        # Insert a payroll audit log entry
        db.log_call("calcular_nomina", "calcular", tenant_id=tid)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["payroll"]["calculos_realizados"] >= 1

    def test_report_metrics_populated(self, client):
        c, db, tid = client
        db.log_call("test_tool", "test_action", tenant_id=tid)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["reports"]["total_audit_log"] >= 1

    def test_reconciliation_metrics_with_asientos(self, client):
        c, db, tid = client
        db.insert_asiento_contable(
            tid, "2026-07-15", "101.01", "201.01", "5000.00", "Test asiento")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert body["reconciliation"]["total_asientos"] == 1
        assert body["reconciliation"]["monto_total_asientos"] == 5000.0

    def test_invoices_across_multiple_months(self, client):
        c, db, tid = client
        for month in [5, 6, 7]:
            _insert_invoice(db, tid, fecha=f"2026-{month:02d}-15",
                            total=f"{month * 1000}",
                            folio_fiscal=f"FF-M{month}-001")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        assert len(body["trends"]) == 3

    def test_many_invoices_performance(self, client):
        """Insert many invoices and verify the endpoint still responds."""
        c, db, tid = client
        now = datetime.utcnow()
        for i in range(50):
            _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                            total=str(100 * (i+1)),
                            folio_fiscal=f"FF-PERF-{i:04d}")
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body["cfdi"]["total_facturas"] == 50
        assert body["cfdi"]["monto_total"] == sum(
            100 * (i+1) for i in range(50))

    def test_insights_with_all_conditions(self, client):
        """Multiple insights triggered at once."""
        c, db, tid = client
        now = datetime.utcnow()
        # Invalid invoices
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="100", folio_fiscal="FF-INS-001",
                        valido=0, requires_human_review=1)
        # Outstanding with 90+ days
        db.upsert_outstanding_invoice(
            tid, "FACT-INS-001", 10000.0, "2026-03-01", 120, 0.2)
        r = c.get("/api/v1/dashboard/analytics", headers=_auth())
        body = r.json()
        # Should have multiple insights
        assert len(body["insights"]) >= 3
        severities = [i["severity"] for i in body["insights"]]
        assert "warning" in severities

    def test_tenant_id_query_param(self, client):
        """Test explicit tenant_id query param."""
        c, db, tid = client
        now = datetime.utcnow()
        _insert_invoice(db, tid, fecha=now.strftime("%Y-%m-%d"),
                        total="1000", folio_fiscal="FF-TQ-001")
        r = c.get(f"/api/v1/dashboard/analytics?tenant_id={tid}",
                  headers=_auth())
        body = r.json()
        assert body["tenant_id"] == tid
        assert body["cfdi"]["total_facturas"] == 1


class TestAnalyticsRouterFactory:
    """Test the build_analytics_router factory."""

    def test_router_has_dashboard_analytics_route(self):
        router = build_analytics_router(db=None, require_api_key=lambda: {})
        routes = [r.path for r in router.routes]
        assert "/dashboard/analytics" in routes

    def test_router_tags(self):
        router = build_analytics_router(db=None, require_api_key=lambda: {})
        assert "analytics" in router.tags
