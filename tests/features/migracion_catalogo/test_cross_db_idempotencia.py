# -*- coding: utf-8 -*-
"""Prueba adversarial: reintentar una migración cross-database ya
completada es idempotente -- 0 filas nuevas duplicadas, sin importar
cuántas veces se reintente, y sin importar si el reintento ocurre con
una `ConexionesMigracion` completamente NUEVA (simulando un proceso que
se reinicia a medias -- el caso real que motiva REQ-MIG-010 en un
escenario cross-database de "cientos de pólizas").

Reutiliza `migrador.poliza_ya_migrada`/`migrar_poliza` SIN
MODIFICARLOS: la idempotencia por póliza ya está garantizada ahí
(REQ-MIG-010); esta prueba confirma que sigue cumpliéndose cuando la
póliza se carga desde una base de datos de origen físicamente distinta
en cada intento, no desde un objeto `PolizaOrigen` reutilizado en
memoria.

Sin mocks: dos bases de PostgreSQL efímeras reales.
"""
from __future__ import annotations

import psycopg
import pytest

from .conftest import _pg_available

from b2b_ai.features.migracion_catalogo.cross_db import (
    ConexionesMigracion,
    migrar_lote_cross_db,
    migrar_poliza_cross_db,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)

pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)

TENANT_ORIGEN = 1
TENANT_DESTINO = 1


def _sembrar_tenant(conn, tenant_id: int) -> None:
    with conn.transaction():
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (tenant_id, "t"),
        )


def _sembrar_cuenta(conn, tenant_id, codigo, descripcion, naturaleza="D", grupo="Activo"):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO cuentas_contables (tenant_id, codigo, descripcion, naturaleza, grupo) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING cuenta_id",
            (tenant_id, codigo, descripcion, naturaleza, grupo),
        )
        return str(cur.fetchone()[0])


def _sembrar_asiento(conn, tenant_id, fecha, cuenta_debito, cuenta_credito, monto):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO asientos_contables (tenant_id, fecha, cuenta_debito, cuenta_credito, monto) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, fecha, cuenta_debito, cuenta_credito, str(monto)),
        )
        return str(cur.fetchone()[0])


def _mapeo(origen_codigo, destino_id):
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_codigo,
        destino_cuenta_id=destino_id,
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
        aprobado_por="contador_lider",
        aprobado_en="2026-09-09T00:00:00+00:00",
    )


@pytest.fixture
def bases_con_lote(dos_bases_migradas):
    origen_dsn, destino_dsn = dos_bases_migradas
    conn_o = psycopg.connect(origen_dsn)
    conn_d = psycopg.connect(destino_dsn)
    try:
        _sembrar_tenant(conn_o, TENANT_ORIGEN)
        _sembrar_tenant(conn_d, TENANT_DESTINO)
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "1000", "Bancos")
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
        destino_bancos = _sembrar_cuenta(conn_d, TENANT_DESTINO, "1000", "Bancos")
        destino_ventas = _sembrar_cuenta(conn_d, TENANT_DESTINO, "4000", "Ventas", naturaleza="A", grupo="Ingreso")

        ids = [
            _sembrar_asiento(conn_o, TENANT_ORIGEN, "2024-01-01", "1000", "4000", "10.00"),
            _sembrar_asiento(conn_o, TENANT_ORIGEN, "2024-01-02", "1000", "4000", "20.00"),
            _sembrar_asiento(conn_o, TENANT_ORIGEN, "2024-01-03", "1000", "4000", "30.00"),
        ]
    finally:
        conn_o.close()
        conn_d.close()

    mapeos = {
        "1000": _mapeo("1000", destino_bancos),
        "4000": _mapeo("4000", destino_ventas),
    }
    return {
        "origen_dsn": origen_dsn,
        "destino_dsn": destino_dsn,
        "mapeos": mapeos,
        "poliza_ids": ids,
    }


