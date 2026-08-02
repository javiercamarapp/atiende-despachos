# 🔍 AUDITORÍA EXHAUSTIVA — Likida AI Enterprise

**Fecha:** 2026-08-01
**Alcance:** Todo el codebase (`b2b_ai/`, `migrations/`, `landing/`, `Dockerfile`, `pyproject.toml`)
**Métricas:** ~95K LOC fuente + ~11K test = 106K total · 533 archivos `.py` · 24 módulos feature

---

## RESUMEN EJECUTIVO

| Categoría | Hallazgos | Severidad |
|-----------|-----------|-----------|
| 🔴 Crítico | 5 | Requiere fix antes de deploy |
| 🟠 Alto | 12 | Fix en sprint actual |
| 🟡 Medio | 18 | Backlog próximo |
| 🟢 Bajo | 8 | Mejora continua |
| **Total** | **43** | |

---

## 1. IMPORTS ROTOS

### 🔴 1.1 — `pyproject.toml` no declara dependencias críticas usadas en producción

**Archivo:** `pyproject.toml:12-29`
**Descripción:** El proyecto importa ~20 paquetes de terceros que NO están declarados en `dependencies`. Si se instala solo con `pip install .`, fallará en runtime.

| Paquete importado | Archivos que lo usan | Severidad |
|---|---|---|
| `pydantic` | 74 archivos | 🔴 CRÍTICO |
| `pydantic-settings` | 1 archivo (config.py) | 🔴 CRÍTICO |
| `requests` | 9 archivos | 🟠 ALTO |
| `starlette` | 7 archivos | 🟠 ALTO |
| `scikit-learn` | 6 archivos | 🟠 ALTO |
| `google-api-python-client` | 6 archivos | 🟡 MEDIO |
| `sentry-sdk` | 4 archivos | 🟡 MEDIO |
| `sendgrid` | 3 archivos | 🟡 MEDIO |
| `psutil` | 2 archivos | 🟡 MEDIO |
| `stripe` | 1 archivo | 🟡 MEDIO |
| `openai` | 1 archivo | 🟡 MEDIO |
| `anthropic` | 1 archivo | 🟡 MEDIO |
| `pandas` | 1 archivo | 🟡 MEDIO |
| `numpy` | 1 archivo | 🟡 MEDIO |
| `pymssql` | 5 archivos | 🟡 MEDIO |
| `pyodbc` | 5 archivos | 🟡 MEDIO |
| `rapidfuzz` | 1 archivo | 🟢 BAJO |
| `playwright` | 1 archivo | 🟢 BAJO |
| `boto3` | 1 archivo | 🟢 BAJO |
| `twilio` | 1 archivo | 🟢 BAJO |
| `zeep` | 2 archivos | 🟢 BAJO |
| `celery` | 2 archivos | 🟢 BAJO |

**Fix:** Añadir todas las dependencias a `pyproject.toml → dependencies` o moverlas a `[project.optional-dependencies]` con grupos (`pip install b2b-ai[erp]`, `b2b-ai[ml]`, etc.).

### 🟠 1.2 — Imports de módulos internos inexistentes (posibles módulos fantasma)

**Archivos:** Varios
**Descripción:** Algunos imports internos apuntan a módulos cuya existencia es dudosa (podrían ser relative imports mal resueltos o módulos que viven en otra rama):

- `b2b_ai/integrations/erp/multileg.py` — importa de `engine` (genérico, posiblemente `sqlalchemy` o interno)
- `b2b_ai/integrations/*/` — módulos `diot_generator`, `error_handler`, `sat_submitter`, `xml_generator` como imports de nivel superior sin prefijo `b2b_ai`

**Fix:** Verificar que todos los imports internos usen el prefijo `b2b_ai.` o relative imports (`.`).

---

## 2. TYPE HINTS

### 🟡 2.1 — 703 funciones públicas sin return type hint

**Descripción:** Del análisis AST, 703 funciones públicas (sin prefijo `_`) carecen de anotación de retorno. Esto incluye funciones core como `parse_cfdi()`, `validate_cfdi()`, `classify_expense()`, `reconcile_bank()`, `calculate_payroll()`, etc.

**Módulos más afectados:**
- `b2b_ai/tools/tools.py` — 15 funciones sin tipo de retorno
- `b2b_ai/demo/routes.py` — 37 funciones
- `b2b_ai/cli.py` — 8 funciones
- `b2b_ai/features/*/routes.py` — la mayoría de `build_*_router()`

