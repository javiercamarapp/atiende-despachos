# -*- coding: utf-8 -*-
"""Prueba adversarial central de este cluster: el origen NUNCA se
modifica, bajo NINGÚN escenario -- éxito, fallo a medias (algunas
pólizas del lote sí migran, otras se bloquean), o fallo total (todas
las pólizas del lote se bloquean).

Se verifica en dos capas independientes, cada una suficiente por sí
sola (ver docstring de `cross_db.py`):
  (a) Efecto observable: un snapshot completo de TODAS las tablas de
      origen relevantes (cuentas_contables, asientos_contables, y el
      conteo total de filas de cada una) tomado ANTES de migrar debe
      ser BIT A BIT idéntico al tomado DESPUÉS -- para los tres
      escenarios.
  (b) Mecanismo: un intento de escritura directo contra la conexión de
      origen debe ser rechazado por Postgres mismo
      (`ReadOnlySqlTransaction`), no solo evitado por el código de la
      aplicación.

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
        return cur.fetchone()[0]


def _sembrar_asiento(conn, tenant_id, fecha, cuenta_debito, cuenta_credito, monto):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO asientos_contables "
            "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, fecha, cuenta_debito, cuenta_credito, str(monto)),
        )
        return str(cur.fetchone()[0])


def _snapshot_origen(dsn) -> dict:
    """Snapshot completo y determinista del estado observable de
    origen: filas de `cuentas_contables` y `asientos_contables` para el
    tenant de prueba, en un orden estable."""
    conn = psycopg.connect(dsn)
    try:
        cuentas = conn.execute(
            "SELECT tenant_id, codigo, descripcion, nivel, naturaleza, grupo "
            "FROM cuentas_contables WHERE tenant_id = %s ORDER BY codigo",
            (TENANT_ORIGEN,),
        ).fetchall()
        asientos = conn.execute(
            "SELECT id, tenant_id, fecha, cuenta_debito, cuenta_credito, monto, descripcion "
            "FROM asientos_contables WHERE tenant_id = %s ORDER BY id",
            (TENANT_ORIGEN,),
        ).fetchall()
        return {"cuentas": cuentas, "asientos": asientos}
    finally:
        conn.close()


@pytest.fixture
def bases_con_datos(dos_bases_migradas):
    origen_dsn, destino_dsn = dos_bases_migradas
    conn_o = psycopg.connect(origen_dsn)
    conn_d = psycopg.connect(destino_dsn)
    try:
        _sembrar_tenant(conn_o, TENANT_ORIGEN)
        _sembrar_tenant(conn_d, TENANT_DESTINO)

        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "1000", "Bancos")
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
        _sembrar_cuenta(conn_o, TENANT_ORIGEN, "9999", "Cuenta Sin Mapeo")

        destino_bancos = _sembrar_cuenta(conn_d, TENANT_DESTINO, "1000", "Bancos")
        destino_ventas = _sembrar_cuenta(conn_d, TENANT_DESTINO, "4000", "Ventas", naturaleza="A", grupo="Ingreso")

        p_ok = _sembrar_asiento(conn_o, TENANT_ORIGEN, "2024-01-01", "1000", "4000", "100.00")
        p_sin_mapeo = _sembrar_asiento(conn_o, TENANT_ORIGEN, "2024-01-02", "9999", "1000", "50.00")
    finally:
        conn_o.close()
        conn_d.close()

    return {
        "origen_dsn": origen_dsn,
        "destino_dsn": destino_dsn,
        "destino_bancos": str(destino_bancos),
        "destino_ventas": str(destino_ventas),
        "p_ok": p_ok,
        "p_sin_mapeo": p_sin_mapeo,
    }


def _mapeo_aprobado(origen_codigo, destino_id):
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_codigo,
        destino_cuenta_id=str(destino_id),
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=EstadoMapeoMigracion.APROBADO,
        aprobado_por="contador_lider",
        aprobado_en="2026-09-09T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# (a) Escenario de ÉXITO total: todo migra, origen sigue intacto.
# ---------------------------------------------------------------------------

def test_origen_intacto_tras_migracion_100_por_ciento_exitosa(bases_con_datos):
    b = bases_con_datos
    snapshot_antes = _snapshot_origen(b["origen_dsn"])

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo_aprobado("1000", b["destino_bancos"]),
            "4000": _mapeo_aprobado("4000", b["destino_ventas"]),
            "9999": _mapeo_aprobado("9999", b["destino_bancos"]),  # también mapeada
        }
        resultados = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)
        assert all(r.migrada for r in resultados.values())

    snapshot_despues = _snapshot_origen(b["origen_dsn"])
    assert snapshot_antes == snapshot_despues, (
        "el origen cambió tras una migración 100% exitosa -- nunca debe "
        "modificarse, ni siquiera cuando todo migra sin problemas"
    )


# ---------------------------------------------------------------------------
# (b) Escenario de FALLO A MEDIAS: una póliza migra, otra se bloquea.
# ---------------------------------------------------------------------------

def test_origen_intacto_tras_fallo_a_medias_del_lote(bases_con_datos):
    b = bases_con_datos
    snapshot_antes = _snapshot_origen(b["origen_dsn"])

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo_aprobado("1000", b["destino_bancos"]),
            "4000": _mapeo_aprobado("4000", b["destino_ventas"]),
            # "9999" deliberadamente sin mapeo -> p_sin_mapeo se bloquea.
        }
        resultados = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)
        assert resultados[b["p_ok"]].migrada is True
        assert resultados[b["p_sin_mapeo"]].bloqueada is True

    snapshot_despues = _snapshot_origen(b["origen_dsn"])
    assert snapshot_antes == snapshot_despues, (
        "el origen cambió tras un lote con fallo A MEDIAS -- ni la "
        "póliza migrada ni la bloqueada deben tocar origen"
    )


# ---------------------------------------------------------------------------
# (c) Escenario de FALLO TOTAL: absolutamente ninguna póliza migra.
# ---------------------------------------------------------------------------

def test_origen_intacto_tras_fallo_total_del_lote(bases_con_datos):
    b = bases_con_datos
    snapshot_antes = _snapshot_origen(b["origen_dsn"])

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        # Ningún mapeo aprobado en absoluto -> las dos pólizas se bloquean.
        resultados = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, {})
        assert all(r.bloqueada for r in resultados.values())
        assert all(r.lineas_migradas == 0 for r in resultados.values())

    snapshot_despues = _snapshot_origen(b["origen_dsn"])
    assert snapshot_antes == snapshot_despues, (
        "el origen cambió tras un fallo TOTAL del lote -- ninguna "
        "póliza bloqueada debe dejar rastro en origen"
    )


# ---------------------------------------------------------------------------
# (d) Fallo real de Postgres a mitad de la transacción de DESTINO (FK
#     inválida) -- también debe dejar origen sin tocar.
# ---------------------------------------------------------------------------

def test_origen_intacto_cuando_destino_falla_por_fk_invalida(bases_con_datos):
    b = bases_con_datos
    snapshot_antes = _snapshot_origen(b["origen_dsn"])
    destino_inexistente = "00000000-0000-0000-0000-000000000000"

    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        mapeos = {
            "1000": _mapeo_aprobado("1000", b["destino_bancos"]),
            # destino "stale": ya no existe en destino -> FK real falla.
            "4000": _mapeo_aprobado("4000", destino_inexistente),
        }
        resultado = migrar_lote_cross_db(c, TENANT_ORIGEN, TENANT_DESTINO, mapeos)[b["p_ok"]]
        assert resultado.migrada is False
        assert resultado.bloqueada is True

        # Confirma también que destino no dejó una línea huérfana.
        filas_destino = c.destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id = %s",
            (TENANT_DESTINO,),
        ).fetchone()[0]
        assert filas_destino == 0

    snapshot_despues = _snapshot_origen(b["origen_dsn"])
    assert snapshot_antes == snapshot_despues


# ---------------------------------------------------------------------------
# Mecanismo (no solo efecto observable): un intento de escritura DIRECTO
# contra origen, en medio de una migración en curso, debe ser rechazado
# por Postgres mismo -- no solo por disciplina del código de este módulo.
# ---------------------------------------------------------------------------

def test_intento_de_escritura_directa_en_origen_es_rechazado_por_postgres(bases_con_datos):
    b = bases_con_datos
    with ConexionesMigracion(b["origen_dsn"], b["destino_dsn"]) as c:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with c.origen.transaction():
                c.origen.execute(
                    "UPDATE cuentas_contables SET descripcion = 'HACKEADO' "
                    "WHERE tenant_id = %s AND codigo = %s",
                    (TENANT_ORIGEN, "1000"),
                )
        c.origen.rollback()

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with c.origen.transaction():
                c.origen.execute(
                    "DELETE FROM asientos_contables WHERE tenant_id = %s",
                    (TENANT_ORIGEN,),
                )
        c.origen.rollback()

    snapshot_despues = _snapshot_origen(b["origen_dsn"])
    # El intento de escritura fue rechazado -- el snapshot debe seguir
    # mostrando "Bancos", nunca "HACKEADO", y los 2 asientos intactos.
    assert any(fila[2] == "Bancos" for fila in snapshot_despues["cuentas"])
    assert len(snapshot_despues["asientos"]) == 2
