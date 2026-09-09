# -*- coding: utf-8 -*-
"""Tests para b2b_ai.infrastructure.rate_limit_store — rate limiting
persistido en PostgreSQL, por tenant, con múltiples workers reales.

Requieren un PostgreSQL alcanzable vía B2B_DB_URL (mismo patrón que
tests/test_pg_migrations.py). Cada módulo de test crea su propia base
dedicada (dropeada al final) para no pisar otros tests ni datos reales.

Cubre:
  - Semántica de ventana fija (permite hasta el límite, bloquea después,
    la ventana siguiente resetea el conteo).
  - Persistencia de tenant_id como columna propia (no solo en `key`) y
    agregación por tenant (`usage_by_tenant`).
  - FK real a `tenants(id)` (un tenant_id inexistente es rechazado por
    PostgreSQL, no solo "aceptado y silenciosamente ignorado").
  - reset() / purge_expired().
  - EL CASO CRÍTICO: multi-worker real. Un `RateLimitStore` nuevo (=
    "otro worker" que no comparte memoria de proceso) ve el mismo estado
    que uno que ya consumió del límite — la razón de ser de este módulo.
  - Concurrencia real con `multiprocessing`: N procesos independientes
    (cada uno abre su propio pool de conexión, como N workers de Gunicorn)
    incrementando la MISMA clave al mismo tiempo nunca producen conteos
    duplicados ni pierden incrementos, y el límite compartido se respeta
    EXACTAMENTE una vez entre todos los procesos (no una vez por proceso,
    que es el bug que este módulo reemplaza).
"""
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible"
)


def _split_dsn(dsn):
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        head, _, tail = dsn.partition("://")
        if "/" in tail:
            server, _, db = tail.rpartition("/")
            return f"{head}://{server}", db
    raise ValueError("DSN no soportado")


def _create_test_db():
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    dbname = f"b2b_rl_test_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        conn.close()
    return f"{server_dsn}/{dbname}", dbname


def _drop_test_db(dbname):
    import psycopg
    server_dsn, _ = _split_dsn(PG_DSN)
    conn = psycopg.connect(server_dsn, autocommit=True)
    try:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        conn.close()


def _migrate_to_head(dsn):
    env = dict(os.environ)
    env["B2B_DB_URL"] = dsn
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture(scope="module")
def pg_dsn():
    """DSN a una base de test ya migrada a head (creada/dropeada una vez
    por módulo — correr alembic para las 14 migraciones en cada test
    individual sería demasiado lento)."""
    dsn, dbname = _create_test_db()
    _migrate_to_head(dsn)
    yield dsn
    _drop_test_db(dbname)


@pytest.fixture
def store(pg_dsn):
    from b2b_ai.infrastructure.rate_limit_store import RateLimitStore
    s = RateLimitStore(dsn=pg_dsn)
    s.reset()  # aislar de cualquier fila que haya dejado otro test
    yield s
    s.reset()
    s.close()


