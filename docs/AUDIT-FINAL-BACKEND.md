# Auditoría Backend & Arquitectura — Likida AI Enterprise

> Auditoría exhaustiva de `b2b_ai/api/`, `b2b_ai/services/`, `b2b_ai/features/`, `b2b_ai/infrastructure/`
> Fecha: 2026-08-01
> Stack: FastAPI + PostgreSQL + SQLAlchemy + Redis
> Volumen: ~108K líneas Python, ~20 features, deploy en Railway

---

## Resumen Ejecutivo

**Hallazgo crítico: La infraestructura enterprise fue construida pero NUNCA instalada.** Los módulos de errors, idempotency, versioning, graceful shutdown, OpenAPI docs, rate limiter avanzado, y config Pydantic existen con implementaciones completas pero `api/app.py` no los importa ni los registra. Toda la app corre con los defaults básicos de FastAPI (HTTPException sin estructura, rate limiter propio simple, sin trace IDs en respuestas).

| Categoría | Hallazgos | CRÍTICO | ALTO | MEDIO | BAJO |
|-----------|-----------|---------|------|-------|------|
| API Design | 4 | 0 | 2 | 1 | 1 |
| Error Handling | 3 | 1 | 1 | 1 | 0 |
| Middleware Stack | 3 | 0 | 1 | 1 | 1 |
| Service Layer | 3 | 0 | 1 | 1 | 1 |
| Dependency Injection | 2 | 0 | 1 | 1 | 0 |
| Configuration | 2 | 0 | 1 | 1 | 0 |
| Background Tasks | 2 | 1 | 0 | 1 | 0 |
| Graceful Shutdown | 1 | 1 | 0 | 0 | 0 |
| Health Checks | 2 | 0 | 1 | 1 | 0 |
| Observability | 3 | 0 | 1 | 1 | 1 |
| API Docs | 1 | 0 | 1 | 0 | 0 |
| Idempotency | 1 | 0 | 1 | 0 | 0 |
| **TOTAL** | **27** | **3** | **11** | **9** | **4** |

---

## 1. API Design

### 1.1 ALTO — ap_ar router sin prefijo API versionado
- **Archivo**: `b2b_ai/features/ap_ar/routes.py:78`
- **Descripción**: `build_ap_ar_router()` crea `APIRouter(tags=["ap-ar"])` sin `prefix="/api/v1/ap-ar"`. Los endpoints quedan expuestos en la raíz (`/ap/invoices`, `/ar/invoices`, `/ar/aging`) sin el prefijo `/api/v1/` que usan TODOS los demás routers. Inconsistente y rompe el versionado.
- **Severidad**: ALTO
- **Fix**: `router = APIRouter(prefix="/api/v1/ap-ar", tags=["ap-ar"])` y actualizar paths internos.

### 1.2 ALTO — Nombres mixtos español/inglés en endpoints
- **Archivo**: Múltiples archivos en `b2b_ai/features/*/routes.py`
- **Descripción**: Algunos routers usan español (`/api/v1/declaraciones`, `/api/v1/contabilidad`, `/api/v1/devolucion_iva`) y otros inglés (`/api/v1/bookkeeping`, `/api/v1/dashboard`). Los prefijos deberían seguir un solo idioma para la API pública.
- **Severidad**: ALTO (consistencia de API)
- **Fix**: Estandarizar a inglés en la API pública; mantener español en dominio interno/modelos.

### 1.3 MEDIO — Versionado v1/v2 inconsistente
- **Archivo**: `b2b_ai/api/app.py:78-79`, `b2b_ai/api/app.py:1159`
- **Descripción**: Existe `api/v2.py` con endpoints enterprise (batch, analytics, webhooks, audit, export). Se registra correctamente en `app.py:1159`. Pero `api/versioning.py` (middleware de deprecación con headers RFC 8594) nunca se instala. Los usuarios de v1 no reciben headers de deprecación ni `Sunset`.
- **Severidad**: MEDIO
- **Fix**: Importar y llamar `install_versioning(app)` en `create_app()`.

