# -*- coding: utf-8 -*-
"""Test de migración 0020_canal_cobro_invoices (REQ-CONC-016).

Mismo patrón que tests/migrations/test_0019_recon_group_matches.py:
crea una base de PostgreSQL de pruebas dedicada, corre `alembic upgrade
head` real y confirma sobre `information_schema` que `invoices` y
`outstanding_invoices` ganaron `canal_cobro`/`id_terminal`, ambas
NULLABLE (dato opcional: no debe romper ni reinterpretar filas ya
cargadas antes de esta migración). También confirma que el downgrade
revierte las 4 columnas sin dejar objetos huérfanos.

Requiere un PG alcanzable vía B2B_DB_URL; si no hay uno disponible, se
skippea.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db():
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqconc016_{uuid.uuid4().hex[:10]}"
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
    env["B2B_SEED_SKIP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.fixture
def migration_db():
    dsn, dbname = _create_test_db()
    yield dsn
    _drop_test_db(dbname)


def _columns(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return {row[0]: {"data_type": row[1], "is_nullable": row[2]}
            for row in cur.fetchall()}


@pytest.mark.parametrize("table", ["invoices", "outstanding_invoices"])
def test_tabla_gana_canal_cobro_e_id_terminal_nullable(migration_db, table):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cols = _columns(conn, table)
        for col in ("canal_cobro", "id_terminal"):
            assert col in cols, f"{table} no tiene {col}"
            assert cols[col]["is_nullable"] == "YES", (
                f"{table}.{col} debe ser NULLABLE (dato opcional, no debe "
                f"romper filas ya cargadas antes de esta migración)")
            assert cols[col]["data_type"] == "text"
    finally:
        conn.close()


def test_filas_preexistentes_no_se_rompen_con_canal_cobro_nulo(migration_db):
    """Una factura cargada antes de esta migración (sin canal_cobro/
    id_terminal) debe seguir leyéndose sin error, con ambos campos en
    NULL -- nunca inventados."""
    r = _run_alembic("upgrade", "0018_mapeos_migracion_catalogo",
                     dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tenants (name) VALUES ('Tenant de prueba') "
            "RETURNING id")
        tenant_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO invoices (tenant_id, archivo, fecha, total) "
            "VALUES (%s, 'f1.xml', '2026-07-01', '1000.00') RETURNING id",
            (tenant_id,))
        inv_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT canal_cobro, id_terminal FROM invoices WHERE id=%s",
            (inv_id,))
        row = cur.fetchone()
        assert row == (None, None)
    finally:
        conn.close()


def test_downgrade_quita_las_4_columnas_sin_huerfanos(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]
    r = _run_alembic("downgrade", "0019_recon_group_matches",
                     dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        for table in ("invoices", "outstanding_invoices"):
            cols = _columns(conn, table)
            assert "canal_cobro" not in cols
            assert "id_terminal" not in cols
        cur = conn.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname IN "
            "('idx_invoices_canal_cobro', 'idx_outstanding_canal_cobro')")
        assert cur.fetchall() == [], "quedaron índices huérfanos"
    finally:
        conn.close()
