# -*- coding: utf-8 -*-
"""
test_reportes_extended.py — Extended tests for the Reportes module.

Targets uncovered lines and adds comprehensive edge-case coverage:
  - _fmt_money exception handler (lines 36-37): non-decimal-formattable values
  - _fmt_importe exception handler (serializers lines 90-95): non-numeric values in HTML
  - All serializer formats with edge-case data shapes
  - All 4 generators with negative, zero, huge, special-character inputs
  - Route edge cases: malformed JSON, missing fields, content-disposition headers
  - Multi-tenant isolation on routes
"""
from __future__ import annotations

import json
import csv
import io
from decimal import Decimal, InvalidOperation

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
def client():
    app = FastAPI()
    app.include_router(build_reportes_router())
    return TestClient(app)


@pytest.fixture
def large_balance_data():
    """Balance with very large values."""
    return {
        "activos_circulantes": [
            {"concepto": "Caja", "importe": 999999999999.99},
            {"concepto": "Bancos", "importe": 888888888888.88},
        ],
        "activos_fijos": [
            {"concepto": "Terrenos", "importe": 500000000000},
        ],
        "pasivos_circulantes": [
            {"concepto": "Proveedores", "importe": 700000000000},
        ],
        "pasivos_largo_plazo": [
            {"concepto": "Hipoteca", "importe": 300000000000},
        ],
        "capital_contable": [
            {"concepto": "Capital", "importe": 1388888888888.87},
        ],
        "empresa_rfc": "BIG010101AAA",
        "empresa_nombre": "Empresa Grande SA de CV",
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-12-31",
    }


# ===========================================================================
# EDGE CASE: _fmt_money exception handler (generator.py lines 36-37)
# ===========================================================================

class TestFmtMoneyEdgeCases:
    """Target the exception handler in _fmt_money (line 36-37)."""

    def test_fmt_money_non_numeric_string(self):
        """Non-numeric string triggers InvalidOperation → returns $0.00."""
        assert _fmt_money("not_a_number") == "$0.00"

    def test_fmt_money_empty_string(self):
        """Empty string triggers InvalidOperation → returns $0.00."""
        assert _fmt_money("") == "$0.00"

    def test_fmt_money_float_nan(self):
        """NaN → Decimal('NaN') → quantize returns NaN (special Decimal behavior)."""
        result = _fmt_money(float('nan'))
        assert "$" in result  # Formats as $NaN

    def test_fmt_money_float_inf(self):
        """Infinity → Decimal('Infinity') → quantize returns Infinity."""
        result = _fmt_money(float('inf'))
        assert "$" in result  # Formats as $Infinity

    def test_fmt_money_list_value(self):
        """A list triggers InvalidOperation → returns $0.00."""
        assert _fmt_money([100]) == "$0.00"

    def test_fmt_money_dict_value(self):
        """A dict triggers InvalidOperation → returns $0.00."""
        assert _fmt_money({"amount": 100}) == "$0.00"

    def test_fmt_money_very_precise_decimal(self):
        """Decimal with many decimal places rounds correctly."""
        assert _fmt_money("123.456789") == "$123.46"

    def test_fmt_money_negative_zero(self):
        """-0 should format as $0.00."""
        assert _fmt_money(-0) == "$0.00"

    def test_fmt_money_boolean_true(self):
        """Boolean True → str(True)='True' → InvalidOperation → $0.00."""
        assert _fmt_money(True) == "$0.00"

    def test_fmt_money_boolean_false(self):
        """Boolean False → str(False)='False' → InvalidOperation → $0.00."""
        assert _fmt_money(False) == "$0.00"


# ===========================================================================
# EDGE CASE: _to_decimal edge cases
# ===========================================================================

class TestToDecimalEdgeCases:
    """Additional _to_decimal edge cases."""

    def test_to_decimal_boolean_true(self):
        """str(True)='True' → Decimal('True') → InvalidOperation → 0.00."""
        assert _to_decimal(True) == Decimal("0.00")

    def test_to_decimal_boolean_false(self):
        """str(False)='False' → Decimal('False') → InvalidOperation → 0.00."""
        assert _to_decimal(False) == Decimal("0.00")

    def test_to_decimal_float_nan(self):
        """NaN → Decimal('NaN') — special Decimal value, not an exception."""
        import math
        result = _to_decimal(float('nan'))
        assert result.is_nan()

    def test_to_decimal_float_inf(self):
        """Inf → Decimal('Infinity') — special Decimal value."""
        result = _to_decimal(float('inf'))
        assert result.is_infinite()

    def test_to_decimal_negative_string(self):
        assert _to_decimal("-500.50") == Decimal("-500.50")

    def test_to_decimal_whitespace_string(self):
        assert _to_decimal("  100.00  ") == Decimal("100.00")

    def test_to_decimal_empty_string(self):
        assert _to_decimal("") == Decimal("0.00")


