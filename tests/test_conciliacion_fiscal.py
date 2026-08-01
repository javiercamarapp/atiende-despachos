# -*- coding: utf-8 -*-
"""Tests for the Conciliación Fiscal module."""
import pytest
from b2b_ai.features.conciliacion_fiscal.models import (
    FiscalComparison,
    FiscalDiscrepancy,
    FiscalReport,
    Omission,
    TipoDiscrepancia,
    TipoOmicion,
)
from b2b_ai.features.conciliacion_fiscal.service import FiscalConciliationService
from b2b_ai.features.conciliacion_fiscal.validators import (
    cross_reference_data,
    validate_fiscal_amounts,
    validate_fiscal_period,
)


# ---------------------------------------------------------------------------
# Validators tests
# ---------------------------------------------------------------------------

class TestValidateFiscalPeriod:
    def test_valid_period(self):
        ok, err = validate_fiscal_period("2024-01")
        assert ok is True
        assert err == ""

    def test_invalid_format(self):
        ok, err = validate_fiscal_period("2024/01")
        assert ok is False
        assert "inválido" in err

    def test_invalid_month(self):
        ok, err = validate_fiscal_period("2024-13")
        assert ok is False

    def test_empty_period(self):
        ok, err = validate_fiscal_period("")
        assert ok is False

    def test_valid_december(self):
        ok, err = validate_fiscal_period("2024-12")
        assert ok is True


class TestValidateFiscalAmounts:
    def test_valid_amounts(self):
        ok, err = validate_fiscal_amounts(10000.0, 9500.0)
        assert ok is True

    def test_negative_erp(self):
        ok, err = validate_fiscal_amounts(-1000.0, 5000.0)
        assert ok is False
        assert "negativo" in err

    def test_negative_sat(self):
        ok, err = validate_fiscal_amounts(5000.0, -1000.0)
        assert ok is False

    def test_zero_amounts(self):
        ok, err = validate_fiscal_amounts(0.0, 0.0)
        assert ok is True


class TestCrossReferenceData:
    def test_matching_data(self):
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        sat = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        ok, issues = cross_reference_data(erp, sat)
        assert ok is True
        assert len(issues) == 0

    def test_erp_not_in_sat(self):
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        sat = []
        ok, issues = cross_reference_data(erp, sat)
        assert ok is False
        assert len(issues) == 1
        # SAT empty → early return message
        assert "SAT" in issues[0]

    def test_sat_not_in_erp(self):
        erp = []
        sat = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        ok, issues = cross_reference_data(erp, sat)
        assert ok is False
        assert len(issues) == 1
        # ERP empty → early return message
        assert "ERP" in issues[0]

    def test_amount_discrepancy(self):
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        sat = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 900.0}]
        ok, issues = cross_reference_data(erp, sat)
        assert ok is False
        assert any("monto" in i.lower() for i in issues)

    def test_both_empty(self):
        ok, issues = cross_reference_data([], [])
        assert ok is False
        assert "vacías" in issues[0]


# ---------------------------------------------------------------------------
# Models tests
# ---------------------------------------------------------------------------

class TestOmission:
    def test_create_omission(self):
        o = Omission(
            tipo=TipoOmicion.FACTURA_ERP,
            periodo="2024-01",
            monto=5000.0,
            rfc="ABC123",
        )
        assert o.tipo == TipoOmicion.FACTURA_ERP
        assert o.periodo == "2024-01"
        assert o.monto == 5000.0
        assert o.resuelta is False


