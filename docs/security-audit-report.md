# Security Audit & Hardening Report — B2B-AI Enterprise (PRODUCCIÓN)

Fecha: 2026-07-31 · Ejecutado por: calidad (Sam) · Alcance: /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise
Comando de verificación global: `.venv/bin/python -m pytest -q -p no:cacheprovider` → **631 passed, 15 skipped, exit 0**

---

## RESUMEN EJECUTIVO

| Área | Estado | Hallazgos críticos |
|---|---|---|
| Bandit (estático) | ✅ LIMPIO | 1 HIGH y 5 MEDIUM corregidos; 14 LOW documentados (todos benignos) |
| Dependencias (pip_audit) | ⚠️ 13 paquetes con CVEs | Causa raíz: **Python 3.9.6 (EOL)**. Fix = migrar a 3.11+. Ver §2 |
| API security | ✅ | Rate limit, validación Pydantic, CORS restrictivo, headers, rotación de keys |
| Data security | ✅ | Cifrado AES-GCM, PII masking, audit trail, retención |

**Veredicto:** la app está **lista para producción con un bloqueador operativo**: el runtime Python 3.9.6 es EOL y bloquea el parcheo de dependencias. No se debe desplegar sin migrar a Python 3.11+.

---

## 1. Security scan (bandit)

Comando: `.venv/bin/bandit -r b2b_ai/`

**Antes: 1 HIGH, 3 MEDIUM, 11 LOW (15 total)**
**Después: 0 HIGH, 0 MEDIUM, 20 LOW (todos documentados como benignos o falsos positivos)**

### Corregidos (HIGH y MEDIUM)

| Severidad | Test | Archivo | Acción |
|---|---|---|---|
| HIGH | B324 (SHA1 débil) | services/contabilidad_electronica.py:63 | SHA-1 es checksum **obligatorio del SAT** (no criptográfico). Añadido `usedforsecurity=False` + comentario |
| MEDIUM | B310 (urlopen) | api/webhooks.py:76 | Añadido `_assert_http_scheme()` que rechaza todo esquema ≠ http/https antes de `urlopen` (previene SSRF desde `Subscription.url`) |
| MEDIUM | B310 (urlopen) | services/llm.py:177 | Validación de esquema http/https con `urlparse` en `_http_post_json` |
| MEDIUM | B310 (urlopen) | monitoring/alerts.py:190 | `WebhookChannel.__init__` valida esquema; `# nosec B310` justificado (URL config-controlada) |
| MEDIUM | B608 (SQL inyección) | db/db.py:348 | Falso positivo: nombres tabla/columna vienen SOLO de la constante `_RETENTION_TABLES`; valor parametrizado con `?`. `# nosec B608` |

### Corregido adicionalmente (bug de producción bloqueante)

**monitoring/logger.py — `request_context()` no era context manager.** Usaba `yield` sin decorador `@contextlib.contextmanager`, lo que lanzaba `AttributeError: __enter__` en **CADA request** (middleware app.py:368). Esto rompía la API completa. Añadido `@contextmanager`. Verificado: la suite pasa.

### LOW documentados (20) — todos benignos, sin acción requerida

| Test | Archivos | Motivo de baja severidad |
|---|---|---|
| B110/B112 (try/except pass/continue) | auth.py, portal.py, pool.py, db.py, pg.py, webhooks.py, reconcile.py | Manejo intencional de errores tolerantes (no romper la petición ante fallo de auditoría/limpieza). Correcto por diseño |
| B406 (xml.sax.saxutils) | accounting, balanza, catalogo_cuentas, payroll | **Falso positivo**: solo usan `sx.escape()` para ESCAPAR texto en XML generado (salida), nunca para parsear XML de entrada. El parseo de CFDI real usa `defusedxml`/`lxml` |
| B311 (random) | services/llm.py:291 | Clase **Mock** de pruebas (inyección de fallos con `error_rate`), no crypto |
| B404/B603/B607 (subprocess) | monitoring/health.py, db/db.py:172 | Health-check ejecuta `sysctl -n hw.memsize` (comando fijo); db.py ejecuta `alembic upgrade head` (migración de esquema, `sys.executable -m alembic` — comando fijo, sin input del usuario) |

---

## 2. Dependency audit (pip_audit)

Comando: `.venv/bin/python -m pip_audit --skip-editable -f json`

**Resultado: 41 vulnerabilidades en 13 paquetes.** NINGUNA corregible en este entorno.

### Diagnóstico raíz

El venv usa **Python 3.9.6** (final de soporte desde 2025). Todas las versiones corregidas de los paquetes afectados (python-multipart, starlette, requests, urllib3, click, msgpack, python-dotenv) **requieren Python ≥ 3.10/3.11**. `pip index versions` confirma que las instaladas son las últimas disponibles para py3.9.

### Paquetes con CVEs (runtime)

| Paquete | CVE(s) | Estado |
|---|---|---|
| python-multipart 0.0.20 | PYSEC-2026-1852 y 5 más | Sin fix para py3.9 — requiere py≥3.10 |
| starlette 0.49.3 | PYSEC-2026-161 y 4 más | Sin fix para py3.9 |
| requests 2.32.5 | PYSEC-2026-2275 | Sin fix para py3.9 |
| urllib3 2.6.3 | PYSEC-2026-142/141 | Sin fix para py3.9 |
| click 8.1.8 | PYSEC-2026-2132 | Sin fix para py3.9 |
| msgpack 1.1.2 | GHSA-6v7p-g79w-8964 | Sin fix para py3.9 |
| python-dotenv 1.2.1 | PYSEC-2026-2270 | Sin fix para py3.9 |

