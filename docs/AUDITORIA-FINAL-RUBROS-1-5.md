# AUDITORÍA FINAL — RUBROS 1–5 (codebase real `b2b_ai/`)

**Proyecto:** Likida AI Enterprise · `/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise`
**Alcance auditado:** `b2b_ai/` (código real) + `landing/index.html` (solo para Rubro 2).
**Fecha:** 2026-08-02 · **Estado de la suite:** Railway online, 1166 casos de prueba `def test_`.

> No se exploraron repos externos (sherpa-onnx, etc.). Solo el árbol `b2b_ai/`.

---

## RESUMEN EJECUTIVO

| Rubro | Calificación | Veredicto |
|-------|--------------|-----------|
| 1. Seguridad | **5/10** | ⛔ NO aprobado — 1 hallazgo CRÍTICO (auth ausente en bookkeeping) |
| 2. Frontend (landing) | **7/10** | ✅ Aprobado con observaciones (formulario de leads inerte) |
| 3. Backend API | **7/10** | ✅ Aprobado con observaciones — 1 CRÍTICO heredado (bookkeeping) |
| 4. Agéntico | **6/10** | ⛔ NO aprobado — detector de anomalías FAIL-OPEN |
| 5. Arquitectura | **8/10** | ✅ Aprobado con observaciones |

**3 hallazgos CRÍTICOS** exigen corrección antes de producción:

1. **R1/R3 — `features/bookkeeping/routes.py` sin autenticación** (4 endpoints públicos).
2. **R4 — Detección de anomalías fail-open** en `agent/loop.py` (timeout LLM ⇒ `nivel="normal"`).
3. **R5 — Patrón de auth "opt-in" por router** que permitió el CRÍTICO nº1 (default-no-seguro).

---

## RUBRO 1 — SEGURIDAD

### CRÍTICO
- **S1-CRÍTICO · `features/bookkeeping/routes.py` — 4 endpoints sin auth.**
  `build_bookkeeping_router(db, require_api_key=None, ...)` acepta `require_api_key` pero **nunca lo usa**: no hay `Depends(...)` en ninguno de los 4 handlers ni dependencia a nivel de router. Endpoints expuestos públicamente:
  - `POST /api/v1/bookkeeping/process` → procesa CFDIs por todo el pipeline **incluida auto-registro a ERP** (`auto_register_erp=True`).
  - `POST /api/v1/bookkeeping/overrides` → inyecta overrides humanos de clasificación.
  - `GET /api/v1/bookkeeping/status`, `GET /api/v1/bookkeeping/suggestions`.
  Cualquier llamador anónimo puede disparar registro contable/ERP sin credenciales. **El parámetro `require_api_key` es un parámetro muerto** (docstring lo declara "Auth dependency" pero no se aplica).

### ALTO
- No se detectaron más rutas sin auth (ver Rubro 3, barrido exhaustivo). No hay otros hallazgos ALTO en este rubro.

### BAJO
- **S1-BAJO · `migration.py:117,185,225`** — f-strings de SQL interpolan `{table}`. El nombre proviene de `sqlite_master`/listas internas de migración (no de input de usuario), por lo que no es explotable por una petición, pero conviene sanitizar con identificadores citados (`_quote_pg_identifier` ya existe y no se usa aquí). Riesgo residual bajo.

### INFO
- **S1-INFO · `db.py:1534`** — `f"UPDATE client_users SET {sets}..."`: las columnas salen de la allowlist fija `_CLIENT_USER_EDITABLE = ("name","email","password_hash","role")`; anotado `# nosec B608`. Seguro por construcción.
- **S1-INFO · "Secrets hardcodeados"** — `password="password123"` en `declaraciones/sat_submitter.py:92` y `declaraciones/fiel_signer.py:54` **son ejemplos en docstrings**, no código ejecutable. No se encontraron secretos reales hardcodeados en `b2b_ai/`.
- **S1-INFO · `.env.example` / `.env.production.example` / `.env.railway.example`** son archivos de 0 bytes (no documentan las variables requeridas). `.gitignore` cubre `.env`, `.env.*`, `*.db`, credenciales; `.dockerignore` excluye `.env.*`, `tests/`, `docs/`, `*.md`. Correcto.
- **S1-INFO · Cifrado en reposo** AES-GCM (`B2B_ENCRYPTION_KEY`) con fail-fast en prod (`app.py:359-365`); JWT fail-fast (`check_jwt_config`); comparación de keys con `hmac.compare_digest` (`auth.py:30-34`); headers de seguridad HSTS/X-Frame-Options/nosniff/Referrer-Policy/CSP (`api/security_headers.py`); CORS desactivado por defecto (solo vía `B2B_CORS_ORIGINS`); límite de payload 10 MB; middleware de audit en todas las mutaciones; ARCO requiere auth en estatus/acceso/cancelación (solicitud pública por diseño LFPDPPP Art. 29).