### 1.4 BAJO — Legacy endpoints sin deprecation warnings
- **Archivo**: `b2b_ai/api/app.py` (endpoints documentados en docstring líneas 25-26)
- **Descripción**: Endpoints legacy (`/invoices`, `/stats`, `/tools`, `/process`) están documentados en el docstring pero su estado de deprecación no se comunica al cliente via headers.
- **Severidad**: BAJO
- **Fix**: Migrar a v1-only o añadir `Deprecation` headers.

---

## 2. Error Handling

### 2.1 CRÍTICO — Sistema de errores enterprise construido pero NUNCA instalado
- **Archivo**: `b2b_ai/api/errors.py` (393 líneas, completo) vs `b2b_ai/api/app.py`
- **Descripción**: `errors.py` implementa un sistema enterprise completo:
  - `EnterpriseError` con códigos numéricos por categoría (1xxx auth, 2xxx fiscal, etc.)
  - Trace IDs en cada respuesta de error (`X-Trace-Id` header + campo `trace_id`)
  - Scrubbing de PII en mensajes de error
  - Exception handlers globales para 422, 500, y EnterpriseError
  - `install_error_handlers(app)` para registrar todo
  
  **Ninguna de esto se usa.** `errors.py` no se importa en `app.py`. Toda la API usa `HTTPException` crudo (33 usos en app.py, 22 en conciliacion, 18 en multi_tenant, etc.). Los errores llegan como `{"detail": "..."}` sin código, sin trace_id, sin estructura consistente.
- **Severidad**: CRÍTICO
- **Fix**: Añadir a `create_app()`:
  ```python
  from b2b_ai.api.errors import install_error_handlers
  install_error_handlers(app)
  ```
  Luego migrar gradualmente los `HTTPException` a `EnterpriseError`/`raise_*_error()`.

### 2.2 ALTO — Sin trace IDs en respuestas
- **Archivo**: `b2b_ai/api/app.py` (toda la app)
- **Descripción**: No hay middleware que genere/propague trace IDs. Si un error ocurre en producción, no hay forma de correlacionar el error del cliente con los logs del servidor. `errors.py` tiene `generate_trace_id()` + `ContextVar` listos, pero no están conectados.
- **Severidad**: ALTO
- **Fix**: Instalar `install_error_handlers(app)` que incluye `trace_id_middleware`.

### 2.3 MEDIO — Respuestas 429 inconsistentes
- **Archivo**: `b2b_ai/api/app.py:556-560`
- **Descripción**: El rate limiter propio devuelve `{"detail": "Demasiadas peticiones..."}` (en español). El módulo `rate_limiter.py` tiene el formato enterprise con `Retry-After` y estructura `{"error": {code, type, message, retry_after_seconds, trace_id}}` pero no se usa.
- **Severidad**: MEDIO
- **Fix**: Usar el rate limiter enterprise o al menos el formato de error estructurado.

---

## 3. Middleware Stack

### 3.1 ALTO — Orden de middleware subóptimo
- **Archivo**: `b2b_ai/api/app.py:508-603`
- **Descripción**: Orden actual de middleware (de más externo a más interno):
  1. `SecurityHeadersMiddleware` (línea 508) — ✅ correcto como externo
  2. `CORSMiddleware` (línea 528) — ✅ correcto
  3. Rate limit (línea 548) — ⚠️ debería ser antes del parsing de body
  4. Metrics (línea 567) — ⚠️ cuenta requests rechazadas por rate limit
  5. Request context (línea 583) — ✅ correcto
  6. Audit middleware (línea 598) — ✅ correcto
  7. Size limit (línea 603) — ❌ dice "outermost" pero se registra DESPUÉS de audit

  El comentario en línea 602 dice "Registered after all other middleware so it is the outermost layer" pero en ASGI/FastAPI, el **último** `add_middleware` es el más **externo**. Así que size limit SÍ es externo — el comentario es correcto pero confuso.
  
  **Problema real**: el `RateLimiter` propio de `app.py` se usa en vez del enterprise `api/rate_limiter.py` que tiene Redis support, headers estándar `X-RateLimit-*`, y configuración por tenant.
