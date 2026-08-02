# -*- coding: utf-8 -*-
"""
db.py — Capa de base de datos multi-tenant (SQLite para dev, PG-ready).

Siempre filtra por tenant_id en las lecturas para aislar datos entre
despachos. Aplica migraciones versionadas automáticamente.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

from b2b_ai.db.models import MIGRATIONS

DEFAULT_DB = (os.environ.get("B2B_DB_URL")
              or os.environ.get("DATABASE_URL")  # Railway/Heroku auto-inject
              or os.environ.get("B2B_DB_PATH")
              or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__)))), "b2b_ai.db"))

# Import adapter factory for PostgreSQL/SQLite switching
from b2b_ai.db.adapter_factory import create_adapter, is_postgres as _is_postgres_url

# Campos de tenant_config que se cifran en reposo (PII / credenciales).
# Cualquier otro valor se guarda en claro.
_SENSITIVE_CONFIG_KEYS = {"webhook_url", "notif_recipient", "whatsapp_token"}


# Pool compartido por DSN: varios `Database()` sobre el mismo PostgreSQL
# reutilizan el mismo PGPool (evita abrir N pools y desperdiciar conexiones).
_PG_POOLS: dict = {}


def _is_postgres(target: str) -> bool:
    """True si `target` es un DSN de PostgreSQL (postgresql:// o postgres://)."""
    t = (target or "").strip().lower()
    return t.startswith("postgresql://") or t.startswith("postgres://")


def _get_pg_pool(dsn: str):
    """Devuelve el PGPool compartido para un DSN (uno por proceso)."""
    from b2b_ai.db.pg import PGPool
    if dsn not in _PG_POOLS:
        _PG_POOLS[dsn] = PGPool(
            dsn,
            min_size=int(os.environ.get("B2B_PG_POOL_MIN", "2")),
            max_size=int(os.environ.get("B2B_PG_POOL_MAX", "10")),
            retries=int(os.environ.get("B2B_PG_RETRIES", "3")),
        )
    return _PG_POOLS[dsn]


def _is_integrity_error(exc: Exception) -> bool:
    """True si `exc` es una violación de unicidad/integridad (SQLite o PG)."""
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        from psycopg import errors as pgerr
        return isinstance(exc, pgerr.UniqueViolation)
    except Exception:  # noqa: BLE001 — psycopg no instalado (modo SQLite)
        return False


def _encrypt_config_value(key: str, value) -> str:
    """Cifra `value` si `key` es sensible y hay B2B_ENCRYPTION_KEY."""
    if key not in _SENSITIVE_CONFIG_KEYS or not isinstance(value, str):
        return value
    from b2b_ai.api.security import encrypt_field
    return encrypt_field(value)


def _decrypt_config_value(key: str, value) -> str:
    """Descifra `value` si `key` es sensible (o devuelve tal cual)."""
    if key not in _SENSITIVE_CONFIG_KEYS or not isinstance(value, str):
        return value
    from b2b_ai.api.security import decrypt_field
    return decrypt_field(value)


class Database:
    def __init__(self, path=DEFAULT_DB, migrate=True):
        self.path = path
        self._is_pg = _is_postgres(path)
        # Conexión por hilo (thread-local). Con SQLite es el patrón correcto
        # para servir la app desde el threadpool de FastAPI/uvicorn: una sola
        # sqlite3.Connection compartida entre hilos NO es segura y crashea
        # (SIGSEGV) bajo carga concurrente. Con PostgreSQL, cada thread tiene
        # su propia conexión checada del pool compartido.
        self._local = threading.local()
        self._connections: set = set()
        self._conn_lock = threading.Lock()
        self._data_version = 0
        self._version_lock = threading.Lock()
        if migrate:
            self.migrate()
        self.conn.commit()

    # ---- Invalidador de cache (FASE perf) ----
    # Las lecturas agregadas (/api/v1/stats, dashboard) se cachean con TTL,
    # pero para que el cache nunca sirva datos viejos tras una escritura, cada
    # escritura de facturas sube `data_version`. Los endpoints de lectura
    # incluyen esa versión en la key del cache: al cambiar la versión, la key
    # deja de existir y se recalcula al momento.
    def data_version(self) -> int:
        return self._data_version

    def _bump_version(self) -> None:
        with self._version_lock:
            self._data_version += 1

    @property
    def conn(self):
        """Conexión del hilo actual (SQLite o PostgreSQL), creada perezosamente."""
        if self._is_pg:
            return self._pg_conn()
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                # WAL: permite lecturas concurrentes con escritura y reduce
                # 'database is locked'. En :memory: no aplica y es un no-op.
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                pass
            conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn = conn
            with self._conn_lock:
                self._connections.add(conn)
            # Migraciones idempotentes por conexión nueva (CREATE IF NOT EXISTS).
            self.migrate()
        return conn

    def _pg_conn(self):
        """Conexión PostgreSQL del hilo actual, checada del pool compartido."""
        conn = getattr(self._local, "conn", None)
        # Detect stale connection released by __exit__ or close()
        if conn is not None and getattr(conn, "_released", False):
            self._local.conn = None
            conn = None
        if conn is None:
            pool = _get_pg_pool(self.path)
            conn = pool.connection()
            self._local.conn = conn
            with self._conn_lock:
                self._connections.add(conn)
            self.migrate()
        return conn

    def close(self):
        """Devuelve/cierra todas las conexiones creadas (todas las threads)."""
        with self._conn_lock:
            conns = list(self._connections)
            self._connections.clear()
        for c in conns:
            try:
                c.close()  # PG: devuelve al pool; SQLite: cierra físicamente
            except Exception:  # noqa: BLE001
                pass
        # limpiar la referencia thread-local del hilo actual
        try:
            del self._local.conn
        except AttributeError:
            pass

    # ---- Migraciones ----
    # Con SQLite el esquema lo gestionan models.MIGRATIONS (idempotente y por
    # conexión). Con PostgreSQL la fuente de verdad es Alembic (migrations/):
    # este método garantiza que la base esté en head antes de usarse.
    def migrate(self):
        if self._is_pg:
            self._pg_migrate()
            return
        self.conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        applied = {r[0] for r in self.conn.execute("SELECT version FROM schema_version")}
        for m in MIGRATIONS:
            if m["version"] not in applied:
                with self.conn:
                    self.conn.executescript(m["sql"])
                    self.conn.execute("INSERT INTO schema_version(version) VALUES (?)",
                                      (m["version"],))

    def _pg_migrate(self):
        """Lleva la base PostgreSQL a `head` con Alembic (idempotente)."""
        from alembic.config import Config
        from alembic import command

        os.environ["B2B_DB_URL"] = self.path
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        alembic_ini = os.path.join(root, "alembic.ini")
        # If not found at the computed root (site-packages in Docker), fall back
        # to the working directory (e.g. /app) and the cwd-relative path.
        if not os.path.exists(alembic_ini):
            for cand in ("alembic.ini",
                         os.path.join(os.getcwd(), "alembic.ini")):
                if os.path.exists(cand):
                    alembic_ini = cand
                    break
        try:
            alembic_cfg = Config(alembic_ini)
            # Use "heads" instead of "head": el repo tiene migraciones con
            # ramas (revisiones 0005/0006 duplicadas) que crean múltiples
            # head revisions. "heads" aplica todas las ramas pendientes sin
            # el error "Multiple head revisions are present".
            command.upgrade(alembic_cfg, "heads")
        except Exception as e:
            raise RuntimeError(
                f"Fallo la migración Alembic a PostgreSQL: {e}")
        # Defensive: ensure the unique constraint needed by
        # upsert_outstanding_invoice() exists even if Alembic head
        # hasn't applied it yet (DB drift / partial migration).
        try:
            self.conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_outstanding_unique
                ON outstanding_invoices(tenant_id, factura_id)
            """)
        except Exception:  # noqa: BLE001
            pass  # table or index doesn't exist yet — fine

    def schema_version(self):
        if self._is_pg:
            try:
                row = self.conn.execute(
                    "SELECT version_num FROM alembic_version").fetchone()
                return 1 if row else 0
            except Exception:  # noqa: BLE001
                return 0
        try:
            return self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        except sqlite3.Error:
            return 0

    # ---- Tenants ----
    def create_tenant(self, name, rfc=""):
        cur = self.conn.execute("INSERT INTO tenants(name, rfc) VALUES (?, ?)", (name, rfc))
        self.conn.commit()
        return cur.lastrowid

    def list_tenants(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM tenants ORDER BY id")]

    def create_user(self, tenant_id, name, email="", role="contador"):
        cur = self.conn.execute(
            "INSERT INTO users(tenant_id, name, email, role) VALUES (?,?,?,?)",
            (tenant_id, name, email, role))
        self.conn.commit()
        return cur.lastrowid

    # ---- Invoices ----
    def insert_invoice(self, tenant_id, datos, clasif, validacion, erp=None):
        """Inserta o actualiza una factura. Devuelve (invoice_id, inserted)."""
        issues_txt = "; ".join(i["mensaje"] for i in validacion.get("issues", []))
        now = datetime.now().isoformat(timespec="seconds")
        row = {
            "tenant_id": tenant_id,
            "folio_fiscal": datos.get("folio_fiscal") or None,
            "archivo": datos.get("archivo", ""),
            "fecha": datos.get("fecha", ""),
            "tipo": datos.get("tipo", ""),
            "serie": datos.get("serie", ""),
            "folio": datos.get("folio", ""),
            "emisor_rfc": datos.get("emisor_rfc", ""),
            "emisor_nombre": datos.get("emisor_nombre", ""),
            "receptor_rfc": datos.get("receptor_rfc", ""),
            "subtotal": str(datos.get("subtotal")) if datos.get("subtotal") is not None else "",
            "iva": str(datos.get("iva")) if datos.get("iva") is not None else "",
            "total": str(datos.get("total")) if datos.get("total") is not None else "",
            "moneda": datos.get("moneda", "MXN"),
            "descripcion": datos.get("descripcion", ""),
            "categoria": clasif.get("categoria", "desconocido"),
            "confianza": clasif.get("confianza", 0.0),
            "razon_clasificacion": clasif.get("razon", ""),
            "valido": 1 if validacion.get("ok") else 0,
            "requires_human_review": 1 if validacion.get("requires_human_review") else 0,
            "issues": issues_txt,
            "erp_poliza": (erp or {}).get("poliza", "") if erp else "",
            "erp_status": (erp or {}).get("status", "") if erp else "",
            # [33] Derivar status del erp_status: pending_approval NO es "procesado".
            "status": ("pending_approval"
                       if (erp or {}).get("status") == "pending_approval"
                       else ("rejected"
                             if (erp or {}).get("status") == "rejected_invalid_cfdi"
                             else "procesado")),
            "procesado_en": now,
        }
        try:
            cur = self.conn.execute("""
                INSERT INTO invoices (
                    tenant_id, folio_fiscal, archivo, fecha, tipo, serie, folio,
                    emisor_rfc, emisor_nombre, receptor_rfc,
                    subtotal, iva, total, moneda, descripcion,
                    categoria, confianza, razon_clasificacion,
                    valido, requires_human_review, issues,
                    erp_poliza, erp_status, status, procesado_en)
                VALUES (
                    :tenant_id, :folio_fiscal, :archivo, :fecha, :tipo, :serie, :folio,
                    :emisor_rfc, :emisor_nombre, :receptor_rfc,
                    :subtotal, :iva, :total, :moneda, :descripcion,
                    :categoria, :confianza, :razon_clasificacion,
                    :valido, :requires_human_review, :issues,
                    :erp_poliza, :erp_status, :status, :procesado_en)
            """, row)
            invoice_id = cur.lastrowid
            inserted = True
            self._bump_version()
        except Exception as exc:
            if not _is_integrity_error(exc):
                raise
            self.conn.rollback()
            existing = self.conn.execute(
                "SELECT id FROM invoices WHERE tenant_id=? AND folio_fiscal=?",
                (tenant_id, row["folio_fiscal"])).fetchone()
            invoice_id = existing["id"] if existing else None
            inserted = False
        # Registro de clasificación (historial) y commit
        if invoice_id:
            self.conn.execute("""
                INSERT INTO classifications(invoice_id, tenant_id, categoria,
                    confianza, razon, method) VALUES (?,?,?,?,?, 'rules')
            """, (invoice_id, tenant_id, row["categoria"], row["confianza"],
                  row["razon_clasificacion"]))
        self.conn.commit()
        return invoice_id, inserted

    def list_invoices(self, tenant_id=None, limit=None,
                      categoria=None, valido=None, fecha_desde=None,
                      fecha_hasta=None):
        q = "SELECT * FROM invoices"
        params = []
        clauses = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if categoria:
            clauses.append("categoria=?")
            params.append(categoria)
        if valido is not None:
            clauses.append("valido=?")
            params.append(1 if valido else 0)
        if fecha_desde:
            clauses.append("fecha>=?")
            params.append(fecha_desde)
        if fecha_hasta:
            clauses.append("fecha<=?")
            params.append(fecha_hasta)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        if limit:
            q += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def invoice_stats(self, tenant_id=None):
        """Métricas agregadas sobre facturas (para GET /api/v1/stats)."""
        q = "SELECT categoria, COUNT(*) AS n, SUM(CAST(total AS REAL)) AS monto FROM invoices"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += " GROUP BY categoria ORDER BY n DESC"
        rows = self.conn.execute(q, params).fetchall()
        by_cat = {r["categoria"]: {"count": r["n"],
                                   "total": round(r["monto"], 2) if r["monto"] else 0}
                  for r in rows}
        total_q = "SELECT COUNT(*), SUM(CAST(total AS REAL)), \
                    SUM(CAST(iva AS REAL)) FROM invoices"
        if tenant_id is not None:
            total_q += " WHERE tenant_id=?"
        trow = self.conn.execute(total_q, params).fetchone()
        n = trow[0] or 0
        return {
            "total_facturas": n,
            "monto_total": round(trow[1] or 0, 2),
            "iva_total": round(trow[2] or 0, 2),
            "por_categoria": by_cat,
        }

    def get_invoice(self, invoice_id, tenant_id=None):
        q = "SELECT * FROM invoices WHERE id=?"
        params = [invoice_id]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        row = self.conn.execute(q, params).fetchone()
        return dict(row) if row else None

    def count_invoices(self, tenant_id=None):
        q = "SELECT COUNT(*) FROM invoices"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        return self.conn.execute(q, params).fetchone()[0]

    # ---- Audit log ----
    def log_call(self, tool_name, action, entity="", entity_id="",
                 payload=None, status="ok", tenant_id=None):
        payload_txt = json.dumps(payload, default=str, ensure_ascii=False) if payload is not None else '{}'
        cur = self.conn.execute("""
            INSERT INTO audit_log(tenant_id, tool_name, action, entity,
                entity_id, payload, status) VALUES (?,?,?,?,?,?,?)
        """, (tenant_id, tool_name, action, entity, entity_id, payload_txt, status))
        self.conn.commit()
        return cur.lastrowid

    def list_audit(self, tenant_id=None, tool_name=None, limit=100):
        q = "SELECT * FROM audit_log"
        params = []
        clauses = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if tool_name:
            clauses.append("tool_name=?")
            params.append(tool_name)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def count_audit(self, tool_name=None):
        q = "SELECT COUNT(*) FROM audit_log"
        params = []
        if tool_name:
            q += " WHERE tool_name=?"
            params.append(tool_name)
        return self.conn.execute(q, params).fetchone()[0]

    # ---- Billing (FASE cobros) ----
    # Persistencia local de clientes, suscripciones y facturas de pago.
    # La referencia `provider_*` es el id opaco del proveedor (Stripe/Conekta).
    def create_billing_customer(self, tenant_id, email, name,
                                provider="stripe", provider_customer_id=None):
        cur = self.conn.execute("""
            INSERT INTO billing_customers(tenant_id, email, name, provider,
                provider_customer_id) VALUES (?,?,?,?,?)
        """, (tenant_id, email, name, provider, provider_customer_id))
        self.conn.commit()
        return cur.lastrowid

    def get_billing_customer_by_email(self, tenant_id, email):
        row = self.conn.execute("""
            SELECT * FROM billing_customers WHERE tenant_id=? AND email=?
        """, (tenant_id, email)).fetchone()
        return dict(row) if row else None

    def create_billing_subscription(self, tenant_id, customer_id, plan,
                                    provider, provider_subscription_id,
                                    status="active", period_start="",
                                    period_end=""):
        cur = self.conn.execute("""
            INSERT INTO billing_subscriptions(tenant_id, customer_id, plan,
                provider, provider_subscription_id, status,
                current_period_start, current_period_end)
            VALUES (?,?,?,?,?,?,?,?)
        """, (tenant_id, customer_id, plan, provider,
              provider_subscription_id, status, period_start, period_end))
        self.conn.commit()
        return cur.lastrowid

    def list_billing_subscriptions(self, tenant_id=None, limit=100):
        q = ("SELECT s.*, c.email, c.name AS customer_name "
             "FROM billing_subscriptions s "
             "LEFT JOIN billing_customers c ON c.id = s.customer_id")
        params = []
        if tenant_id is not None:
            q += " WHERE s.tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY s.id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def create_billing_invoice(self, tenant_id, customer_id, amount,
                               currency="MXN", status="open",
                               provider_invoice_id=None, provider="stripe"):
        cur = self.conn.execute("""
            INSERT INTO billing_invoices(tenant_id, customer_id, amount,
                currency, status, provider_invoice_id, provider)
            VALUES (?,?,?,?,?,?,?)
        """, (tenant_id, customer_id, amount, currency, status,
              provider_invoice_id, provider))
        self.conn.commit()
        return cur.lastrowid

    def list_billing_invoices(self, tenant_id=None, limit=100):
        q = ("SELECT i.*, c.email, c.name AS customer_name "
             "FROM billing_invoices i "
             "LEFT JOIN billing_customers c ON c.id = i.customer_id")
        params = []
        if tenant_id is not None:
            q += " WHERE i.tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY i.id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def mark_billing_invoice_paid_by_ref(self, provider_invoice_id, provider,
                                         paid_at=None):
        """Marca una factura como pagada por su referencia del proveedor
        (usado por los webhooks). Devuelve True si actualizó alguna fila."""
        if paid_at is None:
            from datetime import datetime
            paid_at = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute("""
            UPDATE billing_invoices SET status='paid', paid_at=?
            WHERE provider_invoice_id=? AND provider=?
        """, (paid_at, provider_invoice_id, provider))
        self.conn.commit()
        return cur.rowcount > 0

    def create_billing_payment_method(self, tenant_id, customer_id, type_,
                                      provider, provider_payment_method_id,
                                      last4=None, exp_month=None, exp_year=None):
        cur = self.conn.execute("""
            INSERT INTO billing_payment_methods(tenant_id, customer_id, type,
                provider, provider_payment_method_id, last4, exp_month, exp_year)
            VALUES (?,?,?,?,?,?,?,?)
        """, (tenant_id, customer_id, type_, provider,
              provider_payment_method_id, last4, exp_month, exp_year))
        self.conn.commit()
        return cur.lastrowid

    def list_billing_payment_methods(self, tenant_id=None, limit=100):
        q = ("SELECT pm.*, c.email FROM billing_payment_methods pm "
             "LEFT JOIN billing_customers c ON c.id = pm.customer_id")
        params = []
        if tenant_id is not None:
            q += " WHERE pm.tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY pm.id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Data retention (FASE hardening) ----
    # Elimina registros operativos más viejos que `days` días para cumplir la
    # política de retención de datos (audit, entregas de webhook, sesiones
    # del portal y notificaciones). Las facturas (datos fiscales) NO se tocan:
    # su retención la manda el SAT y va en una política separada.
    _RETENTION_TABLES = {
        "audit_log": "created_at",
        "webhook_deliveries": "created_at",
        "notifications": "created_at",
        "portal_sessions": "created_at",
    }

    def enforce_retention(self, days: int = None) -> dict:
        """Borra filas operativas más viejas que `days` días. `days` por
        defecto viene de B2B_RETENTION_DAYS (default 365). Devuelve cuántas
        filas eliminó por tabla."""
        if days is None:
            days = int(os.environ.get("B2B_RETENTION_DAYS", "365") or "365")
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(
            timespec="seconds")
        removed = {}
        for table, col in self._RETENTION_TABLES.items():
            try:
                # nosec B608: los nombres de tabla/columna vienen SOLO de la
                # constante _RETENTION_TABLES (allowlist fija en código), nunca
                # de input del usuario. El valor (cutoff) va parametrizado (?).
                cur = self.conn.execute(
                    f"DELETE FROM {table} WHERE {col} IS NOT NULL "  # nosec B608
                    f"AND {col} < ?", (cutoff,))
                removed[table] = cur.rowcount
            except sqlite3.Error:
                removed[table] = 0
        self.conn.commit()
        return removed

    # ---- Notifications ----
    def insert_notification(self, tenant_id, type_, channel, recipient,
                            subject, body, status="queued"):
        cur = self.conn.execute("""
            INSERT INTO notifications(tenant_id, type, channel, recipient,
                subject, body, status) VALUES (?,?,?,?,?,?,?)
        """, (tenant_id, type_, channel, recipient, subject, body, status))
        self.conn.commit()
        return cur.lastrowid

    def list_notifications(self, tenant_id=None, limit=100):
        q = "SELECT * FROM notifications"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def update_notification_status(self, notification_id, status):
        """Actualiza el estado de una notificación (sent/error/failed)."""
        cur = self.conn.execute(
            "UPDATE notifications SET status=? WHERE id=?",
            (status, notification_id))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- Conciliación bancaria (estado persistido por tenant) ----
    # Sustituye al diccionario en memoria que vivía en api/reconciliation.py.
    # Solo se guarda lo no derivable: movimientos subidos y confirmaciones
    # manuales. Toda lectura y escritura filtra por tenant_id.
    def add_bank_transactions(self, tenant_id, transactions, banco=None,
                              filename=None):
        """Persiste movimientos normalizados. Devuelve cuántos son nuevos.

        Idempotente por (tenant_id, tx_id): resubir el mismo estado de cuenta
        no duplica movimientos.
        """
        nuevos = 0
        with self.conn:
            for t in transactions or []:
                tx_id = str(t.get("id") or t.get("tx_id") or "")
                if not tx_id:
                    continue
                # `ON CONFLICT DO NOTHING` sin target y no `INSERT OR IGNORE`:
                # la primera forma la entienden SQLite y PostgreSQL por igual,
                # y este método corre contra los dos backends.
                cur = self.conn.execute(
                    "INSERT INTO bank_transactions"
                    "(tenant_id, tx_id, banco, filename, data)"
                    " VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (tenant_id, tx_id, banco, filename, json.dumps(t)))
                nuevos += cur.rowcount or 0
        return nuevos

    def list_bank_transactions(self, tenant_id=None):
        """Movimientos persistidos del tenant, en orden de inserción."""
        rows = self.conn.execute(
            "SELECT data FROM bank_transactions"
            " WHERE COALESCE(tenant_id, -1)=COALESCE(?, -1)"
            " ORDER BY id ASC", (tenant_id,)).fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["data"]))
            except (ValueError, TypeError):
                continue
        return out

    def set_bank_confirmation(self, tenant_id, tx_id, invoice_id):
        """Registra (o reemplaza) una confirmación manual de cruce."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM bank_confirmations"
                " WHERE COALESCE(tenant_id, -1)=COALESCE(?, -1) AND tx_id=?",
                (tenant_id, str(tx_id)))
            self.conn.execute(
                "INSERT INTO bank_confirmations(tenant_id, tx_id, invoice_id)"
                " VALUES (?,?,?)",
                (tenant_id, str(tx_id), str(invoice_id)))

    def list_bank_confirmations(self, tenant_id=None):
        """Confirmaciones manuales del tenant como {tx_id: invoice_id}."""
        rows = self.conn.execute(
            "SELECT tx_id, invoice_id FROM bank_confirmations"
            " WHERE COALESCE(tenant_id, -1)=COALESCE(?, -1)",
            (tenant_id,)).fetchall()
        return {r["tx_id"]: r["invoice_id"] for r in rows}

    def clear_bank_reconciliation(self, tenant_id=None):
        """Borra movimientos y confirmaciones del tenant (reset de sesión)."""
        with self.conn:
            for tabla in ("bank_transactions", "bank_confirmations"):
                self.conn.execute(
                    f"DELETE FROM {tabla}"  # nosec B608 — nombre literal fijo
                    " WHERE COALESCE(tenant_id, -1)=COALESCE(?, -1)",
                    (tenant_id,))

    # ---- API keys (multi-tenant) ----
    def create_api_key(self, tenant_id, name, key):
        """Guarda una API key hashada. Devuelve (id, key_hash)."""
        import hashlib
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO api_keys(tenant_id, name, key_hash) VALUES (?,?,?)",
            (tenant_id, name, key_hash))
        self.conn.commit()
        return cur.lastrowid, key_hash

    def get_api_key(self, key):
        """Busca una API key (se hashea internamente). Devuelve fila o None."""
        import hashlib
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        row = self.conn.execute(
            "SELECT * FROM api_keys WHERE key_hash=? AND active=1",
            (key_hash,)).fetchone()
        return dict(row) if row else None

    def list_api_keys(self, tenant_id=None):
        q = "SELECT id, tenant_id, name, active, created_at FROM api_keys"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY id DESC"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def set_api_key_active(self, api_key_id, active: bool):
        """Activa/desactiva una API key (base de la rotación y revocación).

        Una key desactivada deja de autenticar de inmediato (get_api_key solo
        devuelve filas con active=1). La rotación se hace emitiendo una key
        nueva (create_api_key) y desactivando la vieja (set_api_key_active).
        Devuelve True si cambió alguna fila.
        """
        cur = self.conn.execute(
            "UPDATE api_keys SET active=? WHERE id=?",
            (1 if active else 0, api_key_id))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- Leads (landing page) ----
    def add_lead(self, nombre, email, despacho="", facturas="", mensaje=""):
        cur = self.conn.execute(
            "INSERT INTO leads(nombre, despacho, email, facturas, mensaje) "
            "VALUES (?,?,?,?,?)",
            (nombre, despacho, email, facturas, mensaje))
        self.conn.commit()
        return cur.lastrowid

    def list_leads(self, limit=100):
        q = "SELECT * FROM leads ORDER BY id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q).fetchall()]

    # ---- Config por tenant (FASE 4) ----
    def get_tenant_config(self, tenant_id, key, default=None):
        row = self.conn.execute(
            "SELECT config_value FROM tenant_config "
            "WHERE tenant_id=? AND config_key=?",
            (tenant_id, key)).fetchone()
        if not row:
            return default
        return _decrypt_config_value(key, row["config_value"])

    def set_tenant_config(self, tenant_id, key, value):
        """Upsert de un valor de configuración por tenant. Los campos
        sensibles (webhook_url, notif_recipient) se cifran en reposo cuando
        hay B2B_ENCRYPTION_KEY; sin clave se guardan en claro (degradado)."""
        stored = _encrypt_config_value(key, value)
        with self.conn:
            self.conn.execute(
                "INSERT INTO tenant_config(tenant_id, config_key, config_value) "
                "VALUES (?,?,?) "
                "ON CONFLICT(tenant_id, config_key) DO UPDATE SET "
                "config_value=excluded.config_value, "
                "updated_at=CURRENT_TIMESTAMP",
                (tenant_id, key, stored))
        return value

    def get_all_tenant_config(self, tenant_id):
        rows = self.conn.execute(
            "SELECT config_key, config_value FROM tenant_config "
            "WHERE tenant_id=? ORDER BY config_key", (tenant_id,)).fetchall()
        return {r["config_key"]: _decrypt_config_value(r["config_key"],
                                                       r["config_value"])
                for r in rows}

    # ---- Revisión humana (human-in-the-loop, FASE 4) ----
    def create_review(self, tenant_id, invoice_id, reason, decision=None):
        cur = self.conn.execute(
            "INSERT INTO reviews(tenant_id, invoice_id, reason, decision) "
            "VALUES (?,?,?,?)",
            (tenant_id, invoice_id, reason, decision))
        self.conn.commit()
        return cur.lastrowid

    def list_reviews(self, tenant_id=None, status=None, limit=100):
        q = "SELECT * FROM reviews"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def count_pending_reviews(self, tenant_id=None):
        q = "SELECT COUNT(*) FROM reviews WHERE status='pending'"
        params = []
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        return self.conn.execute(q, params).fetchone()[0]

    def resolve_review(self, review_id, decision, notes="", resolved_by="humano"):
        """Aprobar/rechazar una revisión pendiente. Devuelve fila o None."""
        from datetime import datetime
        cur = self.conn.execute(
            "UPDATE reviews SET status='resolved', decision=?, notes=?, "
            "resolved_by=?, resolved_at=? WHERE id=? AND status='pending'",
            (decision, notes, resolved_by,
             datetime.now().isoformat(timespec="seconds"), review_id))
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        row = self.conn.execute(
            "SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        return dict(row) if row else None

    # ---- Entregas de webhook (retry logic, FASE 4) ----
    def record_webhook_delivery(self, tenant_id, event, url, payload,
                                max_attempts=3):
        cur = self.conn.execute(
            "INSERT INTO webhook_deliveries(tenant_id, event, url, payload, "
            "max_attempts) VALUES (?,?,?,?,?)",
            (tenant_id, event, url,
             json.dumps(payload, default=str, ensure_ascii=False), max_attempts))
        self.conn.commit()
        return cur.lastrowid

    def update_webhook_delivery(self, delivery_id, attempts, last_status,
                                last_error="", next_retry_at=None,
                                completed_at=None):
        with self.conn:
            self.conn.execute(
                "UPDATE webhook_deliveries SET attempts=?, last_status=?, "
                "last_error=?, next_retry_at=?, completed_at=? WHERE id=?",
                (attempts, last_status, last_error, next_retry_at, completed_at,
                 delivery_id))

    def get_webhook_delivery(self, delivery_id):
        row = self.conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id=?",
            (delivery_id,)).fetchone()
        return dict(row) if row else None

    def list_webhook_deliveries(self, tenant_id=None, limit=100):
        q = "SELECT * FROM webhook_deliveries"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def list_pending_webhook_deliveries(self, tenant_id=None, limit=100):
        q = "SELECT * FROM webhook_deliveries WHERE completed_at IS NULL"
        params = []
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        q += f" ORDER BY id ASC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Cobranza automatizada (FASE 3) ----
    def upsert_outstanding_invoice(self, tenant_id, factura_id, monto,
                                   fecha_vencimiento, dias_vencido=0,
                                   score=0.0):
        """Crea o actualiza una factura pendiente de la cartera de cobranza.

        Devuelve el id de la fila. Si la factura ya existe (por tenant+factura),
        se actualizan monto, vencimiento, días vencidos y score.
        """
        with self.conn:
            self.conn.execute(
                "INSERT INTO outstanding_invoices(tenant_id, factura_id, monto, "
                "fecha_vencimiento, dias_vencido, score, updated_at) "
                "VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP) "
                "ON CONFLICT (tenant_id, factura_id) DO UPDATE SET "
                "monto=excluded.monto, fecha_vencimiento=excluded.fecha_vencimiento, "
                "dias_vencido=excluded.dias_vencido, score=excluded.score, "
                "updated_at=CURRENT_TIMESTAMP",
                (tenant_id, factura_id, float(monto), fecha_vencimiento,
                 int(dias_vencido), float(score)))
        row = self.conn.execute(
            "SELECT id FROM outstanding_invoices "
            "WHERE tenant_id=? AND factura_id=?",
            (tenant_id, factura_id)).fetchone()
        return row["id"]

    def list_outstanding_invoices(self, tenant_id=None, factura_id=None,
                                  limit=1000):
        """Lista la cartera de cuentas por cobrar, filtrando por tenant."""
        q = "SELECT * FROM outstanding_invoices"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if factura_id is not None:
            clauses.append("factura_id=?")
            params.append(factura_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY dias_vencido DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def delete_outstanding_invoice(self, tenant_id, factura_id):
        """Elimina una factura pendiente (p. ej. al reportarla como pagada)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM outstanding_invoices "
                "WHERE tenant_id=? AND factura_id=?",
                (tenant_id, factura_id))

    def add_collection_event(self, tenant_id, factura_id, tipo_recordatorio,
                             canal="email", respuesta=None):
        """Registra un intento de cobranza (recordatorio/escalamiento).

        Devuelve el id del evento. `respuesta` guarda la reacción del deudor
        ('pagado', 'promesa_pago', 'sin_respuesta', ...) cuando se conoce.
        """
        cur = self.conn.execute(
            "INSERT INTO collection_events(tenant_id, factura_id, "
            "tipo_recordatorio, canal, respuesta) VALUES (?,?,?,?,?)",
            (tenant_id, factura_id, tipo_recordatorio, canal, respuesta))
        self.conn.commit()
        return cur.lastrowid

    def list_collection_events(self, tenant_id=None, factura_id=None,
                               limit=100):
        """Lista el historial de intentos de cobranza."""
        q = "SELECT * FROM collection_events"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if factura_id is not None:
            clauses.append("factura_id=?")
            params.append(factura_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY timestamp DESC, id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Cobranza: log de pagos (módulo collections) -------------------
    def add_collection_payment(self, tenant_id, factura_id, event_type,
                               amount=0.0, currency="MXN", reference="",
                               provider="manual", paid_at=None,
                               metadata=None):
        """Registra un pago recibido vía webhook. Devuelve el id."""
        import json as _json
        cur = self.conn.execute(
            "INSERT INTO collection_payments(tenant_id, factura_id, "
            "event_type, amount, currency, reference, provider, "
            "paid_at, metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (tenant_id, factura_id, event_type, float(amount), currency,
             reference, provider, paid_at,
             _json.dumps(metadata, default=str, ensure_ascii=False)
             if metadata else None))
        self.conn.commit()
        return cur.lastrowid

    def list_collection_payments(self, tenant_id=None, factura_id=None,
                                  limit=100):
        """Lista el log de pagos recibidos."""
        q = "SELECT * FROM collection_payments"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if factura_id is not None:
            clauses.append("factura_id=?")
            params.append(factura_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Cobranza: configuración por tenant ---------------------------
    def get_collection_config(self, tenant_id, config_key):
        """Lee un valor de configuración de cobranza del tenant."""
        row = self.conn.execute(
            "SELECT config_value FROM collection_config "
            "WHERE tenant_id=? AND config_key=?",
            (tenant_id, config_key)).fetchone()
        return row["config_value"] if row else None

    def set_collection_config(self, tenant_id, config_key, config_value):
        """Guarda/actualiza un valor de configuración de cobranza."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO collection_config(tenant_id, config_key, "
                "config_value) VALUES (?,?,?) "
                "ON CONFLICT(tenant_id, config_key) DO UPDATE SET "
                "config_value=excluded.config_value, "
                "updated_at=CURRENT_TIMESTAMP",
                (tenant_id, config_key, str(config_value)))

    def list_collection_config(self, tenant_id):
        """Lista toda la configuración de cobranza del tenant."""
        rows = self.conn.execute(
            "SELECT * FROM collection_config WHERE tenant_id=? "
            "ORDER BY config_key", (tenant_id,)).fetchall()
        return {r["config_key"]: r["config_value"] for r in rows}


    # ---- Outreach (outbound emails de adquisición) ---------------------
    def create_outreach_campaign(self, tenant_id, name, sequence_id=1,
                                 sender_email=None, reply_to=None):
        """Crea una campaña de outbound. Devuelve el id de la campaña."""
        cur = self.conn.execute(
            "INSERT INTO outreach_campaigns(tenant_id, name, sequence_id, "
            "status, sender_email, reply_to, launched_at) "
            "VALUES (?,?,?, 'active',?,?, CURRENT_TIMESTAMP)",
            (tenant_id, name, sequence_id, sender_email, reply_to))
        self.conn.commit()
        return cur.lastrowid

    def get_outreach_campaign(self, campaign_id):
        """Fila completa de una campaña (o None)."""
        row = self.conn.execute(
            "SELECT * FROM outreach_campaigns WHERE id=?",
            (campaign_id,)).fetchone()
        return dict(row) if row else None

    def list_outreach_campaigns(self, tenant_id=None, limit=100):
        """Lista campañas (opcionalmente por tenant)."""
        q, params = "SELECT * FROM outreach_campaigns", []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def set_outreach_campaign_status(self, campaign_id, status,
                                     paused=False):
        """Cambia el estado de una campaña ('active'|'paused'|'completed'|
        'cancelled'). `paused=True` marca paused_at cuando se pausa."""
        if paused:
            self.conn.execute(
                "UPDATE outreach_campaigns SET status=?, paused_at=?"
                " WHERE id=?",
                (status, "CURRENT_TIMESTAMP", campaign_id))
        else:
            self.conn.execute(
                "UPDATE outreach_campaigns SET status=? WHERE id=?",
                (status, campaign_id))
        self.conn.commit()

    def add_outreach_lead(self, campaign_id, tenant_id, email, first_name="",
                          last_name="", company="", role="", industry=""):
        """Agrega un lead a una campaña. Devuelve el id del lead."""
        cur = self.conn.execute(
            "INSERT INTO outreach_campaign_leads(campaign_id, tenant_id, "
            "email, first_name, last_name, company, role, industry, stage, "
            "status, emails_sent) VALUES (?,?,?,?,?,?,?,?, 1, 'queued', 0)",
            (campaign_id, tenant_id, email, first_name, last_name,
             company, role, industry))
        self.conn.commit()
        return cur.lastrowid

    def _ensure_outreach_standalone_campaign(self, tenant_id: int) -> int:
        """Crea/recupera una campaña default para leads sin campaña asignada."""
        row = self.conn.execute(
            "SELECT id FROM outreach_campaigns WHERE tenant_id=? AND name='Standalone Leads'",
            (tenant_id,)).fetchone()
        if row:
            return row[0] if isinstance(row, (list, tuple)) else row["id"]
        cur = self.conn.execute(
            "INSERT INTO outreach_campaigns(tenant_id, name, status) VALUES (?,?,?)",
            (tenant_id, "Standalone Leads", "active"))
        self.conn.commit()
        return cur.lastrowid or 0

    def get_outreach_lead(self, lead_id):
        """Lead de una campaña (o None)."""
        row = self.conn.execute(
            "SELECT * FROM outreach_campaign_leads WHERE id=?",
            (lead_id,)).fetchone()
        return dict(row) if row else None

    def list_outreach_leads(self, campaign_id=None, tenant_id=None,
                            status=None, limit=200):
        """Lista leads de campaña, filtrando por campaña/tenant/estado."""
        q = "SELECT * FROM outreach_campaign_leads"
        params, clauses = [], []
        if campaign_id is not None:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id ASC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def update_outreach_lead(self, lead_id, **fields):
        """Actualiza campos del lead (stage, status, next_send_at, etc.).
        Solo acepta columnas conocidas para evitar SQL injection."""
        allowed = {"stage", "status", "next_send_at", "emails_sent",
                   "first_name", "last_name", "company", "role", "industry"}
        cols, params = [], []
        for k, v in fields.items():
            if k in allowed:
                cols.append(f"{k}=?")
                params.append(v)
        if not cols:
            return
        params.append(lead_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE outreach_campaign_leads SET {', '.join(cols)}"
                " WHERE id=?", params)

    def add_outreach_email(self, campaign_id, lead_id, tenant_id, template,
                           subject, body):
        """Registra un correo enviado. Devuelve el id del correo."""
        cur = self.conn.execute(
            "INSERT INTO outreach_emails(campaign_id, lead_id, tenant_id, "
            "template, subject, body, status) VALUES (?,?,?,?,?,?, 'sent')",
            (campaign_id, lead_id, tenant_id, template, subject, body))
        self.conn.commit()
        return cur.lastrowid

    def get_outreach_email(self, email_id):
        """Correo enviado (o None)."""
        row = self.conn.execute(
            "SELECT * FROM outreach_emails WHERE id=?",
            (email_id,)).fetchone()
        return dict(row) if row else None

    def list_outreach_emails(self, lead_id=None, campaign_id=None, limit=200):
        """Lista correos enviados, filtrando por lead o campaña."""
        q = "SELECT * FROM outreach_emails"
        params, clauses = [], []
        if lead_id is not None:
            clauses.append("lead_id=?")
            params.append(lead_id)
        if campaign_id is not None:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id ASC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def mark_outreach_email_opened(self, email_id):
        """Registra un open: incrementa opened_count y fija opened_at."""
        with self.conn:
            self.conn.execute(
                "UPDATE outreach_emails SET "
                "opened_count=opened_count+1, "
                "opened_at=COALESCE(opened_at, CURRENT_TIMESTAMP) "
                "WHERE id=?", (email_id,))

    def mark_outreach_email_clicked(self, email_id):
        """Registra un click: incrementa click_count y fija first_clicked_at."""
        with self.conn:
            self.conn.execute(
                "UPDATE outreach_emails SET "
                "click_count=click_count+1, "
                "first_clicked_at=COALESCE(first_clicked_at, CURRENT_TIMESTAMP)"
                " WHERE id=?", (email_id,))

    def add_outreach_event(self, tenant_id, email_id, lead_id, event_type,
                           link_id=None):
        """Registra un evento de tracking (open/click). Devuelve el id."""
        cur = self.conn.execute(
            "INSERT INTO outreach_events(tenant_id, email_id, lead_id, "
            "event_type, link_id) VALUES (?,?,?,?,?)",
            (tenant_id, email_id, lead_id, event_type, link_id))
        self.conn.commit()
        return cur.lastrowid

    def list_outreach_events(self, email_id=None, lead_id=None, limit=200):
        """Lista eventos de tracking, filtrando por correo o lead."""
        q = "SELECT * FROM outreach_events"
        params, clauses = [], []
        if email_id is not None:
            clauses.append("email_id=?")
            params.append(email_id)
        if lead_id is not None:
            clauses.append("lead_id=?")
            params.append(lead_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id ASC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Tenant admin: bloqueo (enterprise API v2) ---------------------
    def set_tenant_blocked(self, tenant_id, blocked=True):
        """Bloquea/desbloquea un tenant. Los bloqueados no pueden autenticarse."""
        with self.conn:
            self.conn.execute(
                "UPDATE tenants SET blocked=? WHERE id=?",
                (1 if blocked else 0, tenant_id))
        return bool(blocked)

    def get_tenant_by_id(self, tenant_id):
        """Fila completa de un tenant (incluye `blocked`)."""
        row = self.conn.execute(
            "SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return dict(row) if row else None

    # ---- Usage tracking (enterprise API v2) ----------------------------
    def increment_usage(self, tenant_id, api_calls=0, invoices_processed=0):
        """Incrementa los contadores de uso del tenant (upsert)."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO tenant_usage(tenant_id, api_calls, "
                "invoices_processed) VALUES (?,?,?) "
                "ON CONFLICT(tenant_id) DO UPDATE SET "
                "api_calls=tenant_usage.api_calls+excluded.api_calls, "
                "invoices_processed=tenant_usage.invoices_processed"
                "+excluded.invoices_processed, "
                "updated_at=CURRENT_TIMESTAMP",
                (tenant_id, int(api_calls), int(invoices_processed)))
        return self.get_usage(tenant_id)

    def get_usage(self, tenant_id):
        """Uso acumulado de un tenant (o ceros si no hay registros)."""
        row = self.conn.execute(
            "SELECT api_calls, invoices_processed, updated_at "
            "FROM tenant_usage WHERE tenant_id=?",
            (tenant_id,)).fetchone()
        if row is None:
            return {"tenant_id": tenant_id, "api_calls": 0,
                    "invoices_processed": 0, "updated_at": None}
        return {"tenant_id": tenant_id, "api_calls": row["api_calls"],
                "invoices_processed": row["invoices_processed"],
                "updated_at": row["updated_at"]}

    def get_all_usage(self):
        """Uso de todos los tenants (para el admin)."""
        return [dict(r) for r in self.conn.execute(
            "SELECT tenant_id, api_calls, invoices_processed, updated_at "
            "FROM tenant_usage ORDER BY tenant_id")]

    # ---- Suscripciones de webhook por evento (enterprise API v2) -------
    def create_webhook_subscription(self, tenant_id, event, url):
        """Registra una URL de webhook para un evento. Devuelve el id."""
        self.conn.execute(
            "INSERT INTO webhook_subscriptions(tenant_id, event, url) "
            "VALUES (?,?,?) "
            "ON CONFLICT(tenant_id, event, url) DO UPDATE SET active=1",
            (tenant_id, event, url))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM webhook_subscriptions "
            "WHERE tenant_id=? AND event=? AND url=?",
            (tenant_id, event, url)).fetchone()
        return row["id"]

    def list_webhook_subscriptions(self, tenant_id=None, event=None):
        """Lista suscripciones, filtrando por tenant y/o evento."""
        q = "SELECT * FROM webhook_subscriptions"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if event is not None:
            clauses.append("event=?")
            params.append(event)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def delete_webhook_subscription(self, subscription_id, tenant_id=None):
        """Borra una suscripción (scoped por tenant). Devuelve True si se borró."""
        q = "DELETE FROM webhook_subscriptions WHERE id=?"
        params = [subscription_id]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        cur = self.conn.execute(q, params)
        self.conn.commit()
        return cur.rowcount > 0


    # ---- Contabilidad electrónica (FASE 3) -------------------------------
    # Cuentas contables del catálogo (por tenant).
    def upsert_cuenta_contable(self, tenant_id, codigo, descripcion,
                               nivel=3, naturaleza="D", grupo=""):
        """Crea o actualiza una cuenta contable del catálogo del tenant."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO cuentas_contables(tenant_id, codigo, descripcion, "
                "nivel, naturaleza, grupo) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id, codigo) DO UPDATE SET "
                "descripcion=excluded.descripcion, nivel=excluded.nivel, "
                "naturaleza=excluded.naturaleza, grupo=excluded.grupo",
                (tenant_id, str(codigo), descripcion, int(nivel),
                 naturaleza.upper(), grupo))
        row = self.conn.execute(
            "SELECT id FROM cuentas_contables WHERE tenant_id=? AND codigo=?",
            (tenant_id, str(codigo))).fetchone()
        return row["id"]

    def list_cuentas_contables(self, tenant_id=None):
        q = "SELECT * FROM cuentas_contables"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY codigo"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def limpiar_cuentas_contables(self, tenant_id):
        """Reemplaza el catálogo: borra las cuentas del tenant."""
        with self.conn:
            self.conn.execute("DELETE FROM cuentas_contables WHERE tenant_id=?",
                              (tenant_id,))

    # Asientos contables.
    def insert_asiento_contable(self, tenant_id, fecha, cuenta_debito,
                                cuenta_credito, monto, descripcion="",
                                factura_id=None):
        cur = self.conn.execute(
            "INSERT INTO asientos_contables(tenant_id, fecha, cuenta_debito, "
            "cuenta_credito, monto, descripcion, factura_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (tenant_id, fecha, str(cuenta_debito), str(cuenta_credito),
             str(monto), descripcion, factura_id))
        self.conn.commit()
        return cur.lastrowid

    def list_asientos_contables(self, tenant_id=None, periodo=None,
                                limit=10000):
        q = "SELECT * FROM asientos_contables"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if periodo:
            clauses.append("substr(fecha,1,7)=?")
            params.append(str(periodo))
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY fecha, id"
        if limit:
            q += " LIMIT %d" % int(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # Balanzas mensuales.
    def upsert_balanza_mensual(self, tenant_id, periodo, cuenta_id,
                               saldo_inicial, debe, haber, saldo_final):
        with self.conn:
            self.conn.execute(
                "INSERT INTO balanzas_mensuales(tenant_id, periodo, cuenta_id, "
                "saldo_inicial, debe, haber, saldo_final) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id, periodo, cuenta_id) DO UPDATE SET "
                "saldo_inicial=excluded.saldo_inicial, debe=excluded.debe, "
                "haber=excluded.haber, saldo_final=excluded.saldo_final",
                (tenant_id, str(periodo), cuenta_id, str(saldo_inicial),
                 str(debe), str(haber), str(saldo_final)))
        return True

    def list_balanzas_mensuales(self, tenant_id=None, periodo=None):
        q = "SELECT * FROM balanzas_mensuales"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if periodo:
            clauses.append("periodo=?")
            params.append(str(periodo))
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY periodo, cuenta_id"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # Paquetes de contabilidad electrónica (control de estados).
    def insert_paquete_contabilidad(self, tenant_id, periodo, rfc, estado,
                                    payload=None):
        cur = self.conn.execute(
            "INSERT INTO paquetes_contabilidad(tenant_id, periodo, rfc, "
            "estado, payload) VALUES (?,?,?,?,?)",
            (tenant_id, str(periodo), rfc, estado,
             json.dumps(payload, default=str, ensure_ascii=False)
             if payload else None))
        self.conn.commit()
        return cur.lastrowid

    def update_paquete_estado(self, paquete_id, estado):
        with self.conn:
            self.conn.execute(
                "UPDATE paquetes_contabilidad SET estado=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (estado, paquete_id))

    def get_paquete_contabilidad(self, paquete_id, tenant_id=None):
        q = "SELECT * FROM paquetes_contabilidad WHERE id=?"
        params = [paquete_id]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        row = self.conn.execute(q, params).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("payload"):
            try:
                d["payload"] = json.loads(d["payload"])
            except (ValueError, TypeError):
                pass
        return d

    def list_paquetes_contabilidad(self, tenant_id=None, periodo=None,
                                   limit=100):
        q = "SELECT * FROM paquetes_contabilidad"
        params, clauses = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if periodo:
            clauses.append("periodo=?")
            params.append(str(periodo))
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"
        if limit:
            q += " LIMIT %d" % int(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]


    # ---- Portal del cliente (FASE 5) -----------------------------------
    def create_client_user(self, tenant_id, email, password_hash, name="",
                           role="cliente", accepted_privacy_at=None):
        """Crea un usuario del portal de cliente. Devuelve el id.

        ``accepted_privacy_at`` — timestamp ISO-8601 de la aceptación del
        aviso de privacidad (LFPDPPP Art. 8).  Se almacena como evidencia
        de consentimiento; nullable para usuarios migrados sin ese dato.
        """
        cur = self.conn.execute(
            "INSERT INTO client_users(tenant_id, email, password_hash, name, "
            "role, accepted_privacy_at) VALUES (?,?,?,?,?,?)",
            (tenant_id, email, password_hash, name, role,
             accepted_privacy_at))
        self.conn.commit()
        return cur.lastrowid

    def get_client_user_by_email(self, email, tenant_id=None):
        """Usuario del portal por email (opcionalmente scoped por tenant)."""
        q = "SELECT * FROM client_users WHERE email=?"
        params = [email]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        rows = [dict(r) for r in self.conn.execute(q, params).fetchall()]
        if not rows:
            return None
        # Si hay varios (mismo email en varios tenants) y no se desambiguó,
        # devolvemos el primero; el router de login pide tenant_id en colisión.
        return rows[0]

    def get_client_user(self, user_id):
        row = self.conn.execute(
            "SELECT * FROM client_users WHERE id=?",
            (user_id,)).fetchone()
        return dict(row) if row else None

    def list_client_users(self, tenant_id=None):
        q = "SELECT * FROM client_users"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def has_tenant_users(self, tenant_id: int) -> bool:
        """Check if a tenant has any users (in either users or client_users)."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE tenant_id=?", (tenant_id,)
        ).fetchone()
        if row and row[0] > 0:
            return True
        row = self.conn.execute(
            "SELECT COUNT(*) FROM client_users WHERE tenant_id=?", (tenant_id,)
        ).fetchone()
        return bool(row and row[0] > 0)

    def create_portal_session(self, user_id, token, expires_at):
        """Guarda una sesión del portal (token guardado HASHADO, sha256)."""
        import hashlib
        cur = self.conn.execute(
            "INSERT INTO portal_sessions(token_hash, user_id, expires_at) "
            "VALUES (?,?,?)",
            (hashlib.sha256(token.encode("utf-8")).hexdigest(),
             user_id, expires_at))
        self.conn.commit()
        return cur.lastrowid

    def get_portal_session(self, token):
        """Resuelve una sesión por token opaco. Devuelve {user, tenant_id,
        expires_at} o None si el token no existe o está caducado."""
        import hashlib
        th = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = self.conn.execute(
            "SELECT * FROM portal_sessions WHERE token_hash=?",
            (th,)).fetchone()
        if not row:
            return None
        expires = row["expires_at"]
        if expires and str(expires) < datetime.now().isoformat(
                timespec="seconds"):
            return None
        user = self.get_client_user(row["user_id"])
        if user is None:
            return None
        return {"user": user, "tenant_id": user["tenant_id"],
                "expires_at": expires}

    def delete_portal_session(self, token):
        import hashlib
        with self.conn:
            self.conn.execute(
                "DELETE FROM portal_sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(),))

    # ---- Gestión de usuarios enterprise (RBAC) --------------------------
    # Reutiliza la tabla client_users (UNIQUE(tenant_id, email)). Los campos
    # permitidos salen de una allowlist fija en código (nunca de input del
    # usuario), por eso el f-string de columnas es seguro.
    _CLIENT_USER_EDITABLE = ("name", "email", "password_hash", "role")

    def update_client_user(self, user_id, data):
        """Actualiza campos de un usuario del portal (allowlist de columnas)."""
        cols = [c for c in self._CLIENT_USER_EDITABLE if c in data]
        if not cols:
            return self.get_client_user(user_id)
        sets = ", ".join(f"{c}=?" for c in cols)
        params = [data[c] for c in cols] + [user_id]
        with self.conn:
            self.conn.execute(f"UPDATE client_users SET {sets} WHERE id=?",
                              params)  # nosec B608 — cols de allowlist fija
        return self.get_client_user(user_id)

    def delete_client_user(self, user_id):
        """Elimina un usuario del portal (baja definitiva)."""
        with self.conn:
            self.conn.execute("DELETE FROM client_users WHERE id=?",
                              (user_id,))

    # ---- Reconciliation Agent (Agente 1) — jobs en DB ----
    def create_reconciliation_job(self, job_id, tenant_id, bank="generic",
                                  fmt="csv", filename=""):
        """Crea un job de conciliación en la DB. Devuelve el id."""
        cur = self.conn.execute(
            "INSERT INTO reconciliation_jobs(job_id, tenant_id, status, "
            "bank, format, filename) VALUES (?,?,?,?,?,?)",
            (job_id, tenant_id, "pending", bank, fmt, filename))
        self.conn.commit()
        return cur.lastrowid

    def update_reconciliation_job(self, job_id, status=None, progress=None,
                                  result_json=None, error=None):
        """Actualiza campos de un job de conciliación."""
        sets, params = [], []
        if status is not None:
            sets.append("status=?")
            params.append(status)
        if progress is not None:
            sets.append("progress=?")
            params.append(float(progress))
        if result_json is not None:
            sets.append("result_json=?")
            params.append(result_json)
        if error is not None:
            sets.append("error=?")
            params.append(error)
        if not sets:
            return
        sets.append("updated_at=CURRENT_TIMESTAMP")
        params.append(job_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE reconciliation_jobs SET {', '.join(sets)} "
                "WHERE job_id=?", params)

    def get_reconciliation_job(self, job_id, tenant_id=None):
        """Obtiene un job de conciliación por job_id (y opcionalmente tenant)."""
        q = "SELECT * FROM reconciliation_jobs WHERE job_id=?"
        params = [job_id]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        row = self.conn.execute(q, params).fetchone()
        return dict(row) if row else None

    def list_reconciliation_jobs(self, tenant_id=None, status=None, limit=100):
        """Lista jobs de conciliación filtrando por tenant y/o status."""
        q = "SELECT * FROM reconciliation_jobs"
        clauses, params = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    # ---- Conciliation sessions (audit trail) ----
    def create_conciliation_session(self, tenant_id, user_id=None, criteria=None):
        criteria_txt = json.dumps(criteria or {}, default=str, ensure_ascii=False)
        cur = self.conn.execute(
            "INSERT INTO conciliation_sessions(tenant_id, user_id, criteria) VALUES (?,?,?)",
            (tenant_id, user_id, criteria_txt))
        self.conn.commit()
        return cur.lastrowid

    def save_conciliation_match(self, session_id, bank_transaction_id, amount, match_score,
                               poliza_id=None, cfdi_folio=None):
        cur = self.conn.execute(
            "INSERT INTO conciliation_matches(session_id, bank_transaction_id, amount, match_score, poliza_id, cfdi_folio) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, bank_transaction_id, amount, match_score, poliza_id, cfdi_folio))
        self.conn.commit()
        return cur.lastrowid

    def confirm_conciliation_session(self, session_id):
        self.conn.execute(
            "UPDATE conciliation_sessions SET status='confirmed', confirmed_at=datetime('now') WHERE id=?",
            (session_id,))
        self.conn.execute(
            "UPDATE conciliation_matches SET status='confirmed' WHERE session_id=? AND status='proposed'",
            (session_id,))
        self.conn.commit()

    def revert_conciliation_match(self, match_id):
        self.conn.execute(
            "UPDATE conciliation_matches SET status='reverted', reverted_at=datetime('now') WHERE id=?",
            (match_id,))
        self.conn.commit()

    def get_conciliation_sessions(self, tenant_id=None, limit=20):
        q = "SELECT * FROM conciliation_sessions"
        params = []
        if tenant_id is not None:
            q += " WHERE tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def get_conciliation_matches(self, session_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM conciliation_matches WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()]

    # ---- Job queue (persistent batch processing) ----
    def enqueue_job(self, tenant_id, job_type='process_cfdi', payload=None, priority=0):
        """Add a job to the persistent queue."""
        payload_txt = json.dumps(payload or {}, default=str, ensure_ascii=False)
        cur = self.conn.execute(
            "INSERT INTO job_queue(tenant_id, job_type, payload, priority) VALUES (?,?,?,?)",
            (tenant_id, job_type, payload_txt, priority))
        self.conn.commit()
        return cur.lastrowid

    def dequeue_job(self, tenant_id=None):
        """Get the next pending job and mark it as running."""
        q = "SELECT * FROM job_queue WHERE status='pending'"
        params = []
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        q += " ORDER BY priority DESC, id ASC LIMIT 1"
        row = self.conn.execute(q, params).fetchone()
        if not row:
            return None
        job_id = row['id']
        self.conn.execute(
            "UPDATE job_queue SET status='running', started_at=datetime('now'), attempts=attempts+1 WHERE id=?",
            (job_id,))
        self.conn.commit()
        result = dict(row)
        try:
            result['payload'] = json.loads(result.get('payload', '{}'))
        except Exception:
            pass
        result['status'] = 'running'
        result['attempts'] = result.get('attempts', 0) + 1
        return result

    def complete_job(self, job_id, error=None):
        """Mark a job as completed or failed."""
        status = 'failed' if error else 'completed'
        self.conn.execute(
            "UPDATE job_queue SET status=?, error=?, completed_at=datetime('now') WHERE id=?",
            (status, error, job_id))
        self.conn.commit()

    def list_jobs(self, tenant_id=None, status=None, limit=50):
        """List jobs with optional filters."""
        q = "SELECT * FROM job_queue"
        params = []
        clauses = []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(q, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d['payload'] = json.loads(d.get('payload', '{}'))
            except Exception:
                pass
            results.append(d)
        return results

    def retry_failed_jobs(self, tenant_id=None, max_attempts=3):
        """Reset failed jobs that haven't exceeded max_attempts."""
        q = "UPDATE job_queue SET status='pending', started_at=NULL WHERE status='failed' AND attempts < ?"
        params = [max_attempts]
        if tenant_id is not None:
            q += " AND tenant_id=?"
            params.append(tenant_id)
        cur = self.conn.execute(q, params)
        self.conn.commit()
        return cur.rowcount

    # ---- Connection pool monitoring ----
    @property
    def connection_count(self) -> int:
        """Number of tracked connections (for monitoring)."""
        with self._conn_lock:
            return len(self._connections)

    def _purge_stale_connections(self):
        """Remove closed/stale connections from the tracking set."""
        with self._conn_lock:
            stale = set()
            for conn in self._connections:
                try:
                    if self._is_pg:
                        if getattr(conn, '_released', False):
                            stale.add(conn)
                    else:
                        conn.execute('SELECT 1')
                except Exception:
                    stale.add(conn)
            self._connections -= stale
            return len(stale)


def main():
    import sys
    db = Database()
    print(f"Base  : {db.path}")
    print(f"Versión esquema: {db.schema_version()}")
    print(f"Tenants: {len(db.list_tenants())} | Invoices: {db.count_invoices()}")
    print(f"Audit calls: {db.count_audit()}")
    if "--reset" in sys.argv:
        db.conn.execute("DROP TABLE IF EXISTS schema_version")
        db.close()
        os.remove(db.path)
        print("Base eliminada.")


if __name__ == "__main__":
    main()
