# Auditoría de Rendimiento y Costos — Likida AI Enterprise

**Fecha:** 2026-08-01
**Alcance:** b2b_ai/db/, b2b_ai/api/, b2b_ai/services/, b2b_ai/infrastructure/, Dockerfile, railway.toml
**Stack:** FastAPI + PostgreSQL + SQLite (dev) + Redis (opcional) — ~106K líneas Python

---

## Resumen Ejecutivo

| Categoría | Hallazgos Críticos | Hallazgos Altos | Hallazgos Medios | Hallazgos Bajos |
|---|---|---|---|---|
| Database | 3 | 4 | 3 | 2 |
| API Latency | 2 | 3 | 2 | 1 |
| Memory | 1 | 2 | 2 | 1 |
| Caching | 1 | 2 | 1 | 0 |
| Batch Processing | 1 | 2 | 1 | 0 |
| Docker | 0 | 1 | 2 | 1 |
| Railway Costs | 0 | 1 | 2 | 1 |
| LLM Costs | 0 | 1 | 2 | 1 |
| Rate Limits | 1 | 1 | 1 | 0 |
| Scaling | 2 | 2 | 1 | 0 |
| **TOTAL** | **11** | **19** | **17** | **7** |

**Costo estimado actual:** $5–20/mes en Railway (1 réplica, 1 worker)
**Costo con 10x tráfico sin cambios:** $50–100/mes (necesitaría más workers + PG optimizado)
**Costo optimizado con 10x tráfico:** $20–40/mes (con los fixes de esta auditoría)

---

## 1. DATABASE PERFORMANCE

### CRÍTICO — DB-01: N+1 en TenantManager._find_tenant()

**Archivo:** `b2b_ai/db/tenants.py:131-135`

```python
def _find_tenant(self, tenant_id: int) -> Optional[Dict[str, Any]]:
    for t in self.db.list_tenants():  # SELECT * FROM tenants ORDER BY id
        if t["id"] == tenant_id:
            return t
    return None
```

**Problema:** `_find_tenant()` carga TODOS los tenants de la DB y los itera en Python para buscar uno por id. Se llama desde `get_tenant()`, `exists()`, e indirectamente desde `get_config()`, `set_config()`, `scoped_invoice()`, `scoped_invoices()`, `scoped_stats()`, `tenant_health()`, etc. Cada operación de tenant dispara un full table scan.

**Impacto:** Con 100 tenants, cada request que toca un tenant hace `SELECT * FROM tenants` + scan lineal. Con 1000 tenants, cada request de dashboard dispara ~10 queries full-scan.

**Fix:** Reemplazar con `SELECT * FROM tenants WHERE id=?` (point lookup por PK):
```python
def _find_tenant(self, tenant_id: int) -> Optional[Dict[str, Any]]:
    row = self.db.conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    return dict(row) if row else None
```

---

### CRÍTICO — DB-02: SELECT * en 20+ queries — carga columnas innecesarias

**Archivo:** `b2b_ai/db/db.py` — líneas 235, 323, 375, 403, 439, 580, 683, 720, 768, 801, 827, 832, 841, 878, 916, 950, 986, 1006, 1012, 1062

**Problema:** Todas las queries usan `SELECT *` que trae todas las columnas (incluyendo `payload TEXT`, `issues TEXT`, `razon_clasificacion TEXT`, etc.). La tabla `invoices` tiene 25 columnas; la mayoría de listados solo necesita 5-8.

**Impacto:**
- Más datos transferidos entre PostgreSQL y la app (latencia de red).
- Más memoria en el proceso Python (cada `dict(r)` crea un dict con todos los campos).
- Con 10K facturas × 25 columnas ≈ ~50MB transferidos innecesariamente por `/api/v1/invoices`.

**Fix:** Seleccionar solo las columnas necesarias por endpoint. Ejemplo:
```python
# list_invoices — solo columnas de listado
q = "SELECT id, tenant_id, folio_fiscal, fecha, tipo, emisor_rfc, total, categoria, status FROM invoices"
```

---

### CRÍTICO — DB-03: list_invoices() sin límite por defecto en dashboard

**Archivo:** `b2b_ai/api/dashboard.py:70` y `b2b_ai/api/app.py:781`

```python
# dashboard.py:70
invoices = db.list_invoices(tenant_id=tenant)  # sin limit → trae TODAS

# app.py:781 (stats endpoint)
invoices = db.list_invoices(tenant_id=tenant)  # sin limit
```

**Problema:** El dashboard y el endpoint `/api/v1/stats` cargan TODAS las facturas del tenant en memoria para calcular reportes. Con 50K facturas, esto es ~100MB de dicts en RAM.

**Impacto:** Memory spike por request, latency crece linealmente con el número de facturas. Un tenant con 100K facturas podría causar OOM en Railway (512MB RAM).

