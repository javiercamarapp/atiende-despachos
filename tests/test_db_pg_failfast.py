# -*- coding: utf-8 -*-
"""Fail-fast de _pg_migrate() cuando PostgreSQL está inalcanzable.

Antes, cualquier excepción durante `command.upgrade()` (Alembic) o el índice
defensivo se tragaba como "no fatal" y solo se logueaba un warning — incluida
una excepción de CONEXIÓN real (host caído, credenciales, red). Eso significa
que `Database(dsn_postgres)` "tenía éxito" en producción sin haber podido
hablar nunca con la base, y el primer síntoma aparecía después, en medio de
una request cualquiera, como un error de pool genérico.

No requiere PostgreSQL real: se simula la excepción de conectividad con
monkeypatch sobre `alembic.command.upgrade` / `Database.conn`, así que corre
siempre (a diferencia de tests/test_db_pg_integration.py, que sí necesita un
servidor real y se salta sin uno).
"""
from __future__ import annotations

import psycopg
import pytest
from sqlalchemy.exc import OperationalError as SAOperationalError

from b2b_ai.db.db import Database, _is_pg_unreachable_error


def test_is_pg_unreachable_error_detecta_sqlalchemy_operational_error():
    exc = SAOperationalError("SELECT 1", {}, Exception("connection refused"))
    assert _is_pg_unreachable_error(exc) is True


def test_is_pg_unreachable_error_detecta_psycopg_operational_error():
    exc = psycopg.OperationalError("could not connect to server")
    assert _is_pg_unreachable_error(exc) is True


def test_is_pg_unreachable_error_no_confunde_error_benigno():
    """Un error de "ya existe" / "ya migrado" NO debe fallar rápido — sigue
    siendo tolerado (comportamiento previo, intencional)."""
    assert _is_pg_unreachable_error(RuntimeError("relation already exists")) is False
    assert _is_pg_unreachable_error(ValueError("head already applied")) is False


def test_pg_migrate_falla_rapido_si_alembic_no_puede_conectar(monkeypatch):
    """Simula que Alembic no logra conectar a PostgreSQL (DSN inalcanzable):
    _pg_migrate() debe propagar un RuntimeError explícito, NO tragárselo ni
    degradar a SQLite."""
    import alembic.command as alembic_command

    def _raise_connection_refused(*args, **kwargs):
        raise SAOperationalError(
            "SELECT 1", {}, Exception("connection to server failed"))

    monkeypatch.setattr(alembic_command, "upgrade", _raise_connection_refused)

    with pytest.raises(RuntimeError, match="No se pudo conectar a PostgreSQL"):
        Database("postgresql://fake_user:fake_pw@127.0.0.1:1/fake_db_unreachable")


def test_pg_migrate_sigue_tolerando_error_benigno_de_alembic(monkeypatch):
    """Un error "ya migrado"/"tabla ya existe" durante Alembic sigue sin
    matar el arranque (comportamiento previo, intencional) — solo las
    excepciones de conectividad real deben fallar rápido."""
    import alembic.command as alembic_command

    def _raise_duplicate_table(*args, **kwargs):
        raise RuntimeError("relation \"tenants\" already exists")

    monkeypatch.setattr(alembic_command, "upgrade", _raise_duplicate_table)

    # También debe tolerar que el índice defensivo falle porque la tabla
    # outstanding_invoices aún no existe (mismo comportamiento previo).
    # Se sustituye la propiedad `conn` a nivel de clase (revertido solo
    # para este test por monkeypatch) para no depender del pool real.
    class _FakeConn:
        def execute(self, *a, **k):
            raise RuntimeError("relation \"outstanding_invoices\" does not exist")

        def commit(self):
            pass

    monkeypatch.setattr(Database, "conn", property(lambda self: _FakeConn()))

    db = Database.__new__(Database)
    db.path = "postgresql://fake_user:fake_pw@127.0.0.1:1/fake_db_tolerante"
    db._is_pg = True
    # No debe levantar: es un error benigno, no de conectividad.
    db._pg_migrate()
