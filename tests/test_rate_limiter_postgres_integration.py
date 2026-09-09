# -*- coding: utf-8 -*-
"""Integración end-to-end: EnterpriseRateLimitMiddleware + backend real de
PostgreSQL, sin pasar un backend explícito (ejercita `_get_backend()` tal
cual lo hace `install_enterprise_rate_limit()` en producción).

Requiere B2B_DB_URL apuntando a un servidor PostgreSQL alcanzable (igual que
tests/test_pg_migrations.py). Crea su PROPIA base de datos efímera migrada a
head (no reutiliza el esquema de B2B_DB_URL tal cual, ni depende de que
otro proceso/test ya la haya migrado) para no pisar ni depender del estado
de otras suites o de otra sesión corriendo en paralelo contra el mismo
servidor.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    dbname = f"b2b_rl_e2e_{uuid.uuid4().hex[:10]}"
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
def e2e_dsn():
    dsn, dbname = _create_test_db()
    _migrate_to_head(dsn)
    yield dsn
    _drop_test_db(dbname)


def _make_tenant(dsn, name):
    import psycopg
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        row = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def _build_app_with_tenant(tenant_id):
    """Una app FastAPI 'worker' que resuelve request.state.tenant_id como
    lo haría el auth middleware real, e instala el rate limiter SIN backend
    explícito -- así se ejercita _get_backend() de verdad."""
    from fastapi import FastAPI, Request
    from starlette.testclient import TestClient
    from b2b_ai.api.rate_limiter import install_enterprise_rate_limit

    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.tenant_id = tenant_id
        return await call_next(request)

    @app.get("/api/v1/data")
    async def data():
        return {"ok": True}

    install_enterprise_rate_limit(app)  # sin backend -> pasa por _get_backend()
    return TestClient(app)


def test_two_separate_apps_share_limit_via_postgres(e2e_dsn, monkeypatch):
    """Prueba el cableado real de producción de punta a punta: dos apps
    FastAPI DISTINTAS, cada una instalando `install_enterprise_rate_limit`
    SIN backend explícito (exactamente como `b2b_ai/api/app.py`), deben
    compartir el mismo consumo para el mismo tenant a través de Postgres.

    Nota: dentro de un solo proceso de test, `get_store()` cachea el pool
    por DSN, así que estas dos apps de hecho comparten el mismo objeto
    `RateLimitStore` -- lo cual es correcto (así se comportaría un solo
    proceso sirviendo varias apps) pero NO es, por sí solo, la prueba de
    "múltiples procesos de SO reales" -- esa la cubren los tests de
    `multiprocessing` en tests/test_rate_limit_store.py::TestMultiProcessConcurrency,
    que sí abren un pool por proceso hijo separado. Lo que este test valida
    es que el camino `install_enterprise_rate_limit -> _get_backend ->
    _get_postgres_backend -> RateLimitStore` está conectado correctamente
    de punta a punta (incluye headers, dispatcher 429, ENDPOINT_LIMITS,
    tenant_id vía request.state) y que ese backend SÍ persiste fuera del
    diccionario en memoria de una `EnterpriseRateLimitMiddleware` -- con el
    backend en memoria (el bug original) cada instancia de middleware trae
    su propio `defaultdict` y este test fallaría igual, sin necesitar
    multiprocessing, porque cada `_MemoryBackend()` se crea fresco por app.
    """
    monkeypatch.delenv("B2B_REDIS_URL", raising=False)
    monkeypatch.setenv("B2B_DB_URL", e2e_dsn)
    from b2b_ai.infrastructure.rate_limit_store import _reset_store_cache_for_tests
    _reset_store_cache_for_tests()  # no arrastrar el pool de otro test/DSN

    tenant_id = _make_tenant(e2e_dsn, f"tenant-e2e-{uuid.uuid4().hex[:8]}")

    # Límite de endpoint específico más bajo para no necesitar 300+ requests.
    from b2b_ai.api import rate_limiter as rl_module
    monkeypatch.setitem(rl_module.ENDPOINT_LIMITS, "/api/v1/data", 5)

    worker_1 = _build_app_with_tenant(tenant_id)
    worker_2 = _build_app_with_tenant(tenant_id)

    for _ in range(5):
        r = worker_1.get("/api/v1/data")
        assert r.status_code == 200, r.text

    # worker_2 usa una instancia de middleware COMPLETAMENTE distinta a la
    # de worker_1 (dos `install_enterprise_rate_limit` separados). Si el
    # backend fuera en memoria (el bug original), worker_2 vería 0
    # peticiones consumidas y respondería 200 cinco veces más (límite real
    # = limite * N workers). Con Postgres como fuente de verdad compartida,
    # ya no tiene cupo.
    r = worker_2.get("/api/v1/data")
    assert r.status_code == 429, (
        "worker_2 no vio el consumo de worker_1 -- el backend NO está "
        "compartiendo estado entre procesos (regresión al bug de memoria)"
    )
    assert r.headers.get("Retry-After") is not None
    _reset_store_cache_for_tests()


def test_falls_back_to_memory_without_postgres_dsn(monkeypatch):
    """Sin B2B_DB_URL/DATABASE_URL configurado, _get_backend() debe seguir
    cayendo a memoria (comportamiento preexistente intacto) en vez de
    fallar o bloquear el arranque de la app."""
    monkeypatch.delenv("B2B_REDIS_URL", raising=False)
    monkeypatch.delenv("B2B_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from b2b_ai.api.rate_limiter import _get_backend, _MemoryBackend
    backend = _get_backend()
    assert isinstance(backend, _MemoryBackend)