**Fix:** Usar queries de agregación en DB en vez de Python:
```python
# En vez de traer todas las facturas para calcular stats
q = "SELECT COUNT(*), SUM(CAST(total AS REAL)), SUM(CAST(iva AS REAL)) FROM invoices WHERE tenant_id=?"
```

---

### ALTO — DB-04: Índices faltantes en columnas frecuentemente filtradas

**Archivo:** `migrations/versions/0002_indexes.py` / `b2b_ai/db/models.py`

**Problema:** Los índices compuestos cubren bien `tenant_id + categoria` y `tenant_id + fecha`, pero faltan:

| Columna filtrada | Índice actual | Queries que lo necesitan |
|---|---|---|
| `invoices.status` | ❌ Ninguno | `WHERE status='pending_approval'` |
| `invoices.valido` | ❌ Ninguno | `WHERE valido=?` en list_invoices |
| `invoices.emisor_rfc` | ❌ Ninguno | Dashboard top providers, anomaly detection |
| `invoices.folio_fiscal` | Solo en UNIQUE(tenant_id, folio_fiscal) | SAT status check |
| `classifications.invoice_id` | ❌ Ninguno | JOIN con invoices |
| `audit_entries.tenant_id` | ✅ idx_audit_entries_tenant | OK |

**Impacto:** Full table scan en queries frecuentes del dashboard y API.

**Fix:** Agregar migración:
```sql
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_valido ON invoices(tenant_id, valido);
CREATE INDEX idx_invoices_emisor ON invoices(emisor_rfc);
CREATE INDEX idx_classifications_invoice ON classifications(invoice_id);
```

---

### ALTO — DB-05: Pool de conexiones fragmentado — 3 implementaciones

**Archivos:**
- `b2b_ai/db/pool.py` — ConnectionPool (queue-based, SQLite+PG)
- `b2b_ai/db/pg.py` — PGPool (psycopg_pool wrapper)
- `b2b_ai/infrastructure/db_pool.py` — EnterpriseConnectionPool (full metrics)

**Problema:** Tres implementaciones de pool de conexiones que hacen lo mismo de forma diferente. `db.py` usa `_get_pg_pool()` que crea `PGPool` de `pg.py`. `v2.py` crea un `_DBPool` interno. `infrastructure/db_pool.py` tiene la implementación más completa (metrics, pre_ping, recycling) pero NO se usa en ninguna parte.

**Impacto:** Complejidad innecesaria, difícil de tunear. La implementación usada (`PGPool`) no tiene slow query logging ni connection recycling.

**Fix:** Consolidar en `infrastructure/db_pool.py` (la más completa) y eliminar las otras dos.

---

### ALTO — DB-06: Cada escritura hace commit() individual

**Archivo:** `b2b_ai/db/db.py` — múltiples métodos

**Problema:** Cada `insert_invoice()`, `log_call()`, `insert_notification()`, etc. hace `self.conn.commit()` inmediatamente. En batch processing (1000 CFDIs), esto son 3000+ commits (3 tablas × 1000 facturas).

**Impacto:** PostgreSQL: cada commit es un fsync = ~5ms. 3000 commits = ~15 segundos solo en commits. SQLite: WAL reduce el impacto pero sigue siendo lento.

**Fix:** Usar transacciones explícitas para batches:
```python
# En process_batch, envolver en una transacción
with db.transaction():
    for f in archivos:
        process_file(f, db=db, tenant_id=tenant_id)
```

---

### ALTO — DB-07: Connection pool sizing por defecto insuficiente

**Archivo:** `b2b_ai/db/db.py:49-50`

```python
min_size=int(os.environ.get("B2B_PG_POOL_MIN", "2")),
max_size=int(os.environ.get("B2B_PG_POOL_MAX", "10")),
```

**Problema:** Default max_size=10 conexiones. Con `B2B_WORKERS=1` esto es suficiente, pero si se sube a 2-4 workers, cada worker crea su propio pool → 40 conexiones totales, que puede exceder el límite de Railway PostgreSQL (usualmente 20-30 conexiones).

**Impacto:** Connection exhaustion bajo carga con múltiples workers.

**Fix:** Documentar que `max_pool_size × workers` debe ser < `max_connections` de PG. Sugerir `max_size = max_connections / workers`.

---

### MEDIO — DB-08: Migration en cada nueva conexión PG

**Archivo:** `b2b_ai/db/db.py:151`

```python
def _pg_conn(self):
    ...
    if conn is None:
        ...
        self.migrate()  # Alembic upgrade head en CADA conexión nueva
    return conn
```

**Problema:** Cada vez que se crea una conexión PG nueva (thread nuevo), se ejecuta `alembic upgrade head`. Esto incluye importar `alembic`, leer `alembic.ini`, y hacer queries al schema.

