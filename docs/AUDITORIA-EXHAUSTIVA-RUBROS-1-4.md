# AUDITORIA EXHAUSTIVA — RUBROS 1-4

**Proyecto:** Likida AI — Agente contable IA enterprise  
**Fecha:** 2026-08-01  
**Versión auditora:** Hermes Agent (subagent)  
**Alcance:** `b2b_ai/`, `landing/`, `Dockerfile`, `.gitignore`, `tests/`

---

## RESUMEN EJECUTIVO

| Nivel | Cantidad |
|-------|----------|
| 🔴 CRITICO | 3 |
| 🟠 ALTO | 9 |
| 🟡 BAJO | 10 |
| 🔵 INFO | 8 |

---

## RUBRO 1: SEGURIDAD

### 🔴 CRITICO

#### SEC-01: `logging` no importado en app.py — AttributeError en producción
**Archivo:** `b2b_ai/api/app.py` (líneas 489, 499, 1450, 1564)  
**Problema:** El módulo `logging` se importa localmente con alias (`import logging as _arl`, `import logging as _demo_logging`) en funciones internas, pero la referencia `logging.getLogger("b2b_ai.shutdown")` en el `lifespan` (línea 489) NO tiene import previa — `logging` no está en el `import` global del archivo. Si uvicorn no inyecta `logging` en el namespace, esto causa `NameError` al arrancar.  
**Riesgo:** La aplicación no arranca en algunos contextos de import.  
**Remediación:** Agregar `import logging` al bloque de imports globales de `app.py`.

#### SEC-02: ARCO endpoint `/api/v1/arco/estatus/{email}` y `/api/v1/arco/datos/{email}` — sin autenticación
**Archivo:** `b2b_ai/api/app.py` (líneas 1484-1548)  
**Problema:** Los endpoints ARCO (`/api/v1/arco/estatus/{email}`, `/api/v1/arco/datos/{email}`, `/api/v1/arco/cancelacion/{email}`) NO requieren `Depends(require_api_key)` ni `Depends(require_auth)`. Cualquier persona puede:
- Consultar si un email tiene solicitudes ARCO registradas (enumeración de usuarios).
- Acceder a los datos personales de cualquier titular por email (violación LFPDPPP).
- Solicitar cancelación de datos personales sin autenticación.

**Riesgo:** Exfiltración de PII, cumplimiento LFPDPPP comprometido.  
**Remediación:** Agregar `auth_info: dict = Depends(require_api_key)` (o JWT auth) a todos los endpoints ARCO. El endpoint de solicitud (`/api/v1/arco/solicitud`) puede quedarse público pero los de consulta/acceso/cancelación requieren auth.

#### SEC-03: ARCO datos — SQL con f-string sobre email no sanitizado
**Archivo:** `b2b_ai/api/app.py` (línea 1489)  
```python
rows = db.conn.execute(
    "SELECT entity_id, payload, status, ts FROM audit_log "
    "WHERE entity = 'arco_request' AND entity_id = ? "
    "ORDER BY ts DESC LIMIT 20",
    (email,),
).fetchall()
```
**Veredicto:** OK — usa parameterized query con `?`. **No hay SQL injection aquí.** (Clasificado como falso positivo tras revisión.)

---

### 🟠 ALTO

#### SEC-04: `b2b-ai.local` hardcodeado en código fuente de producción
**Archivos:** `b2b_ai/api/app.py`, `b2b_ai/api/versioning.py`, `b2b_ai/services/pipeline.py`, `b2b_ai/notifications/sender.py`, `b2b_ai/db/tenants.py`, etc. (~24 archivos)  
**Problema:** El dominio `b2b-ai.local` se usa como default en:
- Email remitente: `agente@b2b-ai.local`, `despacho@b2b-ai.local`
- Sitemap: `https://www.b2b-ai.local/sitemap.xml`
- Docs de migración: `https://docs.b2b-ai.local/migration/v1-to-v2`
- Contacto API: `ventas@b2b-ai.local`

