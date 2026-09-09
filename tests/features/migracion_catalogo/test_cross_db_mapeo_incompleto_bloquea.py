# -*- coding: utf-8 -*-
"""Prueba adversarial: una póliza con mapeo INCOMPLETO en destino se
bloquea sin escribir NADA parcial -- ni una línea suelta, ni en la
póliza incompleta ni en ninguna otra póliza del mismo lote.

"Incompleto" cubre los tres casos reales que puede tener un mapeo de
cuenta en un lote cross-database:
  1. La cuenta de origen no tiene NINGÚN mapeo registrado todavía.
  2. La cuenta de origen tiene un mapeo, pero sigue `pendiente` (nunca
     pasó por la aprobación humana explícita, REQ-MIG-007).
  3. La cuenta de origen tiene un mapeo `sin_match` (el motor de
     matching no encontró ningún candidato razonable en destino) --
     `destino_cuenta_id=None` por diseño, nunca migrable.

Sin mocks: dos bases de PostgreSQL efímeras reales.
"""
from __future__ import annotations

import psycopg
import pytest

from .conftest import _pg_available

from b2b_ai.features.migracion_catalogo.cross_db import (
    ConexionesMigracion,
    migrar_lote_cross_db,
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
            "INSERT INTO tenants (id, name) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (tenant_id, "t"),
        )


def _sembrar_cuenta(conn, tenant_id, codigo, descripcion, naturaleza="D", grupo="Activo"):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO cuentas_contables "
            "(tenant_id, codigo, descripcion, naturaleza, grupo) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING cuenta_id",
            (tenant_id, codigo, descripcion, naturaleza, grupo),
        )
        return str(cur.fetchone()[0])


def _sembrar_asiento(conn, tenant_id, fecha, cuenta_debito, cuenta_credito, monto):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO asientos_contables "
            "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, fecha, cuenta_debito, cuenta_credito, str(monto)),
        )
        return str(cur.fetchone()[0])


def _mapeo(origen_codigo, destino_id, estado, tipo_match=TipoMatchMigracion.EXACTO, score=100.0):
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_codigo,
        destino_cuenta_id=destino_id,
        tipo_match=tipo_match,
        score=score,
        estado=estado,
        aprobado_por="contador_lider" if estado != EstadoMapeoMigracion.PENDIENTE else None,
        aprobado_en="2026-09-09T00:00:00+00:00" if estado != EstadoMapeoMigracion.PENDIENTE else None,
    )


@pytest.fixture
def bases(dos_bases_migradas):
    origen_dsn, destino_dsn = dos_bases_migradas
    conn_o = psycopg.connect(origen_dsn)
    conn_d = psycopg.connect(destino_dsn)
    try:
        _sembrar_tenant(conn_o, TENANT_ORIGEN)
        _sembrar_tenant(conn_d, TENANT_DESTINO)
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "1000", "Bancos")
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "9000", "Cuenta Fantasma")
        destino_bancos = _sembrar_cuenta(conn_d, TENANT_DESTINO, "1000", "Bancos")
        destino_ventas = _sembrar_cuenta(conn_d, TENANT_DESTINO, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
    finally:
        conn_o.close()
        conn_d.close()
    return {
        "origen_dsn": origen_dsn,
        "destino_dsn": destino_dsn,
        "destino_bancos": destino_bancos,
        "destino_ventas": destino_ventas,
    }


def _sembrar_poliza(origen_dsn, cuenta_debito, cuenta_credito, monto="100.00", fecha="2024-01-01"):
    conn = psycopg.connect(origen_dsn)
    try:
        return _sembrar_asiento(conn, TENANT_ORIGEN, fecha, cuenta_debito, cuenta_credito, monto)
    finally:
        conn.close()


def test_cuenta_sin_ningun_mapeo_bloquea_sin_escritura_parcial(bases):
    poliza_id = _sembrar_poliza(bases["origen_dsn"], "1000", "9000")  # "9000" sin mapeo alguno
    with ConexionesMigracion(bases["origen_dsn"], bases["destino_dsn"]) as c:
        mapeos = {"1000": _mapeo("1000", bases["destino_bancos"], EstadoMapeoMigracion.APROBADO)}
        resultado = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)[poliza_id]

        assert resultado.bloqueada is True
        assert resultado.lineas_migradas == 0
        assert resultado.cuentas_sin_mapeo_aprobado == ("9000",)

        filas = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s AND poliza_origen_id=%s",
            (TENANT_DESTINO, poliza_id),
        ).fetchone()[0]
        assert filas == 0, "0 líneas parciales -- ni siquiera la línea de la cuenta 1000, que sí tenía mapeo"