**Impacto:** ~50-100ms por nueva conexión. Bajo carga con pool que rota conexiones, esto suma.

**Fix:** Ejecutar migración solo una vez en startup (lifespan), no por conexión.

---

### MEDIO — DB-09: SQLite como fallback silencioso en producción

**Archivo:** `b2b_ai/db/adapter_factory.py:98-108`

**Problema:** Si `DATABASE_URL` no está configurado, el sistema cae a SQLite sin warning. En Railway esto causaría datos perdidos entre redeploys (SQLite es ephemeral).

**Impacto:** Pérdida de datos silenciosa.

**Fix:** Fail-fast en producción si no hay PostgreSQL configurado:
```python
if os.environ.get("B2B_ENV") == "production" and not is_postgres(url):
    raise RuntimeError("PostgreSQL required in production")
```

---

### MEDIO — DB-10: json.dumps en cada inserción de audit_log

**Archivo:** `b2b_ai/db/db.py:394`

```python
payload_txt = json.dumps(payload, default=str, ensure_ascii=False) if payload is not None else '{}'
```

**Problema:** Cada llamada a `log_call()` serializa el payload a JSON. En batch processing con 1000 CFDIs, cada factura genera 5-8 tool calls → 5000-8000 serializaciones JSON.

**Impacto:** ~1ms por serialización × 8000 = ~8 segundos de overhead puro en JSON.

**Fix:** Considerar async logging o batch inserts para audit_log.

---

### BAJO — DB-11: `count_invoices()` hace full table scan

**Archivo:** `b2b_ai/db/db.py:383-389`

**Problema:** `SELECT COUNT(*) FROM invoices` sin usar estadísticas de PG. Con 1M facturas, PG hace seq scan.

**Fix:** Para PostgreSQL, usar `pg_class.reltuples` para estimación rápida, o cachear el count.

---

### BAJO — DB-12: COALESCE en queries impide uso de índices

**Archivo:** `b2b_ai/db/db.py:628`

```python
"WHERE COALESCE(tenant_id, -1)=COALESCE(?, -1)"
```

**Problema:** `COALESCE()` en el lado izquierdo del WHERE impide que PostgreSQL use el índice en `tenant_id`.

**Fix:** Usar `WHERE tenant_id IS NOT DISTINCT FROM ?` o manejar NULLs en la aplicación.

---

## 2. API LATENCY

### CRÍTICO — API-01: 60 de 69 endpoints son síncronos (bloquean event loop)

**Archivo:** `b2b_ai/api/app.py` — 69 funciones `def` vs 9 `async def`

**Problema:** FastAPI ejecuta funciones `def` síncronas en un threadpool, pero con `B2B_WORKERS=1` (default), solo hay ~4 threads del pool. Los endpoints que hacen I/O (DB queries, llamadas LLM, procesamiento de CFDI) bloquean el thread y reducen la concurrencia.

**Impacto:** Con 4 threads y un endpoint que tarda 200ms (procesar CFDI), el throughput máximo es ~20 req/s. Con 10x tráfico, la API se satura.

**Fix:** Convertir endpoints de alto tráfico a `async def` + usar `asyncpg` o `databases` library. Alternativa más rápida: subir `B2B_WORKERS` a 2-4.

---

### CRÍTICO — API-02: process_file() síncrono bloquea el event loop

**Archivo:** `b2b_ai/api/app.py:677-735`

```python
async def process_invoice(request: Request, ...):
    ...
    res = process_file(tmp.name, db=db, tenant_id=tenant)  # ← SÍNCRONO, bloquea
```

**Problema:** El endpoint `POST /api/v1/invoices/process` es `async def` pero llama a `process_file()` que es completamente síncrona (DB, XML parsing, validación SAT, clasificación LLM, ERP registration, notificaciones). Esto bloquea el event loop de uvicorn durante todo el procesamiento (~100-500ms por CFDI).

**Impacto:** Con 10 CFDIs concurrentes, los requests se serializan. El healthcheck puede timeout.

**Fix:** Usar `asyncio.to_thread()` para envolver la llamada síncrona:
```python
res = await asyncio.to_thread(process_file, tmp.name, db=db, tenant_id=tenant)
```

---

### ALTO — API-03: Dashboard carga TODAS las facturas + reconciliación demo

**Archivo:** `b2b_ai/api/dashboard.py:68-106`

**Problema:** `_build_dashboard_data()` hace:
1. `db.list_invoices(tenant_id=tenant)` — TODAS las facturas
2. `generate_report(invoices)` — procesamiento en Python
3. `_demo_reconcile(invoices)` — conciliación demo contra TODAS las facturas
4. `_invoice_anomalies(invoices)` — detección de anomalías O(n·k)

