# API Reference — Likida AI Enterprise (Enterprise)

Referencia técnica completa de la API REST del agente contable enterprise
(Likida / Likida AI Enterprise). Toda la documentación interactiva está disponible en la
instancia en ejecución:

- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- OpenAPI JSON (contract): `GET /openapi.json`
- Archivo del contrato en el repo: `docs/openapi.json` (generado con
  `scripts/generate_openapi.py` desde la app real, nunca a mano).

Versión documentada: **1.0.0** · Base URL de producción: `https://api.b2b-ai.local`

Este documento se genera en paralelo con `docs/openapi.json`: el contrato
OpenAPI es la fuente de verdad para endpoints, schemas y parámetros; este
documento añade la guía de uso, autenticación, errores y ejemplos.

---

## 1. Authentication

La API usa **tres esquemas de autenticación** según la superficie:

| Esquema | Header | Dónde | Cómo se obtiene |
|---|---|---|---|
| **API Key** | `X-API-Key` | Endpoints `/api/v1/*`, `/api/v2/*` y legacy | Tabla `api_keys` (multi-tenant) o env `B2B_API_KEY` (key de servicio) |
| **JWT Bearer** | `Authorization: Bearer <token>` | `/api/v1/auth/*` y `/api/v1/tenants/{id}/users/*` | `POST /api/v1/auth/login` |
| **Portal Bearer** | `Authorization: Bearer <token>` o `X-Portal-Token` | `/portal/*` | `POST /portal/auth/login` (o magic-link) |

### 1.1 API Key (mayoría de endpoints)

```http
X-API-Key: sk_live_xxxxxxxxxxxxxxxx
```

**Resolución** (`b2b_ai/api/auth.py`):

1. Si la key coincide con la env `B2B_API_KEY` → identidad `service`
   (`tenant_id=None`). Para dev, pruebas y operación del sistema.
2. Si la key existe en la tabla `api_keys` → identidad del `tenant_id` y nombre
   asociados.

**Alcance de tenant (hard-scoping):** una key de tenant **nunca** puede ver u
operar sobre otro tenant, aunque el cliente mande `tenant_id` en la query. Solo
la key de servicio puede pedir un tenant arbitrario o todos. Un tenant
**bloqueado** recibe `403` en cualquier endpoint `/api/v1/*` o `/api/v2/*`.

**Anti-fuerza bruta:** los intentos fallidos se comparan en tiempo constante
(`hmac.compare_digest`) y se auditan en `audit_log` (se guarda solo la longitud
y un hash corto de la key, nunca la key completa).

### 1.2 JWT (auth enterprise)

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email": "admin@despacho.com", "password": "supersecreto", "tenant_id": 1}
```

Respuesta (tokens de acceso y refresco):

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "expires_in": 3600,
  "user": {"id": 1, "email": "admin@despacho.com", "role": "admin"},
  "tenant_id": 1
}
```

Usa el access token en `Authorization: Bearer <access_token>`. Cuando caduque,
refresca con `POST /api/v1/auth/refresh` y `{"refresh_token": "..."}`.

**Roles:** `admin`, `contador`, `lectura` (RBAC). Solo `admin` gestiona
usuarios (`/api/v1/tenants/{id}/users/*`).

### 1.3 Portal (cliente final)

```http
POST /portal/auth/login
Content-Type: application/json

{"email": "cliente@despacho.com", "password": "supersecreto"}
```

Respuesta:

```json
{
  "token": "opaco-aleatorio-64car",
  "user": {"id": 3, "email": "cliente@despacho.com", "name": "Cliente", "role": "cliente"},
  "tenant_id": 1,
  "expires_at": "2026-08-30T21:00:00"
}
```

Sesiones TTL 30 días. Envía el token en `Authorization: Bearer <token>` o en
el header `X-Portal-Token`.

### 1.4 Errores de autenticación