**Calificación Rubro 1: 5/10** — La base es sólida (AES-GCM, JWT fail-fast, headers, rate-limit, audit trail, comparación constante, allowlists SQL), pero el CRÍTICO de bookkeeping anula la garantía de "todos los endpoints protegidos".

---

## RUBRO 2 — FRONTEND (LANDING `landing/index.html`)

**769 líneas**, estilo usehandle.ai (dark, hero con video, secciones `#platform/#agents/#integrations/#security/#pricing/#contact`, mobile menu).

- **Scroll reveal:** ✅ Implementado con `IntersectionObserver` en `landing.js` (39 usos de clase `reveal`, threshold 0.1, rootMargin -40px, un-observe tras revelar). Conteo animado (`.counter`), nav sticky, acordeón y menú móvil vía `addEventListener` (CSP-safe).
- **Responsive:** ✅ 7 bloques `@media` + menú móvil + grid en `1fr`. Correcto.
- **Assets:** ✅ `assets/hero-ai-dashboard.mp4` y `assets/logo-likida.png` existen y resuelven bajo `/static/` (montado a `LANDING_DIR` en `app.py:1131`).
- **Links:** mayormente anclas internas + redes sociales (instagram/linkedin/x) + `/legal/privacy` + fonts (preconnect). Sin links rotos a recursos estáticos.

### ALTO
- **F2-ALTO · Formulario de leads NO persiste datos.** `landing.js:77-83` `handleSubmit` hace `e.preventDefault()` + `alert('¡Gracias...!')` + `reset()`, e intercepta `#leadForm` (`.cta-form`). **No hay ningún `fetch`/XHR a `POST /api/v1/leads`** en `index.html` ni en `landing.js`. Resultado: la CTA principal de conversión no registra ningún lead en la DB (el endpoint backend `/api/v1/leads` queda muerto). Funcional, no de seguridad.

### BAJO
- **F2-BAJO · Video demo no cableado.** `index.html:703` `<iframe src="about:blank" data-video-url="https://www.youtube.com/embed/REPLACE_WITH_REAL_DEMO_VIDEO">`: `src` es `about:blank` y nadie lee `data-video-url` (no hay JS que lo asigne). El iframe queda vacío.

### INFO
- **F2-INFO · `href="#"` en `.nav-logo`** (2 sitios, líneas 209 y 732): el logo no enlaza a `#top`/inicio. Enlace muerto menor.

**Calificación Rubro 2: 7/10** — Estructura, reveal y responsividad sólidas; pierde por el formulario de captura inerte (funcionalidad comercial) y el video placeholder.

---

## RUBRO 3 — BACKEND API

- **Conteo de endpoints:** **354** decoradores `@app.*`/`@router.*` en `b2b_ai/` (168 GET, 152 POST, 12 PUT/PATCH, 3 DELETE). 331 referencias a `require_api_key`.
- **Auth — barrido exhaustivo:** se comparó endpoint-por-endpoint el nº de handlers vs. nº de `Depends(require_api_key|auth_dep|self.require_api_key)` + dependencias a nivel de router. Resultado: **solo `bookkeeping` queda sin auth** (CRÍTICO, Rubro 1). El resto aplica auth por:
  - handler: `auth_info: dict = Depends(require_api_key)` (app.py, `routes_invoices.py`, `routes_arco.py`, `close_management`, `reconciliation_agent`, `clientes`, etc.);
  - router: `router.dependencies.append(Depends(require_api_key))` (`ap_ar`, `contabilidad`, `contabilidad_electronica`, `nomina`, `pagos`, `reportes`, `nomina_completa`, `pre_auditoria`);
  - clase builder: `Depends(self.require_api_key)`.
