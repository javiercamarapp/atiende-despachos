# QA_REPORT_FINAL — Likida AI Enterprise Enterprise MVP + Landing

**Fecha:** 2026-07-31 · **QA:** Leonardo (Ingeniería de Calidad)
**Alcance:** Suite completa, API v1/v2, Portal de cliente, CLI, Landing, Seguridad
**Directorio:** `/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise`
**Modo:** Solo reporte (sin fixes), verificación con evidencia real.

---

## 1. RESUMEN EJECUTIVO

**Veredicto: REQUIERE FIXES ANTES DE DEPLOY** (1 bloqueante en landing; el backend
core está sano).

| Área | Estado | Bloqueante |
|---|---|---|
| Suite de tests | ✅ 422/422 pasan | No |
| API v1 (upload, list, stats) | ✅ Funciona | No |
| Portal de cliente (login + upload) | ✅ Funciona | No |
| CLI (process/batch/report/status) | ✅ Funciona | No |
| Landing — estructura/responsive | ✅ OK | No |
| Landing — assets de hero | ❌ **3 recursos 404** | **SÍ** |
| Seguridad | ✅ Auth + rate-limit + no secrets servidos | No |
| Performance | ⚠️ Video hero 5.5MB sin compresión | No (recomendado) |

---

## 2. SUITE DE TESTS

**Comando:** `python -m pytest -v` (y `python -m pytest` para el total)

```
======================= 422 passed, 1 warning in 12.63s ========================
```

- **Total:** 422 · **Passed:** 422 · **Failed:** 0 · **Skipped:** 0
- **Umbral objetivo (422+):** ✅ superado exactamente.
- 1 warning: `DeprecationWarning` de starlette/TestClient sobre cookies — no afecta.

**Cobertura verificada:** CFDI parse/validate/classify, router, tools, tenants
(aislamiento multi-tenant), reports, webhooks con retry, security-hardening
(XSS, auth bypass, secrets scan), portal, contabilidad, payroll, collections.

---

## 3. API — PRUEBAS MANUALES (curl, contra `http://127.0.0.1:8000`)

Servidor uvicorn local levantado; auth por header `X-API-Key`.

| Endpoint / caso | Método | Resultado |
|---|---|---|
| `/health` | GET | 200 |
| `POST /api/v1/invoices/process` (sin key) | POST | 401 ✅ |
| `POST .../process` con `xml_file` CFDI válido | POST | 200 — `valido:true`, clasificado `gasto_operativo`/`inversion`, póliza ERP `POL-*` generada, `total` correcto ✅ |
| `POST .../process` con archivo NO XML | POST | 422 — `CFDI inválido: XML mal formado` ✅ |
| `GET /api/v1/invoices` | GET | 200 — `count:3` (scope demo) ✅ |
| `GET /api/v1/stats` | GET | 200 — total_facturas 237, monto 331,606.66 ✅ |
| `GET /api/v1/dashboard/summary` | GET | 200 — 237 válidas, 0 inválidas ✅ |

**Portal de cliente (FASE 5):**

| Caso | Resultado |
|---|---|
| `POST /portal/auth/login` credenciales inválidas | 401 `Credenciales inválidas.` ✅ |
| `POST /portal/auth/login` correctas | 200 — token opaco (43 chars) + tenant_id + expires ✅ |
| `GET /portal/auth/me` con Bearer | 200 — usuario demo ligado a tenant ✅ |
| `POST /portal/invoices/upload` (async job) | 200 — `job_id` devuelto ✅ |
| `GET /portal/invoices/{job}/status` (polling) | `status:"done"`, invoice_id, resultado pipeline ✅ |
| `GET /portal/invoices` | 200 — filtrado por tenant ✅ |
| `GET /portal/dashboard/stats` | 200 ✅ |
| Token inválido en `/portal/invoices` | 401 ✅ |

> Nota: para probar el login completo se reseteó la contraseña del usuario demo
> local (`demo@cliente.mx`) a un valor conocido (`qa-test-1234`). No es cambio de
> código; solo dato de la DB dev local. En deploy real el seed debe documentar la
> credencial por defecto.

**Observación (no bloqueante, revisar con negocio):** el dashboard portal reporta
`"anomalias":237` igual al total de facturas. Es consistente con los datos de
demo (mismas 237), pero conviene confirmar que el detector no esté marcando todo
por defecto. Marcado como **? INFERIDO** — requiere revisión del umbral del
servicio `anomaly.detect_anomalies`.

---

## 4. CLI — PRUEBAS MANUALES

