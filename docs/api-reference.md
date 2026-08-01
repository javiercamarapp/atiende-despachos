# API Reference — B&B AI

Referencia técnica completa de la API REST del agente contable enterprise.
Toda la documentación interactiva (OpenAPI) está disponible en
`/docs` (Swagger UI), `/redoc` y `/openapi.json` de la instancia en ejecución.

Versión de API documentada: **1.0.0** · Base URL: `https://<host>:<port>`

---

## 1. Authentication

La API usa **API keys por despacho (multi-tenant)** o una **key maestra de
servicio**. La key se envía en el header HTTP:

```
X-API-Key: <tu-api-key>
```

**Resolución de la key** (`b2b_ai/api/auth.py`):

1. Si la key coincide con la env `B2B_API_KEY` → identidad `service`
   (`tenant_id=None`). Útil para dev, pruebas y operación del sistema.
2. Si la key existe en la tabla `api_keys` → identidad del `tenant_id` asociado
   y su nombre.

**Alcance de tenant (hard-scoping):** una key de tenant **nunca** puede ver o
operar sobre otro tenant, aunque el cliente mande `tenant_id` en la query. Solo
la key de servicio (env) puede pedir un tenant arbitrario o todos. Un tenant
**bloqueado** recibe `403` en cualquier endpoint `/api/v1/*`.

**Seguridad:**
- Comparación de keys a prueba de timing (`hmac.compare_digest`).
- Cada intento fallido de auth se audita en el `audit_log` (sin guardar la key
  completa: se registra longitud + hash corto).
- La key **nunca** se devuelve en respuestas.

### Portal del cliente (auth por token)

El portal (`/portal/*`) usa un **token de sesión** distinto, no API key:

- `POST /portal/auth/login` — email + password (bcrypt) → `token`.
- `POST /portal/auth/magic-link` — emite una sesión sin password (mock: devuelve
  `dev_token` para desarrollo; en producción se envía por email).
- `POST /portal/auth/confirm` — valida el token del magic-link.
- El token se envía como header `Authorization: Bearer <token>` (o según cliente).

---

## 2. Endpoints públicos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Health check: estado, versión, DB, conteo de facturas/tenants, uptime. |
| GET | `/metrics` | Métricas operativas (request count, latencia por ruta, códigos de estado). |
| POST | `/api/v1/leads` | Alta de lead desde la landing (sin auth). |
| GET | `/` `/index.html` `/dashboard` `/dashboard.html` `/manifest.json` `/sw.js` `/icons/{name}` `/robots.txt` `/sitemap.xml` | Landing page y estáticos (PWA). |

### Ejemplos

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"b2b-ai","version":"1.0.0","backend":"sqlite",
#  "db_path":"./b2b_ai.db","schema_version":1,"invoices":12,"tenants":1,
#  "uptime_seconds":120,"total_requests":340}

curl -X POST http://localhost:8000/api/v1/leads \
  -H "Content-Type: application/json" \
  -d '{"nombre":"Ana","email":"ana@despacho.com","despacho":"Despacho A","facturas":"100-500"}'
# {"ok":true,"lead_id":7,"message":"Lead registrado. Te contactamos en menos de 24h."}
```

---

## 3. API v1 — Facturas, estadísticas y procesamiento

### 3.1 `POST /api/v1/invoices/process`

Procesa un CFDI por el pipeline completo (validación → clasificación → póliza
ERP → persistencia → notificación). Acepta dos formatos de entrada.

**Multipart** (campo `xml_file`):

```bash
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" \
  -F "xml_file=@fixtures/cfdis/01_gasto_operativo_papeleria.xml"
```

**JSON** (campo `xml_path` — ruta local al XML en el servidor):

```bash
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"xml_path":"/ruta/al/cfdi.xml"}'
```

**Respuesta (200)** — resumen del pipeline:

```json
{
  "result": {
    "archivo": "01_gasto_operativo_papeleria.xml",
    "valido": true,
    "requires_human_review": false,
    "categoria": "operativo",
    "confianza": 0.98,
    "erp_poliza": "P-2026-001",
    "erp_status": "registered",
    "insertado": true,
    "total": 1130.0,
    "emisor": "XAXX010101000",
    "notificacion": "simulated"
  }
}
```

**Errores:** `400` (body inválido / falta xml_file o xml_path), `404` (archivo no
encontrado), `422` (CFDI inválido, detalle con el mensaje del validador).

### 3.2 `GET /api/v1/invoices`

Lista facturas con filtros.

**Query params:** `tenant_id` (solo key de servicio), `categoria`, `valido`
(bool), `fecha_desde`, `fecha_hasta`, `limit` (default 100, 1–1000).

```bash
curl -G http://localhost:8000/api/v1/invoices \
  -H "X-API-Key: $KEY" \
  -d categoria=operativo -d valido=true -d limit=20
