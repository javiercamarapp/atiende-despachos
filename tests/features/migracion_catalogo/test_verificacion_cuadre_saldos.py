# -*- coding: utf-8 -*-
"""
test_verificacion_cuadre_saldos.py — REQ-MIG-012.

Criterio de aceptación exacto (docs/BLUEPRINT-AGENTES-FISCALES.md §3):

  "Verificación de integridad post-migración — cuadre de saldos: para
  cada cuenta migrada, `abs(saldo_destino_periodo - saldo_origen_periodo)
  <= 0.01` MXN; una diferencia mayor debe bloquear el cierre de la
  migración con un reporte de las cuentas que no cuadraron."

Nota honesta sobre el estado previo de este requisito: el código de
`b2b_ai/features/migracion_catalogo/verificacion.py` que implementa
REQ-MIG-012 (`construir_reporte_cuadre`, `calcular_saldo_cuenta_periodo`,
`verificar_cuadre_saldos`, `cerrar_migracion`) YA EXISTÍA antes de este
cambio (agregado en el mismo commit que REQ-MIG-013/014), pero sin
ningún test -- ni este archivo ni ningún otro lo ejercitaban (`grep` de
"verificar_cuadre_saldos"/"construir_reporte_cuadre" en `tests/` no
daba resultados), y el propio docstring del módulo seguía listando
REQ-MIG-012 como "pendiente, no se toca en este archivo" pese a que el
código ya estaba debajo. Este archivo es la primera verificación real
de ese código contra los criterios exactos del blueprint.

Dos capas de prueba (mismo patrón que REQ-MIG-013/014):

  1. `TestConstruirReporteCuadre` -- la función pura sobre saldos ya
     calculados (`ParSaldoCuenta`): tolerancia exacta de $0.01 (cuadra
     en el límite, no cuadra por encima), mapeos sin destino, y la
     propiedad `cierre_permitido`. No requiere BD.

  2. `TestVerificarCuadreSaldosEnBD` -- integración contra PostgreSQL
     real: dos tenants reales (origen/destino), cuentas reales en
     `cuentas_contables` (con su `cuenta_id` UUID real, REQ-MIG-001) y
     asientos reales en `asientos_contables`, y `verificar_cuadre_saldos`/
     `cerrar_migracion` calculando el saldo real de cada cuenta para el
     periodo -- sin mocks de la conexión ni de las consultas. Se
     skippea si no hay `B2B_DB_URL` disponible.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.verificacion import (
    CuadreSaldosNoPermiteCierreError,
    CuentaContableNoEncontradaError,
    ParSaldoCuenta,
    ReporteCuadreSaldos,
    TOLERANCIA_CUADRE_MXN_DEFAULT,
    calcular_saldo_cuenta_periodo,
    cerrar_migracion,
    construir_reporte_cuadre,
    mapeos_migrados,
    verificar_cuadre_saldos,
)


def _par(mapeo_id, origen_id, destino_id, saldo_origen, saldo_destino):
    return ParSaldoCuenta(
        mapeo_id=mapeo_id,
        origen_cuenta_id=origen_id,
        destino_cuenta_id=destino_id,
        saldo_origen_periodo=Decimal(saldo_origen),
        saldo_destino_periodo=Decimal(saldo_destino),
    )


def _mapeo(origen_id, destino_id, estado=EstadoMapeoMigracion.APROBADO):
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen_id,
        destino_cuenta_id=destino_id,
        tipo_match=TipoMatchMigracion.EXACTO,
        score=100.0,
        estado=estado,
    )


# ---------------------------------------------------------------------------
# 1) Función pura -- sin BD
# ---------------------------------------------------------------------------

class TestConstruirReporteCuadre:
    def test_cuenta_cuadrada_exacta_no_es_discrepancia(self):
        pares = [_par("m1", "o1", "d1", "1000.00", "1000.00")]
        reporte = construir_reporte_cuadre(pares, "2026-01", "2026-01")
        assert reporte.discrepancias == []
        assert len(reporte.cuentas_cuadradas) == 1
        assert reporte.cierre_permitido is True

    def test_diferencia_igual_a_la_tolerancia_si_cuadra(self):
        """Criterio literal: `<= 0.01` cuadra. Una diferencia IGUAL a la
        tolerancia no es una discrepancia."""
        pares = [_par("m1", "o1", "d1", "1000.00", "1000.01")]
        reporte = construir_reporte_cuadre(
            pares, "2026-01", "2026-01", tolerancia=Decimal("0.01")
        )
        assert reporte.discrepancias == []
        assert len(reporte.cuentas_cuadradas) == 1
        assert reporte.cuentas_cuadradas[0].diferencia == Decimal("0.01")
        assert reporte.cierre_permitido is True

    def test_diferencia_mayor_a_la_tolerancia_bloquea(self):
        """Criterio literal: una diferencia MAYOR a 0.01 debe bloquear."""
        pares = [_par("m1", "o1", "d1", "1000.00", "1000.02")]
        reporte = construir_reporte_cuadre(
            pares, "2026-01", "2026-01", tolerancia=Decimal("0.01")
        )
        assert len(reporte.discrepancias) == 1
        assert reporte.cuentas_cuadradas == []
        assert reporte.discrepancias[0].diferencia == Decimal("0.02")
        assert reporte.cierre_permitido is False

    def test_reporte_mixto_incluye_cuadradas_y_discrepancias(self):
        pares = [
            _par("m1", "o1", "d1", "500.00", "500.00"),   # cuadra
            _par("m2", "o2", "d2", "300.00", "310.00"),   # no cuadra
            _par("m3", "o3", "d3", "10.00", "10.01"),     # cuadra (límite)
        ]
        reporte = construir_reporte_cuadre(pares, "2026-01", "2026-01")
        assert len(reporte.cuentas_cuadradas) == 2
        assert len(reporte.discrepancias) == 1
        assert reporte.discrepancias[0].mapeo_id == "m2"
        assert reporte.cuentas_verificadas == 3
        assert reporte.cierre_permitido is False

    def test_mapeos_sin_destino_bloquea_aunque_los_saldos_cuadren(self):
        pares = [_par("m1", "o1", "d1", "100.00", "100.00")]
        reporte = construir_reporte_cuadre(
            pares, "2026-01", "2026-01", mapeos_sin_destino=["m-huerfano"]
        )
        assert reporte.discrepancias == []
        assert reporte.mapeos_sin_destino == ["m-huerfano"]
        assert reporte.cierre_permitido is False

    def test_cierre_vacio_sin_cuentas_verificadas_esta_permitido(self):
        reporte = construir_reporte_cuadre([], "2026-01", "2026-01")
        assert reporte.cuentas_verificadas == 0
        assert reporte.cierre_permitido is True

    def test_tolerancia_default_del_criterio_es_1_centavo(self):
        assert TOLERANCIA_CUADRE_MXN_DEFAULT == Decimal("0.01")

    def test_mapeos_migrados_filtra_pendiente_y_rechazado(self):
        mapeos = [
            _mapeo("o1", "d1", EstadoMapeoMigracion.APROBADO),
            _mapeo("o2", "d2", EstadoMapeoMigracion.EDITADO),
            _mapeo("o3", "d3", EstadoMapeoMigracion.PENDIENTE),
            _mapeo("o4", "d4", EstadoMapeoMigracion.RECHAZADO),
        ]
        migrados = mapeos_migrados(mapeos)
        assert {m.origen_cuenta_id for m in migrados} == {"o1", "o2"}


# ---------------------------------------------------------------------------
# 2) Integración -- PostgreSQL real
# ---------------------------------------------------------------------------

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


@pytest.fixture
def pg_db():
    """`Database()` real sobre PostgreSQL, limpia de datos previos de
    negocio (mismo patrón que
    `tests/features/migracion_catalogo/test_verificacion_conteo_polizas.py`)."""
    from b2b_ai.db.db import Database

    db = Database(PG_DSN)
    for t in ("asientos_contables", "balanzas_mensuales", "cuentas_contables",
              "tenants"):
        try:
            db.conn.execute(f"DELETE FROM {t}")
        except Exception:  # noqa: BLE001
            pass
    db.conn.commit()
    yield db
    db.close()


def _crear_cuenta(db, tenant_id, codigo, naturaleza="D", descripcion=None):
    """Crea la cuenta y devuelve su `cuenta_id` UUID real (REQ-MIG-001) --
    `upsert_cuenta_contable` devuelve el `id` bigint, no el `cuenta_id`
    UUID que usa `verificacion.py`, así que se relee explícitamente."""
    db.upsert_cuenta_contable(
        tenant_id, codigo, descripcion or f"Cuenta {codigo}", naturaleza=naturaleza
    )
    row = db.conn.execute(
        "SELECT cuenta_id FROM cuentas_contables WHERE tenant_id=? AND codigo=?",
        (tenant_id, codigo),
    ).fetchone()
    return str(row[0])


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
class TestCalcularSaldoCuentaPeriodoEnBD:
    def test_saldo_acreedora_credito_menos_debito(self, pg_db):
        tenant = pg_db.create_tenant("Saldo acreedora")
        pg_db.insert_asiento_contable(
            tenant, "2026-01-10", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1000.00")
        pg_db.insert_asiento_contable(
            tenant, "2026-01-20", cuenta_debito="401-001",
            cuenta_credito="102-001", monto="200.00")
        saldo = calcular_saldo_cuenta_periodo(
            pg_db.conn, tenant, "401-001", "A", "2026-01-01", "2026-01-31")
        # Acreedora: créditos (1000.00) - débitos (200.00) = 800.00
        assert saldo == Decimal("800.00")

    def test_saldo_deudora_debito_menos_credito(self, pg_db):
        tenant = pg_db.create_tenant("Saldo deudora")
        pg_db.insert_asiento_contable(
            tenant, "2026-01-10", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1000.00")
        pg_db.insert_asiento_contable(
            tenant, "2026-01-20", cuenta_debito="401-001",
            cuenta_credito="102-001", monto="200.00")
        saldo = calcular_saldo_cuenta_periodo(
            pg_db.conn, tenant, "102-001", "D", "2026-01-01", "2026-01-31")
        # Deudora: débitos (1000.00) - créditos (200.00) = 800.00
        assert saldo == Decimal("800.00")

    def test_asientos_fuera_del_periodo_no_cuentan(self, pg_db):
        tenant = pg_db.create_tenant("Fuera de periodo")
        pg_db.insert_asiento_contable(
            tenant, "2025-12-31", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="500.00")
        pg_db.insert_asiento_contable(
            tenant, "2026-02-01", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="700.00")
        saldo = calcular_saldo_cuenta_periodo(
            pg_db.conn, tenant, "102-001", "D", "2026-01-01", "2026-01-31")
        assert saldo == Decimal("0")


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
class TestVerificarCuadreSaldosEnBD:
    def test_cuenta_migrada_que_cuadra_permite_el_cierre(self, pg_db):
        origen = pg_db.create_tenant("Origen cuadra")
        destino = pg_db.create_tenant("Destino cuadra")
        origen_cuenta_id = _crear_cuenta(pg_db, origen, "102-001", "D")
        destino_cuenta_id = _crear_cuenta(pg_db, destino, "102-001", "D")

        pg_db.insert_asiento_contable(
            origen, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1500.00")
        pg_db.insert_asiento_contable(
            destino, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1500.00")

        mapeo = _mapeo(origen_cuenta_id, destino_cuenta_id)
        reporte = verificar_cuadre_saldos(
            pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")

        assert isinstance(reporte, ReporteCuadreSaldos)
        assert reporte.cierre_permitido is True
        assert len(reporte.cuentas_cuadradas) == 1
        assert reporte.discrepancias == []

        # cerrar_migracion no debe lanzar cuando cuadra.
        cerrar_migracion(pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")

    def test_cuenta_migrada_desbalanceada_bloquea_el_cierre(self, pg_db):
        origen = pg_db.create_tenant("Origen desbalanceado")
        destino = pg_db.create_tenant("Destino desbalanceado")
        origen_cuenta_id = _crear_cuenta(pg_db, origen, "102-001", "D")
        destino_cuenta_id = _crear_cuenta(pg_db, destino, "102-001", "D")

        pg_db.insert_asiento_contable(
            origen, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1500.00")
        # Destino con un monto real distinto -- diferencia de $50.00,
        # muy por encima de la tolerancia de $0.01.
        pg_db.insert_asiento_contable(
            destino, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1450.00")

        mapeo = _mapeo(origen_cuenta_id, destino_cuenta_id)
        reporte = verificar_cuadre_saldos(
            pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")

        assert reporte.cierre_permitido is False
        assert len(reporte.discrepancias) == 1
        assert reporte.discrepancias[0].diferencia == Decimal("50.00")

        with pytest.raises(CuadreSaldosNoPermiteCierreError) as exc_info:
            cerrar_migracion(pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")
        assert exc_info.value.reporte.cierre_permitido is False

    def test_mapeo_pendiente_no_se_verifica_ni_bloquea(self, pg_db):
        """Un mapeo `pendiente` (nunca migró ninguna cuenta, ADR-3) no
        debe verificarse -- ni siquiera si sus saldos reales no
        cuadrarían, porque esa cuenta nunca se movió."""
        origen = pg_db.create_tenant("Origen pendiente")
        destino = pg_db.create_tenant("Destino pendiente")
        origen_cuenta_id = _crear_cuenta(pg_db, origen, "102-001", "D")
        destino_cuenta_id = _crear_cuenta(pg_db, destino, "102-001", "D")

        pg_db.insert_asiento_contable(
            origen, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1000.00")
        pg_db.insert_asiento_contable(
            destino, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="1.00")

        mapeo_pendiente = _mapeo(
            origen_cuenta_id, destino_cuenta_id, EstadoMapeoMigracion.PENDIENTE)
        reporte = verificar_cuadre_saldos(
            pg_db.conn, [mapeo_pendiente], "2026-01-01", "2026-01-31")

        assert reporte.cuentas_verificadas == 0
        assert reporte.cierre_permitido is True

    def test_cuenta_inexistente_lanza_error_explicito_nunca_asume_saldo_cero(
        self, pg_db
    ):
        origen = pg_db.create_tenant("Origen huerfano")
        destino = pg_db.create_tenant("Destino huerfano")
        origen_cuenta_id = _crear_cuenta(pg_db, origen, "102-001", "D")
        # destino_cuenta_id apunta a un UUID que NUNCA se creó.
        import uuid as _uuid

        destino_inexistente = str(_uuid.uuid4())

        mapeo = _mapeo(origen_cuenta_id, destino_inexistente)
        with pytest.raises(CuentaContableNoEncontradaError):
            verificar_cuadre_saldos(
                pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")

    def test_verificacion_es_de_solo_lectura(self, pg_db):
        origen = pg_db.create_tenant("Origen solo lectura saldos")
        destino = pg_db.create_tenant("Destino solo lectura saldos")
        origen_cuenta_id = _crear_cuenta(pg_db, origen, "102-001", "D")
        destino_cuenta_id = _crear_cuenta(pg_db, destino, "102-001", "D")
        pg_db.insert_asiento_contable(
            origen, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="900.00")
        pg_db.insert_asiento_contable(
            destino, "2026-01-15", cuenta_debito="102-001",
            cuenta_credito="401-001", monto="800.00")
        mapeo = _mapeo(origen_cuenta_id, destino_cuenta_id)

        def _saldos_reales():
            return (
                calcular_saldo_cuenta_periodo(
                    pg_db.conn, origen, "102-001", "D", "2026-01-01", "2026-01-31"),
                calcular_saldo_cuenta_periodo(
                    pg_db.conn, destino, "102-001", "D", "2026-01-01", "2026-01-31"),
            )

        antes = _saldos_reales()
        with pytest.raises(CuadreSaldosNoPermiteCierreError):
            cerrar_migracion(pg_db.conn, [mapeo], "2026-01-01", "2026-01-31")
        despues = _saldos_reales()
        assert antes == despues == (Decimal("900.00"), Decimal("800.00"))
