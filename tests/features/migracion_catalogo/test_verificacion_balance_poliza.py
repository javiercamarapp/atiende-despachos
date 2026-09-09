# -*- coding: utf-8 -*-
"""Pruebas de REQ-MIG-014 — balance por póliza (verificacion.py).

Criterio (docs/BLUEPRINT-AGENTES-FISCALES.md §3): el 100% de las
pólizas migradas a destino debe cumplir `sum(debe) == sum(haber)` con
tolerancia `0.00` -- a diferencia de REQ-MIG-012 (cuadre de saldos por
cuenta), que sí tolera 0.01.

Dos capas de prueba, sin mocks de la lógica bajo prueba en ninguna:

  1. `calcular_balance_polizas` (pura, en memoria) -- todos los casos
     de negocio: pólizas balanceadas, desbalanceadas por 0.01 exacto
     (el límite que REQ-MIG-014 NO tolera, a propósito, para probar
     que es más estricto que REQ-MIG-012), pólizas multilínea, y el
     invariante de que `Decimal` nunca pasa por `float` (0.1+0.2).
  2. `verificar_balance_polizas_en_bd` contra un PostgreSQL real
     (columnas NUMERIC reales, no un dict de Python) -- requiere
     `B2B_DB_URL`; se skippea si no hay Postgres disponible, igual que
     el resto de las pruebas de integración del repo
     (`tests/migrations/test_0012_cuenta_id_fk.py`).
"""
import os
import uuid
from decimal import Decimal

import pytest

from b2b_ai.features.migracion_catalogo.verificacion import (
    BalancePolizaDesbalanceadaError,
    LineaPolizaMigrada,
    TOLERANCIA_BALANCE_POLIZA,
    calcular_balance_polizas,
    cerrar_verificacion_balance_polizas,
    verificar_balance_polizas_en_bd,
)


# ---------------------------------------------------------------------------
# 1) calcular_balance_polizas -- pura, en memoria
# ---------------------------------------------------------------------------

def test_tolerancia_es_exactamente_cero_no_un_centavo():
    """REQ-MIG-014 es explícito: tolerancia 0.00, no 0.01 (a diferencia
    de REQ-MIG-012). Esta constante es el contrato del criterio."""
    assert TOLERANCIA_BALANCE_POLIZA == Decimal("0")