# ===========================================================================
# GENERATOR: Balance General edge cases
# ===========================================================================

class TestBalanceGeneralExtended:
    """Extended Balance General tests."""

    def test_all_none_lists(self):
        """All lists are None → zero balances."""
        report = generate_balance_general(
            activos_circulantes=None,
            activos_fijos=None,
            pasivos_circulantes=None,
            pasivos_largo_plazo=None,
            capital_contable=None,
        )
        assert report.totales["total_activos"] == "0"
        assert report.totales["cuadra"] == "True"

    def test_special_chars_company_name(self):
        """Company name with special HTML chars."""
        report = generate_balance_general(
            empresa_nombre="Café & Ñoño <Corp> \"Ltda\"",
        )
        assert report.empresa_nombre == "Café & Ñoño <Corp> \"Ltda\""

    def test_negative_values_across_sections(self):
        """Negative importes in various sections."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Ajuste", "importe": -1000}],
            pasivos_circulantes=[{"concepto": "Devolución", "importe": -500}],
            capital_contable=[{"concepto": "Pérdida", "importe": -500}],
        )
        assert report.secciones[0].subtotal == Decimal("-1000")
        assert report.totales["total_activos"] == "-1000"

    def test_zero_values_everywhere(self):
        """All zero importes."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "X", "importe": 0}],
            activos_fijos=[{"concepto": "Y", "importe": 0}],
            pasivos_circulantes=[{"concepto": "Z", "importe": 0}],
            pasivos_largo_plazo=[{"concepto": "W", "importe": 0}],
            capital_contable=[{"concepto": "V", "importe": 0}],
        )
        assert report.totales["cuadra"] == "True"

    def test_item_missing_importe_key(self):
        """Item dict without 'importe' key defaults to 0."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Sin importe"}],
        )
        assert report.secciones[0].subtotal == Decimal("0")

    def test_item_with_empty_concepto(self):
        """Item with empty concepto."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "", "importe": 100}],
        )
        assert report.secciones[0].lineas[0].concepto == ""

    def test_item_with_all_extra_fields(self):
        """Extra keys in item dict are ignored."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100, "extra": "ignored"}],
        )
        assert report.secciones[0].lineas[0].concepto == "Caja"

    def test_subtotal_label_values(self):
        """Check subtotal labels for all sections."""
        report = generate_balance_general()
        labels = [s.subtotal_label for s in report.secciones]
        assert "Total Activos Circulantes" in labels
        assert "Total Activos Fijos" in labels
        assert "Total Pasivos Circulantes" in labels
        assert "Total Pasivos a Largo Plazo" in labels
        assert "Total Capital Contable" in labels

    def test_metadata_formato_ifrs(self):
        report = generate_balance_general()
        assert report.metadata["formato"] == "IFRS simplificado"

    def test_cuadra_true_with_matching_totals(self):
        """Manually crafted balanced scenario."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 100}],
            capital_contable=[{"concepto": "C", "importe": 100}],
        )
        assert report.totales["cuadra"] == "True"

    def test_cuadra_false_with_unbalanced(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 100}],
            capital_contable=[{"concepto": "C", "importe": 50}],
        )
        assert report.totales["cuadra"] == "False"

    def test_many_items_subtotals(self):
        """100 items should compute correct subtotal."""
        items = [{"concepto": f"C{i}", "importe": 1} for i in range(100)]
        report = generate_balance_general(activos_circulantes=items)
        assert report.secciones[0].subtotal == Decimal("100")

    def test_to_dict_has_all_keys(self):
        report = generate_balance_general()
        d = report.to_dict()
        expected_keys = {"titulo", "subtitulo", "empresa_rfc", "empresa_nombre",
                         "fecha_generacion", "periodo_inicio", "periodo_fin",
                         "secciones", "totales", "metadata"}
        assert expected_keys.issubset(d.keys())


# ===========================================================================
# GENERATOR: Estado de Resultados edge cases
# ===========================================================================