- **Severidad**: ALTO
- **Fix**: Reemplazar con `install_enterprise_rate_limit(app)` de `b2b_ai.api.rate_limiter`.

### 3.2 MEDIO — Doble sistema de rate limiting
- **Archivo**: `b2b_ai/api/app.py:288-335` vs `b2b_ai/api/rate_limiter.py` (300 líneas)
- **Descripción**: `app.py` implementa su propio `RateLimiter` con ventana deslizante en memoria. `rate_limiter.py` implementa uno enterprise con Redis, headers estándar, configuración por tenant/endpoint/rol. Solo uno se usa (el propio). Código duplicado y el enterprise se desperdicia.
- **Severidad**: MEDIO
- **Fix**: Consolidar en `rate_limiter.py` y eliminar el propio.

### 3.3 BAJO — Metrics middleware cuenta requests de rate-limit como métricas
- **Archivo**: `b2b_ai/api/app.py:567-579`
- **Descripción**: El middleware de métricas se registra DESPUÉS del rate limiter, así que cuenta las 429 como requests normales. Esto infla artificialmente el conteo de requests y el cálculo de error rate.
- **Severidad**: BAJO
- **Fix**: O excluir 429 del conteo de errores, o registrar métricas antes del rate limiter y manejar 429 aparte.

---

## 4. Service Layer

### 4.1 ALTO — services/ mezcla capas (DB directa)
- **Archivo**: `b2b_ai/services/pipeline.py:21`, `b2b_ai/services/demo.py:25`
- **Descripción**: `pipeline.py` importa directamente `from b2b_ai.db.db import Database` y `demo.py` importa `DEFAULT_DB`. Los servicios de la capa `services/` deberían recibir la DB por inyección, no importarla ni instanciarla. Esto impide testing aislado y viola la separación API ↔ Service ↔ DB.
- **Severidad**: ALTO
- **Fix**: Pipeline y demo deberían recibir `db` como parámetro, igual que los routers.

### 4.2 MEDIO — Business logic en routes de app.py
- **Archivo**: `b2b_ai/api/app.py:674-735` (process_invoice)
- **Descripción**: El endpoint `process_invoice` hace parsing de multipart, validación de extensión, creación de tempfile, y llamada a `process_file()` — toda la lógica de orquestación vive en el handler. Debería delegar a un servicio.
- **Severidad**: MEDIO
- **Fix**: Extraer a un `InvoiceProcessingService` que maneje el flujo completo.

### 4.3 BAJO — Algunas features no tienen service.py
- **Archivo**: `b2b_ai/features/nomina/`, `b2b_ai/features/pagos/`, `b2b_ai/features/contabilidad/`
- **Descripción**: Estas features tienen routes.py + parsers/validators pero no service.py. La lógica de negocio vive directamente en los parsers o en el router.
- **Severidad**: BAJO
- **Fix**: Extraer lógica de negocio a service.py siguiendo el patrón de clientes, declaraciones, etc.

---

## 5. Dependency Injection

### 5.1 ALTO — ap_ar usa singletons de módulo
- **Archivo**: `b2b_ai/features/ap_ar/routes.py:58-63`
- **Descripción**: `_ap_manager`, `_ar_manager`, `_notas_credito` son variables de módulo (globals). Se inicializan una vez con `or` lazy. Esto impide testing con mocks, crea state leaks entre tests, y no permite multi-tenant (un solo manager compartido).
- **Severidad**: ALTO
- **Fix**: Recibir managers como parámetros en `build_ap_ar_router()` o usar dependency injection via FastAPI `Depends`.

### 5.2 MEDIO — Router builders con DI inconsistente
- **Archivo**: Múltiples `b2b_ai/features/*/routes.py`
- **Descripción**: La mayoría de routers reciben `(db, require_api_key)` — buen patrón. Pero algunos solo reciben `(require_api_key)` sin `db`: `contabilidad`, `nomina`, `pagos`, `contabilidad_electronica`, `nomina_completa`, `pre_auditoria`. Estos features no pueden acceder a la DB multi-tenant del request.
- **Severidad**: MEDIO
- **Fix**: Estandarizar todos los routers a recibir `(db, require_api_key)`.