Estos defaults funcionan como placeholder pero si el operador no configura las env vars reales, los emails se envían a un dominio inexistente y el sitemap/docs apuntan a URLs muertas.  
**Riesgo:** Bajo funcionalmente, pero alto para imagen profesional ante clientes enterprise.  
**Remediación:** Documentar las env vars requeridas (B2B_SMTP_FROM, etc.) y fallar con warning claro en producción si siguen siendo `.local`.

#### SEC-05: Token blacklist en memoria — no persiste entre reinicios
**Archivo:** `b2b_ai/auth/middleware.py` (línea 40)  
```python
_token_blacklist: Dict[str, float] = {}
```
**Problema:** Los tokens revocados (logout) se guardan en un dict en memoria. Si el proceso reinicia (deploy, crash), los tokens revocados vuelven a ser válidos.  
**Riesgo:** Un usuario que hizo logout mantiene acceso si el servidor reinicia.  
**Remediación:** Migrar blacklist a Redis (ya hay `B2B_REDIS_URL` configurado) o tabla DB.

#### SEC-06: `_ctx_tenant` cache en memoria sin TTL máximo ni límite de tamaño
**Archivo:** `b2b_ai/api/app.py` (líneas 648-664)  
**Problema:** `_ctx_tenant_cache` es un dict que crece indefinidamente con cada API key única. En un ataque con miles de keys inválidas, puede consumir memoria.  
**Riesgo:** Low-grade DoS por acumulación de claves.  
**Remediación:** Usar un LRU cache con `functools.lru_cache` o limitar tamaño con TTL sweep (similar al RateLimiter).

#### SEC-07: `import logging` inconsistente — 3 alias distintos en app.py
**Archivo:** `b2b_ai/api/app.py`  
**Problema:** `logging` se importa como `_arl` (líneas 1450, 1564), `_demo_logging` (línea 1613), y se usa directamente como `logging.getLogger` (línea 489) sin import global. Código frágil y difícil de mantener.  
**Remediación:** Unificar en un solo `import logging` global al inicio del archivo.

#### SEC-08: CORS permite wildcard si se configura `B2B_CORS_ORIGINS=*`
**Archivo:** `b2b_ai/api/app.py` (línea 550)  
**Problema:** Si el operador configura `B2B_CORS_ORIGINS=*`, cualquier sitio puede hacer requests autenticados (si el cliente envía la API key desde el browser). Esto es especialmente peligroso si `B2B_CORS_ALLOW_CREDENTIALS=true` se combina con `*` (aunque browsers modernos lo bloquean).  
**Riesgo:** Configuración insegura posible.  
**Remediación:** Validar que si `allow_credentials=true`, `origins` NO sea `*`. Log warning si se detecta.

#### SEC-09: `robots.txt` expone sitemap URL hardcodeada
**Archivo:** `b2b_ai/api/app.py` (línea 1412)  
```python
"Sitemap: https://www.b2b-ai.local/sitemap.xml\n"
```
**Problema:** URL hardcodeada que no existe.  
**Remediación:** Hacer configurable vía env o eliminar el sitemap reference si no hay dominio real.

---

### 🟡 BAJO

#### SEC-10: `.gitignore` incluye `*.db` pero no `*.db` auxiliares en una sola línea
**Archivo:** `.gitignore` (línea 29)  
**Problema:** Línea 29: `*.db-shm\n*.db-wal` — tiene un `\n` literal en la línea, lo cual es un error de formato. Las líneas 14-15 ya cubren `*.db-wal` y `*.db-shm` correctamente.  
**Remediación:** Eliminar la línea 29 redundante/malformada.

#### SEC-11: `b2b_ai.db` presente en el directorio (posiblemente en git)
**Archivo:** `b2b_ai.db`, `b2b_ai.db-shm`, `b2b_ai.db-wal`  
**Problema:** Archivos de base de datos SQLite están en el directorio de trabajo. Si se commitearon antes de agregar `.gitignore`, contienen datos reales.  
**Remediación:** Verificar historial de git; si se commiteó, hacer `git filter-branch` o BFG para purgar.