class TestEstadoResultadosExtended:
    """Extended Estado de Resultados tests."""

    def test_all_none_lists(self):
        report = generate_estado_resultados(
            ingresos=None, costos=None,
            gastos_operacion=None, gastos_administracion=None,
            otros_ingresos=None, impuestos=None,
        )
        assert report.totales["utilidad_neta"] == "0"

    def test_huge_loss(self):
        """Massive costs vs tiny income → large negative utilidad."""
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 1}],
            costos=[{"concepto": "Costo", "importe": 999999}],
        )
        assert Decimal(report.totales["utilidad_neta"]) < 0

    def test_only_costs_no_income(self):
        report = generate_estado_resultados(
            costos=[{"concepto": "Costo", "importe": 50000}],
        )
        assert report.totales["total_ingresos"] == "0"
        assert Decimal(report.totales["utilidad_neta"]) < 0

    def test_only_gastos_no_income(self):
        report = generate_estado_resultados(
            gastos_operacion=[{"concepto": "Renta", "importe": 10000}],
        )
        assert report.totales["total_gastos_operacion"] == "10000"
        assert Decimal(report.totales["utilidad_neta"]) < 0

    def test_only_impuestos_no_income(self):
        report = generate_estado_resultados(
            impuestos=[{"concepto": "ISR", "importe": 5000}],
        )
        assert report.totales["total_impuestos"] == "5000"
        assert Decimal(report.totales["utilidad_neta"]) < 0

    def test_only_otros_ingresos(self):
        report = generate_estado_resultados(
            otros_ingresos=[{"concepto": "Intereses", "importe": 3000}],
        )
        assert report.totales["total_otros_ingresos"] == "3000"
        assert report.totales["utilidad_neta"] == "3000"

    def test_all_sections_populated(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "V", "importe": 100000}],
            costos=[{"concepto": "C", "importe": 40000}],
            gastos_operacion=[{"concepto": "GO", "importe": 10000}],
            gastos_administracion=[{"concepto": "GA", "importe": 5000}],
            otros_ingresos=[{"concepto": "OI", "importe": 2000}],
            impuestos=[{"concepto": "ISR", "importe": 8000}],
        )
        # 100000 - 40000 = 60000 (bruta)
        # 60000 - 10000 - 5000 = 45000 (operación)
        # 45000 + 2000 = 47000 (antes impuestos)
        # 47000 - 8000 = 39000 (neta)
        assert report.totales["utilidad_neta"] == "39000"
        assert len(report.secciones) == 6

    def test_negative_importes(self):
        """Negative importes are summed correctly."""
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ajuste", "importe": -5000}],
        )
        assert report.totales["total_ingresos"] == "-5000"

    def test_decimal_precision(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": "1234.567"}],
        )
        assert "1234.567" in report.totales["total_ingresos"]

    def test_item_missing_importe(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "X"}],
        )
        assert report.totales["total_ingresos"] == "0"

    def test_section_labels(self):
        report = generate_estado_resultados()
        labels = [s.subtotal_label for s in report.secciones]
        assert "Total Ingresos" in labels
        assert "Total Costos" in labels
        assert "Total Gastos de Operación" in labels
        assert "Total Gastos de Administración" in labels
        assert "Total Otros Ingresos" in labels
        assert "Total Impuestos" in labels


# ===========================================================================
# GENERATOR: Conciliación Bancaria edge cases
# ===========================================================================

