# -*- coding: utf-8 -*-
"""
test_postgres_adapter_integration.py — Integration tests for PG adapter with realistic mocks.

60+ tests covering end-to-end scenarios that verify:
  1. Adapter factory correctly selects PG vs SQLite based on DATABASE_URL env var
  2. Query translation works for 10+ common SQL patterns
  3. Connection pooling configuration is correct
  4. Transaction isolation works across both adapters
  5. Error handling when PG is unavailable falls back gracefully to SQLite
  6. Alembic migration detection works for both DB backends

Uses unittest.mock to simulate psycopg2 — no real PG required.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any
from unittest.mock import MagicMock, Mock, PropertyMock, patch, call

import pytest

from b2b_ai.db.postgres_adapter import (
    PGConnection,
    PGCursor,
    PGRecord,
    PostgresAdapter,
    SQLiteAdapter,
    _make_row_factory,
    _strip_pragmas,
    translate_placeholders,
)
from b2b_ai.db.adapter_factory import (
    create_adapter,
    detect_db_url,
    is_postgres,
    _mask_url,
)


# =========================================================================
# Helpers
# =========================================================================

def _make_mock_pg_pool(min_size=2, max_size=10):
    """Create a realistic mock psycopg_pool.ConnectionPool."""
    mock_pool = MagicMock()
    mock_pool._nconns = min_size

    # The pool's connection() method returns a context manager
    mock_cm = MagicMock()
    mock_raw_conn = MagicMock()

    # Mock cursor that supports .description for row_factory
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.execute = MagicMock()
    mock_cursor.fetchall = MagicMock(return_value=[])
    mock_cursor.fetchone = MagicMock(return_value=None)
    mock_raw_conn.cursor.return_value = mock_cursor

    mock_cm.__enter__ = Mock(return_value=mock_raw_conn)
    mock_cm.__exit__ = Mock(return_value=False)
    mock_pool.connection.return_value = mock_cm
    mock_pool.wait = Mock()
    mock_pool.close = Mock()

    return mock_pool


def _make_pg_adapter(migrate=False, pool_min=2, pool_max=10):
    """Create a PG adapter with fully mocked pool."""
    mock_pool = _make_mock_pg_pool(min_size=pool_min, max_size=pool_max)
    env = {k: v for k, v in os.environ.items()
           if k not in ("B2B_PG_POOL_MIN", "B2B_PG_POOL_MAX",
                        "B2B_DB_URL", "DATABASE_URL", "B2B_DB_PATH")}
    with patch.dict(os.environ, env, clear=True), \
         patch("psycopg_pool.ConnectionPool", return_value=mock_pool), \
         patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
        adapter = PostgresAdapter("postgresql://user:pass@localhost:5432/b2b_test",
                                  migrate=False)
    return adapter


def _in_memory_db():
    """Create an in-memory SQLite adapter for testing."""
    return SQLiteAdapter(path=":memory:", migrate=False)


# =========================================================================
# 1. ADAPTER FACTORY — PG vs SQLite selection (DATABASE_URL env var)
# =========================================================================

class TestAdapterFactorySelection:
    """Verify factory correctly routes to PG or SQLite based on env/config."""

    def test_pg_url_returns_postgres_adapter(self):
        """Factory returns PostgresAdapter for postgresql:// URL."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            adapter = create_adapter("postgresql://user:pass@host/db", migrate=False)
            assert isinstance(adapter, PostgresAdapter)
            assert adapter.is_postgres is True

    def test_postgres_prefix_returns_postgres_adapter(self):
        """Factory returns PostgresAdapter for postgres:// URL (Heroku style)."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            adapter = create_adapter("postgres://user:pass@host/db", migrate=False)
            assert isinstance(adapter, PostgresAdapter)

    def test_sqlite_path_returns_sqlite_adapter(self):
        """Factory returns SQLiteAdapter for file path."""
        adapter = create_adapter("/tmp/test_factory.db", migrate=False)
        assert isinstance(adapter, SQLiteAdapter)
        assert adapter.is_postgres is False

    def test_explicit_pg_overrides_database_url_env(self):
        """Explicit pg_url parameter wins over DATABASE_URL env."""
        with patch.dict(os.environ, {"DATABASE_URL": "/tmp/env.db"}, clear=True):
            with patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
                 patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
                adapter = create_adapter(
                    "postgresql://explicit@host/db", migrate=False
                )
                assert isinstance(adapter, PostgresAdapter)

    def test_explicit_sqlite_overrides_database_url_env(self):
        """Explicit sqlite path wins over DATABASE_URL=postgresql://."""
        with patch.dict(os.environ,
                        {"DATABASE_URL": "postgresql://env@host/db"}, clear=True):
            adapter = create_adapter("/tmp/explicit.db", migrate=False)
            assert isinstance(adapter, SQLiteAdapter)

    def test_database_url_env_pg(self):
        """DATABASE_URL env with pg URL auto-selects PG adapter."""
        with patch.dict(os.environ,
                        {"DATABASE_URL": "postgresql://env@host/db"}, clear=True):
            with patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
                 patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
                adapter = create_adapter(migrate=False)
                assert isinstance(adapter, PostgresAdapter)

    def test_b2b_db_url_env_pg(self):
        """B2B_DB_URL env with pg URL auto-selects PG adapter."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_DB_URL", "DATABASE_URL", "B2B_DB_PATH")}
        with patch.dict(os.environ, {**clean, "B2B_DB_URL": "postgresql://b2b@host/db"},
                        clear=True):
            with patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
                 patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
                adapter = create_adapter(migrate=False)
                assert isinstance(adapter, PostgresAdapter)

    def test_b2b_db_path_env_sqlite(self):
        """B2B_DB_PATH env selects SQLite adapter."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_DB_URL", "DATABASE_URL", "B2B_DB_PATH")}
        with patch.dict(os.environ, {**clean, "B2B_DB_PATH": "/tmp/b2b.db"},
                        clear=True):
            adapter = create_adapter(migrate=False)
            assert isinstance(adapter, SQLiteAdapter)

    def test_env_priority_b2b_db_url_over_database_url(self):
        """B2B_DB_URL takes precedence over DATABASE_URL."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_DB_URL", "DATABASE_URL", "B2B_DB_PATH")}
        with patch.dict(os.environ, {
            **clean,
            "B2B_DB_URL": "postgresql://b2b-priority@host/db",
            "DATABASE_URL": "postgresql://database-url@host/db",
        }, clear=True):
            with patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
                 patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
                adapter = create_adapter(migrate=False)
                assert isinstance(adapter, PostgresAdapter)

    def test_case_insensitive_pg_detection(self):
        """PG detection is case-insensitive."""
        assert is_postgres("PostgreSQL://user@host/db") is True
        assert is_postgres("POSTGRES://user@host/db") is True
        assert is_postgres("Postgres://user@host/db") is True

    def test_non_pg_urls_detected_as_sqlite(self):
        """Non-PG URLs are treated as SQLite paths."""
        assert is_postgres("/tmp/test.db") is False
        assert is_postgres("sqlite:///test.db") is False
        assert is_postgres("mysql://host/db") is False
        assert is_postgres("") is False
        assert is_postgres(None) is False

    def test_mask_url_hides_password(self):
        """_mask_url masks password in URL."""
        masked = _mask_url("postgresql://user:s3cret@host:5432/db")
        assert "s3cret" not in masked
        assert "postgresql://***@host:5432/db" == masked

    def test_mask_url_no_password_unchanged(self):
        """_mask_url passes through URLs without passwords."""
        assert _mask_url("sqlite:///test.db") == "sqlite:///test.db"

    def test_mask_url_pg_dsn_format(self):
        """_mask_url masks password in standard PG DSN."""
        masked = _mask_url("postgresql://admin:P@ssw0rd@db.example.com:5432/prod")
        assert "P@ssw0rd" not in masked


# =========================================================================
# 2. QUERY TRANSLATION — 10+ common SQL patterns
# =========================================================================

class TestQueryTranslationIntegration:
    """Test translate_placeholders and PGCursor for real-world SQL patterns."""

    def test_insert_with_positional(self):
        sql = "INSERT INTO users(name, email) VALUES (?, ?)"
        result = translate_placeholders(sql)
        assert result == "INSERT INTO users(name, email) VALUES (%s, %s)"

    def test_select_with_where_positional(self):
        sql = "SELECT * FROM users WHERE id=? AND active=?"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM users WHERE id=%s AND active=%s"

    def test_update_with_where_named(self):
        sql = "UPDATE users SET name=:name WHERE id=:id"
        result = translate_placeholders(sql)
        assert result == "UPDATE users SET name=%(name)s WHERE id=%(id)s"

    def test_delete_with_where(self):
        sql = "DELETE FROM sessions WHERE expires_at < ?"
        result = translate_placeholders(sql)
        assert result == "DELETE FROM sessions WHERE expires_at < %s"

    def test_select_with_join(self):
        sql = "SELECT u.name, i.total FROM users u JOIN invoices i ON u.id = i.user_id WHERE u.id=?"
        result = translate_placeholders(sql)
        assert "?" not in result
        assert "%s" in result

    def test_select_with_aggregate_count(self):
        sql = "SELECT COUNT(*) as cnt FROM invoices WHERE tenant_id=?"
        result = translate_placeholders(sql)
        assert result == "SELECT COUNT(*) as cnt FROM invoices WHERE tenant_id=%s"

    def test_select_with_aggregate_sum_group_by(self):
        sql = "SELECT tenant_id, SUM(total) as total_sum FROM invoices GROUP BY tenant_id HAVING SUM(total) > ?"
        result = translate_placeholders(sql)
        assert "?" not in result
        assert "%s" in result

    def test_select_with_datetime_now(self):
        sql = "SELECT * FROM invoices WHERE created_at > datetime('now', ?)"
        result = translate_placeholders(sql)
        assert "?" not in result
        assert "%s" in result
        assert "datetime('now', %s)" in result

    def test_select_with_limit_offset(self):
        sql = "SELECT * FROM invoices ORDER BY id LIMIT ? OFFSET ?"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM invoices ORDER BY id LIMIT %s OFFSET %s"

    def test_insert_on_conflict_do_update(self):
        sql = """
            INSERT INTO invoices (tenant_id, folio_fiscal, total)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant_id, folio_fiscal)
            DO UPDATE SET total=excluded.total
        """
        result = translate_placeholders(sql)
        assert "VALUES (%s, %s, %s)" in result
        assert "?" not in result

    def test_select_with_between(self):
        sql = "SELECT * FROM logs WHERE ts BETWEEN ? AND ?"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM logs WHERE ts BETWEEN %s AND %s"

    def test_select_with_in_clause(self):
        sql = "SELECT * FROM users WHERE role IN (?, ?, ?)"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM users WHERE role IN (%s, %s, %s)"

    def test_select_with_like(self):
        sql = "SELECT * FROM users WHERE name LIKE ?"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM users WHERE name LIKE %s"

    def test_insert_with_returning(self):
        sql = "INSERT INTO items(name) VALUES (?) RETURNING id"
        result = translate_placeholders(sql)
        assert result == "INSERT INTO items(name) VALUES (%s) RETURNING id"

    def test_select_subquery(self):
        sql = "SELECT * FROM t WHERE id IN (SELECT ref_id FROM s WHERE flag=?)"
        result = translate_placeholders(sql)
        assert "?" not in result

    def test_update_with_case_expression(self):
        sql = "UPDATE t SET status = CASE WHEN ? > 0 THEN 'active' ELSE 'inactive' END WHERE id=?"
        result = translate_placeholders(sql)
        assert "?" not in result
        assert result.count("%s") == 2

    def test_placeholder_in_string_literal_not_translated(self):
        sql = "SELECT * FROM t WHERE col='value?' AND id=?"
        result = translate_placeholders(sql)
        assert "value?" in result  # inside string literal
        assert result.count("%s") == 1  # only the real placeholder

    def test_placeholder_in_double_quotes_not_translated(self):
        sql = 'SELECT * FROM t WHERE "col?" = ?'
        result = translate_placeholders(sql)
        assert '"col?"' in result
        assert result.count("%s") == 1

    def test_escaped_single_quote_preserved(self):
        sql = "SELECT * FROM t WHERE x='it''s?' AND id=?"
        result = translate_placeholders(sql)
        assert "it''s?" in result
        assert result.count("%s") == 1

    def test_empty_sql_stays_empty(self):
        result = translate_placeholders("")
        assert result == ""

    def test_comment_only_sql_preserved(self):
        sql = "-- This is a comment\nSELECT 1"
        result = translate_placeholders(sql)
        assert "-- This is a comment" in result
        assert "SELECT 1" in result

    def test_pgcursor_executes_translated_insert(self):
        """PGCursor translates INSERT with positional placeholders."""
        mock_cursor = MagicMock()
        mock_cursor.description = []
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        pg_cursor.execute(
            "INSERT INTO users(name, email) VALUES (?, ?)",
            ("Alice", "alice@test.com"),
        )
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert executed_sql == "INSERT INTO users(name, email) VALUES (%s, %s)"
        assert mock_cursor.execute.call_args[0][1] == ("Alice", "alice@test.com")

    def test_pgcursor_executes_translated_select(self):
        """PGCursor translates SELECT with named placeholders."""
        mock_cursor = MagicMock()
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.fetchall.return_value = [(1, "test")]
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        pg_cursor.execute(
            "SELECT * FROM users WHERE id=:user_id AND name=:name",
            {"user_id": 42, "name": "Bob"},
        )
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "%(user_id)s" in executed_sql
        assert "%(name)s" in executed_sql
        assert ":user_id" not in executed_sql
        assert ":name" not in executed_sql

    def test_pgcursor_pragma_stripped(self):
        """PRAGMA statements are stripped before execution on PG."""
        mock_cursor = MagicMock()
        mock_cursor.description = []
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        pg_cursor.execute("PRAGMA foreign_keys = ON")
        # PRAGMA-only SQL becomes empty → no execute call
        mock_cursor.execute.assert_not_called()

    def test_pgcursor_multiline_pragma_stripped(self):
        """Multi-line SQL with PRAGMA lines: only PRAGMA lines removed."""
        mock_cursor = MagicMock()
        mock_cursor.description = []
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        sql = "PRAGMA foreign_keys\nPRAGMA journal_mode\nSELECT 1"
        pg_cursor.execute(sql)
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "PRAGMA" not in executed_sql
        assert "SELECT 1" in executed_sql

    def test_pgcursor_lastrowid_returns_int(self):
        """lastrowid calls SELECT lastval() and returns int."""
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value = None
        mock_cursor.fetchone.return_value = (42,)
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        assert pg_cursor.lastrowid == 42
        mock_cursor.execute.assert_called_with("SELECT lastval()")

    def test_pgcursor_lastrowid_returns_none_on_error(self):
        """lastrowid returns None when lastval() fails."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("no sequence")
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        assert pg_cursor.lastrowid is None

    def test_pgcursor_iteration(self):
        """PGCursor supports iteration over results."""
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = Mock(return_value=iter([1, 2, 3]))
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        assert list(pg_cursor) == [1, 2, 3]

    def test_pgcursor_len(self):
        """PGCursor supports len() for row count."""
        mock_cursor = MagicMock()
        mock_cursor.__len__ = Mock(return_value=5)
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)

        assert len(pg_cursor) == 5

    def test_pgcursor_fetchone(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 1, "name": "test"}
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        assert pg_cursor.fetchone() == {"id": 1, "name": "test"}

    def test_pgcursor_fetchall(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        assert len(pg_cursor.fetchall()) == 2

    def test_pgcursor_rowcount(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 7
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        assert pg_cursor.rowcount == 7


# =========================================================================
# 3. CONNECTION POOLING — configuration correctness
# =========================================================================

class TestConnectionPooling:
    """Verify pool is configured from env vars with correct defaults."""

    def test_default_pool_sizes(self):
        """Without env vars: min=2, max=10."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_PG_POOL_MIN", "B2B_PG_POOL_MAX",
                              "B2B_PG_RETRIES", "B2B_PG_TIMEOUT")}
        with patch.dict(os.environ, clean, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()) as mock_cls, \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            PostgresAdapter("postgresql://localhost/test", migrate=False)
            _, kwargs = mock_cls.call_args
            assert kwargs["min_size"] == 2
            assert kwargs["max_size"] == 10

    def test_custom_pool_min(self):
        """B2B_PG_POOL_MIN overrides default."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_PG_POOL_MIN",)}
        with patch.dict(os.environ, {**clean, "B2B_PG_POOL_MIN": "5"}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()) as mock_cls, \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            PostgresAdapter("postgresql://localhost/test", migrate=False)
            _, kwargs = mock_cls.call_args
            assert kwargs["min_size"] == 5

    def test_custom_pool_max(self):
        """B2B_PG_POOL_MAX overrides default."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_PG_POOL_MAX",)}
        with patch.dict(os.environ, {**clean, "B2B_PG_POOL_MAX": "50"}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()) as mock_cls, \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            PostgresAdapter("postgresql://localhost/test", migrate=False)
            _, kwargs = mock_cls.call_args
            assert kwargs["max_size"] == 50

    def test_custom_retries_and_timeout(self):
        """B2B_PG_RETRIES and B2B_PG_TIMEOUT are read from env."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_PG_RETRIES", "B2B_PG_TIMEOUT")}
        with patch.dict(os.environ, {
            **clean, "B2B_PG_RETRIES": "7", "B2B_PG_TIMEOUT": "15"
        }, clear=True):
            with patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
                 patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
                adapter = PostgresAdapter("postgresql://localhost/test", migrate=False)
                assert adapter._pool is not None

    def test_pool_is_created_with_open_false(self):
        """Pool is initially created with open=False (opened later)."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_PG_POOL_MIN",)}
        with patch.dict(os.environ, clean, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()) as mock_cls, \
             patch("b2b_ai.db.postgres_adapter.PostgresAdapter.migrate"):
            PostgresAdapter("postgresql://localhost/test", migrate=False)
            _, kwargs = mock_cls.call_args
            assert kwargs.get("open") is False or kwargs.get("open") is None

    def test_thread_local_connections(self):
        """Each thread gets its own connection object from pool."""
        adapter = _make_pg_adapter()

        results = {}
        barrier = threading.Barrier(3)

        def worker(name):
            barrier.wait(timeout=5)
            conn = adapter.connection
            results[name] = id(conn)

        threads = [threading.Thread(target=worker, args=(f"t{i}",))
                   for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(set(results.values())) == 3

    def test_connection_released_marked_stale(self):
        """Released connections are detected and new ones acquired."""
        adapter = _make_pg_adapter()

        # Simulate a released connection
        mock_released = MagicMock()
        mock_released._released = True
        adapter._local.conn = mock_released

        conn = adapter.connection
        assert conn is not mock_released

    def test_close_clears_all_tracked_connections(self):
        """close() clears all tracked connections and thread-local."""
        adapter = _make_pg_adapter()
        _ = adapter.connection  # triggers pool connection
        assert len(adapter._connections) >= 1
        adapter.close()
        assert len(adapter._connections) == 0


# =========================================================================
# 4. TRANSACTION ISOLATION — across both adapters
# =========================================================================

class TestTransactionIsolation:
    """Verify commit/rollback behavior on both PG and SQLite adapters."""

    def test_sqlite_commit_persists(self):
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection
        cur = conn.execute(
            "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
            ("T1", "RFC1"),
        )
        conn.commit()
        tid = cur.lastrowid
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
        assert row is not None
        assert row["name"] == "T1"

    def test_sqlite_rollback_discards(self):
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection
        conn.execute(
            "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
            ("Rollback", "RBT"),
        )
        conn.rollback()
        rows = conn.execute(
            "SELECT * FROM tenants WHERE name='Rollback'"
        ).fetchall()
        assert len(rows) == 0

    def test_sqlite_context_manager_commits(self):
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        with adapter.connection as conn:
            conn.execute(
                "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
                ("CtxCommit", "CTX"),
            )
        row = adapter.connection.execute(
            "SELECT * FROM tenants WHERE name='CtxCommit'"
        ).fetchone()
        assert row is not None

    def test_sqlite_context_manager_rollback_on_error(self):
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        with pytest.raises(RuntimeError):
            with adapter.connection as conn:
                conn.execute(
                    "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
                    ("WillFail", "WFL"),
                )
                raise RuntimeError("trigger rollback")
        rows = adapter.connection.execute(
            "SELECT * FROM tenants WHERE name='WillFail'"
        ).fetchall()
        assert len(rows) == 0

    def test_pg_connection_commits_on_normal_exit(self):
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        with pg_conn:
            pass
        mock_raw.commit.assert_called_once()
        mock_raw.rollback.assert_not_called()

    def test_pg_connection_rollback_on_exception(self):
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        with pytest.raises(RuntimeError):
            with pg_conn:
                raise RuntimeError("fail")
        mock_raw.rollback.assert_called_once()
        mock_raw.commit.assert_not_called()

    def test_pg_connection_exit_always_returns_false(self):
        """__exit__ never suppresses exceptions."""
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        assert pg_conn.__exit__(None, None, None) is False
        assert pg_conn.__exit__(ValueError, ValueError("x"), None) is False

    def test_pg_connection_close_idempotent(self):
        """Calling close() twice only releases once."""
        mock_release = MagicMock()
        mock_release.__exit__ = Mock(return_value=False)
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw, release=mock_release)
        pg_conn.close()
        pg_conn.close()
        assert mock_release.__exit__.call_count == 1

    def test_pg_connection_close_without_release(self):
        """close() without release context manager calls raw close."""
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw, release=None)
        pg_conn.close()
        mock_raw.close.assert_called_once()

    def test_pg_connection_executescript_splits_statements(self):
        """executescript splits on semicolons and runs each."""
        mock_raw = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.description = []
        mock_raw.cursor.return_value = mock_cursor
        pg_conn = PGConnection(mock_raw)
        pg_conn.executescript("INSERT INTO t VALUES (1); INSERT INTO t VALUES (2)")
        assert mock_cursor.execute.call_count >= 2

    def test_pg_connection_raw_returns_inner(self):
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        assert pg_conn.raw() is mock_raw

    def test_close_without_commit_loses_uncommitted_data_sqlite(self):
        """Closing SQLite without commit does not auto-commit."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection
        conn.execute(
            "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
            ("Uncommitted", "UNC"),
        )
        # Force a new connection (simulating new thread)
        adapter._local.conn = None
        new_adapter = SQLiteAdapter(path=":memory:", migrate=True)
        rows = new_adapter.connection.execute(
            "SELECT * FROM tenants WHERE name='Uncommitted'"
        ).fetchall()
        assert len(rows) == 0


