# AUDITORÍA FINAL — SEGURIDAD Y AUTENTICACIÓN
## Likida AI Enterprise — b2b_ai

**Fecha:** 2026-08-01
**Alcance:** b2b_ai/auth/, b2b_ai/api/app.py, b2b_ai/api/middleware.py, b2b_ai/billing/, b2b_ai/infrastructure/, b2b_ai/api/security.py, b2b_ai/api/webhooks.py, b2b_ai/api/portal.py, b2b_ai/api/security_headers.py
**Método:** Lectura estática exhaustiva de código fuente (108K líneas)
**Stack:** FastAPI, PostgreSQL/SQLite, Celery+Redis, cryptography (AES-GCM), bcrypt, JWT HS256

---

## RESUMEN EJECUTIVO

| Severidad | Hallazgos |
|-----------|-----------|
| 🔴 Crítica | 3 |
| 🟠 Alta    | 8 |
| 🟡 Media   | 9 |
| 🟢 Baja    | 4 |
| **Total**  | **24** |

---

## HALLAZGOS CRÍTICOS

### C-01 — ARCO Endpoints Públicos: Datos Personales sin Autenticación

**Archivo:** `b2b_ai/api/app.py:1402-1509`
**Severidad:** 🔴 CRÍTICA

**Descripción:** Los endpoints ARCO (Acceso, Rectificación, Cancelación, Oposición) están definidos **sin protección `require_api_key`** y **sin autenticación JWT**:

- `POST /api/v1/arco/solicitud` (línea 1405) — público, acepta datos personales
- `GET /api/v1/arco/estatus/{email}` (línea 1448) — **público, devuelve historial de solicitudes de CUALQUIER email**
- `GET /api/v1/arco/datos/{email}` (línea 1479) — **público, expone TODOS los datos personales de un usuario** (nombre, email, teléfono, RFC, etc.)
- `POST /api/v1/arco/cancelacion/{email}` (línea 1514) — **público, permite solicitar eliminación de datos de CUALQUIER usuario**

Cualquiera con acceso a la API puede:
1. Enumerar usuarios por email (fuzzing `{email}` en la URL)
2. Descargar datos personales completos de cualquier titular
3. Solicitar cancelación de datos de terceros

**Nota:** LFPDPPP Art. 28 exige verificar la identidad del titular antes de procesar solicitudes ARCO. Estos endpoints no verifican identidad.

**Fix propuesto:**
```python
# Opción A: Proteger con JWT (requiere que el titular esté autenticado)
@app.get("/api/v1/arco/datos/{email}")
async def arco_acceso(email: str, ctx: dict = Depends(jwt.require_auth)):
    if ctx["email"] != email and ctx["role"] != "admin":
        raise HTTPException(403, "Solo puedes acceder a tus propios datos.")
    ...

# Opción B: Token de verificación por email (sin login previo)
# Generar token de un solo uso enviado al email del titular, 
# validarlo antes de devolver datos.
```

---

### C-02 — Token Blacklist en Memoria: Logout Inefectivo en Multi-Worker

**Archivo:** `b2b_ai/auth/middleware.py:39-40`
**Severidad:** 🔴 CRÍTICA

**Descripción:** La blacklist de tokens JWT vive en un `dict` en memoria del proceso:
```python
_token_blacklist: Dict[str, float] = {}
```

Problemas:
1. **Multi-worker:** Con uvicorn workers > 1, cada worker tiene su propia blacklist. El logout en worker A no revoca el token en worker B.
2. **Reinicio:** Al reiniciar el servidor, TODA la blacklist se pierde. Cada token revocado vuelve a ser válido.
3. **No escalable:** Sin Redis/DB compartida, el logout JWT es una promesa vacía en producción.