---

## 6. Configuration

### 6.1 ALTO — Settings Pydantic construido pero no usado
- **Archivo**: `b2b_ai/infrastructure/config.py` (390 líneas) vs `b2b_ai/api/app.py`
- **Descripción**: `config.py` implementa un sistema enterprise de configuración con:
  - `Settings` con sub-configs (DatabaseSettings, RedisSettings, AuthSettings, etc.)
  - Validación Pydantic con fail-fast en startup
  - Secret masking en string representations
  - Environment-specific overrides
  
  **No se usa.** `app.py` tiene 9 llamadas directas a `os.environ.get()`. La configuración no se valida en startup — errores de config solo se descubren en runtime.
- **Severidad**: ALTO
- **Fix**: Inicializar `settings = Settings.from_env()` en startup y pasar a componentes.

### 6.2 MEDIO — Configuración hardcodeada
- **Archivo**: `b2b_ai/api/app.py:291-293`
- **Descripción**: El `RateLimiter` tiene defaults hardcodeados (`limit=300, window=60.0`). El `_StatsCache` tiene `ttl_seconds=5.0`. Estos deberían venir de configuración.
- **Severidad**: MEDIO
- **Fix**: Migrar a Settings.

---

## 7. Background Tasks

### 7.1 CRÍTICO — Sin Celery configurado
- **Archivo**: `b2b_ai/features/close_management/scheduler.py`
- **Descripción**: Solo existe un task de Celery opcional en scheduler.py (close management). No hay `celery_app` configurado, no hay `celeryconfig.py`, no hay workers, no hay beat schedule. Los procesos batch (v2/batch) usan `ThreadPoolExecutor` en memoria — no persiste a través de restarts, no tiene retry, no tiene dead letter queue.
- **Severidad**: CRÍTICO (para producción)
- **Fix**: Configurar Celery con Redis como broker, definir tasks para batch processing, añadir retry policies con exponential backoff, y configurar dead letter queue.

### 7.2 MEDIO — Async job store en memoria
- **Archivo**: `b2b_ai/api/v2.py:95-119`
- **Descripción**: `_JOBS` es un dict en memoria con lock. Si el proceso restartea, todos los jobs se pierden. Los jobs async (batch processing) no sobreviven deploy.
- **Severidad**: MEDIO
- **Fix**: Persistir jobs en DB (tabla `jobs`) o Redis.

---

## 8. Graceful Shutdown

### 8.1 CRÍTICO — Graceful shutdown construido pero no instalado
- **Archivo**: `b2b_ai/infrastructure/graceful_shutdown.py` (347 líneas) vs `b2b_ai/api/app.py`
- **Descripción**: El módulo implementa:
  - SIGTERM/SIGINT handlers
  - Drain period configurable (30s default)
  - Request tracking (active requests count)
  - Cleanup task registry
  - Health check integration (rechaza requests nuevos durante drain)
  
  **No se instala.** `app.py` tiene un lifespan handler minimal que solo cierra pools de DB. No hay signal handlers, no hay drain period, no hay request tracking. En Railway, un SIGTERM mata el proceso inmediatamente — requests en vuello se cortan.
- **Severidad**: CRÍTICO
- **Fix**: Instalar `GracefulShutdownHandler` en el lifespan de `create_app()`.

---

## 9. Health Checks

### 9.1 ALTO — Sin /health/live ni /health/ready
- **Archivo**: `b2b_ai/api/app.py:633-669` vs `b2b_ai/infrastructure/health.py`
- **Descripción**: Solo existen:
  - `GET /health` — básico (ok/fail, versión, contadores)
  - `GET /health/detailed` — requiere API key
  
  Faltan:
  - `GET /health/live` — liveness probe (Kubernetes lo necesita para decidir si reiniciar el pod)
  - `GET /health/ready` — readiness probe (Kubernetes lo necesita para routing de tráfico)
  
  `infrastructure/health.py` tiene `HealthCheckRegistry.liveness()` y `.readiness()` implementados pero nunca montados como rutas.
