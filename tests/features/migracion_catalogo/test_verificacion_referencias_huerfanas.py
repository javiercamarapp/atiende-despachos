# -*- coding: utf-8 -*-
"""
test_verificacion_referencias_huerfanas.py — REQ-MIG-015.

Criterio de aceptación exacto (docs/BLUEPRINT-AGENTES-FISCALES.md §3):

  "Verificación de integridad — referencias huérfanas: 0 líneas de
  póliza en destino deben apuntar a un `cuenta_id` inexistente en el
  catálogo destino; el chequeo corre como parte del cierre de
  migración y bloquea si `count(huerfanas) > 0`."

Nota honesta sobre el mecanismo real detrás de este requisito: la FK
activa `lineas_poliza_migradas.cuenta_destino_id ->
cuentas_contables(cuenta_id)` (migración `0013_polizas_bloqueadas`,
REQ-MIG-001/009) YA hace estructuralmente imposible insertar una línea
huérfana en operación normal -- Postgres rechaza el INSERT, y por
default también rechaza borrar una cuenta destino todavía referenciada.
Por eso el caso "SÍ hay huérfanas" de este test tiene que desactivar
deliberadamente esa FK (`ALTER TABLE ... DROP CONSTRAINT`) sobre una
base de pruebas efímera para poder construir el escenario -- exactamente
como podría ocurrir en una carga masiva externa que evite la FK, o si un
día ese constraint se relaja por error. Esto NO es una prueba con mock:
es SQL real contra PostgreSQL real, solo que se retira defensivamente la
barrera que en producción evita este caso, para poder probar la SEGUNDA
capa de defensa (esta verificación de aplicación) de forma aislada de la
primera (la FK).

Sin mocks: mismo patrón que
`tests/features/migracion_catalogo/test_verificacion_conteo_polizas.py`
(`Database()` real sobre PostgreSQL). Se skippea si no hay `B2B_DB_URL`
disponible.
"""
from __future__ import annotations

import os
import uuid as _uuid

import pytest

