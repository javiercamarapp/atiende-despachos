# 🔍 Auditoría Exhaustiva — Capa de Datos (Database)

**Fecha:** 2026-08-01
**Alcance:** `b2b_ai/db/` (db.py, models.py, pool.py, pg.py, tenants.py, postgres_adapter.py, adapter_factory.py, migration.py), `migrations/`, `b2b_ai/infrastructure/db_pool.py`
**Stack:** FastAPI, PostgreSQL (prod) / SQLite (dev), psycopg3, Alembic

---

## Resumen Ejecutivo

| Severidad | Hallazgos |
|-----------|-----------|
| 🔴 CRÍTICO | 4 |
| 🟠 ALTO | 7 |
| 🟡 MEDIO | 8 |
| 🔵 BAJO | 5 |

**Hallazgos clave:**
- No hay RLS (Row-Level Security) en PostgreSQL — tenant_id filtering es solo en aplicación
- Migración v15 (privacy_consent) falta en Alembic — schema drift SQLite vs PG
- SELECT * masivo en ~30 queries — riesgo de performance y rotura ante cambio de schema
- `pool_pre_ping` no está activo en el pool principal de `db.py` (sí en `db_pool.py`)
- Código duplicado: `pg.py`, `postgres_adapter.py`, y `infrastructure/db_pool.py` implementan pools separados
- Archivo `migration 2.py` duplicado de `migration.py`

---

## 1. SCHEMA

### H-01 🔴 CRÍTICO — Monetarios como TEXT en vez de NUMERIC
**Archivo:** `b2b_ai/db/models.py:57-59` (invoices), `models.py:229` (outstanding_invoices.monto)
**Descripción:** Los campos `subtotal`, `iva`, `total` en invoices se almacenan como TEXT. `outstanding_invoices.monto` es REAL pero los otros montos son TEXT. Las comparaciones y SUM() requieren CAST y pueden fallar con formato localizado.
**Impacto:** Cálculos fiscales incorrectos, pérdida de precisión con CAST, índices no funcionan en rangos de montos.
**Fix:**
```sql
-- Migración Alembic: cambiar a NUMERIC(15,2)
ALTER TABLE invoices ALTER COLUMN subtotal TYPE NUMERIC(15,2) USING subtotal::numeric;
ALTER TABLE invoices ALTER COLUMN iva TYPE NUMERIC(15,2) USING iva::numeric;
ALTER TABLE invoices ALTER COLUMN total TYPE NUMERIC(15,2) USING total::numeric;
```

### H-02 🟠 ALTO — Fechas como TEXT en vez de DATE/TIMESTAMP
**Archivo:** `b2b_ai/db/models.py:49` (invoices.fecha), `models.py:298-300` (asientos_contables.fecha)
**Descripción:** `invoices.fecha`, `asientos_contables.fecha`, `outstanding_invoices.fecha_vencimiento` son TEXT. Impide indexación por rango, ordenamiento cronológico correcto, y funciones de fecha nativas.
**Impacto:** Queries de rango de fechas usan comparación lexicográfica (falla con formatos inconsistentes), no hay EXTRACT() ni AGE().
**Fix:**
```sql
-- Migración Alembic
ALTER TABLE invoices ALTER COLUMN fecha TYPE DATE USING fecha::date;
ALTER TABLE asientos_contables ALTER COLUMN fecha TYPE DATE USING fecha::date;
ALTER TABLE outstanding_invoices ALTER COLUMN fecha_vencimiento TYPE DATE USING fecha_vencimiento::date;
```

### H-03 🟡 MEDIO — FK faltante en outreach_campaigns.tenant_id
**Archivo:** `b2b_ai/db/models.py:534` (outreach_campaigns), `models.py:209` (collection_events.tenant_id)
**Descripción:** `outreach_campaigns.tenant_id` NO tiene `REFERENCES tenants(id)`. Lo mismo para `collection_events.tenant_id`, `outstanding_invoices.tenant_id`, `notifications.tenant_id`, `audit_log.tenant_id`, `webhook_deliveries.tenant_id`. Solo `invoices`, `users`, `classifications`, `tenant_config`, `reviews`, `billing_*`, `tenant_usage` y `webhook_subscriptions` tienen FK.
**Impacto:** Posible insertar filas huérfanas (tenant_id = 999 inexistente). Sin integridad referencial.
**Fix:**
```sql
ALTER TABLE outreach_campaigns ADD CONSTRAINT fk_outreach_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE collection_events ADD CONSTRAINT fk_coll_events_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE outstanding_invoices ADD CONSTRAINT fk_outstanding_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
-- Repetir para: notifications, audit_log, webhook_deliveries, bank_transactions, bank_confirmations, collection_payments, collection_config, audit_entries, outreach_emails, outreach_events, outreach_campaign_leads
```

