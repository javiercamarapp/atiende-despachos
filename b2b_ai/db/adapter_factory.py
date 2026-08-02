# -*- coding: utf-8 -*-
"""
adapter_factory.py — Database adapter factory for B2B AI Enterprise.

Returns the right adapter (SQLite or PostgreSQL) based on the DATABASE_URL
environment variable. This enables switching between dev (SQLite) and
production (PostgreSQL) with a single environment variable.

Priority for database URL detection:
  1. Explicit ``db_url`` parameter (highest)
  2. ``B2B_DB_URL`` env var
  3. ``DATABASE_URL`` env var (Railway/Heroku auto-inject)
  4. ``B2B_DB_PATH`` env var
  5. Fallback: ``b2b_ai.db`` in project root (SQLite)

Usage:
    from b2b_ai.db.adapter_factory import create_adapter
    adapter = create_adapter()  # auto-detect from env
    adapter = create_adapter("postgresql://user:pass@host/db")  # explicit

    # Then use adapter.connection as you would self.conn in Database
    rows = adapter.connection.execute("SELECT * FROM tenants").fetchall()
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("b2b_ai.db.adapter_factory")


def is_postgres(target: str) -> bool:
    """True if ``target`` is a PostgreSQL DSN.

    Recognizes both ``postgresql://`` and ``postgres://`` prefixes.
    """
    t = (target or "").strip().lower()
    return t.startswith("postgresql://") or t.startswith("postgres://")


def detect_db_url(explicit: Optional[str] = None) -> str:
    """Detect the database URL from parameter, env vars, or default.

    Args:
        explicit: Explicitly provided URL (highest priority).

    Returns:
        A database URL string (PG DSN or SQLite file path).
    """
    if explicit:
        return explicit

    env_url = (
        os.environ.get("B2B_DB_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("B2B_DB_PATH")
    )
    if env_url:
        return env_url

    # Default: SQLite file in project root
    return os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        "b2b_ai.db",
    )


def create_adapter(
    db_url: Optional[str] = None, migrate: bool = True
):
    """Create and return the appropriate database adapter.

    Args:
        db_url: Database URL. If None, auto-detect from environment.
        migrate: Whether to run migrations on initialization.

    Returns:
        A ``PostgresAdapter`` or ``SQLiteAdapter`` instance.

    Raises:
        RuntimeError: If PostgreSQL adapter requested but psycopg2/psycopg3
            is not installed.

    Example::

        # Auto-detect (respects DATABASE_URL env var)
        adapter = create_adapter()

        # Explicit PostgreSQL
        adapter = create_adapter("postgresql://user:pass@localhost:5432/b2b_ai")

        # Explicit SQLite
        adapter = create_adapter("/path/to/b2b_ai.db")
    """
    url = detect_db_url(db_url)
    logger.info("Creating adapter for: %s", _mask_url(url))

    if is_postgres(url):
        from b2b_ai.db.postgres_adapter import PostgresAdapter

        return PostgresAdapter(dsn=url, migrate=migrate)
    else:
        from b2b_ai.db.postgres_adapter import SQLiteAdapter

        return SQLiteAdapter(path=url, migrate=migrate)


def _mask_url(url: str) -> str:
    """Mask password in URL for safe logging."""
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            _, host_part = rest.rsplit("@", 1)
            return f"{prefix}://***@{host_part}"
    return url