def test_cuenta_con_mapeo_pendiente_bloquea_sin_escritura_parcial(bases):
    poliza_id = _sembrar_poliza(bases["origen_dsn"], "1000", "4000")
    with ConexionesMigracion(bases["origen_dsn"], bases["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo("1000", bases["destino_bancos"], EstadoMapeoMigracion.APROBADO),
            # "4000" tiene un mapeo, pero sigue pendiente -- nunca pasó
            # por la aprobación humana explícita de REQ-MIG-007.
            "4000": _mapeo(
                "4000", bases["destino_ventas"], EstadoMapeoMigracion.PENDIENTE,
                tipo_match=TipoMatchMigracion.FUZZY, score=75.0,
            ),
        }
        resultado = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)[poliza_id]

        assert resultado.bloqueada is True
        assert resultado.lineas_migradas == 0
        assert resultado.cuentas_sin_mapeo_aprobado == ("4000",)

        filas = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s AND poliza_origen_id=%s",
            (TENANT_DESTINO, poliza_id),
        ).fetchone()[0]
        assert filas == 0


def test_cuenta_sin_match_bloquea_sin_escritura_parcial(bases):
    """`sin_match` es, por diseño, un mapeo con `destino_cuenta_id=None`
    -- nunca migrable aunque exista un registro para la cuenta."""
    poliza_id = _sembrar_poliza(bases["origen_dsn"], "1000", "4000")
    with ConexionesMigracion(bases["origen_dsn"], bases["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo("1000", bases["destino_bancos"], EstadoMapeoMigracion.APROBADO),
            "4000": MapeoMigracionCuenta(
                origen_cuenta_id="4000",
                destino_cuenta_id=None,
                tipo_match=TipoMatchMigracion.SIN_MATCH,
                score=0.0,
                estado=EstadoMapeoMigracion.PENDIENTE,
                nota="cuenta nueva a crear en destino",
            ),
        }
        resultado = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)[poliza_id]

        assert resultado.bloqueada is True
        assert resultado.lineas_migradas == 0

        filas = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s AND poliza_origen_id=%s",
            (TENANT_DESTINO, poliza_id),
        ).fetchone()[0]
        assert filas == 0


def test_una_poliza_bloqueada_no_afecta_otras_polizas_correctas_del_mismo_lote(bases):
    """El bloqueo es por póliza, no contamina el resto del lote (varias
    docenas de pólizas correctas en un lote real no deben verse
    afectadas porque una de ellas tenga una cuenta sin mapeo)."""
    poliza_mala = _sembrar_poliza(bases["origen_dsn"], "1000", "9000", monto="10.00", fecha="2024-01-01")
    poliza_buena = _sembrar_poliza(bases["origen_dsn"], "1000", "4000", monto="20.00", fecha="2024-01-02")

    with ConexionesMigracion(bases["origen_dsn"], bases["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo("1000", bases["destino_bancos"], EstadoMapeoMigracion.APROBADO),
            "4000": _mapeo("4000", bases["destino_ventas"], EstadoMapeoMigracion.APROBADO),
            # "9000" deliberadamente ausente.
        }
        resultados = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)

        assert resultados[poliza_mala].bloqueada is True
        assert resultados[poliza_mala].lineas_migradas == 0
        assert resultados[poliza_buena].migrada is True
        assert resultados[poliza_buena].lineas_migradas == 2

        total = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=%s",
            (TENANT_DESTINO,),
        ).fetchone()[0]
        assert total == 2  # solo las 2 líneas de la póliza buena