```

```json
{"count": 3, "tenant_id": 1, "invoices": [ { "id": 1, "emisor_rfc": "XAXX010101000", "total": 1130.0, "categoria": "operativo", "valido": true } ]}
```

### 3.3 `GET /api/v1/invoices/{invoice_id}`

Detalle de una factura por id (escopado al tenant autenticado). `404` si no
existe o pertenece a otro tenant.

### 3.4 `GET /api/v1/stats`

Métricas agregadas: totales, IVA, monto por categoría, tenants, audit calls,
notificaciones, reporte generado y tools registradas.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/stats
```

### 3.5 `GET /api/v1/tools`

Tools registradas en el agente (framework de tool calling).

---

## 4. API v1 — Conciliación, nómina y contabilidad

### 4.1 `POST /api/v1/reconcile/run`

Concilia facturas contra movimientos bancarios (monto + fecha + referencia).

```json
{
  "invoices": [{"id": 1, "total": 1000.0, "fecha": "2026-07-01"}],
  "bank_transactions": [{"monto": 1000.0, "fecha": "2026-07-01", "referencia": "REF-1"}],
  "date_tolerance_days": 3
}
```

### 4.2 `GET /api/v1/accounting/catalog`

Catálogo de cuentas (CUC). → `{"count": N, "catalogo": [...]}`.

### 4.3 `GET /api/v1/accounting/balance`

Balanza de comprobación desde facturas de la DB. Query: `periodo` (YYYY-MM).

### 4.4 `POST /api/v1/accounting/sat/send`

Envía la balanza al SAT en **modo MOCK** (acuse simulado). Query params
obligatorios: `ejercicio`, `mes` (1–12), `rfc`, `periodo`. La presentación real
requiere e.firma del contribuyente.

### 4.5 `POST /api/v1/payroll/calculate`

Calcula nómina (ISR, IMSS, INFONAVIT) y opcionalmente genera el CFDI.

```json
{
  "empleado": {"nombre": "Juan", "rfc": "JUAL840101AAA"},
  "periodo": {"sueldo_bruto": 25000, "dias_pagados": 30},
  "generar_cfdi": false
}
```

---

## 5. API v1 — Cobranza (FASE 3)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/collections/analyze` | Clasifica cartera por antigüedad (0-30/31-60/61-90/90+) y calcula score. `sync=true` persiste en `outstanding_invoices`. |
| POST | `/api/v1/collections/send-reminder` | Genera un recordatorio por etapa y canal (no envía reales). `record=true` registra el intento. |
| GET | `/api/v1/collections/aging` | Reporte de antigüedad de la cartera persistida. |
| GET | `/api/v1/collections/score/{invoice_id}` | Score de cobrabilidad (0..1) + historial de intentos. |

---

## 6. API v1 — Contabilidad electrónica (FASE 3)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/contabilidad/catalogo` | Importa/crea el catálogo de cuentas (body `cuentas` o SAT default). Reemplaza el anterior. |
| GET | `/api/v1/contabilidad/catalogo` | Lista el catálogo del tenant (default SAT si vacío). |
| POST | `/api/v1/contabilidad/asientos` | Registra un asiento contable (debe/haber). |
| POST | `/api/v1/contabilidad/balanza/{periodo}` | Genera y persiste la balanza del mes (periodo `YYYY-MM`). |
| GET | `/api/v1/contabilidad/balanza/{periodo}` | Descarga la balanza en XML SAT. |
| POST | `/api/v1/contabilidad/electronica/{periodo}` | Genera el paquete de contabilidad electrónica. |
| GET | `/api/v1/contabilidad/electronica/{periodo}/download` | Descarga el XML listo para el SAT (con SHA-1 del acuse en comentario). |

---

