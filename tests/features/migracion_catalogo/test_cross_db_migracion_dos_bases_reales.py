# -*- coding: utf-8 -*-
"""Escenario real completo (REQ cross-db): dos bases de datos Postgres
físicamente distintas -- simulando el caso exacto del dueño del
proyecto (5 años de una empresa regularizados en 2 bases físicamente
distintas, 2020-2023 y 2024-2026) -- con catálogos PARCIALMENTE
distintos, migración de varias pólizas reales, y verificación de
integridad total en ambos lados al final.

Sin mocks: dos bases de PostgreSQL efímeras reales (fixture
`dos_bases_migradas`), cada una migrada con `alembic upgrade head`
real, cada una con su propia conexión `psycopg` real
(`ConexionesMigracion`). Las aserciones leen ambas bases directamente
por SQL -- nunca se asume el resultado de una función sin verificar el
estado real de ambas bases.
"""
from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from .conftest import _pg_available

from b2b_ai.features.migracion_catalogo.cross_db import (
    ConexionesMigracion,
    cargar_catalogo_destino,
    cargar_catalogo_origen,
    clasificar_catalogo_cross_db,
    migrar_lote_cross_db,
)
from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.service import MigracionCatalogoService

pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)

TENANT_ORIGEN = 1
TENANT_DESTINO = 1  # cada base es físicamente distinta: mismo tenant_id lógico, dos servidores/bases distintos.


def _sembrar_tenant(conn, tenant_id: int) -> None:
    with conn.transaction():
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (tenant_id, "empresa regularizada"),
        )


def _sembrar_cuenta(conn, tenant_id, codigo, descripcion, nivel=3, naturaleza="D", grupo="Activo"):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO cuentas_contables "
            "(tenant_id, codigo, descripcion, nivel, naturaleza, grupo) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, codigo, descripcion, nivel, naturaleza, grupo),
        )
        return cur.fetchone()[0]


def _sembrar_asiento(conn, tenant_id, fecha, cuenta_debito, cuenta_credito, monto, descripcion=""):
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO asientos_contables "
            "(tenant_id, fecha, cuenta_debito, cuenta_credito, monto, descripcion) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, fecha, cuenta_debito, cuenta_credito, str(monto), descripcion),
        )
        return str(cur.fetchone()[0])


