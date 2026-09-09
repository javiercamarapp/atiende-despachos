# -*- coding: utf-8 -*-
"""Fixtures compartidas para los tests cross-database de
`b2b_ai/features/migracion_catalogo/cross_db.py`.

Mismo patrón, sin mocks, que ya usan
`test_migracion_atomica_por_poliza.py` (REQ-MIG-009) y
`test_migracion_idempotente.py` (REQ-MIG-010): crea y dropea bases de
PostgreSQL de pruebas REALES (vía `CREATE DATABASE`/`DROP DATABASE`
contra el servidor de `B2B_DB_URL`) y corre `alembic upgrade head`
real contra cada una -- nunca una base "de mentira" ni un esquema
hardcodeado a mano.

La diferencia frente a esos dos archivos: el caso cross-database
necesita DOS bases físicamente distintas simultáneas (origen y
destino), no una. `dos_bases_migradas` crea y migra ambas contra el
MISMO servidor de Postgres que ya usa el resto de la suite (el único
Postgres disponible en este entorno de pruebas) pero como DOS bases de
datos genuinamente distintas -- Postgres nunca permite una consulta
cruzada entre bases con una sola conexión, así que dos conexiones
`psycopg` distintas (una por base) es una restricción real, no
simulada, exactamente la misma que tendría el caso real de dos
servidores Postgres distintos.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
PG_DSN = os.environ.get("B2B_DB_URL", "")


def _pg_available() -> bool:
    if not PG_DSN:
        return False
    try:
        import psycopg

        psycopg.connect(PG_DSN, connect_timeout=3).close()
        return True
    except Exception:
        return False


def _split_dsn(dsn: str):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db(prefijo: str):
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_{prefijo}_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()
    return f"{server_dsn}/{dbname}", dbname


def _drop_test_db(dbname: str) -> None:
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


def _run_alembic(*args, dsn: str):
    env = dict(os.environ)
    env["B2B_DB_URL"] = dsn
    env["B2B_SEED_SKIP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def bd_temporal_factory():
    """Fábrica de bases de datos de prueba temporales, cada una
    migrada a `head` con Alembic real. Devuelve una función
    `crear(prefijo) -> dsn`; dropea TODAS las bases creadas al final
    del test, incluso si el test falla a medias."""
    creadas = []

    def crear(prefijo: str) -> str:
        dsn, dbname = _create_test_db(prefijo)
        r = _run_alembic("upgrade", "head", dsn=dsn)
        assert r.returncode == 0, r.stderr[-3000:]
        creadas.append(dbname)
        return dsn

    yield crear

    for dbname in creadas:
        _drop_test_db(dbname)


@pytest.fixture
def dos_bases_migradas(bd_temporal_factory):
    """Dos bases de datos Postgres REALES y físicamente distintas
    (nombres de base distintos, cada una con su propio esquema
    recién migrado a `head`), simulando el caso real: origen
    (2024-2026) y destino (2020-2023). Devuelve `(origen_dsn,
    destino_dsn)`."""
    origen_dsn = bd_temporal_factory("crossdb_origen")
    destino_dsn = bd_temporal_factory("crossdb_destino")
    return origen_dsn, destino_dsn


pytestmark_pg = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)
