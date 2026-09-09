# -*- coding: utf-8 -*-
"""Test de REQ-MIG-010 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-MIG).

Criterio de aceptación exacto:
  "La migración de pólizas debe ser idempotente: cada póliza origen
  migrada debe marcarse `migrada_a_id=<id_destino>`; reintentar la
  migración sobre las mismas pólizas debe producir 0 pólizas nuevas
  duplicadas en destino (verificable comparando el conteo de pólizas
  en destino antes/después del segundo intento)."

Nota honesta sobre `migrada_a_id`: este esquema (REQ-MIG-009,
`migrations/versions/0013_polizas_bloqueadas.py`) no crea una "póliza
destino" con id propio -- escribe líneas planas en
`lineas_poliza_migradas` identificadas por
`(tenant_id, poliza_origen_id)`, y ADR-3/REQ-MIG-011 prohíben mutar las
tablas de origen. Por eso este test verifica el efecto OBSERVABLE que
el criterio realmente pide -- 0 filas/pólizas nuevas duplicadas en un
reintento, y el resultado sigue reportando la póliza como migrada -- en
vez de una columna `migrada_a_id` sobre `asientos_contables` que el
diseño ya elegido (documentado en `migrador.py`) decidió no crear. Ver
`b2b_ai/features/migracion_catalogo/migrador.py::poliza_ya_migrada`.

Sin mocks: mismo patrón que
`tests/features/migracion_catalogo/test_migracion_atomica_por_poliza.py`
(REQ-MIG-009) -- crea y dropea una base de PostgreSQL de pruebas
dedicada, corre `alembic upgrade head` real, e invoca
`migrar_poliza()` con una conexión `psycopg` real, verificando el
estado de la base directamente por SQL.

Requiere un PG alcanzable vía B2B_DB_URL; si no hay uno disponible, se
skippea explícitamente (no se asume ni se mockea el resultado).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from decimal import Decimal

import pytest

from b2b_ai.features.migracion_catalogo.migrador import (
    LineaPolizaOrigen,
    PolizaOrigen,
    migrar_poliza,
    poliza_ya_migrada,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
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
    raise ValueError("DSN no soportado para crear base de test")


def _create_test_db():
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqmig010_{uuid.uuid4().hex[:10]}"
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
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def migration_db():
    dsn, dbname = _create_test_db()
    r = _run_alembic("upgrade", "head", dsn=dsn)
    assert r.returncode == 0, r.stderr[-2000:]
    yield dsn
    _drop_test_db(dbname)


@pytest.fixture
def conn(migration_db):
    import psycopg

    connection = psycopg.connect(migration_db)
    yield connection
    connection.close()


TENANT_ID = 1


def _sembrar_tenant_y_cuentas(conn, n_destino: int = 3):
    with conn.transaction():
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (TENANT_ID, "t"),
        )
        destinos = []
        for i in range(n_destino):
            cur = conn.execute(
                "INSERT INTO cuentas_contables (tenant_id, codigo, descripcion) "
                "VALUES (%s, %s, %s) RETURNING cuenta_id",
                (TENANT_ID, f"D-{i:03d}", f"Cuenta destino {i}"),
            )
            destinos.append(cur.fetchone()[0])
    return destinos


def _mapeo_aprobado(origen_id: str, destino_id) -> MapeoMigracionCuenta:
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_id,
        destino_cuenta_id=str(destino_id),
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
        aprobado_por="contador_lider",
        aprobado_en="2026-09-08T12:00:00+00:00",
    )


def _contar_lineas_destino(conn, poliza_id):
    cur = conn.execute(
        "SELECT COUNT(*) FROM lineas_poliza_migradas "
        "WHERE tenant_id=%s AND poliza_origen_id=%s",
        (TENANT_ID, poliza_id),
    )
    return cur.fetchone()[0]


def _contar_polizas_bloqueadas(conn, poliza_id):
    cur = conn.execute(
        "SELECT COUNT(*) FROM polizas_bloqueadas "
        "WHERE tenant_id=%s AND poliza_origen_id=%s",
        (TENANT_ID, poliza_id),
    )
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Caso central del criterio: reintentar una póliza YA migrada exitosamente
# produce 0 filas nuevas en destino, y el resultado sigue reportando
# "migrada" (nunca la trata como error ni la encola en bloqueadas).
# ---------------------------------------------------------------------------

def test_reintentar_poliza_ya_migrada_no_duplica_lineas_en_destino(conn):
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-IDEMP-1",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-A", debe=Decimal("500.00"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-B", debe=Decimal("0"), haber=Decimal("500.00")),
        ),
    )
    mapeos = {
        "ORIG-A": _mapeo_aprobado("ORIG-A", destinos[0]),
        "ORIG-B": _mapeo_aprobado("ORIG-B", destinos[1]),
    }

    primero = migrar_poliza(conn, poliza, mapeos)
    assert primero.migrada is True
    assert primero.lineas_migradas == 2
    assert primero.ya_migrada is False
    conteo_tras_primero = _contar_lineas_destino(conn, "POL-IDEMP-1")
    assert conteo_tras_primero == 2

    # Segundo intento: MISMA póliza, MISMOS mapeos -- simula un reintento
    # real (p.ej. un job que se re-ejecuta tras un timeout de red).
    segundo = migrar_poliza(conn, poliza, mapeos)

    assert segundo.migrada is True, (
        "un reintento sobre una póliza ya migrada exitosamente debe "
        "seguir reportándose como migrada, nunca como bloqueada/fallida"
    )
    assert segundo.bloqueada is False
    assert segundo.ya_migrada is True
    assert segundo.lineas_migradas == 2, (
        "el resultado debe reflejar las 2 líneas YA existentes en "
        "destino, no volver a contarlas como si se hubieran insertado"
    )

    # El criterio en cifras concretas: 0 filas nuevas duplicadas.
    conteo_tras_segundo = _contar_lineas_destino(conn, "POL-IDEMP-1")
    assert conteo_tras_segundo == conteo_tras_primero == 2, (
        f"se esperaban 0 filas nuevas en el reintento; antes="
        f"{conteo_tras_primero}, después={conteo_tras_segundo}"
    )

    # El reintento tampoco debe encolar la póliza como bloqueada -- ya
    # estaba resuelta, no es un caso de error.
    assert _contar_polizas_bloqueadas(conn, "POL-IDEMP-1") == 0


def test_reintentar_tres_veces_sigue_dando_0_filas_nuevas_cada_vez(conn):
    """Refuerza el criterio con más de un reintento: no es un caso
    especial del "segundo" intento, es estable para cualquier número de
    reintentos posteriores."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-IDEMP-2",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-X", debe=Decimal("10.00"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-Y", debe=Decimal("0"), haber=Decimal("10.00")),
        ),
    )
    mapeos = {
        "ORIG-X": _mapeo_aprobado("ORIG-X", destinos[0]),
        "ORIG-Y": _mapeo_aprobado("ORIG-Y", destinos[1]),
    }

    resultados = [migrar_poliza(conn, poliza, mapeos) for _ in range(4)]

    assert resultados[0].ya_migrada is False
    assert all(r.ya_migrada is True for r in resultados[1:])
    assert all(r.migrada is True and r.bloqueada is False for r in resultados)
    assert all(r.lineas_migradas == 2 for r in resultados)
    assert _contar_lineas_destino(conn, "POL-IDEMP-2") == 2