@pytest.fixture
def escenario(dos_bases_migradas):
    """Arma el caso real completo: catálogo parcialmente distinto entre
    origen (2024-2026) y destino (2020-2023), y varias pólizas de
    origen listas para migrar."""
    origen_dsn, destino_dsn = dos_bases_migradas

    # `ConexionesMigracion` abre origen en modo read_only (por diseño --
    # ver su docstring), así que los datos de prueba de origen (que en
    # la vida real ya existirían de antes, esta migración nunca los
    # escribe) se siembran con conexiones de escritura normales,
    # aparte de las conexiones read_only que usa cada test.
    conn_siembra_origen = psycopg.connect(origen_dsn)
    conn_siembra_destino = psycopg.connect(destino_dsn)
    try:
        _sembrar_tenant(conn_siembra_origen, TENANT_ORIGEN)
        _sembrar_tenant(conn_siembra_destino, TENANT_DESTINO)

        # -- Catálogo ORIGEN (2024-2026) --------------------------------
        _sembrar_cuenta(conn_siembra_origen, TENANT_ORIGEN, "1000", "Bancos", naturaleza="D", grupo="Activo")
        _sembrar_cuenta(conn_siembra_origen, TENANT_ORIGEN, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
        # Alerta de riesgo: mismo código que en destino, nombre distinto.
        _sembrar_cuenta(conn_siembra_origen, TENANT_ORIGEN, "2000", "Proveedores Nacionales", naturaleza="A", grupo="Pasivo")
        # Cuenta nueva, sin ninguna correspondencia razonable en destino.
        _sembrar_cuenta(conn_siembra_origen, TENANT_ORIGEN, "9999", "Criptoactivos Digitales Nuevos", naturaleza="D", grupo="Activo")

        # -- Catálogo DESTINO (2020-2023) -- YA EXISTENTE, nunca se debe
        #    sobrescribir ni una sola subcuenta al correr la migración.
        _sembrar_cuenta(conn_siembra_destino, TENANT_DESTINO, "1000", "Bancos", naturaleza="D", grupo="Activo")
        _sembrar_cuenta(conn_siembra_destino, TENANT_DESTINO, "4000", "Ventas", naturaleza="A", grupo="Ingreso")
        _sembrar_cuenta(conn_siembra_destino, TENANT_DESTINO, "2000", "Proveedores", naturaleza="A", grupo="Pasivo")
        # Cuenta de destino que YA existía, sin relación con origen --
        # debe seguir intacta al final.
        _sembrar_cuenta(conn_siembra_destino, TENANT_DESTINO, "5000", "Gastos Generales Ya Contabilizados", naturaleza="D", grupo="Gasto")

        # -- Pólizas de ORIGEN a migrar -----------------------------------
        p1 = _sembrar_asiento(conn_siembra_origen, TENANT_ORIGEN, "2024-01-15", "1000", "4000", "1500.00", "Venta de contado")
        p2 = _sembrar_asiento(conn_siembra_origen, TENANT_ORIGEN, "2024-02-10", "1000", "2000", "300.00", "Pago a proveedor")
        # Esta póliza usa la cuenta 9999 (sin_match) -- debe bloquearse.
        p3 = _sembrar_asiento(conn_siembra_origen, TENANT_ORIGEN, "2024-03-01", "9999", "1000", "50.00", "Compra de cripto")
    finally:
        conn_siembra_origen.close()
        conn_siembra_destino.close()

    return {
        "origen_dsn": origen_dsn,
        "destino_dsn": destino_dsn,
        "polizas": {"p1": p1, "p2": p2, "p3": p3},
    }


def test_matching_lee_catalogo_real_de_ambas_bases_por_su_propia_conexion(escenario):
    with ConexionesMigracion(escenario["origen_dsn"], escenario["destino_dsn"]) as c:
        origen_cuentas = cargar_catalogo_origen(c.origen, TENANT_ORIGEN)
        destino_cuentas = cargar_catalogo_destino(c.destino, TENANT_DESTINO)

    assert {cta.codigo for cta in origen_cuentas} == {"1000", "4000", "2000", "9999"}
    assert {cta.codigo for cta in destino_cuentas} == {"1000", "4000", "2000", "5000"}
    # El id de destino es un UUID real de cuenta_id (REQ-MIG-001), no el código.
    for cta in destino_cuentas:
        assert cta.id != cta.codigo
        assert len(cta.id) == 36  # UUID con guiones


def test_clasificacion_cross_db_produce_exacto_alerta_y_sin_match(escenario):
    with ConexionesMigracion(escenario["origen_dsn"], escenario["destino_dsn"]) as c:
        mapeos = clasificar_catalogo_cross_db(
            c.origen, c.destino, TENANT_ORIGEN, TENANT_DESTINO
        )

    por_origen = {m.origen_cuenta_id: m for m in mapeos}
    assert len(mapeos) == 4

    # "1000 Bancos" y "4000 Ventas" son idénticos en ambas bases -> exacto, auto-aprobado.
    assert por_origen["1000"].tipo_match == TipoMatchMigracion.EXACTO
    assert por_origen["1000"].estado == EstadoMapeoMigracion.APROBADO
    assert por_origen["4000"].tipo_match == TipoMatchMigracion.EXACTO
    assert por_origen["4000"].estado == EstadoMapeoMigracion.APROBADO

    # "2000": mismo código, nombre distinto ("Proveedores Nacionales" vs
    # "Proveedores") -> alerta de riesgo, NUNCA auto-aprobado.
    assert por_origen["2000"].tipo_match == TipoMatchMigracion.ALERTA_RIESGO
    assert por_origen["2000"].estado == EstadoMapeoMigracion.PENDIENTE

    # "9999": no hay nada parecido en destino -> sin_match, sin destino inventado.
    assert por_origen["9999"].tipo_match == TipoMatchMigracion.SIN_MATCH
    assert por_origen["9999"].destino_cuenta_id is None
    assert por_origen["9999"].estado == EstadoMapeoMigracion.PENDIENTE


def test_migracion_completa_del_escenario_real_del_dueno(escenario):
    """El escenario completo: matching cross-db, aprobación humana del
    caso de alerta de riesgo (REQ-MIG-007), migración del lote completo
    de pólizas, y verificación de integridad total en ambos lados.

    A propósito, la migración corre dentro de un `with
    ConexionesMigracion(...)` que se CIERRA antes de verificar nada:
    todas las aserciones de este test leen con conexiones NUEVAS,
    abiertas después de cerrar las que hizo la migración -- así la
    prueba confirma persistencia REAL en Postgres (sobrevive al cierre
    de la conexión), no solo visibilidad dentro de la misma sesión que
    escribió (que también vería datos aún no confirmados de verdad)."""
    with ConexionesMigracion(escenario["origen_dsn"], escenario["destino_dsn"]) as c:
        mapeos = clasificar_catalogo_cross_db(
            c.origen, c.destino, TENANT_ORIGEN, TENANT_DESTINO
        )
        service = MigracionCatalogoService()
        for m in mapeos:
            service.registrar(m)

        # Un humano revisa y aprueba el caso de alerta de riesgo ("2000"):
        # confirma que "Proveedores Nacionales" (origen) SÍ corresponde a
        # "Proveedores" (destino) -- REQ-MIG-007, decisión explícita.
        mapeo_2000 = next(
            m for m in service.listar() if m.origen_cuenta_id == "2000"
        )
        service.aprobar(mapeo_2000.id, decidido_por="contador_lider")

        # "9999" (sin_match) se queda pendiente -- nadie decidió nada
        # todavía sobre esa cuenta nueva; la póliza p3 que la usa debe
        # bloquearse, no migrar con un destino inventado.
        mapeos_por_cuenta_origen = {
            m.origen_cuenta_id: m for m in service.listar()
        }

        resultados = migrar_lote_cross_db(
            c, TENANT_ORIGEN, TENANT_DESTINO, mapeos_por_cuenta_origen
        )

        # -- Resultado esperado por póliza --------------------------------
        assert resultados[escenario["polizas"]["p1"]].migrada is True
        assert resultados[escenario["polizas"]["p1"]].lineas_migradas == 2
        assert resultados[escenario["polizas"]["p2"]].migrada is True
        assert resultados[escenario["polizas"]["p2"]].lineas_migradas == 2
        assert resultados[escenario["polizas"]["p3"]].bloqueada is True
        assert resultados[escenario["polizas"]["p3"]].lineas_migradas == 0
        assert "9999" in resultados[escenario["polizas"]["p3"]].cuentas_sin_mapeo_aprobado

    # -- Conexiones de la migración YA CERRADAS -- todo lo que sigue lee
    # con conexiones nuevas, confirmando persistencia real. ------------
    conn_origen = psycopg.connect(escenario["origen_dsn"])
    conn_destino = psycopg.connect(escenario["destino_dsn"])
    try:
        # -- Integridad en DESTINO ----------------------------------------
        total_lineas = conn_destino.execute(
            "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id = %s",
            (TENANT_DESTINO,),
        ).fetchone()[0]
        assert total_lineas == 4  # 2 líneas x 2 pólizas migradas (p1, p2)

        bloqueadas = conn_destino.execute(
            "SELECT poliza_origen_id, cuentas_sin_mapeo FROM polizas_bloqueadas "
            "WHERE tenant_id = %s",
            (TENANT_DESTINO,),
        ).fetchall()
        assert len(bloqueadas) == 1
        assert bloqueadas[0][0] == escenario["polizas"]["p3"]

        # La cuenta "5000" de destino (ya existía, sin relación con
        # origen) sigue intacta -- ninguna subcuenta del catálogo
        # destino fue sobrescrita por la migración.
        fila_5000 = conn_destino.execute(
            "SELECT descripcion FROM cuentas_contables "
            "WHERE tenant_id = %s AND codigo = %s",
            (TENANT_DESTINO, "5000"),
        ).fetchone()
        assert fila_5000 == ("Gastos Generales Ya Contabilizados",)

        # Debe cuadrar: cada póliza migrada tiene debe==haber en destino.
        for poliza_id in (escenario["polizas"]["p1"], escenario["polizas"]["p2"]):
            filas = conn_destino.execute(
                "SELECT debe, haber FROM lineas_poliza_migradas "
                "WHERE tenant_id = %s AND poliza_origen_id = %s",
                (TENANT_DESTINO, poliza_id),
            ).fetchall()
            total_debe = sum(Decimal(f[0]) for f in filas)
            total_haber = sum(Decimal(f[1]) for f in filas)
            assert total_debe == total_haber

        # -- Integridad en ORIGEN: 0 filas modificadas -----------------
        cuentas_origen = conn_origen.execute(
            "SELECT codigo, descripcion FROM cuentas_contables "
            "WHERE tenant_id = %s ORDER BY codigo",
            (TENANT_ORIGEN,),
        ).fetchall()
        assert cuentas_origen == [
            ("1000", "Bancos"),
            ("2000", "Proveedores Nacionales"),
            ("4000", "Ventas"),
            ("9999", "Criptoactivos Digitales Nuevos"),
        ]
        count_asientos_origen = conn_origen.execute(
            "SELECT COUNT(*) FROM asientos_contables WHERE tenant_id = %s",
            (TENANT_ORIGEN,),
        ).fetchone()[0]
        assert count_asientos_origen == 3
    finally:
        conn_origen.close()
        conn_destino.close()