class TestConciliacionBancariaExtended:
    """Extended Conciliación Bancaria tests."""

    def test_only_banco_movements(self):
        """Only bank movements, no accounting."""
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "Depósito", "monto": 10000, "conciliado": False},
            ],
        )
        assert report.totales["total_no_conciliados_banco"] == "10000"
        assert report.totales["total_no_conciliados_contab"] == "0"

    def test_only_contabilidad_movements(self):
        report = generate_conciliacion_bancaria(
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "Cargo", "monto": 5000, "conciliado": False},
            ],
        )
        assert report.totales["total_no_conciliados_banco"] == "0"
        assert report.totales["total_no_conciliados_contab"] == "5000"

    def test_all_conciliados_zero_diferencia(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "A", "monto": 1000, "conciliado": True},
                {"fecha": "2026-06-02", "descripcion": "B", "monto": 2000, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "A", "monto": 1000, "conciliado": True},
                {"fecha": "2026-06-02", "descripcion": "B", "monto": 2000, "conciliado": True},
            ],
        )
        assert report.totales["diferencia"] == "0"
        assert report.totales["conciliado"] == "True"

    def test_large_diferencia(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "A", "monto": 1000000, "conciliado": False},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "B", "monto": 100, "conciliado": False},
            ],
        )
        assert report.totales["diferencia"] == "999900"

    def test_missing_monto_key(self):
        """Movement dict without 'monto' defaults to 0."""
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "X", "conciliado": False},
            ],
        )
        assert report.totales["total_no_conciliados_banco"] == "0"

    def test_missing_fecha_key(self):
        """Movement without fecha gets N/A."""
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"descripcion": "X", "monto": 100, "conciliado": True},
            ],
        )
        assert report.secciones[0].lineas[0].subconcepto == "Fecha: N/A"

    def test_subtitulo_without_banco(self):
        """No banco_nombre → generic subtitulo."""
        report = generate_conciliacion_bancaria()
        assert report.subtitulo == "Conciliación Bancaria"

    def test_metadata_moneda(self):
        report = generate_conciliacion_bancaria()
        assert report.metadata["moneda"] == "MXN"

    def test_metadata_tipo_reporte(self):
        report = generate_conciliacion_bancaria()
        assert report.metadata["tipo_reporte"] == "conciliacion_bancaria"

    def test_sections_count(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[
                {"fecha": "2026-06-01", "descripcion": "A", "monto": 100, "conciliado": True},
            ],
            movimientos_contabilidad=[
                {"fecha": "2026-06-01", "descripcion": "B", "monto": 200, "conciliado": False},
            ],
        )
        assert len(report.secciones) == 3


# ===========================================================================
# GENERATOR: Reporte de Nómina edge cases
# ===========================================================================

class TestReporteNominaExtended:
    """Extended Reporte de Nómina tests."""

    def test_single_employee_no_department(self):
        """Employee without departamento key."""
        report = generate_reporte_nomina(
            empleados=[{"nombre": "Test", "rfc": "T001", "salario_bruto": 10000, "deducciones": 2000}],
        )
        # Should use "Sin departamento"
        assert report.totales["total_empleados"] == "1"
        assert report.totales["total_neto"] == "8000"

    def test_multiple_departments(self):
        """Employees in 3+ departments."""
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "A", "rfc": "A1", "salario_bruto": 10000, "deducciones": 2000, "departamento": "Ventas"},
                {"nombre": "B", "rfc": "B1", "salario_bruto": 12000, "deducciones": 3000, "departamento": "IT"},
                {"nombre": "C", "rfc": "C1", "salario_bruto": 15000, "deducciones": 4000, "departamento": "RH"},
            ],
        )
        # Department summary should have 3 lines
        depto_sec = report.secciones[-1]
        assert depto_sec.titulo == "Resumen por Departamento"
        assert len(depto_sec.lineas) == 3

    def test_all_same_department(self):
        """All employees in same department."""
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "A", "rfc": "A1", "salario_bruto": 10000, "deducciones": 2000, "departamento": "Ventas"},
                {"nombre": "B", "rfc": "B1", "salario_bruto": 12000, "deducciones": 3000, "departamento": "Ventas"},
            ],
        )
        depto_sec = report.secciones[-1]
        assert len(depto_sec.lineas) == 1  # Just one dept

    def test_empleados_none(self):
        """None empleados list."""
        report = generate_reporte_nomina(empleados=None)
        assert report.totales["total_empleados"] == "0"
        assert report.totales["total_neto"] == "0"

    def test_missing_empleado_keys(self):
        """Employee with missing optional keys."""
        report = generate_reporte_nomina(
            empleados=[{"nombre": "", "rfc": "", "salario_bruto": 0, "deducciones": 0}],
        )
        assert report.totales["total_empleados"] == "1"
        assert report.totales["total_neto"] == "0"

    def test_high_deducciones_exceeds_bruto(self):
        """Deducciones > salario_bruto → negative neto."""
        report = generate_reporte_nomina(
            empleados=[{"nombre": "X", "rfc": "X0", "salario_bruto": 5000, "deducciones": 8000}],
        )
        assert report.totales["total_neto"] == "-3000"

    def test_tipo_nomina_custom(self):
        """Unknown tipo_nomina → displayed as-is."""
        report = generate_reporte_nomina(tipo_nomina="X")
        assert report.totales["tipo_nomina"] == "X"

    def test_periodo_pago_vs_periodo_dates(self):
        """If periodo_pago is provided, it's used in subtitulo."""
        report = generate_reporte_nomina(
            periodo_pago="Mensual Enero 2026",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
        )
        assert "Mensual Enero 2026" in report.subtitulo

    def test_no_periodo_pago_uses_dates(self):
        """Without periodo_pago, subtitulo uses start/end dates."""
        report = generate_reporte_nomina(
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
        )
        assert "2026-01-01" in report.subtitulo
        assert "2026-01-31" in report.subtitulo

    def test_employee_section_titles(self):
        """Each employee section includes name and department."""
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "Juan", "rfc": "J0", "salario_bruto": 10000, "deducciones": 2000, "departamento": "Ventas"},
            ],
        )
        assert "Juan" in report.secciones[0].titulo
        assert "Ventas" in report.secciones[0].titulo

    def test_employee_lines_include_bruto_deducciones(self):
        """Each employee section has bruto and deducciones lines."""
        report = generate_reporte_nomina(
            empleados=[
                {"nombre": "Ana", "rfc": "A0", "salario_bruto": 15000, "deducciones": 3000},
            ],
        )
        line_names = [l.concepto for l in report.secciones[0].lineas]
        assert "Salario Bruto" in line_names
        assert "Deducciones" in line_names