## 7. API v1 — Dashboard

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/dashboard` | Panel HTML (métricas en vivo). |
| GET | `/api/v1/dashboard/data` | Datos del panel en JSON. |
| GET | `/api/v1/dashboard/summary` | Resumen agregado. |
| GET | `/api/v1/dashboard/monthly` | Montos mensuales. |
| GET | `/api/v1/dashboard/by-provider` | Top proveedores. |
| GET | `/api/v1/dashboard/anomalies` | Anomalías detectadas. |
| GET | `/api/v1/dashboard/reconciliation` | Estado de conciliación. |
| GET | `/api/v1/dashboard/kpi` | KPIs. |

> El dashboard SPA gerencial interactivo (Chart.js) se sirve en
> `GET /dashboard/` (ruta fuera de `/api/v1`, no listada en OpenAPI).

---

## 8. API v1 — Tenants y Webhooks (FASE 4)

### 8.1 Tenants

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/tenants` | Onboarding de un cliente (tenant) + config + API key de onboarding. |

```json
{
  "name": "Despacho Jurídico S.A.",
  "rfc": "XDC890101AB1",
  "erp_type": "contpaqi",
  "plantilla_contable": "SAT",
  "notif_channel": "email",
  "webhook_url": "https://despacho.com/hook",
  "user_name": "María",
  "user_email": "maria@despacho.com"
}
```

