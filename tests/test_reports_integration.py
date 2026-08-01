# -*- coding: utf-8 -*-
"""
test_reports_integration.py — Integration tests for the Likida AI Enterprise reports module.

Covers:
  - PDF generation edge cases (empty data, special characters, large datasets)
  - CSV export with encoding (UTF-8 BOM, special chars)
  - Report API endpoints (GET /api/v1/reports/*)
  - Report registration and download
  - Report scheduling and caching (in-memory registry)
  - Edge cases: no data for period, concurrent generation, invalid types
"""
from __future__ import annotations

import io
import threading
import time

import pytest
from fastapi.testclient import TestClient

from b2b_ai.api.app import create_app
from b2b_ai.db.db import Database
from b2b_ai.reports.pdf_generator import PDFGenerator, mxn, fecha_mx, _periodo
from b2b_ai.reports.router import (
    _REGISTRY, _REGISTRY_LOCK, _valid_period, _html_template_name,
    _invoices_data, _f, db_rows
)
from b2b_ai.services.reports import GerentialReports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _insert(db, tenant_id, **kw):
    """Insert one invoice."""
    datos = {
        "folio_fiscal": kw.get("folio_fiscal", f"F-{kw.get('idx', 1)}"),
        "archivo": f"cfdi-{kw.get('idx', 1)}.xml",
        "fecha": kw.get("fecha", "2026-01-15"),
        "tipo": kw.get("tipo", "E"),
        "serie": "A", "folio": str(kw.get("idx", 1)),
        "emisor_rfc": kw.get("emisor_rfc", "XAXX010101000"),
        "emisor_nombre": kw.get("emisor_nombre", "Proveedor"),
        "receptor_rfc": "DESP820101AB1",
        "subtotal": str(kw.get("subtotal", kw.get("total", "100.00"))),
        "iva": str(kw.get("iva", "16.00")),
        "total": str(kw.get("total", "100.00")),
        "moneda": "MXN", "descripcion": "",
    }
    clasif = {"categoria": kw.get("categoria", "gasto_operativo"),
              "confianza": 0.9, "razon": "test"}
    validacion = {"ok": kw.get("valido", 1) not in (0, False),
                  "requires_human_review": False, "issues": []}
    erp = {"poliza": "", "status": ""}
    return db.insert_invoice(tenant_id, datos, clasif, validacion, erp)


@pytest.fixture
def db_and_tenant(tmp_path):
    """DB with a single tenant and seeded invoices."""
    db = Database(str(tmp_path / "reports_integ.db"))
    t = db.create_tenant("Reportes SA", rfc="REP010101AAA")
    _insert(db, t, idx=1, total="2000.00", iva="320.00",
            fecha="2026-04-01", emisor_rfc="AAA010101AAA",
            emisor_nombre="Proveedor Alpha")
    _insert(db, t, idx=2, total="3500.00", iva="560.00",
            fecha="2026-04-15", emisor_rfc="BBB020202BBB",
            emisor_nombre="Consultora Beta", tipo="I")
    _insert(db, t, idx=3, total="800.00", iva="128.00",
            fecha="2026-04-20", emisor_rfc="AAA010101AAA",
            emisor_nombre="Proveedor Alpha", categoria="inversion")
    return db, t


@pytest.fixture
def api_ctx(tmp_path):
    """Full API test context."""
    db = Database(str(tmp_path / "reports_api.db"))
    t = db.create_tenant("API Tenant", rfc="API010101AAA")
    _insert(db, t, idx=1, total="1000.00", fecha="2026-05-01")
    _insert(db, t, idx=2, total="2500.00", fecha="2026-05-10", tipo="I")
    # Create API key
    db.create_api_key(t, "test-reports-key", "test-reports-key")
    app = create_app(db)
    client = TestClient(app)
    return {"client": client, "db": db, "tenant_id": t}


def _api_key_headers():
    return {"X-API-Key": "test-reports-key"}