**Fix propuesto:**
```python
# Mover blacklist a Redis con TTL = exp del token
import redis
_blacklist_client = redis.from_url(os.environ["B2B_REDIS_URL"])

def revoke_token(self, token: str) -> None:
    claims = self.decode(token)
    jti = claims.get("jti")
    exp = claims.get("exp", time.time() + ACCESS_TTL)
    ttl = max(1, int(exp - time.time()))
    _blacklist_client.setex(f"bl:{jti}", ttl, "1")

def is_token_revoked(self, token: str) -> bool:
    claims = self.decode(token)
    jti = claims.get("jti")
    return jti is not None and _blacklist_client.exists(f"bl:{jti}")
```

---

### C-03 — Webhook de Conekta: Firma Verificada contra JSON Re-serializado, no Raw Body

**Archivo:** `b2b_ai/billing/webhook_receiver.py:331-332`
**Severidad:** 🔴 CRÍTICA

**Descripción:** En `process_webhook()`, la firma se verifica contra el JSON re-serializado:
```python
payload_body = json.dumps(payload, separators=(",", ":"))  # ← re-serializa
if not self.verify_signature(payload_body, signature_header):
```

El payload ya fue parseado por FastAPI (línea 466: `payload = json.loads(raw_body)`), luego se re-serializa. La re-serialización JSON puede producir un string diferente al original (orden de keys, whitespace, encoding de Unicode). Esto significa:
- Firmas válidas pueden ser rechazadas (falsos negativos)
- Un atacante podría manipular el raw body para que al re-serializar coincida con una firma que construyó

**Nota:** El endpoint en `b2b_ai/billing/api.py:196-248` **SÍ** verifica contra `raw_body` correctamente. Solo `webhook_receiver.py` tiene el bug.

**Fix propuesto:**
```python
# En webhook_receiver.py, recibir raw_body directamente:
async def conekta_webhook(request: Request):
    raw_body = await request.body()
    payload = json.loads(raw_body)
    # Pasar raw_body.decode() a verify_signature, NO json.dumps(payload)
    receiver = ConektaWebhookReceiver(db, webhook_secret)
    return receiver.process_webhook_raw(raw_body.decode("utf-8"), payload, signature_header)
```

---

## HALLAZGOS ALTOS

### A-01 — Portal Login: tenant_id del Body Controla Búsqueda Cross-Tenant

**Archivo:** `b2b_ai/api/portal.py:189`
**Severidad:** 🟠 ALTA

**Descripción:** El login del portal acepta `tenant_id` del body del request:
```python
user = db.get_client_user_by_email(email, tenant_id=body.tenant_id)
```

Si `body.tenant_id` es `None` (default), busca en TODOS los tenants. Un atacante que conozca un email puede:
1. Hacer login sin especificar tenant → busca globalmente
2. Si el usuario existe en otro tenant, autenticarse ahí

**Estado parcial:** Los endpoints de email processing ya fueron parchados (VULN-13). Este no.

**Fix propuesto:**
```python
# Siempre requerir tenant_id explícito o derivarlo de la sesión
if body.tenant_id is None:
    raise HTTPException(422, "tenant_id es obligatorio para el login del portal.")
user = db.get_client_user_by_email(email, tenant_id=body.tenant_id)
```

---

### A-02 — Onboarding: CIEC, e.firma y Contraseñas de ERP en Plaintext

**Archivo:** `b2b_ai/onboarding/api.py:49-69`
**Severidad:** 🟠 ALTA

**Descripción:** El wizard de onboarding acepta credenciales sensibles como campos Pydantic:
```python
class SATCredentialsBody(BaseModel):
    ciec: str  # Clave CIEC del SAT
    efirma_certificado: Optional[str]  # .cer file
    efirma_llave: Optional[str]  # .key file (private key!)
    efirma_password: Optional[str]  # Password de la llave privada

class ERPConnectionBody(BaseModel):
    credentials_password: Optional[str]  # Password del ERP
```

No hay evidencia de que estos campos se cifren con `encrypt_field()` antes de persistir. El `webhook_url` y `notif_recipient` están listados como campos que se cifran (en `security.py:14`), pero CIEC, e.firma y passwords de ERP no están mencionados.

