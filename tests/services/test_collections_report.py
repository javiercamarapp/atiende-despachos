# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/collections_report.py — collection reports."""
import pytest
from datetime import date
from decimal import Decimal
from b2b_ai.services.collections_report import (
    aging_report, projection, summary,
)


class TestAgingReport:
    def test_basic(self):
        invoices = [
            {"factura_id": "F1", "monto": "1000", "fecha_vencimiento": "2026-07-01",
             "nombre_empresa": "ACME", "score": 0.75},
        ]
        r = aging_report(invoices, today=date(2026, 7, 15))
        assert r["total_count"] == 1
        assert float(r["total_monto"]) == 1000.0

    def test_empty(self):
        r = aging_report([])
        assert r["total_count"] == 0

    def test_buckets_populated(self):
        invoices = [
            {"factura_id": "F1", "monto": "1000", "fecha_vencimiento": "2026-07-01",
             "nombre_empresa": "A"},
            {"factura_id": "F2", "monto": "2000", "fecha_vencimiento": "2026-06-01",
             "nombre_empresa": "B"},
        ]
        r = aging_report(invoices, today=date(2026, 7, 15))
        assert r["total_count"] == 2


class TestProjection:
    def test_basic(self):
        invoices = [
            {"factura_id": "F1", "monto": "1000", "fecha_vencimiento": "2026-07-01",
             "score": 0.8},
        ]
        r = projection(invoices, today=date(2026, 7, 10))
        assert float(r["total_cartera"]) == 1000.0
        assert float(r["total_esperado"]) == 800.0

    def test_empty(self):
        r = projection([])
        assert float(r["total_cartera"]) == 0
        assert r["tasa_recuperacion_esperada"] == 0.0

    def test_score_ranges(self):
        invoices = [
            {"factura_id": "F1", "monto": "1000", "fecha_vencimiento": "2026-07-01",
             "score": 0.8},
            {"factura_id": "F2", "monto": "2000", "fecha_vencimiento": "2026-07-01",
             "score": 0.5},
            {"factura_id": "F3", "monto": "3000", "fecha_vencimiento": "2026-07-01",
             "score": 0.2},
        ]
        r = projection(invoices, today=date(2026, 7, 10))
        assert r["por_score"]["alta"]["count"] == 1
        assert r["por_score"]["media"]["count"] == 1
        assert r["por_score"]["baja"]["count"] == 1


class TestSummary:
    def test_basic(self):
        invoices = [
            {"factura_id": "F1", "monto": "1000", "fecha_vencimiento": "2026-07-01",
             "nombre_empresa": "ACME", "score": 0.75},
        ]
        r = summary(invoices, today=date(2026, 7, 15))
        assert "total_cartera" in r
        assert "total_esperado" in r
        assert "alertas" in r
        assert "top_montos" in r

    def test_empty(self):
        r = summary([])
        assert r["total_count"] == 0

    def test_90_plus_alert(self):
        invoices = [
            {"factura_id": "F1", "monto": "5000", "fecha_vencimiento": "2026-04-01",
             "nombre_empresa": "ACME", "score": 0.2},
        ]
        r = summary(invoices, today=date(2026, 7, 15))
        assert len(r["alertas"]) > 0

    def test_top_montos_sorted(self):
        invoices = [
            {"factura_id": "F1", "monto": "500", "fecha_vencimiento": "2026-07-01",
             "score": 0.8},
            {"factura_id": "F2", "monto": "5000", "fecha_vencimiento": "2026-07-01",
             "score": 0.8},
        ]
        r = summary(invoices, today=date(2026, 7, 10))
        assert r["top_montos"][0]["factura_id"] == "F2"
