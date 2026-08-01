# -*- coding: utf-8 -*-
"""
test_reportes.py — Tests del módulo de Reportes Contables (generators + serializers + routes).

Cobertura:
  Generator:
    - Balance General: vacío, con datos, cuadre activos/pasivos+capital, subtotales,
      decimal precision, metadata, to_dict serializable.
    - Estado de Resultados: vacío, con datos, utilidad bruta/operación/neta,
      sin gastos, solo ingresos, con impuestos, to_dict serializable.
    - Conciliación Bancaria: vacío, todos conciliados, todos no conciliados,
      mixto, saldo cuadra, diferencia, banco/concepto metadata.
    - Nómina: vacío, un empleado, múltiples empleados, deducciones,
      departamento, ordinaria/extraordinaria, to_dict serializable.

  Serializers:
    - JSON: formato válido, indentación, escape unicode, roundtrip.
    - CSV: cabeceras, filas, secciones, totales, encoding UTF-8.
    - HTML: DOCTYPE, secciones, estilos inline, totales, escape HTML.

  Routes:
    - POST /reportes/balance: JSON, CSV, HTML, datos vacíos.
    - POST /reportes/estado-resultados: JSON, CSV, HTML, utilidad neta.
    - POST /reportes/conciliacion: JSON, CSV, HTML, conciliado.
    - POST /reportes/nomina: JSON, CSV, HTML, resumen departamento.
    - GET /reportes/formats: lista formatos.
    - Error: formato inválido.
"""
from __future__ import annotations

import json
import csv
import io
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.reportes.generator import (
    ReportData,
    ReportSection,
    ReportLine,
    generate_balance_general,
    generate_estado_resultados,
    generate_conciliacion_bancaria,
    generate_reporte_nomina,
    _fmt_money,
    _to_decimal,
)
from b2b_ai.features.reportes.serializers import (
    serialize_json,
    serialize_csv,
    serialize_html,
    serialize,
    SUPPORTED_FORMATS,
)
from b2b_ai.features.reportes.routes import build_reportes_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_balance_data():
    """Datos de ejemplo para Balance General."""
    return {
        "activos_circulantes": [
            {"concepto": "Caja", "importe": 50000},
            {"concepto": "Bancos", "importe": 120000},
            {"concepto": "Clientes", "importe": 80000},
        ],
        "activos_fijos": [
            {"concepto": "Mobiliario", "importe": 30000},
            {"concepto": "Equipo de cómputo", "importe": 20000},
        ],
        "pasivos_circulantes": [
            {"concepto": "Proveedores", "importe": 60000},
            {"concepto": "Impuestos por pagar", "importe": 15000},
        ],
        "pasivos_largo_plazo": [
            {"concepto": "Préstamo bancario", "importe": 50000},
        ],
        "capital_contable": [
            {"concepto": "Capital social", "importe": 100000},
            {"concepto": "Resultados acumulados", "importe": 75000},
        ],
        "empresa_rfc": "EMP010101AAA",
        "empresa_nombre": "Empresa Demo SA de CV",
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-06-30",
    }


@pytest.fixture
def sample_estado_resultados_data():
    """Datos de ejemplo para Estado de Resultados."""
    return {
        "ingresos": [
            {"concepto": "Ventas", "importe": 500000},
            {"concepto": "Servicios", "importe": 200000},
        ],
        "costos": [
            {"concepto": "Costo de mercancía", "importe": 250000},
        ],
        "gastos_operacion": [
            {"concepto": "Sueldos", "importe": 80000},
            {"concepto": "Renta", "importe": 24000},
        ],
        "gastos_administracion": [
            {"concepto": "Servicios profesionales", "importe": 15000},
        ],
        "otros_ingresos": [
            {"concepto": "Intereses", "importe": 3000},
        ],
        "impuestos": [
            {"concepto": "ISR", "importe": 52000},
        ],
        "empresa_rfc": "EMP010101AAA",
        "empresa_nombre": "Empresa Demo SA de CV",
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-06-30",
    }