**Fix propuesto:**
1. Cifrar TODOS los campos sensibles con `encrypt_field()` antes de guardar en DB
2. Verificar que `db.set_tenant_config()` cifra automáticamente campos sensibles
3. Nunca loggear estos campos (verificar structured_logging.py filter)

---

### A-03 — Rate Limiting No Cubre Endpoints ARCO ni Portal Auth

**Archivo:** `b2b_ai/api/app.py:431-435, 547-561`
**Severidad:** 🟠 ALTA

**Descripción:** El rate limiter exime estas rutas:
```python
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/health", "/metrics", "/static", "/icons", "/manifest.json",
    "/sw.js", "/robots.txt", "/sitemap.xml", "/docs", "/openapi.json",
    "/redoc", "/favicon.ico",
)
```

Los endpoints públicos NO eximidos pero que son críticos:
- `POST /api/v1/arco/solicitud` — acepta datos sin auth, sin rate limit estricto (solo 300/min global)
- `GET /api/v1/arco/datos/{email}` — devuelve PII, sin rate limit
- `POST /portal/auth/login` — brute-force de passwords
- `POST /api/v1/leads` — tiene rate limit por endpoint en `rate_limiter.py:150` (10/min) pero solo si se usa el middleware enterprise

El rate limiter enterprise (`rate_limiter.py`) con límites por endpoint **NO está instalado** en `app.py`. Solo el rate limiter básico de 300/min global está activo.

**Fix propuesto:**
```python
# Instalar el rate limiter enterprise con límites por endpoint
from b2b_ai.api.rate_limiter import install_enterprise_rate_limit
install_enterprise_rate_limit(app)

# Y añadir rate limit específico para portal auth
ENDPOINT_LIMITS["/portal/auth/login"] = 5  # 5 intentos/min
ENDPOINT_LIMITS["/api/v1/arco/"] = 3  # 3 solicitudes/min
```

---

### A-04 — /metrics/prometheus Público: Expone Datos Operativos Sensibles

**Archivo:** `b2b_ai/api/app.py:653-661`
**Severidad:** 🟠 ALTA

**Descripción:** El endpoint de métricas Prometheus es público (sin `require_api_key`):
```python
@app.get("/metrics/prometheus")
def metrics_prometheus():
    """Público, exento de rate-limit y de CORS para que Prometheus pueda scrapearlo sin auth."""
    prom_metrics.set_tenant_usage(db.get_all_usage())
    return PlainTextResponse(prom_metrics.render_prometheus(), ...)
```

Expone:
- Uso por tenant (`db.get_all_usage()`) — permite a un atacante inferir el tamaño de cada tenant
- Métricas operativas del sistema (latencia, error rates)
- Información de infraestructura

En Railway, este endpoint es accesible públicamente si no hay reglas de firewall.

**Fix propuesto:**
```python
# Proteger con IP allowlist o basic auth para Prometheus
@app.get("/metrics/prometheus")
def metrics_prometheus(request: Request):
    # Solo permitir desde IPs de monitoreo
    allowed = os.environ.get("B2B_PROMETHEUS_IPS", "").split(",")
    client_ip = _client_ip(request)
    if allowed and client_ip not in allowed:
        raise HTTPException(403, "Metrics endpoint restricted.")
    ...
```

---

### A-05 — Dashboard SPA sin Autenticación

**Archivo:** `b2b_ai/api/app.py:1127-1132`
**Severidad:** 🟠 ALTA

**Descripción:** El dashboard SPA es accesible sin autenticación:
```python
@app.get("/dashboard/", include_in_schema=False)
def dashboard_spa():
    """Panel gerencial interactivo (HTML+JS vanilla)."""
    return FileResponse(_DASHBOARD_SPA)
```

Si el HTML del dashboard hace llamadas API con credenciales embebidas (cookies, localStorage), cualquier persona con la URL puede acceder al panel.