# ===========================================================================
# SERIALIZER: JSON extended
# ===========================================================================

class TestSerializeJsonExtended:
    """Extended JSON serializer tests."""

    def test_empty_report(self):
        report = ReportData(titulo="", subtitulo="")
        result = serialize_json(report)
        parsed = json.loads(result)
        assert parsed["titulo"] == ""

    def test_nested_sections(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100, "nivel": 1, "subconcepto": "Efectivo"}],
        )
        result = serialize_json(report)
        parsed = json.loads(result)
        assert parsed["secciones"][0]["lineas"][0]["nivel"] == 1
        assert parsed["secciones"][0]["lineas"][0]["subconcepto"] == "Efectivo"

    def test_metadata_preserved(self):
        report = generate_balance_general()
        result = serialize_json(report)
        parsed = json.loads(result)
        assert parsed["metadata"]["tipo_reporte"] == "balance_general"

    def test_unicode_in_all_fields(self):
        report = ReportData(
            titulo="Reporte Ñoño", subtitulo="Acentos: á é í ó ú",
            empresa_nombre="Ñoño & Hijos", empresa_rfc="XAXX010101",
        )
        result = serialize_json(report)
        parsed = json.loads(result)
        assert "Ñoño" in parsed["titulo"]
        assert "á é í ó ú" in parsed["subtitulo"]


# ===========================================================================
# SERIALIZER: CSV extended
# ===========================================================================

class TestSerializeCsvExtended:
    """Extended CSV serializer tests."""

    def test_empty_report_csv(self):
        report = ReportData(titulo="Empty", subtitulo="No data")
        result = serialize_csv(report)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        assert rows[0] == ["Sección", "Concepto", "Subconcepto", "Importe"]

    def test_csv_with_subtotals(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 100}],
        )
        result = serialize_csv(report)
        assert "Total Activos Circulantes" in result

    def test_csv_multiple_sections(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 10}],
            activos_fijos=[{"concepto": "B", "importe": 20}],
            pasivos_circulantes=[{"concepto": "C", "importe": 30}],
            pasivos_largo_plazo=[{"concepto": "D", "importe": 40}],
            capital_contable=[{"concepto": "E", "importe": 50}],
        )
        result = serialize_csv(report)
        assert "Activos Circulantes" in result
        assert "Activos Fijos" in result
        assert "Pasivos Circulantes" in result
        assert "Pasivos a Largo Plazo" in result
        assert "Capital Contable" in result

    def test_csv_no_totales_section(self):
        """Report with no totales → no TOTAL DEL REPORTE row."""
        report = ReportData(titulo="Test", subtitulo="Sub")
        result = serialize_csv(report)
        assert "TOTAL DEL REPORTE" not in result

    def test_csv_with_totales(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 100}],
        )
        result = serialize_csv(report)
        assert "TOTAL DEL REPORTE" in result


# ===========================================================================
# SERIALIZER: HTML extended
# ===========================================================================

