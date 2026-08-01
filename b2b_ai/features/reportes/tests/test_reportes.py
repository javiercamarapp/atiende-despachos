# -*- coding: utf-8 -*-
"""Tests for the Reportes module (generators, serializers, routes)."""
from __future__ import annotations
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from b2b_ai.features.reportes.generator import (
    generate_balance_general, generate_estado_resultados,
    generate_conciliacion_bancaria, generate_reporte_nomina,
    ReportLine, ReportSection, ReportData,
    _fmt_money, _to_decimal,
)
from b2b_ai.features.reportes.serializers import (
    serialize_json, serialize_csv, serialize_html, serialize,
    SUPPORTED_FORMATS,
)


# ── Generator Helper Tests ──

class TestHelpers:
    def test_fmt_money_none(self):
        assert _fmt_money(None) == "$0.00"

    def test_fmt_money_value(self):
        result = _fmt_money(1234.56)
        assert "$1,234.56" in result

    def test_to_decimal_none(self):
        assert _to_decimal(None) == Decimal("0.00")

    def test_to_decimal_string(self):
        assert _to_decimal("42.5") == Decimal("42.5")

    def test_to_decimal_invalid(self):
        assert _to_decimal("abc") == Decimal("0.00")


# ── ReportLine / ReportSection Tests ──

class TestReportDataclasses:
    def test_report_line(self):
        rl = ReportLine(concepto="Cash", importe=Decimal("1000"))
        assert rl.importe_formatted == "$1,000.00"
        d = rl.to_dict()
        assert d["concepto"] == "Cash"

    def test_report_section(self):
        sec = ReportSection(titulo="Assets", subtotal=Decimal("5000"))
        assert sec.subtotal_formatted == "$5,000.00"

    def test_report_data_to_dict(self):
        rd = ReportData(titulo="Test", subtitulo="Sub")
        d = rd.to_dict()
        assert d["titulo"] == "Test"
        assert d["secciones"] == []


# ── Balance General Generator Tests ──

class TestBalanceGeneral:
    def test_basic_balance(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100000}],
            activos_fijos=[{"concepto": "Equipo", "importe": 50000}],
            pasivos_circulantes=[{"concepto": "Proveedores", "importe": 30000}],
            pasivos_largo_plazo=[{"concepto": "Préstamo", "importe": 20000}],
            capital_contable=[{"concepto": "Capital", "importe": 100000}],
            empresa_rfc="EABC123456789",
            empresa_nombre="Test Corp",
        )
        assert report.titulo == "Balance General"
        assert report.empresa_rfc == "EABC123456789"
        assert len(report.secciones) == 5
        assert report.totales["cuadra"] == "True"

    def test_empty_balance(self):
        report = generate_balance_general()
        assert report.titulo == "Balance General"
        assert report.totales["total_activos"] == "0"

    def test_balance_imbalanced(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Cash", "importe": 100000}],
            pasivos_circulantes=[{"concepto": "Debt", "importe": 50000}],
            capital_contable=[{"concepto": "Capital", "importe": 30000}],
        )
        assert report.totales["cuadra"] == "False"

    def test_to_dict(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 1000}]
        )
        d = report.to_dict()
        assert "secciones" in d
        assert "totales" in d
        assert "metadata" in d


# ── Estado de Resultados Generator Tests ──

class TestEstadoResultados:
    def test_basic_er(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 500000}],
            costos=[{"concepto": "Costo mercancía", "importe": 200000}],
            gastos_operacion=[{"concepto": "Renta", "importe": 50000}],
            gastos_administracion=[{"concepto": "Nómina admin", "importe": 30000}],
            impuestos=[{"concepto": "ISR", "importe": 40000}],
        )
        assert report.titulo == "Estado de Resultados"
        assert Decimal(report.totales["utilidad_neta"]) > 0

    def test_empty_er(self):
        report = generate_estado_resultados()
        assert report.totales["utilidad_neta"] == "0"

    def test_er_with_losses(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Sales", "importe": 100000}],
            costos=[{"concepto": "COGS", "importe": 80000}],
            gastos_operacion=[{"concepto": "Opex", "importe": 30000}],
        )
        assert Decimal(report.totales["utilidad_neta"]) < 0


# ── Conciliación Bancaria Generator Tests ──

class TestConciliacionBancaria:
    def test_basic_conciliacion(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"descripcion": "Depósito", "monto": 50000, "fecha": "2025-01-15", "conciliado": True},
                {"descripcion": "Cargo", "monto": -10000, "fecha": "2025-01-16", "conciliado": False},
            ],
            movimientos_contabilidad=[
                {"descripcion": "Depósito", "monto": 50000, "fecha": "2025-01-15", "conciliado": True},
                {"descripcion": "Nota crédito", "monto": 5000, "fecha": "2025-01-17", "conciliado": False},
            ],
            banco_nombre="BBVA",
            numero_cuenta="123456",
        )
        assert report.titulo == "Conciliación Bancaria"
        assert len(report.secciones) == 3

    def test_fully_reconciled(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"descripcion": "Dep", "monto": 50000, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"descripcion": "Dep", "monto": 50000, "conciliado": True},
            ],
        )
        assert report.totales["conciliado"] == "True"

    def test_empty_conciliacion(self):
        report = generate_conciliacion_bancaria()
        assert report.totales["diferencia"] == "0"