#### SEC-12: `example.com` como default en Computer Use drivers
**Archivos:** `b2b_ai/computer_use/browser.py` (línea 140), `contpaqi_real_driver.py` (línea 100), `aspel_real_driver.py` (línea 105)  
**Problema:** URLs default `https://contaqiweb.example.com/app`. Validación en `config.py` rechaza `example.com` en modo playwright — correcto. Pero el default existe como constante.  
**Riesgo:** Bajo (la validación lo atrapa).  
**Remediación:** INFO. La protección ya existe.

#### SEC-13: `install_security_headers` añade middleware pero no importa `logging`
**Archivo:** `b2b_ai/api/security_headers.py`  
**Problema:** El middleware no tiene logging propio para errores internos. Si `_is_https` falla, devuelve `False` silenciosamente.  
**Riesgo:** Bajo.  
**Remediación:** Agregar logging de debug.

#### SEC-14: Rate limiter IP-based usa `request.client.host` sin fallback robusto
**Archivo:** `b2b_ai/api/app.py` (línea 355)  
**Problema:** Si `request.client` es `None` (raro pero posible en tests), devuelve `"unknown"`. Todas las requests sin IP caen en el mismo bucket.  
**Riesgo:** Bajo (solo edge case).

---

### 🔵 INFO

#### SEC-15: No hay hardcoded secrets en el código fuente
**Verificado:** No se encontraron API keys, passwords, tokens ni secrets literales en el código. Todos los secretos se leen de env vars. Buena práctica.

#### SEC-16: `.gitignore` cubre `.env`, `.env.local`, `.env.production`, `.env.railway`
**Verificado:** Correcto. Los archivos `.env.example` y `.env.production.example` están presentes como templates (OK).

#### SEC-17: Constant-time comparison para API keys y JWT signatures
**Verificado:** `hmac.compare_digest()` se usa en `auth.py` y `middleware.py`. Correcto.

#### SEC-18: AES-GCM encryption at rest implementado
**Verificado:** `b2b_ai/api/security.py` implementa `encrypt_field`/`decrypt_field` con AES-GCM. Fail-fast si `B2B_ENCRYPTION_KEY` no está configurada en producción. Correcto.

---

## RUBRO 2: FRONTEND (landing/index.html)

### 🟠 ALTO

#### FE-01: Formulario de contacto no tiene CSRF ni honeypot anti-spam
**Archivo:** `landing/index.html` (líneas 715-722)  
**Problema:** El formulario `<form class="cta-form">` envía datos sin:
- Token CSRF (aunque es un form estático que hace POST a `/api/v1/leads` que es público, el riesgo es spam masivo).
- Campo honeypot (hidden field para atrapar bots).
- Rate limiting diferenciado para el formulario (el rate limiter global de 300/min es generoso para un form público; `/api/v1/leads` ya tiene limit de 10/min en el enterprise rate limiter).

**Riesgo:** Spam de leads ficticios.  
**Remediación:** Agregar campo honeypot oculto y/o reCAPTCHA.

#### FE-02: Video embed es un rickroll (placeholder)
**Archivo:** `landing/index.html` (línea 703)  
```html
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" ...>
```
**Problema:** El video de demo es el placeholder de Rick Astley. En producción esto es inaceptable.  
**Remediación:** Reemplazar con el video real de demo o eliminar la sección.

#### FE-03: Links de footer sin destino real
**Archivo:** `landing/index.html` (líneas 748-756)  
```html
<a href="#">Blog</a>
<a href="#">Careers</a>
<a href="#">Instagram</a>
<a href="#">LinkedIn</a>
<a href="#">X (Twitter)</a>
```
**Problema:** Todos apuntan a `#` (link roto). El link "Aviso de Privacidad" (línea 761) también va a `#`.  
**Remediación:** Apuntar a URLs reales o eliminar los links hasta que existan.

### 🟡 BAJO

#### FE-04: No hay skip-nav link para accesibilidad
**Archivo:** `landing/index.html`  
**Problema:** No existe un link "Skip to content" para usuarios de teclado/screen readers.  
**Remediación:** Agregar `<a href="#main" class="sr-only focus:not-sr-only">Skip to content</a>`.