@pytest.fixture
def sample_conciliacion_data():
    """Datos de ejemplo para Conciliación Bancaria."""
    return {
        "movimientos_banco": [
            {"fecha": "2026-06-01", "descripcion": "Depósito cliente A", "monto": 50000, "conciliado": True},
            {"fecha": "2026-06-05", "descripcion": "Transferencia proveedor", "monto": -20000, "conciliado": True},
            {"fecha": "2026-06-10", "descripcion": "Comisión bancaria", "monto": -150, "conciliado": False},
        ],
        "movimientos_contabilidad": [
            {"fecha": "2026-06-01", "descripcion": "Ingreso por venta", "monto": 50000, "conciliado": True},
            {"fecha": "2026-06-05", "descripcion": "Pago proveedor", "monto": -20000, "conciliado": True},
            {"fecha": "2026-06-08", "descripcion": "Servicio contable", "monto": -500, "conciliado": False},
        ],
        "empresa_rfc": "EMP010101AAA",
        "empresa_nombre": "Empresa Demo SA de CV",
        "periodo_inicio": "2026-06-01",
        "periodo_fin": "2026-06-30",
        "banco_nombre": "BBVA México",
        "numero_cuenta": "0123456789",
    }


@pytest.fixture
def sample_nomina_data():
    """Datos de ejemplo para Reporte de Nómina."""
    return {
        "empleados": [
            {
                "nombre": "Juan Pérez",
                "rfc": "PEPJ800101ABC",
                "salario_bruto": 25000,
                "deducciones": 5000,
                "puesto": "Contador",
                "departamento": "Contabilidad",
            },
            {
                "nombre": "María García",
                "rfc": "GACM850202DEF",
                "salario_bruto": 30000,
                "deducciones": 6500,
                "puesto": "Gerente",
                "departamento": "Administración",
            },
            {
                "nombre": "Carlos López",
                "rfc": "LOPC900303GHI",
                "salario_bruto": 18000,
                "deducciones": 3600,
                "puesto": "Asistente",
                "departamento": "Contabilidad",
            },
        ],
        "empresa_rfc": "EMP010101AAA",
        "empresa_nombre": "Empresa Demo SA de CV",
        "periodo_inicio": "2026-06-01",
        "periodo_fin": "2026-06-15",
        "periodo_pago": "Quincenal 01-15 junio 2026",
        "tipo_nomina": "O",
    }


@pytest.fixture
def client():
    """TestClient FastAPI con el router de reportes registrado."""
    app = FastAPI()
    app.include_router(build_reportes_router())
    return TestClient(app)


# ===========================================================================
# GENERATOR: Helper functions
# ===========================================================================

class TestHelperFunctions:
    """Tests de _fmt_money() y _to_decimal()."""

    def test_fmt_money_decimal(self):
        assert _fmt_money(Decimal("1234.56")) == "$1,234.56"

    def test_fmt_money_integer(self):
        assert _fmt_money(1000) == "$1,000.00"

    def test_fmt_money_string(self):
        assert _fmt_money("9999.99") == "$9,999.99"

    def test_fmt_money_none(self):
        assert _fmt_money(None) == "$0.00"

    def test_fmt_money_zero(self):
        assert _fmt_money(0) == "$0.00"

    def test_fmt_money_negative(self):
        assert _fmt_money(-500) == "$-500.00"

    def test_fmt_money_large(self):
        assert _fmt_money(1234567.89) == "$1,234,567.89"

    def test_to_decimal_from_int(self):
        assert _to_decimal(42) == Decimal("42")

    def test_to_decimal_from_float(self):
        assert _to_decimal(3.14) == Decimal("3.14")

    def test_to_decimal_from_string(self):
        assert _to_decimal("100.50") == Decimal("100.50")

    def test_to_decimal_from_none(self):
        assert _to_decimal(None) == Decimal("0.00")

    def test_to_decimal_invalid(self):
        assert _to_decimal("abc") == Decimal("0.00")

    def test_to_decimal_decimal_input(self):
        assert _to_decimal(Decimal("99.99")) == Decimal("99.99")


# ===========================================================================
# GENERATOR: Balance General
# ===========================================================================