| Comando | Resultado |
|---|---|
| `python -m b2b_ai.cli --help` | OK — lista process/batch/report/status ✅ |
| `python -m b2b_ai.cli status` | 200 — versión 1.0.0, esquema 7, 2 tenants, 237 facturas ✅ |
| `python -m b2b_ai.cli process fixtures/cfdis/04_nomina_pago.xml` | OK — validación 12/12, NOMINA conf 0.98, póliza ERP ✅ |
| `python -m b2b_ai.cli batch fixtures/cfdis` | OK — 7 procesadas, 7 válidas, 0 observaciones ✅ |
| `python -m b2b_ai.cli report` | OK — 237 facturas, totales por categoría, "presentación fiscal requiere humano" ✅ |

---

## 5. LANDING PAGE

**Servida desde el mismo origen FastAPI** (`landing/index.html` en `/`). Verificada
con Playwright (Chromium headless) en 3 viewports.

### 5.1 Bugs encontrados (BLOQUEANTE)

**BUG-1 — CRÍTICO / Bloqueante: 3 assets del hero resuelven a 404 en producción.**

La landing referencia rutas relativas `assets/...` que resuelven a `/assets/*`,
pero la app **solo monta estáticos en `/static`** (`app.mount("/static", StaticFiles(directory=LANDING_DIR))` en `app.py:872`). Nginx reenvía todo a FastAPI (sin mapeo propio), así que en prod el fallo se reproduce igual.

Evidencia (Playwright, los 3 viewports + curl):

```
GET /assets/hero.jpg               → 404
GET /assets/hero-ai-dashboard.mp4  → 404 (x2, dos <source>)
GET /assets/logo-likida.jpg        → 404
GET /static/assets/hero.jpg        → 200   ← el mismo archivo sí sirve bajo /static
```

Archivos referenciados en `landing/index.html`:
- L301: `<img src="assets/logo-likida.jpg">` (logo nav)
- L333: `<video poster="assets/hero.jpg">` (hero video)
- L334/347: `<source src="assets/hero-ai-dashboard.mp4">` (hero video)

**Impacto:** el hero (video + poster) y el logo no cargan en la página real servida
por la API → sección principal del landing rota y logo ausente.

**Reproducir:** `curl -s -o /dev/null -w "%{http_code}" http://<host>/assets/hero.jpg` → 404.

**Causa raíz (2 defectos distintos):**
1. Path: el HTML usa `assets/...` pero el mount es `/static`. Falta reescribir a
   `/static/assets/...` o añadir un mount/alias `/assets`.
2. Nombre de archivo: `logo-likida.jpg` **no existe**; el real es `landing/assets/logo.png`. Falta renombrar la referencia (o el archivo).

**Sugerencia (para Zuck):** en el HTML usar `/static/assets/...`, y corregir el
nombre del logo a `logo.png`. Verificar con `curl` que los 3 URLs den 200.

### 5.2 Lo que sí funciona (verificado)

| Chequeo | Resultado |
|---|---|
| Render completo (nav, hero, secciones, pricing, form) | ✅ |
| JS errors en consola | 0 (solo los 4 "Failed to load resource" = BUG-1) |
| Links internos / anchors | 13 links, 0 targets rotos (`missing_anchor_targets: []`) |
| `/dashboard` link | 200 ✅ |
| Overflow horizontal 375px | ✅ `scrollWidth=375=clientWidth`, 0 elementos desbordados |
| Overflow 768px | ✅ |
| Overflow 1440px | ✅ |
| Form de contacto (campos + submit) | ✅ presente, campos requeridos correctos |

### 5.3 Performance

Sin Lighthouse CLI disponible; medido con Navigation Timing real (Playwright):

| Viewport | TTFB | DOMContentLoaded | Load |
|---|---|---|---|
| mobile 375 | 9ms | 531ms | 534ms |
| tablet 768 | 3ms | 38ms | 167ms |
| desktop 1440 | 2ms | 35ms | 187ms |

- Carga global **rápida** (< 550ms load incluso en el primer paint de 375px).
- ⚠️ **Recomendación:** `hero-ai-dashboard.mp4` pesa **5.5 MB** y se referencia 2×
  (dos `<source>`), total landing ~11 MB. En móvil/3G es pesado. Sugerir: comprimir
  a WebM/H.265 (~1–2MB), `preload="none"` en móvil, o lazy-load del video bajo el
  fold. No es bloqueante (la carga estática inicial es rápida), pero mejora Core Web Vitals.

---

## 6. SEGURIDAD

