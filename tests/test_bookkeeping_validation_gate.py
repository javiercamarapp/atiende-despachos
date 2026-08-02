# -*- coding: utf-8 -*-
"""test_bookkeeping_validation_gate.py — Validation gate for unbalanced pólizas.

Covers:
  - Unbalanced póliza blocks ERP registration
  - Balanced póliza allows ERP registration
  - Low-confidence classification triggers needs_override
  - Pipeline stage tracking through the gate
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

os.environ.setdefault("B2B_ENV", "test")

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    PolizaContable,
    PolizaType,
    LineaPoliza,
    PipelineStage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_classification(
    uuid="CFDI-001",
    categoria="papeleria",
    confidence=0.95,
    needs_review=False,
    subtotal=1000.0,
    iva=160.0,
    total=1160.0,
):
    return CFDIClassification(
        cfdi_uuid=uuid,
        rfc_emisor="XAXX010101000",
        rfc_receptor="TEST220101CD2",
        descripcion="Test expense",
        subtotal=subtotal,
        iva=iva,
        total=total,
        categoria=categoria,
        confidence=confidence,
        needs_human_review=needs_review,
    )


def _make_poliza(
    poliza_id="POL-001",
    debe=1160.0,
    haber=1160.0,
    cuadrada=True,
):
    return PolizaContable(
        id=poliza_id,
        tipo=PolizaType.EGRESO,
        fecha="2026-01-15",
        concepto="Test poliza",
        lineas=[
            LineaPoliza(cuenta="601", concepto="Gasto", debe=debe, haber=0, tipo="cargo"),
            LineaPoliza(cuenta="111", concepto="Banco", debe=0, haber=haber, tipo="abono"),
        ],
        total_debe=debe,
        total_haber=haber,
        cuadrada=cuadrada,
    )


def _make_pipeline_orchestrator(
    classifications=None,
    polizas=None,
    erp_results=None,
    override_stats=None,
):
    """Build a PipelineOrchestrator with mocked dependencies."""
    from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator

    if classifications is None:
        classifications = [_make_classification()]
    if polizas is None:
        polizas = [_make_poliza()]
    if erp_results is None:
        from b2b_ai.features.bookkeeping.erp_registrar import ERPRegistrationResult
        erp_results = [
            ERPRegistrationResult(success=True, erp_reference="ERP-REF-001")
        ]

    classifier = MagicMock()
    classifier.predict.return_value = ("papeleria", 0.95)
    classifier.get_suggestions.return_value = []
    classifier.CONFIDENCE_MEDIUM = 0.5

    rules_engine = MagicMock()
    rules_engine.get_mapping.return_value = MagicMock(cargo="601", abono="111")

    journal_gen = MagicMock()
    journal_gen.generate_batch.return_value = polizas

    erp_registrar = MagicMock()
    erp_registrar.register_batch.return_value = erp_results
    erp_registrar.get_status.return_value = {"connected": True}

    override_manager = MagicMock()
    override_manager.get_override.return_value = None
    override_manager.get_statistics.return_value = override_stats or {"total": 0}

    pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
    pipe._classifier = classifier
    pipe._rules = rules_engine
    pipe._journal_gen = journal_gen
    pipe._erp = erp_registrar
    pipe._overrides = override_manager
    pipe._jobs = {}

    return pipe, erp_registrar


# ---------------------------------------------------------------------------
# Tests: Validation gate blocks unbalanced pólizas
# ---------------------------------------------------------------------------

class TestValidationGate:
    """Unbalanced pólizas must block ERP registration."""

    def test_unbalanced_poliza_blocks_erp(self):
        """An unbalanced póliza (debe != haber) prevents ERP registration."""
        unbalanced = _make_poliza(debe=1160.0, haber=1000.0, cuadrada=False)
        pipe, erp_registrar = _make_pipeline_orchestrator(polizas=[unbalanced])

        cfdi_data = {
            "uuid": "CFDI-001",
            "rfc_emisor": "XAXX010101000",
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "tipo": "I",
        }

        job = pipe.process_cfdis([cfdi_data], tenant_id="t1", auto_register_erp=True)

        # ERP should NOT have been called
        erp_registrar.register_batch.assert_not_called()

        # Job should have errors about unbalanced póliza
        assert len(job.errors) > 0
        assert any("no cuadrada" in e for e in job.errors)

        # Job should stay at GENERATING_POLIZA stage
        assert job.stage == PipelineStage.GENERATING_POLIZA

        # Should have 0 ERP references
        assert len(job.erp_references) == 0

    def test_multiple_unbalanced_polizas_reported(self):
        """Multiple unbalanced pólizas should all be reported in errors."""
        p1 = _make_poliza(poliza_id="POL-001", debe=100, haber=50, cuadrada=False)
        p2 = _make_poliza(poliza_id="POL-002", debe=200, haber=180, cuadrada=False)
        pipe, erp_registrar = _make_pipeline_orchestrator(polizas=[p1, p2])

        cfdi_data = {"uuid": "CFDI-001", "subtotal": 100, "iva": 16, "total": 116, "tipo": "I"}
        job = pipe.process_cfdis([cfdi_data], tenant_id="t1", auto_register_erp=True)

        erp_registrar.register_batch.assert_not_called()
        assert len(job.errors) >= 2
        assert any("POL-001" in e for e in job.errors)
        assert any("POL-002" in e for e in job.errors)


class TestBalancedPoliza:
    """Balanced pólizas should proceed to ERP registration."""

    def test_balanced_poliza_registers_in_erp(self):
        """A balanced póliza allows ERP registration."""
        balanced = _make_poliza(debe=1160.0, haber=1160.0, cuadrada=True)
        pipe, erp_registrar = _make_pipeline_orchestrator(polizas=[balanced])

        cfdi_data = {
            "uuid": "CFDI-001",
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "tipo": "I",
        }

        job = pipe.process_cfdis([cfdi_data], tenant_id="t1", auto_register_erp=True)

        # ERP SHOULD have been called
        erp_registrar.register_batch.assert_called_once()

        # Job should complete
        assert job.stage == PipelineStage.COMPLETED
        assert len(job.errors) == 0
        assert len(job.erp_references) == 1

    def test_no_erp_registration_when_disabled(self):
        """auto_register_erp=False should skip ERP registration."""
        balanced = _make_poliza(debe=1160.0, haber=1160.0, cuadrada=True)
        pipe, erp_registrar = _make_pipeline_orchestrator(polizas=[balanced])

        cfdi_data = {
            "uuid": "CFDI-001",
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "tipo": "I",
        }

        job = pipe.process_cfdis([cfdi_data], tenant_id="t1", auto_register_erp=False)

        erp_registrar.register_batch.assert_not_called()
        # But job should still complete
        assert job.stage == PipelineStage.COMPLETED


class TestLowConfidenceOverride:
    """Low-confidence classifications should flag needs_override."""

    def test_low_confidence_flags_override(self):
        """Classification with confidence < medium → needs_human_review."""
        balanced = _make_poliza(cuadrada=True)
        pipe, _ = _make_pipeline_orchestrator(polizas=[balanced])

        # Override the mock classifier to return low confidence
        pipe._classifier.predict.return_value = ("otros", 0.3)
        pipe._classifier.CONFIDENCE_MEDIUM = 0.5

        cfdi_data = {
            "uuid": "CFDI-001",
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "tipo": "I",
        }

        job = pipe.process_cfdis([cfdi_data], tenant_id="t1")

        assert job.overrides_needed >= 1

    def test_high_confidence_no_override(self):
        """High confidence → no overrides needed."""
        high_conf = _make_classification(confidence=0.95, needs_review=False)
        balanced = _make_poliza(cuadrada=True)
        pipe, _ = _make_pipeline_orchestrator(
            classifications=[high_conf], polizas=[balanced],
        )

        cfdi_data = {
            "uuid": "CFDI-001",
            "subtotal": 1000.0,
            "iva": 160.0,
            "total": 1160.0,
            "tipo": "I",
        }

        job = pipe.process_cfdis([cfdi_data], tenant_id="t1")

        assert job.overrides_needed == 0


class TestPipelineJobTracking:
    """Pipeline job should track stage transitions."""

    def test_job_tracks_cfdi_uuids(self):
        balanced = _make_poliza(cuadrada=True)
        pipe, _ = _make_pipeline_orchestrator(polizas=[balanced])

        cfdis = [
            {"uuid": "CFDI-001", "subtotal": 1000, "iva": 160, "total": 1160, "tipo": "I"},
            {"uuid": "CFDI-002", "subtotal": 2000, "iva": 320, "total": 2320, "tipo": "I"},
        ]

        job = pipe.process_cfdis(cfdis, tenant_id="t1")

        assert "CFDI-001" in job.cfdi_uuids
        assert "CFDI-002" in job.cfdi_uuids
        assert job.tenant_id == "t1"

    def test_job_stores_polizas(self):
        balanced = _make_poliza(cuadrada=True)
        pipe, _ = _make_pipeline_orchestrator(polizas=[balanced])

        cfdi_data = {"uuid": "CFDI-001", "subtotal": 1000, "iva": 160, "total": 1160, "tipo": "I"}
        job = pipe.process_cfdis([cfdi_data], tenant_id="t1")

        assert len(job.polizas) == 1
        assert job.polizas[0].id == "POL-001"

    def test_job_get_by_id(self):
        balanced = _make_poliza(cuadrada=True)
        pipe, _ = _make_pipeline_orchestrator(polizas=[balanced])

        cfdi_data = {"uuid": "CFDI-001", "subtotal": 1000, "iva": 160, "total": 1160, "tipo": "I"}
        job = pipe.process_cfdis([cfdi_data], tenant_id="t1")

        retrieved = pipe.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_pipeline_exception_marks_failed(self):
        """If the classifier raises, job should be marked FAILED."""
        from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator

        classifier = MagicMock()
        classifier.predict.side_effect = RuntimeError("Model crash")
        classifier.CONFIDENCE_MEDIUM = 0.5

        pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
        pipe._classifier = classifier
        pipe._rules = MagicMock()
        pipe._journal_gen = MagicMock()
        pipe._erp = MagicMock()
        pipe._overrides = MagicMock()
        pipe._overrides.get_override.return_value = None
        pipe._jobs = {}

        cfdi_data = {"uuid": "CFDI-001", "subtotal": 1000, "iva": 160, "total": 1160, "tipo": "I"}
        job = pipe.process_cfdis([cfdi_data], tenant_id="t1")

        assert job.stage == PipelineStage.FAILED
        assert len(job.errors) > 0