# ── Reporte Nómina Generator Tests ──

class TestReporteNomina:
    def test_basic_nomina(self):
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "Juan Pérez", "rfc": "PEPJ850101", "salario_bruto": 30000,
                 "deducciones": 9000, "puesto": "Dev", "departamento": "TI"},
                {"nombre": "Ana López", "rfc": "LOPA900202", "salario_bruto": 25000,
                 "deducciones": 7500, "puesto": "Designer", "departamento": "TI"},
            ],
            empresa_rfc="EABC123456789",
            empresa_nombre="Test Corp",
            tipo_nomina="O",
        )
        assert report.titulo == "Reporte de Nómina"
        assert report.totales["total_empleados"] == "2"
        assert report.totales["tipo_nomina"] == "Ordinaria"

    def test_empty_nomina(self):
        report = generate_reporte_nomina()
        assert report.totales["total_empleados"] == "0"

    def test_nomina_departments(self):
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "A", "salario_bruto": 10000, "deducciones": 3000, "departamento": "Ventas"},
                {"nombre": "B", "salario_bruto": 15000, "deducciones": 4500, "departamento": "TI"},
            ],
        )
        # Should have department summary section
        dept_section = [s for s in report.secciones if "Departamento" in s.titulo]
        assert len(dept_section) == 1
        assert len(dept_section[0].lineas) == 2


# ── Serializer Tests ──

class TestSerializers:
    def _report(self):
        return generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100000}],
            empresa_rfc="EABC123456789",
            empresa_nombre="Test Corp",
        )

    def test_json(self):
        report = self._report()
        result = serialize_json(report)
        assert '"titulo"' in result
        assert "Balance General" in result

    def test_csv(self):
        report = self._report()
        result = serialize_csv(report)
        assert "Seccion" in result or "Sección" in result or "Concepto" in result

    def test_html(self):
        report = self._report()
        result = serialize_html(report)
        assert "<!DOCTYPE html>" in result
        assert "Balance General" in result

    def test_serialize_json(self):
        report = self._report()
        result = serialize(report, fmt="json")
        assert '"titulo"' in result

    def test_serialize_csv(self):
        report = self._report()
        result = serialize(report, fmt="csv")
        assert "Concepto" in result

    def test_serialize_html(self):
        report = self._report()
        result = serialize(report, fmt="html")
        assert "<!DOCTYPE html>" in result

    def test_serialize_invalid_format(self):
        report = self._report()
        with pytest.raises(ValueError):
            serialize(report, fmt="xml")

    def test_supported_formats(self):
        assert "json" in SUPPORTED_FORMATS
        assert "csv" in SUPPORTED_FORMATS
        assert "html" in SUPPORTED_FORMATS


# ── Route Tests ──

class TestRoutes:
    @pytest.fixture
    def client(self):
        from b2b_ai.features.reportes.routes import build_reportes_router
        from fastapi import FastAPI
        app = FastAPI()
        router = build_reportes_router()
        app.include_router(router)
        return TestClient(app)

    def test_balance_json(self, client):
        resp = client.post("/reportes/balance", json={
            "activos_circulantes": [{"concepto": "Caja", "importe": 100000}],
            "formato": "json",
        })
        assert resp.status_code == 200
        assert resp.json()["titulo"] == "Balance General"

    def test_balance_csv(self, client):
        resp = client.post("/reportes/balance", json={
            "activos_circulantes": [{"concepto": "Caja", "importe": 100000}],
            "formato": "csv",
        })
        assert resp.status_code == 200

    def test_balance_html(self, client):
        resp = client.post("/reportes/balance", json={
            "activos_circulantes": [{"concepto": "Caja", "importe": 100000}],
            "formato": "html",
        })
        assert resp.status_code == 200

    def test_estado_resultados(self, client):
        resp = client.post("/reportes/estado-resultados", json={
            "ingresos": [{"concepto": "Ventas", "importe": 500000}],
            "costos": [{"concepto": "COGS", "importe": 200000}],
            "formato": "json",
        })
        assert resp.status_code == 200
        assert resp.json()["titulo"] == "Estado de Resultados"

    def test_conciliacion(self, client):
        resp = client.post("/reportes/conciliacion", json={
            "movimientos_banco": [{"descripcion": "Dep", "monto": 50000, "conciliado": True}],
            "movimientos_contabilidad": [{"descripcion": "Dep", "monto": 50000, "conciliado": True}],
            "formato": "json",
        })
        assert resp.status_code == 200

    def test_nomina(self, client):
        resp = client.post("/reportes/nomina", json={
            "empleados": [{"nombre": "Juan", "salario_bruto": 30000, "deducciones": 9000}],
            "formato": "json",
        })
        assert resp.status_code == 200
        assert resp.json()["titulo"] == "Reporte de Nómina"

    def test_formats_endpoint(self, client):
        resp = client.get("/reportes/formats")
        assert resp.status_code == 200
        assert len(resp.json()["formats"]) == 3

    def test_invalid_format(self, client):
        resp = client.post("/reportes/balance", json={
            "formato": "xml",
        })
        assert resp.status_code == 400
