# 🔥 AUDITORÍA DE DESTRUCCIÓN — SEGURIDAD
## likida-ai-enterprise

**Fecha:** 2026-08-01  
**Método:** Revisión estática ofensiva del código fuente completo (~411 archivos Python)  
**Objetivo:** Encontrar vulnerabilidades que tirarían el software en producción con clientes reales

---

## RESUMEN EJECUTIVO

| Severidad | Cantidad | Descripción |
|-----------|----------|-------------|
| 🔴 CRÍTICA | 4 | XXE, auth bypass multi-tenant, JWT sin revocación, session token en URL |
| 🟠 ALTA | 5 | Sin rate limit en auth, cookie sin secure flag, HSTS off por defecto, SSRF en webhooks, encryption at rest opcional |
| 🟡 MEDIA | 5 | CSP unsafe-inline, CORS allow_headers=*, refresh token sin blacklist, tenant_id del body sin validar, sesión portal 30 días |
| 🔵 BAJA | 3 | FIEL password en env, f-string en LIMIT queries, sin Content-Length en chunked |

**Total: 17 vulnerabilidades**

---

## 🔴 VULNERABILIDADES CRÍTICAS

### VULN-01: XXE (XML External Entity) en Parser de CFDI

**Severidad:** CRÍTICA (CVSS ~9.8)  
**CWE:** CWE-611 (Improper Restriction of XML External Entity Reference)

**Ataque:** Un atacante sube un CFDI XML malicioso con entidades externas que leen archivos del servidor (`/etc/passwd`, `.env`, claves FIEL), hacen SSRF a la red interna, o causan denial of service con "billion laughs":

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
  <!ENTITY xxe2 SYSTEM "http://169.254.169.254/latest/meta-data/">
]>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  Total="100" Version="4.0">
  <cfdi:Emisor Nombre="&xxe;" Rfc="XAXX010101000"/>
</cfdi:Comprobante>
```

**Código vulnerable:**
```python
# b2b_ai/cfdi/parser.py:86
def parse_cfdi(xml_path):
    # ...
    try:
        tree = etree.parse(xml_path)  # ⚠️ SIN protección XXE
    except etree.XMLSyntaxError as e:
        raise CFDIError(f"XML mal formado: {e}") from e
```

`lxml.etree.parse()` por defecto procesa entidades externas, DTDs y carga URLs remotas. Esto permite:
- Lectura de archivos del servidor (FIEL keys, `.env`, DB credentials)
- SSRF a metadatos de cloud (AWS/GCP/Railway)
- Denial of Service (billion laughs, entity expansion)

**Fix:**
```python
# b2b_ai/cfdi/parser.py
from lxml import etree

def _safe_xml_parser():
    """Parser XML seguro: deshabilita entidades externas y DTDs."""
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
    )
    return parser

def parse_cfdi(xml_path):
    if not os.path.exists(xml_path):
        raise OSError(f"Archivo no encontrado: {xml_path}")
    try:
        tree = etree.parse(xml_path, parser=_safe_xml_parser())
    except etree.XMLSyntaxError as e:
        raise CFDIError(f"XML mal formado: {e}") from e
```

Alternativa: usar `defusedxml` como wrapper seguro.

---

### VULN-02: Auth Bypass en Multi-Tenant Router (Fallback a `None`)

**Severidad:** CRÍTICA (CVSS ~9.1)  
**CWE:** CWE-306 (Missing Authentication for Critical Function)

**Ataque:** El router de multi-tenancy usa un fallback que permite acceso sin autenticación:

```python
# b2b_ai/features/multi_tenant/routes.py:157
auth_dep = require_api_key or (lambda: None)
```

Si `require_api_key` es `None` (lo cual puede ocurrir si el router se construye sin pasar el dependency), **TODOS los endpoints** de multi-tenancy quedan sin auth:
- `POST /api/v1/tenants` — Crear tenants
- `GET /api/v1/tenants` — Listar todos los tenants
- `GET /api/v1/tenants/{id}` — Ver detalles de cualquier tenant
- `PUT /api/v1/tenants/{id}` — Modificar cualquier tenant
- `DELETE /api/v1/tenants/{id}` — Eliminar tenants
- `POST /api/v1/tenants/{id}/suspend` — Suspender tenants

**Patrón peligroso replicado en otros routers:**
```python
# b2b_ai/features/email_processing/routes.py:92
auth_dep = require_api_key or (lambda: None)
```

**Fix:**
```python
def build_multi_tenant_router(db, require_api_key):
    if require_api_key is None:
        raise ValueError(
            "require_api_key es obligatorio. "
            "Nunca construir el router sin dependencia de auth."
        )
    auth_dep = require_api_key
    # ...
