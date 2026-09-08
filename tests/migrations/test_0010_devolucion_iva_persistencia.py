# -*- coding: utf-8 -*-
"""Test de migración 0010_devolucion_iva_persistencia (REQ-IVA-005).

Ejecuta `alembic upgrade head` contra una base de PostgreSQL de pruebas
dedicada (creada y dropeada por test, igual que tests/test_pg_migrations.py)
y confirma vía `information_schema.columns`/`pg_indexes` que las 4 tablas
requeridas existen, todas con `tenant_id NOT NULL` y un índice compuesto
(tenant_id, periodo).

Requiere un PG alcanzable vía B2B_DB_URL; si no hay uno disponible, se
skippea (no se asume ni se mockea el resultado de la migración).
"""
import os
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PG_DSN = os.environ.get("B2B_DB_URL", "")

TABLAS_REQ_IVA_005 = [
    "devolucion_iva_solicitudes",
    "devolucion_iva_papeles_trabajo",
    "diot_entries",
    "depositos_bancarios_clasificados",
]


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
    import urllib.parse  # noqa: F401  (mantenido por paridad con test_pg_migrations.py)
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db():
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqiva005_{uuid.uuid4().hex[:10]}"
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
    dsn, dbname = _create_test_db()
    yield dsn
    _drop_test_db(dbname)


def _columns(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _indexdefs(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
                "AND tablename=%s", (table,))
    return [row[0] for row in cur.fetchall()]


def test_migracion_crea_las_4_tablas_con_tenant_id_not_null(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1500:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename NOT IN ('alembic_version')"
        )
        tablas_existentes = {row[0] for row in cur.fetchall()}

        for tabla in TABLAS_REQ_IVA_005:
            assert tabla in tablas_existentes, (
                f"falta la tabla {tabla!r} tras la migración")

            cols = _columns(conn, tabla)
            assert "tenant_id" in cols, f"{tabla}: falta columna tenant_id"
            assert cols["tenant_id"] == "NO", (
                f"{tabla}.tenant_id debe ser NOT NULL, "
                f"information_schema dice is_nullable={cols['tenant_id']!r}")
            assert "periodo" in cols, f"{tabla}: falta columna periodo"
    finally:
        conn.close()


def test_migracion_crea_indice_compuesto_tenant_id_periodo(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1500:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        for tabla in TABLAS_REQ_IVA_005:
            defs = _indexdefs(conn, tabla)
            tiene_compuesto = any(
                "tenant_id" in d and "periodo" in d for d in defs
            )
            assert tiene_compuesto, (
                f"{tabla}: no se encontró un índice que cubra "
                f"(tenant_id, periodo); índices existentes: {defs}")
    finally:
        conn.close()


def test_no_se_puede_insertar_sin_tenant_id(migration_db):
    """tenant_id NOT NULL debe rechazar el INSERT a nivel de esquema, no solo
    de código — blindaje de aislamiento multi-tenant también en la BD."""
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1500:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        with pytest.raises(psycopg.errors.NotNullViolation):
            cur.execute(
                "INSERT INTO devolucion_iva_solicitudes "
                "(id, periodo, created_at) VALUES (%s, %s, %s)",
                ("sol-sin-tenant", "2026-01", "2026-01-01T00:00:00"),
            )
            conn.commit()
    finally:
        conn.rollback()
        conn.close()


def test_migracion_down_up_no_deja_tablas_huerfanas(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1000:]
    r2 = _run_alembic("downgrade", "0009_document_management", dsn=migration_db)
    assert r2.returncode == 0, r2.stderr[-1000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tablas = {row[0] for row in cur.fetchall()}
        for tabla in TABLAS_REQ_IVA_005:
            assert tabla not in tablas, (
                f"{tabla} debería desaparecer tras el downgrade a 0009")
    finally:
        conn.close()

    # re-upgrade para dejar el esquema usable si algo más reutiliza el fixture
    r3 = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r3.returncode == 0, r3.stderr[-1000:]