**Severidad:** 🟡 MEDIO (no rompe nada, pero dificulta mantenimiento y refactoring)

**Fix:** Priorizar type hints en las funciones públicas de `services/`, `db/`, y `features/*/service.py`. Los routers pueden esperar.

---

## 3. ERROR HANDLING

### 🔴 3.1 — 20+ bloques `except: pass` que tragan errores silenciosamente

**Archivos y líneas:**

| Archivo | Línea | Contexto |
|---|---|---|
| `features/dashboard/service.py` | 75, 85, 257, 268, 330, 359, 396 | **7 instancias** — errores de DB silenciados en dashboard |
| `features/reconciliation_agent/routes.py` | 126, 185, 208, 298, 319 | 5 instancias — errores de conciliación tragados |
| `features/close_management/routes.py` | 233 | Error de cierre mensual silenciado |
| `features/bookkeeping/routes.py` | 104 | Error de registro contable |
| `features/alertas/engine.py` | 202 | Error de motor de alertas |
| `features/declaraciones/service.py` | 392 | Error de declaración fiscal |
| `features/reportes/serializers.py` | 179 | Error de serialización |
| `portal/routes.py` | 514 | Error de portal |
| `auth/users.py` | 159 | Error de autenticación |
| `auth/middleware.py` | 268, 278 | Error de middleware de auth |
| `demo/routes.py` | 133, 137 | Errores de demo |

**Severidad:** 🔴 CRÍTICO (en features de producción: dashboard, conciliación, declaraciones)

**Fix:** Reemplazar `except: pass` con:
```python
except SomeSpecificError as exc:
    logger.warning("contexto", extra={"error": str(exc)})
    # o raise HTTPException(500, detail="...")
```

### 🟠 3.2 — ~50 `except Exception` con `# noqa: BLE001` (catch-all)

**Archivos:** `app.py`, `reports/pdf_generator.py`, `infrastructure/db_pool.py`, `infrastructure/retry.py`, `billing/`, `api/webhooks.py`
**Descripción:** Aunque algunos tienen noqa justificado (e.g., "las métricas no deben romper el request"), hay 50+ catch-alls que pueden ocultar bugs.
**Severidad:** 🟠 ALTO
**Fix:** Auditar caso por caso. Los de `db_pool.py` (8 instancias) son los más críticos.

---

## 4. LOGGING

### 🔴 4.1 — PII (RFC) expuesto en logs de integraciones SAT

**Archivos:**
- `b2b_ai/integrations/sat/finkok.py:65` — `logger.info(f"timbrando CFDI de {cfdi_data.rfc_emisor} a {cfdi_data.rfc_receptor}")`
- `b2b_ai/integrations/sat/finkok.py:143` — `logger.info(f"consultando RFC {rfc}")`
- `b2b_ai/integrations/sat/ecodex.py:65,152` — Mismo patrón
- `b2b_ai/integrations/sat/sat_portal.py:119` — `logger.info(f"consultando situación fiscal RFC {rfc}")`
- `b2b_ai/integrations/sat/pacs/*.py:112` — 4 PACs loggeando RFC

**Descripción:** El RFC (Registro Federal de Contribuyentes) es PII bajo la LFPDPPP mexicana. Se loggea en texto plano a pesar de que `b2b_ai/infrastructure/structured_logging.py` tiene masking de PII — pero estos adapters usan `logging.getLogger()` directo, NO el structured logger.

**Severidad:** 🔴 CRÍTICO (violación LFPDPPP en producción)

**Fix:** Usar `mask_pii()` del structured logger, o reemplazar con:
```python
logger.info(f"timbrando CFDI de {mask(rfc_emisor)} a {mask(rfc_receptor)}")
```

### 🟡 4.2 — Structured logging infraestructura presente pero no usada uniformemente

**Descripción:** `b2b_ai/infrastructure/structured_logging.py` tiene masking completo de PII (RFC, CURP, NSS, salario, cuentas bancarias), pero solo `app.py` usa `_structured_log`. Los módulos de integración usan `logging.getLogger()` directo, saltándose el masking.
**Severidad:** 🟡 MEDIO
**Fix:** Migrar todos los módulos a usar el structured logger.

---

## 5. TESTS

### 🟠 5.1 — Cobertura de tests: solo 10% del código

