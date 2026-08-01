# -*- coding: utf-8 -*-
"""
tests/test_diot_service.py — Comprehensive tests for the DIOT service layer.

Covers:
  • Parsing operations from XML (file + string)
  • Totals by RFC calculation
  • Summary generation
  • Full pipeline (process_diot)
  • Report generation
  • Edge cases: empty data, malformed XML, multiple operation types
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from b2b_ai.services.diot_service import (
    DIOTOperation,
    DIOTReport,
    DIOTSummary,
    RFCSummary,
    calculate_tipo_operacion_counts,
    calculate_totals_by_rfc,
    generate_report,
    generate_summary,
    operations_from_xml_string,
    parse_diot_file,
    process_diot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_operation_xml(
    rfc: str = "ABC123456789",
    razon_social: str = "Proveedor SA",
    tipo_operacion: str = "01",
    monto: str = "10000.00",
    iva_trasladado: str = "1600.00",
    iva_acreditable: str = "1600.00",
    fecha_operacion: str = "2024-01-15",
) -> ET.Element:
    node = ET.Element("Operacion")
    for tag, val in [
        ("RFC", rfc), ("RazonSocial", razon_social),
        ("TipoOperacion", tipo_operacion), ("Monto", monto),
        ("IVATrasladado", iva_trasladado), ("IVAAcreditable", iva_acreditable),
        ("FechaOperacion", fecha_operacion),
    ]:
        child = ET.SubElement(node, tag)
        child.text = val
    return node


def _make_diot_xml(
    operations: list | None = None,
    declared_iva_trasladado: str | None = None,
) -> str:
    root = ET.Element("DIOT")
    if declared_iva_trasladado is not None:
        total_el = ET.SubElement(root, "TotalIVATrasladado")
        total_el.text = declared_iva_trasladado
    if operations is None:
        operations = [_make_operation_xml()]
    for op in operations:
        root.append(op)
    return ET.tostring(root, encoding="unicode")


# ===========================================================================
# DIOTOperation
# ===========================================================================

class TestDIOTOperation:

    def test_create_operation(self):
        op = DIOTOperation(
            rfc="ABC123456789", razon_social="Test SA",
            tipo_operacion="01", monto=10000,
            iva_trasladado=1600, iva_acreditable=1600,
        )
        assert op.rfc == "ABC123456789"
        assert op.monto == 10000

    def test_tipo_operacion_label_01(self):
        op = DIOTOperation(rfc="A", razon_social="X", tipo_operacion="01", monto=0, iva_trasladado=0, iva_acreditable=0)
        assert op.tipo_operacion_label == "IVA"

    def test_tipo_operacion_label_02(self):
        op = DIOTOperation(rfc="A", razon_social="X", tipo_operacion="02", monto=0, iva_trasladado=0, iva_acreditable=0)
        assert op.tipo_operacion_label == "IEPS"

    def test_tipo_operacion_label_03(self):
        op = DIOTOperation(rfc="A", razon_social="X", tipo_operacion="03", monto=0, iva_trasladado=0, iva_acreditable=0)
        assert op.tipo_operacion_label == "Exento"

    def test_tipo_operacion_label_unknown(self):
        op = DIOTOperation(rfc="A", razon_social="X", tipo_operacion="99", monto=0, iva_trasladado=0, iva_acreditable=0)
        assert "Desconocido" in op.tipo_operacion_label

    def test_to_dict(self):
        op = DIOTOperation(
            rfc="ABC123456789", razon_social="Test",
            tipo_operacion="01", monto=5000,
            iva_trasladado=800, iva_acreditable=800,
        )
        d = op.to_dict()
        assert d["rfc"] == "ABC123456789"
        assert d["monto"] == 5000
        assert "tipo_operacion_label" in d


# ===========================================================================
# RFCSummary
# ===========================================================================

class TestRFCSummary:

    def test_to_dict(self):
        s = RFCSummary(
            rfc="ABC123456789", razon_social="Test",
            total_monto=10000, total_iva_trasladado=1600,
            total_iva_acreditable=1600, num_operations=3,
            operation_types=["IVA"],
        )
        d = s.to_dict()
        assert d["rfc"] == "ABC123456789"
        assert d["num_operations"] == 3
        assert "IVA" in d["operation_types"]


# ===========================================================================
# parse_diot_file
# ===========================================================================

class TestParseDiotFile:

    def test_parse_single_operation(self):
        xml_str = _make_diot_xml()
        ops = parse_diot_file(xml_str)
        assert len(ops) == 1
        assert ops[0].rfc == "ABC123456789"

    def test_parse_multiple_operations(self):
        ops_xml = [
            _make_operation_xml(rfc="ABC123456789", monto="1000"),
            _make_operation_xml(rfc="DEF987654321", monto="2000"),
        ]
        xml_str = _make_diot_xml(operations=ops_xml)
        ops = parse_diot_file(xml_str)
        assert len(ops) == 2

    def test_parse_from_file(self, tmp_path: Path):
        xml_str = _make_diot_xml()
        filepath = tmp_path / "diot_test.xml"
        filepath.write_text(xml_str, encoding="utf-8")
        ops = parse_diot_file(filepath)
        assert len(ops) == 1

    def test_parse_supports_registro_tag(self):
        root = ET.Element("DIOT")
        node = ET.SubElement(root, "Registro")
        for tag, val in [("RFC", "ABC123456789"), ("RazonSocial", "Test"),
                         ("TipoOperacion", "01"), ("Monto", "5000"),
                         ("IVATrasladado", "800"), ("IVAAcreditable", "800")]:
            child = ET.SubElement(node, tag)
            child.text = val
        xml_str = ET.tostring(root, encoding="unicode")
        ops = parse_diot_file(xml_str)
        assert len(ops) == 1
        assert ops[0].rfc == "ABC123456789"

    def test_rfc_uppercased(self):
        root = ET.Element("DIOT")
        node = ET.SubElement(root, "Operacion")
        for tag, val in [("RFC", "abc123456789"), ("RazonSocial", "X"),
                         ("TipoOperacion", "01"), ("Monto", "100"),
                         ("IVATrasladado", "16"), ("IVAAcreditable", "16")]:
            child = ET.SubElement(node, tag)
            child.text = val
        xml_str = ET.tostring(root, encoding="unicode")
        ops = parse_diot_file(xml_str)
        assert ops[0].rfc == "ABC123456789"

    def test_skips_operations_without_rfc(self):
        ops_xml = [
            _make_operation_xml(rfc="ABC123456789"),
            # Node without RFC will be skipped
        ]
        xml_str = _make_diot_xml(operations=ops_xml)
        ops = parse_diot_file(xml_str)
        assert len(ops) >= 1

    def test_operations_from_xml_string(self):
        xml_str = _make_diot_xml()
        ops = operations_from_xml_string(xml_str)
        assert len(ops) == 1


# ===========================================================================
# calculate_totals_by_rfc
# ===========================================================================

class TestCalculateTotalsByRfc:

    def test_single_rfc(self):
        ops = [
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=5000, iva_trasladado=800, iva_acreditable=800),
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=3000, iva_trasladado=480, iva_acreditable=480),
        ]
        by_rfc = calculate_totals_by_rfc(ops)
        assert len(by_rfc) == 1
        assert by_rfc["ABC123456789"].total_monto == 8000
        assert by_rfc["ABC123456789"].total_iva_trasladado == 1280
        assert by_rfc["ABC123456789"].num_operations == 2

    def test_multiple_rfcs(self):
        ops = [
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=5000, iva_trasladado=800, iva_acreditable=800),
            DIOTOperation(rfc="DEF987654321", razon_social="B", tipo_operacion="01",
                          monto=3000, iva_trasladado=480, iva_acreditable=480),
        ]
        by_rfc = calculate_totals_by_rfc(ops)
        assert len(by_rfc) == 2
        assert by_rfc["ABC123456789"].total_monto == 5000
        assert by_rfc["DEF987654321"].total_monto == 3000

    def test_operation_types_aggregated(self):
        ops = [
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=5000, iva_trasladado=800, iva_acreditable=800),
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="03",
                          monto=2000, iva_trasladado=0, iva_acreditable=0),
        ]
        by_rfc = calculate_totals_by_rfc(ops)
        types = by_rfc["ABC123456789"].operation_types
        assert "IVA" in types
        assert "Exento" in types

    def test_empty_operations(self):
        by_rfc = calculate_totals_by_rfc([])
        assert by_rfc == {}


# ===========================================================================
# calculate_tipo_operacion_counts
# ===========================================================================

class TestCalculateTipoOperacionCounts:

    def test_counts(self):
        ops = [
            DIOTOperation(rfc="A", razon_social="", tipo_operacion="01", monto=0, iva_trasladado=0, iva_acreditable=0),
            DIOTOperation(rfc="B", razon_social="", tipo_operacion="01", monto=0, iva_trasladado=0, iva_acreditable=0),
            DIOTOperation(rfc="C", razon_social="", tipo_operacion="03", monto=0, iva_trasladado=0, iva_acreditable=0),
        ]
        counts = calculate_tipo_operacion_counts(ops)
        assert counts["01"] == 2
        assert counts["03"] == 1


# ===========================================================================
# generate_summary
# ===========================================================================

class TestGenerateSummary:

    def test_empty_operations(self):
        s = generate_summary([])
        assert s.total_operations == 0
        assert s.unique_rfcs == 0

    def test_summary_totals(self):
        ops = [
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=5000, iva_trasladado=800, iva_acreditable=600),
            DIOTOperation(rfc="DEF987654321", razon_social="B", tipo_operacion="01",
                          monto=3000, iva_trasladado=480, iva_acreditable=480),
        ]
        s = generate_summary(ops)
        assert s.total_operations == 2
        assert s.unique_rfcs == 2
        assert s.total_monto == pytest.approx(8000, abs=0.01)
        assert s.total_iva_trasladado == pytest.approx(1280, abs=0.01)
        assert s.total_iva_acreditable == pytest.approx(1080, abs=0.01)
        assert s.iva_balance == pytest.approx(200, abs=0.01)

    def test_summary_with_validation(self):
        from b2b_ai.services.diot_validator import DIOTValidationResult
        v = DIOTValidationResult(declared_total_iva_trasladado=1600.0)
        s = generate_summary([], validation=v)
        assert s.declared_total_iva_trasladado == 1600.0

    def test_by_rfc_populated(self):
        ops = [
            DIOTOperation(rfc="ABC123456789", razon_social="A", tipo_operacion="01",
                          monto=5000, iva_trasladado=800, iva_acreditable=800),
        ]
        s = generate_summary(ops)
        assert "ABC123456789" in s.by_rfc

    def test_to_dict(self):
        s = generate_summary([])
        d = s.to_dict()
        assert "total_operations" in d
        assert "by_rfc" in d


# ===========================================================================
# process_diot — full pipeline
# ===========================================================================

class TestProcessDiot:

    def test_valid_xml(self):
        xml_str = _make_diot_xml()
        report = process_diot(xml_str)
        assert isinstance(report, DIOTReport)
        assert len(report.operations) == 1
        assert report.summary is not None
        assert report.validation is not None

    def test_malformed_xml(self):
        report = process_diot("<DIOT><unclosed>")
        assert report.validation is not None
        assert report.validation.valid is False

    def test_multiple_operations(self):
        ops = [
            _make_operation_xml(rfc="ABC123456789", monto="10000", iva_trasladado="1600", iva_acreditable="1600"),
            _make_operation_xml(rfc="DEF987654321", monto="5000", iva_trasladado="800", iva_acreditable="800"),
        ]
        xml_str = _make_diot_xml(operations=ops)
        report = process_diot(xml_str)
        assert len(report.operations) == 2
        assert report.summary.unique_rfcs == 2

    def test_file_path(self, tmp_path: Path):
        xml_str = _make_diot_xml()
        filepath = tmp_path / "test_diot.xml"
        filepath.write_text(xml_str, encoding="utf-8")
        report = process_diot(filepath)
        assert len(report.operations) == 1

    def test_to_dict(self):
        xml_str = _make_diot_xml()
        report = process_diot(xml_str)
        d = report.to_dict()
        assert "operations" in d
        assert "summary" in d
        assert "validation" in d


# ===========================================================================
# generate_report
# ===========================================================================

class TestGenerateReport:

    def test_report_structure(self):
        xml_str = _make_diot_xml()
        report = process_diot(xml_str)
        rpt = generate_report(report)
        assert "overview" in rpt
        assert "by_rfc" in rpt
        assert "by_tipo_operacion" in rpt
        assert "validation_summary" in rpt

    def test_report_overview_values(self):
        ops = [
            _make_operation_xml(rfc="ABC123456789", monto="10000", iva_trasladado="1600", iva_acreditable="1600"),
            _make_operation_xml(rfc="DEF987654321", monto="5000", iva_trasladado="800", iva_acreditable="800"),
        ]
        xml_str = _make_diot_xml(operations=ops)
        report = process_diot(xml_str)
        rpt = generate_report(report)
        assert rpt["overview"]["total_operations"] == 2
        assert rpt["overview"]["total_monto"] == pytest.approx(15000, abs=0.01)
        assert rpt["overview"]["unique_rfcs"] == 2

    def test_report_by_rfc(self):
        xml_str = _make_diot_xml()
        report = process_diot(xml_str)
        rpt = generate_report(report)
        assert "ABC123456789" in rpt["by_rfc"]

    def test_report_by_tipo_operacion_uses_labels(self):
        xml_str = _make_diot_xml()
        report = process_diot(xml_str)
        rpt = generate_report(report)
        assert "IVA" in rpt["by_tipo_operacion"]

    def test_report_empty_operations(self):
        report = DIOTReport()
        rpt = generate_report(report)
        assert rpt["overview"] == {}
        assert rpt["by_rfc"] == {}

    def test_report_validation_errors(self):
        node = _make_operation_xml(rfc="INVALID")
        xml_str = _make_diot_xml(operations=[node])
        report = process_diot(xml_str)
        rpt = generate_report(report)
        assert rpt["validation_summary"]["valid"] is False
        assert rpt["validation_summary"]["error_count"] >= 1