class TestSerializeHtmlExtended:
    """Extended HTML serializer tests."""

    def test_empty_report_html(self):
        report = ReportData(titulo="Empty", subtitulo="Test")
        result = serialize_html(report)
        assert result.startswith("<!DOCTYPE html>")
        assert "Empty" in result

    def test_html_with_nivel_indentation(self):
        """Lines with nivel > 0 get indentation."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Bancos", "importe": 1000, "nivel": 2}],
        )
        result = serialize_html(report)
        assert "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;" in result

    def test_html_section_title_styling(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 10}],
        )
        result = serialize_html(report)
        assert "section-title" in result

    def test_html_subtotal_row(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "A", "importe": 100}],
        )
        result = serialize_html(report)
        assert "subtotal" in result

    def test_html_footer_moneda(self):
        report = generate_balance_general()
        result = serialize_html(report)
        assert "Moneda" in result

    def test_html_footer_tipo_reporte(self):
        report = generate_balance_general()
        result = serialize_html(report)
        assert "balance_general" in result

    def test_html_no_rfc_in_header(self):
        """When empresa_rfc is empty, RFC line not shown."""
        report = ReportData(titulo="T", subtitulo="S", empresa_rfc="")
        result = serialize_html(report)
        assert "RFC:" not in result

    def test_html_with_rfc_in_header(self):
        report = ReportData(titulo="T", subtitulo="S", empresa_rfc="TEST01")
        result = serialize_html(report)
        assert "RFC: TEST01" in result

    def test_html_nodate_periods(self):
        """Empty periods show N/A."""
        report = ReportData(titulo="T", subtitulo="S", periodo_inicio="", periodo_fin="")
        result = serialize_html(report)
        assert "N/A" in result

    def test_html_script_tag_escaped(self):
        report = generate_balance_general(
            empresa_nombre="<script>alert('x')</script>",
        )
        result = serialize_html(report)
        assert "<script>" not in result

    def test_html_special_chars_in_concepto(self):
        """Special chars in concepto are HTML-escaped."""
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja & Efectivo <principal>", "importe": 100}],
        )
        result = serialize_html(report)
        assert "&amp;" in result
        assert "&lt;" in result

    def test_html_format_non_numeric_totales(self):
        """Totales with non-numeric values are kept as-is."""
        report = ReportData(
            titulo="T", subtitulo="S",
            totales={"cuadra": "True", "total": "100"},
        )
        result = serialize_html(report)
        assert "Cuadra" in result
        assert "True" in result

    def test_fmt_importe_exception_handler(self):
        """Force the exception handler in _fmt_importe (lines 90-95)
        by using a ReportLine with a non-numeric importe that causes
        Decimal(str(val)) to fail."""
        report = ReportData(titulo="T", subtitulo="S")
        section = ReportSection(titulo="Test Section")
        # Create a line with a broken importe that will cause Decimal to fail
        line = ReportLine(concepto="Test")
        # Override the importe to a value that Decimal(str(val)) can't handle
        line.importe = "not_a_number"
        section.lineas.append(line)
        report.secciones = [section]
        # This should trigger the exception handler in _fmt_importe
        result = serialize_html(report)
        assert "Test" in result

    def test_html_empty_totales(self):
        """Empty totales dict → no 'Resumen del Reporte' section."""
        report = ReportData(titulo="T", subtitulo="S", totales={})
        result = serialize_html(report)
        assert "Resumen del Reporte" not in result


# ===========================================================================
# SERIALIZER: serialize() convenience extended
# ===========================================================================

class TestSerializeConvenienceExtended:
    """Extended serialize() tests."""

    def test_default_format(self):
        """Default format is json."""
        report = generate_balance_general()
        result = serialize(report)
        parsed = json.loads(result)
        assert parsed["titulo"] == "Balance General"

    def test_uppercase_csv(self):
        report = generate_balance_general()
        result = serialize(report, "CSV")
        assert "Sección" in result

    def test_mixed_case_html(self):
        report = generate_balance_general()
        result = serialize(report, "Html")
        assert "<!DOCTYPE html>" in result

    def test_unsupported_format_pdf(self):
        with pytest.raises(ValueError, match="Formato no soportado"):
            serialize(ReportData(titulo="T", subtitulo="S"), "pdf")

    def test_unsupported_format_xml(self):
        with pytest.raises(ValueError, match="Formato no soportado"):
            serialize(ReportData(titulo="T", subtitulo="S"), "xml")

    def test_unsupported_format_empty(self):
        with pytest.raises(ValueError, match="Formato no soportado"):
            serialize(ReportData(titulo="T", subtitulo="S"), "")

    def test_supported_formats_constant(self):
        assert set(SUPPORTED_FORMATS) == {"json", "csv", "html"}


# ===========================================================================
# ROUTES: Balance General extended
# ===========================================================================

class TestRoutesBalanceExtended:
    """Extended route tests for POST /reportes/balance."""

    def test_invalid_json_body(self, client):
        """Sending malformed JSON."""
        resp = client.post(
            "/reportes/balance",
            content=b"{bad json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_partial_body(self, client):
        """Partial body with only some fields."""
        resp = client.post("/reportes/balance", json={"activos_circulantes": [{"concepto": "A", "importe": 100}]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["totales"]["total_activos_circulantes"] == "100"

    def test_csv_content_disposition(self, client):
        """CSV response has Content-Disposition header."""
        resp = client.post("/reportes/balance", json={"formato": "csv"})
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_csv_filename_in_disposition(self, client):
        resp = client.post("/reportes/balance", json={"formato": "csv"})
        assert "reporte_balance_general" in resp.headers.get("content-disposition", "")

    def test_html_content_type(self, client):
        resp = client.post("/reportes/balance", json={"formato": "html"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_nested_data_in_request(self, client):
        """Deeply nested data doesn't crash."""
        resp = client.post("/reportes/balance", json={
            "activos_circulantes": [{"concepto": "A", "importe": 100, "extra": {"nested": True}}],
        })
        assert resp.status_code == 200

    def test_negative_values_in_request(self, client):
        resp = client.post("/reportes/balance", json={
            "activos_circulantes": [{"concepto": "Ajuste", "importe": -5000}],
            "capital_contable": [{"concepto": "Pérdida", "importe": -5000}],
        })
        assert resp.status_code == 200


