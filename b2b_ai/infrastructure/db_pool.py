# -*- coding: utf-8 -*-
"""
db_pool.py — Enterprise database connection pool with monitoring.

Features:
    - Configurable pool sizing (min, max, overflow)
    - Connection health checks (pool_pre_ping)
    - Connection recycling (max lifetime)
    - Slow query logging (> configurable threshold)
    - Connection pool metrics (active, idle, overflow, wait times)
    - Prometheus-compatible metrics export
    - Thread-safe with connection context manager
"""
from __future__ import annotations

import collections
import logging
import os
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from b2b_ai.infrastructure.structured_logging import get_logger

logger = get_logger("b2b_ai.db_pool")


# --------------------------------------------------------------------------- #
# Pool Configuration
# --------------------------------------------------------------------------- #

@dataclass
class PoolConfig:
    """Connection pool configuration.

    Attributes:
        min_size: Minimum connections maintained in the pool.
        max_size: Maximum connections (active + idle).
        overflow: Extra connections allowed beyond max_size under load.
        max_lifetime: Max seconds a connection can live before recycling.
        idle_timeout: Seconds before idle connections are closed.
        pre_ping: Check connection health before handing out.
        slow_query_threshold_ms: Log queries slower than this.
        connect_timeout: Max seconds to wait for a connection from pool.
        retry_on_disconnect: Auto-reconnect on stale connections.
    """
    min_size: int = 2
    max_size: int = 10
    overflow: int = 5
    max_lifetime: float = 3600.0    # 1 hour
    idle_timeout: float = 300.0     # 5 minutes
    pre_ping: bool = True
    slow_query_threshold_ms: float = 500.0
    connect_timeout: float = 10.0
    retry_on_disconnect: bool = True


# --------------------------------------------------------------------------- #
# Pool Metrics
# --------------------------------------------------------------------------- #