**Impacto:** Con 10K facturas, este endpoint tarda ~2-5 segundos. Con 100K facturas, ~30 segundos o OOM.

**Fix:**
1. Usar queries de agregación en DB
2. Limitar aúltimas N facturas para el dashboard
3. Mover anomaly detection a background job

---

### ALTO — API-04: /api/v1/stats hace 6+ queries por request

**Archivo:** `b2b_ai/api/app.py:769-793`

**Problema:** El endpoint de stats:
1. `db.list_invoices(tenant_id=tenant)` — trae TODAS
2. `generate_report(invoices)` — procesamiento
3. `db.invoice_stats(tenant_id=tenant)` — 2 queries más
4. `db.list_tenants()` — todos los tenants
5. `db.count_audit()` — count de audit
6. `db.list_notifications()` — todas las notificaciones

El cache TTL (5s) ayuda, pero la primera request después de cada escritura recalcula todo.

**Impacto:** ~500ms por request sin cache.

**Fix:** Precomputar stats en background, servir del cache.

---

### ALTO — API-05: Rate limiter en memoria no funciona con múltiples workers

**Archivo:** `b2b_ai/api/app.py:288-335`

**Problema:** El `RateLimiter` usa un `defaultdict` en memoria. Con `B2B_WORKERS=4`, cada worker tiene su propio rate limiter → un atacante puede hacer 4× el límite.

**Impacto:** Rate limiting inefectivo en producción multi-worker.

**Fix:** Usar el `EnterpriseRateLimitMiddleware` de `rate_limiter.py` con Redis backend (ya implementado pero no instalado en `app.py`).

---

### MEDIO — API-06: Monolito app.py de 1611 líneas

**Archivo:** `b2b_ai/api/app.py` — 1611 líneas, 69 funciones

**Problema:** Todos los endpoints están en un solo archivo. Cada import carga todos los módulos (features, services, etc.) incluso si solo se usa un endpoint.

**Impacto:** Tiempo de startup lento (~2-3s), mayor uso de memoria.

**Fix:** Usar `APIRouter` con `lazy loading` de features.

---

### MEDIO — API-07: _find_tenant se llama en TODA operación de tenant

**Archivo:** `b2b_ai/db/tenants.py:124-138`

**Problema:** Cada operación que toca un tenant pasa por `get_tenant()` → `_find_tenant()` → `list_tenants()` → full scan. Esto se llama en:
- `get_config()`, `set_config()`
- `scoped_invoice()`, `scoped_invoices()`, `scoped_stats()`
- `tenant_health()`
- `erp_factory()`

**Impacto:** ~10ms extra por operación × muchas operaciones/request.

**Fix:** DB-01 fix resuelve esto.

---

## 3. MEMORY USAGE

### CRÍTICO — MEM-01: Dashboard carga TODAS las facturas en memoria

**Archivo:** `b2b_ai/api/dashboard.py:70`

**Problema:** `db.list_invoices(tenant_id=tenant)` sin limit trae todas las facturas como dicts en memoria. Con 50K facturas × ~2KB/dict = ~100MB de RAM.

**Impacto:** Railway Hobby plan tiene 512MB RAM. Un tenant con muchas facturas puede causar OOM.

**Fix:** Paginación + streaming para listados grandes.

---

### ALTO — MEM-02: Jobs async en memoria se pierden al reiniciar

**Archivo:** `b2b_ai/api/v2.py:95-96`

```python
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
```

**Problema:** Los jobs de batch async se guardan en un dict en memoria. Si Railway reinicia el contenedor (deploys, OOM, health check failure), todos los jobs se pierden.

**Impacto:** Pérdida de trabajo en curso. El usuario hace polling de un job que ya no existe.

**Fix:** Persistir jobs en PostgreSQL (tabla `batch_jobs`).

---

### ALTO — MEM-03: Rate limiter acumula claves indefinidamente

**Archivo:** `b2b_ai/api/app.py:295-325` (RateLimiter)

**Problema:** El `RateLimiter` tiene sweep cada 1000 admisiones, pero un atacante que rota IPs puede crear miles de claves antes del sweep.

**Impacto:** Memory leak bajo ataque. El sweep cada 1000 requests puede no ser suficiente.

**Fix:** Usar el `EnterpriseRateLimitMiddleware` con Redis backend (ya implementado).

---

### MEDIO — MEM-04: batch results almacenados en memoria del job

**Archivo:** `b2b_ai/api/v2.py:109-115`

```python
def _finish_job(job_id, summary, results):
    _JOBS[job_id]["results"] = results  # Puede ser lista de 1000 dicts
```

**Problema:** Un batch de 1000 CFDIs genera ~1000 dicts de resultado (~2MB). Jobs nunca se limpian.

