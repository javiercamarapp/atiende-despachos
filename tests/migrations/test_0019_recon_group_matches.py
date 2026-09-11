# -*- coding: utf-8 -*-
"""Test de migración 0019_recon_group_matches (REQ-CONC-013).

Ejecuta `alembic upgrade head` contra una base de PostgreSQL de pruebas
dedicada (creada y dropeada por test, mismo patrón que
tests/migrations/test_0012_cuenta_id_fk.py y tests/test_pg_migrations.py)
y confirma, sin mocks, sobre el catálogo real de Postgres
(`information_schema`) que la tabla `reconciliation_group_matches` existe
con las columnas del criterio de aceptación: `group_id`, `transaction_id`,
`tenant_id`, `naturaleza`, `confidence`, `estado`, `score`, `aprobado_por`,
`aprobado_en`.

También verifica: se puede insertar una fila por cada `estado` real que
produce `_pass_group()` (confirmado / sugerido / sin_conciliar), el
downgrade revierte todo sin dejar objetos huérfanos, y el ciclo
upgrade->downgrade->upgrade es reproducible.

Requiere un PG alcanzable vía B2B_DB_URL; si no hay uno disponible, se
skippea (no se asume ni se mockea el resultado de la migración).
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
    dbname = f"b2b_pg_reqconc013_{uuid.uuid4().hex[:10]}"
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


def _table_exists(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return cur.fetchone() is not None


CRITERIO_COLUMNAS = {
    "group_id", "transaction_id", "tenant_id", "naturaleza",
    "confidence", "estado", "score", "aprobado_por", "aprobado_en",
}


def test_reconciliation_group_matches_tiene_las_columnas_del_criterio(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        assert _table_exists(conn, "reconciliation_group_matches")
        cols = _columns(conn, "reconciliation_group_matches")
        faltantes = CRITERIO_COLUMNAS - set(cols.keys())
        assert not faltantes, (
            f"reconciliation_group_matches no tiene las columnas del "
            f"criterio REQ-CONC-013: {faltantes}")
        # group_id/transaction_id/naturaleza/estado son obligatorios en toda
        # fila real que produce _pass_group (siempre sabe a qué grupo,
        # movimiento, dirección y estado pertenece una fila).
        for col in ("group_id", "transaction_id", "naturaleza", "estado"):
            assert cols[col]["is_nullable"] == "NO", (
                f"{col} debe ser NOT NULL")
        # score es NULL-able: ambigüedad real (2+ candidatos, ADR-2) y
        # sin_conciliar no tienen un score individual que guardar.
        assert cols["score"]["is_nullable"] == "YES"
        assert cols["aprobado_por"]["is_nullable"] == "YES"
        assert cols["aprobado_en"]["is_nullable"] == "YES"
    finally:
        conn.close()


def test_reconciliation_group_matches_acepta_los_3_estados_reales(migration_db):
    """Inserta una fila por cada `estado` que produce _pass_group() hoy:
    confirmado (auto-confirmado), sugerido (ambigüedad o score bajo,
    ADR-2) y sin_conciliar (ningún candidato en la banda, ADR-1,
    REQ-CONC-014)."""
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reconciliation_group_matches "
            "(tenant_id, group_id, transaction_id, invoice_ref, naturaleza, "
            " confidence, estado, score, aprobado_por, aprobado_en) VALUES "
            "(1, 'grp_tx1', 'tx1', 'INV-1', 'abono', 'alta', 'confirmado', "
            " 95.0, NULL, NULL), "
            "(1, 'grp_tx2', 'tx2', 'INV-2', 'abono', NULL, 'sugerido', "
            " NULL, NULL, NULL), "
            "(1, 'grp_tx3', 'tx3', NULL, 'cargo', NULL, 'sin_conciliar', "
            " NULL, NULL, NULL)"
        )
        conn.commit()
        cur.execute(
            "SELECT estado, score, invoice_ref FROM "
            "reconciliation_group_matches ORDER BY transaction_id")
        rows = cur.fetchall()
        assert [r[0] for r in rows] == [
            "confirmado", "sugerido", "sin_conciliar"]
        assert rows[0][1] == 95.0
        assert rows[1][2] is None or rows[1][2] == "INV-2"
        assert rows[2][2] is None, (
            "sin_conciliar no tiene un grupo de facturas que registrar")
    finally:
        conn.close()


def test_downgrade_reconciliation_group_matches_no_deja_huerfanos(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]
    r = _run_alembic("downgrade", "0018_mapeos_migracion_catalogo",
                     dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        assert not _table_exists(conn, "reconciliation_group_matches")
        cur = conn.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE "
            "'idx_recon_group_matches%%'")
        assert cur.fetchall() == [], "quedaron índices huérfanos"
    finally:
        conn.close()

    # Ciclo reproducible: upgrade -> downgrade -> upgrade sin error.
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]
    conn = psycopg.connect(migration_db)
    try:
        assert _table_exists(conn, "reconciliation_group_matches")
    finally:
        conn.close()