### H-04 🟡 MEDIO — Índices faltantes en columnas filtradas frecuentemente
**Archivo:** `b2b_ai/db/models.py` (varios), `b2b_ai/db/db.py` (varios queries)
**Descripción:** Algunas columnas filtradas en queries no tienen índice:
- `invoices.status` — filtrado en queries de dashboard
- `invoices.valido` — filtrado frecuentemente
- `invoices.emisor_rfc` / `receptor_rfc` — búsquedas por RFC
- `client_users.email` — lookup por email (solo tiene idx_client_users_email, OK)
- `outreach_campaign_leads.next_send_at` — scheduler de envíos
- `outreach_campaign_leads.status` — parcialmente cubierto por idx_outreach_leads_campaign_status
- `api_keys.key_hash` — UNIQUE ya crea índice, OK
**Fix:**
```sql
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_valido ON invoices(valido);
CREATE INDEX idx_invoices_emisor_rfc ON invoices(emisor_rfc);
CREATE INDEX idx_invoices_tenant_status ON invoices(tenant_id, status);
CREATE INDEX idx_outreach_leads_next_send ON outreach_campaign_leads(next_send_at)
    WHERE next_send_at IS NOT NULL;
```

---

## 2. MIGRATIONS

### H-05 🔴 CRÍTICO — Migration v15 (privacy_consent) falta en Alembic
**Archivo:** `b2b_ai/db/models.py:696-705` vs `migrations/versions/`
**Descripción:** SQLite migration v15 agrega `accepted_privacy_at` a `client_users`. El archivo más reciente de Alembic es `0007_collections_module.py`. No existe una migración Alembic para este campo. En producción PostgreSQL, `client_users.accepted_privacy_at` NO existirá, causando `column "accepted_privacy_at" does not exist` en los endpoints de portal.
**Impacto:** Portal del cliente roto en producción con PostgreSQL.
**Fix:** Crear `migrations/versions/0008_privacy_consent.py`:
```python
"""privacy_consent: accepted_privacy_at en client_users

Revision ID: 0008_privacy_consent
Revises: 0007_collections_module
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_privacy_consent"
down_revision = "0007_collections_module"

def upgrade() -> None:
    op.add_column("client_users",
        sa.Column("accepted_privacy_at", sa.TIMESTAMP(timezone=True), nullable=True))
```

### H-06 🟡 MEDIO — Archivo duplicado `migration 2.py`
**Archivo:** `b2b_ai/db/migration 2.py`
**Descripción:** Archivo duplicado exacto de `migration.py` con espacio en el nombre. El `ensure_pg_schema()` en la copia usa subprocess.run mientras que el original usa `alembic.command`.
**Impacto:** Confusión de desarrolladores, posible uso del archivo incorrecto.
**Fix:** Eliminar `migration 2.py`.

### H-07 🟡 MEDIO — COALESCE en UNIQUE INDEX es ineficiente en PG
**Archivo:** `b2b_ai/db/models.py:639` (idx_bank_tx_unico), `models.py:651` (idx_bank_conf_unico)
**Descripción:** `CREATE UNIQUE INDEX ... ON bank_transactions(COALESCE(tenant_id, -1), tx_id)` usa una expresión funcional. En PostgreSQL esto crea un índice de expresión que no se usa para queries normales de `WHERE tenant_id = ?`.
**Impacto:** Queries con `WHERE tenant_id=?` no usan este índice. Se necesita un índice adicional.
**Fix:** Agregar índices regulares además del funcional, o usar `WHERE tenant_id IS NOT NULL` + caso separado para NULL.

---

## 3. QUERIES