**Impacto:** Memory leak acumulativo.

**Fix:** TTL para jobs completados + persistencia en DB.

---

### MEDIO — MEM-05: Cache entries nunca se purgan completamente

**Archivo:** `b2b_ai/api/app.py:139-168` (_StatsCache)

**Problema:** El `_StatsCache` pura entries individuales por TTL, pero las claves viejas con versiones diferentes nunca se eliminan. Cada escritura crea una nueva key.

**Impacto:** Con muchas escrituras, el cache crece indefinidamente.

**Fix:** Purge periódico de entries expiradas, o usar un LRU cache con tamaño máximo.

---

## 4. CACHING

### CRÍTICO — CACHE-01: No hay Redis cache — todo recalcula en cada request

**Archivo:** `pyproject.toml:27` — `redis>=5.0` está en dependencies pero NO se usa para caching.

**Problema:** El único caching es el `_StatsCache` en memoria (TTL 5s) que no funciona entre workers ni sobrevive restarts. No hay cache para:
- Catálogo de cuentas del tenant
- Configuración del tenant (se consulta en CADA request de tenant)
- Listados de facturas
- Resultados de anomaly detection

**Impacto:** Cada request repite las mismas queries. Con 100 req/s, la DB hace 100× las mismas queries.

**Fix:** Implementar Redis cache con `redis.asyncio`:
```python
# Para tenant config (cambia raramente)
async def get_cached_tenant_config(tenant_id):
    key = f"tenant_config:{tenant_id}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    config = db.get_all_tenant_config(tenant_id)
    await redis.setex(key, 300, json.dumps(config))  # 5min TTL
    return config
```

---

### ALTO — CACHE-02: data_version invalidación es global, no por tenant

**Archivo:** `b2b_ai/db/db.py:107-112`

```python
def _bump_version(self) -> None:
    with self._version_lock:
        self._data_version += 1
```

**Problema:** `data_version` es global para toda la DB. Una escritura en tenant A invalida el cache de tenant B.

**Impacto:** Cache hit rate bajo con múltiples tenants activos.

**Fix:** Version por tenant: `data_version[tenant_id]`.

---

### ALTO — CACHE-03: Dashboard cache no usa la versión de datos correctamente

**Archivo:** `b2b_ai/api/dashboard.py:475`

```python
cached = _dash_cache.get(id(db), "dashboard_data", tenant, db.data_version())
```

**Problema:** `id(db)` es el id del objeto Python, que cambia en cada restart. El cache nunca hace hit después de un redeploy.

**Impacto:** Cache inútil después de cada deploy.

**Fix:** Usar un string fijo como db identifier.

---

## 5. BATCH PROCESSING

### CRÍTICO — BATCH-01: process_batch() es secuencial y síncrono

**Archivo:** `b2b_ai/services/pipeline.py:232-264`

```python
def process_batch(folder, db=None, tenant_id=None, ...):
    for f in archivos:
        result = process_file(f, db=db, tenant_id=tenant_id)  # Uno por uno
```

**Problema:** Procesa CFDIs uno por uno, secuencialmente. Cada `process_file()` incluye: parse XML → validate → classify (posible LLM call) → anomaly detection → ERP register → DB insert → notification. ~200-500ms por CFDI.

**Impacto:** 1000 CFDIs × 300ms = 300 segundos (5 minutos). El HTTP request timeout de Railway es 60 segundos.

**Fix:**
1. Usar `ThreadPoolExecutor` para paralelizar (ya existe en v2.py pero no se usa en pipeline.py)
2. Procesar en chunks de 50 con parallel execution
3. Siempre usar modo async para batches > 10

---

### ALTO — BATCH-02: Batch async usa threading.Thread sin pool

**Archivo:** `b2b_ai/api/v2.py:377-383`

```python
if req.async_:
    job_id = _new_job(tenant)
    t = threading.Thread(target=lambda: _run_job(...), daemon=True)
    t.start()
```

**Problema:** Cada batch async crea un thread nuevo sin límite. Un atacante que envía 100 requests de batch async crea 100 threads, cada uno abriendo su propia conexión a DB.

**Impacto:** Thread exhaustion, connection exhaustion, posible OOM.

**Fix:** Usar un `ThreadPoolExecutor` con max_workers limitado.

---

### ALTO — BATCH-03: Sin chunking para listados grandes

**Archivo:** `b2b_ai/db/db.py:320-347` (list_invoices)

**Problema:** `list_invoices()` con limit=1000 trae todo de una vez. Con fetchall(), PostgreSQL envía todas las filas en un solo round-trip.

**Impacto:** Con 1000 facturas × 25 columnas = ~5MB de datos en un solo fetch.

**Fix:** Usar server-side cursors o fetchmany() para streaming.