def test_poliza_ya_migrada_helper_es_de_solo_lectura(conn):
    """`poliza_ya_migrada()` debe poder llamarse repetidamente sin
    alterar el conteo real en destino (es una consulta, no un side
    effect)."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-IDEMP-3",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-P", debe=Decimal("1"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-Q", debe=Decimal("0"), haber=Decimal("1")),
        ),
    )
    mapeos = {
        "ORIG-P": _mapeo_aprobado("ORIG-P", destinos[0]),
        "ORIG-Q": _mapeo_aprobado("ORIG-Q", destinos[1]),
    }

    assert poliza_ya_migrada(conn, TENANT_ID, "POL-IDEMP-3") == 0
    migrar_poliza(conn, poliza, mapeos)
    assert poliza_ya_migrada(conn, TENANT_ID, "POL-IDEMP-3") == 2
    # Llamar 3 veces más no debe insertar ni borrar nada.
    for _ in range(3):
        poliza_ya_migrada(conn, TENANT_ID, "POL-IDEMP-3")
    assert poliza_ya_migrada(conn, TENANT_ID, "POL-IDEMP-3") == 2
    assert _contar_lineas_destino(conn, "POL-IDEMP-3") == 2


def test_poliza_nunca_migrada_no_se_confunde_con_idempotente(conn):
    """Una póliza que nunca se migró (0 líneas en destino) debe seguir
    tomando el camino normal de `migrar_poliza()` -- `ya_migrada=False`
    -- y no debe confundirse con el caso idempotente."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-NUEVA",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-N1", debe=Decimal("5"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-N2", debe=Decimal("0"), haber=Decimal("5")),
        ),
    )
    mapeos = {
        "ORIG-N1": _mapeo_aprobado("ORIG-N1", destinos[0]),
        "ORIG-N2": _mapeo_aprobado("ORIG-N2", destinos[1]),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)
    assert resultado.ya_migrada is False
    assert resultado.migrada is True
    assert resultado.lineas_migradas == 2