| Chequeo | Resultado | Evidencia |
|---|---|---|
| Secrets en código | ✅ Ninguno real | Escaneo regex (SK-, AKIA, ghp_, RSA keys, password=, api_key=, B2B_API_KEY=) → solo valores de ejemplo (`secret`, `change-me`, `mi-secreto`) en docs/README/Dockerfile. Test `test_secrets_scan_repo` PASSED. |
| Secrets servidos vía web | ✅ Ninguno | La API key no aparece en la landing ni en respuestas `/stats` (grep count = 0). Test `test_secrets_scan_no_servidos_via_web` PASSED. |
| Auth API (X-API-Key) | ✅ | Sin key → 401 · key inválida → 401 · key válida → 200. Comparación constant-time (`hmac.compare_digest`). Intento fallido auditado. |
| Auth portal | ✅ | Login inválido 401, token inválido 401, sesiones guardadas **hashadas** (SHA-256 64 hex, nunca token en claro en DB), TTL 30 días. |
| Rate limiting | ✅ ACTIVO | Middleware global (default 300 req/min/IP+path, configurable `B2B_RATE_LIMIT_PER_MIN` / `B2B_RATE_LIMIT=off`). Bajo carga → **429** `Demasiadas peticiones.` con `Retry-After`. Health/metrics/estáticos exentos. Multi-tenant: limitador por tenant en v2. |
| XSS | ✅ | Tests `test_xss_*` PASSED (escapes en dashboard HTML, JSON no servido como HTML, leads no almacenan HTML). |
| Auth bypass | ✅ | `test_auth_bypass_medios_alternativos` PASSED. |
| Path traversal (icons) | ✅ | Solo `.png` y validación de resolve dentro de LANDING_DIR. |
| Contenedor | ✅ | Dockerfile corre como usuario no-root (`USER b2b`), healthcheck curl. |

**Hallazgo menor:** `.env` local contiene una API key real de 32 hex en claro. Como
**no hay repo git** en el directorio, no está en VCS (no comprometido), pero en el
despliegue real debe rotarse y asegurarse de que `.env*` esté en `.gitignore` del
repo fuente. No es bloqueante para este entregable (es la key de dev), sí para
higiene de secretos.

---

## 7. RECOMENDACIONES ANTES DE DEPLOY

**Obligatorias (bloquean):**
1. Corregir los 3 URLs de la landing (BUG-1): `assets/*` → `/static/assets/*`, y
   `logo-likida.jpg` → `logo.png`. Verificar con `curl` que devuelvan 200.
2. Rotar la `B2B_API_KEY` antes de producción (la de `.env` es de dev) y asegurar
   `.env*` en `.gitignore`.

**Recomendadas:**
3. Comprimir el video hero (5.5MB) y considerar `preload="none"` en móvil.
4. Documentar la credencial por defecto del portal demo en el seed/deploy.
5. Revisar con negocio el detector de anomalías (dashboard reporta anomalias == total).

**No bloquea, ya sano:** tests 422/422, auth, rate-limit, multi-tenant, CLI, API.

---

## 8. ESTADO DE VERIFICACIÓN

**✓ Verificado**
- 422/422 tests pasan — `python -m pytest` → `422 passed in 12.63s`
- API upload/list/stats funcionan (curl, códigos 200/401/422 correctos)
- Portal login+upload+status+list funcionan (curl, token real)
- CLI process/batch/report/status funcionan (salida real)
- Landing responsive 375/768/1440 sin overflow, 0 anchors rotos
- BUG-1 confirmado: 3 assets 404 en `/assets/*`, mismo archivo 200 en `/static/assets/*`
- Rate-limit devuelve 429 bajo carga; auth devuelve 401 sin key/key inválida
- Sesiones portal hashadas en DB; key no servida por web

**? Inferido**
- La anomalía del dashboard (== total) es un problema real — falta revisar el umbral
  del detector para confirmar si es bug o comportamiento esperado con datos demo.

**✗ No verificado**
- Lighthouse oficial (no instalado) — se sustituyó por Navigation Timing real.
- Docker/nginx en vivo (no se levantó el stack prod completo; se validó la lógica
  de nginx + Dockerfile por lectura, y el comportamiento FastAPI es idéntico).
- Carga bajo estrés real (load_test.py existe, no se ejecutó — fuera de alcance 30min).

**Qué NO prueba esto:** que los tests sean exhaustivos sobre la lógica de negocio
fiscal (los fixtures son demo), ni que el stack Postgres/Redis declarado en
`docker-compose.prod.yml` funcione (la capa de datos es SQLite, PG es roadmap).