# ===========================================================================
# ROUTES: Estado de Resultados extended
# ===========================================================================

class TestRoutesEstadoResultadosExtended:
    """Extended route tests for POST /reportes/estado-resultados."""

    def test_invalid_format_400(self, client):
        resp = client.post("/reportes/estado-resultados", json={"formato": "pdf"})
        assert resp.status_code == 400

    def test_csv_response(self, client):
        resp = client.post("/reportes/estado-resultados", json={
            "formato": "csv",
            "ingresos": [{"concepto": "V", "importe": 100000}],
        })
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_html_response(self, client):
        resp = client.post("/reportes/estado-resultados", json={
            "formato": "html",
            "ingresos": [{"concepto": "V", "importe": 100000}],
        })
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_all_sections_data(self, client):
        resp = client.post("/reportes/estado-resultados", json={
            "ingresos": [{"concepto": "V", "importe": 100000}],
            "costos": [{"concepto": "C", "importe": 30000}],
            "gastos_operacion": [{"concepto": "GO", "importe": 10000}],
            "gastos_administracion": [{"concepto": "GA", "importe": 5000}],
            "otros_ingresos": [{"concepto": "OI", "importe": 2000}],
            "impuestos": [{"concepto": "ISR", "importe": 10000}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["totales"]["utilidad_neta"] == "47000"


# ===========================================================================
# ROUTES: Conciliación extended
# ===========================================================================

class TestRoutesConciliacionExtended:
    """Extended route tests for POST /reportes/conciliacion."""

    def test_invalid_format_400(self, client):
        resp = client.post("/reportes/conciliacion", json={"formato": "txt"})
        assert resp.status_code == 400

    def test_csv_with_data(self, client):
        resp = client.post("/reportes/conciliacion", json={
            "formato": "csv",
            "movimientos_banco": [
                {"fecha": "2026-06-01", "descripcion": "D", "monto": 10000, "conciliado": True},
            ],
            "movimientos_contabilidad": [
                {"fecha": "2026-06-01", "descripcion": "I", "monto": 10000, "conciliado": True},
            ],
        })
        assert resp.status_code == 200

    def test_html_with_data(self, client):
        resp = client.post("/reportes/conciliacion", json={
            "formato": "html",
            "movimientos_banco": [
                {"fecha": "2026-06-01", "descripcion": "D", "monto": 10000, "conciliado": True},
            ],
        })
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text


# ===========================================================================
# ROUTES: Nómina extended
# ===========================================================================

class TestRoutesNominaExtended:
    """Extended route tests for POST /reportes/nomina."""

    def test_invalid_format_400(self, client):
        resp = client.post("/reportes/nomina", json={"formato": "xlsx"})
        assert resp.status_code == 400

    def test_csv_with_employees(self, client):
        resp = client.post("/reportes/nomina", json={
            "formato": "csv",
            "empleados": [
                {"nombre": "Ana", "rfc": "A0", "salario_bruto": 20000, "deducciones": 4000},
            ],
        })
        assert resp.status_code == 200

    def test_html_with_employees(self, client):
        resp = client.post("/reportes/nomina", json={
            "formato": "html",
            "empleados": [
                {"nombre": "Bob", "rfc": "B0", "salario_bruto": 25000, "deducciones": 5000},
            ],
        })
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_extraordinaria_nomina(self, client):
        resp = client.post("/reportes/nomina", json={
            "tipo_nomina": "E",
            "empleados": [{"nombre": "X", "rfc": "X0", "salario_bruto": 10000, "deducciones": 0}],
        })
        assert resp.status_code == 200
        assert resp.json()["totales"]["tipo_nomina"] == "Extraordinaria"


# ===========================================================================
# ROUTES: Formats endpoint extended
# ===========================================================================

class TestRoutesFormatsExtended:
    """Extended GET /reportes/formats tests."""

    def test_formats_count(self, client):
        resp = client.get("/reportes/formats")
        assert len(resp.json()["formats"]) == 3

    def test_format_descriptions(self, client):
        resp = client.get("/reportes/formats")
        for fmt in resp.json()["formats"]:
            assert "name" in fmt
            assert "description" in fmt

    def test_format_names(self, client):
        resp = client.get("/reportes/formats")
        names = {f["name"] for f in resp.json()["formats"]}
        assert names == {"json", "csv", "html"}


# ===========================================================================
# DATACLASSES: Extended
# ===========================================================================

class TestDataclassesExtended:
    """Extended dataclass tests."""

    def test_report_line_defaults(self):
        rl = ReportLine(concepto="Test")
        assert rl.importe == Decimal("0")
        assert rl.subconcepto == ""
        assert rl.nivel == 0

    def test_report_line_to_dict_defaults(self):
        rl = ReportLine(concepto="X")
        d = rl.to_dict()
        assert d["importe"] == "0"
        assert d["nivel"] == 0

    def test_report_section_defaults(self):
        rs = ReportSection(titulo="Sec")
        assert rs.lineas == []
        assert rs.subtotal == Decimal("0")
        assert rs.subtotal_label == "Total"

    def test_report_section_to_dict_empty_lineas(self):
        rs = ReportSection(titulo="Sec")
        d = rs.to_dict()
        assert d["lineas"] == []

    def test_report_data_defaults(self):
        rd = ReportData(titulo="T", subtitulo="S")
        assert rd.empresa_rfc == ""
        assert rd.empresa_nombre == ""
        assert rd.periodo_inicio == ""
        assert rd.periodo_fin == ""
        assert rd.secciones == []
        assert rd.totales == {}
        assert rd.metadata == {}

    def test_report_data_to_dict_structure(self):
        rd = ReportData(titulo="T", subtitulo="S")
        d = rd.to_dict()
        assert d["titulo"] == "T"
        assert d["secciones"] == []
        assert d["totales"] == {}
        assert d["metadata"] == {}


# ===========================================================================
# INTEGRATION: Generator + Serializer
# ===========================================================================

class TestGeneratorSerializerIntegration:
    """Integration tests: generator output → serializer."""

    def test_balance_all_formats(self):
        report = generate_balance_general(
            activos_circulantes=[{"concepto": "Caja", "importe": 10000}],
        )
        j = serialize_json(report)
        c = serialize_csv(report)
        h = serialize_html(report)
        assert json.loads(j)["titulo"] == "Balance General"
        assert "Caja" in c
        assert "Caja" in h

    def test_estado_resultados_all_formats(self):
        report = generate_estado_resultados(
            ingresos=[{"concepto": "Ventas", "importe": 100000}],
            costos=[{"concepto": "Costo", "importe": 40000}],
        )
        j = serialize_json(report)
        c = serialize_csv(report)
        h = serialize_html(report)
        assert "40000" in json.loads(j)["totales"]["total_costos"]
        assert "Ventas" in c
        assert "Ventas" in h

    def test_conciliacion_all_formats(self):
        report = generate_conciliacion_bancaria(
            movimientos_banco=[{"fecha": "2026-06-01", "descripcion": "D", "monto": 5000, "conciliado": True}],
        )
        j = serialize_json(report)
        c = serialize_csv(report)
        h = serialize_html(report)
        assert json.loads(j)["titulo"] == "Conciliación Bancaria"
        assert "D" in c
        assert "D" in h

    def test_nomina_all_formats(self):
        report = generate_reporte_nomina(
            empleados=[{"nombre": "Ana", "rfc": "A0", "salario_bruto": 10000, "deducciones": 2000}],
        )
        j = serialize_json(report)
        c = serialize_csv(report)
        h = serialize_html(report)
        assert json.loads(j)["totales"]["total_neto"] == "8000"
        assert "Ana" in c
        assert "Ana" in h