class TestFiscalDiscrepancy:
    def test_create_discrepancy(self):
        d = FiscalDiscrepancy(
            tipo=TipoDiscrepancia.MONTO,
            erp_amount=1000.0,
            sat_amount=900.0,
            diff=100.0,
        )
        assert d.tipo == TipoDiscrepancia.MONTO
        assert d.diff == 100.0


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestFiscalConciliationService:
    def test_compare_erp_vs_sat_matching(self):
        service = FiscalConciliationService()
        erp = [
            {"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0, "concepto": "Servicios"},
            {"uuid": "uuid-2", "rfc": "DEF456", "monto": 5000.0, "concepto": "Productos"},
        ]
        sat = [
            {"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0, "concepto": "Servicios"},
            {"uuid": "uuid-2", "rfc": "DEF456", "monto": 5000.0, "concepto": "Productos"},
        ]
        comparison = service.compare_erp_vs_sat("t1", 1, 2024, erp, sat)
        assert comparison.erp_total == 15000.0
        assert comparison.sat_total == 15000.0
        assert comparison.diferencia == 0.0
        assert len(comparison.omisiones) == 0
        assert len(comparison.discrepancias) == 0

    def test_compare_erp_vs_sat_with_omissions(self):
        service = FiscalConciliationService()
        erp = [
            {"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0},
            {"uuid": "uuid-2", "rfc": "DEF456", "monto": 5000.0},
        ]
        sat = [
            {"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0},
        ]
        comparison = service.compare_erp_vs_sat("t1", 1, 2024, erp, sat)
        assert len(comparison.omisiones) == 1
        assert comparison.omisiones[0].tipo == TipoOmicion.FACTURA_ERP

    def test_compare_erp_vs_sat_with_discrepancies(self):
        service = FiscalConciliationService()
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0, "concepto": "Servicios"}]
        sat = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 9500.0, "concepto": "Servicios"}]
        comparison = service.compare_erp_vs_sat("t1", 1, 2024, erp, sat)
        assert len(comparison.discrepancias) == 1
        assert comparison.discrepancias[0].tipo == TipoDiscrepancia.MONTO
        assert comparison.discrepancias[0].diff == 500.0

    def test_detect_omissions(self):
        service = FiscalConciliationService()
        erp = [{"uuid": "uuid-1"}, {"uuid": "uuid-2"}]
        sat = [{"uuid": "uuid-1"}]
        omissions = service.detect_omissions(erp, sat, "2024-01")
        assert len(omissions) == 1
        assert omissions[0].uuid_cfdi == "uuid-2"

    def test_detect_discrepancies_rfc(self):
        service = FiscalConciliationService()
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 1000.0}]
        sat = [{"uuid": "uuid-1", "rfc": "XYZ789", "monto": 1000.0}]
        disc = service.detect_discrepancies(erp, sat, "2024-01")
        assert len(disc) == 1
        assert disc[0].tipo == TipoDiscrepancia.RFC

    def test_generate_fiscal_report(self):
        service = FiscalConciliationService()
        comparison = FiscalComparison(
            erp_total=10000.0,
            sat_total=9500.0,
            diferencia=500.0,
            periodo="2024-01",
        )
        report = service.generate_fiscal_report(comparison)
        assert report.id.startswith("FR-")
        assert report.comparison.periodo == "2024-01"
        assert len(report.recomendaciones) > 0

    def test_generate_report_no_issues(self):
        service = FiscalConciliationService()
        comparison = FiscalComparison(
            erp_total=10000.0,
            sat_total=10000.0,
            diferencia=0.0,
            periodo="2024-01",
        )
        report = service.generate_fiscal_report(comparison)
        assert len(report.recomendaciones) == 1
        assert "conciliados" in report.recomendaciones[0].lower()

    def test_resolve_omission(self):
        service = FiscalConciliationService()
        erp = [{"uuid": "uuid-1", "rfc": "ABC123", "monto": 10000.0}]
        sat = []
        comparison = service.compare_erp_vs_sat("t1", 1, 2024, erp, sat)
        assert len(comparison.omisiones) == 1

        omission_id = comparison.omisiones[0].id
        resolved = service.resolve_omission("2024-01", omission_id)
        assert resolved is True
        assert comparison.omisiones[0].resuelta is True

    def test_resolve_nonexistent(self):
        service = FiscalConciliationService()
        resolved = service.resolve_omission("2024-01", "nonexistent")
        assert resolved is False

    def test_empty_data(self):
        service = FiscalConciliationService()
        comparison = service.compare_erp_vs_sat("t1", 1, 2024, [], [])
        assert comparison.erp_total == 0.0
        assert comparison.sat_total == 0.0
        assert comparison.diferencia == 0.0
