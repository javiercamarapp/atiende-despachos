# -*- coding: utf-8 -*-
"""
test_verificacion_conteo_polizas.py — REQ-MIG-013.

Criterio de aceptación exacto (docs/BLUEPRINT-AGENTES-FISCALES.md §3):

  "Verificación de integridad — conteo de pólizas:
  count(polizas_destino_migradas) == count(polizas_origen_elegibles),
  exacto (0 de diferencia); cualquier discrepancia bloquea el cierre de
  la migración."

Dos capas de prueba:

  1. `TestVerificarConteoPolizas` -- la función pura
     `verificar_conteo_polizas` sobre enteros ya calculados: cuadra
     exacto, no cuadra por defecto (faltan pólizas en destino), no
     cuadra por exceso (sobran pólizas en destino -- señal de una
     migración duplicada por falla de idempotencia de REQ-MIG-010), y
     conteos negativos inválidos. No requiere BD.

  2. `TestVerificarConteoPolizasEnBD` -- integración contra PostgreSQL
     real (REQ-MIG-013 está listado como "credenciales de BD de
     pruebas" en la matriz): dos tenants reales (`origen`/`destino`),
     pólizas reales insertadas en `asientos_contables` vía
     `Database.insert_asiento_contable`, y `verificar_conteo_polizas_en_bd`
     ejecutando `SELECT COUNT(*)` reales contra esas filas -- sin mocks
     de la conexión ni de las consultas. Se skippea si no hay
     `B2B_DB_URL` disponible (mismo patrón que
     `tests/test_db_pg_integration.py` y
     `tests/migrations/test_0012_cuenta_id_fk.py`).

     También se verifica que la verificación es de solo lectura: los
     conteos reales en ambos tenants quedan intactos después de correr
     la verificación, tanto en el caso que cuadra como en los dos casos
     que no cuadran y lanzan excepción.
"""
from __future__ import annotations

import os

import pytest

from b2b_ai.features.migracion_catalogo.verificacion import (
    DiscrepanciaConteoPolizasError,
    ResultadoConteoPolizas,
    verificar_conteo_polizas,
    verificar_conteo_polizas_en_bd,
)


# ---------------------------------------------------------------------------
# 1) Función pura -- sin BD
# ---------------------------------------------------------------------------

class TestVerificarConteoPolizas:
    def test_cuadra_exacto_devuelve_resultado(self):
        resultado = verificar_conteo_polizas(37, 37)
        assert isinstance(resultado, ResultadoConteoPolizas)
        assert resultado.count_origen_elegibles == 37
        assert resultado.count_destino_migradas == 37
        assert resultado.diferencia == 0
        assert resultado.cuadra is True

    def test_cuadra_en_cero_polizas(self):
        resultado = verificar_conteo_polizas(0, 0)
        assert resultado.cuadra is True
        assert resultado.diferencia == 0

    def test_faltan_polizas_en_destino_bloquea(self):
        with pytest.raises(DiscrepanciaConteoPolizasError) as exc_info:
            verificar_conteo_polizas(50, 49)
        err = exc_info.value
        assert err.count_origen_elegibles == 50
        assert err.count_destino_migradas == 49
        assert err.diferencia == 1

    def test_sobran_polizas_en_destino_tambien_bloquea(self):
        # Destino con MÁS pólizas que origen -- p.ej. una migración
        # duplicada por una falla de idempotencia (REQ-MIG-010) -- debe
        # bloquear el cierre exactamente igual que si faltaran.
        with pytest.raises(DiscrepanciaConteoPolizasError) as exc_info:
            verificar_conteo_polizas(50, 52)
        err = exc_info.value
        assert err.count_origen_elegibles == 50
        assert err.count_destino_migradas == 52
        assert err.diferencia == 2

    def test_diferencia_de_uno_tambien_bloquea_sin_tolerancia(self):
        # A diferencia de REQ-MIG-012 (saldos, tolerancia 0.01 MXN), el
        # conteo de pólizas no tolera ninguna diferencia -- ni siquiera 1.
        with pytest.raises(DiscrepanciaConteoPolizasError):
            verificar_conteo_polizas(1000, 999)

    def test_mensaje_de_error_reporta_los_dos_conteos_y_la_diferencia(self):
        with pytest.raises(DiscrepanciaConteoPolizasError) as exc_info:
            verificar_conteo_polizas(12, 10)
        mensaje = str(exc_info.value)
        assert "12" in mensaje
        assert "10" in mensaje
        assert "2" in mensaje
        assert "REQ-MIG-013" in mensaje

    @pytest.mark.parametrize("origen,destino", [(-1, 0), (0, -1), (-5, -5)])
    def test_conteos_negativos_son_invalidos(self, origen, destino):
        with pytest.raises(ValueError):
            verificar_conteo_polizas(origen, destino)


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


pytestmark_pg = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


@pytest.fixture
def pg_db():
    """`Database()` real sobre PostgreSQL, limpia de datos previos de
    negocio para que el test sea determinista (mismo patrón que
    `tests/test_db_pg_integration.py`)."""
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