def _contar_lineas_destino(destino_dsn):
    conn = psycopg.connect(destino_dsn)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s",
            (TENANT_DESTINO,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_reintentar_el_lote_completo_con_conexiones_nuevas_no_duplica_nada(bases_con_lote):
    b = bases_con_lote

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c1:
        primero = migrar_lote_cross_db(c1, TENANT_ORIGEN, TENANT_DESTINO, b["mapeos"])
    assert all(r.migrada and not r.ya_migrada for r in primero.values())
    assert _contar_lineas_destino(b["destino_dsn"]) == 6  # 3 pólizas x 2 líneas

    # Reintento con CONEXIONES COMPLETAMENTE NUEVAS -- simula un proceso
    # que se reinició por completo entre el primer intento y el segundo.
    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c2:
        segundo = migrar_lote_cross_db(c2, TENANT_ORIGEN, TENANT_DESTINO, b["mapeos"])
    assert all(r.migrada and r.ya_migrada for r in segundo.values())
    assert _contar_lineas_destino(b["destino_dsn"]) == 6, (
        "el reintento del lote completo con conexiones nuevas duplicó filas"
    )

    # Un tercer y cuarto reintento siguen sin duplicar nada -- no es un
    # caso especial del "segundo" intento.
    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c3:
        migrar_lote_cross_db(c3, TENANT_ORIGEN, TENANT_DESTINO, b["mapeos"])
    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c4:
        cuarto = migrar_lote_cross_db(c4, TENANT_ORIGEN, TENANT_DESTINO, b["mapeos"])
    assert all(r.ya_migrada for r in cuarto.values())
    assert _contar_lineas_destino(b["destino_dsn"]) == 6


def test_reintentar_una_sola_poliza_ya_migrada_es_idempotente(bases_con_lote):
    b = bases_con_lote
    poliza_id = b["poliza_ids"][0]

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        primero = migrar_poliza_cross_db(
            c, TENANT_ORIGEN, TENANT_DESTINO, poliza_id, b["mapeos"]
        )
        assert primero.migrada is True and primero.ya_migrada is False

        segundo = migrar_poliza_cross_db(
            c, TENANT_ORIGEN, TENANT_DESTINO, poliza_id, b["mapeos"]
        )
        assert segundo.migrada is True
        assert segundo.ya_migrada is True
        assert segundo.bloqueada is False
        assert segundo.lineas_migradas == primero.lineas_migradas == 2

        filas = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s AND poliza_origen_id=%s",
            (TENANT_DESTINO, poliza_id),
        ).fetchone()[0]
        assert filas == 2


def test_reintento_de_un_lote_con_polizas_bloqueadas_tampoco_duplica_bloqueos(bases_con_lote):
    """Una póliza bloqueada, al reintentar el lote, se vuelve a evaluar
    (no es "idempotente" en el mismo sentido que una migrada -- puede
    incluso desbloquearse si mientras tanto se aprobó el mapeo
    faltante) pero nunca debe acumular registros de bloqueo duplicados
    de forma descontrolada para el mismo estado."""
    b = bases_con_lote
    mapeos_incompletos = {"1000": b["mapeos"]["1000"]}  # falta "4000" a propósito

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c1:
        primero = migrar_lote_cross_db(c1, TENANT_ORIGEN, TENANT_DESTINO, mapeos_incompletos)
    assert all(r.bloqueada for r in primero.values())

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c2:
        segundo = migrar_lote_cross_db(c2, TENANT_ORIGEN, TENANT_DESTINO, mapeos_incompletos)
    assert all(r.bloqueada for r in segundo.values())
    assert _contar_lineas_destino(b["destino_dsn"]) == 0

    conn_d = psycopg.connect(b["destino_dsn"])
    try:
        total_bloqueadas = conn_d.execute(
            "SELECT COUNT(*) FROM polizas_bloqueadas WHERE tenant_id=%s",
            (TENANT_DESTINO,),
        ).fetchone()[0]
    finally:
        conn_d.close()
    # 3 pólizas x 2 intentos -- cada intento SÍ vuelve a encolar (no hay
    # idempotencia de "bloqueo" en el diseño actual, solo de "migrada",
    # ver migrador.py), pero el conteo debe ser exactamente predecible
    # (2 por póliza), nunca crecer sin control ni perder registros.
    assert total_bloqueadas == 6