### H-08 🔴 CRÍTICO — SELECT * masivo (~30 queries)
**Archivo:** `b2b_ai/db/db.py:235,323,375,384,403,580,688,720,768,832,878,916,950,986,1012,1069,1122,1165,1244,1289,1349,1400,1435,1454,1486` (todas las list_ y get_ methods)
**Descripción:** Prácticamente todos los métodos `list_*` y `get_*` usan `SELECT *`. Con PostgreSQL, cada fila devuelve TODAS las columnas incluyendo payloads JSON potencialmente grandes (audit_log.payload, webhook_deliveries.payload, paquetes_contabilidad.payload).
**Impacto:**
- Rendimiento: transferencia de datos innecesarios
- Fragilidad: un ALTER TABLE rompe código que asume columnas específicas
- Memoria: payloads JSON de 100KB+ multiplicados por LIMIT 100
**Fix:** Ejemplo para `list_invoices`:
```python
def list_invoices(self, tenant_id=None, limit=None, ...):
    q = """SELECT id, tenant_id, folio_fiscal, fecha, tipo, emisor_rfc,
                  emisor_nombre, receptor_rfc, subtotal, iva, total,
                  moneda, categoria, confianza, valido, status, created_at
           FROM invoices"""
    # ... resto igual
```
Aplicar a TODOS los métodos `list_*` y `get_*`.

### H-09 🟠 ALTO — N+1 en TenantManager._find_tenant()
**Archivo:** `b2b_ai/db/tenants.py:131-135`
**Descripción:** `_find_tenant()` carga TODOS los tenants con `list_tenants()` y filtra en Python. Esto se llama en `get_tenant()`, `exists()`, `get_config()`, `set_config()`, `scoped_invoice()`, `scoped_invoices()`, `scoped_stats()`, `tenant_health()`.
**Impacto:** O(N) donde N = número de tenants, en cada request.
**Fix:**
```python
def _find_tenant(self, tenant_id: int) -> Optional[Dict[str, Any]]:
    row = self.db.conn.execute(
        "SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    return dict(row) if row else None
```

### H-10 🟠 ALTO — COUNT(*) sin tenant_id en count_audit()
**Archivo:** `b2b_ai/db/db.py:417-423`
**Descripción:** `count_audit(tool_name)` filtra solo por `tool_name` sin `tenant_id`. En un sistema multi-tenant esto devuelve datos de TODOS los tenants.
**Impacto:** Filtrado de datos cross-tenant (violación de aislamiento).
**Fix:**
```python
def count_audit(self, tool_name=None, tenant_id=None):
    q = "SELECT COUNT(*) FROM audit_log"
    params, clauses = [], []
    if tenant_id is not None:
        clauses.append("tenant_id=?")
        params.append(tenant_id)
    if tool_name:
        clauses.append("tool_name=?")
        params.append(tool_name)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    return self.conn.execute(q, params).fetchone()[0]
```

### H-11 🟠 ALTO — list_leads() sin tenant_id (datos globales expuestos)
**Archivo:** `b2b_ai/db/db.py:719-723`
**Descripción:** `list_leads()` no filtra por tenant_id. La tabla leads no tiene tenant_id. Todos los leads son globales y visibles a cualquier admin.
**Impacto:** Un tenant puede ver leads de otro tenant.
**Fix:** Agregar `tenant_id` a la tabla `leads` y filtrar siempre.

### H-12 🟡 MEDIO — SQL injection f-string en list_asientos_contables
**Archivo:** `b2b_ai/db/db.py:1330`
**Descripción:** `q += " LIMIT %d" % int(limit)` — usa formatting directo. Aunque `int()` lo mitiga, es una mala práctica.
**Impacto:** Bajo (int() previene injection), pero inconsistente con el resto del código que usa `?`.
**Fix:**
```python
# En vez de:
q += " LIMIT %d" % int(limit)
# Usar:
q += " LIMIT ?"
params.append(int(limit))
```

### H-13 🟡 MEDIO — `list_tenants()` retorna todo sin paginación
**Archivo:** `b2b_ai/db/db.py:234-235`
**Descripción:** `SELECT * FROM tenants ORDER BY id` sin LIMIT. Con miles de tenants se carga todo en memoria.
**Fix:** Agregar parámetro `limit` con default razonable.

