# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/reports.py — GerentialReports."""
import pytest
from b2b_ai.services.reports import GerentialReports, _proximo_mes


class TestProximoMes:
    def test_basic(self):
        assert _proximo_mes("2026-07") == "2026-08"

    def test_year_boundary(self):
        assert _proximo_mes("2026-12") == "2027-01"

    def test_empty(self):
        assert _proximo_mes("") == ""

    def test_none(self):
        assert _proximo_mes(None) == ""

    def test_invalid(self):
        assert _proximo_mes("invalid") == ""


class TestGerentialReports:
    def setup_method(self):
        self.invoices = [
            {"id": 1, "fecha": "2026-07-03", "total": "1000.00",
             "subtotal": "1000.00", "iva": "160.00", "tipo": "I",
             "emisor_rfc": "RFC1", "emisor_nombre": "Proveedor A",
             "categoria": "gasto_operativo", "valido": True,
             "requires_human_review": False, "erp_status": "procesado",
             "status": "procesado", "folio_fiscal": "F1"},
            {"id": 2, "fecha": "2026-07-05", "total": "2000.00",
             "subtotal": "2000.00", "iva": "320.00", "tipo": "I",
             "emisor_rfc": "RFC2", "emisor_nombre": "Proveedor B",
             "categoria": "inversion", "valido": True,
             "requires_human_review": False, "erp_status": "procesado",
             "status": "procesado", "folio_fiscal": "F2"},
        ]
        self.gr = GerentialReports(self.invoices)

    def test_resumen_ejecutivo(self):
        r = self.gr.resumen_ejecutivo(period="2026-07")
        assert r["facturas"] == 2
        assert r["validas"] == 2

    def test_resumen_ejecutivo_empty(self):
        gr = GerentialReports([])
        r = gr.resumen_ejecutivo()
        assert r["facturas"] == 0

    def test_analisis_proveedores(self):
        r = self.gr.analisis_proveedores()
        assert r["total_proveedores"] == 2

    def test_flujo_caja(self):
        r = self.gr.flujo_caja()
        assert len(r["flujo"]) == 1
        assert r["flujo"][0]["mes"] == "2026-07"

    def test_alertas(self):
        r = self.gr.alertas()
        assert isinstance(r["total"], int)

    def test_alertas_pendientes(self):
        inv = [{"id": 1, "fecha": "2026-07-03", "total": "1000.00",
                "requires_human_review": True}]
        gr = GerentialReports(inv)
        r = gr.alertas()
        assert r["total"] > 0

    def test_export_csv(self):
        r = self.gr.resumen_ejecutivo()
        csv = self.gr.export_csv(r)
        assert isinstance(csv, str)

    def test_export_pdf(self):
        r = self.gr.resumen_ejecutivo()
        html = self.gr.export_pdf(r)
        assert "<html" in html
        assert "Reporte" in html

    def test_extract_rows_with_list(self):
        report = {"items": [{"a": 1}, {"a": 2}]}
        rows = GerentialReports._extract_rows(report)
        assert len(rows) == 2

    def test_extract_rows_no_list(self):
        report = {"total": 100}
        rows = GerentialReports._extract_rows(report)
        assert rows == []

    def test_reconciliation_derived(self):
        r = self.gr.reconciliation()
        assert "es_muestra" in r
        assert r["es_muestra"] is True