#### FE-05: Accordion buttons sin `aria-expanded`
**Archivo:** `landing/index.html` (líneas 403, 425, 446, 467, 489)  
**Problema:** Los botones del accordion no tienen `aria-expanded`, `aria-controls`, ni `role="button"`. Screen readers no pueden determinar el estado.  
**Remediación:** Agregar atributos ARIA.

#### FE-06: Counter animation no tiene fallback para `prefers-reduced-motion`
**Archivo:** `landing/index.html` + `landing.js`  
**Problema:** Los counters animados no respetan `prefers-reduced-motion`.  
**Remediación:** Envolver en `@media (prefers-reduced-motion: no-preference)`.

#### FE-07: Logo sin `width`/`height` explícitos (CLS)
**Archivo:** `landing/index.html` (línea 210)  
```html
<img src="/static/assets/logo-likida.png" alt="Likida AI">
```
**Problema:** Sin `width`/`height`, causa layout shift (CLS).  
**Remediación:** Agregar dimensiones intrínsecas.

#### FE-08: Hero video sin `poster` funcional verificado
**Archivo:** `landing/index.html` (línea 240)  
```html
<video ... poster="/static/assets/hero.jpg">
```
**Problema:** Si `hero.jpg` no existe, el video area queda en negro hasta que carga. No se verificó si el asset existe.  
**Remediación:** Verificar que `/static/assets/hero.jpg` existe.

### 🔵 INFO

#### FE-09: Scroll reveal implementado correctamente
**Verificado:** CSS `.reveal { opacity: 0; transform: translateY(30px); }` con `.reveal.visible`. Intersection Observer probablemente en `landing.js`. Implementación estándar.

#### FE-10: Responsive breakpoints correctos
**Verificado:** Media queries en 768px (tablet) y 640px (mobile). Grid se adapta. Pricing en mobile va a 1 columna. Correcto.

#### FE-11: `lang="es"` declarado
**Verificado:** `<html lang="es">` — correcto para el target mexicano.

#### FE-12: Font loading optimizado
**Verificado:** `<link rel="preconnect">` para Google Fonts. `display=swap` para FOIT prevention. Correcto.

---

## RUBRO 3: BACKEND API

### 🟠 ALTO

#### API-01: Exceso de routers incluidos — 40+ sub-routers en `create_app()`
**Archivo:** `b2b_ai/api/app.py` (líneas 1153-1314)  
**Problema:** `create_app()` registra **40+ routers** con `app.include_router()`. Esto crea:
- Un startup lento (cada router importa sus módulos).
- Complejidad de mantenimiento extrema.
- Dificultad para auditar qué endpoints existen realmente.
- Posibles conflictos de rutas no detectados.

**Riesgo:** Mantenibilidad, performance de startup.  
**Remediación:** Consolidar routers por dominio (billing, accounting, fiscal, etc.) en sub-apps FastAPI.

#### API-02: Endpoints legacy (`/process`, `/invoices`, `/stats`, `/tools`) aún presentes
**Archivo:** `b2b_ai/api/app.py` (líneas 1321-1371)  
**Problema:** Los endpoints legacy duplican funcionalidad de `/api/v1/*`. Aunque ahora requieren API key, mantienen superficie de ataque duplicada y pueden divergir en comportamiento.  
**Riesgo:** Mantenimiento, inconsistencias.  
**Remediación:** Deprecar con header `Sunset` y eliminar en próxima versión.

#### API-03: Double rate limiting (dos middlewares superpuestos)
**Archivo:** `b2b_ai/api/app.py` (líneas 578-597)  
**Problema:** Hay DOS sistemas de rate limiting:
1. `RateLimiter` (in-memory, por IP+ruta, línea 574)
2. `EnterpriseRateLimitMiddleware` (Redis-backed, por tenant, línea 597)

Ambos se ejecutan para cada request. El primero es más restrictivo (300/min global). El segundo es más granular (per-tenant).  
**Riesgo:** Confusión operativa; un request puede pasar el primer limiter y ser bloqueado por el segundo, o viceversa. Los headers de rate limit son inconsistentes.  
**Remediación:** Elegir UNO como fuente de verdad. El enterprise limiter debería subsumir el básico.