---

## 4. CONNECTION POOL

### H-14 🔴 CRÍTICO — pool_pre_ping NO activo en el pool principal
**Archivo:** `b2b_ai/db/pg.py:240-248` (PGPool), `b2b_ai/db/db.py:47-53` (_get_pg_pool)
**Descripción:** `PGPool` usa `psycopg_pool.ConnectionPool` con un `check` function, pero `pool_pre_ping` como concepto de SQLAlchemy no aplica aquí (no usan SQLAlchemy ORM). Sin embargo, el `check` function SÍ está presente (`_health` en pg.py:233-238), lo cual es equivalente.
**Corrección:** SÍ hay health check — el hallazgo es menor. La `_health` function hace `SELECT 1` lo cual es correcto.
**Severidad revisada:** 🟢 OK

### H-15 🟠 ALTO — Código de pool triplicado
**Archivo:** `b2b_ai/db/pg.py:217-308`, `b2b_ai/db/postgres_adapter.py:420-451`, `b2b_ai/infrastructure/db_pool.py:238-448`
**Descripción:** Tres implementaciones de pool separadas:
1. `PGPool` en pg.py — el que usa db.py en producción
2. `_PGPool` en postgres_adapter.py — usado por PostgresAdapter
3. `EnterpriseConnectionPool` en infrastructure/db_pool.py — pool enterprise con métricas

`EnterpriseConnectionPool` tiene métricas, slow query logging, pre_ping, recycling, pero NO se usa por la capa principal (`db.py`).
**Impacto:** Mantenimiento de código duplicado, confusión sobre cuál usar.
**Fix:** Consolidar: que `db.py` use `EnterpriseConnectionPool` o que las métricas se integren en `PGPool`.

### H-16 🟡 MEDIO — Connection leak potencial en Database._pg_conn()
**Archivo:** `b2b_ai/db/db.py:138-152`
**Descripción:** `_pg_conn()` crea conexiones del pool y las guarda en `self._local.conn` + `self._connections`. Si el thread muere sin llamar `close()`, la conexión se pierde (no se devuelve al pool). `Database.__del__()` no existe.
**Impacto:** Leaks de conexiones bajo carga de hilos (uvicorn workers).
**Fix:**
```python
def __del__(self):
    try:
        self.close()
    except Exception:
        pass
```

### H-17 🟡 MEDIO — Pool no usado por infraestructura
**Archivo:** `b2b_ai/infrastructure/db_pool.py` (clase completa)
**Descripción:** `EnterpriseConnectionPool` tiene pre_ping, slow_query_logging, recycling, métricas Prometheus — pero NINGUNA de las llamadas en db.py o los servicios lo usa. Es código dead en producción.
**Impacto:** Las features enterprise (slow query logging, métricas) no están activas.
**Fix:** Integrar `EnterpriseConnectionPool` en `Database.__init__` o eliminar el código.

---

## 5. MULTI-TENANT

### H-18 🟠 ALTO — Sin RLS (Row-Level Security) en PostgreSQL
**Archivo:** `migrations/` (ninguna migración crea políticas RLS)
**Descripción:** El aislamiento multi-tenant depende 100% de la capa de aplicación (filtros WHERE tenant_id=? en db.py). No hay RLS en PostgreSQL. Un bug en la aplicación, un query olvidado, o acceso directo a la DB expone datos de todos los tenants.
**Impacto:** Un solo query sin `WHERE tenant_id=?` en db.py = leak de datos cross-tenant. Esto ya pasó en H-10 (count_audit).
**Fix:**
```sql
-- En migración Alembic
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON invoices USING (tenant_id = current_setting('app.tenant_id')::bigint);

-- Repetir para TODAS las tablas con tenant_id
-- En la app, al inicio de cada request:
-- SET LOCAL app.tenant_id = '<tenant_id>';
```

### H-19 🟡 MEDIO — leads table no tiene tenant_id
**Archivo:** `b2b_ai/db/models.py:134-143`
**Descripción:** La tabla `leads` no tiene columna `tenant_id`. Es la única tabla de datos sin aislamiento multi-tenant.
**Impacto:** Leads compartidos entre todos los tenants (o visibles a todos).
**Fix:** Agregar `tenant_id` nullable y backfill.