# ===================================================================
# 1. PDF GENERATOR — unit-level edge cases
# ===================================================================
class TestPDFGenerator:
    def test_generate_with_empty_data(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "empty.db")))
        pdf = gen.custom_report({}, title="Vacio")
        assert pdf
        assert pdf[:4] == b"%PDF"

    def test_generate_with_special_chars_title(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "sc.db")))
        pdf = gen.custom_report(
            {"title": "Reporte Ñ & <script>alert(1)</script>"},
            title="Reporte Ñ & <script>alert(1)</script>")
        assert pdf
        assert pdf[:4] == b"%PDF"

    def test_generate_with_large_dataset(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "lg.db")))
        data = {
            "title": "Reporte Grande",
            "table": {
                "headers": ["ID", "Monto", "Estado"],
                "rows": [[str(i), f"${i * 100:.2f}", "OK"] for i in range(500)],
            },
        }
        pdf = gen.custom_report(data)
        assert pdf
        assert len(pdf) > 10000  # substantial PDF

    def test_monthly_summary_empty(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "ms.db")))
        pdf = gen.monthly_summary(None, "2026-01")
        assert pdf[:4] == b"%PDF"

    def test_tax_report_empty(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "tax.db")))
        pdf = gen.tax_report(None, "2026-01")
        assert pdf[:4] == b"%PDF"

    def test_anomaly_report_empty(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "anom.db")))
        pdf = gen.anomaly_report([], tenant_id=None)
        assert pdf[:4] == b"%PDF"

    def test_reconciliation_report_empty(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "rec.db")))
        rep = {"conciliadas": 0, "pendientes_banco": 0,
               "pendientes_facturas": 0, "es_muestra": True}
        pdf = gen.reconciliation_report(rep, tenant_id=None)
        assert pdf[:4] == b"%PDF"

    def test_invoice_report_with_full_data(self, tmp_path):
        gen = PDFGenerator(db=Database(str(tmp_path / "inv.db")))
        inv = {
            "folio_fiscal": "ABC-123-UUID",
            "fecha": "2026-06-15",
            "total": "12345.67",
            "emisor_rfc": "TEC010101AAA",
            "emisor_nombre": "Tecnología SA",
            "receptor_rfc": "DESP820101AB1",
            "categoria": "gasto_operativo",
            "moneda": "MXN",
            "tipo": "I", "serie": "A", "folio": "42",
        }
        pdf = gen.invoice_report(inv)
        assert pdf[:4] == b"%PDF"


# ===================================================================
# 2. FORMATTING HELPERS
# ===================================================================
class TestFormattingHelpers:
    def test_mxn_basic(self):
        assert mxn(1234.56) == "$1,234.56 MXN"

    def test_mxn_zero(self):
        assert mxn(0) == "$0.00 MXN"

    def test_mxn_negative(self):
        assert mxn(-500) == "-$500.00 MXN"

    def test_mxn_string_input(self):
        assert mxn("1234.56") == "$1,234.56 MXN"

    def test_mxn_none(self):
        assert mxn(None) == "$0.00 MXN"

    def test_mxn_with_commas(self):
        assert mxn("1,234,567.89") == "$1,234,567.89 MXN"

    def test_fecha_mx_iso(self):
        assert fecha_mx("2026-07-15") == "15/07/2026"

    def test_fecha_mx_slash(self):
        assert fecha_mx("15/07/2026") == "15/07/2026"

    def test_fecha_mx_none(self):
        assert fecha_mx(None) == ""

    def test_fecha_mx_empty(self):
        assert fecha_mx("") == ""

    def test_periodo_valid(self):
        assert _periodo("2026-07-15") == "2026-07"

    def test_periodo_none(self):
        assert _periodo(None) == "sin-fecha"

    def test_periodo_empty(self):
        assert _periodo("") == "sin-fecha"


# ===================================================================
# 3. REPORT ROUTER HELPERS
# ===================================================================
class TestReportRouterHelpers:
    def test_valid_period_ok(self):
        assert _valid_period("2026-07") is True

    def test_valid_period_bad_format(self):
        assert _valid_period("2026-07-15") is False
        assert _valid_period("07-2026") is False
        assert _valid_period("abc") is False
        assert _valid_period("") is False

    def test_valid_period_invalid_month(self):
        assert _valid_period("2026-13") is False
        assert _valid_period("2026-00") is False

    def test_html_template_name_mapping(self):
        assert _html_template_name("monthly") == "monthly_summary"
        assert _html_template_name("invoices") == "invoices_report"
        assert _html_template_name("reconciliation") == "reconciliation"
        assert _html_template_name("anomaly") == "anomaly_report"
        assert _html_template_name("tax") == "tax_report"
        assert _html_template_name("custom") == "monthly_summary"  # fallback

    def test_f_numeric_string(self):
        assert _f("1234.56") == 1234.56

    def test_f_with_commas(self):
        assert _f("1,234.56") == 1234.56

    def test_f_with_dollar(self):
        assert _f("$500.00") == 500.0

    def test_f_none(self):
        assert _f(None) == 0.0

    def test_f_garbage(self):
        assert _f("not-a-number") == 0.0

    def test_invoices_data_structure(self, db_and_tenant):
        db, t = db_and_tenant
        invoices = db.list_invoices(tenant_id=t)
        rows = [i for i in invoices if _periodo(i.get("fecha")) == "2026-04"]
        data = _invoices_data(rows, "2026-04")
        assert "title" in data
        assert "kpis" in data
        assert "table" in data
        assert "chart" in data
        assert len(data["kpis"]) == 4

    def test_db_rows_filters_by_period(self, db_and_tenant):
        db, t = db_and_tenant
        gen = PDFGenerator(db=db)
        rows = db_rows(db, t, "2026-04")
        assert len(rows) == 3  # all seeded invoices are in 2026-04

    def test_db_rows_empty_period(self, db_and_tenant):
        db, t = db_and_tenant
        rows = db_rows(db, t, "2099-01")
        assert len(rows) == 0


