# -*- coding: utf-8 -*-
"""Tests de `repositorio_postgres.RepositorioMapeosPostgres` (REQ-MIG-016):
persistencia real en Postgres para `MapeoMigracionCuenta`, que hasta
ahora solo vivía en memoria (`MigracionCatalogoService`'s dict inyectable).

Cubre:
  - Interfaz de `dict` (contrato que `MigracionCatalogoService` ya
    exige) respaldada por SQL real.
  - `MigracionCatalogoService(repositorio=RepositorioMapeosPostgres(...))`
    se comporta IDÉNTICO a `MigracionCatalogoService()` -- mismas
    guardias de REQ-MIG-007/008 -- sin ningún cambio en `service.py`.
  - Durabilidad real: el estado sobrevive a que el proceso "se
    reinicie" (conexión nueva + instancia nueva de
    `MigracionCatalogoService` con el mismo `migracion_id`) -- el
    escenario que motiva REQ-MIG-016 (una migración larga, cientos de
    pólizas, no debe perder las aprobaciones humanas ya hechas si el
    proceso se interrumpe a medias).
  - Aislamiento por `migracion_id`: dos migraciones distintas nunca
    comparten mapeos aunque usen la misma tabla física.

Sin mocks: Postgres real (una sola base basta aquí -- esta tabla vive
del lado de la aplicación, no es "origen" ni "destino" de una
migración cross-database concreta).
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
    RepositorioMapeosPostgres,
)
from b2b_ai.features.migracion_catalogo.service import (
    DivisionUnoANoAutomaticaError,
    EstrategiaConciliacionRequeridaError,
    MigracionCatalogoService,
    TransicionEstadoInvalidaError,
)

pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


@pytest.fixture
def db(bd_temporal_factory):
    dsn = bd_temporal_factory("repo_mapeos")
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


# ---------------------------------------------------------------------------
# Interfaz de dict respaldada por SQL real.
# ---------------------------------------------------------------------------

def test_setitem_getitem_persisten_en_postgres(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-1")
    mapeo = _mapeo_fuzzy()

    repo[mapeo.id] = mapeo
    recuperado = repo[mapeo.id]

    assert recuperado == mapeo
    fila = conn.execute(
        "SELECT origen_cuenta_id, destino_cuenta_id, tipo_match, estado "
        "FROM mapeos_migracion_catalogo WHERE id = %s",
        (mapeo.id,),
    ).fetchone()
    assert fila == ("ORIG-A", "DEST-A", "fuzzy", "pendiente")


def test_setitem_con_clave_distinta_de_mapeo_id_lanza_value_error(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-1")
    mapeo = _mapeo_fuzzy()
    with pytest.raises(ValueError):
        repo["otra-clave-cualquiera"] = mapeo


def test_getitem_de_id_inexistente_lanza_keyerror(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-1")
    with pytest.raises(KeyError):
        repo["no-existe"]


def test_get_devuelve_none_si_no_existe(db):
    """`.get()` (heredado de MutableMapping) es exactamente lo que usa
    `MigracionCatalogoService` internamente en algunos caminos -- debe
    comportarse igual que sobre un dict vacío."""
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-1")
    assert repo.get("no-existe") is None


def test_values_y_len_reflejan_solo_los_mapeos_de_este_migracion_id(db):
    dsn, conn = db
    repo_a = RepositorioMapeosPostgres(conn, migracion_id="mig-a")
    repo_b = RepositorioMapeosPostgres(conn, migracion_id="mig-b")

    m1 = _mapeo_fuzzy("O1", "D1")
    m2 = _mapeo_fuzzy("O2", "D2")
    m3 = _mapeo_fuzzy("O3", "D3")
    repo_a[m1.id] = m1
    repo_a[m2.id] = m2
    repo_b[m3.id] = m3

    assert len(repo_a) == 2
    assert len(repo_b) == 1
    assert {m.origen_cuenta_id for m in repo_a.values()} == {"O1", "O2"}
    assert {m.origen_cuenta_id for m in repo_b.values()} == {"O3"}


def test_migracion_id_vacio_lanza_value_error(db):
    dsn, conn = db
    with pytest.raises(ValueError):
        RepositorioMapeosPostgres(conn, migracion_id="")
    with pytest.raises(ValueError):
        RepositorioMapeosPostgres(conn, migracion_id="   ")


def test_upsert_actualiza_en_vez_de_duplicar(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-1")
    mapeo = _mapeo_fuzzy()
    repo[mapeo.id] = mapeo

    editado = mapeo.model_copy(update={"estado": EstadoMapeoMigracion.APROBADO, "aprobado_por": "x"})
    repo[editado.id] = editado

    assert len(repo) == 1
    assert repo[mapeo.id].estado == EstadoMapeoMigracion.APROBADO


# ---------------------------------------------------------------------------
# MigracionCatalogoService funciona IDÉNTICO con este repositorio --
# service.py no cambia nada.
# ---------------------------------------------------------------------------

def test_service_con_repositorio_postgres_aprobar_funciona_igual_que_en_memoria(db):
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-servicio")
    service = MigracionCatalogoService(repositorio=repo)

    mapeo = _mapeo_fuzzy()
    service.registrar(mapeo)

    aprobado = service.aprobar(mapeo.id, decidido_por="contador_lider", nota="confirmado")
    assert aprobado.estado == EstadoMapeoMigracion.APROBADO
    assert aprobado.aprobado_por == "contador_lider"

    # La guardia de REQ-MIG-007 (no se puede aprobar dos veces) sigue
    # aplicando igual con este repositorio.
    with pytest.raises(TransicionEstadoInvalidaError):
        service.aprobar(mapeo.id, decidido_por="otro")

    # Y el estado quedó realmente en Postgres, no solo en el objeto Python.
    fila = conn.execute(
        "SELECT estado, aprobado_por FROM mapeos_migracion_catalogo WHERE id=%s",
        (mapeo.id,),
    ).fetchone()
    assert fila == ("aprobado", "contador_lider")


def test_service_con_repositorio_postgres_respeta_guardia_de_cardinalidad(db):
    """REQ-MIG-008 (1:N y N:1) debe seguir aplicando exactamente igual
    -- la validación vive en `service.py`, sin cambios; solo cambia
    dónde vive el estado que consulta."""
    dsn, conn = db
    repo = RepositorioMapeosPostgres(conn, migracion_id="mig-cardinalidad")
    service = MigracionCatalogoService(repositorio=repo)

    m1 = _mapeo_fuzzy("ORIG-X", "DEST-COMPARTIDO")
    m2 = _mapeo_fuzzy("ORIG-Y", "DEST-COMPARTIDO")
    service.registrar(m1)
    service.registrar(m2)

    # N:1 sin estrategia de conciliación -> debe rechazarse.
    with pytest.raises(EstrategiaConciliacionRequeridaError):
        service.aprobar(m1.id, decidido_por="c")

    # Con estrategia, sí se puede.
    aprobado = service.aprobar(
        m1.id, decidido_por="c", estrategia_conciliacion_saldos="sumar saldos"
    )
    assert aprobado.estado == EstadoMapeoMigracion.APROBADO

    m3 = _mapeo_fuzzy("ORIG-X", "DEST-OTRO")  # 1:N: mismo origen, otro destino
    service.registrar(m3)
    # OJO: m3 tiene un id distinto de m1 aunque comparta origen_cuenta_id.
    with pytest.raises(DivisionUnoANoAutomaticaError):
        service.aprobar(m3.id, decidido_por="c")


# ---------------------------------------------------------------------------
# Durabilidad real: sobrevive a un "reinicio del proceso" (conexión y
# service.py nuevos, mismo migracion_id).
# ---------------------------------------------------------------------------

def test_estado_sobrevive_a_reinicio_simulado_del_proceso(db):
    dsn, _conn_fixture = db

    conn_proceso_1 = psycopg.connect(dsn)
    try:
        service_1 = MigracionCatalogoService(
            repositorio=RepositorioMapeosPostgres(conn_proceso_1, migracion_id="mig-durable")
        )
        mapeo = _mapeo_fuzzy("ORIG-DURABLE", "DEST-DURABLE")
        service_1.registrar(mapeo)
        service_1.aprobar(mapeo.id, decidido_por="contador_lider", nota="aprobado antes del reinicio")
    finally:
        conn_proceso_1.close()  # simula que el proceso murió/se reinició

    # "Proceso nuevo": conexión nueva, MigracionCatalogoService nuevo,
    # MISMO migracion_id -- debe recuperar exactamente el mismo estado.
    conn_proceso_2 = psycopg.connect(dsn)
    try:
        service_2 = MigracionCatalogoService(
            repositorio=RepositorioMapeosPostgres(conn_proceso_2, migracion_id="mig-durable")
        )
        recuperado = service_2.obtener(mapeo.id)
        assert recuperado.estado == EstadoMapeoMigracion.APROBADO
        assert recuperado.aprobado_por == "contador_lider"
        assert recuperado.nota == "aprobado antes del reinicio"
        assert len(service_2.listar()) == 1

        # La guardia de "no se puede aprobar dos veces" también sigue
        # aplicando tras el reinicio -- el estado no se "olvidó" de que
        # ya no está pendiente.
        with pytest.raises(TransicionEstadoInvalidaError):
            service_2.aprobar(mapeo.id, decidido_por="otro")
    finally:
        conn_proceso_2.close()


def test_migraciones_distintas_nunca_comparten_mapeos(db):
    dsn, conn = db
    service_empresa_x = MigracionCatalogoService(
        repositorio=RepositorioMapeosPostgres(conn, migracion_id="empresa-x:2024-2026->2020-2023")
    )
    service_empresa_y = MigracionCatalogoService(
        repositorio=RepositorioMapeosPostgres(conn, migracion_id="empresa-y:2024-2026->2020-2023")
    )

    m_x = _mapeo_fuzzy("ORIG-X", "DEST-X")
    m_y = _mapeo_fuzzy("ORIG-Y", "DEST-Y")
    service_empresa_x.registrar(m_x)
    service_empresa_y.registrar(m_y)

    assert [m.origen_cuenta_id for m in service_empresa_x.listar()] == ["ORIG-X"]
    assert [m.origen_cuenta_id for m in service_empresa_y.listar()] == ["ORIG-Y"]

    from b2b_ai.features.migracion_catalogo.service import MapeoNoEncontradoError
    with pytest.raises(MapeoNoEncontradoError):
        service_empresa_x.obtener(m_y.id)
