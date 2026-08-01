# -*- coding: utf-8 -*-
"""
pool.py — Pool de conexiones para la base de datos (enterprise API v2).

SQLite por defecto abre una conexión por Database; para cargas grandes
(batch de hasta 1000 CFDI, analytics, exports) un solo cursor serializa
todo. Este pool mantiene N conexiones `sqlite3` listas para checkout/
checkin bajo un lock, permitiendo lecturas concurrentes en endpoints de
solo lectura (analytics/export). El mismo contrato es el que usaría un
pool real de PostgreSQL (psycopg2) cuando se migre a PG.

Uso:
    from b2b_ai.db.pool import ConnectionPool
    pool = ConnectionPool(db_path, size=4)
    with pool.acquire() as conn:      # conn es sqlite3.Connection
        rows = conn.execute("SELECT 1").fetchall()
"""
from __future__ import annotations

import queue
import sqlite3
import threading


class _Lease:
    """Context manager que entrega una conexión y la devuelve al salir."""

    def __init__(self, pool: "ConnectionPool"):
        self.pool = pool
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = self.pool._acquire_raw()
        return self._conn

    def __exit__(self, *exc):
        if self._conn is not None:
            self.pool._release_raw(self._conn)
        return False


class ConnectionPool:
    """Pool de conexiones sqlite3 thread-safe (FIFO) listas para leer."""

    def __init__(self, db_path: str, size: int = 4, timeout: float = 5.0):
        self.db_path = db_path
        self.size = max(1, int(size))
        self.timeout = timeout
        self._pool: "queue.LifoQueue[sqlite3.Connection]" = queue.LifoQueue()
        self._lock = threading.Lock()
        self._created = 0

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._created += 1
        return conn

    def _acquire_raw(self) -> sqlite3.Connection:
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.size:
                    return self._open()
            # Todas ocupadas: bloquea hasta que una se libere.
            return self._pool.get(timeout=self.timeout)

    def _release_raw(self, conn: sqlite3.Connection):
        try:
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
                "available": self._pool.qsize()}

    def close(self) -> None:
        while True:
            try:
                self._pool.get_nowait().close()
            except queue.Empty:
                break
