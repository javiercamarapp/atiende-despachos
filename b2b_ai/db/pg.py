# -*- coding: utf-8 -*-
"""
pg.py — Backend PostgreSQL para la capa de datos (producción).

La capa `Database` (db.py) está escrita contra sqlite3 (conexión por hilo,
placeholders `?`, filas tipo dict). Para migrar a PostgreSQL SIN reescribir
los ~60 métodos de db.py, este módulo ofrece un conector que preserva el
mismo contrato:

  * `conn.execute(sql, params)` — traduce `?` -> `%s` y delega en psycopg3.
  * filas tipo dict que además soportan acceso posicional (`r[0]`), igual que
    `sqlite3.Row`.
  * `cursor.lastrowid` — psycopg3 no lo trae; lo derivamos de `lastval()`.
  * pool de conexiones con health check, retry y límites de tamaño.

Uso desde db.py:
    from b2b_ai.db.pg import PGPool
    pool = PGPool(os.environ["B2B_DB_URL"], min_size=2, max_size=10)
    with pool.connection() as conn:      # conn es PGConnection (wrapper)
        conn.execute("SELECT 1")
"""
from __future__ import annotations

import logging
import time

import psycopg
import psycopg_pool

logger = logging.getLogger("b2b_ai.db.pg")


def qmark_to_percent(sql: str) -> str:
    """Convierte placeholders `?` (sqlite) a `%s` (psycopg3).

    Convierte `?` -> `%s` y `:name` -> `%(name)s` (estilo SQLite) al estilo
    de psycopg3. Respeta cadenas literales simples/dobles para no tocar
    placeholders dentro de textos.
    """
    out, i, n = [], 0, len(sql)
    quote = None
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote and i + 1 < n and sql[i + 1] == quote:
                out.append(sql[i + 1])  # '' o "" escapado en SQL
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
        # Placeholder nombrado estilo SQLite `:name` -> psycopg `%(name)s`.
        # Solo cuando va seguido de un identificador (evita tocar
        # `::` de cast de PostgreSQL si lo hubiera, que no usamos aquí).
        if ch == ":" and i + 1 < n and (sql[i + 1].isalpha()
                                        or sql[i + 1] == "_"):
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            name = sql[i + 1:j]
            out.append(f"%({name})s")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class PGRecord(dict):
    """Fila tipo dict que también soporta acceso posicional (r[0])."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    """Factory psycopg3: recibe el cursor y devuelve make_row(values)."""
    names = [d.name for d in cursor.description] if cursor.description else []

    def make_row(values):
        return PGRecord(zip(names, values))

    return make_row


class PGCursor:
    """Envuelve un cursor psycopg3: traduce SQL y expone lastrowid."""

    def __init__(self, cursor):
        self._c = cursor

    def execute(self, sql, params=None):
        self._c.execute(qmark_to_percent(sql), params or ())
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def __iter__(self):
        # sqlite3.Cursor es iterable; el código (list_tenants, etc.) recorre
        # el resultado de execute() directamente.
        return iter(self._c)

    def __len__(self):
        return len(self._c)

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def lastrowid(self):
        """Id del último INSERT (psycopg3 no lo expone; se deriva de lastval)."""
        try:
            self._c.execute("SELECT lastval()")
            val = self._c.fetchone()[0]
            return int(val)
        except psycopg.Error:
            return None


class PGConnection:
    """Wrapper de psycopg3 Connection que preserva el API de sqlite3 usado
    por db.py: execute (con `?`), commit, rollback, close, executescript.

    Soporta `with conn:` — al salir devuelve la conexión al pool (vía el
    context manager que la prestó) en vez de cerrarla físicamente.
    """

    def __init__(self, raw_conn, release=None):
        # `raw_conn` es la conexión psycopg real; `release` es el context
        # manager del pool que la devuelve al pool al salir.
        self._c = raw_conn
        self._release = release
        self._c.row_factory = _row_factory

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def execute(self, sql, params=None):
        return PGCursor(self._c.cursor()).execute(sql, params)

    def executescript(self, sql):
        # Para migraciones se usa Alembic (migrations/). Aquí lo toleramos
        # ejecutando cada sentencia por separado (útil para --reset en dev).
        for stmt in self._split_statements(sql):
            if stmt.strip():
                self.execute(stmt)
        return self

    @staticmethod
    def _split_statements(sql):
        return [s for s in sql.split(";") if s.strip()]

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        # Devuelve la conexión al pool vía el context manager que la prestó.
        if self._release is not None:
            try:
                self._release.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                self._c.close()
            except Exception:  # noqa: BLE001
                pass

    def raw(self):
        return self._c


class PGPool:
    """Pool de conexiones PostgreSQL con health check, retry y límites.

    min_size / max_size limitan cuántas conexiones reales abre el pool
    (connection limits). `health_check` valida cada conexión al chequearla
    con `SELECT 1`. `connect_timeout` controla el timeout de apertura.
    """

    def __init__(self, dsn, min_size=1, max_size=10, connect_timeout=5,
                 retries=3, retry_delay=0.5, pool_timeout=10.0):
        self.dsn = dsn
        self.min_size = max(1, int(min_size))
        self.max_size = max(self.min_size, int(max_size))
        self.retries = int(retries)
        self.retry_delay = float(retry_delay)

        def _health(conn):
            try:
                conn.execute("SELECT 1").fetchone()
            except Exception:
                return False
            return True

        self._pool = psycopg_pool.ConnectionPool(
            dsn,
            min_size=self.min_size,
            max_size=self.max_size,
            open=False,
            kwargs={"connect_timeout": connect_timeout},
            check=_health,
            timeout=pool_timeout,
        )
        self._pool.open()
        self._open()

    def _open(self):
        # Asegura min_size conexiones sanas (abre y hace health check).
        last = None
        for attempt in range(self.retries):
            try:
                self._pool.wait()
                return
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("PG pool open attempt %s/%s failed: %s",
                               attempt + 1, self.retries, e)
                time.sleep(self.retry_delay * (attempt + 1))
        raise RuntimeError(f"No se pudo abrir el pool PostgreSQL: {last}")

    def connection(self):
        """Devuelve una PGConnection del pool (con retry ante fallo)."""
        last = None
        for attempt in range(self.retries):
            try:
                cm = self._pool.connection()
                raw = cm.__enter__()  # entra y obtiene la conexión real
                return PGConnection(raw, release=cm)
            except psycopg_pool.PoolTimeout:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("PG acquire attempt %s/%s failed: %s",
                               attempt + 1, self.retries, e)
                time.sleep(self.retry_delay * (attempt + 1))
        raise RuntimeError(f"No se pudo adquirir conexión PostgreSQL: {last}")

    def health_check(self):
        """Verifica conectividad real. Devuelve dict de estado."""
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1").fetchone()
            return {
                "ok": True,
                "min_size": self.min_size,
                "max_size": self.max_size,
                "active": getattr(self._pool, "_nconns", None),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def close(self):
        try:
            self._pool.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