- **Endpoints públicos intencionales:** `/health` (+HEAD), landing/estáticos, `POST /api/v1/leads` (landing), `POST /api/v1/arco/solicitud` (LFPDPPP Art. 29, titular del dato). Los públicos de escritura (`/leads`, `/arco/solicitud`) **sí caen bajo rate-limit por IP** (no están en `_RATE_LIMIT_EXEMPT_PREFIXES`).
- **Validation:** bodies vía Pydantic `BaseModel` en la gran mayoría; validación de periodos y `ge/le` en queries; `allowed_upload_extension` (solo .xml/.pdf).
- **Rate limiting:** doble capa — limiter en memoria por `(IP, ruta)` (default 300/min, `B2B_RATE_LIMIT_PER_MIN`, con `_sweep` que evita DoS de memoria) + `install_enterprise_rate_limit` (Redis, per-tenant/rol, headers `X-RateLimit-*`, si `B2B_REDIS_URL` está configurado). `_client_ip` solo confía en `X-Forwarded-For` con `B2B_TRUST_PROXY` (evita spoofing). **Buen diseño.**
- **Idempotencia:** middleware por `Idempotency-Key` (TTL 24h) para escrituras. ✅

### BAJO
- **B3-BAJO · `contabilidad_balanza_get` (`app.py:837`)** hace `int(ejercicio)`/`int(mes)` sobre `periodo` sin try/except → un `periodo` no numérico lanza `ValueError` no capturado (500 en vez de 422). Mismo patrón parcial en `contabilidad_electronica_post`/`download` (ahí sí hay try/except). Robustez menor.

### INFO
- **B3-INFO ·** la API expone además versionado v2 (`api/v2.py`), `openapi_docs` enterprise y rutas legacy `/process`, `/stats`, `/tools` (deprecated, aún con auth). Coherente.

**Calificación Rubro 3: 7/10** — Endpoints, validación y rate-limiting en general correctos; la nota baja por el CRÍTICO de bookkeeping (auth ausente) y los `int()` no validados.

---

## RUBRO 4 — AGENTIC (`agent/loop.py`)

Árbol de decisión explícito y human-in-the-loop (crea filas en `reviews` al escalar). Líneas clave:
- **Confidence gate:** ✅ **Correcto.** `_CONFIDENCE_FLOOR = 0.50` (línea 203-205) fuerza `requires_human_review=True` para cualquier confianza < 0.50 "SIEMPRE, sin importar policy"; threshold efectivo por tenant `confidence_threshold` (default `DEFAULT_CONFIDENCE_THRESHOLD = 0.7`). Con `policy='hold'` no se registra ERP; con `auto_register` se registra pero con revisión (y el floor 0.50 lo blinda).
- **PII masking antes de LLM externo:** ✅ `_SENSITIVE_KEYS = {nomina, curp, rfc_receptor, rfc_emisor}` filtrados + `_mask_pii` (SECURITY/LFPDPPP-06).
- **Tenant explícito en prod:** ✅ `_resolve_tenant` exige `tenant_id` si no es dev (`loop.py:293-296`).
- **`record_agent_processing`:** ✅ **Presente.** Definido en `monitoring/metrics.py:264` y llamado en `loop.py:262-266` (registra confianza + éxito; `try/except` para que métricas nunca rompan el pipeline).

### CRÍTICO
- **A4-CRÍTICO · Detección de anomalías FAIL-OPEN en timeout LLM.**
  `loop.py:193-195`: ante `ServiceTimeoutError` del detector, se asigna
  ```python
  anomalia = {"nivel": "normal", "anomalias": [], "razon": "Timeout en LLM, asumiendo normal"}
  ```
  Esto es exactamente lo **contrario** del fail-closed requerido (`nivel="alerta"`). Si el LLM de anomalías falla/expira, el pipeline asume "normal", no dispara `requiere_rev`, y la factura puede auto-procesarse (registro ERP) sin que nadie revise una posible anomalía (montos inusuales, facturación sospechosa). **Silencio de riesgo ante fallo del detector.** Debe cambiar a fail-closed: timeout ⇒ `nivel="alerta"` + revisión humana obligatoria.

### BAJO
- **A4-BAJO ·** La métrica `record_agent_processing` cuenta "éxito" como `decision == "auto_processed"`; una anomalía fail-open que deriva en auto_procesado infla la tasa de éxito y enmascara el fallo del detector en dashboards.

