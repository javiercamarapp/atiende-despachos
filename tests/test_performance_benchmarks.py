# -*- coding: utf-8 -*-
"""Performance benchmarks for critical paths.

Measures baseline latency for CFDI parsing, validation, ISR calculation,
and API endpoint response times. Uses simple timing, not pytest-benchmark
(to avoid extra dependency).
"""
import os
import time
import pytest

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fixtures", "cfdis")


class TestCFDIParsingPerformance:
    """Benchmark CFDI parsing latency."""

    @pytest.fixture
    def consultoria_xml(self):
        path = os.path.join(FIXTURES, "02_inversion_consultoria.xml")
        if not os.path.exists(path):
            pytest.skip("Fixture not found")
        return path

    def test_parse_single_cfdi_under_100ms(self, consultoria_xml):
        """Single CFDI parse should complete under 100ms."""
        from b2b_ai.cfdi.parser import parse_cfdi
        start = time.perf_counter()
        for _ in range(10):
            parse_cfdi(consultoria_xml)
        elapsed = (time.perf_counter() - start) / 10
        assert elapsed < 0.1, f"Average parse time {elapsed:.4f}s > 100ms"

    def test_validate_single_cfdi_under_50ms(self, consultoria_xml):
        """Single CFDI validation should complete under 50ms."""
        from b2b_ai.cfdi.parser import parse_cfdi
        from b2b_ai.cfdi.validator import validate_cfdi
        datos = parse_cfdi(consultoria_xml)
        start = time.perf_counter()
        for _ in range(10):
            validate_cfdi(datos)
        elapsed = (time.perf_counter() - start) / 10
        assert elapsed < 0.05, f"Average validation time {elapsed:.4f}s > 50ms"


class TestISRCalculationPerformance:
    """Benchmark ISR calculation latency."""

    def test_isr_calculation_under_1ms(self):
        """ISR calculation should complete under 1ms."""
        from b2b_ai.features.declaraciones.engine import calculate_isr_pf
        start = time.perf_counter()
        for _ in range(1000):
            calculate_isr_pf(25000.0)
        elapsed = (time.perf_counter() - start) / 1000
        assert elapsed < 0.001, f"Average ISR calc time {elapsed:.6f}s > 1ms"

    def test_isr_pm_calculation_under_1ms(self):
        """ISR PM calculation should complete under 1ms."""
        from b2b_ai.features.declaraciones.engine import calculate_isr_pm
        start = time.perf_counter()
        for _ in range(1000):
            calculate_isr_pm(500000.0)
        elapsed = (time.perf_counter() - start) / 1000
        assert elapsed < 0.001, f"Average ISR PM calc time {elapsed:.6f}s > 1ms"


class TestIVACalculationPerformance:
    """Benchmark IVA calculation latency."""

    def test_iva_calculation_under_1ms(self):
        """IVA calculation should complete under 1ms."""
        from b2b_ai.features.declaraciones.engine import calculate_iva
        start = time.perf_counter()
        for _ in range(1000):
            calculate_iva(16000.0, 8000.0, 100000.0, 200000.0)
        elapsed = (time.perf_counter() - start) / 1000
        assert elapsed < 0.001, f"Average IVA calc time {elapsed:.6f}s > 1ms"


class TestDIOTAggregationPerformance:
    """Benchmark DIOT aggregation latency."""

    def test_diot_aggregation_100_invoices_under_200ms(self):
        """DIOT aggregation of 100 invoices should complete under 200ms."""
        from b2b_ai.features.declaraciones.engine import aggregate_diot
        invoices = [
            {
                "rfc_emisor": f"RFC{i:04d}A1B2C",
                "nombre_emisor": f"Proveedor {i}",
                "subtotal": 1000.0 * (i + 1),
                "iva_trasladado": 160.0 * (i + 1),
                "iva_acreditable": 160.0 * (i + 1),
                "tasa_iva": 0.16,
                "fecha": "2025-07-01",
            }
            for i in range(100)
        ]
        start = time.perf_counter()
        result = aggregate_diot(invoices, "TESTRFC01", "2025-07")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.2, f"DIOT aggregation time {elapsed:.4f}s > 200ms"
        assert result.total_records > 0


class TestPayrollPerformance:
    """Benchmark payroll calculation latency."""

    def test_payroll_calc_under_5ms(self):
        """Full payroll calculation should complete under 5ms."""
        from b2b_ai.services.payroll import calculate_payroll
        empleado = {"salario_diario": "500.00", "anios_trabajados": 3}
        start = time.perf_counter()
        for _ in range(100):
            calculate_payroll(empleado, 15000.0, dias_pagados=30)
        elapsed = (time.perf_counter() - start) / 100
        assert elapsed < 0.005, f"Average payroll calc time {elapsed:.6f}s > 5ms"


class TestAPIEndpointLatency:
    """Benchmark basic API endpoint latency."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return TestClient(app)

    def test_health_endpoint_under_10ms(self, client):
        """Health endpoint should respond under 10ms."""
        start = time.perf_counter()
        for _ in range(100):
            resp = client.get("/health")
            assert resp.status_code == 200
        elapsed = (time.perf_counter() - start) / 100
        assert elapsed < 0.01, f"Average health latency {elapsed:.6f}s > 10ms"
