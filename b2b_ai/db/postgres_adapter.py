# -*- coding: utf-8 -*-
"""
postgres_adapter.py — PostgreSQL database adapter for B2B AI Enterprise.

Implements the same interface as the SQLite adapter in db.py, providing
a transparent switch between SQLite (dev) and PostgreSQL (production).

Key features:
  - Query translation: SQLite `?` → PG `%s`, `:name` → `%(name)s`
  - Connection pooling with configurable min/max size
  - PG-compatible row factory (dict + positional access)
  - Alembic-based migration for PG (vs SQLite MIGRATIONS)
  - Thread-safe connection management
  - Health checks and retry logic

Usage:
    from b2b_ai.db.postgres_adapter import PostgresAdapter
    adapter = PostgresAdapter(dsn="postgresql://user:pass@host/db")
    conn = adapter.connection  # PGConnection with sqlite3-compatible API
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("b2b_ai.db.postgres_adapter")


# ---------------------------------------------------------------------------
# Query translation: SQLite → PostgreSQL
# ---------------------------------------------------------------------------

def translate_placeholders(sql: str) -> str:
    """Convert SQLite-style placeholders to PostgreSQL-style.

    Converts:
      - ``?``  → ``%s``          (positional)
      - ``:name`` → ``%(name)s`` (named)

    Respects string literals (single and double quotes) so placeholders
    inside quoted text are left untouched.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    quote = None
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote and i + 1 < n and sql[i + 1] == quote:
                out.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            out.append("%s")
            i += 1
            continue
        if ch == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            name = sql[i + 1 : j]
            out.append(f"%({name})s")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# SQLite PRAGMAs that have no PG equivalent (silently ignored).
_SQLITE_PRAGMAS = {
    "PRAGMA foreign_keys",
    "PRAGMA journal_mode",
    "PRAGMA busy_timeout",
}

# Regex to detect PRAGMA statements (for stripping).
_PRAGMA_RE = re.compile(r"PRAGMA\s+\w+", re.IGNORECASE)


def _strip_pragmas(sql: str) -> str:
    """Remove SQLite PRAGMA statements from a SQL string."""
    lines = sql.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if _PRAGMA_RE.match(stripped):
            continue
        result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# PG-compatible row factory
# ---------------------------------------------------------------------------