class TestBalanceGeneral:
    """Tests de generate_balance_general()."""

    def test_empty_balance(self):
        report = generate_balance_general()
        assert report.titulo == "Balance General"
        assert len(report.secciones) == 5
        assert report.totales["total_activos"] == "0"
        assert report.totales["cuadra"] == "True"

    def test_with_data(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        assert report.empresa_rfc == "EMP010101AAA"
        assert report.empresa_nombre == "Empresa Demo SA de CV"
        assert len(report.secciones) == 5

    def test_activos_circulantes_section(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        sec = report.secciones[0]
        assert sec.titulo == "Activos Circulantes"
        assert len(sec.lineas) == 3
        assert sec.subtotal == Decimal("250000")

    def test_activos_fijos_section(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        sec = report.secciones[1]
        assert sec.titulo == "Activos Fijos"
        assert len(sec.lineas) == 2
        assert sec.subtotal == Decimal("50000")

    def test_pasivos_circulantes_section(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        sec = report.secciones[2]
        assert sec.titulo == "Pasivos Circulantes"
        assert sec.subtotal == Decimal("75000")

    def test_pasivos_largo_plazo_section(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        sec = report.secciones[3]
        assert sec.titulo == "Pasivos a Largo Plazo"
        assert sec.subtotal == Decimal("50000")

    def test_capital_contable_section(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        sec = report.secciones[4]
        assert sec.titulo == "Capital Contable"
        assert sec.subtotal == Decimal("175000")

    def test_balance_cuadra(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        # Activos: 250000 + 50000 = 300000
        # Pasivos+Capital: 75000 + 50000 + 175000 = 300000
        assert report.totales["total_activos"] == "300000"
        assert report.totales["total_pasivos_y_capital"] == "300000"
        assert report.totales["cuadra"] == "True"

    def test_balance_no_cuadra(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100000}],
            capital_contable=[{"concepto": "Capital", "importe": 50000}],
        )
        assert report.totales["cuadra"] == "False"

    def test_metadata(self):
        report = generate_balance_general()
        assert report.metadata["tipo_reporte"] == "balance_general"
        assert report.metadata["moneda"] == "MXN"

    def test_to_dict_serializable(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        d = report.to_dict()
        assert isinstance(d, dict)
        # Debe ser serializable a JSON sin errores
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_linea_with_subconcepto(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Bancos", "importe": 10000, "subconcepto": "BBVA"}],
        )
        line = report.secciones[0].lineas[0]
        assert line.subconcepto == "BBVA"

    def test_linea_with_nivel(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Bancos", "importe": 10000, "nivel": 1}],
        )
        line = report.secciones[0].lineas[0]
        assert line.nivel == 1

    def test_periodo(self, sample_balance_data):
        report = generate_balance_general(**sample_balance_data)
        assert report.periodo_inicio == "2026-01-01"
        assert report.periodo_fin == "2026-06-30"

    def test_decimal_precision(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": "1234.567"}],
        )
        assert report.secciones[0].subtotal == Decimal("1234.567")

    def test_many_accounts(self):
        items = [{"concepto": f"Cuenta {i}", "importe": i * 100} for i in range(100)]
        report = generate_balance_general(activos_circulantes=items)
        assert len(report.secciones[0].lineas) == 100
        expected = sum(Decimal(str(i * 100)) for i in range(100))
        assert report.secciones[0].subtotal == expected


# ===========================================================================
# GENERATOR: Estado de Resultados
# ===========================================================================

class TestEstadoResultados:
    """Tests de generate_estado_resultados()."""

    def test_empty(self):
        report = generate_estado_resultados()
        assert report.titulo == "Estado de Resultados"
        assert report.totales["utilidad_neta"] == "0"

    def test_with_data(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        assert report.empresa_rfc == "EMP010101AAA"
        assert len(report.secciones) == 6

    def test_ingresos_section(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        sec = report.secciones[0]
        assert sec.titulo == "Ingresos"
        assert sec.subtotal == Decimal("700000")

    def test_costos_section(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        sec = report.secciones[1]
        assert sec.titulo == "Costos"
        assert sec.subtotal == Decimal("250000")

    def test_utilidad_bruta(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        # 700000 - 250000 = 450000
        assert report.totales["utilidad_bruta"] == "450000"

    def test_utilidad_operacion(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        # 450000 - 80000 - 24000 - 15000 = 331000
        assert report.totales["utilidad_operacion"] == "331000"

    def test_utilidad_neta(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        # 331000 + 3000 - 52000 = 282000
        assert report.totales["utilidad_neta"] == "282000"

    def test_only_ingresos(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 100000}],
        )
        assert report.totales["total_ingresos"] == "100000"
        assert report.totales["utilidad_neta"] == "100000"

    def test_with_otros_ingresos(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 100000}],
            otros_ingresos=[{"concepto": "Intereses", "importe": 5000}],
        )
        assert report.totales["total_otros_ingresos"] == "5000"
        assert report.totales["utilidad_neta"] == "105000"

    def test_with_impuestos(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 100000}],
            impuestos=[{"concepto": "ISR", "importe": 20000}],
        )
        assert report.totales["total_impuestos"] == "20000"
        assert report.totales["utilidad_neta"] == "80000"

    def test_metadata(self):
        report = generate_estado_resultados()
        assert report.metadata["tipo_reporte"] == "estado_resultados"

    def test_to_dict_serializable(self, sample_estado_resultados_data):
        report = generate_estado_resultados(**sample_estado_resultados_data)
        d = report.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_utilidad_negativa(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 10000}],
            costos=[{"concepto": "Costo", "importe": 15000}],
        )
        # -5000
        assert Decimal(report.totales["utilidad_neta"]) < 0

    def test_many_line_items(self):
        ingresos = [{"concepto": f"Venta {i}", "importe": i * 1000} for i in range(1, 51)]
        report = generate_estado_resultados(ingresos=ingresos)
        assert len(report.secciones[0].lineas) == 50


# ===========================================================================
# GENERATOR: Conciliación Bancaria
# ===========================================================================

class TestConciliacionBancaria:
    """Tests de generate_conciliacion_bancaria()."""

    def test_empty(self):
        report = generate_conciliacion_bancaria()
        assert report.titulo == "Conciliación Bancaria"
        assert report.totales["conciliado"] == "True"

    def test_all_reconciled(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "Depósito", "monto": 10000, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "Ingreso", "monto": 10000, "conciliado": True},
            ],
        )
        assert report.totales["conciliado"] == "True"
        assert report.totales["diferencia"] == "0"

    def test_all_unreconciled(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "Banco 1", "monto": 10000, "conciliado": False},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "Conta 1", "monto": 5000, "conciliado": False},
            ],
        )
        assert report.totales["conciliado"] == "False"
        assert report.totales["total_conciliados"] == "0"

    def test_mixed(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        assert len(report.secciones) == 3
        # Conciliados: 50000 + (-20000) + 50000 + (-20000) = 60000
        assert report.totales["total_conciliados"] == "60000"

    def test_sections_present(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        assert report.secciones[0].titulo == "Movimientos Conciliados"
        assert report.secciones[1].titulo == "No Conciliados — Banco"
        assert report.secciones[2].titulo == "No Conciliados — Contabilidad"

    def test_saldo_banco(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        # Banco: 60000 (conciliados) + (-150) (no conciliados banco) = 59850
        assert report.totales["saldo_banco"] == "59850"

    def test_saldo_contable(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        # Contable: 60000 (conciliados) + (-500) (no conciliados contab) = 59500
        assert report.totales["saldo_contable"] == "59500"

    def test_diferencia(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        assert report.totales["diferencia"] == "350"
        assert report.totales["conciliado"] == "False"

    def test_metadata_banco(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        assert report.metadata["banco"] == "BBVA México"
        assert report.metadata["numero_cuenta"] == "0123456789"

    def test_subtitulo_with_banco(self):
        report = generate_conciliacion_bancaria(
            banco_nombre="Santander",
            numero_cuenta="999",
        )
        assert "Santander" in report.subtitulo
        assert "999" in report.subtitulo

    def test_to_dict_serializable(self, sample_conciliacion_data):
        report = generate_conciliacion_bancaria(**sample_conciliacion_data)
        d = report.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 0


# ===========================================================================
# GENERATOR: Reporte de Nómina
# ===========================================================================

class TestReporteNomina:
    """Tests de generate_reporte_nomina()."""

    def test_empty(self):
        report = generate_reporte_nomina()
        assert report.titulo == "Reporte de Nómina"
        assert report.totales["total_empleados"] == "0"

    def test_single_employee(self):
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "Ana", "rfc": "AAA000101", "salario_bruto": 20000, "deducciones": 4000},
            ]
        )
        assert report.totales["total_empleados"] == "1"
        assert report.totales["total_neto"] == "16000"

    def test_multiple_employees(self, sample_nomina_data):
        report = generate_reporte_nomina(**sample_nomina_data)
        assert report.totales["total_empleados"] == "3"
        # Bruto: 25000 + 30000 + 18000 = 73000
        assert report.totales["total_bruto"] == "73000"
        # Deducciones: 5000 + 6500 + 3600 = 15100
        assert report.totales["total_deducciones"] == "15100"
        # Neto: 73000 - 15100 = 57900
        assert report.totales["total_neto"] == "57900"

    def test_department_summary(self, sample_nomina_data):
        report = generate_reporte_nomina(**sample_nomina_data)
        # La última sección es el resumen por departamento
        depto_section = report.secciones[-1]
        assert depto_section.titulo == "Resumen por Departamento"
        assert len(depto_section.lineas) >= 2

    def test_employee_sections_have_details(self, sample_nomina_data):
        report = generate_reporte_nomina(**sample_nomina_data)
        for section in report.secciones[:3]:
            assert len(section.lineas) >= 1

    def test_tipo_nomina_ordinaria(self):
        report = generate_reporte_nomina(tipo_nomina="O")
        assert report.totales["tipo_nomina"] == "Ordinaria"

    def test_tipo_nomina_extraordinaria(self):
        report = generate_reporte_nomina(tipo_nomina="E")
        assert report.totales["tipo_nomina"] == "Extraordinaria"

    def test_periodo_pago(self):
        report = generate_reporte_nomina(periodo_pago="Quincenal 01-15 junio 2026")
        assert report.totales["periodo_pago"] == "Quincenal 01-15 junio 2026"

    def test_metadata(self):
        report = generate_reporte_nomina()
        assert report.metadata["tipo_reporte"] == "nomina"

    def test_to_dict_serializable(self, sample_nomina_data):
        report = generate_reporte_nomina(**sample_nomina_data)
        d = report.to_dict()
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_employee_section_titulo(self, sample_nomina_data):
        report = generate_reporte_nomina(**sample_nomina_data)
        first = report.secciones[0]
        assert "Juan Pérez" in first.titulo

    def test_many_employees(self):
        empleados = [
            {"nombre": f"Emp {i}", "rfc": f"RFC{i}", "salario_bruto": 15000 + i * 1000, "deducciones": 3000 + i * 100}
            for i in range(50)
        ]
        report = generate_reporte_nomina(empleados=empleados)
        assert report.totales["total_empleados"] == "50"
        assert len(report.secciones) > 50  # employees + dept summary


# ===========================================================================
# SERIALIZER: JSON
# ===========================================================================

class TestSerializeJson:
    """Tests de serialize_json()."""

    def test_valid_json(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_json(report)
        parsed = json.loads(result)
        assert parsed["titulo"] == "Balance General"

    def test_indent(self):
        report = generate_balance_general()
        result = serialize_json(report, indent=4)
        assert "\n    " in result

    def test_unicode(self):
        report = generate_balance_general(
            empresa_nombre="Empresa Ñoño SA",
        )
        result = serialize_json(report)
        assert "Ñoño" in result

    def test_roundtrip(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_json(report)
        parsed = json.loads(result)
        # Roundtrip back to ReportData fields
        assert parsed["secciones"][0]["titulo"] == "Activos Circulantes"


# ===========================================================================
# SERIALIZER: CSV
# ===========================================================================

class TestSerializeCsv:
    """Tests de serialize_csv()."""

    def test_valid_csv(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_csv(report)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        assert rows[0] == ["Sección", "Concepto", "Subconcepto", "Importe"]

    def test_section_rows(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_csv(report)
        assert "Activos Circulantes" in result
        assert "Caja" in result

    def test_totals_in_csv(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_csv(report)
        assert "TOTAL DEL REPORTE" in result

    def test_csv_encoding(self):
        report = generate_balance_general(
            empresa_nombre="Empresa Ñoño",
            activos_circulantes=[{"concepto": "Caja ñ", "importe": 1000}],
        )
        result = serialize_csv(report)
        assert "Caja" in result


# ===========================================================================
# SERIALIZER: HTML
# ===========================================================================

class TestSerializeHtml:
    """Tests de serialize_html()."""

    def test_valid_html(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_html(report)
        assert result.startswith("<!DOCTYPE html>")
        assert "</html>" in result

    def test_sections_in_html(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_html(report)
        assert "Activos Circulantes" in result
        assert "Caja" in result

    def test_totals_in_html(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        result = serialize_html(report)
        assert "Resumen del Reporte" in result

    def test_escape_html(self):
        report = generate_balance_general(
            empresa_nombre="<script>alert('xss')</script>",
        )
        result = serialize_html(report)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_styles_inline(self):
        report = generate_balance_general()
        result = serialize_html(report)
        assert "<style>" in result

    def test_header_metadata(self):
        report = generate_balance_general(
            empresa_nombre="Test Corp",
            empresa_rfc="TC001",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-06-30",
        )
        result = serialize_html(report)
        assert "Test Corp" in result
        assert "TC001" in result

    def test_footer(self):
        report = generate_balance_general()
        result = serialize_html(report)
        assert "B&B AI" in result


# ===========================================================================
# SERIALIZER: serialize() convenience
# ===========================================================================

class TestSerializeConvenience:
    """Tests de serialize() convenience function."""

    def test_json(self):
        report = generate_balance_general()
        result = serialize(report, "json")
        parsed = json.loads(result)
        assert parsed["titulo"] == "Balance General"

    def test_csv(self):
        report = generate_balance_general()
        result = serialize(report, "csv")
        assert "Sección" in result

    def test_html(self):
        report = generate_balance_general()
        result = serialize(report, "html")
        assert "<!DOCTYPE html>" in result

    def test_invalid_format(self):
        report = generate_balance_general()
        with pytest.raises(ValueError, match="Formato no soportado"):
            serialize(report, "xml")

    def test_case_insensitive(self):
        report = generate_balance_general()
        result = serialize(report, "JSON")
        parsed = json.loads(result)
        assert parsed["titulo"] == "Balance General"

    def test_supported_formats_list(self):
        assert "json" in SUPPORTED_FORMATS
        assert "csv" in SUPPORTED_FORMATS
        assert "html" in SUPPORTED_FORMATS
        assert len(SUPPORTED_FORMATS) == 3


# ===========================================================================
# ROUTES: Balance General
# ===========================================================================

class TestRoutesBalance:
    """Tests de POST /reportes/balance."""

    def test_json_default(self, client, sample_balance_data):
        resp = client.post("/reportes/balance", json=sample_balance_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["titulo"] == "Balance General"
        assert data["empresa_rfc"] == "EMP010101AAA"

    def test_csv_format(self, client, sample_balance_data):
        sample_balance_data["formato"] = "csv"
        resp = client.post("/reportes/balance", json=sample_balance_data)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_html_format(self, client, sample_balance_data):
        sample_balance_data["formato"] = "html"
        resp = client.post("/reportes/balance", json=sample_balance_data)
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_empty_data(self, client):
        resp = client.post("/reportes/balance", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["totales"]["total_activos"] == "0"

    def test_cuadra(self, client, sample_balance_data):
        resp = client.post("/reportes/balance", json=sample_balance_data)
        data = resp.json()
        assert data["totales"]["cuadra"] == "True"

    def test_invalid_format(self, client, sample_balance_data):
        sample_balance_data["formato"] = "xml"
        resp = client.post("/reportes/balance", json=sample_balance_data)
        assert resp.status_code == 400


# ===========================================================================
# ROUTES: Estado de Resultados
# ===========================================================================

class TestRoutesEstadoResultados:
    """Tests de POST /reportes/estado-resultados."""

    def test_json_default(self, client, sample_estado_resultados_data):
        resp = client.post("/reportes/estado-resultados", json=sample_estado_resultados_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["titulo"] == "Estado de Resultados"

    def test_csv_format(self, client, sample_estado_resultados_data):
        sample_estado_resultados_data["formato"] = "csv"
        resp = client.post("/reportes/estado-resultados", json=sample_estado_resultados_data)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_html_format(self, client, sample_estado_resultados_data):
        sample_estado_resultados_data["formato"] = "html"
        resp = client.post("/reportes/estado-resultados", json=sample_estado_resultados_data)
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_utilidad_neta(self, client, sample_estado_resultados_data):
        resp = client.post("/reportes/estado-resultados", json=sample_estado_resultados_data)
        data = resp.json()
        assert data["totales"]["utilidad_neta"] == "282000"

    def test_empty_data(self, client):
        resp = client.post("/reportes/estado-resultados", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["totales"]["utilidad_neta"] == "0"


# ===========================================================================
# ROUTES: Conciliación Bancaria
# ===========================================================================

class TestRoutesConciliacion:
    """Tests de POST /reportes/conciliacion."""

    def test_json_default(self, client, sample_conciliacion_data):
        resp = client.post("/reportes/conciliacion", json=sample_conciliacion_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["titulo"] == "Conciliación Bancaria"

    def test_csv_format(self, client, sample_conciliacion_data):
        sample_conciliacion_data["formato"] = "csv"
        resp = client.post("/reportes/conciliacion", json=sample_conciliacion_data)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_html_format(self, client, sample_conciliacion_data):
        sample_conciliacion_data["formato"] = "html"
        resp = client.post("/reportes/conciliacion", json=sample_conciliacion_data)
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_conciliado(self, client):
        data = {
            "movimientos_banco": [
                {"fecha": "2026-06-01", "descripcion": "Depósito", "monto": 10000, "conciliado": True},
            ],
            "movimientos_contabilidad": [
                {"fecha": "2026-06-01", "descripcion": "Ingreso", "monto": 10000, "conciliado": True},
            ],
        }
        resp = client.post("/reportes/conciliacion", json=data)
        assert resp.status_code == 200
        assert resp.json()["totales"]["conciliado"] == "True"

    def test_empty_data(self, client):
        resp = client.post("/reportes/conciliacion", json={})
        assert resp.status_code == 200
        assert resp.json()["totales"]["conciliado"] == "True"


# ===========================================================================
# ROUTES: Reporte de Nómina
# ===========================================================================

class TestRoutesNomina:
    """Tests de POST /reportes/nomina."""

    def test_json_default(self, client, sample_nomina_data):
        resp = client.post("/reportes/nomina", json=sample_nomina_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["titulo"] == "Reporte de Nómina"

    def test_csv_format(self, client, sample_nomina_data):
        sample_nomina_data["formato"] = "csv"
        resp = client.post("/reportes/nomina", json=sample_nomina_data)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_html_format(self, client, sample_nomina_data):
        sample_nomina_data["formato"] = "html"
        resp = client.post("/reportes/nomina", json=sample_nomina_data)
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_employee_count(self, client, sample_nomina_data):
        resp = client.post("/reportes/nomina", json=sample_nomina_data)
        data = resp.json()
        assert data["totales"]["total_empleados"] == "3"

    def test_dept_summary(self, client, sample_nomina_data):
        resp = client.post("/reportes/nomina", json=sample_nomina_data)
        data = resp.json()
        # Last section should be department summary
        last_section = data["secciones"][-1]
        assert last_section["titulo"] == "Resumen por Departamento"

    def test_empty_data(self, client):
        resp = client.post("/reportes/nomina", json={})
        assert resp.status_code == 200
        assert resp.json()["totales"]["total_empleados"] == "0"


# ===========================================================================
# ROUTES: Formats endpoint
# ===========================================================================

class TestRoutesFormats:
    """Tests de GET /reportes/formats."""

    def test_list_formats(self, client):
        resp = client.get("/reportes/formats")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["formats"]) == 3
        names = [f["name"] for f in data["formats"]]
        assert "json" in names
        assert "csv" in names
        assert "html" in names


# ===========================================================================
# DATACLASSES: ReportData, ReportSection, ReportLine
# ===========================================================================

class TestDataclasses:
    """Tests de las dataclasses del módulo."""

    def test_report_line_to_dict(self):
        rl = ReportLine(concepto="Test", importe=Decimal("100.50"), subconcepto="Sub", nivel=1)
        d = rl.to_dict()
        assert d["concepto"] == "Test"
        assert d["importe"] == "100.50"
        assert d["nivel"] == 1

    def test_report_line_importe_formatted(self):
        rl = ReportLine(concepto="Test", importe=Decimal("1234567.89"))
        assert rl.importe_formatted == "$1,234,567.89"

    def test_report_section_to_dict(self):
        rs = ReportSection(
            titulo="Sección Test",
            lineas=[ReportLine(concepto="Línea", importe=Decimal("500"))],
            subtotal=Decimal("500"),
            subtotal_label="Total Test",
        )
        d = rs.to_dict()
        assert d["titulo"] == "Sección Test"
        assert len(d["lineas"]) == 1
        assert d["subtotal"] == "500"

    def test_report_section_subtotal_formatted(self):
        rs = ReportSection(titulo="Test", subtotal=Decimal("9999.99"))
        assert rs.subtotal_formatted == "$9,999.99"

    def test_report_data_to_dict(self):
        rd = ReportData(titulo="Test Report", subtitulo="Subtitle")
        d = rd.to_dict()
        assert d["titulo"] == "Test Report"
        assert "secciones" in d
        assert "totales" in d
        assert "metadata" in d

    def test_report_data_default_fecha(self):
        rd = ReportData(titulo="Test", subtitulo="Sub")
        assert rd.fecha_generacion != ""


# ===========================================================================
# EDGE CASES & INTEGRATION
# ===========================================================================

class TestEdgeCases:
    """Tests de casos extremos e integración."""

    def test_negative_amounts_balance(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Pérdida", "importe": -5000}],
        )
        assert report.secciones[0].subtotal == Decimal("-5000")

    def test_negative_amounts_nomina(self):
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "Test", "rfc": "T001", "salario_bruto": 10000, "deducciones": 12000},
            ]
        )
        assert report.totales["total_neto"] == "-2000"

    def test_conciliacion_all_zero(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "Test", "monto": 0, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "Test", "monto": 0, "conciliado": True},
            ],
        )
        assert report.totales["diferencia"] == "0"
        assert report.totales["conciliado"] == "True"

    def test_balance_large_values(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Big", "importe": 999999999999}],
        )
        assert report.totales["total_activos"] == "999999999999"

    def test_estado_resultados_all_zero(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Nada", "importe": 0}],
        )
        assert report.totales["utilidad_neta"] == "0"

    def test_many_sections_in_html(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": f"Item {i}", "importe": i} for i in range(20)],
        )
        html = serialize_html(report)
        for i in range(20):
            assert f"Item {i}" in html

    def test_csv_preserves_order(self):
        report = generate_balance_general(
            activos_circulantes=[
                {"concepto": "Zebra", "importe": 100},
                {"concepto": "Alpha", "importe": 200},
            ],
        )
        csv_str = serialize_csv(report)
        assert csv_str.index("Zebra") < csv_str.index("Alpha")

    def test_conciliacion_negative_monto(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "Retiro", "monto": -5000, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "Pago", "monto": -5000, "conciliado": True},
            ],
        )
        assert report.totales["diferencia"] == "0"

    def test_route_all_endpoints_accessible(self, client):
        """Smoke test: all report endpoints respond without error."""
        endpoints = [
            "/reportes/formats",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 200, f"Failed: {ep}"

    def test_route_post_endpoints_empty_body(self, client):
        """All POST endpoints accept empty JSON body."""
        post_endpoints = [
            "/reportes/balance",
            "/reportes/estado-resultados",
            "/reportes/conciliacion",
            "/reportes/nomina",
        ]
        for ep in post_endpoints:
            resp = client.post(ep, json={})
            assert resp.status_code == 200, f"Failed: {ep}"
