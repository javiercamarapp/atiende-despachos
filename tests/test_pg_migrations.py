# -*- coding: utf-8 -*-
"""Tests de migración Alembic (up/down) contra PostgreSQL.

Requieren un PG alcanzable vía B2B_DB_URL. Cada test crea una base de test
dedicada (b2b_pg_mig_test) para NO pisar el esquema público que usan otros
tests ni datos reales.
"""
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


pytestmark = pytest.mark.skipif(not _pg_available(),
                                reason="B2B_DB_URL PostgreSQL no disponible")


def _split_dsn(dsn):
    """Separa el DSN de conexión de la base de la que apunta."""
    import urllib.parse
    # postgresql://user:pass@host:port/db -> (conn_part, db)
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db():
    """Crea una base de test única y devuelve (dsn, dbname)."""
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_mig_{uuid.uuid4().hex[:10]}"
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


def _run_alembic(*args, dsn):
    env = dict(os.environ)
    env["B2B_DB_URL"] = dsn
    env["B2B_SEED_SKIP"] = "1"  # el test valida el esquema, no el seed
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.fixture
def migration_db():
    """DSN a una base de test vacía (se crea y se dropea por test)."""
    dsn, dbname = _create_test_db()
    yield dsn
    _drop_test_db(dbname)


def test_migration_up_to_head(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1200:]
    import psycopg
    conn = psycopg.connect(migration_db)
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('alembic_version')")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    assert "tenants" in tables
    assert "invoices" in tables
    assert "portal_sessions" in tables


def test_migration_down_up(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-800:]
    r2 = _run_alembic("downgrade", "base", dsn=migration_db)
    assert r2.returncode == 0, r2.stderr[-800:]
    import psycopg
    conn = psycopg.connect(migration_db)
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('alembic_version')")
    leftover = [r[0] for r in cur.fetchall()]
    conn.close()
    assert leftover == [], f"quedaron tablas tras downgrade: {leftover}"
    # re-upgrade para dejar el esquema usable
    r3 = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r3.returncode == 0, r3.stderr[-800:]