```

---

### VULN-03: JWT Access Tokens No Se Revocan Tras Logout

**Severidad:** CRÍTICA (CVSS ~8.2)  
**CWE:** CWE-613 (Insufficient Session Expiration)

**Ataque:** Un usuario hace logout, pero su access token sigue siendo válido hasta que expire (30 min por defecto). Un atacante que roba el token (XSS, log compartido, proxy) puede seguir usándolo:

```python
# b2b_ai/auth/middleware.py:38
ACCESS_TTL = int(os.environ.get("B2B_JWT_ACCESS_TTL", "1800"))  # 30 min
REFRESH_TTL = int(os.environ.get("B2B_JWT_REFRESH_TTL", "604800"))  # 7 días
```

**El logout solo invalida la sesión del portal (cookie), NO los JWTs:**
```python
# b2b_ai/api/portal.py:257-260
@router.post("/auth/logout")
def portal_logout(user: dict = Depends(require_user)):
    db.delete_portal_session(user["token"])  # Solo portal session
    return {"ok": True}
    # ⚠️ No invalida el access_token ni el refresh_token JWT
```

**No hay ningún mecanismo de blacklist/revocación de tokens:**
```
$ grep -rn "blacklist\|revoke\|blocklist" b2b_ai/ --include="*.py"
# (resultados vacíos)
```

**Impacto:** Un token robado es válido hasta su expiración. En un despacho contable, 30 minutos es tiempo suficiente para extraer toda la información fiscal de un tenant.

**Fix:**
```python
# Agregar tabla de blacklist
# b2b_ai/db/models.py
"""
CREATE TABLE IF NOT EXISTS token_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# En el middleware, verificar blacklist
def _require_auth(self, request, authorization=None):
    # ... existing decode logic ...
    claims = self.decode(token)
    jti = claims.get("jti") or f"{claims['sub']}:{claims.get('iat')}"
    if self._db.is_token_blacklisted(jti):
        raise HTTPException(401, "Token revocado.")
    # ...

# En logout, agregar el token a blacklist
def revoke_token(self, token: str):
    claims = self.decode(token)
    jti = claims.get("jti") or f"{claims['sub']}:{claims.get('iat')}"
    exp = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    self._db.blacklist_token(jti, exp.isoformat())
```

---

### VULN-04: Session Token Expuesto en URL Query Parameter

**Severidad:** CRÍTICA (CVSS ~7.5)  
**CWE:** CWE-598 (Use of GET Request Method With Sensitive Query Strings)

**Ataque:** El portal acepta el token de sesión como query parameter `?token=`:

```python
# b2b_ai/portal/routes.py:99-108
def _resolve_user(db, request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        token = request.query_params.get("token")  # ⚠️ Token en URL
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
```

**Impactos:**
1. **Browser history:** El token queda en el historial del navegador
2. **Server logs:** El token aparece en logs de acceso (nginx, uvicorn, proxies)
3. **Referrer header:** El token se envía en el header `Referer` al navegar a otros sitios
4. **Shared URLs:** El usuario puede compartir la URL (con token) accidentalmente
5. **Proxy logs:** CDNs y proxies registran las URLs completas

**Fix:**
```python
def _resolve_user(db, request):
    """Resuelve usuario solo desde cookie HttpOnly o header Authorization."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    # ⚠️ ELIMINAR: token = request.query_params.get("token")
    if not token:
        return None
    # ...
