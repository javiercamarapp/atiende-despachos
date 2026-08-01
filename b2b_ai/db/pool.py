# -*- coding: utf-8 -*-
"""
pool.py — Pool de conexiones para la base de datos (enterprise API v2).

Soporta SQLite (dev) y PostgreSQL (producción). Detecta el backend por el
DSN: si empieza con `postgresql://` o `postgres://` usa PGPool (psycopg_pool);
en caso contrario usa sqlite3.

Uso:
    from b2b_ai.db.pool import ConnectionPool
    pool = ConnectionPool(db_path_or_dsn, size=4)
    with pool.acquire() as conn:
        rows = conn.execute("SELECT 1").fetchall()
"""
from __future__ import annotations

import os
import queue
import sqlite3
import threading


def _is_postgres(target: str) -> bool:
    t = (target or "").strip().lower()
    return t.startswith("postgresql://") or t.startswith("postgres://")


class _Lease:
    """Context manager que entrega una conexión y la devuelve al salir."""

    def __init__(self, pool: "ConnectionPool"):
        self.pool = pool
        self._conn = None

    def __enter__(self):
        self._conn = self.pool._acquire_raw()
        return self._conn

    def __exit__(self, *exc):
        if self._conn is not None:
            self.pool._release_raw(self._conn)
        return False


class ConnectionPool:
    """Pool de conexiones thread-safe — SQLite o PostgreSQL según el DSN."""

    def __init__(self, db_path: str, size: int = 4, timeout: float = 5.0):
        self.db_path = db_path
        self.size = max(1, int(size))
        self.timeout = timeout
        self._is_pg = _is_postgres(db_path)
        self._pool: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._created = 0
        # Para PG, reusar el pool compartido de pg.py
        self._pg_pool = None

    def _open(self):
        if self._is_pg:
            if self._pg_pool is None:
                from b2b_ai.db.pg import PGPool
                self._pg_pool = PGPool(
                    self.db_path,
                    min_size=1,
                    max_size=self.size,
                )
            return self._pg_pool.connection()
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._created += 1
        return conn

    def _acquire_raw(self):
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.size or self._is_pg:
                    conn = self._open()
                    if not self._is_pg:
                        self._created += 1
                    return conn
            # Todas ocupadas: bloquea hasta que una se libere.
            return self._pool.get(timeout=self.timeout)

    def _release_raw(self, conn):
        try:
            if self._is_pg:
                # PGConnection: commit and release back to pool
                try:
                    conn.commit()
                except Exception:
                    pass
            else:
                conn.rollback()
            self._pool.put(conn)
        except Exception:  # noqa: BLE001  — conexión rota: cerrar
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def acquire(self) -> _Lease:
        """Devuelve un context manager: `with pool.acquire() as conn:`."""
        return _Lease(self)

    def run(self, query: str, params: tuple = ()) -> list:
        """Atajo: ejecuta una query de solo lectura con una conexión del pool."""
        with self.acquire() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    @property
    def stats(self) -> dict:
        return {"size": self.size, "created": self._created,
                "available": self._pool.qsize(),
                "backend": "postgresql" if self._is_pg else "sqlite"}

    def close(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
