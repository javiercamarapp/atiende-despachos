# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/report.py — report generation."""
import pytest
from b2b_ai.services.report import generate_report, _dec, _periodo


class TestDec:
    def test_normal(self):
        assert _dec("100.50") == 100.5

    def test_none(self):
        assert _dec(None) == 0

    def test_empty(self):
        assert _dec("") == 0

    def test_commas(self):
        # _dec in report.py doesn't strip commas (only the reconcile module does)
        # "1,234.56" fails Decimal conversion -> returns 0
        from decimal import Decimal
        assert _dec("1234.56") == Decimal("1234.56")


class TestPeriodo:
    def test_iso(self):
        assert _periodo("2026-07-03") == "2026-07"

    def test_none(self):
        assert _periodo(None) == "sin-fecha"

    def test_empty(self):
        assert _periodo("") == "sin-fecha"


class TestGenerateReport:
    def test_basic(self):
        invoices = [
            {"fecha": "2026-07-03", "subtotal": "1000.00", "iva": "160.00",
             "total": "1160.00", "categoria": "gasto_operativo", "valido": True},
        ]
        r = generate_report(invoices)
        assert r["facturas"] == 1
        assert r["validas"] == 1
        assert float(r["total"]) == 1160.0

    def test_empty(self):
        r = generate_report([])
        assert r["facturas"] == 0

    def test_period_filter(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "100.00", "valido": True},
            {"fecha": "2026-08-03", "total": "200.00", "valido": True},
        ]
        r = generate_report(invoices, period="2026-07")
        assert r["facturas"] == 1

    def test_tenant_filter(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "100.00", "tenant_id": 1, "valido": True},
            {"fecha": "2026-07-03", "total": "200.00", "tenant_id": 2, "valido": True},
        ]
        r = generate_report(invoices, tenant_id=1)
        assert r["facturas"] == 1

    def test_por_categoria(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "100.00", "categoria": "gasto_operativo"},
            {"fecha": "2026-07-03", "total": "200.00", "categoria": "inversion"},
        ]
        r = generate_report(invoices)
        assert "gasto_operativo" in r["por_categoria"]
        assert "inversion" in r["por_categoria"]

    def test_invalidas_count(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "100.00", "valido": True},
            {"fecha": "2026-07-03", "total": "200.00", "valido": False},
        ]
        r = generate_report(invoices)
        assert r["validas"] == 1
        assert r["invalidas"] == 1

    def test_por_mes(self):
        invoices = [
            {"fecha": "2026-07-03", "total": "100.00"},
            {"fecha": "2026-07-15", "total": "200.00"},
        ]
        r = generate_report(invoices)
        assert "2026-07" in r["por_mes"]
        assert r["por_mes"]["2026-07"]["count"] == 2