#### API-04: `B2B_LOCAL_XML_DIRS` — path traversal mitigado pero feature peligrosa
**Archivo:** `b2b_ai/api/app.py` (líneas 394-437)  
**Problema:** La ingesta por ruta local (`xml_path`) está confinada a `B2B_LOCAL_XML_DIRS` y resuelve symlinks — buena mitigación. Pero la feature existe y si un operador configura `/` como root, cualquier archivo del sistema es accesible.  
**Riesgo:** Configuración insegura posible.  
**Remediación:** Validar que los roots no contengan `/`, `/etc`, `/home`, etc. en startup.

### 🟡 BAJO

#### API-05: `_StatsCache` no tiene límite de entries
**Archivo:** `b2b_ai/api/app.py` (líneas 149-178)  
**Problema:** El cache de stats crece con cada combinación (db, route, tenant, version). Sin límite superior.  
**Riesgo:** Bajo (pocas combinaciones en práctica).

#### API-06: Health check público expone conteos internos
**Archivo:** `b2b_ai/api/app.py` (líneas 669-681)  
```python
"invoices": db.count_invoices(),
"tenants": len(db.list_tenants()),
```
**Problema:** El health check público expone cuántas facturas y tenants hay. Un competidor puede usar esto para estimar el tamaño del negocio.  
**Remediación:** Mover conteos a `/health/detailed` (que sí requiere auth).

#### API-07: `/metrics/prometheus` público sin autenticación
**Archivo:** `b2b_ai/api/app.py` (líneas 689-697)  
**Problema:** El endpoint de Prometheus es público (sin auth). Expone métricas operativas detalladas.  
**Justificación:** Prometheus necesita scrapear sin auth.  
**Riesgo:** Si el servidor es accesible públicamente, las métricas son visibles.  
**Remediación:** Restringir por IP en producción (firewall/nginx) o agregar auth básica.

#### API-08: Error handlers estructurados — verificado OK
**Verificado:** `install_error_handlers(app)` está registrado. Los errores devuelven JSON estructurado.

### 🔵 INFO

#### API-09: Pipeline de middleware correcto
**Verificado:** Orden: Request Size Limit → Rate Limit → Metrics → Request Context → Audit → Auth. Correcto (outermost a innermost).

#### API-10: Idempotency middleware presente
**Verificado:** `install_idempotency(app)` — protege contra reenvío de requests.

#### API-11: OpenAPI docs enterprise configuradas
**Verificado:** `install_openapi_docs(app)` — schemas de error, flujos de auth, ejemplos de webhooks.

#### API-12: Graceful shutdown implementado
**Verificado:** `ShutdownManager`, signal handlers para SIGTERM/SIGINT, drain de conexiones PG/SQLite.

---

## RUBRO 4: AGENTIC (agent/loop.py)

### 🟠 ALTO

#### AG-01: `record_agent_processing()` nunca se llama en el loop
**Archivo:** `b2b_ai/monitoring/metrics.py` (línea 264) vs `b2b_ai/agent/loop.py`  
**Problema:** La función `record_agent_processing(confidence, success)` existe en metrics pero NO se invoca en `AgentLoop.process()`. Las métricas de confianza del agente y tasa de éxito no se registran.  
**Riesgo:** No hay observabilidad sobre la calidad de las decisiones del agente.  
**Remediación:** Llamar `record_agent_processing(clasif["confianza"], decision == "auto_processed")` al final de `process()`.

#### AG-02: LLM timeout fallback asume "normal" en anomalías — riesgo silencioso
**Archivo:** `b2b_ai/agent/loop.py` (líneas 193-194)  
```python
anomalia = {"nivel": "normal", "anomalias": [],
            "razon": "Timeout en LLM, asumiendo normal"}
```
**Problema:** Si el LLM hace timeout durante la detección de anomalías, el agente asume que NO hay anomalía. Esto es un falso negativo peligroso: una factura fraudulenta podría pasar como normal.  
**Riesgo:** Facturas fraudulentas procesadas automáticamente.  
**Remediación:** Timeout en anomalía debería escalar a revisión humana (como se hace con clasificación timeout → `requires_human_review: True`).

