# -*- coding: utf-8 -*-
"""Tests de `migracion_catalogo_audit_log` (REQ-MIG-016): log de
auditoría append-only para `MapeoMigracionCuenta`.

Cubre exactamente el criterio de aceptación del blueprint
(docs/BLUEPRINT-AGENTES-FISCALES.md):

  1. Fail-closed: un UPDATE o DELETE directo contra
     `migracion_catalogo_audit_log` (aunque venga de una conexión con
     los mismos privilegios que usa la app/las migraciones -- el
     escenario adversarial real de este repo, ver el docstring de
     `migrations/versions/0019_migracion_audit_log.py` sobre por qué
     un trigger y no GRANT/REVOKE) debe fallar, dejando la fila
     intacta.
  2. El flujo normal (`MigracionCatalogoService.aprobar/rechazar/editar`
     con `RegistroAuditoriaPostgres` inyectado,
     `repositorio_postgres.py`) sí inserta filas de auditoría
     correctamente, con quién/qué/cuándo/antes/después.

Sin mocks: Postgres real, mismo patrón que
`test_repositorio_mapeos_postgres.py` y el resto de la suite de este
módulo (`conftest.py::bd_temporal_factory`, migración real de Alembic a
`head` contra una base de test efímera).
"""
from __future__ import annotations

import psycopg
import pytest

from .conftest import _pg_available

from b2b_ai.features.migracion_catalogo.models import (
    EstadoMapeoMigracion,
    MapeoMigracionCuenta,
    TipoMatchMigracion,
)
from b2b_ai.features.migracion_catalogo.repositorio_postgres import (
    RegistroAuditoriaPostgres,
    RepositorioMapeosPostgres,
)
from b2b_ai.features.migracion_catalogo.service import MigracionCatalogoService

pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


@pytest.fixture
def db(bd_temporal_factory):
    dsn = bd_temporal_factory("audit_log")
    conn = psycopg.connect(dsn)
    yield dsn, conn
    conn.close()


def _mapeo_fuzzy(origen="ORIG-A", destino="DEST-A", score=72.5):
    return MapeoMigracionCuenta(
        origen_cuenta_id=origen,
        destino_cuenta_id=destino,
        tipo_match=TipoMatchMigracion.FUZZY,
        score=score,
        estado=EstadoMapeoMigracion.PENDIENTE,
        nota="match fuzzy de prueba",
    )


def _insertar_fila_directa(conn, id_="fila-1", migracion_id="mig-directo", mapeo_id="mapeo-1"):
    conn.execute(
        """
        INSERT INTO migracion_catalogo_audit_log (
            id, migracion_id, mapeo_id, accion, decidido_por, nota,
            valores_antes, valores_despues
        ) VALUES (%s, %s, %s, 'aprobar', 'contador_x', 'nota original',
                   '{"estado": "pendiente"}'::jsonb,
                   '{"estado": "aprobado"}'::jsonb)
        """,
        (id_, migracion_id, mapeo_id),
    )


# ---------------------------------------------------------------------------
# 1) Fail-closed: UPDATE/DELETE directo contra la tabla debe fallar.
# ---------------------------------------------------------------------------

def test_update_directo_falla(db):
    dsn, conn = db
    _insertar_fila_directa(conn, id_="fila-update")
    conn.commit()

    with pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute(
            "UPDATE migracion_catalogo_audit_log SET nota = 'manipulado' "
            "WHERE id = %s",
            ("fila-update",),
        )
    conn.rollback()

    # La fila sigue intacta -- el intento de UPDATE no dejó rastro.
    fila = conn.execute(
        "SELECT nota FROM migracion_catalogo_audit_log WHERE id = %s",
        ("fila-update",),
    ).fetchone()
    assert fila == ("nota original",)


def test_delete_directo_falla(db):
    dsn, conn = db
    _insertar_fila_directa(conn, id_="fila-delete")
    conn.commit()

    with pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute(
            "DELETE FROM migracion_catalogo_audit_log WHERE id = %s",
            ("fila-delete",),
        )
    conn.rollback()

    # La fila nunca se borró.
    fila = conn.execute(
        "SELECT id FROM migracion_catalogo_audit_log WHERE id = %s",
        ("fila-delete",),
    ).fetchone()
    assert fila == ("fila-delete",)