```

---

## 🟠 VULNERABILIDADES ALTAS

### VULN-05: Sin Rate Limiting Específico en Endpoints de Autenticación

**Severidad:** ALTA (CVSS ~7.5)  
**CWE:** CWE-307 (Improper Restriction of Excessive Authentication Attempts)

**Ataque:** El rate limiter global (300 req/min por IP) protege contra DDoS pero NO contra brute-force de login. Un atacante puede hacer ~300 intentos de login por minuto desde una sola IP:

```python
# b2b_ai/api/app.py:544-548
if _rl_enabled:
    @app.middleware("http")
    async def _rate_limit_mw(request: Request, call_next):
        path = request.url.path
        if path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
            return await call_next(request)
        key = (_client_ip(request), path)
        # 300 req/min por (IP, ruta) — suficiente para brute-force
```

Además, el login del portal HTML no tiene ningún rate limit:
```python
# b2b_ai/portal/routes.py:240-256
def login_submit(request, email, password):
    em = (email or "").strip().lower()
    user = db.get_client_user_by_email(em)
    if user is None or not _check_password(password, user["password_hash"]):
        return RedirectResponse(url="/portal/login?error=1", status_code=302)
    # ⚠️ Sin rate limit, sin delay, sin account lockout
```

**Fix:**
```python
# Rate limit específico para login (por IP + email)
from collections import defaultdict
import time

class LoginRateLimiter:
    def __init__(self, max_attempts=5, window=300):  # 5 intentos / 5 min
        self._attempts = defaultdict(list)
        self.max_attempts = max_attempts
        self.window = window

    def check(self, key: str) -> bool:
        now = time.monotonic()
        self._attempts[key] = [t for t in self._attempts[key] if now - t < self.window]
        if len(self._attempts[key]) >= self.max_attempts:
            return False
        self._attempts[key].append(now)
        return True

_login_limiter = LoginRateLimiter()

# En login_submit:
if not _login_limiter.check(f"{ip}:{em}"):
    return RedirectResponse(url="/portal/login?error=rate_limit", status_code=429)
```

---

### VULN-06: Cookie de Portal Sin Flag `Secure`

**Severidad:** ALTA (CVSS ~7.1)  
**CWE:** CWE-614 (Sensitive Cookie in HTTPS Session Without 'Secure' Attribute)

**Ataque:** La cookie de sesión del portal no tiene el flag `secure`:

```python
# b2b_ai/portal/routes.py:254-255
resp.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL_DAYS * 86400,
                httponly=True, samesite="lax", path="/")
# ⚠️ Falta: secure=True
```

Sin `secure=True`, la cookie se envía sobre conexiones HTTP (no cifradas), lo que permite:
- **Man-in-the-Middle:** Interceptar la cookie en redes WiFi públicas
- **Session hijacking:** Robar la sesión del portal contable

**Fix:**
```python
resp.set_cookie(
    COOKIE_NAME, token,
    max_age=SESSION_TTL_DAYS * 86400,
    httponly=True,
    secure=True,      # ← Solo enviar sobre HTTPS
    samesite="lax",
    path="/"
)
```

---

### VULN-07: HSTS Deshabilitado por Defecto

**Severidad:** ALTA (CVSS ~6.5)  
**CWE:** CWE-319 (Cleartext Transmission of Sensitive Information)

**Ataque:** HSTS solo se activa si `B2B_HSTS_ALWAYS=true` o si la petición ya viene por HTTPS:

```python
# b2b_ai/api/security_headers.py:67-68
self.hsts_enabled = self.hsts_always or (
    os.environ.get("B2B_HSTS", "").lower() == "")