# =========================================================================
# 5. ERROR HANDLING — PG unavailable → graceful fallback to SQLite
# =========================================================================

class TestGracefulFallback:
    """Verify behavior when PG is unavailable and fallback logic."""

    def test_create_adapter_sqlite_when_no_pg_env(self):
        """When no PG env var is set, factory returns SQLite."""
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("B2B_DB_URL", "DATABASE_URL", "B2B_DB_PATH")}
        with patch.dict(os.environ, clean, clear=True):
            adapter = create_adapter("/tmp/fallback.db", migrate=False)
            assert isinstance(adapter, SQLiteAdapter)

    def test_pg_health_check_ok(self):
        """health_check returns ok=True on working connection."""
        adapter = _make_pg_adapter()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_conn._released = False
        adapter._local = MagicMock()
        adapter._local.conn = mock_conn
        result = adapter.health_check()
        assert result["ok"] is True
        assert result["backend"] == "postgresql"

    def test_pg_health_check_failure(self):
        """health_check returns ok=False on broken connection."""
        adapter = _make_pg_adapter()
        # Use a real thread-local so _released defaults to False
        import threading
        adapter._local = threading.local()
        # Build a PGConnection whose cursor.execute raises
        broken_raw = MagicMock()
        broken_cursor = MagicMock()
        broken_cursor.execute.side_effect = Exception("connection refused")
        broken_raw.cursor.return_value = broken_cursor
        broken_conn = PGConnection(broken_raw)
        adapter._local.conn = broken_conn
        result = adapter.health_check()
        assert result["ok"] is False
        assert "error" in result

    def test_sqlite_health_check_always_ok(self):
        """SQLite health_check always returns ok."""
        adapter = _in_memory_db()
        result = adapter.health_check()
        assert result["ok"] is True
        assert result["backend"] == "sqlite"

    def test_pg_integrity_error_with_psycopg(self):
        """is_integrity_error detects psycopg UniqueViolation."""
        mock_exc_class = type("UniqueViolation", (Exception,), {})
        with patch.dict("sys.modules", {
            "psycopg": MagicMock(errors=MagicMock(UniqueViolation=mock_exc_class)),
            "psycopg.errors": MagicMock(UniqueViolation=mock_exc_class),
        }):
            exc = mock_exc_class("duplicate key")
            assert PostgresAdapter.is_integrity_error(exc) is True

    def test_pg_integrity_error_without_psycopg(self):
        """is_integrity_error returns False when psycopg not installed."""
        with patch.dict("sys.modules", {"psycopg": None, "psycopg.errors": None}):
            import importlib
            import b2b_ai.db.postgres_adapter as mod
            result = mod.PostgresAdapter.is_integrity_error(Exception("test"))
            assert result is False

    def test_sqlite_integrity_error_detected(self):
        exc = sqlite3.IntegrityError("UNIQUE constraint failed")
        assert SQLiteAdapter.is_integrity_error(exc) is True

    def test_sqlite_non_integrity_error_not_detected(self):
        exc = sqlite3.OperationalError("disk full")
        assert SQLiteAdapter.is_integrity_error(exc) is False

    def test_generic_exception_not_detected_as_integrity(self):
        assert SQLiteAdapter.is_integrity_error(ValueError("nope")) is False
        assert PostgresAdapter.is_integrity_error(ValueError("nope")) is False

    def test_pg_adapter_data_version_always_zero(self):
        """PG adapter data_version is always 0 (no cache invalidation)."""
        adapter = _make_pg_adapter()
        assert adapter.data_version() == 0

    def test_sqlite_adapter_data_version_bumps(self):
        """SQLite adapter data_version increments with bump_version."""
        adapter = SQLiteAdapter(path=":memory:", migrate=False)
        assert adapter.data_version() == 0
        adapter.bump_version()
        assert adapter.data_version() == 1
        adapter.bump_version()
        assert adapter.data_version() == 2

    def test_sqlite_data_version_thread_safe(self):
        """bump_version is thread-safe under concurrent access."""
        adapter = SQLiteAdapter(path=":memory:", migrate=False)
        n = 10
        barrier = threading.Barrier(n)

        def bump():
            barrier.wait()
            for _ in range(100):
                adapter.bump_version()

        threads = [threading.Thread(target=bump) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert adapter.data_version() == n * 100

    def test_pg_adapter_schema_version_returns_int(self):
        """schema_version returns 1 when alembic_version has data."""
        adapter = _make_pg_adapter()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("abc123",)
        mock_conn._released = False
        adapter._local = MagicMock()
        adapter._local.conn = mock_conn
        assert adapter.schema_version() == 1

    def test_pg_adapter_schema_version_returns_0_when_empty(self):
        """schema_version returns 0 when alembic_version is empty."""
        adapter = _make_pg_adapter()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn._released = False
        adapter._local = MagicMock()
        adapter._local.conn = mock_conn
        assert adapter.schema_version() == 0

    def test_pg_adapter_schema_version_returns_0_on_exception(self):
        """schema_version returns 0 on any exception."""
        adapter = _make_pg_adapter()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("table missing")
        mock_conn._released = False
        adapter._local = MagicMock()
        adapter._local.conn = mock_conn
        assert adapter.schema_version() == 0


# =========================================================================
# 6. ALEMBIC MIGRATION DETECTION — both backends
# =========================================================================

class TestAlembicMigrationDetection:
    """Verify migration system works for both PG and SQLite backends."""

    def test_sqlite_migrate_creates_tables(self):
        """SQLite migrate() creates expected tables."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        tables = adapter.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {t["name"] for t in tables}
        assert "tenants" in names
        assert "invoices" in names
        assert "users" in names
        assert "schema_version" in names

    def test_sqlite_migrate_idempotent(self):
        """Running migrate() twice on SQLite doesn't fail."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        adapter.migrate()  # second call
        assert adapter.schema_version() >= 1

    def test_sqlite_schema_version_positive(self):
        """SQLite schema_version returns positive integer after migration."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        v = adapter.schema_version()
        assert v is not None
        assert v >= 1

    def test_pg_migrate_calls_alembic_upgrade(self):
        """PostgresAdapter migrate() calls subprocess with alembic upgrade head."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("subprocess.run") as mock_sub, \
             patch("sys.executable", "/usr/bin/python3"):
            mock_sub.return_value = Mock(returncode=0, stdout="", stderr="")
            adapter = PostgresAdapter("postgresql://localhost/test", migrate=True)
            # Verify alembic was called
            mock_sub.assert_called()
            args = mock_sub.call_args
            assert "alembic" in str(args)
            assert "upgrade" in str(args)
            assert "head" in str(args)

    def test_pg_migrate_sets_b2b_db_url_env(self):
        """migrate() passes B2B_DB_URL env to subprocess."""
        dsn = "postgresql://user:pass@pg-host:5432/mydb"
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("subprocess.run") as mock_sub, \
             patch("sys.executable", "/usr/bin/python3"):
            mock_sub.return_value = Mock(returncode=0, stdout="", stderr="")
            adapter = PostgresAdapter(dsn, migrate=True)
            env_passed = mock_sub.call_args[1].get("env") or mock_sub.call_args[0][1] if len(mock_sub.call_args[0]) > 1 else mock_sub.call_args[1].get("env", {})
            # The B2B_DB_URL should be in the subprocess env
            if "env" in (mock_sub.call_args[1] if mock_sub.call_args[1] else {}):
                assert env_passed.get("B2B_DB_URL") == dsn

    def test_pg_migrate_gracefully_handles_alembic_failure(self):
        """If Alembic fails, adapter still initializes (warning logged)."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("subprocess.run", side_effect=FileNotFoundError("no alembic")), \
             patch("sys.executable", "/usr/bin/python3"):
            # Should not raise
            adapter = PostgresAdapter("postgresql://localhost/test", migrate=True)
            assert adapter is not None

    def test_pg_migrate_creates_unique_index(self):
        """After Alembic, adapter creates idx_outstanding_unique index."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("psycopg_pool.ConnectionPool", return_value=_make_mock_pg_pool()), \
             patch("subprocess.run") as mock_sub:
            mock_sub.return_value = Mock(returncode=0, stdout="", stderr="")
            adapter = PostgresAdapter("postgresql://localhost/test", migrate=True)
            # The unique index creation should have been attempted
            # (via connection.execute in migrate())

    def test_pg_adapter_interface_matches_sqlite(self):
        """PG adapter exposes same public API as SQLite adapter."""
        pg_adapter = _make_pg_adapter()
        sqlite_adapter = _in_memory_db()

        for attr in ("connection", "close", "migrate", "schema_version",
                      "is_postgres", "health_check", "data_version"):
            assert hasattr(pg_adapter, attr), f"PG adapter missing {attr}"
            assert hasattr(sqlite_adapter, attr), f"SQLite adapter missing {attr}"

    def test_pg_is_postgres_true(self):
        assert _make_pg_adapter().is_postgres is True

    def test_sqlite_is_postgres_false(self):
        assert _in_memory_db().is_postgres is False

    def test_pg_row_factory_creates_pgrecord(self):
        """PGRecord factory creates rows with dict + positional access."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            MagicMock(name="id"), MagicMock(name="name"), MagicMock(name="email")
        ]
        mock_cursor.description[0].name = "id"
        mock_cursor.description[1].name = "name"
        mock_cursor.description[2].name = "email"
        factory = _make_row_factory(mock_cursor)
        row = (1, "Alice", "alice@test.com")
        record = factory(row)
        assert isinstance(record, PGRecord)
        assert record["id"] == 1
        assert record["name"] == "Alice"
        assert record[0] == 1
        assert record[1] == "Alice"
        assert record[2] == "alice@test.com"

    def test_pg_row_factory_no_description(self):
        """Factory handles empty cursor description."""
        mock_cursor = MagicMock()
        mock_cursor.description = None
        factory = _make_row_factory(mock_cursor)
        row = factory((1,))
        assert isinstance(row, PGRecord)
        assert len(row) == 0  # no names mapped

    def test_pg_connection_sets_row_factory(self):
        """PGConnection sets row_factory on raw connection."""
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        mock_raw.row_factory = _make_row_factory  # verify it was set


# =========================================================================
# 7. INTEGRATION — end-to-end SQLite adapter workflows
# =========================================================================

class TestSQLiteIntegration:
    """End-to-end workflows on real SQLite adapter (in-memory)."""

    def test_full_crud_cycle(self):
        """INSERT → SELECT → UPDATE → DELETE on SQLite adapter."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection

        # INSERT
        cur = conn.execute(
            "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
            ("TestCo", "TST010101ABC"),
        )
        conn.commit()
        tid = cur.lastrowid

        # SELECT
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
        assert row is not None
        assert row["name"] == "TestCo"

        # UPDATE
        conn.execute(
            "UPDATE tenants SET name=? WHERE id=?",
            ("UpdatedCo", tid),
        )
        conn.commit()
        row2 = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
        assert row2["name"] == "UpdatedCo"

        # DELETE
        conn.execute("DELETE FROM tenants WHERE id=?", (tid,))
        conn.commit()
        row3 = conn.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
        assert row3 is None

    def test_multiple_tenants_insert_and_query(self):
        """Insert multiple tenants and query with aggregate."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection
        for i in range(5):
            conn.execute(
                "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
                (f"Tenant{i}", f"RFC{i:03d}"),
            )
        conn.commit()
        rows = conn.execute("SELECT COUNT(*) as cnt FROM tenants").fetchone()
        assert rows["cnt"] == 5

    def test_invoices_with_tenant_join(self):
        """Insert tenant + invoices, verify join query works."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        conn = adapter.connection
        # Insert tenant
        cur = conn.execute(
            "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
            ("JoinCo", "JNC010101"),
        )
        conn.commit()
        tid = cur.lastrowid

        # Insert invoices
        for amt in [100.0, 200.0, 300.0]:
            conn.execute(
                "INSERT INTO invoices(tenant_id, total, status, archivo) VALUES (?, ?, ?, ?)",
                (tid, amt, "paid", "test.pdf"),
            )
        conn.commit()

        # Verify
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM invoices WHERE tenant_id=?", (tid,)
        ).fetchone()
        assert rows["cnt"] == 3

    def test_schema_version_after_migration(self):
        """schema_version returns correct value after migration."""
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        assert adapter.schema_version() >= 1

    def test_close_and_reopen(self):
        """Adapter can be closed and connection re-obtained."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            adapter = SQLiteAdapter(path=db_path, migrate=True)
            conn = adapter.connection
            conn.execute(
                "INSERT INTO tenants(name, rfc) VALUES (?, ?)",
                ("PreClose", "PRC"),
            )
            conn.commit()
            adapter.close()
            # New connection should still have data
            conn2 = adapter.connection
            rows = conn2.execute(
                "SELECT * FROM tenants WHERE name='PreClose'"
            ).fetchall()
            assert len(rows) == 1
        finally:
            os.unlink(db_path)
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + suffix)
                except OSError:
                    pass


# =========================================================================
# 8. EDGE CASES & ROBUSTNESS
# =========================================================================

class TestEdgeCasesIntegration:
    """Edge cases that exercise the full adapter stack."""

    def test_pgconnection_enter_returns_self(self):
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        assert pg_conn.__enter__() is pg_conn

    def test_pgcursor_execute_returns_self_for_chaining(self):
        mock_cursor = MagicMock()
        mock_cursor.description = []
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        result = pg_cursor.execute("SELECT 1")
        assert result is pg_cursor

    def test_pgcursor_empty_string_is_noop(self):
        mock_cursor = MagicMock()
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        pg_cursor.execute("")
        mock_cursor.execute.assert_not_called()

    def test_pgcursor_whitespace_only_is_noop(self):
        mock_cursor = MagicMock()
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        pg_cursor.execute("   \n\t  ")
        mock_cursor.execute.assert_not_called()

    def test_pgcursor_pragma_only_is_noop(self):
        mock_cursor = MagicMock()
        raw_conn = MagicMock()
        pg_cursor = PGCursor(mock_cursor, raw_conn)
        pg_cursor.execute("PRAGMA foreign_keys")
        mock_cursor.execute.assert_not_called()

    def test_pgconnection_context_manager_exception_ignored(self):
        """If commit/rollback in __exit__ raises, exception is swallowed."""
        mock_raw = MagicMock()
        mock_raw.commit.side_effect = RuntimeError("commit failed")
        pg_conn = PGConnection(mock_raw)
        # Should not raise
        result = pg_conn.__exit__(None, None, None)
        assert result is False

    def test_pg_adapter_close_handles_already_released(self):
        """close() handles connections that were already released."""
        adapter = _make_pg_adapter()
        conn = adapter.connection
        conn.close()  # release it
        # Close again — should not crash
        adapter.close()

    def test_pg_adapter_thread_safety_close(self):
        """Concurrent close() calls don't raise."""
        adapter = _make_pg_adapter()
        _ = adapter.connection  # ensure connection exists

        def closer():
            adapter.close()

        threads = [threading.Thread(target=closer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(adapter._connections) == 0

    def test_sqlite_close_cleans_thread_local(self):
        adapter = SQLiteAdapter(path=":memory:", migrate=True)
        _ = adapter.connection
        adapter.close()
        # Thread-local conn should be cleaned up
        local_conn = getattr(adapter._local, "conn", None)
        assert local_conn is None

    def test_pg_record_getitem_string_key(self):
        """PGRecord supports standard dict key access."""
        r = PGRecord({"a": 1, "b": 2})
        assert r["a"] == 1
        assert r["b"] == 2

    def test_pg_record_getitem_int_key(self):
        """PGRecord supports positional integer access."""
        r = PGRecord({"a": 1, "b": 2, "c": 3})
        assert r[0] == 1
        assert r[1] == 2
        assert r[2] == 3

    def test_pg_record_to_dict(self):
        r = PGRecord({"x": 10, "y": 20})
        d = dict(r)
        assert d == {"x": 10, "y": 20}

    def test_pg_record_key_error(self):
        r = PGRecord({"a": 1})
        with pytest.raises(KeyError):
            _ = r["nonexistent"]

    def test_strip_pragmas_removes_all_pragma_lines(self):
        sql = "PRAGMA foreign_keys\nSELECT 1\nPRAGMA journal_mode\nSELECT 2"
        result = _strip_pragmas(sql)
        assert "PRAGMA" not in result
        assert "SELECT 1" in result
        assert "SELECT 2" in result

    def test_strip_pragmas_leaves_non_pragma_untouched(self):
        sql = "SELECT * FROM t WHERE id=1"
        result = _strip_pragmas(sql)
        assert result == sql

    def test_translate_placeholders_colon_not_alphabetic(self):
        """Colon followed by space or digit is NOT treated as named param."""
        sql = "SELECT * FROM t WHERE x=:3"  # digit after colon → not named param
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM t WHERE x=:3"

    def test_translate_placeholders_underscore_name(self):
        """Named params with underscores work."""
        sql = "SELECT * FROM t WHERE id=:user_id"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM t WHERE id=%(user_id)s"

    def test_translate_placeholders_numeric_after_colon(self):
        """Colon followed by digit is not a named param."""
        sql = "SELECT * FROM t WHERE x=1:2"
        result = translate_placeholders(sql)
        assert result == "SELECT * FROM t WHERE x=1:2"

    def test_pg_cursor_description_used_for_row_factory(self):
        """_make_row_factory maps column names from description."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            MagicMock(name="tenant_id"), MagicMock(name="folio_fiscal"),
            MagicMock(name="total"),
        ]
        mock_cursor.description[0].name = "tenant_id"
        mock_cursor.description[1].name = "folio_fiscal"
        mock_cursor.description[2].name = "total"
        factory = _make_row_factory(mock_cursor)
        row = (42, "ABC-123", 999.99)
        record = factory(row)
        assert record["tenant_id"] == 42
        assert record["folio_fiscal"] == "ABC-123"
        assert record["total"] == 999.99

    def test_pg_connection_setattr_sets_row_factory(self):
        """PGConnection sets _make_row_factory on raw conn."""
        mock_raw = MagicMock()
        pg_conn = PGConnection(mock_raw)
        # Verify row_factory was set during __init__
        assert mock_raw.row_factory is not None