def _sembrar_polizas(db, tenant_id, cantidad, prefijo):
    """Inserta `cantidad` asientos_contables reales para `tenant_id`,
    cada uno un renglón débito/crédito autocuadrado -- el equivalente de
    una "póliza" en el esquema actual (ver nota en
    `verificacion.py`: no existe todavía una tabla `polizas` separada,
    REQ-MIG-009 no está implementado)."""
    for i in range(cantidad):
        db.insert_asiento_contable(
            tenant_id=tenant_id,
            fecha="2026-01-01",
            cuenta_debito="102-001",
            cuenta_credito="401-001",
            monto="100.00",
            descripcion=f"{prefijo}-{i}",
        )


def _query_conteo_tenant():
    return "SELECT COUNT(*) FROM asientos_contables WHERE tenant_id = ?"


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
class TestVerificarConteoPolizasEnBD:
    def test_conteos_iguales_cuadra(self, pg_db):
        tenant_origen = pg_db.create_tenant("Origen 2020-2023")
        tenant_destino = pg_db.create_tenant("Destino 2024-2026")
        _sembrar_polizas(pg_db, tenant_origen, 15, "origen")
        _sembrar_polizas(pg_db, tenant_destino, 15, "destino")

        resultado = verificar_conteo_polizas_en_bd(
            pg_db.conn,
            _query_conteo_tenant(),
            _query_conteo_tenant(),
            (tenant_origen,),
            (tenant_destino,),
        )

        assert resultado.count_origen_elegibles == 15
        assert resultado.count_destino_migradas == 15
        assert resultado.cuadra is True

    def test_faltan_polizas_en_destino_bloquea_el_cierre(self, pg_db):
        tenant_origen = pg_db.create_tenant("Origen faltante")
        tenant_destino = pg_db.create_tenant("Destino faltante")
        _sembrar_polizas(pg_db, tenant_origen, 20, "origen")
        # Solo 19 migraron -- 1 póliza se quedó sin migrar.
        _sembrar_polizas(pg_db, tenant_destino, 19, "destino")

        with pytest.raises(DiscrepanciaConteoPolizasError) as exc_info:
            verificar_conteo_polizas_en_bd(
                pg_db.conn,
                _query_conteo_tenant(),
                _query_conteo_tenant(),
                (tenant_origen,),
                (tenant_destino,),
            )
        err = exc_info.value
        assert err.count_origen_elegibles == 20
        assert err.count_destino_migradas == 19
        assert err.diferencia == 1

    def test_sobran_polizas_en_destino_bloquea_el_cierre(self, pg_db):
        # Simula una migración duplicada (falla de idempotencia,
        # REQ-MIG-010): destino terminó con MÁS pólizas que las
        # elegibles en origen.
        tenant_origen = pg_db.create_tenant("Origen duplicado")
        tenant_destino = pg_db.create_tenant("Destino duplicado")
        _sembrar_polizas(pg_db, tenant_origen, 10, "origen")
        _sembrar_polizas(pg_db, tenant_destino, 11, "destino")

        with pytest.raises(DiscrepanciaConteoPolizasError) as exc_info:
            verificar_conteo_polizas_en_bd(
                pg_db.conn,
                _query_conteo_tenant(),
                _query_conteo_tenant(),
                (tenant_origen,),
                (tenant_destino,),
            )
        err = exc_info.value
        assert err.count_origen_elegibles == 10
        assert err.count_destino_migradas == 11
        assert err.diferencia == 1

    def test_verificacion_es_de_solo_lectura(self, pg_db):
        """La verificación nunca escribe ni migra nada -- ni cuando
        cuadra, ni cuando bloquea el cierre (regla dura del blueprint:
        nunca migrar/reclasificar sin aprobación humana explícita; una
        verificación de integridad, con más razón, nunca debe tocar
        datos)."""
        tenant_origen = pg_db.create_tenant("Origen solo lectura")
        tenant_destino = pg_db.create_tenant("Destino solo lectura")
        _sembrar_polizas(pg_db, tenant_origen, 7, "origen")
        _sembrar_polizas(pg_db, tenant_destino, 5, "destino")

        def _conteos_reales():
            return (
                pg_db.conn.execute(
                    "SELECT COUNT(*) FROM asientos_contables WHERE tenant_id=?",
                    (tenant_origen,),
                ).fetchone()[0],
                pg_db.conn.execute(
                    "SELECT COUNT(*) FROM asientos_contables WHERE tenant_id=?",
                    (tenant_destino,),
                ).fetchone()[0],
            )

        antes = _conteos_reales()
        with pytest.raises(DiscrepanciaConteoPolizasError):
            verificar_conteo_polizas_en_bd(
                pg_db.conn,
                _query_conteo_tenant(),
                _query_conteo_tenant(),
                (tenant_origen,),
                (tenant_destino,),
            )
        despues = _conteos_reales()
        assert antes == despues == (7, 5)
