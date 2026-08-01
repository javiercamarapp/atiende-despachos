# -*- coding: utf-8 -*-
"""Tests for Fiscal Conciliation (ERP vs SAT) agent."""
from __future__ import annotations

import pytest
from datetime import datetime

from b2b_ai.features.conciliacion_fiscal.models import (
    DeclaracionTipo,
    DiscrepancySeverity,
    ERPRecord,
    SATRecord,
)
from b2b_ai.features.conciliacion_fiscal.service import (
    compare_erp_vs_sat,
    detect_discrepancies,
    detect_omissions,
    generate_fiscal_report,
    get_comparison,
    resolve_discrepancy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def erp_records():
    """Sample ERP records."""
    return [
        ERPRecord(id="erp-1", concepto="iva", monto=50000.00, periodo="2026-06"),
        ERPRecord(id="erp-2", concepto="isr", monto=30000.00, periodo="2026-06"),
        ERPRecord(id="erp-3", concepto="diot", monto=15000.00, periodo="2026-06"),
    ]


@pytest.fixture
def sat_records():
    """Sample SAT records matching ERP."""
    return [
        SATRecord(id="sat-1", tipo=DeclaracionTipo.IVA, monto=50000.00, periodo="2026-06"),
        SATRecord(id="sat-2", tipo=DeclaracionTipo.ISR, monto=30000.00, periodo="2026-06"),
        SATRecord(id="sat-3", tipo=DeclaracionTipo.DIOT, monto=15000.00, periodo="2026-06"),
    ]


@pytest.fixture
def erp_records_with_discrepancy():
    """ERP records with amount mismatches."""
    return [
        ERPRecord(id="erp-d1", concepto="iva", monto=52000.00, periodo="2026-06"),
        ERPRecord(id="erp-d2", concepto="isr", monto=30000.00, periodo="2026-06"),
    ]


@pytest.fixture
def sat_records_with_discrepancy():
    """SAT records with different amounts."""
    return [
        SATRecord(id="sat-d1", tipo=DeclaracionTipo.IVA, monto=50000.00, periodo="2026-06"),
        SATRecord(id="sat-d2", tipo=DeclaracionTipo.ISR, monto=30000.00, periodo="2026-06"),
    ]


# ---------------------------------------------------------------------------
# Tests: Comparison with matching data
# ---------------------------------------------------------------------------

class TestComparisonMatching:
    """Test comparison when ERP and SAT data match perfectly."""

    def test_perfect_match(self, erp_records, sat_records):
        comp = compare_erp_vs_sat(
            tenant_id="tenant-test",
            month=6,
            year=2026,
            erp_records=erp_records,
            sat_records=sat_records,
        )
        assert comp.tenant_id == "tenant-test"
        assert comp.periodo == "2026-06"
        assert comp.erp_total == 95000.00
        assert comp.sat_total == 95000.00
        assert comp.diferencia == 0.0
        assert len(comp.omisiones) == 0
        assert len(comp.discrepancias) == 0

    def test_perfect_match_generates_report(self, erp_records, sat_records):
        comp = compare_erp_vs_sat(
            tenant_id="tenant-test",
            month=6,
            year=2026,
            erp_records=erp_records,
            sat_records=sat_records,
        )
        report = generate_fiscal_report(comp)
        assert report.risk_level == "low"
        assert report.total_omisiones == 0
        assert report.total_discrepancias == 0
        assert len(report.recommendations) == 1
        assert "Sin acciones" in report.recommendations[0]

    def test_empty_data(self):
        comp = compare_erp_vs_sat(
            tenant_id="tenant-empty",
            month=6,
            year=2026,
            erp_records=[],
            sat_records=[],
        )
        assert comp.erp_total == 0.0
        assert comp.sat_total == 0.0
        assert comp.diferencia == 0.0


# ---------------------------------------------------------------------------
# Tests: Omission detection
# ---------------------------------------------------------------------------

class TestOmissionDetection:
    """Test detection of missing SAT declarations."""

    def test_omission_detected(self, erp_records):
        """DIOT in ERP but not in SAT → omission."""
        sat_only_iva_isr = [
            SATRecord(id="sat-1", tipo=DeclaracionTipo.IVA, monto=50000.00, periodo="2026-06"),
            SATRecord(id="sat-2", tipo=DeclaracionTipo.ISR, monto=30000.00, periodo="2026-06"),
        ]
        omisiones = detect_omissions(erp_records, sat_only_iva_isr, "2026-06")
        assert len(omisiones) == 1
        assert omisiones[0].tipo == DeclaracionTipo.DIOT
        assert omisiones[0].monto == 15000.00

    def test_no_omissions_when_all_match(self, erp_records, sat_records):
        omisiones = detect_omissions(erp_records, sat_records, "2026-06")
        assert len(omisiones) == 0

    def test_multiple_omissions(self):
        erp = [
            ERPRecord(id="e1", concepto="iva", monto=10000, periodo="2026-06"),
            ERPRecord(id="e2", concepto="isr", monto=20000, periodo="2026-06"),
            ERPRecord(id="e3", concepto="diot", monto=5000, periodo="2026-06"),
        ]
        # No SAT records at all
        omisiones = detect_omissions(erp, [], "2026-06")
        assert len(omisiones) == 3

    def test_omission_preserves_periodo(self, erp_records):
        sat = [
            SATRecord(id="sat-1", tipo=DeclaracionTipo.IVA, monto=50000.00, periodo="2026-06"),
        ]
        omisiones = detect_omissions(erp_records, sat, "2026-06")
        for o in omisiones:
            assert o.periodo == "2026-06"


# ---------------------------------------------------------------------------
# Tests: Discrepancy calculation
# ---------------------------------------------------------------------------

class TestDiscrepancyCalculation:
    """Test detection of amount mismatches."""

    def test_discrepancy_detected(self, erp_records_with_discrepancy, sat_records_with_discrepancy):
        disc = detect_discrepancies(erp_records_with_discrepancy, sat_records_with_discrepancy)
        assert len(disc) == 1
        assert disc[0].erp_amount == 52000.00
        assert disc[0].sat_amount == 50000.00
        assert disc[0].diff == 2000.00
        assert disc[0].concepto == "iva"

    def test_no_discrepancy_when_matching(self, erp_records, sat_records):
        disc = detect_discrepancies(erp_records, sat_records)
        assert len(disc) == 0

    def test_severity_high_for_large_diff(self):
        erp = [ERPRecord(id="e1", concepto="iva", monto=100000, periodo="2026-06")]
        sat = [SATRecord(id="s1", tipo=DeclaracionTipo.IVA, monto=80000, periodo="2026-06")]
        disc = detect_discrepancies(erp, sat)
        assert len(disc) == 1
        assert disc[0].severity == DiscrepancySeverity.HIGH

    def test_severity_critical_for_huge_diff(self):
        erp = [ERPRecord(id="e1", concepto="iva", monto=100000, periodo="2026-06")]
        sat = [SATRecord(id="s1", tipo=DeclaracionTipo.IVA, monto=50000, periodo="2026-06")]
        disc = detect_discrepancies(erp, sat)
        assert disc[0].severity == DiscrepancySeverity.CRITICAL

    def test_penny_differences_ignored(self):
        erp = [ERPRecord(id="e1", concepto="iva", monto=10000.00, periodo="2026-06")]
        sat = [SATRecord(id="s1", tipo=DeclaracionTipo.IVA, monto=10000.01, periodo="2026-06")]
        disc = detect_discrepancies(erp, sat)
        assert len(disc) == 0

    def test_comparison_stores_discrepancies(self, erp_records_with_discrepancy, sat_records_with_discrepancy):
        comp = compare_erp_vs_sat(
            tenant_id="tenant-disc",
            month=6,
            year=2026,
            erp_records=erp_records_with_discrepancy,
            sat_records=sat_records_with_discrepancy,
        )
        assert len(comp.discrepancias) == 1
        assert comp.diferencia == 2000.00

    def test_resolve_discrepancy(self, erp_records_with_discrepancy, sat_records_with_discrepancy):
        comp = compare_erp_vs_sat(
            tenant_id="tenant-resolve",
            month=6,
            year=2026,
            erp_records=erp_records_with_discrepancy,
            sat_records=sat_records_with_discrepancy,
        )
        assert len(comp.discrepancias) == 1
        result = resolve_discrepancy(comp.id, 0)
        assert result is True
        comp2 = get_comparison(comp.id)
        assert len(comp2.discrepancias) == 0
        assert comp2.status == "resolved"

    def test_resolve_nonexistent_returns_false(self):
        result = resolve_discrepancy("nonexistent-id", 0)
        assert result is False