**Fix propuesto:**
Proteger con autenticación (session cookie o redirect a login):
```python
@app.get("/dashboard/", include_in_schema=False)
def dashboard_spa(request: Request):
    # Verificar sesión activa
    token = request.cookies.get("session_token")
    if not token or not db.get_portal_session(token):
        return RedirectResponse("/portal/")
    return FileResponse(_DASHBOARD_SPA)
```

---

### A-06 — Portal Magic Link: Token Devuelto en Respuesta HTTP en Dev

**Archivo:** `b2b_ai/api/portal.py:232-240`
**Severidad:** 🟠 ALTA

**Descripción:** En entornos de desarrollo, el magic link token se devuelve en la respuesta HTTP:
```python
_dev_envs = {"dev", "development", "test", "testing", "local"}
if os.environ.get("B2B_ENV", "").strip().lower() in _dev_envs:
    resp["dev_token"] = token
```

Si `B2B_ENV` se configura incorrectamente como "development" en producción (error humano común), cualquier magic link token se devuelve directamente al atacante, bypassing el envío por email.

**Fix propuesto:**
```python
# Nunca devolver token en la respuesta. En dev, loggearlo a consola.
if _is_dev_env():
    logging.getLogger("portal").info(
        "MAGIC-LINK dev_token=%s (dev only, NEVER in response)", token)
```

---

### A-07 — Encrypt Field Degrada Silenciosamente a Plaintext

**Archivo:** `b2b_ai/api/security.py:161-172`
**Severidad:** 🟠 ALTA

**Descripción:** `encrypt_field()` devuelve el valor en plaintext si la clave no está configurada:
```python
def encrypt_field(value: str) -> str:
    if not value or value.startswith(_CIPHER_PREFIX):
        return value
    c = _cipher()
    if c is None:
        return value  # ← devuelve plaintext sin error
```

Si `B2B_ENCRYPTION_KEY` se pierde o no se configura en un despliegue, TODOS los campos "cifrados" se guardan en plaintext sin ninguna advertencia. El `create_app()` falla si la key no está, pero `encrypt_field()` se puede llamar desde otros puntos sin esa verificación.

**Fix propuesto:**
```python
def encrypt_field(value: str) -> str:
    if not value or value.startswith(_CIPHER_PREFIX):
        return value
    c = _cipher()
    if c is None:
        raise RuntimeError(
            "B2B_ENCRYPTION_KEY not configured. Cannot encrypt sensitive field. "
            "Set the env var or use encrypt_field_degraded() for explicit opt-in.")
    ...
```

---

### A-08 — FIEL Password Hardcodeado en Ejemplo/Tests

**Archivo:** `b2b_ai/features/declaraciones/fiel_signer.py:54` y `sat_submitter.py:92`
**Severidad:** 🟠 ALTA

**Descripción:** Password de ejemplo hardcodeado en el docstring y código:
```python
# fiel_signer.py:54
password="password123",

# sat_submitter.py:92
password="password123",
```

Aunque están en docstrings/constructores de ejemplo, si estos se usan como defaults o si un desarrollador copia el patrón, las credenciales FIEL quedarían expuestas. La FIEL es la firma electrónica del SAT — su compromiso permite firmar declaraciones fiscales fraudulentas.

**Fix propuesto:**
```python
# Nunca usar defaults. Siempre requerir password explícito.
password: str  # sin default, requerido
```

---

## HALLAZGOS MEDIOS

### M-01 — SQL Injection Potencial en Migrations (f-string en execute)

**Archivo:** `b2b_ai/db/migration.py:117,185,225`
**Severidad:** 🟡 MEDIA

**Descripción:** F-strings dentro de `execute()`:
```python
cursor = sqlite_conn.execute(f"PRAGMA table_info({table})")  # :117
cur = conn.execute(f"SELECT COUNT(*) FROM {table}")           # :185
rows = conn.execute(f"SELECT * FROM {table}")                 # :225
```