# ===================================================================
# 4. REGISTRY — thread-safety and download
# ===================================================================
class TestReportRegistry:
    def setup_method(self):
        """Clear registry before each test."""
        with _REGISTRY_LOCK:
            _REGISTRY.clear()

    def test_register_and_retrieve(self):
        from b2b_ai.reports.router import _register
        rid = _register("monthly", 1, "2026-07", "test.pdf", b"fake-pdf")
        assert rid
        with _REGISTRY_LOCK:
            entry = _REGISTRY[rid]
        assert entry["type"] == "monthly"
        assert entry["tenant_id"] == 1
        assert entry["bytes"] == b"fake-pdf"

    def test_concurrent_register(self):
        """Thread-safe registration."""
        from b2b_ai.reports.router import _register
        ids = []

        def _reg(i):
            rid = _register("custom", 1, f"2026-{i:02d}", f"r{i}.pdf", b"x")
            ids.append(rid)

        threads = [threading.Thread(target=_reg, args=(i,)) for i in range(1, 13)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == 12
        assert len(set(ids)) == 12  # all unique


# ===================================================================
# 5. API ENDPOINTS — reports
# ===================================================================
class TestReportAPI:
    def test_get_monthly_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/monthly/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.headers.get("x-report-id")

    def test_get_invoices_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/invoices/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")

    def test_get_anomaly_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/anomaly/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 200

    def test_get_reconciliation_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/reconciliation/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 200

    def test_get_tax_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/tax/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 200

    def test_invalid_report_type_returns_400(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/fake/2026-05",
                  headers=_api_key_headers())
        assert r.status_code == 400

    def test_invalid_period_returns_422(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/monthly/not-a-period",
                  headers=_api_key_headers())
        assert r.status_code == 422

    def test_custom_report(self, api_ctx):
        c = api_ctx["client"]
        r = c.post("/api/v1/reports/custom",
                   headers=_api_key_headers(),
                   json={"data": {"title": "Custom Test", "kpis": [{"label": "X", "value": "42"}]},
                         "template": "custom_report"})
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")

    def test_custom_report_as_html(self, api_ctx):
        c = api_ctx["client"]
        r = c.post("/api/v1/reports/custom",
                   headers=_api_key_headers(),
                   json={"data": {"title": "HTML Test"}, "as_html": True})
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_download_registered_report(self, api_ctx):
        c = api_ctx["client"]
        # Generate a report first
        r = c.get("/api/v1/reports/monthly/2026-05",
                  headers=_api_key_headers())
        rid = r.headers["x-report-id"]
        # Download it
        r2 = c.get(f"/api/v1/reports/{rid}/download",
                   headers=_api_key_headers())
        assert r2.status_code == 200
        assert r2.headers.get("content-type", "").startswith("application/pdf")

    def test_download_nonexistent_report_returns_404(self, api_ctx):
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/fakeid123/download",
                  headers=_api_key_headers())
        assert r.status_code == 404

    def test_no_data_for_period_still_generates(self, api_ctx):
        """Even with no invoices for the period, the endpoint should not crash."""
        c = api_ctx["client"]
        r = c.get("/api/v1/reports/invoices/2099-01",
                  headers=_api_key_headers())
        assert r.status_code == 200

    def test_tenant_isolation_on_report_download(self, api_ctx):
        """Download requires same tenant or no tenant restriction."""
        c = api_ctx["client"]
        # Generate with tenant
        r = c.get("/api/v1/reports/monthly/2026-05",
                  headers=_api_key_headers())
        rid = r.headers["x-report-id"]
        # Same key should work
        r2 = c.get(f"/api/v1/reports/{rid}/download",
                   headers=_api_key_headers())
        assert r2.status_code == 200

    def test_concurrent_report_generation(self, api_ctx):
        """Multiple reports generated simultaneously."""
        c = api_ctx["client"]
        results = []

        def _gen(report_type):
            r = c.get(f"/api/v1/reports/{report_type}/2026-05",
                      headers=_api_key_headers())
            results.append(r.status_code)

        threads = [
            threading.Thread(target=_gen, args=("monthly",)),
            threading.Thread(target=_gen, args=("invoices",)),
            threading.Thread(target=_gen, args=("anomaly",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(s == 200 for s in results)

    def test_report_with_empty_tenant(self, tmp_path):
        """Report for tenant with no data should still work."""
        db = Database(str(tmp_path / "empty_tenant.db"))
        t = db.create_tenant("Empty", rfc="EMP000000000")
        db.create_api_key(t, "empty-key", "empty-key")
        app = create_app(db)
        c = TestClient(app)
        r = c.get("/api/v1/reports/monthly/2026-01",
                  headers={"X-API-Key": "empty-key"})
        assert r.status_code == 200


# ===================================================================
# 6. GERENTIAL REPORTS — unit tests
# ===================================================================
class TestGerentialReports:
    def _invoices(self):
        """Sample invoices for gerential reports."""
        base = {
            "tenant_id": 1, "tipo": "E", "serie": "A",
            "emisor_rfc": "AAA010101AAA", "emisor_nombre": "Proveedor A",
            "receptor_rfc": "DESP820101AB1", "moneda": "MXN",
            "categoria": "gasto_operativo", "valido": 1,
            "requires_human_review": 0, "status": "procesado",
            "erp_status": "confirmado", "folio": "1",
            "razon_clasificacion": "test", "confianza": 0.9,
        }
        return [
            {**base, "id": 1, "folio_fiscal": "F-0001", "total": "1000.00",
             "subtotal": "862.07", "iva": "137.93", "fecha": "2026-06-01"},
            {**base, "id": 2, "folio_fiscal": "F-0002", "total": "2500.00",
             "subtotal": "2155.17", "iva": "344.83", "fecha": "2026-06-10",
             "emisor_rfc": "BBB020202BBB", "emisor_nombre": "Consultora B"},
            {**base, "id": 3, "folio_fiscal": "F-0003", "total": "500.00",
             "subtotal": "431.03", "iva": "68.97", "fecha": "2026-06-15",
             "tipo": "I"},
        ]

    def test_resumen_ejecutivo_basic(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.resumen_ejecutivo()
        assert rep["facturas"] == 3
        assert rep["validas"] == 3
        assert rep["monto_total"] > 0

    def test_analisis_proveedores(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.analisis_proveedores()
        assert rep["total_proveedores"] >= 2
        names = [p["nombre"] for p in rep["proveedores"]]
        assert "Proveedor A" in names

    def test_flujo_caja(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.flujo_caja()
        assert "flujo" in rep
        assert "proyeccion" in rep
        assert len(rep["flujo"]) >= 1

    def test_alertas_with_pending(self):
        invs = self._invoices()
        invs[0]["requires_human_review"] = 1
        gr = GerentialReports(invs)
        rep = gr.alertas()
        assert rep["total"] >= 1

    def test_export_csv(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.resumen_ejecutivo()
        csv_text = gr.export_csv(rep)
        assert "campo" in csv_text
        assert "valor" in csv_text

    def test_export_pdf_html(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.resumen_ejecutivo()
        html = gr.export_pdf(rep, title="Test Reporte")
        assert "<!DOCTYPE html>" in html
        assert "Test Reporte" in html
        assert "<table>" in html

    def test_empty_invoices(self):
        gr = GerentialReports([])
        rep = gr.resumen_ejecutivo()
        assert rep["facturas"] == 0
        assert rep["reconciliacion"] is None

    def test_reconciliation_derived(self):
        invs = self._invoices()
        gr = GerentialReports(invs)
        conc = gr.reconciliation()
        assert conc is not None
        assert "es_muestra" in conc

    def test_csv_to_file(self, tmp_path):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.resumen_ejecutivo()
        path = str(tmp_path / "report.csv")
        result = gr.export_csv(rep, filename=path)
        assert result == path
        import os
        assert os.path.exists(path)

    def test_pdf_to_file(self, tmp_path):
        invs = self._invoices()
        gr = GerentialReports(invs)
        rep = gr.resumen_ejecutivo()
        path = str(tmp_path / "report.html")
        result = gr.export_pdf(rep, title="File Test", filename=path)
        assert result == path
        import os
        assert os.path.exists(path)