**Calificación Rubro 4: 6/10** — Confidence gate impecable, PII masking y `record_agent_processing` presentes; la decisión fail-open del detector de anomalías es un riesgo de compliance/seguridad que contradice la política declarada (línea 15 del docstring: "anomalía alerta → escalate").

---

## RUBRO 5 — ARQUITECTURA

- **Estructura modular sólida:** `api/` (app, auth, middleware, rate_limiter, security, validators, routes_*), `features/` (24 módulos por dominio), `integrations/` (adapters por categoría), `services/`, `db/` (SQLite+PG vía `adapter_factory`), `billing/`, `cfdi/`, `auth/` (JWT+RBAC), `audit/`, `notifications/`, `portal/`, `monitoring/`, `infrastructure/`, `computer_use/`. Separación por responsabilidad clara.
- **Factory pattern:** ✅ `build_*_router(db, require_api_key)` en cada feature, `db/adapter_factory.py`, `computer_use/factory.py`, providers de billing (`stripe_provider`, `conekta_provider`), `integrations/hub.py`. Consistente.
- **DI:** ✅ `create_app(db=None)` (inyección de DB para tests), `AgentLoop(db=..., llm=..., erp=..., email=...)` con defaults pero overridables, clases `XxxRouter(db, require_api_key)` con `@dataclass`-style builders. Buen patrón.

### ALTO
- **AR5-ALTO · Auth "opt-in" por router (default no seguro).** La convención es `if require_api_key: router.dependencies.append(Depends(require_api_key))`. Cuando un builder recibe `None` (o se le olvida aplicarlo, caso bookkeeping), la ruta queda **silenciosamente pública** — no hay fallo ni error en arranque. Un esquema *fail-secure* (auth obligatoria por defecto, `Depends` incondicional) habría impedido el CRÍTICO de bookkeeping. Es la causa raíz arquitectónica del hallazgo nº1.

### BAJO
- **AR5-BAJO · `b2b_ai/__init__.py` importa 9 subpaquetes de forma EAGER** (`from b2b_ai import cfdi, tools, erp, db, notifications, services, api, computer_use, monitoring`). El rubro esperaba imports **lazy**. Esto arrastra dependencias pesadas (FastAPI vía `api`, Playwright/computer_use) al importar el paquete raíz, encarece el cold-start y arriesga imports circulares. Debería diferirse (lazy `__getattr__` o imports solo en funciones) o documentarse como decisión.

### INFO
- **AR5-INFO ·** Separación API real (`b2b_ai/api`) vs. paquete `api` como subcarpeta duplica el término pero es navegable. `features/` mezcla dominios de negocio con `routes.py` (capa de transporte) — aceptable para este tamaño.
- **AR5-INFO ·** Más de 354 endpoints en un solo `create_app` (app.py de 1153 líneas): bien descompuesto vía `include_router`, aunque `app.py` sigue siendo el pegamento central.

**Calificación Rubro 5: 8/10** — Modularidad, factories y DI bien resueltos; la nota baja por el patrón de auth opt-in (default no seguro) que es la causa raíz del CRÍTICO de bookkeeping y por el eager-import del `__init__.py`.

---

## PLAN DE ACCIÓN (priorizado)

1. **CRÍTICO · Bookkeeping sin auth:** añadir `auth_info: dict = Depends(require_api_key)` a los 4 handlers de `features/bookkeeping/routes.py` (o `router.dependencies.append(...)`) y eliminar el parámetro muerto.
2. **CRÍTICO · Fail-open de anomalías:** en `agent/loop.py:193-195` cambiar timeout del detector a `{"nivel": "alerta", ...}` + `requires_human_review=True` (fail-closed).
3. **ALTO · Auth fail-secure:** revertir la convención a `Depends` incondicional / validar en arranque que ningún router quede sin auth (test que enumere endpoints públicos no declarados).
4. **ALTO · Landing leads:** conectar `#leadForm` a `POST /api/v1/leads` (fetch con X-API-Key opcional) en vez de `alert()`.
5. **BAJO:** sanitizar `migration.py` f-strings con `_quote_pg_identifier`; `int()` de `periodo` con 422; cablear `data-video-url` del iframe; convertir `__init__.py` a lazy imports.

---

*Generado por auditoría de rubros 1–5 sobre el codebase real `b2b_ai/`. Ningún hallazgo se basa en repos externos.*