Aunque `table` probablemente viene de una lista interna de tablas (no de input del usuario), el patrón es peligroso. Si en el futuro `table` se deriva de input externo, habría SQL injection.

**Contexto:** `db/db.py:1526` usa f-string pero con allowlist de columnas — ese caso es seguro.

**Fix propuesto:**
```python
# Validar table name contra allowlist conocida
_ALLOWED_TABLES = {"invoices", "tenants", "audit_log", ...}
if table not in _ALLOWED_TABLES:
    raise ValueError(f"Table not in allowlist: {table}")
```

---

### M-02 — JWT Config: MIN_SECRET_LEN = 32 en Auth, pero 16 en Config/Infrastructure

**Archivo:** `b2b_ai/auth/middleware.py:52` vs `b2b_ai/infrastructure/config.py:113`
**Severidad:** 🟡 MEDIA

**Descripción:** Inconsistencia en longitud mínima del JWT secret:
- `auth/middleware.py`: `MIN_SECRET_LEN = 32`
- `infrastructure/config.py`: `validate_jwt_secret` acepta `len(v) < 16`

Si se usa el `Settings` de infrastructure para validar (y no el middleware directamente), se aceptan secrets de 16 caracteres — débiles para HS256.

**Fix propuesto:** Unificar a 32 caracteres en ambos lugares.

---

### M-03 — Rate Limiter Enterprise Definido pero No Instalado

**Archivo:** `b2b_ai/api/rate_limiter.py` (332 líneas) vs `b2b_ai/api/app.py`
**Severidad:** 🟡 MEDIA

**Descripción:** Se implementó un rate limiter enterprise completo (Redis-backed, per-tenant, per-endpoint, per-role) en `rate_limiter.py`, pero `app.py` solo usa el rate limiter básico en memoria (300 req/min global). El enterprise limiter nunca se instala.

Esto significa:
- Los límites por endpoint (10/min para leads, 60/min para process) no están activos
- Los headers `X-RateLimit-*` no se envían
- El rate limiting por tenant no funciona

**Fix propuesto:**
```python
# En create_app(), reemplazar el rate limiter básico con el enterprise:
from b2b_ai.api.rate_limiter import install_enterprise_rate_limit
install_enterprise_rate_limit(app)
```

---

### M-04 — Webhook Subscription: URL del Tenant sin Validación de Esquema Robusta

**Archivo:** `b2b_ai/api/webhooks.py:336-338`
**Severidad:** 🟡 MEDIA

**Descripción:** La suscripción de webhook valida el esquema de forma superficial:
```python
if not sub.url.startswith(("http://", "https://")):
    raise HTTPException(status_code=422, detail="URL inválida.")
```

Pero no usa `_assert_http_scheme()` que SÍ valida contra SSRF (bloquea IPs privadas, localhost, metadata). La URL se guarda y se usa en `retry_deliver()` que SÍ llama a `_assert_http_scheme()` al hacer el POST, pero:
1. La URL se almacena sin validación → se expone en `GET /api/v1/webhooks/subscriptions`
2. Si se cambia `default_post` en el futuro sin la validación, el SSRF se activa

**Fix propuesto:**
```python
# Validar con la misma función que el POST
_assert_http_scheme(sub.url)  # Reutilizar la validación SSRF
tm.set_config(scope, webhook_url=sub.url)
```

---

### M-05 — CSP Permite unsafe-inline para Estilos

**Archivo:** `b2b_ai/api/security_headers.py:33`
**Severidad:** 🟡 MEDIA

**Descripción:** La CSP permite `'unsafe-inline'` para estilos:
```python
"style-src 'self' 'nonce-{nonce}' 'unsafe-inline'; "
```

Aunque `'unsafe-inline'` es ignorado cuando hay un nonce en navegadores modernos (CSP3), en navegadores más viejos (pre-CSP3) permite inyección de CSS que puede extraer datos via side-channels.