### H-20 🟡 MEDIO — tenant_id nullable en tablas operativas
**Archivo:** `b2b_ai/db/models.py:89` (audit_log), `models.py:104` (notifications), `models.py:185` (webhook_deliveries), `models.py:209` (collection_events), `models.py:225` (outstanding_invoices), `models.py:627-649` (bank_transactions, bank_confirmations), `models.py:491` (audit_entries)
**Descripción:** Varios tablas permiten `tenant_id IS NULL` (no NOT NULL). Los queries usan `COALESCE(tenant_id, -1)` como workaround.
**Impacto:** Datos sin tenant son inseguros — cualquier query sin filtro los incluye.
**Fix:** Hacer `tenant_id NOT NULL` y usar un tenant_id especial (0) para datos de servicio.

---

## 6. TRANSACTIONS

### H-21 🟠 ALTO — commit() manual inconsistente
**Archivo:** `b2b_ai/db/db.py` (varios métodos)
**Descripción:** Algunos métodos hacen `self.conn.commit()` (create_tenant:231, insert_invoice:317, log_call:399), otros usan `with self.conn:` (set_tenant_config:740, upsert_outstanding_invoice:858). No hay consistencia.
**Impacto:**
- `with conn:` en SQLite hace autocommit (context manager de sqlite3)
- `with conn:` en PGConnection hace commit/rollback (custom __exit__)
- Mezclar ambos patrones puede causar commits parciales
**Fix:** Estandarizar a `with self.conn:` para todas las escrituras.

### H-22 🟡 MEDIO — set_outreach_campaign_status pasa literal como parámetro
**Archivo:** `b2b_ai/db/db.py:1027`
**Descripción:** `(status, "CURRENT_TIMESTAMP", campaign_id)` pasa el STRING `"CURRENT_TIMESTAMP"` como valor, no la función SQL.
**Impacto:** `paused_at` se guarda como el string `"CURRENT_TIMESTAMP"`, no como timestamp real.
**Fix:**
```python
self.conn.execute(
    "UPDATE outreach_campaigns SET status=?, paused_at=CURRENT_TIMESTAMP WHERE id=?",
    (status, campaign_id))
```

---

## 7. SQLite vs PostgreSQL

### H-23 🟡 MEDIO — Integer PRIMARY KEY en PG (BIGINT vs INTEGER)
**Archivo:** `b2b_ai/db/models.py:29` (tenants.id), todas las tablas
**Descripción:** En SQLite, `INTEGER PRIMARY KEY` es ROWID alias (autoincrement implícito). En Alembic se usa `sa.BigInteger()` + `sa.Identity()`, que es correcto. Sin embargo, el código Python usa `int` genérico, lo cual es compatible.
**Impacto:** Bajo (compatible), pero `BigInteger` en PG vs `int` en SQLite puede causar overflow en SQLite si hay >2^63 filas (extremadamente improbable).
**Severidad:** 🟢 OK — ya está bien manejado.

### H-24 🟡 MEDIO — LIMIT con placeholder en PG vs SQLite
**Archivo:** `b2b_ai/db/db.py:344-346`
**Descripción:** `q += " LIMIT ?"` funciona en ambos, pero en PostgreSQL el placeholder de LIMIT puede requerir CAST: `LIMIT $1::int`. psycopg3 maneja esto automáticamente, así que es OK.
**Severidad:** 🟢 OK

### H-25 🟡 MEDIO — retention except sqlite3.Error
**Archivo:** `b2b_ai/db/db.py:564`
**Descripción:** `enforce_retention()` captura `sqlite3.Error` pero en modo PG no captura `psycopg.Error`.
**Impacto:** En PG, errores de retención se propagan sin catch.
**Fix:**
```python
except Exception:  # cubre sqlite3.Error y psycopg.Error
    removed[table] = 0
```

---

## 8. BACKUP / RECOVERY