**Métricas:**
- Líneas fuente: 95,353
- Líneas de test: 11,208
- Ratio: **10.5%** (industria target: 60-80%)

### 🟠 5.2 — Feature sin tests: `multi_tenant`

**Archivo:** `b2b_ai/features/multi_tenant/`
**Descripción:** Es el único de 24 features que NO tiene directorio de tests. Es crítico porque maneja aislamiento de datos entre tenants.
**Severidad:** 🟠 ALTO

### 🟡 5.3 — Archivos de test duplicados con espacio en nombre

| Archivo | Problema |
|---|---|
| `tests/test_close_management 2.py` | Duplicado con espacio |
| `tests/test_ap_ar 2.py` | Duplicado con espacio |

**Severidad:** 🟡 MEDIO (pytest no los ejecuta por el espacio en el nombre)
**Fix:** Eliminar o renombrar sin espacio.

### 🟡 5.4 — Módulos sin tests unitarios

Módulos del core (`b2b_ai/` raíz) sin test dedicado:
- `b2b_ai/agent/loop.py`
- `b2b_ai/erp/contpaqi.py`, `quickbooks.py`, `erp_automation.py`
- `b2b_ai/services/llm.py` (61 archivos lo importan)
- `b2b_ai/services/bank_reconciliation.py`
- `b2b_ai/integrations/` — todos los adapters (ERP, pagos, SAT)
- `b2b_ai/notifications/` — scheduler, email, whatsapp
- `b2b_ai/collections/`

---

## 6. DB MIGRATIONS (ALEMBIC)

### 🟠 6.1 — Conflicto de numeración: dos migraciones `0005`

**Archivos:**
- `migrations/versions/0005_outstanding_unique.py` — `down_revision = "0004_audit_feature_flags"`
- `migrations/versions/0005_bank_reconciliation_state.py` — `down_revision = "0005_outstanding_unique"`

**Descripción:** Aunque técnicamente forman una cadena (`0004 → 0005_outstanding_unique → 0005_bank_reconciliation_state`), la numeración es confusa. `0005_bank_reconciliation_state` DEBERÍA ser `0006` o `0005b`.
**Severidad:** 🟠 ALTO (puede causar confusiones al hacer rollback)

**Fix:** Renombrar a `0006_bank_reconciliation_state` y actualizar el `revision` y `down_revision` internos.

### 🟡 6.2 — Dual-track de migraciones: Alembic vs `models.MIGRATIONS`

**Descripción:** El proyecto tiene DOS sistemas de migración:
1. **Alembic** (`migrations/`) — para PostgreSQL en producción
2. **`b2b_ai/db/models.py` MIGRATIONS** — SQLite en dev/test (737 líneas de SQL inline)

El `env.py` de Alembic rechaza SQLite explícitamente (línea 24). Esto significa que el esquema SQLite y el PostgreSQL pueden divergir silenciosamente.

**Severidad:** 🟡 MEDIO
**Fix:** Documentar claramente que Alembic es la fuente de verdad para producción, y que `models.MIGRATIONS` es legacy/dev-only. Considerar unificar.

### 🟢 6.3 — Migración `0003_seed.py` en Alembic

**Descripción:** Seeds de datos en migraciones es antipatrón — si los datos cambian, hay que crear otra migración.
**Severidad:** 🟢 BAJO

---

## 7. DEPENDENCIES

### 🔴 7.1 — `pydantic` no declarado (ver §1.1)

74 archivos dependen de pydantic. Sin ella, la app no arranca.

### 🟠 7.2 — Dependencias de integración opcionales sin grupo separado

`pymssql`, `pyodbc`, `boto3`, `twilio`, `playwright`, `pandas`, `numpy`, `sklearn`, `stripe`, `openai`, `anthropic` — ninguna está en `pyproject.toml`.

**Fix:**
```toml
[project.optional-dependencies]
erp = ["pymssql", "pyodbc"]
ml = ["scikit-learn", "pandas", "numpy"]
payments = ["stripe"]
integrations = ["boto3", "twilio", "sendgrid", "playwright", "zeep"]
llm = ["openai", "anthropic"]
sentry = ["sentry-sdk"]
```

### 🟡 7.3 — `psycopg_pool` declarado como `psycopg-pool` pero importado como `psycopg_pool`