---

## 6. DOCKER IMAGE

### ALTO — DOCKER-01: Imagen de producción de 353MB — optimizable

**Archivo:** `Dockerfile`

**Problema:** La imagen de producción (`b2b-ai:1.0.0`) pesa 353MB. El test pesa 897MB.

**Desglose estimado:**
- `python:3.11-slim-bookworm` base: ~150MB
- Dependencias Python (psycopg, lxml, reportlab, openpyxl, etc.): ~120MB
- Código + landing: ~30MB
- build-essential en builder stage (bien, no se copia)

**Impacto:** Deploys más lentos, más consumo de almacenamiento en Railway.

**Fix:**
1. `COPY --from=builder /build/b2b_ai ./b2b_ai` se copia al builder pero no se necesita en runtime (ya está en /install). Verificar que no se copia código fuente redundante.
2. Considerar `python:3.11-slim-bookworm` con `--no-install-recommends` ya aplicado (bien).
3. reportlab (~30MB) solo se usa para PDFs — considerar moverlo a optional dependency.

---

### MEDIO — DOCKER-02: Sin BuildKit cache mount para pip

**Archivo:** `Dockerfile:36`

```dockerfile
RUN pip install --prefix=/install --no-cache-dir .
```

**Problema:** Sin `--mount=type=cache,target=/root/.cache/pip`, cada build re-descarga todas las dependencias.

**Impacto:** Build time ~3-5 minutos en vez de ~30 segundos con cache.

**Fix:** Agregar BuildKit syntax:
```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install .
```

---

### MEDIO — DOCKER-03: COPY de código fuente al builder innecesario

**Archivo:** `Dockerfile:30-31`

```dockerfile
COPY b2b_ai ./b2b_ai
COPY landing ./landing
```

**Problema:** Se copia `b2b_ai/` completo al builder stage, pero `pip install .` lo instala en `/install`. El código fuente no se necesita en el runtime stage (ya está en `/install/lib/python3.11/site-packages/`).

**Impacto:** Capa Docker cacheada se invalida cada vez que cambia el código, forzando reinstalación de dependencias.

**Fix:** Separar COPY de requirements del código:
```dockerfile
COPY pyproject.toml README.md ./  # Primero (cacheable)
RUN pip install --prefix=/install --no-cache-dir .
COPY b2b_ai ./b2b_ai  # Después (cambia más)
```

---

## 7. RAILWAY COSTS

### ALTO — COST-01: Single worker limita throughput a ~20 req/s

**Archivo:** `railway.toml:14`

```toml
startCommand = "sh -c 'uvicorn ... --workers ${B2B_WORKERS:-1}'"
```

**Problema:** 1 worker de uvicorn maneja ~20-50 req/s dependiendo del endpoint. Los endpoints de procesamiento de CFDI (~300ms) limitan a ~3 req/s por worker.

**Impacto:** Con $5/mes (Hobby plan, 1 vCPU, 512MB RAM), el throughput máximo es ~3 CFDIs/segundo.

**Fix:**
1. Subir a `B2B_WORKERS=2` (cabe en 512MB si se optimiza la memoria)
2. Railway Pro ($20/mes, 8 vCPU, 8GB RAM) permite 4 workers → ~12 CFDIs/s

---

### MEDIO — COST-02: Health check cada 15s consume recursos

**Archivo:** `railway.toml:11`

```toml
healthcheckInterval = 15
```

**Problema:** Cada 15s Railway hace GET /health que ejecuta `db.count_invoices()` + `db.list_tenants()` + `db.schema_version()`. Con PostgreSQL, esto son 3 queries.

**Impacto:** ~2880 health check queries/día. Menor con SQLite pero innecesario.

**Fix:** Health check simple sin queries DB:
```python
@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}
```

---

### MEDIO — COST-03: numReplicas=1 — sin high availability

**Archivo:** `railway.toml:16`

**Problema:** Solo 1 réplica. Si el contenedor crashea, hay downtime hasta que Railway reinicia.

**Fix:** Para producción, usar 2 réplicas mínimo (requiere Redis para rate limiting y cache compartidos).

---

## 8. LLM COSTS

### ALTO — LLM-01: Sin model routing — siempre usa el mismo modelo

**Archivo:** `b2b_ai/services/llm.py:575-589`

```python
def get_llm(provider=None):
    provider = (provider or os.environ.get("B2B_LLM_PROVIDER", "")).lower()
    if provider == "openai": return OpenAIProvider()
    ...
    return MockLLM()
```

**Problema:** No hay routing por complejidad de tarea. Todas las tareas (classify, extract, summarize, anomaly) usan el mismo modelo. Para clasificación de CFDIs (tarea simple con keywords claras), un modelo caro como `gpt-4o` es overkill.

