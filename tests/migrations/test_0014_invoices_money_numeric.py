# -*- coding: utf-8 -*-
"""Test de migración 0014_invoices_money_numeric.

Ejecuta `alembic upgrade`/`downgrade` reales contra una base de PostgreSQL
de pruebas dedicada (creada y dropeada por test, igual que
tests/test_pg_migrations.py y tests/migrations/test_0012_cuenta_id_fk.py) y
confirma, sin mocks, que:

  - Con datos existentes 100% numéricos (incluyendo "" y NULL, que deben
    tratarse como NULL), la migración convierte subtotal/iva/total a
    NUMERIC(18,2) y preserva los valores.
  - Con AL MENOS UN valor no numérico ("N/A", "1,160.00" con separador de
    miles) en cualquiera de las tres columnas, la migración ABORTA
    (returncode != 0) y deja el esquema intacto (columnas siguen TEXT,
    alembic_version sigue en 0013) -- nunca migra a ciegas ni descarta el
    dato ofensor en silencio.
  - El downgrade revierte a TEXT sin perder los valores (ahora como texto)
    y el ciclo up->down->up es reproducible.

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
    dbname = f"b2b_pg_reqmoney001_{uuid.uuid4().hex[:10]}"
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


def _column_type(conn, table, column):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _seed_tenant_and_invoices(dsn, rows):
    """Inserta un tenant y filas de `invoices` con (subtotal, iva, total)
    crudos (strings o None) tal como llegarían de datos preexistentes."""
    import psycopg
    conn = psycopg.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tenants (id, name) VALUES (1, 'Test') "
            "ON CONFLICT (id) DO NOTHING")
        for i, (subtotal, iva, total) in enumerate(rows):
            cur.execute(
                "INSERT INTO invoices (tenant_id, archivo, subtotal, iva, total) "
                "VALUES (1, %s, %s, %s, %s)",
                (f"f{i}.xml", subtotal, iva, total),
            )
        conn.commit()
    finally:
        conn.close()


def test_upgrade_convierte_valores_numericos_validos(migration_db):
    r0 = _run_alembic("upgrade", "0013_polizas_bloqueadas", dsn=migration_db)
    assert r0.returncode == 0, r0.stderr[-1200:]

    _seed_tenant_and_invoices(migration_db, [
        ("100.00", "16.00", "116.00"),   # típico
        ("", "", ""),                     # legado: "" en vez de NULL
        (None, None, None),               # ya era NULL
        ("0", "0", "0"),                  # cero explícito
        ("-50.00", "0", "-50.00"),        # nota de crédito (negativo)
    ])

    r1 = _run_alembic("upgrade", "0014_invoices_money_numeric", dsn=migration_db)
    assert r1.returncode == 0, r1.stderr[-1500:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        for col in ("subtotal", "iva", "total"):
            assert _column_type(conn, "invoices", col) == "numeric", (
                f"{col} no quedó como numeric tras la migración")
        cur = conn.cursor()
        cur.execute(
            "SELECT archivo, subtotal, iva, total FROM invoices ORDER BY id")
        by_archivo = {row[0]: row[1:] for row in cur.fetchall()}
    finally:
        conn.close()

    from decimal import Decimal
    assert by_archivo["f0.xml"] == (Decimal("100.00"), Decimal("16.00"),
                                    Decimal("116.00"))
    # "" preexistente se convierte en NULL real, no en 0 ni se descarta la fila
    assert by_archivo["f1.xml"] == (None, None, None)
    assert by_archivo["f2.xml"] == (None, None, None)
    assert by_archivo["f3.xml"] == (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    assert by_archivo["f4.xml"] == (Decimal("-50.00"), Decimal("0.00"),
                                    Decimal("-50.00"))


def test_upgrade_aborta_si_hay_valores_no_numericos(migration_db):
    r0 = _run_alembic("upgrade", "0013_polizas_bloqueadas", dsn=migration_db)
    assert r0.returncode == 0, r0.stderr[-1200:]

    _seed_tenant_and_invoices(migration_db, [
        ("100.00", "16.00", "116.00"),    # válida
        ("N/A", "16.00", "1,160.00"),     # basura: texto libre + separador de miles
    ])

    r1 = _run_alembic("upgrade", "0014_invoices_money_numeric", dsn=migration_db)
    assert r1.returncode != 0, "la migración debía abortar con datos no numéricos"
    combined = (r1.stdout + r1.stderr)
    assert "N/A" in combined
    assert "1,160.00" in combined
    assert "ABORTADO" in combined

    # El esquema NO debe haber cambiado: sigue en 0013, columnas siguen TEXT.
    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] == "0013_polizas_bloqueadas"
        for col in ("subtotal", "iva", "total"):
            assert _column_type(conn, "invoices", col) == "text"
        # La fila ofensora sigue intacta -- no se descartó ni se "arregló" sola.
        cur.execute("SELECT subtotal, total FROM invoices WHERE archivo='f1.xml'")
        assert cur.fetchone() == ("N/A", "1,160.00")
    finally:
        conn.close()


def test_downgrade_revierte_a_text_sin_perder_datos(migration_db):
    r0 = _run_alembic("upgrade", "0013_polizas_bloqueadas", dsn=migration_db)
    assert r0.returncode == 0, r0.stderr[-1200:]
    _seed_tenant_and_invoices(migration_db, [("100.00", "16.00", "116.00")])

    r1 = _run_alembic("upgrade", "0014_invoices_money_numeric", dsn=migration_db)
    assert r1.returncode == 0, r1.stderr[-1200:]

    r2 = _run_alembic("downgrade", "0013_polizas_bloqueadas", dsn=migration_db)
    assert r2.returncode == 0, r2.stderr[-1200:]

    import psycopg
    conn = psycopg.connect(migration_db)
    try:
        for col in ("subtotal", "iva", "total"):
            assert _column_type(conn, "invoices", col) == "text"
        cur = conn.cursor()
        cur.execute("SELECT subtotal, iva, total FROM invoices")
        assert cur.fetchone() == ("100.00", "16.00", "116.00")
    finally:
        conn.close()

    # re-upgrade para confirmar que el ciclo es reproducible
    r3 = _run_alembic("upgrade", "0014_invoices_money_numeric", dsn=migration_db)
    assert r3.returncode == 0, r3.stderr[-1200:]