from b2b_ai.features.migracion_catalogo.verificacion import (
    ReferenciasHuerfanasNoPermiteCierreError,
    ReporteReferenciasHuerfanas,
    cerrar_verificacion_referencias_huerfanas,
    verificar_referencias_huerfanas_en_bd,
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


@pytest.fixture
def pg_db():
    """`Database()` real sobre PostgreSQL, limpia de datos previos de
    negocio (mismo patrón que las otras verificaciones de este módulo)."""
    from b2b_ai.db.db import Database

    db = Database(PG_DSN)
    for t in ("lineas_poliza_migradas", "polizas_bloqueadas",
              "asientos_contables", "balanzas_mensuales",
              "cuentas_contables", "tenants"):
        try:
            db.conn.execute(f"DELETE FROM {t}")
        except Exception:  # noqa: BLE001
            pass
    db.conn.commit()
    yield db
    db.close()


def _crear_cuenta(db, tenant_id, codigo):
    db.upsert_cuenta_contable(tenant_id, codigo, f"Cuenta {codigo}")
    row = db.conn.execute(
        "SELECT cuenta_id FROM cuentas_contables WHERE tenant_id=? AND codigo=?",
        (tenant_id, codigo),
    ).fetchone()
    return str(row[0])


def _restaurar_fk(conn):
    """Vuelve a dejar el esquema como en producción tras un test que
    desactivó deliberadamente la FK para construir un caso huérfano:
    primero limpia cualquier fila que violaría la constraint (si no,
    `ADD CONSTRAINT` fallaría al validar los datos existentes -- sería
    absurdo que restaurar la FK requiriera antes limpiar lo que ella
    misma prohíbe), luego la restaura idéntica a
    `migrations/versions/0013_polizas_bloqueadas.py`."""
    conn.execute(
        "DELETE FROM lineas_poliza_migradas WHERE cuenta_destino_id NOT IN "
        "(SELECT cuenta_id FROM cuentas_contables)"
    )
    conn.execute(
        "ALTER TABLE lineas_poliza_migradas "
        "ADD CONSTRAINT lineas_poliza_migradas_cuenta_destino_id_fkey "
        "FOREIGN KEY (cuenta_destino_id) "
        "REFERENCES cuentas_contables(cuenta_id)"
    )
    conn.commit()


def _insertar_linea_migrada(db, tenant_id, poliza_id, cuenta_destino_id,
                            cuenta_origen_id="ORIG-X"):
    db.conn.execute(
        "INSERT INTO lineas_poliza_migradas "
        "(tenant_id, poliza_origen_id, mapeo_id, cuenta_origen_id, "
        "cuenta_destino_id, debe, haber) VALUES (?,?,?,?,?,?,?)",
        (tenant_id, poliza_id, "mapeo-test", cuenta_origen_id,
         cuenta_destino_id, "100.00", "0.00"),
    )
    db.conn.commit()


def test_sin_lineas_migradas_no_hay_huerfanas_y_cierre_permitido(pg_db):
    tenant = pg_db.create_tenant("Sin líneas")
    reporte = verificar_referencias_huerfanas_en_bd(pg_db.conn, tenant)
    assert isinstance(reporte, ReporteReferenciasHuerfanas)
    assert reporte.count_huerfanas == 0
    assert reporte.cierre_permitido is True
    # No debe lanzar.
    cerrar_verificacion_referencias_huerfanas(pg_db.conn, tenant)


def test_linea_migrada_con_cuenta_destino_real_no_es_huerfana(pg_db):
    tenant = pg_db.create_tenant("Con línea válida")
    destino_id = _crear_cuenta(pg_db, tenant, "102-001")
    _insertar_linea_migrada(pg_db, tenant, "POL-1", destino_id)

    reporte = verificar_referencias_huerfanas_en_bd(pg_db.conn, tenant)
    assert reporte.count_huerfanas == 0
    assert reporte.cierre_permitido is True


def test_la_fk_activa_rechaza_insertar_una_linea_huerfana_directamente(pg_db):
    """Documenta y verifica la PRIMERA capa de defensa: con la FK activa
    (comportamiento por defecto, sin tocar el esquema), Postgres rechaza
    de raíz el INSERT de una línea con `cuenta_destino_id` inexistente --
    nunca llega a existir una fila huérfana que verificar."""
    import psycopg

    tenant = pg_db.create_tenant("FK activa rechaza")
    destino_inexistente = str(_uuid.uuid4())

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insertar_linea_migrada(pg_db, tenant, "POL-FK", destino_inexistente)
    pg_db.conn.rollback()


def test_huerfana_real_con_fk_desactivada_se_detecta_y_bloquea_el_cierre(pg_db):
    """Caso "SÍ hay huérfanas": se desactiva deliberadamente la FK sobre
    esta base de pruebas efímera (ver nota honesta arriba) para poder
    insertar una línea huérfana real y probar que la SEGUNDA capa de
    defensa (esta verificación de aplicación) la detecta y bloquea el
    cierre -- exactamente el criterio literal del requisito."""
    tenant = pg_db.create_tenant("Huérfana real")
    destino_valido = _crear_cuenta(pg_db, tenant, "102-001")
    destino_inexistente = str(_uuid.uuid4())

    pg_db.conn.execute(
        "ALTER TABLE lineas_poliza_migradas "
        "DROP CONSTRAINT lineas_poliza_migradas_cuenta_destino_id_fkey"
    )
    pg_db.conn.commit()
    try:
        _insertar_linea_migrada(pg_db, tenant, "POL-OK", destino_valido)
        _insertar_linea_migrada(
            pg_db, tenant, "POL-HUERFANA", destino_inexistente,
            cuenta_origen_id="ORIG-HUERFANA")

        reporte = verificar_referencias_huerfanas_en_bd(pg_db.conn, tenant)

        assert reporte.count_huerfanas == 1, (
            "debe detectar exactamente la línea huérfana, no la válida"
        )
        assert reporte.cierre_permitido is False
        huerfana = reporte.huerfanas[0]
        assert huerfana.poliza_origen_id == "POL-HUERFANA"
        assert huerfana.cuenta_destino_id == destino_inexistente

        with pytest.raises(ReferenciasHuerfanasNoPermiteCierreError) as exc:
            cerrar_verificacion_referencias_huerfanas(pg_db.conn, tenant)
        assert exc.value.reporte.count_huerfanas == 1
    finally:
        _restaurar_fk(pg_db.conn)


def test_no_mezcla_huerfanas_entre_tenants(pg_db):
    """La verificación es por tenant -- una huérfana de otro tenant
    nunca debe filtrarse ni ocultarse en el reporte del tenant correcto."""
    tenant_a = pg_db.create_tenant("Tenant A huérfanas")
    tenant_b = pg_db.create_tenant("Tenant B huérfanas")
    destino_a = _crear_cuenta(pg_db, tenant_a, "102-001")

    pg_db.conn.execute(
        "ALTER TABLE lineas_poliza_migradas "
        "DROP CONSTRAINT lineas_poliza_migradas_cuenta_destino_id_fkey"
    )
    pg_db.conn.commit()
    try:
        _insertar_linea_migrada(pg_db, tenant_a, "POL-A", destino_a)
        _insertar_linea_migrada(
            pg_db, tenant_b, "POL-B-HUERFANA", str(_uuid.uuid4()))

        reporte_a = verificar_referencias_huerfanas_en_bd(pg_db.conn, tenant_a)
        assert reporte_a.count_huerfanas == 0
        assert reporte_a.cierre_permitido is True

        reporte_b = verificar_referencias_huerfanas_en_bd(pg_db.conn, tenant_b)
        assert reporte_b.count_huerfanas == 1
        assert reporte_b.cierre_permitido is False
    finally:
        _restaurar_fk(pg_db.conn)


def test_verificacion_es_de_solo_lectura(pg_db):
    tenant = pg_db.create_tenant("Solo lectura huérfanas")
    destino_valido = _crear_cuenta(pg_db, tenant, "102-001")

    pg_db.conn.execute(
        "ALTER TABLE lineas_poliza_migradas "
        "DROP CONSTRAINT lineas_poliza_migradas_cuenta_destino_id_fkey"
    )
    pg_db.conn.commit()
    try:
        _insertar_linea_migrada(
            pg_db, tenant, "POL-RO-HUERFANA", str(_uuid.uuid4()))

        def _conteo_real():
            return pg_db.conn.execute(
                "SELECT COUNT(*) FROM lineas_poliza_migradas WHERE tenant_id=?",
                (tenant,),
            ).fetchone()[0]

        antes = _conteo_real()
        with pytest.raises(ReferenciasHuerfanasNoPermiteCierreError):
            cerrar_verificacion_referencias_huerfanas(pg_db.conn, tenant)
        despues = _conteo_real()
        assert antes == despues == 1
    finally:
        _restaurar_fk(pg_db.conn)