def _make_tenant(pg_dsn, name="tenant-test"):
    import psycopg
    conn = psycopg.connect(pg_dsn, autocommit=True)
    try:
        row = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()
        return row[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Semántica básica de ventana fija
# ---------------------------------------------------------------------------
class TestFixedWindow:
    def test_allows_up_to_limit_then_blocks(self, store):
        key = f"k:{uuid.uuid4().hex}"
        now = 1_000_000.0
        for i in range(1, 6):
            remaining, reset_ts = store.check_and_consume(
                key, limit=5, window_seconds=60, now=now
            )
            assert remaining == max(0, 5 - i)
        # 6ª petición en la misma ventana: remaining ya es 0 y el conteo
        # real (get_usage) supera el límite -> es la señal de "bloqueado"
        # que usa EnterpriseRateLimitMiddleware.dispatch().
        remaining, _ = store.check_and_consume(
            key, limit=5, window_seconds=60, now=now
        )
        assert remaining == 0
        assert store.get_usage(key, window_seconds=60, now=now) == 6
        assert store.get_usage(key, window_seconds=60, now=now) > 5

    def test_window_rollover_resets_count(self, store):
        key = f"k:{uuid.uuid4().hex}"
        for _ in range(5):
            store.check_and_consume(key, limit=5, window_seconds=1, now=0.0)
        assert store.get_usage(key, window_seconds=1, now=0.0) == 5
        # Ventana siguiente (t=2, ventana de 1s -> window_start distinto):
        # el conteo debe partir de cero otra vez.
        remaining, _ = store.check_and_consume(
            key, limit=5, window_seconds=1, now=2.0
        )
        assert remaining == 4
        assert store.get_usage(key, window_seconds=1, now=2.0) == 1

    def test_reset_ts_matches_next_window_boundary(self, store):
        key = f"k:{uuid.uuid4().hex}"
        _, reset_ts = store.check_and_consume(
            key, limit=10, window_seconds=60, now=125.0
        )
        # window_start = floor(125/60)*60 = 120; próxima ventana en 180.
        assert reset_ts == 180.0


# ---------------------------------------------------------------------------
# reset() / purge_expired()
# ---------------------------------------------------------------------------
class TestMaintenance:
    def test_reset_single_key(self, store):
        key = f"k:{uuid.uuid4().hex}"
        for _ in range(3):
            store.check_and_consume(key, limit=100, window_seconds=60, now=0.0)
        assert store.get_usage(key, window_seconds=60, now=0.0) == 3
        store.reset(key)
        assert store.get_usage(key, window_seconds=60, now=0.0) == 0

    def test_purge_expired_removes_old_windows_only(self, store):
        old_key = f"k:{uuid.uuid4().hex}"
        new_key = f"k:{uuid.uuid4().hex}"
        # Ventana "vieja": ocurrió hace 2 horas.
        store.check_and_consume(old_key, limit=10, window_seconds=60, now=0.0)
        # Ventana "actual".
        now = 7200.0
        store.check_and_consume(new_key, limit=10, window_seconds=60, now=now)

        deleted = store.purge_expired(older_than_seconds=3600.0, now=now)
        assert deleted == 1
        assert store.get_usage(old_key, window_seconds=60, now=0.0) == 0
        assert store.get_usage(new_key, window_seconds=60, now=now) == 1


# ---------------------------------------------------------------------------
# Por tenant, no solo por IP: tenant_id es columna propia + FK real.
# ---------------------------------------------------------------------------
class TestTenantScoping:
    def test_tenant_id_persisted_and_summable_across_keys(self, store, pg_dsn):
        tid = _make_tenant(pg_dsn, "tenant-scoping")
        now = 500.0
        store.check_and_consume(
            f"rl:tenant:{tid}:api", limit=1000, window_seconds=60,
            tenant_id=tid, now=now,
        )
        store.check_and_consume(
            f"rl:tenant:{tid}:auth", limit=1000, window_seconds=60,
            tenant_id=tid, now=now,
        )
        store.check_and_consume(
            f"rl:tenant:{tid}:auth", limit=1000, window_seconds=60,
            tenant_id=tid, now=now,
        )
        # 1 + 2 peticiones repartidas en dos "endpoint class" distintas,
        # sumadas por tenant_id real (columna), no por parseo de `key`.
        assert store.usage_by_tenant(tid, window_seconds=60, now=now) == 3

    def test_two_tenants_do_not_share_bucket(self, store, pg_dsn):
        t1 = _make_tenant(pg_dsn, "tenant-a")
        t2 = _make_tenant(pg_dsn, "tenant-b")
        now = 900.0
        for _ in range(5):
            store.check_and_consume(
                f"rl:tenant:{t1}:api", limit=5, window_seconds=60,
                tenant_id=t1, now=now,
            )
        # tenant 2 nunca tocó su bucket -> sigue con cupo entero, aunque
        # tenant 1 (identificador DISTINTO, no IP) ya agotó el suyo.
        remaining, _ = store.check_and_consume(
            f"rl:tenant:{t2}:api", limit=5, window_seconds=60,
            tenant_id=t2, now=now,
        )
        assert remaining == 4

    def test_unknown_tenant_id_rejected_by_real_fk(self, store):
        """Un tenant_id que no existe en `tenants` debe rechazarlo
        PostgreSQL de verdad (constraint real, no solo un comentario)."""
        import psycopg
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            store.check_and_consume(
                "rl:tenant:999999999:api", limit=10, window_seconds=60,
                tenant_id=999999999, now=0.0,
            )


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------
def test_health_true_when_reachable(store):
    assert store.health() is True


# ---------------------------------------------------------------------------
# EL CASO CRÍTICO: multi-worker.
# ---------------------------------------------------------------------------
class TestMultiWorker:
    def test_second_independent_instance_sees_same_state(self, pg_dsn):
        """Simula dos workers que arrancaron por separado (Gunicorn
        --workers 2): cada uno abre su PROPIO RateLimitStore/pool, sin
        compartir memoria de proceso. El segundo debe ver el consumo que
        hizo el primero -- justo lo que el backend en memoria NUNCA podía
        garantizar (cada worker llevaba su propio diccionario)."""
        from b2b_ai.infrastructure.rate_limit_store import RateLimitStore

        key = f"k:{uuid.uuid4().hex}"
        worker_a = RateLimitStore(dsn=pg_dsn)
        worker_b = RateLimitStore(dsn=pg_dsn)
        try:
            now = 10_000.0
            for _ in range(5):
                remaining, _ = worker_a.check_and_consume(
                    key, limit=5, window_seconds=60, now=now
                )
            assert remaining == 0
            # worker_b es una instancia/pool totalmente distinta -- si el
            # estado viviera en memoria de proceso (el bug original) vería
            # el bucket vacío y permitiría 5 peticiones más.
            remaining_b, _ = worker_b.check_and_consume(
                key, limit=5, window_seconds=60, now=now
            )
            assert remaining_b == 0
            assert worker_b.get_usage(key, window_seconds=60, now=now) == 6
        finally:
            worker_a.close()
            worker_b.close()


def _worker_hammer(args):
    """Top-level (picklable) para multiprocessing con start method
    'spawn': cada proceso hijo abre su PROPIO pool psycopg -- nunca se
    hereda una conexión abierta a través de fork/spawn."""
    dsn, key, limit, window_seconds, now, n_requests = args
    from b2b_ai.infrastructure.rate_limit_store import RateLimitStore

    s = RateLimitStore(dsn=dsn, min_size=1, max_size=2)
    remainings = []
    try:
        for _ in range(n_requests):
            remaining, _ = s.check_and_consume(
                key, limit=limit, window_seconds=window_seconds, now=now
            )
            remainings.append(remaining)
    finally:
        s.close()
    return remainings


@pytest.mark.slow
class TestMultiProcessConcurrency:
    def test_concurrent_processes_never_lose_or_duplicate_increments(self, pg_dsn):
        """N procesos de SO reales (no hilos -- multiprocessing con start
        method 'spawn', cada uno con su propio pool de conexión, como N
        workers de Gunicorn en máquinas/containers distintos) incrementan
        la MISMA clave al mismo tiempo. Con `limit` muy por encima del
        total de peticiones, cada llamada exitosa debe recibir un
        `remaining` ÚNICO (remaining = limit - count): si el incremento
        en PostgreSQL no fuera atómico, dos procesos podrían leer el mismo
        conteo y pisarse (remaining duplicado) o perderse un incremento
        (un hueco en la secuencia).
        """
        n_procs = 4
        n_per_proc = 50
        total = n_procs * n_per_proc
        limit = 1_000_000  # muy por encima de `total`: remaining siempre > 0
        key = f"k:{uuid.uuid4().hex}"
        now = 20_000.0

        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=n_procs) as pool:
            results = pool.map(
                _worker_hammer,
                [(pg_dsn, key, limit, 60, now, n_per_proc)] * n_procs,
            )

        all_remaining = [r for sub in results for r in sub]
        assert len(all_remaining) == total

        counts = sorted(limit - r for r in all_remaining)
        # Sin pérdidas ni duplicados: el conjunto de conteos asignados es
        # EXACTAMENTE la permutación 1..total, sin huecos ni repetidos.
        assert counts == list(range(1, total + 1)), (
            f"conteos duplicados o huecos bajo concurrencia real: {counts}"
        )
        assert len(set(counts)) == total  # explícito: cero duplicados

    def test_shared_limit_enforced_exactly_once_across_processes(self, pg_dsn):
        """La prueba que reproduce el bug original: con el limiter en
        memoria, `n_procs` procesos cada uno con su propio diccionario
        habrían permitido `limit` peticiones POR PROCESO (limit * n_procs
        en total). Con el store persistido, el límite se aplica UNA sola
        vez para todos los procesos juntos.
        """
        n_procs = 4
        n_per_proc = 40
        limit = 50  # bug viejo: hubiera permitido hasta 50*4=200 en total
        key = f"k:{uuid.uuid4().hex}"
        now = 30_000.0

        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=n_procs) as pool:
            results = pool.map(
                _worker_hammer,
                [(pg_dsn, key, limit, 60, now, n_per_proc)] * n_procs,
            )

        all_remaining = [r for sub in results for r in sub]
        # Total de peticiones que de verdad cupieron dentro del límite
        # compartido (conteo real <= limit), verificado con get_usage tras
        # que todos los procesos terminaron.
        from b2b_ai.infrastructure.rate_limit_store import RateLimitStore
        checker = RateLimitStore(dsn=pg_dsn)
        try:
            final_count = checker.get_usage(key, window_seconds=60, now=now)
        finally:
            checker.close()

        # Se hicieron n_procs*n_per_proc intentos, pero el conteo real en
        # PostgreSQL (compartido por los 4 "workers") es exactamente ese
        # total -- no se resetea ni se pierde por proceso.
        assert final_count == n_procs * n_per_proc
        # Y ese conteo total EXCEDE el límite (lo cual es correcto: cada
        # intento se registra; lo que importa es que remaining==0 empieza a
        # aparecer justo después del intento número `limit`, igual para
        # TODOS los procesos, no una vez por cada uno).
        assert final_count > limit
        # remaining = max(0, limit - count) es > 0 solo para los conteos
        # 1..limit-1 (el conteo == limit ya deja remaining en 0, aunque esa
        # petición también cupo dentro del cupo). Con conteos únicos
        # 1..total garantizados por el test anterior, exactamente
        # `limit - 1` peticiones vieron remaining > 0 -- el límite se
        # aplicó UNA vez para los 4 procesos juntos, no una vez por cada uno
        # (que hubiera dado remaining > 0 hasta 4*limit veces).
        admitted_with_headroom = sum(1 for r in all_remaining if r > 0)
        assert admitted_with_headroom == limit - 1