### 8.2 Webhooks

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/webhooks/email` | Recibe facturas por email (mock Mailgun/SendGrid): attachments base64 o XML embebido. |
| POST | `/api/v1/webhooks/notify` | Entrega un resultado al webhook del tenant. |
| POST | `/api/v1/webhooks/subscriptions` | Registra la URL de webhook para eventos. |
| GET | `/api/v1/webhooks/subscriptions` | Lista las suscripciones. |
| POST | `/api/v1/webhooks/retry` | Reintenta entregas pendientes (backoff exponencial). |

---

## 9. API v2 — Enterprise (`/api/v2/*`)

API multi-tenant robusta con rate limiting por tenant.

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v2/batch` | Procesa hasta **1000** CFDI en lote. `async_=true` → job en segundo plano. |
| GET | `/api/v2/batch/{job_id}` | Estado y resultado de un lote async. |
| GET | `/api/v2/analytics` | Analytics avanzado por tenant (cache TTL). Query: `periodo`, `desde`, `hasta`. |
| POST | `/api/v2/webhooks` | Registra webhooks para eventos del tenant (múltiples). |
| GET | `/api/v2/webhooks` | Lista suscripciones (`?event=`). |
| DELETE | `/api/v2/webhooks/{subscription_id}` | Elimina una suscripción. |
| GET | `/api/v2/audit` | Log completo de auditoría por tenant. |
| POST | `/api/v2/export` | Exporta datos a CSV/XLSX/PDF. |
| GET | `/api/v2/usage` | Uso del tenant (calls, facturas). |
| GET | `/api/v2/health` | Health detallado del servicio. |
| GET | `/api/v2/tenants` | (admin) Lista tenants + uso. |
| POST | `/api/v2/tenants` | (admin) Onboarding de un tenant. |
| POST | `/api/v2/tenants/{tid}/block` | (admin) Bloquea un tenant (deja de autenticar). |
| POST | `/api/v2/tenants/{tid}/unblock` | (admin) Desbloquea. |
| PATCH | `/api/v2/tenants/{tid}` | (admin) Configura un tenant. |
| GET | `/api/v2/tenants/{tid}/usage` | (admin) Uso de un tenant. |

**Ejemplo batch async:**

```bash
curl -X POST http://localhost:8000/api/v2/batch \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"folder":"/data/cfdis","async_":true,"webhook":"https://miapp.com/hook"}'
# {"accepted":true,"job_id":"...","total":120,"status":"running"}
```

---

## 10. Portal de cliente (`/portal/*`)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/portal/auth/login` | Login email+password (bcrypt) → token de sesión. |
| POST | `/portal/auth/magic-link` | Sesión sin password (mock → `dev_token`). |
| POST | `/portal/auth/confirm` | Valida token del magic-link. |
| POST | `/portal/auth/logout` | Cierra la sesión. |
| GET | `/portal/auth/me` | Datos del usuario autenticado. |
| GET | `/portal/invoices` | Facturas del cliente. |
| GET | `/portal/invoices/{job_or_id}/status` | Estado de un job o factura. |
| POST | `/portal/invoices/upload` | Sube facturas desde el navegador (async). |
| GET | `/portal/invoices/export.csv` | Exporta facturas a CSV. |
| GET | `/portal/dashboard/stats` | Estadísticas del dashboard del cliente. |

---

## 11. Rate limiting

- **Default:** 300 peticiones por minuto por (IP, ruta), ventana deslizante, en
  memoria (sin dependencias). Aplica a `/api/v1/*`, `/api/v2/*` y legacy.
- **Respuesta al exceder:** `429` con `Retry-After` (segundos):
  `{"detail": "Demasiadas peticiones. Intenta en un minuto."}`
- **Exentos:** `/health`, `/metrics`, `/static`, `/icons`, `/manifest.json`,
  `/sw.js`, `/robots.txt`, `/sitemap.xml`, `/docs`, `/openapi.json`, `/redoc`,
  `/favicon.ico`.
- **Config:** `B2B_RATE_LIMIT` (`on`/`off`), `B2B_RATE_LIMIT_PER_MIN` (0 = off).
- **V2** aplica además rate limiting **por tenant** (`_tenant_rate_limit`).
- En producción multi-replica conviene mover el limiter a un store compartido
  (Redis); para el MVP single-node es suficiente.

---

## 12. Pagination

La paginación se hace con el query param **`limit`** (offset no implementado;
usar `limit` + filtros de rango de fechas):

- `/api/v1/invoices`: `limit` default 100, rango 1–1000.
- La respuesta incluye `count` (número de ítems devueltos) y la lista.
- Para paginar sobre conjuntos grandes, filtrar por `fecha_desde`/`fecha_hasta`
  o por `categoria`/`valido` y avanzar por rango temporal.
- `/api/v2/analytics` filtra por `periodo`/`desde`/`hasta`.

> Nota: para recorridos completos de un tenant en producción, considera usar el
> endpoint de **export** (`/api/v2/export`) en lugar de paginar manualmente.

---

## 13. Error codes

| Código | Significado | Detalle típico |
|---|---|---|
| `400` | Petición mal formada | Body inválido, falta `xml_file` o `xml_path`, `monto` inválido. |
| `401` | No autenticado | Falta header `X-API-Key` o key inválida. |
| `403` | Prohibido | Tenant bloqueado; key sin permiso para el recurso. |
| `404` | No encontrado | Factura, archivo, lote, cuenta o tenant inexistentes. |
| `409` | Conflicto | Estado inconsistente (p. ej. webhook ya registrado). |
| `422` | CFDI inválido / validación | CFDI rechazado, monto ≤ 0, más de `MAX_BATCH` (1000) por lote, evento webhook inválido, cuenta no existe. |
| `429` | Rate limit excedido | `Retry-After` en el header. |
| `5xx` | Error interno | Fallo no manejado. |

El formato de error es el estándar FastAPI:

```json
{"detail": "Mensaje legible del error"}
```

---

## 14. Ejemplos rápidos (curl)

```bash
# Health (público)
curl http://localhost:8000/health

# Procesar CFDI (multipart)
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" -F "xml_file=@factura.xml"

# Listar facturas del tenant (con filtros)
curl -G http://localhost:8000/api/v1/invoices -H "X-API-Key: $KEY" \
  -d categoria=operativo -d valido=true -d limit=50

# Estadísticas
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/stats

# Conciliación bancaria
curl -X POST http://localhost:8000/api/v1/reconcile/run \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"invoices":[],"bank_transactions":[]}'

# Nómina
curl -X POST http://localhost:8000/api/v1/payroll/calculate \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"empleado":{"rfc":"JUAL840101AAA"},"periodo":{"sueldo_bruto":25000}}'

# Batch v2 async
curl -X POST http://localhost:8000/api/v2/batch \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"folder":"/data/cfdis","async_":true}'
```

---

## 15. Base URL y versionado

- Los endpoints `/api/v1/*` y `/api/v2/*` son versionados. `/api/v1` es el
  conjunto principal; `/api/v2` añade las capacidades enterprise (batch,
  analytics, export, admin tenants).
- Existen **endpoints legacy sin versión** (`/invoices`, `/stats`, `/tools`,
  `/process`) para compatibilidad; **ahora protegidos por API key**. Se
  recomienda migrar a `/api/v1/*`.
- La versión del servicio se expone en `/health` y en el header/título de OpenAPI.