def test_poliza_balanceada_simple_no_es_discrepancia():
    lineas = [
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("100.00"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("100.00")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.total_polizas == 1
    assert reporte.discrepancias == []
    assert reporte.cuadra is True
    assert reporte.polizas_ok == 1


def test_poliza_multilinea_balanceada_no_es_discrepancia():
    """Varias líneas de debe y varias de haber que sí suman igual --
    el caso real de una póliza con más de dos movimientos."""
    lineas = [
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("60.00"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("40.00"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("70.00")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("30.00")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.cuadra is True
    assert reporte.total_polizas == 1


def test_diferencia_de_un_centavo_exacto_SI_es_discrepancia():
    """El caso límite explícito del criterio: 0.01 de diferencia NO se
    tolera aquí (a diferencia de REQ-MIG-012, que sí tolera <=0.01).
    Si este test alguna vez pasara con tolerancia relajada a 0.01,
    estaría probando el requisito equivocado."""
    lineas = [
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("100.01"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("100.00")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.cuadra is False
    assert reporte.total_polizas == 1
    assert len(reporte.discrepancias) == 1
    disc = reporte.discrepancias[0]
    assert disc.poliza_id == "p1"
    assert disc.suma_debe == Decimal("100.01")
    assert disc.suma_haber == Decimal("100.00")
    assert disc.diferencia == Decimal("0.01")


def test_diferencia_minima_menor_a_un_centavo_tambien_es_discrepancia():
    """Tolerancia 0 significa CERO, no "redondeado a centavos": una
    diferencia de una fracción de centavo también debe bloquear."""
    lineas = [
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("100.001"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("100.000")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.cuadra is False
    assert reporte.discrepancias[0].diferencia == Decimal("0.001")


def test_multiples_polizas_reporta_solo_las_que_no_cuadran():
    lineas = [
        # p1: balanceada
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("50.00"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("50.00")),
        # p2: desbalanceada
        LineaPolizaMigrada(poliza_id="p2", debe=Decimal("30.00"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p2", debe=Decimal("0"), haber=Decimal("29.50")),
        # p3: balanceada
        LineaPolizaMigrada(poliza_id="p3", debe=Decimal("10.00"), haber=Decimal("10.00")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.total_polizas == 3
    assert reporte.polizas_ok == 2
    assert [d.poliza_id for d in reporte.discrepancias] == ["p2"]
    assert reporte.discrepancias[0].diferencia == Decimal("0.50")


def test_conjunto_vacio_cuadra_vacuamente():
    reporte = calcular_balance_polizas([])
    assert reporte.total_polizas == 0
    assert reporte.cuadra is True
    assert reporte.discrepancias == []


def test_decimal_nunca_pasa_por_float_0_1_mas_0_2():
    """El caso clásico de error de redondeo binario: 0.1 + 0.2 != 0.3
    en float, pero SÍ debe dar exactamente 0.3 en Decimal. Si
    calcular_balance_polizas convirtiera a float en algún punto, esta
    póliza (que en origen SÍ está balanceada) se reportaría como
    discrepancia por error, un falso positivo con tolerancia 0."""
    lineas = [
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0.1"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0.2"), haber=Decimal("0")),
        LineaPolizaMigrada(poliza_id="p1", debe=Decimal("0"), haber=Decimal("0.3")),
    ]
    reporte = calcular_balance_polizas(lineas)
    assert reporte.cuadra is True, (
        "falso positivo: 0.1 + 0.2 debe dar exactamente 0.3 en Decimal"
    )


def test_100_polizas_balanceadas_cuadran_al_100_por_ciento():
    """Literal del criterio: "el 100% de las pólizas migradas"."""
    lineas = []
    for i in range(100):
        pid = f"p{i}"
        monto = Decimal(i) + Decimal("1.23")
        lineas.append(LineaPolizaMigrada(poliza_id=pid, debe=monto, haber=Decimal("0")))
        lineas.append(LineaPolizaMigrada(poliza_id=pid, debe=Decimal("0"), haber=monto))
    reporte = calcular_balance_polizas(lineas)
    assert reporte.total_polizas == 100
    assert reporte.cuadra is True
    assert reporte.polizas_ok == 100


def test_una_sola_poliza_desbalanceada_entre_muchas_rompe_el_100_por_ciento():
    lineas = []
    for i in range(50):
        pid = f"p{i}"
        monto = Decimal("10.00")
        lineas.append(LineaPolizaMigrada(poliza_id=pid, debe=monto, haber=Decimal("0")))
        lineas.append(LineaPolizaMigrada(poliza_id=pid, debe=Decimal("0"), haber=monto))
    # Rompe la última a propósito.
    lineas.append(
        LineaPolizaMigrada(poliza_id="p49", debe=Decimal("0.01"), haber=Decimal("0"))
    )
    reporte = calcular_balance_polizas(lineas)
    assert reporte.total_polizas == 50
    assert reporte.cuadra is False
    assert reporte.polizas_ok == 49
    assert [d.poliza_id for d in reporte.discrepancias] == ["p49"]


# ---------------------------------------------------------------------------
# cerrar_verificacion_balance_polizas -- guardia de cierre
# ---------------------------------------------------------------------------

def test_cerrar_verificacion_devuelve_el_reporte_si_cuadra():
    reporte = calcular_balance_polizas(
        [
            LineaPolizaMigrada(poliza_id="p1", debe=Decimal("5"), haber=Decimal("5")),
        ]
    )
    assert cerrar_verificacion_balance_polizas(reporte) is reporte


def test_cerrar_verificacion_bloquea_si_no_cuadra_con_reporte_adjunto():
    reporte = calcular_balance_polizas(
        [
            LineaPolizaMigrada(poliza_id="p1", debe=Decimal("5.00"), haber=Decimal("4.00")),
        ]
    )
    with pytest.raises(BalancePolizaDesbalanceadaError) as exc_info:
        cerrar_verificacion_balance_polizas(reporte)
    err = exc_info.value
    assert err.reporte is reporte
    assert "p1" in str(err)
    assert "REQ-MIG-014" in str(err)


# ---------------------------------------------------------------------------
# 2) verificar_balance_polizas_en_bd -- integración contra Postgres real
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


def _split_dsn(dsn):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado para crear base de test")


@pytest.fixture
def pg_lineas_migradas():
    """Base de Postgres escratch (creada y dropeada por test, igual que
    tests/migrations/test_0012_cuenta_id_fk.py) con una tabla mínima de
    líneas de póliza migrada -- NUMERIC(14,2) real, no floats de
    Python -- para probar `verificar_balance_polizas_en_bd` contra un
    driver y un tipo de columna genuinos."""
    import psycopg

    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_pg_reqmig014_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(server_dsn, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        admin.close()

    dsn = f"{server_dsn}/{dbname}"
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute(
        """
        CREATE TABLE lineas_poliza_migrada_test (
            id SERIAL PRIMARY KEY,
            poliza_id TEXT NOT NULL,
            cuenta_id UUID,
            debe NUMERIC(14,2) NOT NULL DEFAULT 0,
            haber NUMERIC(14,2) NOT NULL DEFAULT 0
        )
        """
    )
    try:
        yield conn
    finally:
        conn.close()
        admin = psycopg.connect(server_dsn, autocommit=True)
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        finally:
            admin.close()


_QUERY = (
    "SELECT poliza_id, debe, haber FROM lineas_poliza_migrada_test "
    "ORDER BY id"
)


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
def test_bd_polizas_balanceadas_reales_cuadran(pg_lineas_migradas):
    conn = pg_lineas_migradas
    conn.execute(
        "INSERT INTO lineas_poliza_migrada_test (poliza_id, debe, haber) VALUES "
        "('p1', 100.00, 0), ('p1', 0, 100.00), "
        "('p2', 50.25, 0), ('p2', 0, 50.25)"
    )
    reporte = verificar_balance_polizas_en_bd(conn, _QUERY)
    assert reporte.total_polizas == 2
    assert reporte.cuadra is True


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
def test_bd_una_poliza_desbalanceada_por_un_centavo_bloquea(pg_lineas_migradas):
    """Prueba de extremo a extremo del criterio contra un NUMERIC(14,2)
    real de Postgres (no un Decimal fabricado a mano en Python): una
    diferencia de un centavo debe detectarse y bloquear el cierre."""
    conn = pg_lineas_migradas
    conn.execute(
        "INSERT INTO lineas_poliza_migrada_test (poliza_id, debe, haber) VALUES "
        "('p1', 100.00, 0), ('p1', 0, 100.00), "  # balanceada
        "('p2', 200.01, 0), ('p2', 0, 200.00)"  # desbalanceada por 0.01
    )
    reporte = verificar_balance_polizas_en_bd(conn, _QUERY)
    assert reporte.total_polizas == 2
    assert reporte.cuadra is False
    assert [d.poliza_id for d in reporte.discrepancias] == ["p2"]
    assert reporte.discrepancias[0].diferencia == Decimal("0.01")

    with pytest.raises(BalancePolizaDesbalanceadaError):
        cerrar_verificacion_balance_polizas(reporte)


@pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")
def test_bd_sin_lineas_cuadra_vacuamente(pg_lineas_migradas):
    conn = pg_lineas_migradas
    reporte = verificar_balance_polizas_en_bd(conn, _QUERY)
    assert reporte.total_polizas == 0
    assert reporte.cuadra is True