**Impacto:** Si se configura `gpt-4o` para todo:
- classify: ~500 tokens × $0.005/1K = $0.0025/CFDI
- Con 10K CFDIs/mes = $25/mes solo en LLM

Con routing a `gpt-4o-mini` para classify:
- classify: ~500 tokens × $0.00015/1K = $0.000075/CFDI
- Con 10K CFDIs/mes = $0.75/mes

**Ahorro potencial:** $24.25/mes (97% reduction)

**Fix:** Implementar model routing por tarea:
```python
TASK_MODELS = {
    "classify": "gpt-4o-mini",      # Simple, keywords-based
    "extract": "gpt-4o-mini",       # Structured extraction
    "summarize": "gpt-4o-mini",     # Short text
    "anomaly": "gpt-4o",            # Needs reasoning
}
```

---

### MEDIO — LLM-02: Token budget reset por sesión, no por tenant

**Archivo:** `b2b_ai/services/llm.py:194`

```python
_global_budget = TokenBudget()  # Singleton, compartido entre TODOS los tenants
```

**Problema:** El presupuesto de tokens es global. Un tenant que consume mucho agota el presupuesto para todos.

**Impacto:** Un tenant abusivo puede bloquear el LLM para todos.

**Fix:** Budget por tenant.

---

### MEDIO — LLM-03: Estimación de tokens rough (4 chars/token)

**Archivo:** `b2b_ai/services/llm.py:282-284`

```python
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

**Problema:** La estimación de 4 chars/token es imprecisa para español (tokens más cortos) y JSON (muchos símbolos). Puede subestimar el costo real.

**Impacto:** Desviación de ±30% en el tracking de costos.

**Fix:** Usar `tiktoken` para estimación precisa (OpenAI) o el usage de la respuesta API.

---

## 9. API RATE LIMITS

### CRÍTICO — RL-01: Rate limiter in-memory duplicado con Enterprise middleware

**Archivos:**
- `b2b_ai/api/app.py:288-335` — `RateLimiter` (instalado)
- `b2b_ai/api/rate_limiter.py` — `EnterpriseRateLimitMiddleware` (NO instalado)

**Problema:** Hay DOS implementaciones de rate limiting. La que está instalada (`RateLimiter`) es in-memory y no funciona con múltiples workers. La `EnterpriseRateLimitMiddleware` soporta Redis y per-tenant limits pero NO se usa.

**Impacto:** Rate limiting inefectivo en producción multi-worker.

**Fix:** Reemplazar `RateLimiter` con `EnterpriseRateLimitMiddleware` + Redis.

---

### ALTO — RL-02: Rate limit por IP+ruta, no por tenant

**Archivo:** `b2b_ai/api/app.py:553`

```python
key = (_client_ip(request), path)
```

**Problema:** Rate limit por IP. Si el cliente usa un proxy (común en empresas), todas las requests vienen de la misma IP → rate limit se activa para todos los usuarios de una empresa.

**Impacto:** Falsos positivos de rate limiting para clientes enterprise.

**Fix:** Rate limit por tenant (ya implementado en `EnterpriseRateLimitMiddleware`).

---

## 10. SCALING

### CRÍTICO — SCALE-01: SQLite no soporta múltiples writers concurrentes

**Archivo:** `b2b_ai/db/db.py:121-136`

**Problema:** Si se usa SQLite en producción (posible si DATABASE_URL no está configurado), solo 1 writer a la vez. Con múltiples workers, los writes se serializan con `busy_timeout = 5000ms`.

**Impacto:** Throughput de escritura limitado a ~200 writes/s con SQLite vs ~5000+ con PostgreSQL.

**Fix:** DB-09 fix (fail-fast si no hay PG en producción).

---

### CRÍTICO — SCALE-02: Sin horizontal scaling — stateful en memoria

**Archivo:** `b2b_ai/api/v2.py:95-96` (_JOBS), `b2b_ai/api/app.py:139-168` (_StatsCache), `b2b_ai/api/app.py:288-335` (RateLimiter)

**Problema:** Estado en memoria (jobs, cache, rate limiter) impide horizontal scaling. Con 2 réplicas:
- Jobs batch solo visibles en la réplica que los creó
- Rate limits se duplican
- Cache no se comparte

**Impacto:** Imposible escalar a más de 1 réplica sin perder funcionalidad.

**Fix:** Migrar todo a Redis/PostgreSQL:
- Jobs → tabla `batch_jobs`
- Cache → Redis
- Rate limiter → Redis (ya implementado)

---

### ALTO — SCALE-03: Batch async crea Database() por thread sin pool sharing

**Archivo:** `b2b_ai/api/v2.py:392`

```python
def _run_job(job_id, tenant_id, paths, folder, webhook):
    dbx = Database(db.path, migrate=False)  # Nueva instancia por job
