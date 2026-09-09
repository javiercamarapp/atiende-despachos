# -*- coding: utf-8 -*-
"""
job_store.py — Persistencia de jobs asíncronos en PostgreSQL.

Por qué existe (PO-02 / SCALE-02)
----------------------------------
Dos lugares de este repo guardan el estado de un job de procesamiento en un
diccionario de proceso:

  * ``b2b_ai/features/bookkeeping/pipeline.py`` —
    ``PipelineOrchestrator._jobs: Dict[str, PipelineJob]``. Cada llamada a
    ``process_cfdis()`` crea un ``PipelineJob`` y lo guarda ahí; las rutas
    (``/api/v1/bookkeeping/status?job_id=...``) lo leen después.
  * ``b2b_ai/api/v2.py`` — ``_JOBS: dict`` para los batches async
    (``POST /api/v2/batch`` con ``async: true`` corre en un ``threading.Thread``
    y el resultado se consulta con ``GET /api/v2/batch/{id}``).

En ambos casos, si el proceso se reinicia (deploy, crash, restart de pod) o
si hay más de una réplica sirviendo tráfico, ese estado desaparece o queda
invisible para las demás réplicas — un cliente que hizo polling sobre un
``job_id`` recibe 404 aunque el trabajo haya completado exitosamente.

Este módulo añade un backend persistido en PostgreSQL para ese estado,
reutilizable por ambos llamadores (columna ``job_type`` los distingue).

Aislamiento del cluster db-core
--------------------------------
Igual que ``b2b_ai/infrastructure/rate_limit_store.py`` (mismo criterio),
este módulo NO importa ``b2b_ai/db/db.py`` ni reutiliza su pool. Abre su
propio ``psycopg_pool.ConnectionPool`` diminuto, con su propio DSN resuelto
de forma independiente. Es deliberado: minimiza el área de conflicto de
merge con trabajo concurrente sobre ``db.py`` y permite borrar/reemplazar
este módulo sin tocar la capa de datos "core".

Payload como TEXT (no JSONB)
------------------------------
El resultado completo del job (para bookkeeping: clasificaciones, pólizas,
referencias ERP, conciliación; para batch v2: summary + results) se guarda
serializado con ``json.dumps``/``json.loads`` en una columna ``TEXT``, no
``JSONB``. A diferencia de ``audit_log.payload``/``webhook_deliveries.payload``
en ``b2b_ai/db/models.py`` (que sí usan ``JSONB``, por ser documentos que la
capa de datos "core" consulta), este módulo es deliberadamente independiente
de esa capa (ver ``_is_postgres_dsn`` arriba) y no necesita consultar dentro
del payload -- lo trata siempre como blob opaco escribe/lee completo. TEXT
evita depender de cómo cada versión del driver adapta/decodifica jsonb, y
hace trivial mover el payload a otro almacén de texto plano si hiciera falta.

Fallback opcional: sin DSN de PostgreSQL configurado (dev/test con SQLite),
``get_store()`` devuelve ``None`` y el llamador debe seguir usando su
fallback en memoria — igual que ``rate_limit_store.get_store()``. Esto es
lo que mantiene verdes las suites existentes que instancian
``PipelineOrchestrator`` sin ninguna base de datos Postgres disponible.

Uso:

    from b2b_ai.infrastructure.job_store import get_store

    store = get_store()  # None si no hay Postgres configurado/alcanzable
    if store is not None:
        store.save_job(job_id="abc123", job_type="bookkeeping_pipeline",
                       tenant_id="t1", stage="completed", progress_pct=100.0,
                       payload={...}, errors=[])
        row = store.get_job("abc123")
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

# Nombre de la tabla. Ver migración migrations/versions/0016_pipeline_jobs.py
TABLE = "pipeline_jobs"


def _is_postgres_dsn(dsn: str) -> bool:
    """True si `dsn` apunta a PostgreSQL (postgresql:// o postgres://).

    Chequeo local y deliberadamente duplicado (en vez de importar desde
    b2b_ai.db.adapter_factory o b2b_ai.infrastructure.rate_limit_store) para
    que este módulo no dependa de NINGÚN archivo de b2b_ai/db/ — cero
    acoplamiento con el cluster db-core.
    """
    t = (dsn or "").strip().lower()
    return t.startswith("postgresql://") or t.startswith("postgres://")


def resolve_dsn(explicit: Optional[str] = None) -> Optional[str]:
    """DSN de PostgreSQL para el store, o None si no hay uno configurado.

    Orden: `explicit` > B2B_DB_URL > DATABASE_URL. Si el valor resuelto no es
    un DSN de PostgreSQL (p.ej. apunta a SQLite en dev), devuelve None — el
    llamador debe hacer fallback a memoria.
    """
    dsn = explicit or os.environ.get("B2B_DB_URL") or os.environ.get("DATABASE_URL")
    if dsn and _is_postgres_dsn(dsn):
        return dsn
    return None


class JobStoreUnavailable(RuntimeError):
    """No hay DSN de PostgreSQL configurado o la conexión falló al crear el pool."""


class JobStore:
    """Backend de persistencia de jobs asíncronos en PostgreSQL.

    Un "job" aquí es genérico: un `job_id` único, un `job_type` (namespace
    lógico — p.ej. "bookkeeping_pipeline" o "batch_v2", para que distintos
    llamadores compartan la tabla sin colisionar), un `tenant_id`, una
    `stage`/estado como texto libre, un `progress_pct`, un `payload` (dict
    JSON-safe con el resultado completo) y una lista de `errors`.
    """

    def __init__(self, dsn: Optional[str] = None, min_size: int = 1,
                 max_size: int = 5, connect_timeout: float = 3.0) -> None:
        dsn = resolve_dsn(dsn)
        if not dsn:
            raise JobStoreUnavailable(
                "No hay DSN de PostgreSQL (B2B_DB_URL / DATABASE_URL) para "
                "el job store."
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
            raise JobStoreUnavailable(
                f"No se pudo conectar a PostgreSQL para el job store: {exc}"
            ) from exc

    # -- escritura ------------------------------------------------------
    def save_job(
        self,
        job_id: str,
        job_type: str,
        tenant_id: str,
        stage: str,
        progress_pct: float,
        payload: Dict[str, Any],
        errors: Optional[List[str]] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Upsert del estado completo de un job (insert-or-replace por job_id).

        Se llama en cada checkpoint relevante del pipeline (no solo al
        terminar) para que el estado sea visible/recuperable aun si el
        proceso muere a mitad de un job largo.

        `started_at` solo se fija la primera vez (COALESCE contra el valor
        ya guardado) — llamadas posteriores para el mismo job_id con
        started_at=None no lo borran.
        """
        sql = f"""
            INSERT INTO {TABLE}
                (job_id, job_type, tenant_id, stage, progress_pct, payload,
                 errors, started_at, completed_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (job_id) DO UPDATE SET
                job_type = EXCLUDED.job_type,
                tenant_id = EXCLUDED.tenant_id,
                stage = EXCLUDED.stage,
                progress_pct = EXCLUDED.progress_pct,
                payload = EXCLUDED.payload,
                errors = EXCLUDED.errors,
                started_at = COALESCE({TABLE}.started_at, EXCLUDED.started_at),
                completed_at = COALESCE(EXCLUDED.completed_at, {TABLE}.completed_at),
                updated_at = now()
        """
        params = (
            job_id,
            job_type,
            tenant_id or "",
            stage,
            float(progress_pct),
            json.dumps(payload, default=str),
            json.dumps(errors or [], default=str),
            started_at,
            completed_at,
        )
        with self._pool.connection() as conn:
            conn.execute(sql, params)

    # -- lectura ----------------------------------------------------------
    _COLUMNS = (
        "job_id", "job_type", "tenant_id", "stage", "progress_pct",
        "payload", "errors", "started_at", "completed_at", "created_at",
        "updated_at",
    )

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        d = dict(zip(self._COLUMNS, row))
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        d["errors"] = json.loads(d["errors"]) if d["errors"] else []
        return d

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Devuelve el job (dict con `payload` ya deserializado) o None."""
        cols = ", ".join(self._COLUMNS)
        sql = f"SELECT {cols} FROM {TABLE} WHERE job_id = %s"
        with self._pool.connection() as conn:
            row = conn.execute(sql, (job_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_jobs(
        self,
        job_type: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> List[Dict[str, Any]]:
        """Lista jobs, más recientes primero (por `started_at`, luego
        `created_at`). Filtra por `job_type`/`tenant_id` cuando se pasan.
        `limit=None` devuelve todos los jobs que matcheen (usado por
        callers que necesitan el histórico completo, p.ej.
        PipelineOrchestrator.get_suggestions()).
        """
        cols = ", ".join(self._COLUMNS)
        clauses = []
        params: List[Any] = []
        if job_type is not None:
            clauses.append("job_type = %s")
            params.append(job_type)
        if tenant_id:
            clauses.append("tenant_id = %s")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {cols} FROM {TABLE} {where} "
            f"ORDER BY started_at DESC NULLS LAST, created_at DESC"
        )
        if limit is not None:
            sql += " LIMIT %s"
            params.append(int(limit))
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_jobs(
        self, job_type: Optional[str] = None, tenant_id: Optional[str] = None,
    ) -> int:
        """Cuenta jobs que matcheen `job_type`/`tenant_id` sin traer payloads
        a Python — usado por health checks (p.ej. `async_jobs` en
        GET /api/v2/health)."""
        clauses = []
        params: List[Any] = []
        if job_type is not None:
            clauses.append("job_type = %s")
            params.append(job_type)
        if tenant_id:
            clauses.append("tenant_id = %s")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) FROM {TABLE} {where}"
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def delete_job(self, job_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(f"DELETE FROM {TABLE} WHERE job_id = %s", (job_id,))

    def health(self) -> bool:
        try:
            with self._pool.connection(timeout=1.0) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        try:
            self._pool.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Fábrica perezosa por DSN, para reutilizar un único pool por proceso (igual
# que `_STORES` en b2b_ai/infrastructure/rate_limit_store.py).
# ---------------------------------------------------------------------------
_STORES: dict = {}
_STORES_LOCK = threading.Lock()


def get_store(dsn: Optional[str] = None) -> Optional[JobStore]:
    """Devuelve un `JobStore` compartido por proceso para `dsn` (o el
    resuelto de env), o None si no hay PostgreSQL disponible/alcanzable.

    Pensado para que los llamadores (PipelineOrchestrator, api/v2.py) hagan
    fallback a un dict en memoria cuando esto devuelve None — igual que
    `rate_limit_store.get_store()` — así las suites que corren sin Postgres
    configurado (SQLite de dev/test) siguen funcionando sin cambios.
    """
    resolved = resolve_dsn(dsn)
    if not resolved:
        return None
    with _STORES_LOCK:
        store = _STORES.get(resolved)
        if store is not None:
            return store
        try:
            store = JobStore(dsn=resolved)
        except JobStoreUnavailable:
            return None
        _STORES[resolved] = store
        return store


def _reset_store_cache_for_tests() -> None:
    """Cierra y limpia la caché de stores. Solo para uso en tests."""
    with _STORES_LOCK:
        for store in _STORES.values():
            store.close()
        _STORES.clear()