| Código | Significado |
|---|---|
| `401` | Falta `X-API-Key` / token inválido o caducado |
| `403` | Tenant bloqueado, rol sin permiso, o key sin tenant en endpoint que lo exige |

---

## 2. Rate limiting

### 2.1 Por IP (capa global, `/api/v1/*`)

Ventana deslizante por `(IP, ruta)`. Por defecto **300 peticiones por minuto**
por IP+ruta. Configurable:

| Env | Default | Efecto |
|---|---|---|
| `B2B_RATE_LIMIT` | `on` | `off` desactiva el limitador |
| `B2B_RATE_LIMIT_PER_MIN` | `300` | Límite por minuto por (IP, ruta) |

Al exceder el límite se devuelve:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{"detail": "Demasiadas peticiones. Intenta en un minuto."}
```

**Exentos del rate limit** (healthchecks, monitoreo y documentación):
`/health`, `/health/detailed`, `/metrics`, `/metrics/prometheus`, `/static/*`,
`/icons/*`, `/manifest.json`, `/sw.js`, `/robots.txt`, `/sitemap.xml`,
`/docs`, `/openapi.json`, `/redoc`, `/favicon.ico`.

**IP real:** por defecto se usa la IP de la conexión (`REMOTE_ADDR`). Solo se
confía en `X-Forwarded-For` si `B2B_TRUST_PROXY` está configurado con IPs de
proxy de confianza (evita el bypass por spoofing de XFF).

### 2.2 Por tenant (capa `/api/v2/*`)

Los endpoints v2 aplican además un **rate limit por tenant** (independiente
del por-IP). Default 300/min, configurable por tenant
(`rate_limit_per_min` en la config del tenant). Al exceder:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
{"detail": "Rate limit por tenant excedido. Reduce el ritmo."}
```

### 2.3 Buenas prácticas

- Backoff exponencial en el cliente: espera `Retry-After` + jitter.
- En lotes (`/api/v2/batch`) usa `async: true` para no quemar cuota en
  síncronos largos.
- El `GET /api/v2/usage` te dice cuántas llamadas llevas en el periodo.

---

## 3. Pagination

- **`limit`**: la mayoría de listados aceptan `limit` (default 100, máx 1000
  en `/api/v1/invoices`; hasta 5000 en `/api/v2/audit`).
- **`offset`**: solo `/api/v2/audit` soporta paginación con `offset`
  (default 0). Es paginación por desplazamiento (no cursor), adecuada para
  volumen bajo/medio.
- La respuesta incluye `count` (número de ítems devueltos en esta página).

Ejemplo:

```http
GET /api/v2/audit?limit=100&offset=200
X-API-Key: sk_live_xxx
```

```json
{"count": 100, "limit": 100, "offset": 200, "audit": [ ... ]}
```

No hay paginación por cursor; para volúmenes grandes usa `/api/v2/export`
(CSV/XLSX/PDF) que soporta hasta 10 000 registros.

---

## 4. Formato de errores

Errores de validación (FastAPI/Pydantic) devuelven `HTTPValidationError`:

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

Errores de negocio devuelven el detalle plano en `detail`:

```json
{"detail": "Factura no encontrada."}
```

### Códigos de error globales

| Código | Significado |
|---|---|
| `400` | Body/petición mal formada |
| `401` | Falta o es inválida la autenticación |
| `403` | Sin permiso / tenant bloqueado / otro tenant |
| `404` | Recurso no encontrado |
| `409` | Conflicto de estado (p. ej. webhook sin URL configurada) |
| `422` | Validación falló (schemas o reglas de negocio: CFDI inválido, URL inválida…) |
| `429` | Rate limit excedido |
| `5xx` | Error de servidor (revisa `/health/detailed`) |

---

## 5. Resumen de endpoints

### 5.1 Públicos (sin auth)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Health check + versión + estado DB |
| GET | `/health/detailed` | Estado detallado: DB, pool, cache, disco, memoria |
| GET | `/metrics` | Métricas operativas JSON |
| GET | `/metrics/prometheus` | Métricas en formato Prometheus |
| POST | `/api/v1/leads` | Alta de lead desde la landing |
| POST | `/api/v1/auth/register` | Alta de usuario (bootstrap del 1er admin del tenant) |
| POST | `/api/v1/auth/login` | Login → tokens JWT |
| POST | `/portal/auth/login` | Login del portal cliente |
| POST | `/portal/auth/magic-link` | Emite sesión sin password (mock email) |
| POST | `/portal/auth/confirm` | Valida un token de magic link |

### 5.2 Facturas (invoices) — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/invoices/process` | Procesa un CFDI (multipart o xml_path) por el pipeline completo |
| GET | `/api/v1/invoices` | Lista con filtros (categoria, valido, fechas, limit) |
| GET | `/api/v1/invoices/{invoice_id}` | Detalle de una factura |

### 5.3 Métricas y estado — API key

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/stats` | Métricas agregadas (totales y por categoría) |
| GET | `/api/v1/tools` | Tools registradas en el agente |
| GET | `/api/v1/dashboard` | Dashboard web HTML |
| GET | `/api/v1/dashboard/data` | Datos del dashboard en JSON |
| GET | `/api/v1/dashboard/summary` | Totales procesados y estado |
| GET | `/api/v1/dashboard/kpi` | KPIs: tiempo, error %, % automático |
| GET | `/api/v1/dashboard/monthly` | Facturas/montos/anomalías por mes |
| GET | `/api/v1/dashboard/anomalies` | Anomalías por severidad y tipo |
| GET | `/api/v1/dashboard/by-provider` | Top 10 proveedores por monto |
| GET | `/api/v1/dashboard/reconciliation` | Estado de la conciliación |

### 5.4 Contabilidad, nómina, SAT — API key

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/accounting/catalog` | Catálogo de cuentas (CUC) |
| GET | `/api/v1/accounting/balance` | Balanza de comprobación |
| POST | `/api/v1/accounting/sat/send` | Envía balanza al SAT (MOCK) |
| POST | `/api/v1/payroll/calculate` | Calcula nómina (ISR, IMSS, INFONAVIT) + CFDI opcional |
| POST | `/api/v1/contabilidad/catalogo` | Importa/crea catálogo de cuentas |
| GET | `/api/v1/contabilidad/catalogo` | Lista catálogo del tenant |
| POST | `/api/v1/contabilidad/asientos` | Registra un asiento contable |
| POST | `/api/v1/contabilidad/balanza/{periodo}` | Genera balanza del mes |
| GET | `/api/v1/contabilidad/balanza/{periodo}` | Descarga balanza XML (SAT) |
| POST | `/api/v1/contabilidad/electronica/{periodo}` | Genera paquete de contabilidad electrónica |
| GET | `/api/v1/contabilidad/electronica/{periodo}/download` | Descarga XML listo para SAT |
| POST | `/api/v1/sat/download` | Descarga masiva de CFDI por rango |
| POST | `/api/v1/sat/verify` | Verifica estatus y cadena de un CFDI |
| POST | `/api/v1/sat/schedule` | Programa descarga/verificación periódica |
| GET | `/api/v1/sat/status` | Estado de sesión y scheduler SAT |

### 5.5 Conciliación y cobranza — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/reconcile/run` | Ejecuta conciliación bancaria |
| POST | `/api/v1/reconciliation/upload` | Sube estado de cuenta (CSV/PDF) |
| GET | `/api/v1/reconciliation/matches` | Cruces automáticos (con confidence) |
| GET | `/api/v1/reconciliation/report` | Reporte de la sesión actual |
| POST | `/api/v1/reconciliation/confirm` | Confirma manualmente un cruce |
| POST | `/api/v1/collections/analyze` | Analiza cartera pendiente |
| POST | `/api/v1/collections/send-reminder` | Genera/registra recordatorio |
| GET | `/api/v1/collections/aging` | Reporte de antigüedad |
| GET | `/api/v1/collections/score/{invoice_id}` | Score de cobrabilidad |

### 5.5b Reportes — API key

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/reports/{report_type}/{period}` | Genera un reporte PDF del periodo (`report_type` en `invoices`\|`monthly`\|`reconciliation`\|`anomaly`\|`tax`) |
| POST | `/api/v1/reports/custom` | Genera un reporte personalizado desde JSON (`data` + `template`); devuelve PDF |
| GET | `/api/v1/reports/{report_id}/download` | Descarga un reporte previamente generado por id |

### 5.6 Webhooks — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/webhooks/email` | Recibe facturas por email (mock Mailgun/SendGrid) |
| POST | `/api/v1/webhooks/notify` | Entrega un resultado al webhook del tenant |
| POST | `/api/v1/webhooks/subscriptions` | Registra la URL de webhook |
| GET | `/api/v1/webhooks/subscriptions` | Lista la URL de webhook |
| POST | `/api/v1/webhooks/retry` | Reintenta entregas pendientes (worker) |

Ver `docs/webhooks.md` para el detalle completo de eventos, firma y retry.

### 5.7 Notificaciones — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/notifications/send` | Encola/envía WhatsApp |
| POST | `/api/v1/notifications/email` | Envía email (SMTP) |
| GET | `/api/v1/notifications/history` | Historial persistido |
| POST | `/api/v1/notifications/config` | Guarda config de WhatsApp del tenant |
| PUT | `/api/v1/notifications/preferences` | Guarda preferencias de notificación |

### 5.8 Facturación (billing) — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/billing/checkout` | Inicia checkout y procesa pago |
| POST | `/api/v1/billing/subscription` | Crea/activa suscripción a un plan |
| GET | `/api/v1/billing/invoices` | Facturas del tenant |
| GET | `/api/v1/billing/plans` | Planes y precios |
| POST | `/api/v1/billing/webhook` | Recibe eventos del proveedor |

### 5.9 Tenants y onboarding — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/tenants` | Onboarding de un nuevo cliente |
| GET | `/api/v1/onboarding/status` | Estado del onboarding + score readiness |
| PUT | `/api/v1/onboarding/step/{step}` | Envía y valida un paso del wizard |
| POST | `/api/v1/onboarding/complete` | Cierra onboarding y crea usuarios |

### 5.10 Usuarios (admin) — JWT

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/tenants/{tenant_id}/users` | Lista usuarios del tenant |
| POST | `/api/v1/tenants/{tenant_id}/users` | Crea un usuario |
| PUT | `/api/v1/tenants/{tenant_id}/users/{user_id}/role` | Cambia rol |
| GET | `/api/v1/auth/me` | Usuario autenticado |
| PUT | `/api/v1/auth/me` | Actualiza perfil propio |

### 5.11 Enterprise v2 (escala) — API key

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v2/batch` | Procesa hasta 1000 CFDI en lote (sync o async) |
| GET | `/api/v2/batch/{job_id}` | Estado/resultado de un lote async |
| GET | `/api/v2/analytics` | Analytics avanzado por tenant (cache TTL) |
| POST | `/api/v2/webhooks` | Registra suscripciones por evento |
| GET | `/api/v2/webhooks` | Lista suscripciones |
| DELETE | `/api/v2/webhooks/{subscription_id}` | Elimina suscripción |
| GET | `/api/v2/audit` | Log de auditoría del tenant |
| POST | `/api/v2/export` | Exporta a CSV/XLSX/PDF |
| GET | `/api/v2/usage` | Uso del tenant (calls, facturas) |
| GET | `/api/v2/health` | Health detallado del servicio |
| GET | `/api/v2/tenants` | Lista tenants + uso (admin) |
| POST | `/api/v2/tenants` | Onboarding de tenant (admin) |
| PATCH | `/api/v2/tenants/{tid}` | Configura un tenant (admin) |
| POST | `/api/v2/tenants/{tid}/block` | Bloquea tenant |
| POST | `/api/v2/tenants/{tid}/unblock` | Desbloquea tenant |
| GET | `/api/v2/tenants/{tid}/usage` | Uso de un tenant (admin) |
| POST | `/api/v2/retention/purge` | Aplica política de retención (key de servicio) |

### 5.12 Portal del cliente (Bearer)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/portal/auth/logout` | Cierra sesión |
| GET | `/portal/auth/me` | Usuario autenticado |
| GET | `/portal/invoices.json` | Lista facturas (con filtros) |
| GET | `/portal/invoices/{job_or_id}/status` | Estado de un job o factura |
| POST | `/portal/invoices/upload` | Sube CFDI y lo procesa en segundo plano |
| GET | `/portal/invoices/export.csv` | Exporta historial a CSV |
| GET | `/portal/dashboard/stats` | Métricas del tenant |
| GET | `/portal/notifications` | Notificaciones del tenant |
| PUT | `/portal/settings` | Actualiza ajustes del portal |

### 5.13 Legacy (compatibilidad, protegidos por API key)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/tools` | Tools registradas |
| GET | `/invoices` | Lista facturas |
| GET | `/stats` | Métricas agregadas |
| POST | `/process` | Procesa CFDI (xml_path o folder) |

---

## 6. Ejemplos de request/response

### 6.1 Procesar un CFDI

**Multipart** (recomendado desde un navegador o curl):

```bash
curl -X POST https://api.b2b-ai.local/api/v1/invoices/process \
  -H "X-API-Key: sk_live_xxx" \
  -F "xml_file=@factura.xml" \
  -F "tenant_id=1"
```

**JSON con ruta en servidor** (para integraciones server-to-server):

```bash
curl -X POST https://api.b2b-ai.local/api/v1/invoices/process \
  -H "X-API-Key: sk_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{"xml_path": "/data/cfdi/factura_20260731.xml", "tenant_id": 1}'
```

Respuesta `200 OK`:

```json
{
  "result": {
    "archivo": "factura.xml",
    "valido": true,
    "requires_human_review": false,
    "categoria": "gastos",
    "confianza": 0.97,
    "erp_poliza": "P-00123",
    "erp_status": "contabilizada",
    "insertado": true,
    "total": 12000.0,
    "emisor": "XAXX010101000",
    "notificacion": "enviada"
  }
}
```

Errores:
- `422` CFDI inválido (`detail: "CFDI inválido: <motivo>"`).
- `404` xml_path no existe.
- `400` no mandaste `xml_file` ni `xml_path`.
- `422` extensión no permitida (solo `.xml`/`.pdf`).

### 6.2 Listar facturas

```http
GET /api/v1/invoices?categoria=gastos&valido=true&fecha_desde=2026-07-01&fecha_hasta=2026-07-31&limit=100
X-API-Key: sk_live_xxx
```

```json
{
  "count": 2,
  "tenant_id": 1,
  "invoices": [
    {
      "id": 42,
      "folio_fiscal": "UUID-1234",
      "emisor_rfc": "XAXX010101000",
      "emisor_nombre": "Proveedor X",
      "fecha": "2026-07-30",
      "total": 12000.0,
      "categoria": "gastos",
      "valido": true,
      "status": "procesado"
    }
  ]
}
```

Nota de multi-tenant: la key autenticada fija el tenant; el parámetro
`tenant_id` solo aplica para la key de servicio.

### 6.3 Lote asíncrono (v2)

```bash
curl -X POST https://api.b2b-ai.local/api/v2/batch \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"paths": ["/data/cfdi/1.xml", "/data/cfdi/2.xml"], "async": true, "webhook": true}'
```

```json
{"accepted": true, "job_id": "3f2a1c9b7d41", "total": 2, "status": "running"}
```

Polling:

```http
GET /api/v2/batch/3f2a1c9b7d41
X-API-Key: sk_live_xxx
```

```json
{
  "id": "3f2a1c9b7d41",
  "tenant_id": 1,
  "status": "completed",
  "summary": {
    "procesadas": 2, "validas": 2, "con_observaciones": 0,
    "insertadas": 2, "por_categoria": {"gastos": 2}, "errores": 0
  },
  "results": [
    {"archivo": "1.xml", "valido": true, "categoria": "gastos",
     "confianza": 0.98, "erp_poliza": "P-0001", "erp_status": "contabilizada",
     "insertado": true, "total": 100.0, "emisor": "XAXX010101000", "invoice_id": 1}
  ]
}
```

### 6.4 Exportar

```bash
curl -X POST https://api.b2b-ai.local/api/v2/export \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"format": "csv", "scope": "invoices", "limit": 1000}' -o export.csv
```

Soporta `format`: `csv`, `xlsx`, `pdf`; `scope`: `invoices`, `audit`.
Responde con `Content-Disposition: attachment`.

### 6.5 Alta de lead (público)

```bash
curl -X POST https://api.b2b-ai.local/api/v1/leads \
  -H "Content-Type: application/json" \
  -d '{"nombre":"María González","email":"maria@despacho.com","despacho":"Despacho XYZ","facturas":"400/mes","mensaje":"Quiero automatizar"}'
```

```json
{"ok": true, "lead_id": 12, "message": "Lead registrado. Te contactamos en menos de 24h."}
```

### 6.6 Payroll

```bash
curl -X POST https://api.b2b-ai.local/api/v1/payroll/calculate \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{
    "empleado": {"nombre":"Juan Pérez","rfc":"PEJA850101XXX"},
    "periodo": {"sueldo_bruto": 25000.0, "dias_pagados": 30},
    "generar_cfdi": false
  }'
```

Devuelve desglose de ISR, IMSS, INFONAVIT y neto; si `generar_cfdi=true`,
añade `cfdi_xml`.

### 6.7 Concilación

```bash
curl -X POST https://api.b2b-ai.local/api/v1/reconcile/run \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{
    "invoices": [{"folio_fiscal":"A1B2C3","fecha":"2026-07-30","total":12000.0,"emisor":"XAXX010101000"}],
    "bank_transactions": [{"fecha":"2026-07-30","monto":12000.0,"descripcion":"Transferencia","ref":"A1B2C3"}],
    "date_tolerance_days": 3
  }'
```

---

## 7. CORS y seguridad

- **CORS**: desactivado por defecto (solo same-origin). Para integraciones de
  otro dominio, configura `B2B_CORS_ORIGINS` (lista separada por coma) y
  opcionalmente `B2B_CORS_ALLOW_CREDENTIALS=true`.
- **Headers de seguridad**: HSTS, CSP, `X-Frame-Options`, `X-Content-Type-Options:
  nosniff` instalados por `b2b_ai/api/security_headers.py`.
- **Cifrado de campos**: campos PII cifrables via `encrypt_field`/`decrypt_field`
  y detección PII en `b2b_ai/api/security.py`.
- Subidas de archivos restringidas a `.xml`/`.pdf` (CFDI).

Ver `docs/security-audit-report.md` para el detalle.

---

## 8. Monitoring

- `GET /health` — liveness simple.
- `GET /health/detailed` — DB, pool, cache, disco, memoria, uptime; `status`
  `ok` o `degraded` con `degraded_components`.
- `GET /metrics` — JSON operativo (count, latencia por ruta, códigos de estado).
- `GET /metrics/prometheus` — texto Prometheus (scrape sin auth, exento de
  rate limit), incluye uso por tenant.

---

## 9. Cómo regenerar esta referencia y el OpenAPI

```bash
cd enterprise
.venv/bin/python scripts/generate_openapi.py   # regenera docs/openapi.json
```

El script hace `model_rebuild()` sobre todos los módulos con modelos Pydantic
(billing, auth, onboarding, sat, notifications, portal) antes de pedir el
schema a `create_app()`, de modo que es determinista y nunca se desincroniza
del código.