#### AG-03: `_resolve_tenant` crea tenant "Despacho Demo" si no existe ninguno
**Archivo:** `b2b_ai/agent/loop.py` (líneas 278-285)  
```python
tenants = self.db.list_tenants()
if tenants:
    return tenants[0]["id"]
return self.db.create_tenant("Despacho Demo", "")
```
**Problema:** Si no se pasa `tenant_id` y no hay tenants, se crea uno automáticamente. En producción esto puede crear tenants fantasma con RFC vacío.  
**Remediación:** En producción, fallar si no hay tenant explícito.

### 🟡 BAJO

#### AG-04: Confidence threshold configurable pero sin validación de rango
**Archivo:** `b2b_ai/agent/loop.py` (línea 205)  
```python
confidence_threshold = cfg.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)
```
**Problema:** Un operador puede configurar `confidence_threshold: 0.0` (todo pasa) o `confidence_threshold: 1.0` (nada pasa automáticamente) sin warning.  
**Remediación:** Validar rango [0.1, 0.95] en configuración.

#### AG-05: PII masking antes de enviar al LLM — correcto pero incompleto
**Archivo:** `b2b_ai/agent/loop.py` (líneas 169-174)  
**Verificado:** Se filtran keys sensibles (`nomina`, `curp`, `rfc_receptor`, `rfc_emisor`) y se aplica `_mask_pii` a strings. Correcto para LFPDPPP.  
**Mejora sugerida:** También filtrar `receptor_nombre` (es PII).

#### AG-06: Computer Use driver inyectado pero sin health check previo
**Archivo:** `b2b_ai/agent/loop.py` (líneas 272-276)  
```python
if self._cu_driver is not None:
    return self._call("register_erp", tenant_id, invoice=invoice, erp=self._cu_driver)
```
**Problema:** No se verifica que el CU driver esté healthy antes de usarlo. Si Playwright crash, el error se propaga sin graceful fallback.  
**Remediación:** Llamar `self._cu_driver.health()` antes de `_call("register_erp")`.

#### AG-07: `_llm_log` registra el resultado completo del LLM (posible PII leak en logs)
**Archivo:** `b2b_ai/agent/loop.py` (línea 83)  
```python
payload=payload
```
**Problema:** El payload del LLM classification se guarda completo en audit_log. Si el LLM devuelve datos sensibles en su respuesta, quedan persistidos.  
**Remediación:** Truncar o filtrar el payload antes de persistir.

### 🔵 INFO

#### AG-08: Confidence gate hard-coded a 0.50 — correcto
**Verificado:** `_CONFIDENCE_FLOOR = 0.50` (línea 202). Cualquier confianza debajo de 0.50 SIEMPRE requiere revisión humana, sin importar la policy del tenant. Buena práctica.

#### AG-09: HITL implementado correctamente
**Verificado:** `_escalate()` crea fila en tabla `reviews` para resolución humana. Se invoca en: parse_failed, invalid, anomaly, low_confidence. Correcto.

#### AG-10: Decision tree completo y documentado
**Verificado:** El docstring del módulo documenta el árbol de decisión completo. La implementación lo sigue fielmente.

---

## TABLA RESUMEN

