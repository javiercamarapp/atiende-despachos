# -*- coding: utf-8 -*-
"""Test de migración 0012_cuenta_id_fk (REQ-MIG-001).

Ejecuta `alembic upgrade head` contra una base de PostgreSQL de pruebas
dedicada (creada y dropeada por test, igual que tests/test_pg_migrations.py
y tests/migrations/test_0010_devolucion_iva_persistencia.py) y confirma,
sin mocks, sobre el catálogo real de Postgres (`information_schema`,
`pg_indexes`, `pg_constraint`) que:

  - `cuentas_contables` tiene una columna `cuenta_id` UUID NOT NULL y esa
    columna es el PRIMARY KEY de la tabla.
  - `cuentas_contables.id` (el bigint identity original) sigue existiendo,
    NOT NULL, y con una UNIQUE constraint propia (para que
    `balanzas_mensuales.cuenta_id` -> `cuentas_contables(id)` no se
    rompa).
  - `asientos_contables` tiene una columna `cuenta_id` UUID con una FK
    ACTIVA hacia `cuentas_contables(cuenta_id)` — verificable a nivel de
    esquema (equivalente a inspeccionar `\\d asientos_contables`) y a
    nivel de comportamiento (INSERT con un UUID inexistente debe fallar
    con ForeignKeyViolation).
  - `cuenta_debito`/`cuenta_credito` en `asientos_contables` NO se tocan
    (siguen NOT NULL TEXT): esta migración es aditiva, no reclasifica
    nada (ADR-3 del blueprint).
  - El downgrade revierte todo sin dejar objetos huérfanos y el
    up->down->up es reproducible.

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
    dbname = f"b2b_pg_reqmig001_{uuid.uuid4().hex[:10]}"
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


def _pk_columns(conn, table):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        """,
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _foreign_keys(conn, table):
    """Lista (constraint_name, columna_local, tabla_destino, columna_destino)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            con.conname,
            att_local.attname AS local_col,
            cl_foreign.relname AS foreign_table,
            att_foreign.attname AS foreign_col
        FROM pg_constraint con
        JOIN pg_class cl_local ON cl_local.oid = con.conrelid
        JOIN pg_class cl_foreign ON cl_foreign.oid = con.confrelid
        JOIN unnest(con.conkey) WITH ORDINALITY AS lk(attnum, ord) ON true
        JOIN unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = lk.ord
        JOIN pg_attribute att_local
            ON att_local.attrelid = con.conrelid AND att_local.attnum = lk.attnum
        JOIN pg_attribute att_foreign
            ON att_foreign.attrelid = con.confrelid AND att_foreign.attnum = fk.attnum
        WHERE con.contype = 'f' AND cl_local.relname = %s
        """,
        (table,),
    )
    return [
        {"name": r[0], "local_col": r[1], "foreign_table": r[2], "foreign_col": r[3]}
        for r in cur.fetchall()
    ]


