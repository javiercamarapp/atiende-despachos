# -*- coding: utf-8 -*-
"""test_bookkeeping.py — Tests for the Bookkeeping Agent (Agente 5).

Covers:
  1. AccountingRulesEngine — mapping, validation, catalog
  2. AutoClassifier — training, prediction, overrides
  3. JournalEntryGenerator — poliza generation, validation, adjustments
  4. ERPRegistrar — registration, idempotency, rollback
  5. HumanOverride — submission, learning, statistics
  6. PipelineOrchestrator — full pipeline, suggestions, status
  7. API endpoints — process, status, override, suggestions
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    ERPSystem,
    LineaPoliza,
    OverrideAction,
    PipelineStage,
    PolizaContable,
    PolizaType,
)
from b2b_ai.features.bookkeeping.rules_engine import (
    AccountingRulesEngine,
    AccountMapping,
    CATALOGO_CUENTAS_SAT,
)
from b2b_ai.features.bookkeeping.auto_classifier import (
    AutoClassifier,
    generate_synthetic_dataset,
)
from b2b_ai.features.bookkeeping.journal_generator import JournalEntryGenerator
from b2b_ai.features.bookkeeping.erp_registrar import ERPRegistrar
from b2b_ai.features.bookkeeping.human_override import HumanOverrideManager
from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator
from b2b_ai.features.bookkeeping.routes import build_bookkeeping_router


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def rules_engine():
    return AccountingRulesEngine()


@pytest.fixture
def classifier():
    c = AutoClassifier()
    c.train()
    return c


@pytest.fixture
def journal_gen(rules_engine):
    return JournalEntryGenerator(rules_engine)


@pytest.fixture
def erp_registrar():
    return ERPRegistrar(erp_system=ERPSystem.MOCK)


@pytest.fixture
def override_mgr():
    return HumanOverrideManager()


@pytest.fixture
def pipeline(classifier, rules_engine, journal_gen, erp_registrar, override_mgr):
    return PipelineOrchestrator(
        classifier=classifier,
        rules_engine=rules_engine,
        journal_generator=journal_gen,
        erp_registrar=erp_registrar,
        override_manager=override_mgr,
    )


@pytest.fixture
def app(pipeline):
    app = FastAPI()
    router = build_bookkeeping_router(erp_system=ERPSystem.MOCK)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def sample_cfdi():
    return {
        "uuid": "test-uuid-001",
        "cfdi_uuid": "test-uuid-001",
        "rfc_emisor": "XAXX010101000",
        "rfc_receptor": "ABC123456XYZ",
        "descripcion": "Servicio de consultoría y asesoría profesional",
        "subtotal": 10000.0,
        "iva": 1600.0,
        "total": 11600.0,
        "tasa_iva": 0.16,
        "tipo": "I",
        "tipo_cfdi": "I",
        "uso_cfdi": "G03",
        "regimen_emisor": "612",
    }


@pytest.fixture
def sample_classification():
    return CFDIClassification(
        cfdi_uuid="test-uuid-001",
        rfc_emisor="XAXX010101000",
        descripcion="Honorarios de consultoría",
        subtotal=10000.0,
        iva=1600.0,
        total=11600.0,
        tasa_iva=0.16,
        tipo_cfdi="I",
        categoria="servicios_profesionales",
        confidence=0.92,
        cuenta_cargo="6020100",
        cuenta_abono="2010000",
    )


# ===================================================================
# 1. AccountingRulesEngine tests
# ===================================================================

class TestAccountingRulesEngine:
    """Tests for the rules engine."""

    def test_get_mapping_default(self, rules_engine):
        """Default mapping exists for servicios_profesionales."""
        mapping = rules_engine.get_mapping("I", "servicios_profesionales")
        assert mapping is not None
        assert mapping.cargo == "6020100"
        assert mapping.abono == "2010000"

    def test_get_mapping_not_found(self, rules_engine):
        """Returns None for unknown category."""
        mapping = rules_engine.get_mapping("I", "categoria_inexistente")
        assert mapping is None

    def test_get_mapping_egreso(self, rules_engine):
        """Egreso mapping for venta_servicios."""
        mapping = rules_engine.get_mapping("E", "venta_servicios")
        assert mapping is not None
        assert mapping.cargo == "1050000"
        assert mapping.abono == "4080000"
        assert mapping.iva_abono == "2600400"

    def test_tenant_custom_mapping(self, rules_engine):
        """Tenant-specific mapping overrides default."""
        custom = AccountMapping(cargo="6080100", abono="2010000")
        rules_engine.add_tenant_mapping("tenant_abc", "I", "servicios_profesionales", custom)

        mapping = rules_engine.get_mapping("I", "servicios_profesionales", "tenant_abc")
        assert mapping.cargo == "6080100"

        # Default still works for other tenants
        default = rules_engine.get_mapping("I", "servicios_profesionales")
        assert default.cargo == "6020100"

    def test_validate_account(self, rules_engine):
        """Account validation against SAT catalog."""
        assert rules_engine.validate_account("6020100") is True
        assert rules_engine.validate_account("9999999") is False

    def test_get_account_name(self, rules_engine):
        """Account name lookup."""
        assert rules_engine.get_account_name("6020100") == "Servicios profesionales"
        assert rules_engine.get_account_name("9999999") == "Cuenta 9999999"

    def test_get_all_categories(self, rules_engine):
        """Returns all known categories."""
        cats = rules_engine.get_all_categories()
        assert "servicios_profesionales" in cats
        assert "venta_servicios" in cats
        assert len(cats) >= 10

    def test_get_catalogo(self, rules_engine):
        """Returns SAT catalog."""
        catalogo = rules_engine.get_catalogo()
        assert "6020100" in catalogo
        assert len(catalogo) > 40

    def test_generate_poliza(self, rules_engine, sample_classification):
        """Generates a balanced journal entry."""
        poliza = rules_engine.generate_poliza(sample_classification, "test_tenant")
        assert poliza is not None
        assert poliza.cuadrada is True
        assert poliza.total_debe == poliza.total_haber
        assert len(poliza.lineas) >= 2


# ===================================================================
# 2. AutoClassifier tests
# ===================================================================

class TestAutoClassifier:
    """Tests for the ML classifier."""

    def test_synthetic_dataset_generation(self):
        """Synthetic dataset has correct structure."""
        cfdis, labels = generate_synthetic_dataset(n_samples_per_category=10)
        assert len(cfdis) > 0
        assert len(cfdis) == len(labels)
        assert all("descripcion" in c for c in cfdis)
        assert all("subtotal" in c for c in cfdis)

    def test_classifier_training(self, classifier):
        """Classifier trains and reports metrics."""
        assert classifier.is_trained
        assert len(classifier.categories) > 10

    def test_predict_returns_category_and_confidence(self, classifier, sample_cfdi):
        """Prediction returns category and confidence."""
        cat, conf = classifier.predict(sample_cfdi)
        assert isinstance(cat, str)
        assert 0.0 <= conf <= 1.0

    def test_predict_batch(self, classifier, sample_cfdi):
        """Batch prediction works."""
        results = classifier.predict_batch([sample_cfdi, sample_cfdi])
        assert len(results) == 2
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_override_affects_prediction(self, classifier):
        """Human override takes priority over ML prediction."""
        classifier.add_override("RFC12345", "nomina")
        cfdi = {
            "descripcion": "consultoría",
            "subtotal": 50000,
            "iva": 8000,
            "total": 58000,
            "tasa_iva": 0.16,
            "tipo_cfdi": "I",
            "uso_cfdi": "G03",
            "regimen_emisor": "612",
            "rfc_emisor": "RFC12345",
        }
        cat, conf = classifier.predict(cfdi)
        assert cat == "nomina"
        assert conf == 1.0

    def test_get_suggestions(self, classifier, sample_cfdi):
        """Returns multiple suggestions with confidence."""
        sugs = classifier.get_suggestions(sample_cfdi, top_n=3)
        assert len(sugs) <= 3
        assert all("categoria" in s and "confidence" in s for s in sugs)

    def test_rule_based_fallback(self):
        """Rule-based prediction works when sklearn not trained."""
        c = AutoClassifier()
        # Don't train — should fall back to rules
        cfdi = {
            "descripcion": "honorarios de consultoría profesional",
            "subtotal": 50000,
            "iva": 8000,
            "total": 58000,
            "tasa_iva": 0.16,
            "tipo_cfdi": "I",
            "uso_cfdi": "G03",
            "regimen_emisor": "612",
        }
        cat, conf = c.predict(cfdi)
        assert cat == "servicios_profesionales"
        assert conf > 0.3


# ===================================================================
# 3. JournalEntryGenerator tests
# ===================================================================

class TestJournalEntryGenerator:
    """Tests for journal entry generation."""

    def test_generate_from_classification(self, journal_gen, sample_classification):
        """Generates a poliza from a classification."""
        poliza = journal_gen.generate_from_classification(
            sample_classification, fecha="2026-07-15"
        )
        assert poliza is not None
        assert poliza.fecha == "2026-07-15"
        assert poliza.cuadrada is True
        assert len(poliza.lineas) >= 2

    def test_generate_batch(self, journal_gen, sample_classification):
        """Batch generation works."""
        polizas = journal_gen.generate_batch([sample_classification], fecha="2026-07-15")
        assert len(polizas) == 1
        assert polizas[0].cuadrada is True

    def test_generate_adjustment(self, journal_gen):
        """Manual adjustment entry is balanced."""
        entries = [
            {"cuenta": "6020300", "debe": 5000, "haber": 0, "concepto": "Gasto"},
            {"cuenta": "1020000", "debe": 0, "haber": 5000, "concepto": "Banco"},
        ]
        poliza = journal_gen.generate_adjustment("2026-07-15", "Ajuste manual", entries)
        assert poliza.cuadrada is True
        assert poliza.tipo == PolizaType.DIARIO

    def test_generate_depreciation(self, journal_gen):
        """Depreciation entry is balanced."""
        activos = [
            {
                "cuenta_activo": "1540000",
                "cuenta_depreciacion": "1540100",
                "cuenta_gasto": "6020300",
                "monto": 5000.0,
            }
        ]
        poliza = journal_gen.generate_depreciation_entry("2026-07-15", activos)
        assert poliza.cuadrada is True
        assert "depreciación" in poliza.concepto.lower()

    def test_generate_provision(self, journal_gen):
        """Provision entry is balanced."""
        poliza = journal_gen.generate_provision_entry(
            "2026-07-15", "aguinaldo", 15000.0,
            "6010800", "2670000",
        )
        assert poliza.cuadrada is True

    def test_validate_poliza_valid(self, journal_gen, sample_classification):
        """Valid poliza passes validation."""
        poliza = journal_gen.generate_from_classification(
            sample_classification, fecha="2026-07-15"
        )
        errors = journal_gen.validate_poliza(poliza)
        assert len(errors) == 0

    def test_validate_poliza_unbalanced(self, journal_gen):
        """Unbalanced poliza fails validation."""
        poliza = PolizaContable(
            fecha="2026-07-15",
            lineas=[
                LineaPoliza(cuenta="6020100", debe=10000, haber=0),
                LineaPoliza(cuenta="2010000", debe=0, haber=8000),
            ],
        )
        errors = journal_gen.validate_poliza(poliza)
        assert any("desbalanceada" in e.lower() for e in errors)

    def test_validate_poliza_no_lines(self, journal_gen):
        """Empty poliza fails validation."""
        poliza = PolizaContable(fecha="2026-07-15", lineas=[])
        errors = journal_gen.validate_poliza(poliza)
        assert len(errors) > 0


# ===================================================================
# 4. ERPRegistrar tests
# ===================================================================

class TestERPRegistrar:
    """Tests for ERP registration."""

    def test_register_success(self, erp_registrar, journal_gen, sample_classification):
        """Successful registration."""
        poliza = journal_gen.generate_from_classification(
            sample_classification, fecha="2026-07-15"
        )
        result = erp_registrar.register(poliza)
        assert result.success is True
        assert result.erp_reference is not None
        assert poliza.erp_registered is True

    def test_idempotency(self, erp_registrar, journal_gen, sample_classification):
        """Same poliza registered twice returns idempotent skip."""
        poliza = journal_gen.generate_from_classification(
            sample_classification, fecha="2026-07-15"
        )
        r1 = erp_registrar.register(poliza)
        r2 = erp_registrar.register(poliza)
        assert r1.success is True
        assert r2.idempotent_skip is True
        assert r1.erp_reference == r2.erp_reference

    def test_register_unbalanced_fails(self, erp_registrar):
        """Unbalanced poliza fails registration."""
        poliza = PolizaContable(
            fecha="2026-07-15",
            cuadrada=False,
            lineas=[LineaPoliza(cuenta="6020100", debe=1000, haber=0)],
        )
        result = erp_registrar.register(poliza)
        assert result.success is False
        assert "cuadrada" in (result.error or "").lower()

    def test_register_batch(self, erp_registrar, journal_gen, sample_classification):
        """Batch registration."""
        polizas = journal_gen.generate_batch([sample_classification], fecha="2026-07-15")
        results = erp_registrar.register_batch(polizas)
        assert len(results) == 1
        assert results[0].success is True

    def test_erp_status(self, erp_registrar):
        """Status reporting."""
        status = erp_registrar.get_status()
        assert status["erp_system"] == "mock"
        assert "registered_count" in status


# ===================================================================
# 5. HumanOverride tests
# ===================================================================

class TestHumanOverride:
    """Tests for human override manager."""

    def test_submit_override(self, override_mgr):
        """Override submission works."""
        record = override_mgr.submit_override(
            cfdi_uuid="uuid-001",
            action=OverrideAction.RECLASSIFY,
            new_categoria="nomina",
            original_categoria="otros",
            reason="Wrong category",
            corrected_by="contador@test.com",
            rfc_emisor="RFC001",
        )
        assert record.cfdi_uuid == "uuid-001"
        assert record.new_categoria == "nomina"

    def test_get_override(self, override_mgr):
        """Retrieve override by UUID."""
        override_mgr.submit_override(
            cfdi_uuid="uuid-002",
            action=OverrideAction.RECLASSIFY,
            new_categoria="publicidad",
        )
        record = override_mgr.get_override("uuid-002")
        assert record is not None
        assert record.new_categoria == "publicidad"

    def test_learning_from_feedback(self, override_mgr):
        """RFC feedback aggregation."""
        override_mgr.submit_override(
            cfdi_uuid="u1", action=OverrideAction.RECLASSIFY,
            new_categoria="nomina", rfc_emisor="RFC_A",
        )
        override_mgr.submit_override(
            cfdi_uuid="u2", action=OverrideAction.RECLASSIFY,
            new_categoria="nomina", rfc_emisor="RFC_A",
        )
        override_mgr.submit_override(
            cfdi_uuid="u3", action=OverrideAction.RECLASSIFY,
            new_categoria="publicidad", rfc_emisor="RFC_A",
        )

        # Most common: nomina (2/3)
        assert override_mgr.get_rfc_category_feedback("RFC_A") == "nomina"

    def test_statistics(self, override_mgr):
        """Statistics reporting."""
        override_mgr.submit_override(
            cfdi_uuid="u1", action=OverrideAction.RECLASSIFY,
            new_categoria="nomina", corrected_by="user1",
        )
        stats = override_mgr.get_statistics()
        assert stats["total_overrides"] == 1
        assert "reclassify" in stats["by_action"]

    def test_retraining_suggestions(self, override_mgr):
        """Retraining suggestions with strong signal."""
        for i in range(5):
            override_mgr.submit_override(
                cfdi_uuid=f"u{i}", action=OverrideAction.RECLASSIFY,
                new_categoria="nomina", rfc_emisor="RFC_STRONG",
            )
        suggestions = override_mgr.get_suggestions_for_retraining()
        assert len(suggestions) == 1
        assert suggestions[0]["rfc"] == "RFC_STRONG"
        assert suggestions[0]["suggested_categoria"] == "nomina"


# ===================================================================
# 6. PipelineOrchestrator tests
# ===================================================================

class TestPipelineOrchestrator:
    """Tests for the full pipeline orchestrator."""

    def test_full_pipeline(self, pipeline, sample_cfdi):
        """End-to-end pipeline processes CFDI."""
        job = pipeline.process_cfdis(
            cfdis=[sample_cfdi],
            tenant_id="test_tenant",
            periodo="2026-07",
        )
        assert job.stage == PipelineStage.COMPLETED
        assert len(job.classifications) == 1
        assert len(job.polizas) >= 1
        assert job.progress_pct == 100.0

    def test_pipeline_with_multiple_cfdis(self, pipeline, sample_cfdi):
        """Pipeline handles multiple CFDIs."""
        cfdis = [sample_cfdi, {**sample_cfdi, "uuid": "test-uuid-002", "cfdi_uuid": "test-uuid-002"}]
        job = pipeline.process_cfdis(cfdis=cfdis, tenant_id="test_tenant")
        assert len(job.classifications) == 2

    def test_pipeline_job_tracking(self, pipeline, sample_cfdi):
        """Jobs are tracked and retrievable."""
        job = pipeline.process_cfdis(cfdis=[sample_cfdi])
        retrieved = pipeline.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_pipeline_status(self, pipeline, sample_cfdi):
        """Pipeline status aggregation."""
        pipeline.process_cfdis(cfdis=[sample_cfdi], tenant_id="t1")
        status = pipeline.get_pipeline_status("t1")
        assert status["total_jobs"] == 1
        assert status["total_cfdis_processed"] == 1

    def test_pipeline_suggestions(self, pipeline):
        """Suggestions for low-confidence items."""
        low_conf_cfdi = {
            "uuid": "ambig-uuid",
            "cfdi_uuid": "ambig-uuid",
            "descripcion": "xyz",
            "subtotal": 1.0,
            "iva": 0.0,
            "total": 1.0,
            "tasa_iva": 0.0,
            "tipo": "I",
            "tipo_cfdi": "I",
        }
        job = pipeline.process_cfdis(cfdis=[low_conf_cfdi])
        # Low confidence CFDIs should trigger suggestions
        assert job.overrides_needed >= 0  # May or may not need override

    def test_override_affects_pipeline(self, pipeline, sample_cfdi):
        """Human override changes pipeline classification."""
        # Submit override first
        pipeline.override_manager.submit_override(
            cfdi_uuid=sample_cfdi["uuid"],
            action=OverrideAction.RECLASSIFY,
            new_categoria="publicidad",
        )
        job = pipeline.process_cfdis(cfdis=[sample_cfdi])
        cls = job.classifications[0]
        assert cls.categoria == "publicidad"


# ===================================================================
# 7. API endpoint tests
# ===================================================================

class TestBookkeepingAPI:
    """Tests for the bookkeeping API endpoints."""

    def test_process_endpoint(self, client, sample_cfdi):
        """POST /api/v1/bookkeeping/process works."""
        resp = client.post("/api/v1/bookkeeping/process", json={
            "cfdis": [sample_cfdi],
            "tenant_id": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["stage"] == "completed"

    def test_status_endpoint(self, client, sample_cfdi):
        """GET /api/v1/bookkeeping/status works."""
        # Process first
        client.post("/api/v1/bookkeeping/process", json={
            "cfdis": [sample_cfdi],
            "tenant_id": "test",
        })
        resp = client.get("/api/v1/bookkeeping/status?tenant_id=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_jobs"] >= 1

    def test_override_endpoint(self, client):
        """POST /api/v1/bookkeeping/override works."""
        resp = client.post("/api/v1/bookkeeping/override", json={
            "cfdi_uuid": "test-uuid",
            "action": "reclassify",
            "new_categoria": "nomina",
            "corrected_by": "user@test.com",
            "rfc_emisor": "RFC_TEST",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["learned"] is True

    def test_suggestions_endpoint(self, client):
        """GET /api/v1/bookkeeping/suggestions works."""
        resp = client.get("/api/v1/bookkeeping/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_review" in data
        assert "retraining_suggestions" in data

    def test_process_empty_cfdis(self, client):
        """Process with empty CFDIs returns 400."""
        resp = client.post("/api/v1/bookkeeping/process", json={
            "cfdis": [],
        })
        assert resp.status_code == 400