def test_update_y_delete_fallan_incluso_actualizando_otra_columna_cualquiera(db):
    """El trigger rechaza el UPDATE/DELETE completo, sin importar QUÉ
    columna se intente tocar -- no es una regla por columna."""
    dsn, conn = db
    _insertar_fila_directa(conn, id_="fila-cualquier-columna")
    conn.commit()

    with pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute(
            "UPDATE migracion_catalogo_audit_log SET decidido_por = 'otro' "
            "WHERE id = %s",
            ("fila-cualquier-columna",),
        )
    conn.rollback()


def test_mensaje_de_error_identifica_la_tabla_y_el_motivo(db):
    """El mensaje del trigger debe ser explícito (append-only,
    REQ-MIG-016) -- no un error genérico indistinguible de cualquier
    otro fallo de base de datos."""
    dsn, conn = db
    _insertar_fila_directa(conn, id_="fila-mensaje")
    conn.commit()

    with pytest.raises(psycopg.errors.RestrictViolation) as exc_info:
        conn.execute(
            "DELETE FROM migracion_catalogo_audit_log WHERE id = %s",
            ("fila-mensaje",),
        )
    conn.rollback()
    mensaje = str(exc_info.value)
    assert "append-only" in mensaje
    assert "migracion_catalogo_audit_log" in mensaje


# ---------------------------------------------------------------------------
# 2) Flujo normal: aprobar/rechazar/editar sí insertan filas de auditoría.
# ---------------------------------------------------------------------------