### H-26 🟠 ALTO — Sin estrategia de backup documentada
**Archivo:** Ningún archivo
**Descripción:** No hay scripts de backup, cron jobs, ni documentación de backup para PostgreSQL. No hay pg_dump automatizado, WAL archiving configurado, ni point-in-time recovery.
**Impacto:** Pérdida de datos en caso de fallo de disco.
**Fix:**
```bash
# Script de backup (cron diario)
#!/bin/bash
pg_dump -Fc -f /backups/b2b_ai_$(date +%Y%m%d_%H%M%S).dump $DATABASE_URL
# Retener 30 días
find /backups -name "b2b_ai_*.dump" -mtime +30 -delete
```

### H-27 🟠 ALTO — Sin retención de datos CFF Art. 30
**Archivo:** `b2b_ai/db/db.py:533-567` (enforce_retention)
**Descripción:** `enforce_retention()` borra audit_log, webhook_deliveries, notifications, portal_sessions. El CFF Art. 30 requiere conservar CFDI (facturas) y registros contables por 5 años. La política actual borra audit_log a 365 días, pero no documenta retención de facturas.
**Impacto:** Potencial incumplimiento fiscal si se purgan facturas/audit trails.
**Fix:** Documentar política de retención explícita: facturas 5 años mínimo, audit_log 5 años (CFF), portal_sessions 30 días OK.

---

## 9. ENCRYPTION

### H-28 🟢 OK — Encrypt at-rest parcial implementado
**Archivo:** `b2b_ai/db/db.py:29,67-80`, `b2b_ai/api/security.py:161-175`
**Descripción:** Se encriptan campos sensibles de `tenant_config` (`webhook_url`, `notif_recipient`, `whatsapp_token`) con AES-GCM vía `encrypt_field`/`decrypt_field`. Requiere `B2B_ENCRYPTION_KEY`.
**Riesgo residual:** Sin `B2B_ENCRYPTION_KEY`, los valores se guardan en claro (degradado graceful). Password hashes están hasheados (bcrypt/SHA256), no cifrados.
**Hallazgo:** ✅ Correctamente implementado para tenant_config. Sin embargo, `api_keys` se guardan como SHA256 hash (correcto), pero `client_users.password_hash` debería ser bcrypt (verificar en security.py).

---

## 10. PERFORMANCE

### H-29 🟡 MEDIO — Sin EXPLAIN ANALYZE o query plan review
**Archivo:** Ningún archivo
**Descripción:** No hay evidencia de EXPLAIN ANALYZE en queries críticas. No hay tooling de profiling de queries en el código.
**Fix:** Agregar endpoint de admin o script que ejecute EXPLAIN ANALYZE en las top queries.

### H-30 🟡 MEDIO — invoice_stats() ejecuta 2 queries secuenciales
**Archivo:** `b2b_ai/db/db.py:349-372`
**Descripción:** `invoice_stats()` ejecuta un GROUP BY y luego un COUNT/SUM separados. Se podría hacer en una sola query con window functions.
**Fix:**
```python
q = """SELECT
    COUNT(*) OVER() as total,
    SUM(CAST(total AS REAL)) OVER() as monto_total,
    SUM(CAST(iva AS REAL)) OVER() as iva_total,
    categoria,
    COUNT(*) as n,
    SUM(CAST(total AS REAL)) as monto
FROM invoices WHERE tenant_id=? GROUP BY categoria"""
```

### H-31 🔵 BAJO — get_portal_session() carga user y tenant separadamente
**Archivo:** `b2b_ai/db/db.py:1490-1503`
**Descripción:** `get_portal_session()` hace 3 queries: 1) SELECT session, 2) get_client_user (otro SELECT), 3) dict construction.
**Fix:** JOIN en una sola query:
```python
SELECT ps.*, cu.tenant_id, cu.email, cu.name, cu.role
FROM portal_sessions ps
JOIN client_users cu ON cu.id = ps.user_id
WHERE ps.token_hash = ?
```

---

## 11. HALLAZGOS ADICIONALES

### H-32 🔵 BAJO — `migration 2.py` con espacio en nombre
**Archivo:** `b2b_ai/db/migration 2.py`
**Descripción:** Archivo con espacio en el nombre. Python puede importarlo como módulo, pero `migration 2` no es un nombre de módulo válido.
**Fix:** Eliminar el archivo.