class PGRecord(dict):
    """Dict-based row that also supports positional access (r[0])."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _make_row_factory(cursor):
    """Factory that creates PGRecord rows from cursor description."""
    names = [d.name for d in cursor.description] if cursor.description else []

    def make_row(values):
        return PGRecord(zip(names, values))

    return make_row


# ---------------------------------------------------------------------------
# PGCursor — sqlite3.Cursor-compatible wrapper
# ---------------------------------------------------------------------------

class PGCursor:
    """Wraps a psycopg cursor to match sqlite3.Cursor's API.

    - Translates ``?`` and ``:name`` placeholders
    - Provides ``lastrowid`` via ``SELECT lastval()``
    - Supports iteration, fetchone, fetchall
    """

    def __init__(self, cursor, conn):
        self._c = cursor
        self._conn = conn  # raw psycopg connection for lastval()

    def execute(self, sql: str, params=None):
        translated = _strip_pragmas(translate_placeholders(sql))
        if not translated.strip():
            return self
        self._c.execute(translated, params or ())
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def __iter__(self):
        return iter(self._c)

    def __len__(self):
        return len(self._c)

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def lastrowid(self):
        try:
            self._c.execute("SELECT lastval()")
            val = self._c.fetchone()[0]
            return int(val)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# PGConnection — sqlite3.Connection-compatible wrapper
# ---------------------------------------------------------------------------

class PGConnection:
    """Wraps a psycopg connection to match sqlite3.Connection's API.

    Supports:
      - execute() with ``?`` / ``:name`` placeholders
      - commit() / rollback()
      - executescript() (splits on ``;``)
      - Context manager (``with conn:`` → commit/rollback)
      - close() → returns connection to pool

    The ``release`` context manager is how we give the connection back
    to psycopg_pool — close() calls its ``__exit__``.
    """

    def __init__(self, raw_conn, release=None):
        self._c = raw_conn
        self._release = release
        self._c.row_factory = _make_row_factory
        self._released = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if exc[0] is not None:
                self._c.rollback()
            else:
                self._c.commit()
        except Exception:
            pass
        return False

    def execute(self, sql, params=None):
        return PGCursor(self._c.cursor(), self._c).execute(sql, params)

    def executescript(self, sql):
        """Execute multiple statements (splits on ``;``)."""
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self.execute(stmt)
        return self

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        if self._released:
            return
        self._released = True
        if self._release is not None:
            try:
                self._release.__exit__(None, None, None)
            except Exception:
                pass
        else:
            try:
                self._c.close()
            except Exception:
                pass

    def raw(self):
        return self._c


# ---------------------------------------------------------------------------
# PostgresAdapter — the main adapter class
# ---------------------------------------------------------------------------

class PostgresAdapter:
    """PostgreSQL adapter implementing the same interface as the SQLite adapter.

    Handles:
      - Connection pooling (via psycopg_pool)
      - Query translation (``?`` → ``%s``, ``:name`` → ``%(name)s``)
      - Thread-safe per-thread connections
      - Migrations via Alembic
      - Health checks

    Environment variables:
      - ``B2B_PG_POOL_MIN``  : Minimum pool connections (default 2)
      - ``B2B_PG_POOL_MAX``  : Maximum pool connections (default 10)
      - ``B2B_PG_RETRIES``   : Retry count on connection failure (default 3)
      - ``B2B_PG_TIMEOUT``   : Connection timeout in seconds (default 5)
    """

    def __init__(self, dsn: str, migrate: bool = True):
        self.dsn = dsn
        self._pool = None
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: set = set()
        self._init_pool()
        if migrate:
            self.migrate()

    def _init_pool(self):
        """Initialize the connection pool from env vars or defaults."""
        try:
            import psycopg_pool as _pool_mod

            min_size = int(os.environ.get("B2B_PG_POOL_MIN", "2"))
            max_size = int(os.environ.get("B2B_PG_POOL_MAX", "10"))
            retries = int(os.environ.get("B2B_PG_RETRIES", "3"))
            timeout = float(os.environ.get("B2B_PG_TIMEOUT", "5"))

            self._pool = _PGPool(
                self.dsn,
                min_size=min_size,
                max_size=max_size,
                retries=retries,
                pool_timeout=timeout,
            )
        except ImportError:
            logger.warning(
                "psycopg_pool not installed; PG pool will be created lazily"
            )
            self._pool = None

    def _ensure_pool(self):
        """Lazily create pool if psycopg_pool became available."""
        if self._pool is None:
            self._init_pool()
        if self._pool is None:
            raise RuntimeError(
                "psycopg_pool is required for PostgreSQL adapter"
            )

    @property
    def connection(self):
        """Get a thread-local PostgreSQL connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None and getattr(conn, "_released", False):
            self._local.conn = None
            conn = None
        if conn is None:
            self._ensure_pool()
            raw_cm = self._pool._pool.connection()
            raw = raw_cm.__enter__()
            conn = PGConnection(raw, release=raw_cm)
            self._local.conn = conn
            with self._lock:
                self._connections.add(conn)
        return conn

    def close(self):
        """Close all connections (return to pool)."""
        with self._lock:
            conns = list(self._connections)
            self._connections.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        try:
            del self._local.conn
        except AttributeError:
            pass

    # ---- Migrations ----
    def migrate(self):
        """Run Alembic migrations to bring PostgreSQL to head."""
        try:
            from alembic.config import Config
            from alembic import command

            os.environ["B2B_DB_URL"] = self.dsn
            root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            alembic_ini = os.path.join(root, "alembic.ini")
            alembic_cfg = Config(alembic_ini)
            command.upgrade(alembic_cfg, "head")
        except Exception as e:
            logger.warning("Alembic migration failed (may not be configured): %s", e)

        # Defensive: ensure the unique constraint for upsert_outstanding_invoice
        try:
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_outstanding_unique
                ON outstanding_invoices(tenant_id, factura_id)
            """
            )
        except Exception:
            pass

    def schema_version(self):
        """Get current schema version (from alembic_version table)."""
        try:
            row = self.connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            return 1 if row else 0
        except Exception:
            return 0

    # ---- Integrity error detection ----
    @staticmethod
    def is_integrity_error(exc: Exception) -> bool:
        """True if exc is a uniqueness/integrity violation in PostgreSQL."""
        try:
            from psycopg import errors as pgerr

            return isinstance(exc, pgerr.UniqueViolation)
        except ImportError:
            return False

    # ---- Health check ----
    def health_check(self) -> Dict[str, Any]:
        """Verify PG connectivity. Returns dict with status."""
        try:
            with self.connection as conn:
                conn.execute("SELECT 1").fetchone()
            return {"ok": True, "backend": "postgresql"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @property
    def is_postgres(self) -> bool:
        return True

    def data_version(self) -> int:
        """Data version for cache invalidation (stub for PG)."""
        return 0


# ---------------------------------------------------------------------------
# Internal pool wrapper (reuses psycopg_pool.ConnectionPool)
# ---------------------------------------------------------------------------

class _PGPool:
    """Thin wrapper around psycopg_pool.ConnectionPool with retry logic."""

    def __init__(self, dsn, min_size=2, max_size=10, retries=3,
                 pool_timeout=10.0):
        import psycopg_pool

        def _health(conn):
            try:
                conn.execute("SELECT 1").fetchone()
            except Exception:
                return False
            return True

        self._pool = psycopg_pool.ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"connect_timeout": 5},
            check=_health,
            timeout=pool_timeout,
        )
        self._pool.open()
        # Wait for min_size connections to be ready
        for _ in range(retries):
            try:
                self._pool.wait()
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("Could not open PostgreSQL connection pool")


# ---------------------------------------------------------------------------
# SQLite adapter — same interface for backward compatibility
# ---------------------------------------------------------------------------

class SQLiteAdapter:
    """SQLite adapter implementing the same interface as PostgresAdapter.

    This wraps the existing sqlite3-based logic so that the Database class
    can treat both backends uniformly via the adapter interface.
    """

    def __init__(self, path: str, migrate: bool = True):
        self.path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: set = set()
        self._data_version = 0
        self._version_lock = threading.Lock()
        if migrate:
            self.migrate()
            self.connection.commit()

    @property
    def connection(self):
        """Get a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            import sqlite3 as _sqlite3

            conn = _sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = _sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except _sqlite3.Error:
                pass
            conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn = conn
            with self._lock:
                self._connections.add(conn)
            self.migrate()
        return conn

    def close(self):
        with self._lock:
            conns = list(self._connections)
            self._connections.clear()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        try:
            del self._local.conn
        except AttributeError:
            pass

    def migrate(self):
        """Run SQLite migrations from models.MIGRATIONS."""
        from b2b_ai.db.models import MIGRATIONS

        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        applied = {
            r[0]
            for r in self.connection.execute("SELECT version FROM schema_version")
        }
        for m in MIGRATIONS:
            if m["version"] not in applied:
                with self.connection:
                    self.connection.executescript(m["sql"])
                    self.connection.execute(
                        "INSERT INTO schema_version(version) VALUES (?)",
                        (m["version"],),
                    )

    def schema_version(self):
        import sqlite3 as _sqlite3

        try:
            return self.connection.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0]
        except _sqlite3.Error:
            return 0

    @staticmethod
    def is_integrity_error(exc: Exception) -> bool:
        import sqlite3 as _sqlite3

        return isinstance(exc, _sqlite3.IntegrityError)

    def health_check(self) -> Dict[str, Any]:
        return {"ok": True, "backend": "sqlite", "path": self.path}

    @property
    def is_postgres(self) -> bool:
        return False

    def data_version(self) -> int:
        return self._data_version

    def bump_version(self) -> None:
        with self._version_lock:
            self._data_version += 1
