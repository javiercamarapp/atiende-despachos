# API Documentation — B&B AI (Agente Contable Enterprise)

Versión de API: `1.0.0` · Base URL: `http://localhost:8000`

Esta documentación describe los endpoints del API real de B&B AI. El API se
autodocumenta en OpenAPI/Swagger:

| Recurso | URL |
|---|---|
| Interfaz Swagger UI (interactiva) | `http://localhost:8000/docs` |
| Spec OpenAPI (JSON) | `http://localhost:8000/openapi.json` |
| Health check | `http://localhost:8000/health` |

> La interfaz `/docs` de Swagger se genera automáticamente por FastAPI a
> partir del spec OpenAPI. Para usarla: navega a `/docs`, clic en
> "Authorize", pega tu API key, y prueba cada endpoint interactivamente.

---

## 1. Autenticación

Todos los endpoints bajo `/api/v1/*` requieren una **API key** enviada en el
header `X-API-Key`.

```
X-API-Key: <tu-api-key>
```

La key se resuelve en dos niveles (ver `b2b_ai/api/auth.py`):

1. **Multi-tenant (recomendado en producción):** la key se guarda **hashada**
   (SHA-256) en la tabla `api_keys` de la base, asociada a un `tenant_id`.
   Cada despacho tiene su propia key y solo ve sus propios datos.
2. **Key de servicio standalone (dev):** la variable de entorno
   `B2B_API_KEY` actúa como key maestra. Útil para pruebas single-tenant.

Características de seguridad:

- Comparación a prueba de timing (evita side-channel).
- Cada intento fallido se registra en el `audit_log` (con hash corto de la
  key, nunca el secreto completo).
- La key nunca se expone en las respuestas.

### Códigos de error de autenticación

| Código | Significado |
|---|---|
| `401` | Falta el header `X-API-Key`, o la key es inválida/no autorizada. |
| `422` | Body de la petición mal formado (para endpoints con body). |
| `404` | Recurso no encontrado (p. ej. `xml_path` inexistente, factura por id no hallada). |
| `400` | Petición mal formada (p. ej. falta `xml_file`/`xml_path`). |

---

## 2. Endpoints

### 2.1 `GET /health` — Health check (público)

Sin autenticación. Devuelve el estado del servicio.

**Respuesta 200**

```json
{
  "status": "ok",
  "service": "b2b-ai",
  "version": "1.0.0",
  "db_path": "/data/b2b_ai.db",
  "schema_version": 2,
  "invoices": 12,
  "tenants": 1
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `status` | string | `ok` si el servicio responde. |
| `version` | string | Versión del paquete. |
| `db_path` | string | Ruta de la base SQLite. |
| `schema_version` | int | Versión del esquema de DB aplicada. |
| `invoices` | int | Total de facturas registradas. |
| `tenants` | int | Número de despachos (tenants) en el sistema. |

---

### 2.2 `POST /api/v1/invoices/process` — Procesa un CFDI (API key)

Recibe el XML de un CFDI y ejecuta el **pipeline completo**: parse → validación
fiscal → clasificación → póliza ERP → persistencia → notificación.

**Dos formas de enviar el XML:**

**A) Multipart (campo `xml_file`)** — recomendada para subida de archivo:

```bash
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: <TU_KEY>" \
  -F "xml_file=@/ruta/al/cfdi.xml"