**Archivo:** `b2b_ai/db/pg.py`, `b2b_ai/infrastructure/db_pool.py` (3 archivos)
**Descripción:** Nombre correcto en pip pero no verificado que `psycopg[binary]` incluya el pool.
**Severidad:** 🟡 MEDIO

---

## 8. CONFIG VALIDATION

### 🟢 8.1 — Buena estructura de validación con Pydantic

**Archivo:** `b2b_ai/infrastructure/config.py`
**Descripción:** Configuración bien estructurada con:
- `Settings.from_env()` con fail-fast
- Validación de JWT_SECRET ≥ 16 chars en producción
- Validación de ENCRYPTION_KEY ≥ 16 chars en producción
- `validate_production_ready()` que lista warnings
- Masking de secretos en `__repr__`

### 🟡 8.2 — `B2B_API_KEY` no se valida como obligatorio en producción

**Archivo:** `b2b_ai/infrastructure/config.py:106`
**Descripción:** `api_key` es `Optional[str] = None`. En producción, sin API key, cualquiera puede llamar a los endpoints protegidos (el auth degrada a "standalone mode").
**Severidad:** 🟡 MEDIO

### 🟡 8.3 — `create_app()` fuerza validación pero no usa `Settings`

**Archivo:** `b2b_ai/api/app.py:453`
**Descripción:** `check_jwt_config()` y la verificación de `B2B_ENCRYPTION_KEY` están duplicadas entre `create_app()` y `Settings.validate_production_ready()`. La app NO usa `Settings.from_env()` — lee env vars directamente en cada módulo.
**Severidad:** 🟡 MEDIO

---

## 9. DEAD CODE

### 🟠 9.1 — 6 archivos de backup/duplicado con espacio en el nombre

| Archivo | Probablemente duplicado de |
|---|---|
| `features/close_management/scheduler 2.py` | `scheduler.py` |
| `features/close_management/tests/test_close_management 2.py` | `test_close_management.py` |
| `features/ap_ar/tests/test_ap_ar 2.py` | `test_ap_ar.py` |
| `cfdi/xml_security 2.py` | `xml_security.py` |
| `db/migration 2.py` | `migration.py` |
| `api/errors 2.py` | `errors.py` |

**Severidad:** 🟠 ALTO (confunde herramientas, ocupa espacio, puede causar imports accidentales)
**Fix:** Eliminar todos los `* 2.py`.

### 🟡 9.2 — Landing page duplicada: `landing/` y `landing-b/`

**Descripción:** Dos directorios de landing page con contenido similar. `landing-b/` tiene `netlify.toml` (probablemente deploy separado). Dockerfile solo copia `landing/`.
**Severidad:** 🟡 MEDIO
**Fix:** Consolidar en un solo directorio o documentar la separación.

### 🟡 9.3 — 80+ marcadores TODO/FIXME/XXX sin resolver

**Archivos más afectados:**
- `demo/mock_data.py` — 15 TODOs
- `integrations/hub.py` — 5 TODOs
- `integrations/*/adapter.py` — ~10 TODOs
- `features/email_processing/service.py` — 3 TODOs

**Severidad:** 🟡 MEDIO

---

## 10. PERFORMANCE

### 🟠 10.1 — 11 potenciales N+1 queries

| Archivo | Línea | Descripción |
|---|---|---|
| `db/db.py` | 560, 662 | DB calls inside loop |
| `db/pg.py` | 183 | `self.execute(stmt)` en loop |
| `db/migration.py` | 225 | `SELECT *` por tabla en loop |
| `db/migration 2.py` | 228 | Idem (duplicado) |
| `features/flags.py` | 167 | DB call en loop de flags |
| `integrations/erp/*.py` | ~191 (5 archivos) | INSERT en loop para movimientos contables |

**Severidad:** 🟠 ALTO (los de `db.py` están en hot path)
**Fix:** Usar `executemany()` o batch inserts para los ERPs. Para `db.py`, verificar que el loop no se ejecuta en cada request.

### 🟡 10.2 — Índices faltantes en 3 tablas con `tenant_id`

| Tabla | Tiene `tenant_id` | Tiene índice en `tenant_id` |
|---|---|---|
| `classifications` | ✅ | ❌ |
| `notifications` | ✅ | ❌ |
| `portal_sessions` | ✅ | ❌ |

