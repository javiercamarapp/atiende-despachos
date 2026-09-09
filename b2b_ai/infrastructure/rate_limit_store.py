# -*- coding: utf-8 -*-
"""
rate_limit_store.py — Rate limiting persistido en PostgreSQL, por tenant.

Por qué existe
---------------
Los rate limiters previos de este repo (``b2b_ai/api/app.py::RateLimiter``,
``b2b_ai/middleware/rate_limiter.py``, y el backend por defecto de
``b2b_ai/api/rate_limiter.py``) guardan sus contadores en un diccionario de
proceso. Eso rompe en cuanto hay más de un worker (Gunicorn/Uvicorn con
``--workers N``, o varias réplicas): cada proceso lleva su propia cuenta, así
que el límite real que sufre un cliente es ``limite * N`` en vez de
``limite``. Redis arregla eso, pero es una dependencia opcional en este
proyecto (``B2B_REDIS_URL``) — sin ella, el fallback siempre ha sido memoria.

Este módulo añade un tercer backend, persistido en PostgreSQL (que SIEMPRE
está disponible en producción — es la base de datos de tenants), como
alternativa intermedia entre "memoria" y "Redis obligatorio": funciona con
cualquier número de workers/réplicas sin infraestructura adicional.

Aislamiento del cluster db-core
--------------------------------
A propósito este módulo NO importa ``b2b_ai/db/db.py`` (la capa multi-tenant
principal, de alto tráfico de cambios) ni reutiliza su pool. Abre su propio
``psycopg_pool.ConnectionPool`` diminuto, con su propio DSN resuelto de forma
independiente. Esto es deliberado: minimiza el área de conflicto de merge
con cualquier trabajo concurrente sobre ``db.py`` y hace que este módulo se
pueda borrar o reemplazar sin tocar la capa de datos "core".

Algoritmo: contador de ventana fija (fixed window counter)
------------------------------------------------------------
Se eligió ventana fija (no "sliding log" ni "sliding window log" como los
backends Redis/memoria existentes) por dos razones concretas:

  1. Tamaño de almacenamiento O(1) por (clave, ventana) — un UPSERT, no una
     fila por request. Un sliding log en PostgreSQL (una fila por petición)
     crecería sin techo bajo carga sostenida y necesitaría un job de
     limpieza más agresivo solo para no llenar el disco.
  2. Corrección bajo concurrencia SIN locks explícitos de aplicación: el
     incremento es un único ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING
     count``, que PostgreSQL serializa a nivel de fila. Múltiples workers/
     procesos incrementando la MISMA clave en el MISMO instante nunca pueden
     pisarse el conteo (a diferencia de un "leer, sumar en Python, escribir"
     que sí tiene condición de carrera).

Trade-off aceptado: en el borde entre dos ventanas un cliente puede emitir
hasta ~2x el límite nominal (ráfaga al final de una ventana + ráfaga al
inicio de la siguiente). Es el mismo trade-off que aceptan la mayoría de
rate limiters de ventana fija en producción (p.ej. el "fixed window counter"
de Cloudflare/Stripe-style); para las clases de endpoint de esta API
(auth/api/webhooks, límites de decenas a cientos por minuto) es una
degradación aceptable frente a la alternativa real hoy: sin límite
compartido en absoluto entre workers.

Por tenant, no solo por IP
----------------------------
La clave de rate limiting (``key``) puede incluir el ``tenant_id`` resuelto
por el llamador (p.ej. ``f"tenant:{tenant_id}:{endpoint_class}"``) en vez de
la IP del cliente. Esta capa es agnóstica al esquema de clave — igual que los
backends Redis/memoria existentes — pero además persiste ``tenant_id`` como
columna propia (nullable) para que las peticiones sin tenant resuelto
(anónimas / pre-auth) puedan seguir limitándose por IP sin romper el
contrato, y para permitir auditoría/reporting "cuánto está consumiendo el
tenant X" sin tener que parsear la clave.

Uso:

    from b2b_ai.infrastructure.rate_limit_store import RateLimitStore

    store = RateLimitStore()  # DSN de B2B_DB_URL / DATABASE_URL
    allowed, remaining, reset_ts = store.check_and_consume(
        key="tenant:42:api", limit=100, window_seconds=60, tenant_id=42,
    )
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional, Tuple

# Nombre de la tabla. Ver migración migrations/versions/0015_rate_limit_windows.py
TABLE = "rate_limit_windows"

# Ventana mínima para evitar división/floor por cero con configuraciones
# erróneas (limit/window <= 0).
_MIN_WINDOW_SECONDS = 1.0


def _is_postgres_dsn(dsn: str) -> bool:
    """True si `dsn` apunta a PostgreSQL (postgresql:// o postgres://).

    Chequeo local y deliberadamente duplicado (en vez de importar desde
    b2b_ai.db.adapter_factory) para que este módulo no dependa de NINGÚN
    archivo de b2b_ai/db/ — cero acoplamiento con el cluster db-core.
    """
    t = (dsn or "").strip().lower()
    return t.startswith("postgresql://") or t.startswith("postgres://")


def resolve_dsn(explicit: Optional[str] = None) -> Optional[str]:
    """DSN de PostgreSQL para el store, o None si no hay uno configurado.

    Orden: `explicit` > B2B_DB_URL > DATABASE_URL. Si el valor resuelto no es
    un DSN de PostgreSQL (p.ej. apunta a SQLite en dev), devuelve None — el
    llamador debe hacer fallback a otro backend.
    """
    dsn = explicit or os.environ.get("B2B_DB_URL") or os.environ.get("DATABASE_URL")
    if dsn and _is_postgres_dsn(dsn):
        return dsn
    return None


class RateLimitStoreUnavailable(RuntimeError):
    """No hay DSN de PostgreSQL configurado o la conexión falló al crear el pool."""


class RateLimitStore:
    """Backend de rate limiting persistido en PostgreSQL, ventana fija.

    Expone el mismo contrato mínimo que los backends en memoria/Redis de
    ``b2b_ai/api/rate_limiter.py`` (``check_and_consume``, ``get_usage``,
    ``reset``, ``health``) para poder usarse como reemplazo directo, más un
    método de mantenimiento (`purge_expired`) que no tiene equivalente en
    Redis (que expira claves solo) porque una tabla SQL no expira sola.
    """

    def __init__(self, dsn: Optional[str] = None, min_size: int = 1,
                 max_size: int = 5, connect_timeout: float = 3.0) -> None:
        dsn = resolve_dsn(dsn)
        if not dsn:
            raise RateLimitStoreUnavailable(
                "No hay DSN de PostgreSQL (B2B_DB_URL / DATABASE_URL) para "
                "el rate limit store."
            )
        # Import tardío: psycopg/psycopg_pool son dependencias del extra de
        # producción; que fallen aquí (import) o al abrir el pool debe dejar
        # al llamador decidir el fallback, no tumbar el proceso.
        import psycopg  # noqa: F401 — valida que el driver esté instalado
        from psycopg_pool import ConnectionPool

        self._dsn = dsn
        self._lock = threading.Lock()
        try:
            self._pool = ConnectionPool(
                dsn,
                min_size=min_size,
                max_size=max_size,
                open=True,
                timeout=connect_timeout,
                kwargs={"autocommit": True},
            )
            # Falla rápido si PostgreSQL no es alcanzable, en vez de dejar
            # que el primer request de verdad tropiece con el timeout.
            with self._pool.connection(timeout=connect_timeout) as conn:
                conn.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            raise RateLimitStoreUnavailable(
                f"No se pudo conectar a PostgreSQL para rate limiting: {exc}"
            ) from exc

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _window_start(now: float, window_seconds: float) -> int:
        window_seconds = max(_MIN_WINDOW_SECONDS, float(window_seconds))
        return int(now // window_seconds) * int(window_seconds)

    # -- API tipo backend (compatible con _RedisBackend/_MemoryBackend) -
    def check_and_consume(
        self,
        key: str,
        limit: int,
        window_seconds: float,
        tenant_id: Optional[int] = None,
        now: Optional[float] = None,
    ) -> Tuple[int, float]:
        """Consume una unidad de `key` en la ventana actual.

        Returns:
            (remaining, reset_ts) — `remaining` como max(0, limit - count)
            tras este consumo; `reset_ts` (epoch UTC) cuando abre la
            siguiente ventana. `remaining == 0` puede significar "esta
            petición fue exactamente la número `limit`" (permitida) o
            "ya se excedió" — igual que los backends existentes, el
            llamador debe usar `get_usage` para desambiguar si lo necesita
            (ver EnterpriseRateLimitMiddleware.dispatch).
        """
        now = time.time() if now is None else now
        window_seconds = max(_MIN_WINDOW_SECONDS, float(window_seconds))
        window_start = self._window_start(now, window_seconds)

        sql = f"""
            INSERT INTO {TABLE} (key, tenant_id, window_start, count, updated_at)
            VALUES (%s, %s, %s, 1, now())
            ON CONFLICT (key, window_start)
            DO UPDATE SET count = {TABLE}.count + 1, updated_at = now()
            RETURNING count
        """
        with self._pool.connection() as conn:
            cur = conn.execute(sql, (key, tenant_id, window_start))
            count = cur.fetchone()[0]

        remaining = max(0, int(limit) - int(count))
        reset_ts = float(window_start) + window_seconds
        return remaining, reset_ts

    def get_usage(self, key: str, window_seconds: float,
                  now: Optional[float] = None) -> int:
        """Conteo actual de `key` en la ventana vigente (no consume)."""
        now = time.time() if now is None else now
        window_start = self._window_start(now, window_seconds)
        sql = f"SELECT count FROM {TABLE} WHERE key = %s AND window_start = %s"
        with self._pool.connection() as conn:
            row = conn.execute(sql, (key, window_start)).fetchone()
        return int(row[0]) if row else 0

    def reset(self, key: Optional[str] = None) -> None:
        """Borra el estado de `key` (todas sus ventanas), o toda la tabla si
        `key` es None (uso: tests / operación manual, no producción normal).
        """
        with self._pool.connection() as conn:
            if key is None:
                conn.execute(f"DELETE FROM {TABLE}")
            else:
                conn.execute(f"DELETE FROM {TABLE} WHERE key = %s", (key,))

    def health(self) -> bool:
        try:
            with self._pool.connection(timeout=1.0) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    def usage_by_tenant(self, tenant_id: int, window_seconds: float,
                        now: Optional[float] = None) -> int:
        """Suma de peticiones consumidas por `tenant_id` en la ventana
        vigente, a través de TODAS las claves (endpoints/clases) que
        registraron ese tenant_id. Solo posible porque persistimos
        `tenant_id` como columna propia y no solo embebido en `key` — es la
        pieza que permite reportar/auditar consumo "por tenant" de verdad.
        """
        now = time.time() if now is None else now
        window_start = self._window_start(now, window_seconds)
        sql = (
            f"SELECT COALESCE(SUM(count), 0) FROM {TABLE} "
            f"WHERE tenant_id = %s AND window_start = %s"
        )
        with self._pool.connection() as conn:
            row = conn.execute(sql, (tenant_id, window_start)).fetchone()
        return int(row[0]) if row else 0

    def purge_expired(self, older_than_seconds: float = 3600.0,
                      now: Optional[float] = None) -> int:
        """Borra ventanas más viejas que `older_than_seconds`. Idempotente y
        seguro de llamar concurrentemente desde varios workers (un DELETE
        por rango de tiempo, sin estado compartido en Python).

        No hay TTL nativo en una tabla de PostgreSQL como en Redis — este
        método es el equivalente, pensado para un cron/tarea periódica
        (ver docs de despliegue). Sin él la tabla crece indefinidamente:
        una fila nueva por (key, ventana) que se haya usado alguna vez.

        Returns:
            Número de filas borradas.
        """
        now = time.time() if now is None else now
        cutoff = int(now - older_than_seconds)
        sql = f"DELETE FROM {TABLE} WHERE window_start < %s"
        with self._pool.connection() as conn:
            cur = conn.execute(sql, (cutoff,))
            return cur.rowcount

    def close(self) -> None:
        try:
            self._pool.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Fábrica perezosa por DSN, para reutilizar un único pool por proceso (igual
# que `_PG_POOLS` en b2b_ai/db/db.py, pero con su propio diccionario — sin
# importar ni tocar ese módulo).
# ---------------------------------------------------------------------------
_STORES: dict = {}
_STORES_LOCK = threading.Lock()


def get_store(dsn: Optional[str] = None) -> Optional[RateLimitStore]:
    """Devuelve un `RateLimitStore` compartido por proceso para `dsn`
    (o el resuelto de env), o None si no hay PostgreSQL disponible/alcanzable.

    Pensado para el `_get_backend()` de b2b_ai/api/rate_limiter.py: probar
    Postgres sin que un DSN mal configurado o una BD caída tumben el arranque
    de la app — el llamador hace fallback a memoria si esto devuelve None.
    """
    resolved = resolve_dsn(dsn)
    if not resolved:
        return None
    with _STORES_LOCK:
        store = _STORES.get(resolved)
        if store is not None:
            return store
        try:
            store = RateLimitStore(dsn=resolved)
        except RateLimitStoreUnavailable:
            return None
        _STORES[resolved] = store
        return store


def _reset_store_cache_for_tests() -> None:
    """Cierra y limpia la caché de stores. Solo para uso en tests."""
    with _STORES_LOCK:
        for store in _STORES.values():
            store.close()
        _STORES.clear()