```

**B) JSON con `xml_path`** (ruta accesible en el servidor):

```bash
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: <TU_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"xml_path": "/ruta/al/cfdi.xml"}'
```

El schema JSON `ProcessRequest` acepta también `tenant_id`, `tenant_name`
(default `"Despacho Demo"`) y `tenant_rfc` — aunque en modo multi-tenant el
tenant efectivo lo impone la API key.

**Respuesta 200** (el resultado es un resumen; los campos voluminosos se
recortan):

```json
{
  "result": {
    "archivo": "01_gasto_operativo_papeleria.xml",
    "valido": true,
    "requires_human_review": false,
    "categoria": "gasto_operativo",
    "confianza": 0.95,
    "erp_poliza": "POL-9F3A21C4D0",
    "insertado": true,
    "total": "1200.50",
    "emisor": "XAXX010101000",
    "notificacion": "simulado"
  }
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `archivo` | string | Nombre del archivo XML procesado. |
| `valido` | bool | `true` si pasó todas las validaciones fiscales. |
| `requires_human_review` | bool | `true` si hay que revisar manualmente (DIOT, excepción, nómina, etc.). |
| `categoria` | string | Clasificación contable (`gasto_operativo`, `inversion`, `activo_fijo`, `nomina`, `desconocido`). |
| `confianza` | number | Confianza de la clasificación (0–1). |
| `erp_poliza` | string\|null | Id de la póliza generada en el ERP (mock). |
| `insertado` | bool | `true` si se insertó como factura nueva. |
| `total` | string\|null | Monto total del CFDI. |
| `emisor` | string\|null | RFC del emisor. |
| `notificacion` | string | Estado de la notificación (`simulado`, `sent`, `skipped`, `error`). |

---

### 2.3 `GET /api/v1/invoices` — Lista facturas (API key)

Lista las facturas con filtros opcionales.

**Query params** (todos opcionales):

| Param | Tipo | Descripción |
|---|---|---|
| `tenant_id` | int | Filtra por despacho. |
| `categoria` | string | Filtra por categoría (`gasto_operativo`, `inversion`, …). |
| `valido` | bool | `true`/`false` filtra por validez fiscal. |
| `fecha_desde` | string | Fecha inicial (`YYYY-MM-DD`). |
| `fecha_hasta` | string | Fecha final (`YYYY-MM-DD`). |
| `limit` | int | Máx. de resultados (default `100`, rango `1–1000`). |

```bash
curl -G http://localhost:8000/api/v1/invoices \
  -H "X-API-Key: <TU_KEY>" \
  -d categoria=inversion -d valido=true -d limit=20
```

**Respuesta 200**

```json
{
  "count": 2,
  "tenant_id": 1,
  "invoices": [
    {
      "id": 3,
      "tenant_id": 1,
      "folio_fiscal": "uuid-...",
      "archivo": "02_inversion_consultoria.xml",
      "fecha": "2026-07-15T10:00:00",
      "tipo": "I",
      "serie": "A",
      "folio": "100",
      "emisor_rfc": "XAXX010101000",
      "emisor_nombre": "Consultora X SA de CV",
      "receptor_rfc": "...",
      "subtotal": "1000.00",
      "iva": "160.00",
      "total": "1160.00",
      "moneda": "MXN",
      "categoria": "inversion",
      "confianza": 0.95,
      "razon_clasificacion": "Coincidencias: consultoria",
      "valido": 1,
      "requires_human_review": 0,
      "issues": "",
      "erp_poliza": "POL-...",
      "erp_status": "registrada",
      "status": "procesado",
      "procesado_en": "2026-07-31T17:00:00",
      "created_at": "2026-07-31T17:00:00"
    }
  ]
}
```

---

### 2.4 `GET /api/v1/invoices/{invoice_id}` — Detalle de factura (API key)

Devuelve una factura por su id. Respuesta `404` si no existe (o no pertenece
al tenant de la key).

```bash
curl -H "X-API-Key: <TU_KEY>" http://localhost:8000/api/v1/invoices/3
```

**Respuesta 200**

```json
{
  "invoice": { "id": 3, "tenant_id": 1, "...": "..." }
}
```

---

### 2.5 `GET /api/v1/stats` — Métricas agregadas (API key)

Totales, IVA, montos por categoría, tenants, audit y notificaciones.

```bash
curl -H "X-API-Key: <TU_KEY>" http://localhost:8000/api/v1/stats
```

**Respuesta 200**

```json
{
  "total_facturas": 12,
  "monto_total": 15000.0,
  "iva_total": 2400.0,
  "por_categoria": {
    "gasto_operativo": { "count": 5, "total": 5200.0 },
    "inversion": { "count": 3, "total": 4800.0 }
  },
  "tenants": [ { "id": 1, "name": "Despacho Demo", "rfc": "" } ],
  "audit_calls": 67,
  "notifications": 12,
  "report": {
    "period": null,
    "tenant_id": null,
    "facturas": 12,
    "validas": 12,
    "invalidas": 0,
    "subtotal": "12600.00",
    "iva": "2400.00",
    "total": "15000.00",
    "por_categoria": {},
    "por_mes": {}
  },
  "tools_registered": ["parse_cfdi", "validate_cfdi", "classify_expense",
                       "register_erp", "send_notification", "reconcile_bank",
                       "generate_report"]
}
```

---

### 2.6 `GET /api/v1/tools` — Tools registradas (API key)

Lista las tools del agente con su schema de parámetros.

```bash
curl -H "X-API-Key: <TU_KEY>" http://localhost:8000/api/v1/tools
```

**Respuesta 200**

```json
{
  "tools": [
    {
      "name": "parse_cfdi",
      "description": "Extrae todos los campos de un CFDI 4.0 XML.",
      "category": "parse",
      "parameters": [ { "name": "xml_path", "type": "string", "required": true } ]
    }
  ]
}
```

---

### 2.7 `POST /api/v1/leads` — Alta de lead (público)

Registra un lead desde la landing page. **No requiere API key.**

```bash
curl -X POST http://localhost:8000/api/v1/leads \
  -H "Content-Type: application/json" \
  -d '{"nombre":"Ana","email":"ana@despacho.com","despacho":"Despacho A","facturas":"100-500"}'
```

**Respuesta 200**

```json
{
  "ok": true,
  "lead_id": 5,
  "message": "Lead registrado. Te contactamos en menos de 24h."
}
```

Rechaza con `422` si `nombre` o `email` vienen vacíos.

---

### 2.8 Endpoints legacy (sin versión, compatibilidad)

Existen para retrocompatibilidad y **no deben usarse en integraciones nuevas**:

| Endpoint | Método | Descripción |
|---|---|---|
| `/invoices` | GET | Lista facturas (`tenant_id`, `limit`). |
| `/stats` | GET | Métricas (sin auth). |
| `/tools` | GET | Tools registradas (sin auth). |
| `/process` | POST | Procesa CFDI por `xml_path` o `folder` (batch). |

---

## 3. Landing page (servida por el API)

Cuando la carpeta `landing/` está presente junto al código, el API sirve la
landing estática en el mismo origen:

| Ruta | Contenido |
|---|---|
| `/` y `/index.html` | Landing page. |
| `/robots.txt` | Robots (permite todo, apunta sitemap). |
| `/sitemap.xml` | Sitemap. |
| `/static/*` | Estáticos (CSS/JS/img). |

---

## 4. Errores comunes

| Situación | Código | Cómo resolver |
|---|---|---|
| Sin header `X-API-Key` | `401` | Añade `-H "X-API-Key: <key>"`. |
| Key inválida | `401` | Verifica la key en `api_keys` o `B2B_API_KEY`. |
| XML no encontrado (`xml_path`) | `404` | Verifica la ruta en el servidor. |
| Body sin `xml_file` ni `xml_path` | `400` | Envía multipart o JSON con `xml_path`. |
| Archivo XML vacío | `400` | Envía un CFDI XML válido. |
| Factura por id no existe | `404` | Verifica el id y que pertenezca al tenant. |

---

## 5. Levantar el API

**Local (dev):**

```bash
cd enterprise
source .venv/bin/activate
B2B_API_KEY=mi-secreto uvicorn b2b_ai.api.app:app --reload
# Docs en http://localhost:8000/docs
```

**Con Docker:**

```bash
cd enterprise
cp .env.example .env && vi .env     # define B2B_API_KEY
docker compose up --build -d
# API en http://localhost:8000 · Docs en /docs · DB persistente en volumen
```

**Verificación:** `curl http://localhost:8000/health` debe devolver
`{"status":"ok", ...}`.