**Severidad:** 🟡 MEDIO (afecta queries de multi-tenant)
**Fix:** Crear índices:
```sql
CREATE INDEX IF NOT EXISTS idx_classifications_tenant ON classifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notifications_tenant ON notifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_portal_sessions_tenant ON portal_sessions(tenant_id);
```

### 🟡 10.3 — `_StatsCache` no tiene límite de tamaño

**Archivo:** `b2b_ai/api/app.py:139-167`
**Descripción:** El cache en memoria `_StatsCache._store` crece indefinidamente. Las entradas se limpian por TTL al leer, pero si se generan muchas keys únicas, puede consumir memoria.
**Severidad:** 🟡 MEDIO
**Fix:** Añadir `max_size` con LRU eviction.

---

## 11. DOCKER

### 🟢 11.1 — Dockerfile bien estructurado (multi-stage)

**Archivo:** `Dockerfile`
- ✅ Multi-stage build (builder → runtime)
- ✅ No corre como root (user `b2b`)
- ✅ Healthcheck con curl a `/health`
- ✅ `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`
- ✅ Puerto configurable via `$PORT` (Railway compatible)

### 🟡 11.2 — Healthcheck endpoint requiere DB connection

**Archivo:** `b2b_ai/api/app.py:633`
**Descripción:** El `/health` check falla si la DB no está disponible. En un contenedor con startup lento (migraciones), el healthcheck puede fallar durante `start_period`.
**Severidad:** 🟡 MEDIO
**Fix:** Añadir un `/healthz` (liveness) que solo retorna 200 sin DB, y mantener `/health` como readiness.

### 🟢 11.3 — `docker-compose.yml` correcto

- ✅ PostgreSQL 16 con healthcheck
- ✅ Redis 7 con AOF persistence
- ✅ Nginx reverse proxy
- ✅ Red interna bridge (no expuesta al host)
- ✅ `POSTGRES_PASSWORD` obligatorio via `${VAR:?error}`

---

## 12. RAILWAY

### 🟢 12.1 — `railway.toml` correcto

- ✅ Builder: DOCKERFILE
- ✅ Healthcheck: `/health` con timeout 30s
- ✅ Restart policy: ON_FAILURE, max 5 retries
- ✅ Puerto dinámico via `$PORT`

### 🟡 12.2 — Variables de entorno no documentadas

**Descripción:** No hay `.env.example` ni documentación de las ~30 env vars requeridas. Las más críticas:

| Variable | Requerida en prod | Documentada |
|---|---|---|
| `B2B_API_KEY` | ✅ | Solo en docstring |
| `B2B_JWT_SECRET` | ✅ | Solo en config.py |
| `B2B_ENCRYPTION_KEY` | ✅ | Solo en config.py |
| `B2B_DATABASE_URL` | ✅ | Solo en config.py |
| `B2B_REDIS_URL` | ⚠️ | Solo en config.py |
| `B2B_LLM_API_KEY` | ⚠️ | Solo en config.py |
| `B2B_ENV` | ✅ | Solo en config.py |

**Severidad:** 🟡 MEDIO
**Fix:** Crear `.env.example` con todas las variables y descripciones.

### 🟡 12.3 — SQLite como default en producción

**Archivo:** `b2b_ai/infrastructure/config.py:284` / `b2b_ai/db/db.py:18-22`
**Descripción:** Sin `B2B_DATABASE_URL`, la app usa SQLite local. En Railway con múltiples replicas, cada una tendría su propia DB.
**Severidad:** 🟡 MEDIO (debería fallar closed en producción, no degradar a SQLite)

---

## 13. API DOCS

### 🟢 13.1 — OpenAPI auto-generada por FastAPI

**Descripción:** FastAPI genera `/docs` (Swagger UI) y `/openapi.json` automáticamente. El archivo `b2b_ai/api/openapi_docs.py` parece personalizar la spec.
**Severidad:** 🟢 OK

### 🟡 13.2 — Endpoints sin documentación de ejemplos

**Descripción:** Muchos endpoints no tienen `examples` en sus schemas Pydantic, lo que hace que la spec OpenAPI sea menos útil para integradores.
**Severidad:** 🟡 MEDIO

---

## 14. LANDING PAGE

### 🔴 14.1 — Formulario NO envía leads al API