- **Severidad**: ALTO
- **Fix**: Registrar endpoints `/health/live` y `/health/ready` usando `HealthCheckRegistry`.

### 9.2 MEDIO — /health requiere DB access para liveness
- **Archivo**: `b2b_ai/api/app.py:634-645`
- **Descripción**: El endpoint `/health` hace queries a la DB (`db.schema_version()`, `db.count_invoices()`, `db.list_tenants()`). Si la DB está down, el health check falla — pero un health check de liveness debería responder 200 siempre que el proceso esté vivo.
- **Severidad**: MEDIO
- **Fix**: Separar en `/health/live` (sin DB) y `/health/ready` (con DB check).

---

## 10. Observability

### 10.1 ALTO — Feature routes sin logging
- **Archivo**: `b2b_ai/features/*/routes.py` (todos)
- **Descripción**: Ningún archivo de routes en features tiene llamadas a `logger.info()`, `logger.error()`, o `get_logger()`. Los requests a estos endpoints no generan logs estructurados. Solo `app.py` tiene 6 llamadas a `_structured_log`.
- **Severidad**: ALTO
- **Fix**: Añadir logging estructurado en cada endpoint handler (al menos request/response en nivel INFO, errores en ERROR).

### 10.2 MEDIO — Dos sistemas de logging paralelos
- **Archivo**: `b2b_ai/infrastructure/structured_logging.py` vs `b2b_ai/monitoring/logger.py`
- **Descripción**: Existen dos módulos de logging estructurado:
  - `infrastructure/structured_logging.py` — 500 líneas, JSON logging, request context
  - `monitoring/logger.py` — importado en `app.py` como `get_structured_logger`
  
  `app.py` usa el de `monitoring/`. Los health checks y graceful shutdown usan el de `infrastructure/`. Dos loggers diferentes, potencialmente con formatos diferentes.
- **Severidad**: MEDIO
- **Fix**: Consolidar en un solo logger. Eliminar el duplicado.

### 10.3 BAJO — Metrics por proceso (no global)
- **Archivo**: `b2b_ai/api/metrics.py:86-88`
- **Descripción**: Las métricas (`Metrics()`) son por proceso. En producción con múltiples workers uvicorn, cada worker tiene sus propias métricas. Prometheus scrapea uno al azar. `prom_metrics` de `monitoring/` es el correcto para Prometheus, pero las métricas del API (`metrics.snapshot()`) son inconsistentes.
- **Severidad**: BAJO
- **Fix**: Documentar que `/metrics` es por-worker y `/metrics/prometheus` es el canónico.

---

## 11. API Docs

### 11.1 ALTO — OpenAPI enhancement construido pero no instalado
- **Archivo**: `b2b_ai/api/openapi_docs.py` (393 líneas) vs `b2b_ai/api/app.py`
- **Descripción**: `openapi_docs.py` implementa:
  - Esquemas de error response (`ErrorResponse`, `RateLimitResponse`)
  - Security schemes (`ApiKeyAuth`, `BearerAuth`, `IdempotencyKey`)
  - Examples de respuesta (health, auth_error, CFDI processed, webhook payload)
  - Mexican fiscal domain examples
  
  **No se instala.** `install_openapi_docs(app)` nunca se llama. La documentación `/docs` tiene solo el auto-generated de FastAPI sin examples ni schemas de error.
- **Severidad**: ALTO
- **Fix**: `from b2b_ai.api.openapi_docs import install_openapi_docs; install_openapi_docs(app)`.

---

## 12. Idempotency

### 12.1 ALTO — Middleware de idempotencia construido pero no instalado
- **Archivo**: `b2b_ai/api/idempotency.py` (300 líneas) vs `b2b_ai/api/app.py`
- **Descripción**: Implementa:
  - Header `Idempotency-Key` para endpoints de escritura
  - Cache de respuestas (24h TTL)
  - Detección de conflicto (misma key, body diferente → 422)
  - Backend Redis para distribuido, fallback in-memory
  
  **No se instala.** Los endpoints POST/PUT/DELETE no son idempotentes. Un retry de red puede crear duplicados (facturas, leads, declaraciones).