```

Sin HSTS:
1. **SSL stripping:** Un atacante en la red puede downgrade la conexión a HTTP
2. **Cookie theft:** Las cookies se envían en claro
3. **Credential theft:** Login/password del portal contable van en texto plano

**Fix:** En producción, HSTS debe estar SIEMPRE activo:
```python
# En deploy de producción (Railway, Docker), setear:
# B2B_HSTS_ALWAYS=true
# O mejor: forzar en código para producción
self.hsts_enabled = True  # En producción siempre
```

---

### VULN-08: SSRF en Webhook URL (Red Interna Accesible)

**Severidad:** ALTA (CVSS ~7.2)  
**CWE:** CWE-918 (Server-Side Request Forgery)

**Ataque:** Aunque `_assert_http_scheme` bloquea `file://`, un atacante con acceso al config de un tenant puede configurar `webhook_url` a direcciones internas:

```python
# b2b_ai/api/webhooks.py:86-92
def _assert_http_scheme(url: str) -> None:
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Esquema de URL no permitido: {scheme!r}")
    # ⚠️ No bloquea: http://169.254.169.254 (cloud metadata)
    # ⚠️ No bloquea: http://localhost:5432 (PostgreSQL)
    # ⚠️ No bloquea: http://10.0.0.1 (red interna)
```

**Escenarios de ataque:**
- `webhook_url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"` → Robar credenciales AWS
- `webhook_url = "http://localhost:6379/"` → Interactuar con Redis sin auth
- `webhook_url = "http://10.0.0.5:9200/_search"` → Acceder a Elasticsearch interno

**Fix:**
```python
import ipaddress
from urllib.parse import urlparse

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Cloud metadata
    ipaddress.ip_network("127.0.0.0/8"),      # Localhost
]

def _assert_safe_webhook_url(url: str) -> None:
    _assert_http_scheme(url)
    parsed = urlparse(url)
    import socket
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
    except (socket.gaierror, ValueError):
        raise ValueError(f"No se pudo resolver: {parsed.hostname}")
    for range_ in _PRIVATE_RANGES:
        if ip in range_:
            raise ValueError(f"URL en red privada no permitida: {url}")
```

---

### VULN-09: Encryption at Rest es Opt-in (Datos Sensibles en Claro)

**Severidad:** ALTA (CVSS ~6.5)  
**CWE:** CWE-311 (Missing Encryption of Sensitive Data)

**Ataque:** Sin `B2B_ENCRYPTION_KEY`, los datos sensibles se guardan en texto plano:

```python
# b2b_ai/api/security.py:141-150
def _encryption_key() -> bytes | None:
    raw = os.environ.get("B2B_ENCRYPTION_KEY", "").strip()
    if not raw or len(raw) < 16:
        return None  # ⚠️ Sin clave → sin cifrado
    return hashlib.sha256(raw.encode("utf-8")).digest()

def encrypt_field(value: str) -> str:
    c = _cipher()
    if c is None:
        return value  # ⚠️ Devuelve en claro si no hay clave
```

**Datos afectados:**
- `webhook_url` (URLs de integración)
- `notif_recipient` (emails de notificación)
- `whatsapp_token` (tokens de WhatsApp Business)
- Credenciales FIEL/CSD (`FIEL_PASSWORD` en env var)

**Fix:**
```python
# En startup, FALLAR si no hay clave en producción
def check_encryption_config():
    if not _is_dev_env() and not os.environ.get("B2B_ENCRYPTION_KEY"):
        raise RuntimeError(
            "B2B_ENCRYPTION_KEY es obligatoria en producción. "
            "Genera una con: openssl rand -hex 32"
        )
```

---

## 🟡 VULNERABILIDADES MEDIAS

### VULN-10: CSP Permite `unsafe-inline` (XSS Risk)

**Severidad:** MEDIA (CVSS ~6.1)  
**CWE:** CWE-79 (Cross-site Scripting)

```python
# b2b_ai/api/security_headers.py:28-39
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    # ⚠️ unsafe-inline permite XSS si hay inyección en templates
    "style-src 'self' 'unsafe-inline'; "
    # ...
)
```

