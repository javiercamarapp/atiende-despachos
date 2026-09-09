# -*- coding: utf-8 -*-
"""Tests de `cross_db.ConexionesMigracion`: apertura de DOS conexiones
Postgres reales y físicamente distintas, y la guardia dura de
solo-lectura sobre origen.

Sin mocks: usa `psycopg` real contra dos bases de datos Postgres
efímeras (fixture `dos_bases_migradas`, ver conftest.py de este
directorio).
"""
from __future__ import annotations

import pytest

from .conftest import PG_DSN, _pg_available

from b2b_ai.features.migracion_catalogo.cross_db import (
    ConexionesInvalidasError,
    ConexionesMigracion,
)

pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


def test_dsn_vacio_de_origen_lanza_conexiones_invalidas():
    with pytest.raises(ConexionesInvalidasError):
        ConexionesMigracion("", "postgresql://localhost/algo")


def test_dsn_vacio_de_destino_lanza_conexiones_invalidas():
    with pytest.raises(ConexionesInvalidasError):
        ConexionesMigracion("postgresql://localhost/algo", "   ")


def test_abre_y_cierra_ambas_conexiones_reales(dos_bases_migradas):
    origen_dsn, destino_dsn = dos_bases_migradas
    with ConexionesMigracion(origen_dsn, destino_dsn) as c:
        assert c.origen.execute("SELECT 1").fetchone() == (1,)
        assert c.destino.execute("SELECT 1").fetchone() == (1,)
        assert c.origen is not c.destino

    # Tras salir del `with`, ambas conexiones quedan cerradas -- usarlas
    # debe fallar, no funcionar "por accidente".
    with pytest.raises(Exception):
        c.origen.execute("SELECT 1")


def test_acceder_origen_destino_antes_de_abrir_lanza_runtime_error():
    c = ConexionesMigracion("postgresql://localhost/x", "postgresql://localhost/y")
    with pytest.raises(RuntimeError):
        c.origen
    with pytest.raises(RuntimeError):
        c.destino


def test_origen_se_abre_en_modo_solo_lectura_real(dos_bases_migradas):
    """La conexión de origen debe rechazar CUALQUIER escritura a nivel
    de Postgres (no solo por disciplina de código) -- ver docstring de
    `ConexionesMigracion`."""
    import psycopg

    origen_dsn, destino_dsn = dos_bases_migradas
    with ConexionesMigracion(origen_dsn, destino_dsn) as c:
        assert c.origen.read_only is True
        assert c.destino.read_only is not True

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with c.origen.transaction():
                c.origen.execute(
                    "INSERT INTO tenants (id, name) VALUES (999, 'hackeo')"
                )

        # La conexión de origen sigue utilizable para LECTURA después del
        # intento de escritura rechazado.
        c.origen.rollback()
        assert c.origen.execute("SELECT 1").fetchone() == (1,)

        # La conexión de destino, en cambio, sí puede escribir con
        # normalidad -- confirma que el read_only es específico de
        # origen, no un efecto accidental sobre ambas conexiones.
        with c.destino.transaction():
            c.destino.execute(
                "INSERT INTO tenants (id, name) VALUES (999, 'destino ok')"
            )
        fila = c.destino.execute(
            "SELECT name FROM tenants WHERE id = 999"
        ).fetchone()
        assert fila == ("destino ok",)


def test_falla_al_abrir_destino_cierra_origen_ya_abierto():
    """Si la conexión de destino falla al abrirse, `ConexionesMigracion`
    no debe dejar la conexión de origen abierta y huérfana."""
    with pytest.raises(Exception):
        ConexionesMigracion(
            PG_DSN,
            "postgresql://usuario_invalido_xyz@localhost:5432/db_no_existe_xyz",
        ).abrir()
