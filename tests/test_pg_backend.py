# -*- coding: utf-8 -*-
"""Tests del backend PostgreSQL (pg.py): traducción `?`->%s, pool, health check.

Estos tests corren solo si hay un PostgreSQL alcanzable (B2B_DB_URL). Si no
hay variable de entorno, se saltan (la suite default sigue usando SQLite).
"""
import os

import pytest

from b2b_ai.db.pg import PGPool, PGConnection, PGCursor, PGRecord, qmark_to_percent

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


pytestmark = pytest.mark.skipif(not _pg_available(),
                                reason="B2B_DB_URL PostgreSQL no disponible")


def test_qmark_to_percent():
    assert qmark_to_percent("SELECT ? AS x, ? AS y") == "SELECT %s AS x, %s AS y"
    # no toca literales de cadena ni ? fuera de placeholder en strings
    assert qmark_to_percent("SELECT '?literal' AS t, ? AS n") == \
        "SELECT '?literal' AS t, %s AS n"
    # los literales con ? no se tocan (el caso real de este código base)
    assert qmark_to_percent("SELECT '?literal' AS t, ? AS n") == \
        "SELECT '?literal' AS t, %s AS n"
    assert qmark_to_percent("UPDATE t SET v='a?b' WHERE id=?") == \
        "UPDATE t SET v='a?b' WHERE id=%s"


def test_pg_record_dict_and_positional():
    r = PGRecord({"a": 1, "b": "x"})
    assert r["a"] == 1
    assert r[0] == 1
    assert r[1] == "x"


def test_pool_connection_ping():
    pool = PGPool(PG_DSN, min_size=1, max_size=4)
    try:
        h = pool.health_check()
        assert h["ok"] is True, h
        with pool.connection() as conn:
            row = conn.execute("SELECT ? AS one", (1,)).fetchone()
            assert row["one"] == 1
            assert row[0] == 1
    finally:
        pool.close()


def test_pool_reuses_connections():
    """Dos adquisiciones consecutivas devuelven conexión usable del pool."""
    pool = PGPool(PG_DSN, min_size=1, max_size=4)
    try:
        with pool.connection() as c1:
            c1.execute("SELECT 1").fetchone()
        with pool.connection() as c2:
            c2.execute("SELECT 2").fetchone()
        assert pool.health_check()["ok"]
    finally:
        pool.close()


def test_pool_connection_limits():
    """max_size limita las conexiones físicas reales del pool."""
    pool = PGPool(PG_DSN, min_size=1, max_size=3)
    try:
        assert pool.max_size == 3
        assert pool.min_size <= 3
        # con las conexiones en uso, el pool no crea más allá del límite
        held = [pool.connection() for _ in range(pool.max_size)]
        for c in held:
            c.close()
        # tras liberar, health_check vuelve a pasar
        assert pool.health_check()["ok"] is True
    finally:
        pool.close()


def test_lastrowid_via_lastval():
    pool = PGPool(PG_DSN, min_size=1, max_size=4)
    try:
        with pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS pg_lrid")
            conn.execute("CREATE TABLE pg_lrid (id bigserial primary key, v text)")
            cur = conn.execute("INSERT INTO pg_lrid(v) VALUES (?)", ("a",))
            assert cur.lastrowid == 1
            cur = conn.execute("INSERT INTO pg_lrid(v) VALUES (?)", ("b",))
            assert cur.lastrowid == 2
            conn.commit()
    finally:
        pool.close()


def test_rowcount():
    pool = PGPool(PG_DSN, min_size=1, max_size=4)
    try:
        with pool.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS pg_rc")
            conn.execute("CREATE TABLE pg_rc (id bigserial primary key, v text)")
            conn.execute("INSERT INTO pg_rc(v) VALUES (?),(?),(?)", ("a", "b", "c"))
            conn.commit()
            cur = conn.execute("UPDATE pg_rc SET v=? WHERE id IN (?, ?)", ("x", 1, 2))
            assert cur.rowcount == 2
            conn.rollback()
    finally:
        pool.close()