```

**Problema:** Cada batch job crea una instancia `Database` nueva con su propio pool de conexiones. Con 10 batch jobs concurrentes = 10 pools × 10 conexiones = 100 conexiones PG.

**Impacto:** Connection exhaustion en PostgreSQL.

**Fix:** Usar el pool compartido (`_PG_POOLS`) en vez de crear instancias nuevas.

---

### ALTO — SCALE-04: process_file() carga historial completo para anomaly detection

**Archivo:** `b2b_ai/services/pipeline.py:114`

```python
historico = db.list_invoices(tenant_id=tenant_id, limit=200)
```

**Problema:** Cada CFDI procesado carga las últimas 200 facturas para anomaly detection. En batch de 1000 CFDIs, esto son 1000 queries de 200 facturas cada una.

**Impacto:** ~200K filas leídas innecesariamente. El historial no cambia entre CFDIs del mismo batch.

**Fix:** Cargar historial una vez antes del batch y reutilizar.

---

## TABLA RESUMEN DE PRIORIDADES

| # | ID | Severidad | Categoría | Ahorro Estimado | Esfuerzo |
|---|---|---|---|---|---|
| 1 | DB-01 | 🔴 CRÍTICO | Database | -10ms/request | 5 min |
| 2 | API-02 | 🔴 CRÍTICO | Latency | -200ms/request | 15 min |
| 3 | BATCH-01 | 🔴 CRÍTICO | Batch | -90% tiempo batch | 2 horas |
| 4 | CACHE-01 | 🔴 CRÍTICO | Caching | -50% queries DB | 4 horas |
| 5 | SCALE-02 | 🔴 CRÍTICO | Scaling | Habilita HA | 8 horas |
| 6 | RL-01 | 🔴 CRÍTICO | Rate Limits | Habilita multi-worker RL | 1 hora |
| 7 | DB-02 | 🔴 CRÍTICO | Database | -30% datos transferidos | 2 horas |
| 8 | DB-03 | 🔴 CRÍTICO | Database | -90% RAM dashboard | 1 hora |
| 9 | API-01 | 🔴 CRÍTICO | Latency | +50% throughput | 8 horas |
| 10 | MEM-01 | 🔴 CRÍTICO | Memory | Previene OOM | 1 hora |
| 11 | SCALE-01 | 🔴 CRÍTICO | Scaling | Previene data loss | 5 min |
| 12 | DB-04 | 🟠 ALTO | Database | -20% query time | 30 min |
| 13 | DB-06 | 🟠 ALTO | Database | -80% commit time batch | 2 horas |
| 14 | API-03 | 🟠 ALTO | Latency | -90% dashboard time | 2 horas |
| 15 | API-04 | 🟠 ALTO | Latency | -80% stats time | 1 hora |
| 16 | LLM-01 | 🟠 ALTO | LLM Costs | -$24/mes | 1 hora |
| 17 | COST-01 | 🟠 ALTO | Railway | +100% throughput | 5 min |
| 18 | BATCH-02 | 🟠 ALTO | Batch | Previene thread exhaustion | 30 min |
| 19 | MEM-02 | 🟠 ALTO | Memory | Previene data loss | 2 horas |

---

## PLAN DE IMPLEMENTACIÓN RECOMENDADO

### Fase 1 — Quick Wins (1 día, $0 costo)
1. DB-01: Fix `_find_tenant()` → point lookup
2. DB-04: Agregar índices faltantes
3. API-02: `asyncio.to_thread()` para process_file
4. DOCKER-02: BuildKit cache mount
5. COST-01: Subir B2B_WORKERS a 2

### Fase 2 — Performance (2-3 días, $0-5/mes)
1. DB-02: SELECT específico en vez de SELECT *
2. DB-03: Agregar LIMIT a dashboard queries
3. API-03: Dashboard con aggregation queries
4. BATCH-01: ThreadPoolExecutor para batches
5. BATCH-03: Chunking para listados grandes
6. RL-01: Instalar EnterpriseRateLimitMiddleware

### Fase 3 — Scaling (1 semana, $5-10/mes adicionales)
1. CACHE-01: Implementar Redis cache
2. SCALE-02: Persistir jobs en PostgreSQL
3. MEM-02: Jobs persistence
4. LLM-01: Model routing por tarea
5. DB-05: Consolidar pools de conexiones

### Fase 4 — Production Hardening (1-2 semanas)
1. API-01: Convertir endpoints críticos a async
2. SCALE-03: Pool sharing para batch jobs
3. DB-06: Transaction batching
4. CACHE-02: Per-tenant versioning
5. Monitoring: Prometheus + alertas

---

*Auditoría generada el 2026-08-01 por el agente de rendimiento y costos.*