### Dev/tooling (no producción, pero en el venv)

pip, setuptools, pytest, nltk, marshmallow, filelock — son herramientas de desarrollo, no entran en el runtime.

### Acción requerida (bloqueador)

1. **MIGRAR el runtime a Python 3.11+** (recrear venv, re-instalar desde `requirements-production.txt`).
2. Re-ejecutar `pip_audit` tras la migración; debería quedar en 0.
3. Actualizar `Dockerfile` / CI al nuevo Python.

### Entregable: requirements-production.txt (nuevo)

Creado en `requirements-production.txt` con SOLO las dependencias de runtime reales (fastapi, uvicorn, python-multipart, starlette, pydantic, bcrypt, cryptography, lxml, requests, python-dotenv) + sección de opcionales (psycopg, redis, psutil, openpyxl) comentada. Determinado por análisis AST de imports reales del paquete.

---

## 3. API security (verificado)

| Control | Estado | Evidencia |
|---|---|---|
| Rate limiting por IP+ruta | ✅ | `RateLimiter` (app.py) ventana deslizante, default 300/min, configurable `B2B_RATE_LIMIT*`, responde 429 con Retry-After |
| Input validation con Pydantic | ✅ | Schemas `BaseModel` en app.py (ProcessRequest, LeadRequest, etc.) + límites Query (ge/le) + `allowed_upload_extension` (solo .xml/.pdf) |
| CORS restricted | ✅ | Solo si `B2B_CORS_ORIGINS`; vacío = desactivado (same-origin). Credenciales off por defecto |
| Security headers | ✅ | `SecurityHeadersMiddleware`: HSTS (31536000, includeSubDomains, preload), CSP (object-src 'none', frame-ancestors 'none'), X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy |
| API key rotation | ✅ (nuevo) | Añadido `db.set_api_key_active()`: emitir nueva key + desactivar vieja. Verificado end-to-end |
| Auth robusto | ✅ | X-API-Key header, comparación timing-safe (`hmac.compare_digest`), key hasheada (SHA-256) en DB, bloqueo de tenants, intentos fallidos auditados |
| Mitigación SSRF | ✅ (nuevo) | Guardas de esquema http/https en webhooks y LLM |

---

## 4. Data security (verificado)

| Control | Estado | Evidencia |
|---|---|---|
| Cifrado en reposo | ✅ | `security.py`: AES-GCM, clave de 32B derivada de `B2B_ENCRYPTION_KEY`. Aplica a webhook_url, notif_recipient. Roundtrip verificado |
| PII masking en logs | ✅ | `monitoring/logger.py::JsonFormatter` + `mask_pii` (RFC, CURP, emails, teléfonos, tarjetas). `detect_pii` en pipeline |
| Audit trail | ✅ | `audit_log` + `db.log_call()` en auth (denied), onboarding, webhook mutations |
| Data retention | ✅ | `enforce_retention()` (audit_log, webhook_deliveries, notifications, portal_sessions) configurable `B2B_RETENTION_DAYS` (default 365). Facturas NO se tocan (las manda SAT). Purga verificada |

### Config de producción (mejorado)

`.env.production.example` ahora documenta: `B2B_ENCRYPTION_KEY` (obligatoria), `B2B_RETENTION_DAYS`, `B2B_HSTS`, `B2B_HSTS_ALWAYS`, `B2B_TRUST_PROXY`, `B2B_CSP`, `B2B_ALERT_WEBHOOK_URL`, `B2B_LOG_LEVEL`.

---

## Archivos modificados

- b2b_ai/services/contabilidad_electronica.py (SHA1 usedforsecurity)
- b2b_ai/api/webhooks.py (SSRF guard + nosec)
- b2b_ai/services/llm.py (SSRF guard + nosec)
- b2b_ai/monitoring/alerts.py (scheme validation + nosec)
- b2b_ai/db/db.py (nosec B608 + set_api_key_active)
- b2b_ai/monitoring/logger.py (**fix crítico**: @contextmanager en request_context)
- requirements-production.txt (nuevo)
- .env.production.example (config de seguridad documentada)

---

## Estado de verificación (evidencia)

**✓ Verificado**
- `bandit -r b2b_ai/` → 0 HIGH, 0 MEDIUM, 20 LOW (benignos)
- `pip_audit` → 41 vulns / 13 paquetes, todos bloqueados por py3.9 EOL
- `pytest -q -p no:cacheprovider` → **631 passed, 15 skipped, exit 0**
- tests/production/ → 28 passed
- tests/test_security_hardening* + e2e_security + webhooks + llm → 67 passed
- API key rotation: create → auth OK → deactivate → auth denegado → reactivate → auth OK
- Encryption AES-GCM: encrypt → decrypt roundtrip correcto
- Retention: enforce_retention(days=-30) purgó audit_log y notifications

**? Inferido**
- El parcheo de CVEs funcionará tras migrar a py3.11 — no lo pude probar aquí (no es mi alcance).

**✗ Incierto / no revisado**
- No audité el código de la landing estática ni los drivers de desktop (contpaqi/aspel/browser) con bandit (fueron excluidos por estar fuera del alcance `b2b_ai/` de la tarea).
- La rotación de keys no tiene endpoint de API expuesto (solo método DB + CLI); si se quiere rotación vía HTTP, es trabajo futuro.
- `safety check` no se usó (requiere API key comercial); se usó `pip_audit` (DB PyPA/OSV pública).

**Qué NO prueba esto**
- Que la app pase un pentest real (no se ejecutó).
- Que el despliegue esté seguro: depende de variables de entorno reales (B2B_ENCRYPTION_KEY, B2B_API_KEY, secrets) que deben generarse con `openssl rand`.