**Impacto:** Si algún template Jinja2 tiene una inyección (XSS via `{{ variable }}` sin escape), CSP no la bloquea.

**Fix:** Migrar a `nonce`-based CSP o eliminar scripts inline.

---

### VULN-11: CORS `allow_headers=["*"]` Cuando Está Habilitado

**Severidad:** MEDIA (CVSS ~5.3)

```python
# b2b_ai/api/app.py:526-531
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],  # ⚠️ Permite cualquier header
    allow_credentials=_allow_creds,
)
```

Con `allow_credentials=True` y `allow_headers=["*"]`, un sitio malicioso puede enviar requests autenticados con headers custom.

**Fix:** Especificar headers explícitos:
```python
allow_headers=["X-API-Key", "Authorization", "Content-Type"],
```

---

### VULN-12: Refresh Tokens Sin Blacklist (Reusables Post-Logout)

**Severidad:** MEDIA (CVSS ~5.9)

```python
# b2b_ai/auth/users.py:163-178
def refresh_token(self, token: str) -> Dict[str, Any]:
    claims = self.jwt.decode(token)
    if claims.get("type") != "refresh":
        raise InvalidTokenError("No es un token de refresco.")
    user = self.db.get_client_user(user_id)
    if user is None:
        raise InvalidTokenError("Usuario inexistente.")
    return self._session(user)  # ⚠️ Genera nuevos tokens sin invalidar el refresh
```

**Ataque:** Un refresh token robado puede usarse para generar nuevos access tokens indefinidamente (7 días). Hacer logout no lo invalida.

**Fix:** Implementar blacklist de refresh tokens + invalidación en logout.

---

### VULN-13: Tenant ID Aceptado del Request Body Sin Validar

**Severidad:** MEDIA (CVSS ~5.3)  
**CWE:** CWE-285 (Improper Authorization)

```python
# b2b_ai/features/email_processing/routes.py:50-56
class ScanRequest(BaseModel):
    tenant_id: str = Field(default="default", description="Tenant ID")
    emails: List[Dict[str, Any]] = Field(...)
```

El `tenant_id` viene del body del request, no del token autenticado. Un usuario puede enviar datos a cualquier tenant.

**Fix:** Siempre derivar `tenant_id` del token de autenticación, nunca del request body.

---

### VULN-14: Portal Session TTL Excesivo (30 días)

**Severidad:** MEDIA (CVSS ~4.7)

```python
# b2b_ai/portal/routes.py:43
SESSION_TTL_DAYS = 30  # ⚠️ 30 días para datos fiscales sensibles
```

Para una aplicación que maneja CFDIs, RFC, y datos contables, 30 días es excesivo. Una sesión robada es válida por un mes.

**Fix:** Reducir a 8 horas (una jornada laboral) o usar sliding window:
```python
SESSION_TTL_HOURS = 8
```

---

## 🔵 VULNERABILIDADES BAJAS

### VULN-15: FIEL Password Almacenado en Variable de Entorno

**Severidad:** BAJA (CVSS ~3.3)

```python
# b2b_ai/integrations/firmas/fiel_adapter.py:21
fiel_password=os.environ.get("FIEL_PASSWORD", ""),
```

Las variables de entorno son visibles en:
- `/proc/self/environ` (Linux)
- `ps eww` (algunos sistemas)
- Logs de Docker/Railway
- Crash reports

**Fix:** Usar un secret manager (Vault, AWS Secrets Manager) o al menos cifrar el password con la `B2B_ENCRYPTION_KEY`.

---

### VULN-16: f-string en Queries SQL (LIMIT)

**Severidad:** BAJA (CVSS ~2.0)

```python
# b2b_ai/db/db.py:414
q += f" ORDER BY id DESC LIMIT {int(limit)}"
```

Aunque `int(limit)` previene inyección SQL directa, es una mala práctica. Si el código se refactoriza y se quita el `int()`, se convierte en SQL injection.