**Fix propuesto:** Quitar `'unsafe-inline'` de `style-src` si se usa nonce.

---

### M-06 — Token Blacklist: Cleanup Race Condition

**Archivo:** `b2b_ai/auth/middleware.py:309-313`
**Severidad:** 🟡 MEDIA

**Descripción:** El cleanup de la blacklist ocurre inline en `revoke_token()`:
```python
def revoke_token(self, token: str) -> None:
    ...
    _token_blacklist[jti] = float(exp)
    # Cleanup expired entries
    now = time.time()
    expired = [k for k, v in _token_blacklist.items() if v < now]
    for k in expired:
        _token_blacklist.pop(k, None)
```

En un endpoint de logout concurrente, múltiples hilos iteran y modifican `_token_blacklist` simultáneamente sin lock. Esto puede causar `RuntimeError: dictionary changed size during iteration`.

**Fix propuesto:** Usar `threading.Lock` o delegar a Redis (C-02).

---

### M-07 — Endpoint de Leads Público: Sin Protección Anti-Spam Efectiva

**Archivo:** `b2b_ai/api/app.py:801-812`
**Severidad:** 🟡 MEDIA

**Descripción:** El endpoint de leads es público y solo valida que nombre y email no estén vacíos:
```python
@app.post("/api/v1/leads")
def create_lead(lead: LeadRequest):
    if not lead.nombre.strip() or not lead.email.strip():
        raise HTTPException(422, ...)
    lead_id = db.add_lead(lead.nombre, lead.email, ...)
```

Sin CAPTCHA, honeypot, ni verificación de email, un atacante puede:
1. Inyectar leads falsos masivamente (spam)
2. Inyectar XSS en los campos (nombre/email) si se renderizan en un admin panel

**Fix propuesto:**
```python
# 1. Sanitizar/escapar HTML en todos los campos
# 2. Rate limit estricto (10/min ya está en rate_limiter.py pero no instalado)
# 3. Validar formato de email
# 4. Añadir honeypot field
```

---

### M-08 — Structured Logging: Filtro de Campos Sensibles Incompleto

**Archivo:** `b2b_ai/monitoring/logger.py:56`, `b2b_ai/infrastructure/structured_logging.py:63`
**Severidad:** 🟡 MEDIA

**Descripción:** Los filtros de logging enmascaran `webhook_url` y `notif_recipient`, pero no:
- `ciec` (clave CIEC del SAT)
- `efirma_password`
- `efirma_llave`
- `credentials_password` (password de ERP)
- `password_hash` (no debería loggearse nunca)

**Fix propuesto:** Añadir todos los campos sensibles a la lista de enmascaramiento.

---

### M-09 — CORS: Wildcard Posible con B2B_CORS_ORIGINS=*

**Archivo:** `b2b_ai/api/app.py:523-535`
**Severidad:** 🟡 MEDIA

**Descripción:** El código permite `*` como origen CORS:
```python
_cors_origins_raw = os.environ.get("B2B_CORS_ORIGINS", "").strip()
if _cors_origins_raw:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
```

Si alguien configura `B2B_CORS_ORIGINS=*`, CORS permite cualquier origen. FastAPI/CORSMiddleware con `allow_origins=["*"]` y `allow_credentials=True` es una combinación peligrosa (aunque `allow_credentials` defaults a `false`).

**Fix propuesto:**
```python
if "*" in _cors_origins and _allow_creds:
    raise RuntimeError("CORS: allow_origins='*' with credentials is not allowed.")
```

---

## HALLAZGOS BAJOS

### B-01 — Health Endpoint Expone Conteo de Tenants e Invoices

**Archivo:** `b2b_ai/api/app.py:633-645`
**Severidad:** 🟢 BAJA

**Descripción:** El endpoint `/health` es público y devuelve:
```python
"tenants": len(db.list_tenants()),
"invoices": db.count_invoices(),
```