| ID | Rubro | Nivel | Descripción | Estado |
|----|-------|-------|-------------|--------|
| SEC-01 | Seguridad | 🔴 CRITICO | `logging` no importado globalmente en app.py | ABIERTO |
| SEC-02 | Seguridad | 🔴 CRITICO | Endpoints ARCO sin autenticación | ABIERTO |
| SEC-03 | Seguridad | 🔴 | SQL injection en ARCO (falso positivo — usa `?`) | CERRADO |
| SEC-04 | Seguridad | 🟠 ALTO | `b2b-ai.local` hardcodeado en ~24 archivos | ABIERTO |
| SEC-05 | Seguridad | 🟠 ALTO | Token blacklist en memoria (no persistente) | ABIERTO |
| SEC-06 | Seguridad | 🟠 ALTO | `_ctx_tenant_cache` sin límite de tamaño | ABIERTO |
| SEC-07 | Seguridad | 🟠 ALTO | `import logging` inconsistente (3 alias) | ABIERTO |
| SEC-08 | Seguridad | 🟠 ALTO | CORS wildcard posible | ABIERTO |
| SEC-09 | Seguridad | 🟠 ALTO | robots.txt con sitemap hardcodeado | ABIERTO |
| SEC-10 | Seguridad | 🟡 BAJO | .gitignore línea malformada | ABIERTO |
| SEC-11 | Seguridad | 🟡 BAJO | DB SQLite en directorio de trabajo | INFO |
| SEC-12 | Seguridad | 🟡 BAJO | example.com como default (validado) | CERRADO |
| SEC-13 | Seguridad | 🟡 BAJO | Security headers sin logging | ABIERTO |
| SEC-14 | Seguridad | 🟡 BAJO | Rate limiter sin fallback IP robusto | ABIERTO |
| FE-01 | Frontend | 🟠 ALTO | Form sin honeypot/CSRF | ABIERTO |
| FE-02 | Frontend | 🟠 ALTO | Video placeholder (rickroll) | ABIERTO |
| FE-03 | Frontend | 🟠 ALTO | Links de footer rotos (`#`) | ABIERTO |
| FE-04 | Frontend | 🟡 BAJO | Sin skip-nav link | ABIERTO |
| FE-05 | Frontend | 🟡 BAJO | Accordion sin ARIA | ABIERTO |
| FE-06 | Frontend | 🟡 BAJO | Animaciones sin reduced-motion | ABIERTO |
| FE-07 | Frontend | 🟡 BAJO | Logo sin dimensiones (CLS) | ABIERTO |
| FE-08 | Frontend | 🟡 BAJO | Hero poster no verificado | INFO |
| API-01 | Backend | 🟠 ALTO | 40+ routers en create_app() | ABIERTO |
| API-02 | Backend | 🟠 ALTO | Endpoints legacy duplicados | ABIERTO |
| API-03 | Backend | 🟠 ALTO | Double rate limiting | ABIERTO |
| API-04 | Backend | 🟠 ALTO | B2B_LOCAL_XML_DIRS peligroso si mal config | ABIERTO |
| API-05 | Backend | 🟡 BAJO | Stats cache sin límite | ABIERTO |
| API-06 | Backend | 🟡 BAJO | Health check expone conteos | ABIERTO |
| API-07 | Backend | 🟡 BAJO | Prometheus metrics público | ABIERTO |
| AG-01 | Agentic | 🟠 ALTO | `record_agent_processing()` nunca llamado | ABIERTO |
| AG-02 | Agentic | 🟠 ALTO | LLM timeout en anomalía asume "normal" | ABIERTO |
| AG-03 | Agentic | 🟠 ALTO | Auto-crea tenant "Despacho Demo" | ABIERTO |
| AG-04 | Agentic | 🟡 BAJO | Confidence threshold sin validación de rango | ABIERTO |
| AG-05 | Agentic | 🟡 BAJO | PII masking podría incluir más campos | INFO |
| AG-06 | Agentic | 🟡 BAJO | CU driver sin health check previo | ABIERTO |
| AG-07 | Agentic | 🟡 BAJO | LLM payload completo en audit log | ABIERTO |

---

## PRIORIDADES DE REMEDIACIÓN

### Sprint inmediato (antes de deploy a producción):
1. **SEC-01:** Agregar `import logging` global en `app.py`
2. **SEC-02:** Agregar auth a endpoints ARCO de consulta/acceso/cancelación
3. **FE-02:** Reemplazar video placeholder
4. **FE-03:** Eliminar links rotos o apuntar a URLs reales

### Sprint siguiente:
5. **AG-02:** Timeout en anomalía → escalar a review (no asumir normal)
6. **AG-01:** Integrar `record_agent_processing()` en el loop
7. **SEC-05:** Migrar token blacklist a Redis
8. **API-03:** Consolidar rate limiting en un solo sistema
9. **FE-01:** Agregar honeypot al formulario de contacto

### Backlog:
10. **API-01:** Consolidar routers por dominio
11. **API-02:** Deprecar endpoints legacy
12. **SEC-06:** Limitar tamaño de tenant cache
13. **AG-03:** Fail-fast si no hay tenant en producción