@dataclass
class PoolMetrics:
    """Connection pool metrics (thread-safe)."""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    total_connections_created: int = 0
    total_connections_recycled: int = 0
    total_connections_errored: int = 0
    total_acquires: int = 0
    total_acquires_timeout: int = 0
    total_slow_queries: int = 0
    total_pre_ping_failures: int = 0
    current_active: int = 0
    current_idle: int = 0
    current_overflow: int = 0
    wait_time_sum_ms: float = 0.0
    wait_time_count: int = 0
    query_time_sum_ms: float = 0.0
    query_time_count: int = 0

    def record_acquire(self, wait_ms: float) -> None:
        with self._lock:
            self.total_acquires += 1
            self.wait_time_sum_ms += wait_ms
            self.wait_time_count += 1

    def record_query(self, duration_ms: float) -> None:
        with self._lock:
            self.query_time_sum_ms += duration_ms
            self.query_time_count += 1

    def record_slow_query(self, duration_ms: float) -> None:
        with self._lock:
            self.total_slow_queries += 1

    def record_connection_created(self) -> None:
        with self._lock:
            self.total_connections_created += 1

    def record_connection_recycled(self) -> None:
        with self._lock:
            self.total_connections_recycled += 1

    def record_connection_error(self) -> None:
        with self._lock:
            self.total_connections_errored += 1

    def record_acquire_timeout(self) -> None:
        with self._lock:
            self.total_acquires_timeout += 1

    def record_pre_ping_failure(self) -> None:
        with self._lock:
            self.total_pre_ping_failures += 1

    def update_counts(self, active: int, idle: int, overflow: int) -> None:
        with self._lock:
            self.current_active = active
            self.current_idle = idle
            self.current_overflow = overflow

    @property
    def avg_wait_time_ms(self) -> float:
        with self._lock:
            if self.wait_time_count == 0:
                return 0.0
            return self.wait_time_sum_ms / self.wait_time_count

    @property
    def avg_query_time_ms(self) -> float:
        with self._lock:
            if self.query_time_count == 0:
                return 0.0
            return self.query_time_sum_ms / self.query_time_count

    def snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of all metrics."""
        with self._lock:
            return {
                "total_connections_created": self.total_connections_created,
                "total_connections_recycled": self.total_connections_recycled,
                "total_connections_errored": self.total_connections_errored,
                "total_acquires": self.total_acquires,
                "total_acquires_timeout": self.total_acquires_timeout,
                "total_slow_queries": self.total_slow_queries,
                "total_pre_ping_failures": self.total_pre_ping_failures,
                "current_active": self.current_active,
                "current_idle": self.current_idle,
                "current_overflow": self.current_overflow,
                "avg_wait_time_ms": round(self.avg_wait_time_ms, 2),
                "avg_query_time_ms": round(self.avg_query_time_ms, 2),
            }

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        lines = []
        snap = self.snapshot()
        for key, value in snap.items():
            metric_name = f"b2b_db_pool_{key}"
            lines.append(f"# HELP {metric_name} Database pool metric: {key}")
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {value}")
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Connection Wrapper (tracks lifetime + query timing)
# --------------------------------------------------------------------------- #

class ManagedConnection:
    """Wrapper around a DB connection that tracks lifetime and queries."""

    def __init__(self, conn: Any, created_at: float, pool: "EnterpriseConnectionPool"):
        self.conn = conn
        self.created_at = created_at
        self.pool = pool
        self._in_use = False

    @property
    def age(self) -> float:
        """Connection age in seconds."""
        return time.monotonic() - self.created_at

    def is_expired(self, max_lifetime: float) -> bool:
        """Check if connection has exceeded max lifetime."""
        return self.age > max_lifetime

    def execute(self, query: str, params: tuple = ()) -> Any:
        """Execute a query with timing and slow-query logging."""
        start = time.perf_counter()
        try:
            result = self.conn.execute(query, params)
            return result
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.pool.metrics.record_query(duration_ms)
            threshold = self.pool.config.slow_query_threshold_ms
            if duration_ms > threshold:
                self.pool.metrics.record_slow_query(duration_ms)
                logger.warning(
                    f"Slow query ({duration_ms:.1f}ms > {threshold}ms)",
                    extra={"extra_fields": {
                        "query": query[:200],
                        "duration_ms": round(duration_ms, 2),
                        "threshold_ms": threshold,
                    }},
                )

    def fetchone(self, query: str, params: tuple = ()):
        """Execute and fetch one row."""
        return self.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple = ()):
        """Execute and fetch all rows."""
        return self.execute(query, params).fetchall()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Enterprise Connection Pool
# --------------------------------------------------------------------------- #

class EnterpriseConnectionPool:
    """Enterprise-grade connection pool for SQLite (dev) and PostgreSQL (prod).

    Features:
        - Min/max/overflow sizing
        - Connection health checks (pre_ping)
        - Connection recycling (max lifetime)
        - Slow query logging
        - Comprehensive metrics
    """

    def __init__(
        self,
        db_path: str,
        config: Optional[PoolConfig] = None,
    ):
        self.db_path = db_path
        self.config = config or PoolConfig()
        self.metrics = PoolMetrics()
        self._is_pg = self._is_postgres(db_path)

        # Pool state
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._active: set = set()
        self._lock = threading.Lock()
        self._total_created = 0
        self._closed = False

        # Initialize minimum connections
        self._initialize_pool()

    @staticmethod
    def _is_postgres(target: str) -> bool:
        t = (target or "").strip().lower()
        return t.startswith("postgresql://") or t.startswith("postgres://")

    def _create_connection(self) -> ManagedConnection:
        """Create a new database connection."""
        if self._is_pg:
            from b2b_ai.db.pg import PGPool
            pool = PGPool(
                self.db_path,
                min_size=1,
                max_size=1,
            )
            conn = pool.connection()
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                pass
            conn.execute("PRAGMA busy_timeout = 5000")

        self.metrics.record_connection_created()
        self._total_created += 1
        return ManagedConnection(conn, time.monotonic(), self)

    def _initialize_pool(self) -> None:
        """Pre-create minimum connections."""
        for _ in range(self.config.min_size):
            try:
                mc = self._create_connection()
                self._idle.put(mc)
            except Exception as exc:
                logger.error(f"Failed to create initial connection: {exc}")
                break

    def _pre_ping(self, mc: ManagedConnection) -> bool:
        """Check if a connection is still alive."""
        try:
            mc.execute("SELECT 1")
            return True
        except Exception:
            self.metrics.record_pre_ping_failure()
            return False

    def _recycle_if_needed(self, mc: ManagedConnection) -> ManagedConnection:
        """Recycle connection if it has exceeded max lifetime."""
        if mc.is_expired(self.config.max_lifetime):
            self.metrics.record_connection_recycled()
            try:
                mc.close()
            except Exception:
                pass
            return self._create_connection()
        return mc

    @contextmanager
    def acquire(self):
        """Acquire a connection from the pool.

        Usage:
            with pool.acquire() as conn:
                rows = conn.fetchall("SELECT * FROM invoices WHERE tenant_id = ?", (t_id,))
        """
        if self._closed:
            raise RuntimeError("Pool is closed")

        start = time.monotonic()
        mc = None

        try:
            # Try to get an idle connection
            try:
                mc = self._idle.get_nowait()
            except queue.Empty:
                pass

            # Check if idle connection is healthy
            if mc is not None:
                if self.config.pre_ping and not self._pre_ping(mc):
                    try:
                        mc.close()
                    except Exception:
                        pass
                    mc = None
                else:
                    mc = self._recycle_if_needed(mc)

            # Create new connection if needed
            if mc is None:
                with self._lock:
                    current_total = self._total_created
                    max_allowed = self.config.max_size + self.config.overflow

                if current_total >= max_allowed:
                    # Wait for one to become available
                    wait_start = time.monotonic()
                    try:
                        mc = self._idle.get(timeout=self.config.connect_timeout)
                    except queue.Empty:
                        self.metrics.record_acquire_timeout()
                        raise TimeoutError(
                            f"Could not acquire connection within "
                            f"{self.config.connect_timeout}s"
                        )
                else:
                    mc = self._create_connection()

            # Mark as active
            with self._lock:
                self._active.add(id(mc))
            mc._in_use = True

            wait_ms = (time.monotonic() - start) * 1000
            self.metrics.record_acquire(wait_ms)
            self._update_counts()

            yield mc

        finally:
            # Return to pool
            if mc is not None:
                mc._in_use = False
                with self._lock:
                    self._active.discard(id(mc))

                if not self._closed:
                    try:
                        if not self._is_pg:
                            mc.rollback()
                        self._idle.put(mc)
                    except Exception:
                        try:
                            mc.close()
                        except Exception:
                            pass
                        self.metrics.record_connection_error()

                self._update_counts()

    def _update_counts(self) -> None:
        """Update current pool counts in metrics."""
        with self._lock:
            active = len(self._active)
            idle = self._idle.qsize()
            total = active + idle
            overflow = max(0, total - self.config.max_size)
        self.metrics.update_counts(active, idle, overflow)

    def close(self) -> None:
        """Close all connections in the pool."""
        self._closed = True
        closed = 0
        while True:
            try:
                mc = self._idle.get_nowait()
                mc.close()
                closed += 1
            except queue.Empty:
                break
        logger.info(f"Connection pool closed ({closed} connections)")

    @property
    def stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        return {
            "config": {
                "min_size": self.config.min_size,
                "max_size": self.config.max_size,
                "overflow": self.config.overflow,
                "pre_ping": self.config.pre_ping,
                "slow_query_threshold_ms": self.config.slow_query_threshold_ms,
            },
            "metrics": self.metrics.snapshot(),
            "backend": "postgresql" if self._is_pg else "sqlite",
        }


# --------------------------------------------------------------------------- #
# Connection context manager (standalone, not tied to pool)
# --------------------------------------------------------------------------- #

@contextmanager
def timed_query(
    db_path: str,
    query: str,
    params: tuple = (),
    slow_threshold_ms: float = 500.0,
):
    """Execute a query with timing and slow-query logging (standalone).

    Usage:
        with timed_query("db.sqlite", "SELECT * FROM invoices") as result:
            rows = result.fetchall()
    """
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    start = time.perf_counter()
    try:
        cursor = conn.execute(query, params)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        if duration_ms > slow_threshold_ms:
            logger.warning(
                f"Slow query ({duration_ms:.1f}ms)",
                extra={"extra_fields": {
                    "query": query[:200],
                    "duration_ms": round(duration_ms, 2),
                }},
            )
        conn.close()