### H-33 🔵 BAJO — lastrowid via SELECT lastval() en PG
**Archivo:** `b2b_ai/db/pg.py:128-135`
**Descripción:** `PGCursor.lastrowid` ejecuta `SELECT lastval()` — una query extra por cada INSERT. `lastval()` puede fallar si no hubo INSERT previo en la sesión.
**Impacto:** Overhead mínimo, pero cada INSERT hace round-trip extra.
**Fix:** Considerar usar `RETURNING id` en los INSERTs y cachear el resultado.

### H-34 🔵 BAJO — PGRecord positional access es O(n)
**Archivo:** `b2b_ai/db/pg.py:83-86`
**Descripción:** `PGRecord.__getitem__(int)` hace `list(self.values())[key]` — O(n) por acceso posicional.
**Fix:**
```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._values = list(self.values())
def __getitem__(self, key):
    if isinstance(key, int):
        return self._values[key]
    return super().__getitem__(key)
```

### H-35 🔵 BAJO — `_is_postgres()` duplicado 3 veces
**Archivo:** `b2b_ai/db/db.py:37-40`, `b2b_ai/db/pool.py:23-25`, `b2b_ai/db/adapter_factory.py:33-39`
**Descripción:** Misma función copiada 3 veces.
**Fix:** Centralizar en un solo módulo (ej. `b2b_ai/db/utils.py`).

---

## Tabla de Priorización

| # | Hallazgo | Severidad | Esfuerzo | Prioridad |
|---|----------|-----------|----------|-----------|
| H-05 | Migration v15 falta en Alembic | 🔴 | 30min | **P0 — Fix ahora** |
| H-22 | paused_at guarda literal string | 🟠 | 5min | **P0 — Fix ahora** |
| H-10 | count_audit sin tenant_id | 🟠 | 5min | **P0 — Fix ahora** |
| H-08 | SELECT * masivo | 🔴 | 2h | **P1 — Sprint actual** |
| H-01 | Monetarios como TEXT | 🔴 | 4h | **P1 — Sprint actual** |
| H-09 | N+1 en _find_tenant | 🟠 | 10min | **P1 — Sprint actual** |
| H-18 | Sin RLS en PostgreSQL | 🟠 | 4h | **P1 — Sprint actual** |
| H-15 | Pool triplicado | 🟠 | 4h | **P2 — Próximo sprint** |
| H-26 | Sin backup automatizado | 🟠 | 2h | **P2 — Próximo sprint** |
| H-27 | Retención CFF Art. 30 | 🟠 | 1h | **P2 — Próximo sprint** |
| H-02 | Fechas como TEXT | 🟠 | 4h | **P2 — Próximo sprint** |
| H-03 | FKs faltantes | 🟡 | 2h | **P2 — Próximo sprint** |
| H-21 | commit() inconsistente | 🟠 | 2h | **P2 — Próximo sprint** |
| H-11 | leads sin tenant_id | 🟠 | 1h | **P3** |
| H-19 | leads sin tenant_id (schema) | 🟡 | 1h | **P3** |
| H-20 | tenant_id nullable | 🟡 | 2h | **P3** |
| H-06 | migration 2.py duplicado | 🟡 | 1min | **P3** |
| H-04 | Índices faltantes | 🟡 | 30min | **P3** |
| H-12 | SQL injection f-string | 🟡 | 5min | **P3** |
| H-13 | list_tenants sin paginación | 🟡 | 10min | **P3** |
| H-16 | Connection leak potencial | 🟡 | 10min | **P3** |
| H-17 | Enterprise pool no usado | 🟡 | 4h | **P4** |
| H-25 | enforce_retention except type | 🟡 | 5min | **P3** |
| H-30 | invoice_stats 2 queries | 🟡 | 15min | **P4** |
| H-29 | Sin EXPLAIN ANALYZE | 🟡 | 1h | **P4** |
| H-07 | COALESCE en UNIQUE INDEX | 🟡 | 30min | **P4** |
| H-31 | get_portal_session 3 queries | 🔵 | 15min | **P4** |
| H-32 | migration 2.py nombre | 🔵 | 1min | **P4** |
| H-33 | lastrowid extra query | 🔵 | 2h | **P4** |
| H-34 | PGRecord O(n) positional | 🔵 | 10min | **P4** |
| H-35 | _is_postgres duplicado | 🔵 | 15min | **P4** |