Esto permite a un atacante inferir el tamaño de la plataforma.

**Fix propuesto:** Quitar datos de negocio del healthcheck público. Mover a `/health/detailed` (que sí requiere auth).

---

### B-02 — B2B_TRUST_PROXY: Doble Implementación Inconsistente

**Archivo:** `b2b_ai/api/app.py:348-366` vs `b2b_ai/api/security_headers.py:50-54`
**Severidad:** 🟢 BAJA

**Descripción:** Dos implementaciones de trust proxy:
- `app.py`: acepta lista de IPs separadas por coma
- `security_headers.py`: acepta solo `"true"` como booleano

Un operador que configure `B2B_TRUST_PROXY=10.0.0.1,10.0.0.2` tendrá:
- Rate limiting correcto (usa la lista de IPs)
- HSTS incorrecto (no se activa porque `"10.0.0.1,10.0.0.2"` != `"true"`)

**Fix propuesto:** Unificar la lógica de trust proxy.

---

### B-03 — OpenAPI/Docs Públicos en Producción

**Archivo:** `b2b_ai/api/app.py:431-435` (eximidos de rate limit)
**Severidad:** 🟢 BAJA

**Descripción:** `/docs` y `/openapi.json` están accesibles públicamente y eximidos de rate limiting. En producción, exponen toda la superficie de la API, facilitando el descubrimiento de endpoints.

**Fix propuesto:**
```python
# Deshabilitar docs en producción
if not _is_dev_env():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
```

---

### B-04 — BCRYPT_ROUNDS Configurable por Env (Posible Degradación)

**Archivo:** `b2b_ai/auth/users.py:26`
**Severidad:** 🟢 BAJA

**Descripción:**
```python
BCRYPT_ROUNDS = int(os.environ.get("B2B_BCRYPT_ROUNDS", "12"))
```

Si un atacante obtiene acceso a las variables de entorno, puede reducir `BCRYPT_ROUNDS` a 4, haciendo el brute-force de passwords trivialmente rápido.

**Fix propuesto:** Hardcodear el mínimo (12) y solo permitir incrementar:
```python
BCRYPT_ROUNDS = max(12, int(os.environ.get("B2B_BCRYPT_ROUNDS", "12")))
```

---

## VERIFICACIÓN POR CATEGORÍA

### 1. Auth Bypass
| Endpoint | Protegido | Estado |
|----------|-----------|--------|
| `/health` | ❌ | ✅ OK (público por diseño) |
| `/metrics` | ✅ require_api_key | ✅ OK |
| `/metrics/prometheus` | ❌ | ⚠️ Ver A-04 |
| `/health/detailed` | ✅ require_api_key | ✅ OK |
| `/api/v1/invoices/*` | ✅ require_api_key | ✅ OK |
| `/api/v1/leads` | ❌ | ✅ OK (público por diseño, ver M-07) |
| `/api/v1/arco/*` | ❌❌❌ | 🔴 **CRÍTICO** (ver C-01) |
| `/portal/auth/*` | ❌ (login público) | ⚠️ Ver A-01 |
| `/portal/invoices/*` | ✅ require_user | ✅ OK |
| `/dashboard/` | ❌ | ⚠️ Ver A-05 |
| Todos los routers montados vía `include_router` | ✅ require_api_key | ✅ OK |
| Webhook billing | ❌ (usa firma HMAC) | ✅ OK (ver C-03 para receiver) |

### 2. JWT
- ✅ Tokens con JTI único (`secrets.token_urlsafe`)
- ✅ Blacklist implementada (ver C-02 para problema de persistencia)
- ✅ Refresh token rotation (VULN-12: revoca el viejo antes de emitir nuevo)
- ✅ TTLs configurables por env (access=30min, refresh=7d, reset=1h)
- ✅ Secret mínimo 32 chars enforced en middleware
- ⚠️ Inconsistencia con config.py (ver M-02)

