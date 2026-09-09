# -*- coding: utf-8 -*-
"""Integración: los jobs de batch async de b2b_ai/api/v2.py (`_new_job` /
`_finish_job` / `_get_job` / `_count_jobs`) respaldados por JobStore real de
PostgreSQL (SCALE-02).

Ejercita las mismas funciones internas que usan las rutas `POST
/api/v2/batch` (con `async: true`) y `GET /api/v2/batch/{id}` -- ver
`b2b_ai/api/v2.py::batch()` / `batch_status()` / `_run_job()` -- sin tener
que levantar la app FastAPI completa (eso ya lo cubre
tests/test_api_v2.py::test_batch_async, que sigue pasando sin cambios
porque no fija B2B_DB_URL y por lo tanto usa el fallback en memoria).

Requiere B2B_DB_URL apuntando a un servidor PostgreSQL alcanzable. Crea su
propia base de datos efímera migrada a head.
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
    dbname = f"b2b_v2jobs_test_{uuid.uuid4().hex[:10]}"
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


@pytest.fixture(autouse=True)
def _reset_job_store_cache():
    from b2b_ai.infrastructure.job_store import _reset_store_cache_for_tests
    _reset_store_cache_for_tests()
    yield
    _reset_store_cache_for_tests()


def test_async_job_survives_in_memory_dict_being_wiped(pg_dsn, monkeypatch):
    """EL CASO PEDIDO en el lado de batch async: se crea un job, se vacía a
    mano el dict `_JOBS` en memoria (simula un restart del proceso -- si el
    backend en memoria estuviera activo, esto sería exactamente el bug
    original: 404 sobre un job que sí corrió), y el job se sigue pudiendo
    leer y actualizar porque vive en Postgres."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("B2B_DB_URL", pg_dsn)

    from b2b_ai.api import v2 as v2mod

    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    job_id = v2mod._new_job(tenant)
    job = v2mod._get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["tenant_id"] == tenant
    assert job["status"] == "running"

    # Simula el proceso reiniciando: se pierde TODO el heap de Python.
    v2mod._JOBS.clear()

    job_after_wipe = v2mod._get_job(job_id)
    assert job_after_wipe is not None, (
        "El job desapareció al vaciar el dict en memoria -- el backend "
        "activo NO está usando Postgres (regresión al bug SCALE-02)"
    )
    assert job_after_wipe["id"] == job_id
    assert job_after_wipe["tenant_id"] == tenant

    v2mod._finish_job(job_id, {"procesadas": 3, "validas": 3},
                      [{"archivo": "a.xml", "valido": True}])
    v2mod._JOBS.clear()  # de nuevo, para que la lectura no pueda venir del dict
    done = v2mod._get_job(job_id)
    assert done["status"] == "completed"
    assert done["summary"] == {"procesadas": 3, "validas": 3}
    assert done["results"] == [{"archivo": "a.xml", "valido": True}]


def test_async_job_error_path_persists(pg_dsn, monkeypatch):
    """El camino de error de `_run_job()` (excepción no controlada durante
    el procesamiento en background) también debe sobrevivir el vaciado del
    dict en memoria."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("B2B_DB_URL", pg_dsn)

    from b2b_ai.api import v2 as v2mod

    tenant = f"tenant-{uuid.uuid4().hex[:8]}"
    job_id = v2mod._new_job(tenant)
    v2mod._fail_job(job_id, "boom: disco lleno")
    v2mod._JOBS.clear()

    job = v2mod._get_job(job_id)
    assert job is not None
    assert job["status"] == "error"
    assert job["error"] == "boom: disco lleno"


def test_tenant_isolation_preserved_with_postgres_backend(pg_dsn, monkeypatch):
    """P1-1 (aislamiento por tenant) no se debe romper al cambiar de
    backend: `_get_job` devuelve el registro completo, pero es
    `batch_status()` (la ruta) quien compara `job['tenant_id']` contra el
    tenant autenticado -- aquí probamos que ese campo sigue viniendo
    correcto desde Postgres."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("B2B_DB_URL", pg_dsn)

    from b2b_ai.api import v2 as v2mod

    tenant_a = f"a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"b-{uuid.uuid4().hex[:8]}"
    job_id = v2mod._new_job(tenant_a)

    job = v2mod._get_job(job_id)
    assert job["tenant_id"] == tenant_a
    assert job["tenant_id"] != tenant_b


def test_count_jobs_reflects_postgres_not_memory_dict(pg_dsn, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("B2B_DB_URL", pg_dsn)

    from b2b_ai.api import v2 as v2mod

    before = v2mod._count_jobs()
    v2mod._new_job(f"tenant-{uuid.uuid4().hex[:8]}")
    v2mod._new_job(f"tenant-{uuid.uuid4().hex[:8]}")
    v2mod._JOBS.clear()  # el conteo no debe depender del dict en memoria
    after = v2mod._count_jobs()
    assert after == before + 2


def test_falls_back_to_memory_without_postgres(monkeypatch):
    """Sin B2B_DB_URL/DATABASE_URL, sigue exactamente el comportamiento
    preexistente: dict en memoria, se pierde si se vacía (documentado aquí
    a propósito como contraste con los tests de arriba)."""
    monkeypatch.delenv("B2B_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from b2b_ai.api import v2 as v2mod

    job_id = v2mod._new_job("mem-tenant")
    assert v2mod._get_job(job_id) is not None
    assert job_id in v2mod._JOBS

    v2mod._JOBS.clear()
    assert v2mod._get_job(job_id) is None