**Fix:** Usar parámetros preparados:
```python
q += " ORDER BY id DESC LIMIT ?"
params.append(int(limit))
```

---

### VULN-17: Size Limit Solo Verifica Content-Length Header

**Severidad:** BAJA (CVSS ~3.1)

```python
# b2b_ai/api/middleware.py:66-68
content_length = request.headers.get("content-length")
if content_length is not None:
    # ⚠️ Solo verifica si el header existe
    # Transfer-Encoding: chunked no tiene Content-Length
```

Un atacante puede usar `Transfer-Encoding: chunked` para evadir el límite de 10MB.

**Fix:** Verificar también el tamaño del body leído:
```python
# Leer el body con límite
body = await request.body()
if len(body) > _limit:
    return JSONResponse(status_code=413, content={"detail": "Too large"})
```

---

## HALLAZGOS POSITIVOS ✅

El código tiene buenas prácticas implementadas:

1. **JWT secret sin hardcodear** — Se genera efímero en dev, falla en prod sin env
2. **bcrypt con 12 rounds** — Password hashing robusto
3. **Password policy fuerte** — 10+ chars, mayúscula, minúscula, dígito, especial
4. **Comparación constante (hmac.compare_digest)** — Anti timing attack en API keys y JWT
5. **Tenant isolation en queries** — La DB filtra por `tenant_id` en la mayoría de queries
6. **Upload extension validation** — Solo acepta `.xml` y `.pdf`
7. **Cifrado AES-GCM at rest** — Implementado (aunque opt-in)
8. **Audit logging** — Registra todas las mutaciones
9. **Rate limiting global** — 300 req/min por IP (aunque insuficiente para auth)
10. **Security headers** — HSTS, X-Frame-Options, nosniff, CSP (aunque con gaps)
11. **SSRF parcial** — Bloquea `file://` en webhooks (pero no IPs privadas)
12. **Request size limit** — 10MB máximo (aunque solo por Content-Length)

---

## PLAN DE REMEDIACIÓN PRIORITIZADO

| Prioridad | Vuln | Esfuerzo | Impacto |
|-----------|------|----------|---------|
| P0 (HOY) | VULN-01 XXE | 5 min | Elimina RCE/file read |
| P0 (HOY) | VULN-02 Auth bypass | 10 min | Elimina acceso no autenticado |
| P0 (HOY) | VULN-04 Token en URL | 2 min | Elimina session leak |
| P1 (SEMANA) | VULN-03 JWT revocación | 2-4h | Elimina token reuse |
| P1 (SEMANA) | VULN-05 Rate limit auth | 1-2h | Mitiga brute-force |
| P1 (SEMANA) | VULN-06 Cookie secure | 1 min | Elimina cookie leak |
| P1 (SEMANA) | VULN-08 SSRF | 1h | Elimina red interna access |
| P2 (MES) | VULN-07 HSTS | 30 min | Elimina SSL stripping |
| P2 (MES) | VULN-09 Encryption | 1h | Cifra datos sensibles |
| P2 (MES) | VULN-10-14 | 2-4h | Hardening general |

---

## COMANDOS DE VERIFICACIÓN

```bash
# VULN-01: Verificar que lxml parsea con entidades externas
python3 -c "
from lxml import etree
xml = b'<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><root>&xxe;</root>'
tree = etree.fromstring(xml)
print(tree.text)  # Si imprime contenido de /etc/passwd → vulnerable
"

# VULN-02: Verificar fallback de auth
grep -rn "lambda: None" b2b_ai/ --include="*.py"

# VULN-03: Verificar que no hay blacklist
grep -rn "blacklist\|revoke\|blocklist" b2b_ai/ --include="*.py"

# VULN-06: Verificar cookie sin secure
grep -rn "set_cookie" b2b_ai/ --include="*.py"
```

---

*Auditoría generada por destrucción ofensiva del código fuente. Cada vulnerabilidad incluye el código exacto, el vector de ataque, y el fix propuesto.*