**Archivo:** `landing/index.html:831-837`
**Descripción:**
```javascript
function handleSubmit(e) {
  e.preventDefault();
  const data = new FormData(e.target);
  const name = data.get('name');
  alert('¡Gracias ' + name + '! Nos pondremos en contacto contigo pronto.');
  e.target.reset();
}
```
El formulario muestra un `alert()` y **no hace ninguna llamada al API**. El endpoint `POST /api/v1/leads` existe en el backend pero nunca se llama desde la landing.

**Severidad:** 🔴 CRÍTICO (leads se pierden — nadie recibe los datos)

**Fix:**
```javascript
async function handleSubmit(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const res = await fetch('/api/v1/leads', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    if (res.ok) {
      alert('¡Gracias ' + data.name + '! Nos pondremos en contacto.');
      e.target.reset();
    } else {
      alert('Error al enviar. Intenta de nuevo.');
    }
  } catch (err) {
    alert('Error de conexión. Intenta de nuevo.');
  }
}
```

### 🟢 14.2 — CSS carga correctamente (inline)

**Descripción:** Todo el CSS está inline en `<style>` dentro del HTML. No depende de archivos externos de estilo.
**Severidad:** 🟢 OK

### 🟢 14.3 — Landing montada en el API

**Archivo:** `b2b_ai/api/app.py:189` — `LANDING_DIR` resuelto y montado como `StaticFiles`.
**Severidad:** 🟢 OK

---

## 15. SEGURIDAD

### 🟡 15.1 — `subprocess.run()` en health check (macOS-specific)

**Archivo:** `b2b_ai/monitoring/health.py:121-122`
**Descripción:**
```python
import subprocess
out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True)
```
`sysctl` es macOS-only. En Linux (producción), esto falla silenciosamente.
**Severidad:** 🟡 MEDIO
**Fix:** Usar `/proc/meminfo` en Linux, `sysctl` en macOS, con fallback.

### 🟡 15.2 — `alembic.ini` tiene URL de PostgreSQL hardcodeada

**Archivo:** `alembic.ini:87`
```
sqlalchemy.url = postgresql://postgres:***@localhost:5432/b2b_ai
```
Aunque `env.py` la sobreescribe con env vars, tener credenciales en el archivo es antipatrón.
**Severidad:** 🟡 MEDIO

---

## 16. CODE QUALITY

### 🟠 16.1 — Funciones gigantes (God Functions)

| Función | Archivo | Líneas |
|---|---|---|
| `create_app()` | `api/app.py:439` | **1,139 líneas** |
| `build_conciliacion_router()` | `features/conciliacion/routes.py:134` | 578 |
| `mount_demo_routes()` | `demo/routes.py:61` | 483 |
| `generate_roi_report()` | `demo/report_pdf.py:247` | 464 |
| `build_v2_router()` | `api/v2.py:182` | 460 |

**Severidad:** 🟠 ALTO (especialmente `create_app()` a 1,139 líneas)
**Fix:** Dividir `create_app()` en funciones de setup (routers, middleware, lifespan). Cada router builder ya es modular pero el registro central no.

### 🟡 16.2 — Duplicación de lógica entre `db/migration.py` y `db/migration 2.py`

**Severidad:** 🟡 MEDIO (archivo duplicado, ver §9.1)

---

## PLAN DE ACCIÓN PRIORITIZADO

### Inmediato (antes de deploy a prod):
1. ✅ Añadir `pydantic`, `pydantic-settings`, `requests`, `starlette` a `pyproject.toml`
2. ✅ Fix landing page: conectar formulario a `POST /api/v1/leads`
3. ✅ Eliminar 6 archivos `* 2.py` duplicados
4. ✅ Fix PII logging en integraciones SAT (RFC → masked)

### Sprint actual:
5. Añadir todas las dependencias faltantes a `pyproject.toml` (con optional groups)
6. Reemplazar los 20+ `except: pass` con logging mínimo
7. Añadir tests para `multi_tenant` feature
8. Crear índices en `classifications`, `notifications`, `portal_sessions`
9. Renombrar migración `0005_bank_reconciliation_state` → `0006_*`

### Próximo sprint:
10. Reducir `create_app()` de 1,139 a <200 líneas
11. Crear `.env.example` con todas las variables
12. Migrar integraciones a structured logger
13. Añadir `/healthz` (liveness) separado de `/health` (readiness)
14. Tests para `services/llm.py`, `services/bank_reconciliation.py`, `notifications/`

---

*Auditoría generada automáticamente por Hermes Agent · 2026-08-01*
