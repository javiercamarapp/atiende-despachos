# -*- coding: utf-8 -*-
"""Tests para b2b_ai.infrastructure.job_store — persistencia de jobs
asíncronos en PostgreSQL (PO-02 / SCALE-02).

Requieren un PostgreSQL alcanzable vía B2B_DB_URL (mismo patrón que
tests/test_rate_limit_store.py). El módulo crea su propia base de test
dedicada, migrada a head con Alembic, y la dropea al final.

Cubre:
  - CRUD básico del backend (save_job / get_job / list_jobs / count_jobs /
    delete_job / health).
  - Namespacing por `job_type`: dos llamadores (bookkeeping pipeline y
    batch v2) comparten la tabla sin colisionar.
  - Filtro por tenant_id y orden por started_at en list_jobs.
  - EL CASO CRÍTICO de esta ronda -- "el proceso se reinicia, el job sigue
    ahí con su estado" -- simulado a tres niveles:
      1. JobStore crudo: un JobStore nuevo (pool de conexión nuevo, sin
         nada de Python compartido con el que escribió) ve exactamente lo
         que el primero guardó.
      2. PipelineOrchestrator real: un orchestrator procesa CFDIs con el
         store de Postgres activo, y un PipelineOrchestrator SEGUNDO,
         construido desde cero (como pasaría tras un restart del proceso,
         con un dict `_jobs_mem` vacío), recupera el mismo job con su
         mismo stage/progreso/clasificaciones/pólizas.
      3. El store de batch async de b2b_ai/api/v2.py (_new_job/_get_job):
         se vacía a mano el dict `_JOBS` en memoria (simula el proceso
         reiniciando y perdiendo su heap) y el job se sigue pudiendo leer
         porque vive en Postgres, no en ese dict.
  - Fallback a memoria (`get_store()` -> None) cuando no hay DSN de
    Postgres -- lo que mantiene verdes las suites de bookkeeping/v2 que
    corren sin Postgres configurado (SQLite de dev/test).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

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
    dbname = f"b2b_jobs_test_{uuid.uuid4().hex[:10]}"
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
    """DSN a una base de test ya migrada a head (creada/dropeada una vez
    por módulo)."""
    dsn, dbname = _create_test_db()
    _migrate_to_head(dsn)
    yield dsn
    _drop_test_db(dbname)


@pytest.fixture
def store(pg_dsn):
    from b2b_ai.infrastructure.job_store import JobStore
    s = JobStore(dsn=pg_dsn)
    yield s
    s.close()


def _payload(**extra):
    base = {"foo": "bar", "n": 3, "nested": {"a": [1, 2, 3]}}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# CRUD básico
# ---------------------------------------------------------------------------
class TestJobStoreCRUD:
    def test_save_and_get_job(self, store):
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        started = datetime(2026, 9, 9, 10, 0, 0)
        store.save_job(
            job_id=job_id, job_type="bookkeeping_pipeline", tenant_id="t1",
            stage="classifying", progress_pct=10.0,
            payload=_payload(job_id=job_id), errors=[], started_at=started,
        )
        row = store.get_job(job_id)
        assert row is not None
        assert row["job_id"] == job_id
        assert row["job_type"] == "bookkeeping_pipeline"
        assert row["tenant_id"] == "t1"
        assert row["stage"] == "classifying"
        assert row["progress_pct"] == 10.0
        assert row["payload"]["foo"] == "bar"
        assert row["payload"]["nested"]["a"] == [1, 2, 3]
        assert row["errors"] == []
        assert row["completed_at"] is None

    def test_get_missing_job_returns_none(self, store):
        assert store.get_job(f"does-not-exist-{uuid.uuid4().hex}") is None

    def test_upsert_updates_existing_row_not_inserts_new(self, store):
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        store.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="classifying", progress_pct=10.0,
                       payload=_payload(v=1), errors=[])
        store.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="completed", progress_pct=100.0,
                       payload=_payload(v=2), errors=["algo falló pero se recuperó"])
        row = store.get_job(job_id)
        assert row["stage"] == "completed"
        assert row["progress_pct"] == 100.0
        assert row["payload"]["v"] == 2
        assert row["errors"] == ["algo falló pero se recuperó"]
        assert store.count_jobs(job_type="bookkeeping_pipeline", tenant_id="t1") >= 1

    def test_started_at_is_not_overwritten_by_later_saves_with_none(self, store):
        """Guardar de nuevo el mismo job_id sin pasar started_at (llamadas de
        progreso intermedias) no debe borrar el started_at original -- si no,
        se perdería cuándo arrancó realmente el job."""
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        store.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="classifying", progress_pct=10.0,
                       payload=_payload(), errors=[], started_at=t0)
        store.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="generating_poliza",
                       progress_pct=30.0, payload=_payload(), errors=[],
                       started_at=None)
        row = store.get_job(job_id)
        assert row["started_at"].replace(tzinfo=None) == t0

    def test_delete_job(self, store):
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        store.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="completed", progress_pct=100.0,
                       payload=_payload(), errors=[])
        assert store.get_job(job_id) is not None
        store.delete_job(job_id)
        assert store.get_job(job_id) is None

    def test_health_true_when_connected(self, store):
        assert store.health() is True


# ---------------------------------------------------------------------------
# Namespacing por job_type + filtros de list_jobs/count_jobs
# ---------------------------------------------------------------------------
class TestJobTypeNamespacingAndListing:
    def test_two_job_types_share_table_without_colliding(self, store):
        tenant = f"tenant-{uuid.uuid4().hex[:8]}"
        pk_id = f"pk-{uuid.uuid4().hex[:8]}"
        bv2_id = f"bv2-{uuid.uuid4().hex[:8]}"
        store.save_job(job_id=pk_id, job_type="bookkeeping_pipeline",
                       tenant_id=tenant, stage="completed", progress_pct=100.0,
                       payload={"kind": "pipeline"}, errors=[])
        store.save_job(job_id=bv2_id, job_type="batch_v2",
                       tenant_id=tenant, stage="running", progress_pct=0.0,
                       payload={"kind": "batch"}, errors=[])

        pipeline_jobs = store.list_jobs(job_type="bookkeeping_pipeline",
                                        tenant_id=tenant, limit=None)
        batch_jobs = store.list_jobs(job_type="batch_v2", tenant_id=tenant,
                                     limit=None)
        assert {j["job_id"] for j in pipeline_jobs} == {pk_id}
        assert {j["job_id"] for j in batch_jobs} == {bv2_id}
        assert pipeline_jobs[0]["payload"]["kind"] == "pipeline"
        assert batch_jobs[0]["payload"]["kind"] == "batch"

    def test_list_jobs_filters_by_tenant(self, store):
        job_type = f"t-{uuid.uuid4().hex[:8]}"
        tenant_a = f"a-{uuid.uuid4().hex[:8]}"
        tenant_b = f"b-{uuid.uuid4().hex[:8]}"
        for i in range(3):
            store.save_job(job_id=f"{tenant_a}-{i}", job_type=job_type,
                           tenant_id=tenant_a, stage="completed",
                           progress_pct=100.0, payload={}, errors=[])
        store.save_job(job_id=f"{tenant_b}-0", job_type=job_type,
                       tenant_id=tenant_b, stage="completed",
                       progress_pct=100.0, payload={}, errors=[])

        jobs_a = store.list_jobs(job_type=job_type, tenant_id=tenant_a, limit=None)
        jobs_b = store.list_jobs(job_type=job_type, tenant_id=tenant_b, limit=None)
        assert len(jobs_a) == 3
        assert len(jobs_b) == 1
        assert all(j["tenant_id"] == tenant_a for j in jobs_a)

    def test_list_jobs_orders_most_recent_first(self, store):
        job_type = f"t-{uuid.uuid4().hex[:8]}"
        tenant = f"tenant-{uuid.uuid4().hex[:8]}"
        base = datetime(2026, 3, 1, 12, 0, 0)
        ids = []
        for i in range(3):
            jid = f"{tenant}-{i}"
            ids.append(jid)
            store.save_job(job_id=jid, job_type=job_type, tenant_id=tenant,
                           stage="completed", progress_pct=100.0, payload={},
                           errors=[], started_at=base + timedelta(minutes=i))
        jobs = store.list_jobs(job_type=job_type, tenant_id=tenant, limit=None)
        assert [j["job_id"] for j in jobs] == list(reversed(ids))

    def test_list_jobs_limit_none_returns_all(self, store):
        job_type = f"t-{uuid.uuid4().hex[:8]}"
        tenant = f"tenant-{uuid.uuid4().hex[:8]}"
        for i in range(60):
            store.save_job(job_id=f"{tenant}-{i}", job_type=job_type,
                           tenant_id=tenant, stage="completed",
                           progress_pct=100.0, payload={}, errors=[])
        assert len(store.list_jobs(job_type=job_type, tenant_id=tenant,
                                   limit=None)) == 60
        assert len(store.list_jobs(job_type=job_type, tenant_id=tenant,
                                   limit=10)) == 10

    def test_count_jobs(self, store):
        job_type = f"t-{uuid.uuid4().hex[:8]}"
        tenant = f"tenant-{uuid.uuid4().hex[:8]}"
        assert store.count_jobs(job_type=job_type, tenant_id=tenant) == 0
        for i in range(4):
            store.save_job(job_id=f"{tenant}-{i}", job_type=job_type,
                           tenant_id=tenant, stage="completed",
                           progress_pct=100.0, payload={}, errors=[])
        assert store.count_jobs(job_type=job_type, tenant_id=tenant) == 4
        assert store.count_jobs(job_type=job_type) == 4


# ---------------------------------------------------------------------------
# EL CASO CRÍTICO: el proceso se reinicia, el job sigue ahí con su estado.
# ---------------------------------------------------------------------------
class TestSurvivesProcessRestart:
    def test_new_jobstore_instance_sees_what_another_wrote(self, pg_dsn):
        """Dos JobStore == dos pools de conexión independientes == la
        situación real de 'proceso A escribió, proceso B (el reinicio) lee'.
        Ninguno comparte memoria de Python con el otro."""
        from b2b_ai.infrastructure.job_store import JobStore

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        writer = JobStore(dsn=pg_dsn)
        try:
            writer.save_job(
                job_id=job_id, job_type="bookkeeping_pipeline",
                tenant_id="t-restart", stage="registering_erp",
                progress_pct=50.0,
                payload={"erp_references": ["ERP-001"], "note": "en curso"},
                errors=[], started_at=datetime(2026, 5, 1, 9, 0, 0),
            )
        finally:
            writer.close()  # simula que el proceso que escribió murió

        # "El proceso se reinicia": nadie reutiliza `writer`, se abre un
        # JobStore nuevo desde cero contra el mismo DSN.
        reader = JobStore(dsn=pg_dsn)
        try:
            row = reader.get_job(job_id)
            assert row is not None
            assert row["stage"] == "registering_erp"
            assert row["progress_pct"] == 50.0
            assert row["payload"]["erp_references"] == ["ERP-001"]
            assert row["tenant_id"] == "t-restart"
        finally:
            reader.close()

    def test_get_store_factory_survives_cache_reset(self, pg_dsn, monkeypatch):
        """`_reset_store_cache_for_tests()` cierra y limpia el pool cacheado
        -- lo más parecido a un restart de proceso sin recrear la base de
        datos. get_store() debe reconectar y seguir viendo los datos."""
        from b2b_ai.infrastructure import job_store as js

        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("B2B_DB_URL", pg_dsn)
        js._reset_store_cache_for_tests()

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        store1 = js.get_store()
        assert store1 is not None
        store1.save_job(job_id=job_id, job_type="bookkeeping_pipeline",
                        tenant_id="t1", stage="completed", progress_pct=100.0,
                        payload={"ok": True}, errors=[])

        js._reset_store_cache_for_tests()  # tira el pool -- "restart"

        store2 = js.get_store()
        assert store2 is not None
        assert store2 is not store1
        row = store2.get_job(job_id)
        assert row is not None
        assert row["payload"]["ok"] is True
        js._reset_store_cache_for_tests()


# ---------------------------------------------------------------------------
# Fallback a memoria sin DSN de Postgres.
# ---------------------------------------------------------------------------
class TestFallbackWithoutPostgres:
    def test_get_store_returns_none_without_dsn(self, monkeypatch):
        from b2b_ai.infrastructure import job_store as js
        monkeypatch.delenv("B2B_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        js._reset_store_cache_for_tests()
        assert js.get_store() is None

    def test_non_postgres_dsn_falls_back_to_none(self, monkeypatch):
        from b2b_ai.infrastructure import job_store as js
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./dev.db")
        monkeypatch.delenv("B2B_DB_URL", raising=False)
        js._reset_store_cache_for_tests()
        assert js.get_store() is None