def _unique_constraint_columns(conn, table, constraint_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.attname
        FROM pg_constraint con
        JOIN pg_class cl ON cl.oid = con.conrelid
        JOIN unnest(con.conkey) AS k(attnum) ON true
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        WHERE con.conname = %s AND cl.relname = %s
        """,
        (constraint_name, table),
    )
    return {row[0] for row in cur.fetchall()}


def test_cuentas_contables_tiene_cuenta_id_uuid_como_pk(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cols = _columns(conn, "cuentas_contables")
        assert "cuenta_id" in cols, "falta cuenta_id en cuentas_contables"
        assert cols["cuenta_id"]["data_type"] == "uuid", (
            f"cuenta_id debe ser UUID, es {cols['cuenta_id']['data_type']!r}")
        assert cols["cuenta_id"]["is_nullable"] == "NO", "cuenta_id debe ser NOT NULL"

        pk_cols = _pk_columns(conn, "cuentas_contables")
        assert pk_cols == {"cuenta_id"}, (
            f"cuenta_id debe ser el PRIMARY KEY de cuentas_contables, "
            f"PK actual: {pk_cols}")

        # `id` (bigint identity original) se conserva: NOT NULL + UNIQUE,
        # para no romper balanzas_mensuales ni el código existente que usa
        # ids enteros (b2b_ai/db/models.py, líneas 909-932).
        assert "id" in cols, "no debe eliminarse la columna id original"
        assert cols["id"]["is_nullable"] == "NO"
        assert cols["id"]["data_type"] == "bigint"
        unique_cols = _unique_constraint_columns(
            conn, "cuentas_contables", "uq_cuentas_contables_id")
        assert unique_cols == {"id"}, (
            "falta la UNIQUE constraint sobre cuentas_contables.id")
    finally:
        conn.close()


def test_asientos_contables_tiene_fk_activa_a_cuenta_id(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cols = _columns(conn, "asientos_contables")
        assert "cuenta_id" in cols, "falta cuenta_id en asientos_contables"
        assert cols["cuenta_id"]["data_type"] == "uuid"

        # ADR-3: esta migración es solo esquema, no reclasifica datos —
        # cuenta_debito/cuenta_credito TEXT deben seguir intactas.
        assert cols["cuenta_debito"]["data_type"] == "text"
        assert cols["cuenta_debito"]["is_nullable"] == "NO"
        assert cols["cuenta_credito"]["data_type"] == "text"
        assert cols["cuenta_credito"]["is_nullable"] == "NO"

        fks = _foreign_keys(conn, "asientos_contables")
        cuenta_fks = [fk for fk in fks if fk["local_col"] == "cuenta_id"]
        assert len(cuenta_fks) == 1, (
            f"debe existir exactamente una FK activa sobre "
            f"asientos_contables.cuenta_id, encontradas: {fks}")
        fk = cuenta_fks[0]
        assert fk["foreign_table"] == "cuentas_contables"
        assert fk["foreign_col"] == "cuenta_id", (
            "la FK debe apuntar a cuentas_contables.cuenta_id (el nuevo PK "
            f"UUID), apunta a {fk['foreign_col']!r}")
    finally:
        conn.close()


def test_fk_asientos_cuenta_id_rechaza_uuid_inexistente(migration_db):
    """La FK debe estar realmente activa, no solo declarada: un INSERT con
    un cuenta_id que no existe en cuentas_contables debe fallar."""
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenants (id, name) VALUES (1, 't') "
                    "ON CONFLICT DO NOTHING")
        conn.commit()

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO asientos_contables "
                "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto, cuenta_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (1, "2026-01-01", "102-001", "401-001", "100.00",
                 "11111111-1111-1111-1111-111111111111"),
            )
            conn.commit()
    finally:
        conn.rollback()
        conn.close()


def test_fk_asientos_cuenta_id_acepta_cuenta_real(migration_db):
    """Camino feliz: un cuenta_id que sí existe en el catálogo se inserta
    sin problema y el JOIN entre ambas tablas funciona."""
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenants (id, name) VALUES (1, 't') "
                    "ON CONFLICT DO NOTHING")
        cur.execute(
            "INSERT INTO cuentas_contables (tenant_id, codigo, descripcion) "
            "VALUES (%s, %s, %s) RETURNING cuenta_id",
            (1, "102-001", "Bancos"),
        )
        cuenta_uuid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO asientos_contables "
            "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto, cuenta_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (1, "2026-01-01", "102-001", "401-001", "100.00", cuenta_uuid),
        )
        asiento_id = cur.fetchone()[0]
        conn.commit()

        cur.execute(
            "SELECT c.descripcion FROM asientos_contables a "
            "JOIN cuentas_contables c ON c.cuenta_id = a.cuenta_id "
            "WHERE a.id = %s",
            (asiento_id,),
        )
        assert cur.fetchone() == ("Bancos",)
    finally:
        conn.rollback()
        conn.close()


def test_balanzas_mensuales_conserva_su_fk_a_cuentas_contables_id(migration_db):
    """La FK preexistente balanzas_mensuales.cuenta_id -> cuentas_contables.id
    (bigint) no debe romperse al degradar `id` de PK a UNIQUE."""
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-2000:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        fks = _foreign_keys(conn, "balanzas_mensuales")
        cuenta_fks = [fk for fk in fks if fk["local_col"] == "cuenta_id"]
        assert len(cuenta_fks) == 1
        assert cuenta_fks[0]["foreign_table"] == "cuentas_contables"
        assert cuenta_fks[0]["foreign_col"] == "id"

        cur = conn.cursor()
        cur.execute("INSERT INTO tenants (id, name) VALUES (1, 't') "
                    "ON CONFLICT DO NOTHING")
        cur.execute(
            "INSERT INTO cuentas_contables (tenant_id, codigo, descripcion) "
            "VALUES (%s, %s, %s) RETURNING id",
            (1, "102-001", "Bancos"),
        )
        cuenta_id_bigint = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO balanzas_mensuales (tenant_id, periodo, cuenta_id) "
            "VALUES (%s, %s, %s)",
            (1, "2026-01", cuenta_id_bigint),
        )
        conn.commit()
    finally:
        conn.rollback()
        conn.close()


def test_migracion_down_up_no_deja_objetos_huerfanos(migration_db):
    r = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r.returncode == 0, r.stderr[-1500:]

    r2 = _run_alembic("downgrade", "0011_devolucion_iva_seguimiento",
                       dsn=migration_db)
    assert r2.returncode == 0, r2.stderr[-1500:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cols = _columns(conn, "cuentas_contables")
        assert "cuenta_id" not in cols, (
            "downgrade debió eliminar cuentas_contables.cuenta_id")
        pk_cols = _pk_columns(conn, "cuentas_contables")
        assert pk_cols == {"id"}, (
            f"downgrade debió restaurar id como PK, PK actual: {pk_cols}")

        cols_asientos = _columns(conn, "asientos_contables")
        assert "cuenta_id" not in cols_asientos, (
            "downgrade debió eliminar asientos_contables.cuenta_id")

        fks = _foreign_keys(conn, "balanzas_mensuales")
        cuenta_fks = [fk for fk in fks if fk["local_col"] == "cuenta_id"]
        assert len(cuenta_fks) == 1
        assert cuenta_fks[0]["foreign_col"] == "id", (
            "downgrade debió restaurar balanzas_mensuales -> cuentas_contables(id)")
    finally:
        conn.close()

    # re-upgrade: debe ser reproducible y dejar el mismo estado que antes.
    r3 = _run_alembic("upgrade", "head", dsn=migration_db)
    assert r3.returncode == 0, r3.stderr[-1500:]

    conn = psycopg.connect(migration_db)
    try:
        pk_cols = _pk_columns(conn, "cuentas_contables")
        assert pk_cols == {"cuenta_id"}
        fks = _foreign_keys(conn, "asientos_contables")
        cuenta_fks = [fk for fk in fks if fk["local_col"] == "cuenta_id"]
        assert len(cuenta_fks) == 1
        assert cuenta_fks[0]["foreign_col"] == "cuenta_id"
    finally:
        conn.close()