def test_aprobar_inserta_fila_de_auditoria_con_antes_y_despues(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-aprobar")
    auditoria = RegistroAuditoriaPostgres(conn, migracion_id="mig-aprobar")
    service = MigracionCatalogoService(repositorio=repo, auditoria=auditoria)

    mapeo = _mapeo_fuzzy()
    service.registrar(mapeo)
    service.aprobar(mapeo.id, decidido_por="contador_lider", nota="confirmado")

    filas = conn.execute(
        "SELECT migracion_id, mapeo_id, accion, decidido_por, nota, "
        "valores_antes, valores_despues FROM migracion_catalogo_audit_log "
        "WHERE mapeo_id = %s",
        (mapeo.id,),
    ).fetchall()
    assert len(filas) == 1
    (migracion_id, mapeo_id, accion, decidido_por, nota,
     valores_antes, valores_despues) = filas[0]
    assert migracion_id == "mig-aprobar"
    assert mapeo_id == mapeo.id
    assert accion == "aprobar"
    assert decidido_por == "contador_lider"
    assert nota == "confirmado"
    assert valores_antes["estado"] == "pendiente"
    assert valores_antes["aprobado_por"] is None
    assert valores_despues["estado"] == "aprobado"
    assert valores_despues["aprobado_por"] == "contador_lider"


def test_rechazar_inserta_fila_de_auditoria(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-rechazar")
    auditoria = RegistroAuditoriaPostgres(conn, migracion_id="mig-rechazar")
    service = MigracionCatalogoService(repositorio=repo, auditoria=auditoria)

    mapeo = _mapeo_fuzzy()
    service.registrar(mapeo)
    service.rechazar(mapeo.id, decidido_por="contador_lider", nota="no aplica")

    fila = conn.execute(
        "SELECT accion, decidido_por, nota, valores_despues "
        "FROM migracion_catalogo_audit_log WHERE mapeo_id = %s",
        (mapeo.id,),
    ).fetchone()
    accion, decidido_por, nota, valores_despues = fila
    assert accion == "rechazar"
    assert decidido_por == "contador_lider"
    assert nota == "no aplica"
    assert valores_despues["estado"] == "rechazado"


def test_editar_inserta_fila_de_auditoria(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-editar")
    auditoria = RegistroAuditoriaPostgres(conn, migracion_id="mig-editar")
    service = MigracionCatalogoService(repositorio=repo, auditoria=auditoria)

    mapeo = _mapeo_fuzzy(destino="DEST-VIEJO")
    service.registrar(mapeo)
    service.editar(
        mapeo.id,
        decidido_por="contador_lider",
        destino_cuenta_id="DEST-NUEVO",
        nota="corregido a mano",
    )

    fila = conn.execute(
        "SELECT accion, valores_antes, valores_despues "
        "FROM migracion_catalogo_audit_log WHERE mapeo_id = %s",
        (mapeo.id,),
    ).fetchone()
    accion, valores_antes, valores_despues = fila
    assert accion == "editar"
    assert valores_antes["destino_cuenta_id"] == "DEST-VIEJO"
    assert valores_despues["destino_cuenta_id"] == "DEST-NUEVO"
    assert valores_despues["estado"] == "editado"


def test_registrar_alta_inicial_no_genera_auditoria(db):
    """`registrar()` (alta inicial del motor de matching, sin decisión
    humana todavía) NO es una aprobación/rechazo/edición -- REQ-MIG-016
    solo pide auditar esas tres. Ver docstring de módulo de
    `service.py`."""
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-alta")
    auditoria = RegistroAuditoriaPostgres(conn, migracion_id="mig-alta")
    service = MigracionCatalogoService(repositorio=repo, auditoria=auditoria)

    mapeo = _mapeo_fuzzy()
    service.registrar(mapeo)

    filas = conn.execute(
        "SELECT id FROM migracion_catalogo_audit_log WHERE mapeo_id = %s",
        (mapeo.id,),
    ).fetchall()
    assert filas == []


def test_multiples_decisiones_en_migraciones_distintas_no_se_mezclan(db):
    dsn, conn = db
    repo_x = RepositorioMapeosPostgres(conn, migracion_id="empresa-x")
    audit_x = RegistroAuditoriaPostgres(conn, migracion_id="empresa-x")
    service_x = MigracionCatalogoService(repositorio=repo_x, auditoria=audit_x)

    repo_y = RepositorioMapeosPostgres(conn, migracion_id="empresa-y")
    audit_y = RegistroAuditoriaPostgres(conn, migracion_id="empresa-y")
    service_y = MigracionCatalogoService(repositorio=repo_y, auditoria=audit_y)

    m_x = _mapeo_fuzzy("ORIG-X", "DEST-X")
    m_y = _mapeo_fuzzy("ORIG-Y", "DEST-Y")
    service_x.registrar(m_x)
    service_y.registrar(m_y)
    service_x.aprobar(m_x.id, decidido_por="c1", nota="ok x")
    service_y.aprobar(m_y.id, decidido_por="c2", nota="ok y")

    filas_x = conn.execute(
        "SELECT mapeo_id FROM migracion_catalogo_audit_log "
        "WHERE migracion_id = 'empresa-x'"
    ).fetchall()
    filas_y = conn.execute(
        "SELECT mapeo_id FROM migracion_catalogo_audit_log "
        "WHERE migracion_id = 'empresa-y'"
    ).fetchall()
    assert [f[0] for f in filas_x] == [m_x.id]
    assert [f[0] for f in filas_y] == [m_y.id]


def test_auditoria_es_append_only_tambien_a_traves_del_flujo_normal(db):
    """Una vez que `service.aprobar()` escribió la fila de auditoría,
    intentar modificarla directamente (como si alguien quisiera alterar
    el rastro de una decisión ya tomada) debe seguir fallando -- la
    protección del trigger no depende de por dónde entró la fila."""
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-flujo-normal")
    auditoria = RegistroAuditoriaPostgres(conn, migracion_id="mig-flujo-normal")
    service = MigracionCatalogoService(repositorio=repo, auditoria=auditoria)

    mapeo = _mapeo_fuzzy()
    service.registrar(mapeo)
    service.aprobar(mapeo.id, decidido_por="contador_lider", nota="confirmado")

    fila_id = conn.execute(
        "SELECT id FROM migracion_catalogo_audit_log WHERE mapeo_id = %s",
        (mapeo.id,),
    ).fetchone()[0]

    with pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute(
            "UPDATE migracion_catalogo_audit_log SET decidido_por = 'atacante' "
            "WHERE id = %s",
            (fila_id,),
        )
    conn.rollback()

    decidido_por = conn.execute(
        "SELECT decidido_por FROM migracion_catalogo_audit_log WHERE id = %s",
        (fila_id,),
    ).fetchone()[0]
    assert decidido_por == "contador_lider"