### 3. Multi-tenant
- ✅ `tenant_id` se deriva del token/API key en la mayoría de endpoints
- ✅ `_scope(auth_info)` siempre prioriza el token
- ⚠️ Portal login acepta `tenant_id` del body (ver A-01)
- ✅ ARCO endpoints NO son multi-tenant (son públicos) — ver C-01
- ✅ Webhook email: tenant del token, no del body (VULN-13 ya parchado)

### 4. Inyección
- ✅ SQL: La mayoría de queries usa parámetros (? placeholders)
- ⚠️ f-strings en migrations (ver M-01) — bajo riesgo actual
- ✅ Path traversal: `_resolve_local_path()` resuelve symlinks y valida contra roots
- ✅ SSRF: `_assert_http_scheme()` bloquea IPs privadas y localhost (VULN-08)
- ✅ Upload: solo .xml/.pdf permitidos
- ⚠️ Leads: sin sanitización HTML (ver M-07)

### 5. Secrets
- ✅ No hay secretos hardcodeados en código de producción
- ✅ JWT secret se lee de env, falla en prod si no está
- ⚠️ Password de ejemplo en docstrings FIEL (ver A-08)
- ✅ API key comparison es constant-time (`hmac.compare_digest`)
- ✅ Logging enmascara webhook_url y notif_recipient
- ⚠️ Filtro de logging incompleto (ver M-08)

### 6. Rate Limiting
- ✅ Rate limiter básico activo (300/min global)
- ⚠️ Enterprise limiter implementado pero NO instalado (ver M-03)
- ⚠️ Límites por endpoint no activos (ver A-03)
- ✅ Leads tiene límite definido (10/min) pero no activo

### 7. CORS
- ✅ Por defecto CORS desactivado (más seguro)
- ✅ Headers explícitos, no wildcard por defecto
- ⚠️ Wildcard posible via env (ver M-09)
- ✅ `allow_credentials` default `false`

### 8. CSP/HSTS
- ✅ CSP activa con nonce-based scripts
- ✅ HSTS activo por defecto (VULN-07 ya parchado)
- ✅ X-Frame-Options: DENY
- ✅ X-Content-Type-Options: nosniff
- ✅ Referrer-Policy: strict-origin-when-cross-origin
- ⚠️ `unsafe-inline` en styles (ver M-05)

### 9. Encryption at Rest
- ✅ AES-GCM con `cryptography` library
- ✅ `B2B_ENCRYPTION_KEY` requerido en producción (fail-fast)
- ⚠️ `encrypt_field()` degrada silenciosamente (ver A-07)
- ⚠️ CIEC/e.firma/ERP passwords no verificados como cifrados (ver A-02)
- ✅ Prefijo `enc1:` identifica valores cifrados

### 10. Webhook Signatures
- ✅ `billing/api.py`: verifica contra `raw_body` (correcto)
- 🔴 `billing/webhook_receiver.py`: verifica contra JSON re-serializado (ver C-03)
- ✅ `hmac.compare_digest` para comparación (previene timing attacks)
- ✅ Sin secret → siempre rechaza (nunca bypass)
- ✅ Conekta: formato `hmac_sha256=<hash>,t=<timestamp>` parseado correctamente
- ✅ Stripe: formato `t=<ts>,v1=<sig>` parseado correctamente

---

## PRIORIDAD DE REMEDIACIÓN

1. **C-01** — Proteger endpoints ARCO (inmediato, datos PII expuestos)
2. **C-02** — Mover blacklist JWT a Redis (antes de multi-worker en producción)
3. **C-03** — Fix webhook receiver signature verification
4. **A-01** — Fix portal login tenant_id
5. **A-02** — Cifrar credenciales onboarding
6. **A-03/A-04** — Rate limiting y métricas
7. **A-05** — Proteger dashboard
8. **A-06** — Quitar dev_token de respuesta
9. **A-07** — encrypt_field fail-fast
10. **M-*** — Hardening progresivo