- **Severidad**: ALTO
- **Fix**: `from b2b_ai.api.idempotency import install_idempotency; install_idempotency(app)`.

---

## Archivos Huérfanos / Duplicados

| Archivo | Problema |
|---------|----------|
| `b2b_ai/api/errors 2.py` | Copia de errors.py (¿merge conflict?) |
| `b2b_ai/features/close_management/scheduler 2.py` | Copia de scheduler.py |
| `b2b_ai/features/close_management/tests/test_close_management 2.py` | Copia de test |
| `b2b_ai/features/ap_ar/tests/test_ap_ar 2.py` | Copia de test |
| `b2b_ai/api/rate_limiter.py` | Enterprise rate limiter, nunca usado |
| `b2b_ai/api/versioning.py` | Versioning middleware, nunca instalado |

**Fix**: Eliminar archivos " 2.py" y consolidar.

---

## Plan de Remediación (Prioridad)

### Fase 0 — Quick Wins (1-2 días)
1. Instalar `install_error_handlers(app)` → trace IDs + structured errors
2. Instalar `install_openapi_docs(app)` → mejor documentación
3. Registrar `/health/live` y `/health/ready`
4. Eliminar archivos " 2.py" duplicados
5. Añadir prefijo `/api/v1/ap-ar` al router de ap_ar

### Fase 1 — Fundamentos (3-5 días)
6. Instalar `install_idempotency(app)` en endpoints de escritura
7. Instalar graceful shutdown handler
8. Reemplazar RateLimiter propio por enterprise `rate_limiter.py`
9. Instalar `install_versioning(app)`
10. Inicializar `Settings.from_env()` y reemplazar `os.environ.get()` en app.py

### Fase 2 — Calidad (1 semana)
11. Migrar `HTTPException` a `EnterpriseError` en features (22 archivos)
12. Añadir logging estructurado a todos los feature routes
13. Consolidar los dos sistemas de logging en uno
14. Estandarizar DI en todos los router builders (todos reciben `db`)
15. Eliminar globals en ap_ar, usar DI

### Fase 3 — Producción (1-2 semanas)
16. Configurar Celery con Redis para background tasks
17. Persistir async jobs en DB
18. Separar service layer de DB direct imports
19. Extraer business logic de app.py handlers a servicios
20. Estandarizar nombres de endpoints (inglés)

---

## Checklist de Infraestructura

| Componente | Construido | Instalado | Estado |
|------------|:----------:|:---------:|--------|
| Structured error handling | ✅ | ❌ | **Dead code** |
| Trace IDs | ✅ | ❌ | **Dead code** |
| Idempotency middleware | ✅ | ❌ | **Dead code** |
| Versioning middleware | ✅ | ❌ | **Dead code** |
| OpenAPI enhancement | ✅ | ❌ | **Dead code** |
| Graceful shutdown | ✅ | ❌ | **Dead code** |
| Enterprise rate limiter | ✅ | ❌ | **Dead code** |
| Pydantic config | ✅ | ❌ | **Dead code** |
| Health check registry | ✅ | ❌ parcial | Solo /health, /health/detailed |
| Security headers | ✅ | ✅ | Funcionando |
| CORS | ✅ | ✅ | Funcionando |
| Auth (API key) | ✅ | ✅ | Funcionando |
| Audit middleware | ✅ | ✅ | Funcionando |
| Request size limit | ✅ | ✅ | Funcionando |
| Prometheus metrics | ✅ | ✅ | Funcionando |
| Alert engine | ✅ | ✅ | Funcionando |
| Circuit breaker | ✅ | ✅ | Usado en integraciones |
| Encryption at rest | ✅ | ✅ | AES-GCM opt-in |
| PII detection | ✅ | ✅ | En pipeline CFDI |
| SSRF protection | ✅ | ✅ | En webhooks |
| CSP nonce-based | ✅ | ✅ | En security_headers |
