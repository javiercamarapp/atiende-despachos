# -*- coding: utf-8 -*-
"""Test de REQ-MIG-009 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-MIG).

Criterio de aceptación exacto:
  "El motor de migración de pólizas debe ser transaccional por póliza
  completa: si alguna línea de una póliza no tiene mapeo aprobado, la
  póliza ENTERA se aborta (0 líneas migradas de esa póliza) y se manda
  a una cola `polizas_bloqueadas`; nunca debe migrar parcialmente una
  póliza dejando débito≠crédito en destino."

Sin mocks: corre `alembic upgrade head` contra una base de PostgreSQL de
pruebas dedicada (creada y dropeada por test, igual que
`tests/migrations/test_0012_cuenta_id_fk.py`) e invoca
`b2b_ai.features.migracion_catalogo.migrador.migrar_poliza` con una
conexión `psycopg` real. Las aserciones leen `lineas_poliza_migradas` y
`polizas_bloqueadas` directamente por SQL -- nunca se asume el
resultado de la función, se verifica el estado real de la base.

Requiere un PG alcanzable vía B2B_DB_URL; si no hay uno disponible, se
skippea (no se asume ni se mockea el resultado de la migración).
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
    dbname = f"b2b_pg_reqmig009_{uuid.uuid4().hex[:10]}"
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
    """Crea el tenant y `n_destino` cuentas reales en `cuentas_contables`
    (destino), devolviendo sus `cuenta_id` UUID reales -- nunca un UUID
    inventado, para que la FK de `lineas_poliza_migradas` sea genuina."""
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


def _mapeo_pendiente(origen_id: str, destino_id) -> MapeoMigracionCuenta:
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_id,
        destino_cuenta_id=str(destino_id),
        tipo_match=TipoMatchMigracion.FUZZY,
        score=75.0,
        estado=EstadoMapeoMigracion.PENDIENTE,
    )


def _lineas_migradas(conn, poliza_id):
    cur = conn.execute(
        "SELECT cuenta_origen_id, cuenta_destino_id, debe, haber "
        "FROM lineas_poliza_migradas WHERE tenant_id=%s AND poliza_origen_id=%s "
        "ORDER BY cuenta_origen_id",
        (TENANT_ID, poliza_id),
    )
    return cur.fetchall()


def _polizas_bloqueadas(conn, poliza_id):
    cur = conn.execute(
        "SELECT motivo, cuentas_sin_mapeo FROM polizas_bloqueadas "
        "WHERE tenant_id=%s AND poliza_origen_id=%s",
        (TENANT_ID, poliza_id),
    )
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Camino feliz: todas las líneas tienen mapeo aprobado -> migra completa.
# ---------------------------------------------------------------------------

def test_poliza_con_todas_las_lineas_mapeadas_migra_completa(conn):
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-001",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-BANCOS", debe=Decimal("500.00"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-VENTAS", debe=Decimal("0"), haber=Decimal("500.00")),
        ),
    )
    mapeos = {
        "ORIG-BANCOS": _mapeo_aprobado("ORIG-BANCOS", destinos[0]),
        "ORIG-VENTAS": _mapeo_aprobado("ORIG-VENTAS", destinos[1]),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.migrada is True
    assert resultado.bloqueada is False
    assert resultado.lineas_migradas == 2

    filas = _lineas_migradas(conn, "POL-001")
    assert len(filas) == 2
    assert _polizas_bloqueadas(conn, "POL-001") == []

    total_debe = sum(Decimal(f[2]) for f in filas)
    total_haber = sum(Decimal(f[3]) for f in filas)
    assert total_debe == total_haber == Decimal("500.00")


def test_mapeo_editado_tambien_migra_como_aprobado(conn):
    """EDITADO cuenta igual que APROBADO para migrar (ver docstring del
    módulo de producción sobre la interpretación de ADR-3)."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-EDIT",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-X", debe=Decimal("10"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-Y", debe=Decimal("0"), haber=Decimal("10")),
        ),
    )
    mapeo_editado = _mapeo_aprobado("ORIG-X", destinos[0]).model_copy(
        update={"estado": EstadoMapeoMigracion.EDITADO}
    )
    mapeos = {
        "ORIG-X": mapeo_editado,
        "ORIG-Y": _mapeo_aprobado("ORIG-Y", destinos[1]),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.migrada is True
    assert resultado.lineas_migradas == 2


# ---------------------------------------------------------------------------
# El caso central del criterio: una sola línea sin mapeo aprobado aborta
# TODA la póliza, incluidas las líneas que sí tenían mapeo válido.
# ---------------------------------------------------------------------------

def test_una_linea_sin_mapeo_aprobado_aborta_la_poliza_entera(conn):
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-002",
        tenant_id=TENANT_ID,
        lineas=(
            # Esta línea SÍ tiene mapeo aprobado.
            LineaPolizaOrigen("ORIG-BANCOS", debe=Decimal("300.00"), haber=Decimal("0")),
            # Esta línea NO tiene ningún mapeo registrado.
            LineaPolizaOrigen("ORIG-SIN-MAPEO", debe=Decimal("0"), haber=Decimal("300.00")),
        ),
    )
    mapeos = {
        "ORIG-BANCOS": _mapeo_aprobado("ORIG-BANCOS", destinos[0]),
        # ORIG-SIN-MAPEO deliberadamente ausente del dict.
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.migrada is False
    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0
    assert resultado.cuentas_sin_mapeo_aprobado == ("ORIG-SIN-MAPEO",)

    # Cero líneas migradas -- ni siquiera ORIG-BANCOS, que sí tenía un
    # mapeo aprobado. Esto es lo que el criterio prohíbe explícitamente:
    # migrar parcialmente dejando débito≠crédito en destino.
    filas = _lineas_migradas(conn, "POL-002")
    assert filas == [], (
        "una póliza bloqueada no debe dejar NINGUNA línea en destino, "
        f"ni siquiera las que sí tenían mapeo aprobado; encontradas: {filas}"
    )

    bloqueadas = _polizas_bloqueadas(conn, "POL-002")
    assert len(bloqueadas) == 1
    motivo, cuentas_sin_mapeo_json = bloqueadas[0]
    assert "ORIG-SIN-MAPEO" in motivo
    import json

    assert json.loads(cuentas_sin_mapeo_json) == ["ORIG-SIN-MAPEO"]


def test_linea_con_mapeo_pendiente_tambien_bloquea_la_poliza(conn):
    """Un mapeo que EXISTE pero sigue `pendiente` (nunca pasó por el
    endpoint de aprobación, REQ-MIG-007) cuenta igual que no tener
    ningún mapeo: la póliza se bloquea completa."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-003",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-A", debe=Decimal("100"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-B", debe=Decimal("0"), haber=Decimal("100")),
        ),
    )
    mapeos = {
        "ORIG-A": _mapeo_aprobado("ORIG-A", destinos[0]),
        "ORIG-B": _mapeo_pendiente("ORIG-B", destinos[1]),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0
    assert resultado.cuentas_sin_mapeo_aprobado == ("ORIG-B",)
    assert _lineas_migradas(conn, "POL-003") == []


def test_linea_con_mapeo_rechazado_tambien_bloquea_la_poliza(conn):
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-004",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-A", debe=Decimal("50"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-B", debe=Decimal("0"), haber=Decimal("50")),
        ),
    )
    mapeo_rechazado = _mapeo_pendiente("ORIG-B", destinos[1]).model_copy(
        update={
            "estado": EstadoMapeoMigracion.RECHAZADO,
            "aprobado_por": "contador_lider",
            "aprobado_en": "2026-09-08T12:00:00+00:00",
            "nota": "no aplica",
        }
    )
    mapeos = {
        "ORIG-A": _mapeo_aprobado("ORIG-A", destinos[0]),
        "ORIG-B": mapeo_rechazado,
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0
    assert _lineas_migradas(conn, "POL-004") == []


def test_poliza_con_todas_las_lineas_sin_mapeo_tambien_bloquea(conn):
    _sembrar_tenant_y_cuentas(conn, n_destino=0)
    poliza = PolizaOrigen(
        id="POL-005",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-X", debe=Decimal("1"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-Y", debe=Decimal("0"), haber=Decimal("1")),
        ),
    )

    resultado = migrar_poliza(conn, poliza, {})

    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0
    assert resultado.cuentas_sin_mapeo_aprobado == ("ORIG-X", "ORIG-Y")


# ---------------------------------------------------------------------------
# Atomicidad real de base de datos: un fallo de la propia base de datos a
# mitad de la escritura (FK inválida) también debe revertir TODO -- no
# solo la línea que falló.
# ---------------------------------------------------------------------------

def test_fk_invalida_en_destino_revierte_toda_la_transaccion_de_la_poliza(conn):
    """Simula un mapeo "stale" cuya `destino_cuenta_id` ya no existe en
    `cuentas_contables` (p.ej. la cuenta destino se borró después de
    aprobar el mapeo). Ambas líneas tienen mapeo `aprobado` -- pasan el
    chequeo de aplicación -- pero el INSERT de la segunda debe fallar
    por la FK real de Postgres, y la transacción debe revertir también
    el INSERT de la primera línea, que sí era válido."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=1)
    poliza = PolizaOrigen(
        id="POL-FK",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-VALIDA", debe=Decimal("200"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-STALE", debe=Decimal("0"), haber=Decimal("200")),
        ),
    )
    destino_inexistente = "00000000-0000-0000-0000-000000000000"
    mapeos = {
        "ORIG-VALIDA": _mapeo_aprobado("ORIG-VALIDA", destinos[0]),
        "ORIG-STALE": _mapeo_aprobado("ORIG-STALE", destino_inexistente),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.migrada is False
    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0

    filas = _lineas_migradas(conn, "POL-FK")
    assert filas == [], (
        "la FK inválida de UNA línea no debe dejar la OTRA línea "
        f"(ORIG-VALIDA, que sí era válida) huérfana en destino: {filas}"
    )
    assert len(_polizas_bloqueadas(conn, "POL-FK")) == 1

    # La conexión debe quedar utilizable después del rollback -- una
    # nueva operación normal debe funcionar sin necesidad de reconectar.
    otra = conn.execute("SELECT 1").fetchone()
    assert otra == (1,)


# ---------------------------------------------------------------------------
# Casos borde de la función.
# ---------------------------------------------------------------------------

def test_desbalance_tras_remapeo_bloquea_en_lugar_de_confirmar(conn):
    """Defensa en profundidad: si por algún motivo debe != haber entre
    las líneas con mapeo válido (no debería pasar nunca si la póliza de
    origen ya venía cuadrada), el motor debe abortar y bloquear en vez
    de confirmar una transacción desbalanceada en destino."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)
    poliza = PolizaOrigen(
        id="POL-DESBALANCE",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-A", debe=Decimal("100"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-B", debe=Decimal("0"), haber=Decimal("99")),
        ),
    )
    mapeos = {
        "ORIG-A": _mapeo_aprobado("ORIG-A", destinos[0]),
        "ORIG-B": _mapeo_aprobado("ORIG-B", destinos[1]),
    }

    resultado = migrar_poliza(conn, poliza, mapeos)

    assert resultado.migrada is False
    assert resultado.bloqueada is True
    assert resultado.lineas_migradas == 0
    assert _lineas_migradas(conn, "POL-DESBALANCE") == [], (
        "un desbalance detectado ANTES de confirmar la transacción no "
        "debe dejar ninguna línea en destino"
    )
    assert len(_polizas_bloqueadas(conn, "POL-DESBALANCE")) == 1


def test_poliza_sin_lineas_lanza_value_error(conn):
    poliza = PolizaOrigen(id="POL-VACIA", tenant_id=TENANT_ID, lineas=())
    with pytest.raises(ValueError):
        migrar_poliza(conn, poliza, {})


def test_dos_polizas_independientes_no_se_afectan_entre_si(conn):
    """Una póliza bloqueada no debe impedir que otra póliza, correcta,
    migre en la misma sesión de trabajo."""
    destinos = _sembrar_tenant_y_cuentas(conn, n_destino=2)

    poliza_mala = PolizaOrigen(
        id="POL-MALA",
        tenant_id=TENANT_ID,
        lineas=(LineaPolizaOrigen("ORIG-HUERFANA", debe=Decimal("1"), haber=Decimal("0")),),
    )
    resultado_mala = migrar_poliza(conn, poliza_mala, {})
    assert resultado_mala.bloqueada is True

    poliza_buena = PolizaOrigen(
        id="POL-BUENA",
        tenant_id=TENANT_ID,
        lineas=(
            LineaPolizaOrigen("ORIG-C", debe=Decimal("20"), haber=Decimal("0")),
            LineaPolizaOrigen("ORIG-D", debe=Decimal("0"), haber=Decimal("20")),
        ),
    )
    mapeos = {
        "ORIG-C": _mapeo_aprobado("ORIG-C", destinos[0]),
        "ORIG-D": _mapeo_aprobado("ORIG-D", destinos[1]),
    }
    resultado_buena = migrar_poliza(conn, poliza_buena, mapeos)

    assert resultado_buena.migrada is True
    assert resultado_buena.lineas_migradas == 2
    assert len(_lineas_migradas(conn, "POL-BUENA")) == 2
    assert _lineas_migradas(conn, "POL-MALA") == []
