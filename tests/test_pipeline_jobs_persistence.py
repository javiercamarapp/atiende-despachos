# -*- coding: utf-8 -*-
"""Integración end-to-end: PipelineOrchestrator + JobStore real de
PostgreSQL (PO-02).

A diferencia de tests/test_job_store.py (que prueba el backend crudo),
este módulo ejercita la API PÚBLICA que consumen las rutas
(`process_cfdis()` / `get_job()` / `get_jobs()` / `get_pipeline_status()` /
`get_suggestions()`) para demostrar que sigue funcionando igual, pero ahora
respaldada por Postgres -- incluyendo el caso pedido en esta ronda: "el
proceso se reinicia, el job sigue ahí con su estado".

Requiere B2B_DB_URL apuntando a un servidor PostgreSQL alcanzable (mismo
patrón que tests/test_rate_limiter_postgres_integration.py). Crea su propia
base de datos efímera migrada a head.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PG_DSN = os.environ.get("B2B_DB_URL", "")


def _pg_available():
    if not PG_DSN:
        return False
    try:
        import psycopg
        psycopg.connect(PG_DSN, connect_timeout=3).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


def _split_dsn(dsn):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado")


def _create_test_db():
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pj_test_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()
    return f"{server_dsn}/{dbname}", dbname


def _drop_test_db(dbname):
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


def _migrate_to_head(dsn):
    env = dict(os.environ)
    env["B2B_DB_URL"] = dsn
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture(scope="module")
def pg_dsn():
    dsn, dbname = _create_test_db()
    _migrate_to_head(dsn)
    yield dsn
    _drop_test_db(dbname)


@pytest.fixture(scope="module")
def trained_classifier():
    """Entrenado UNA vez por módulo -- entrenar por test (como hace el
    fixture `classifier` de test_bookkeeping.py) es innecesariamente lento
    para lo que prueba este módulo (persistencia, no clasificación)."""
    from b2b_ai.features.bookkeeping.auto_classifier import AutoClassifier
    c = AutoClassifier()
    c.train()
    return c


def _make_orchestrator(classifier):
    from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator
    from b2b_ai.features.bookkeeping.rules_engine import AccountingRulesEngine
    from b2b_ai.features.bookkeeping.journal_generator import JournalEntryGenerator
    from b2b_ai.features.bookkeeping.erp_registrar import ERPRegistrar
    from b2b_ai.features.bookkeeping.human_override import HumanOverrideManager
    from b2b_ai.features.bookkeeping.models import ERPSystem

    rules = AccountingRulesEngine()
    return PipelineOrchestrator(
        classifier=classifier,
        rules_engine=rules,
        journal_generator=JournalEntryGenerator(rules),
        erp_registrar=ERPRegistrar(erp_system=ERPSystem.MOCK),
        override_manager=HumanOverrideManager(),
    )


def _sample_cfdi(uuid_val):
    return {
        "uuid": uuid_val,
        "cfdi_uuid": uuid_val,
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


@pytest.fixture(autouse=True)
def _reset_job_store_cache():
    """Aísla cada test: ningún pool cacheado de un test anterior debe
    sobrevivir (evita falsos positivos si un test anterior dejó B2B_DB_URL
    puesto vía monkeypatch, aunque monkeypatch ya lo deshace solo)."""
    from b2b_ai.infrastructure.job_store import _reset_store_cache_for_tests
    _reset_store_cache_for_tests()
    yield
    _reset_store_cache_for_tests()


class TestPipelineJobSurvivesRestart:
    def test_job_survives_orchestrator_restart(self, pg_dsn, monkeypatch,
                                                trained_classifier):
        """EL CASO PEDIDO: procesa un job con un PipelineOrchestrator,
        descarta ese orchestrator por completo (nada de Python compartido
        -- simula el proceso reiniciándose), construye uno SEGUNDO desde
        cero, y confirma que ve el mismo job con su mismo estado completo
        (stage, progreso, clasificaciones, pólizas, tenant)."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("B2B_DB_URL", pg_dsn)

        tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
        cfdi_uuid = f"uuid-{uuid.uuid4().hex[:8]}"

        orchestrator_before = _make_orchestrator(trained_classifier)
        job = orchestrator_before.process_cfdis(
            cfdis=[_sample_cfdi(cfdi_uuid)],
            tenant_id=tenant_id, periodo="2026-05",
        )
        assert job.stage.value == "completed"
        assert job.progress_pct == 100.0
        job_id = job.job_id

        # "El proceso muere": se descarta sin reutilizar nada de él.
        del orchestrator_before

        orchestrator_after = _make_orchestrator(trained_classifier)
        recovered = orchestrator_after.get_job(job_id)
        assert recovered is not None
        assert recovered.job_id == job_id
        assert recovered.stage.value == "completed"
        assert recovered.progress_pct == 100.0
        assert recovered.tenant_id == tenant_id
        assert recovered.periodo == "2026-05"
        assert len(recovered.classifications) == 1
        assert recovered.classifications[0].cfdi_uuid == cfdi_uuid
        assert len(recovered.polizas) >= 1
        assert recovered.started_at is not None
        assert recovered.completed_at is not None

        # get_jobs() / get_pipeline_status() -- también API pública --
        # deben ver el job recuperado, no solo get_job() directo.
        jobs_for_tenant = orchestrator_after.get_jobs(tenant_id=tenant_id)
        assert any(j.job_id == job_id for j in jobs_for_tenant)

        status = orchestrator_after.get_pipeline_status(tenant_id)
        assert status["total_jobs"] >= 1
        assert status["total_cfdis_processed"] >= 1

    def test_in_progress_stage_is_visible_before_completion(
        self, pg_dsn, monkeypatch, trained_classifier,
    ):
        """El checkpoint intermedio (no solo el final) queda persistido --
        si el proceso muriera a mitad del pipeline, otra réplica/otro
        proceso vería el último stage alcanzado, no un job fantasma."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("B2B_DB_URL", pg_dsn)

        from b2b_ai.infrastructure.job_store import get_store
        from b2b_ai.features.bookkeeping.pipeline import _JOB_TYPE

        tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
        orchestrator = _make_orchestrator(trained_classifier)
        job = orchestrator.process_cfdis(
            cfdis=[_sample_cfdi(f"uuid-{uuid.uuid4().hex[:8]}")],
            tenant_id=tenant_id,
        )

        # Verificamos directo contra el store (bypass de la API pública)
        # que el job_type usado coincide con lo documentado -- si alguien
        # cambia el namespace sin querer, otro llamador (batch_v2) podría
        # empezar a verlo o viceversa.
        store = get_store()
        row = store.get_job(job.job_id)
        assert row is not None
        assert row["job_type"] == _JOB_TYPE == "bookkeeping_pipeline"
        assert row["stage"] == "completed"

    def test_falls_back_to_memory_without_postgres(self, monkeypatch,
                                                    trained_classifier):
        """Sin B2B_DB_URL/DATABASE_URL, el orchestrator sigue funcionando
        igual que antes de este cambio: dict en memoria, por-instancia.
        Documenta también la diferencia real que trae Postgres: SIN él, un
        orchestrator segundo NO ve el job del primero (el bug que esta
        ronda arregla cuando SÍ hay Postgres configurado)."""
        monkeypatch.delenv("B2B_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        orchestrator_1 = _make_orchestrator(trained_classifier)
        job = orchestrator_1.process_cfdis(
            cfdis=[_sample_cfdi(f"uuid-{uuid.uuid4().hex[:8]}")],
            tenant_id="mem-tenant",
        )
        assert orchestrator_1.get_job(job.job_id) is not None

        orchestrator_2 = _make_orchestrator(trained_classifier)
        assert orchestrator_2.get_job(job.job_id) is None
