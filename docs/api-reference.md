# API Reference — Likida AI (Enterprise)

Referencia de la API REST del agente contable IA para despachos contables.
Documenta la integración completa para un despacho: autenticación, CFDI,
bancos, nómina, documentos, reportes, contabilidad electrónica y conciliación.

- Base URL (producción): `https://api.b2b-ai.local`
- Base URL (local): `http://localhost:8000`
- Documentación interactiva: `GET /docs` (Swagger UI), `GET /redoc`
- Contrato OpenAPI: `GET /openapi.json` · también en `docs/openapi.json`
  y `docs/openapi.yaml` (generado con `scripts/export_openapi.py`).
- Versión documentada: **1.0.0** · 284 rutas · 152 schemas.

> El contrato OpenAPI (`docs/openapi.json`) es la fuente de verdad para rutas,
> parámetros y schemas. Este documento añade guía de uso, ejemplos y errores.

---

## 1. Autenticación

La mayoría de endpoints de `/api/v1/*` se autentican con una **API key** en el
header `X-API-Key`. Los módulos `/api/v1/auth/*` y el portal usan **JWT Bearer**.

| Esquema | Header | Ámbito | Cómo se obtiene |
|---|---|---|---|
| **API Key** | `X-API-Key: <key>` | `/api/v1/*`, `/api/v2/*`, legacy | Se emite al crear un tenant (`POST /api/v1/tenants`) o en la env `B2B_API_KEY` (key de servicio) |
| **JWT Bearer** | `Authorization: Bearer <jwt>` | `/api/v1/auth/*`, `/api/v1/tenants/{id}/users/*` | `POST /api/v1/auth/login` |

### 1.1 Uso de la API key

```http
X-API-Key: sk_likida_XXXXXXXX
```

Cada key resuelve un `tenant_id` (aislamiento multi-tenant). Si la key coincide
con la env `B2B_API_KEY` se trata como key de servicio (`tenant_id=None`).

### 1.2 Respuestas de error estándar

| Código | Significado |
|---|---|
| `200` | OK |
| `400` | Petición mal formada / error de negocio validable |
| `401` | Falta o es inválida la API key |
| `403` | Key válida pero sin permiso para el recurso/tenant |
| `404` | Recurso no encontrado |
| `413` | Payload excede el límite (10 MB; subidas de docs 15 MB) |
| `422` | Validación de schemas/reglas falló (CFDI inválido, periodo mal formado…) |
| `429` | Rate limit superado (300 req/min por IP por defecto) |
| `500` | Error interno |

Los errores de `4xx/5xx` devuelven JSON estructurado:

```json
{
  "detail": "Cuenta no encontrada."
}
```

**Rate limit:** 300 req/min por IP (configurable con `B2B_RATE_LIMIT_PER_MIN`,
o `off` para desactivarlo). Cabecera `Retry-After` en el 429.

---

## 2. CFDI (facturas)

Módulo de procesamiento, listado y batch de Comprobantes Fiscales.

### 2.1 Procesar un CFDI — `POST /api/v1/invoices/process`

Sube un XML de CFDI y lo procesa por el pipeline completo (validación,
clasificación, póliza ERP, inserción en DB).

**multipart/form-data** (recomendado):

| Campo | Tipo | Descripción |
|---|---|---|
| `xml_file` | file | Archivo XML o PDF del CFDI (obligatorio) |

**O bien JSON** con:

```json
{ "xml_path": "/data/cfdi/factura_20260731.xml", "tenant_id": 1 }
```

> La ingesta por `xml_path` requiere que el servidor tenga `B2B_LOCAL_XML_DIRS`
> configurado; si no, responde `400`. Para integración externa use multipart.

Ejemplo curl (multipart):

```bash
curl -X POST https://api.b2b-ai.local/api/v1/invoices/process \
  -H "X-API-Key: sk_likida_XXXXXXXX" \
  -F "xml_file=@factura.xml"
```

Respuesta `200`:

```json
{
  "result": {
    "archivo": "factura.xml",
    "valido": true,
    "requires_human_review": false,
    "categoria": "Gastos",
    "confianza": 0.97,
    "erp_poliza": "P-2026-0781",
    "erp_status": "ok",
    "insertado": 1,
    "total": "12000.00",
    "emisor": "XAXX010101000",
    "notificacion": "sent"
  }
}
```

Errores: `400` (archivo vacío), `422` (CFDI inválido o solo `.xml/.pdf`), `401`.

### 2.2 Listar facturas — `GET /api/v1/invoices`

```bash
curl "https://api.b2b-ai.local/api/v1/invoices?categoria=gastos&valido=true&fecha_desde=2026-07-01&fecha_hasta=2026-07-31&limit=100" \
  -H "X-API-Key: sk_likida_XXXXXXXX"
```

Query params: `tenant_id`, `categoria`, `valido`, `fecha_desde`, `fecha_hasta`,
`limit` (default 100, max 1000).

```json
{
  "count": 2,
  "tenant_id": 1,
  "invoices": [
    { "id": 12, "folio_fiscal": "A1B2C3", "fecha": "2026-07-30",
      "total": "12000.00", "emisor_rfc": "XAXX010101000",
      "categoria": "Gastos", "valido": 1 }
  ]
}
```

### 2.3 Detalle de una factura — `GET /api/v1/invoices/{invoice_id}`

```bash
curl https://api.b2b-ai.local/api/v1/invoices/12 -H "X-API-Key: sk_likida_XXXXXXXX"
```

```json
{ "invoice": { "id": 12, "folio_fiscal": "A1B2C3", "fecha": "2026-07-30",
               "total": "12000.00", "emisor_rfc": "XAXX010101000" } }
```

`404` si no existe.

### 2.4 Procesar batch de CFDIs — `POST /api/v1/cfdi/batch` + `GET /api/v1/cfdi/batch/{id}`

> Rutas definidas en `features/batch` (límites: 500 CFDIs / 10 MB). Nota: la
> app principal monta el batch **vía `/api/v2/batch`** (hasta 1000 CFDIs).
> Ver sección 8.

### 2.5 Métricas — `GET /api/v1/stats`

Totales, por categoría, auditoría, notificaciones y reporte.

---

## 3. Bank Feeds (bancos)

Módulo `/api/v1/bank-feeds/*` — conexión de cuentas, sincronización,
categorización y conciliación bancaria.

### 3.1 Conectar cuenta — `POST /api/v1/bank-feeds/accounts`

Body (`ConnectAccountRequest`):

```json
{
  "provider": "BBVA",
  "clabe": "012180015000000001",
  "account_label": "Cuenta operativa",
  "ofx_content": "...",
  "statement_text": "...",
  "tenant_id": ""
}
```

`provider`: `BBVA | BANORTE | SANTANDER | HSBC`. `clabe`, `ofx_content` y
`statement_text` son opcionales para el MVP.

```json
{ "ok": true, "message": "Cuenta conectada.", "data": { "id": "acc-1", "provider": "BBVA" } }
```

`400` si el proveedor es inválido.

### 3.2 Listar cuentas — `GET /api/v1/bank-feeds/accounts`

```json
{ "ok": true, "data": [ { "id": "acc-1", "provider": "BBVA", "clabe": "..." } ] }
```

### 3.3 Detalle de cuenta — `GET /api/v1/bank-feeds/accounts/{account_id}`

`404` si no existe.

### 3.4 Sincronizar — `POST /api/v1/bank-feeds/accounts/{account_id}/sync`

Query: `from_date`, `to_date` (`YYYY-MM-DD`), `limit` (default 200, max 1000).

```json
{ "ok": true, "data": { "synced": 150, "new_transactions": 12 } }
```

`404` cuenta no encontrada · `502` fallo del proveedor.

### 3.5 Transacciones — `GET /api/v1/bank-feeds/accounts/{account_id}/transactions`

Query: `status`, `category`, `limit`.

### 3.6 Historial de syncs — `GET /api/v1/bank-feeds/accounts/{account_id}/syncs`

### 3.7 Categorizar — `POST /api/v1/bank-feeds/transactions/{txn_id}/categorize`

Body (`CategorizeRequest`):

```json
{ "category": "Servicios", "auto": false }
```

`category` opcional (si es `null` y `auto=true`, infiere por heurística).
`404` si la transacción no existe.

### 3.8 Conciliar — `POST /api/v1/bank-feeds/reconcile`

Cruza transacciones con CFDI/pólizas. Body (`ReconcileRequest`):

```json
{
  "account_id": "acc-1",
  "cfdi_list": [ { "uuid": "A1B2C3", "fecha": "2026-07-30", "total": 12000.0 } ],
  "tolerance_days": 3
}
```

```json
{ "ok": true, "data": { "matched": 10, "unmatched": 2 } }
```

---

## 4. Nómina

Módulo `/nomina-completa/*` — cálculo ISR/IMSS/INFONAVIT, CFDI de nómina 1.2,
recibos (payslips) y resumen por periodo.

### 4.1 Procesar nómina — `POST /nomina-completa/process`

Body (`ProcessPayrollRequest`):

```json
{
  "period": { "month": 7, "year": 2026, "dias_pagados": 30 },
  "employees": [
    { "employee_id": "EMP-1", "name": "Juan Pérez",
      "salary": 25000.0, "benefits": 0.0 }
  ],
  "tenant_id": 1
}
```

```json
{
  "ok": true,
  "payroll": {
    "period": "2026-07",
    "employee_count": 1,
    "employees": [ { "employee_id": "EMP-1", "salario_bruto": 25000.0,
                     "neto": 20300.0, "taxes": { "isr": 3500.0, "imss": 900.0,
                     "infonavit": 300.0 } } ],
    "totals": { "neto": 20300.0, "isr": 3500.0 }
  }
}
```

### 4.2 CFDI de nómina — `POST /nomina-completa/cfdi`

Body (`CFDINominaRequest`): `{ "payroll_data": { ...datos procesados... } }`

### 4.3 Recibo de nómina — `GET /nomina-completa/payslip/{employee_id}`

Query: `month` (1-12, req), `year` (req), `tenant_id`.

> El tenant se deriva **siempre** del token autenticado (anti-IDOR).

`404` si no hay nómina procesada para ese periodo/empleado.

### 4.4 Resumen del periodo — `GET /nomina-completa/summary`

Query: `month`, `year`, `tenant_id`.

### 4.5 Impuestos individuales — `POST /nomina-completa/taxes`

Body (`TaxesRequest`): `{ "salary": 25000.0, "benefits": 0.0, "salary_per_day": 0.0 }`

```json
{ "ok": true, "taxes": { "isr": 3500.0, "imss": 900.0, "infonavit": 300.0, "neto": 20300.0 } }
```

---

## 5. Documentos

Módulo `/api/v1/documents/*` — gestión documental con OCR, versionado y sharing.
Tenant **obligatorio** en el contexto de auth (`400` si falta).

### 5.1 Subir documento — `POST /api/v1/documents/upload`

multipart:

| Campo | Tipo | Descripción |
|---|---|---|
| `file` | file | Archivo (max 15 MB) — obligatorio |
| `category` | form | Categoría (`FACTURA`, `RECIBO`, `CONTRATO`, `OTRO`…) |
| `tags` | form | Tags separados por coma |
| `created_by` | form | Autor |

```json
{ "ok": true, "document": { "id": "doc-1", "name": "contrato.pdf", "category": "OTRO" } }
```

`400` vacío/categoría inválida · `413` > 15 MB.

### 5.2 Buscar — `GET /api/v1/documents/search`

Query: `q`, `category`, `tag` (repetible), `limit` (default 50, max 200).

```json
{ "ok": true, "count": 1,
  "results": [ { "id": "doc-1", "name": "contrato.pdf", "category": "OTRO" } ] }
```

### 5.3 Metadata — `GET /api/v1/documents/{document_id}`

### 5.4 Descargar contenido — `GET /api/v1/documents/{document_id}/content`

Devuelve el binario como `attachment` con `Content-Disposition`.

### 5.5 Historial de versiones — `GET /api/v1/documents/{document_id}/versions`

### 5.6 Compartir — `POST /api/v1/documents/{document_id}/share`

Body: `{ "shared_with": "contador@despacho.mx", "permission": "LECTURA" }`
(`permission`: `LECTURA | ESCRITURA`).

### 5.7 Listar comparticiones — `GET /api/v1/documents/{document_id}/shares`

### 5.8 Añadir tag — `POST /api/v1/documents/{document_id}/tags`

Body: `{ "tag": "revision-2026" }`

---

## 6. Reportes

### 6.1 Reportes gerenciales — `/api/v1/reportes/*`

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/reportes/monthly` | Reporte financiero mensual con KPIs |
| `POST` | `/api/v1/reportes/kpi` | Dashboard de KPIs con alertas |
| `POST` | `/api/v1/reportes/cash-flow` | Análisis de flujo de caja (con proyección) |
| `POST` | `/api/v1/reportes/profit-loss` | Estado de Resultados (P&L) con ISR |
| `GET` | `/api/v1/reportes/` | Lista periodos disponibles |
| `GET` | `/api/v1/reportes/download/{period}` | Descarga en `json/csv/pdf` |

**`POST /api/v1/reportes/monthly`** — body (`MonthlyReportRequest`):

```json
{
  "tenant_id": "default", "month": 7, "year": 2026,
  "revenue": 250000.0, "expenses": 120000.0, "taxes_paid": 30000.0,
  "invoices_count": 45, "prev_revenue": 230000.0
}
```

```json
{ "ok": true, "report": { "period": "2026-07", "revenue": 250000.0,
                          "gross_margin": 52.0, "net": 100000.0 } }
```

**`POST /api/v1/reportes/kpi`** — body (`KPIRequest`):
`tenant_id`, `period` (`YYYY-MM`), `revenue`, `expenses`, `profit`,
`invoices_count`, `avg_ticket`, `days_to_collect`, `data`.

**`POST /api/v1/reportes/cash-flow`** — body (`CashFlowRequest`):
`period`, `opening_balance`, `inflows`, `outflows`, `categories`,
`project_forward`, `monthly_growth_rate`, `projection_months`.

**`POST /api/v1/reportes/profit-loss`** — body (`ProfitLossRequest`):
`period`, `income`, `cost_of_goods_sold`, `operating_expenses`,
`other_income`, `other_expenses`, `isr_rate` (default 0.30), breakdowns.

**`GET /api/v1/reportes/download/{period}?report_type=monthly&format=csv`**
`report_type`: `monthly | cash-flow | profit-loss`; `format`: `json | csv | pdf`.
`404` si no existe el reporte del periodo.

### 6.2 Reportes PDF — `/api/v1/reports/*`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/reports/{type}/{period}` | Genera PDF; cabecera `X-Report-Id` |
| `GET` | `/api/v1/reports/{id}/download` | Descarga un PDF generado |
| `POST` | `/api/v1/reports/custom` | Reporte personalizado (JSON) |

`type` ∈ `invoices | monthly | reconciliation | anomaly | tax`.
`GET /api/v1/reports/monthly/2026-07` devuelve el PDF en `application/pdf`.

### 6.3 DIOT — `/api/v1/diot/*`

**`POST /api/v1/diot/generate`** — body (`GenerateDiotRequest`):

```json
{
  "month": 7, "year": 2026,
  "invoices": [ { "rfc_tercero": "XAXX010101000", "nombre": "Proveedor SA",
                  "tipo_operacion": "Nacional", "monto_neto": 10000.0,
                  "iva_trasladado": 1600.0, "iva_acreditable": 1600.0 } ],
  "tenant_id": null
}
```

```json
{ "ok": true, "message": "DIOT generada para 07/2026.",
  "report_id": "rpt-1", "report": { ... } }
```

**`POST /api/v1/diot/validate`** — body: `{ "invoices": [ ... ] }`

**`GET /api/v1/diot/download/{report_id}`** — XML SAT (`text/plain`).

**`GET /api/v1/diot/history`** — historial de DIOT.

---

## 7. Contabilidad Electrónica

Módulo `/contabilidad-electronica/*` — generación y validación de XML SAT
(no requiere `/api/v1`).

### 7.1 Generar Balanza XML — `POST /contabilidad-electronica/balanza`

Body (`BalanzaRequest`):

```json
{
  "periodo": "2026-07",
  "ejercicio": 2026,
  "mes": 7,
  "rfc": "DESP820101AB1",
  "rows": [ { "cuenta": "101", "saldo_inicial": "0", "debe": "1000",
              "haber": "0", "saldo_final": "1000" } ]
}
```

`rfc` es obligatorio en producción (validación SAT). Respuesta:

```json
{ "estado": "generado", "xml_content": "<BCE:Balanza ...>...</BCE:Balanza>",
  "errores": [] }
```

o `{ "estado": "error", "errores": ["El RFC es obligatorio..."] }`.

### 7.2 Generar Catálogo XML — `POST /contabilidad-electronica/catalogo`

Body: lista de `CatalogoCuenta` (array). Responde `estado: "generado"` con
`xml_content`.

### 7.3 Validar antes de enviar — `POST /contabilidad-electronica/validate`

Body: `{ "balanza": { ... }, "catalogo": [ ... ] }` (ambos opcionales, al menos
uno obligatorio). Devuelve `{ "ok": bool, "errores": [...], "balanza": {...},
"catalogo": {...} }`.

### 7.4 Obligaciones SAT — `GET /contabilidad-electronica/obligaciones/{rfc}`

```json
{ "rfc": "DESP820101AB1", "regimen": "601",
  "mensuales": ["Declaración mensual de IVA", "Declaración mensual de ISR", ...],
  "anuales": ["Declaración anual de ISR", ...],
  "contabilidad_electronica": true, "fecha_consulta": "2026-08-02 12:00:00" }
```

---

## 8. Conciliación bancaria

Módulo `/api/v1/conciliacion/*` — upload de estados de cuenta, matching con
CFDI/pólizas, ajustes, discrepancias y exportación.

### 8.1 Subir estado de cuenta — `POST /api/v1/conciliacion/upload`

multipart `file` (CSV con columnas `id,date,description,amount,type,reference,
bank_account`). Query `period` (YYYY-MM, auto-detectado).

```json
{ "ok": true, "statement_id": "stmt-2026-07-1", "period": "2026-07",
  "transaction_count": 150, "file_name": "banco.csv" }
```

`422` CSV inválido.

### 8.2 Matching — `POST /api/v1/conciliacion/match`

Body (`MatchRequest`):

```json
{
  "bank_transactions": [ { "id": "t1", "date": "2026-07-15", "amount": 12000.0,
                           "type": "cargo", "reference": "REF-1", "bank_account": "acc-1" } ],
  "cfdi_list": [ { "uuid": "A1B2C3", "fecha": "2026-07-15", "total": 12000.0,
                   "rfc_emisor": "XAXX010101000", "tipo_comprobante": "I" } ],
  "polizas": null,
  "date_tolerance_days": 3
}
```

```json
{ "ok": true, "period": "2026-07", "total_transactions": 1,
  "total_cfdi": 1, "matches": [...], "discrepancies": [...], "report": {...} }
```

### 8.3 Matching desde CSV — `POST /api/v1/conciliacion/match/csv`

multipart `file` (CSV banco) + query `cfdi_json` y `polizas_json` (JSON
string), `date_tolerance_days`.

### 8.4 Conciliación completa — `POST /api/v1/conciliacion/reconcile`

Body (`ReconcileRequest`): `bank_transactions`, `polizas`, `cfdi_list`,
`tolerance_days`, `period`. Devuelve `report` + `summary`
(`matched`, `unmatched`, `match_rate`, `adjustments_proposed`, `total_variance`).

### 8.5 Reporte por periodo — `GET /api/v1/conciliacion/report/{period}`

`404` si no hay reporte para el periodo (aislado por tenant).

### 8.6 Aplicar ajustes — `POST /api/v1/conciliacion/apply`

Body (`ApplyAdjustmentsRequest`): `{ "adjustment_ids": ["adj-1"], "applied_by": "contador@despacho.mx" }`

### 8.7 Listar discrepancias — `GET /api/v1/conciliacion/discrepancies`

Query: `period`, `discrepancy_type` (`monto|fecha|faltante|sobrante|duplicado`),
`min_variance`.

### 8.8 Listar ajustes — `GET /api/v1/conciliacion/adjustments`

Query: `status` (`PROPOSED|APPROVED|REJECTED|APPLIED`).

### 8.9 Exportar CSV — `POST /api/v1/conciliacion/export` · `POST /api/v1/conciliacion/export/download`

Body (`ExportRequest`): `period`, `matches`, `bank_transactions`, `cfdi_list`.
`export` devuelve `{ "csv": "...", "period": "..." }`; `export/download`
descarga como archivo.

---

## 9. Onboarding de tenant y obtención de API key

### 9.1 Crear tenant (emite API key) — `POST /api/v1/tenants`

El flujo real para que un despacho obtenga su API key es **crear el tenant**:

Body (`TenantOnboardRequest`):

```json
{
  "name": "Despacho Contable XYZ",
  "rfc": "DESP820101AB1",
  "erp_type": "contpaqi",
  "plantilla_contable": "SAT",
  "notif_channel": "email",
  "webhook_url": "",
  "user_name": "admin",
  "user_email": "admin@despacho.mx"
}
```

```json
{
  "ok": true,
  "tenant": {
    "id": 1, "name": "Despacho Contable XYZ", "rfc": "DESP820101AB1",
    "user_id": 3, "api_key": "sk_likida_XXXXXXXX"
  }
}
```

> Guarde la `api_key` devuelta: no se puede volver a leer en claro.

### 9.2 Onboarding wizard — `/api/v1/onboarding/*`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/onboarding/status` | Estado del wizard + score |
| `GET` | `/api/v1/onboarding/steps` | Definiciones de pasos |
| `GET` | `/api/v1/onboarding/plans` | Planes con precios |
| `GET` | `/api/v1/onboarding/erp-options` | ERPs disponibles |
| `GET` | `/api/v1/onboarding/step/{step}` | Datos de un paso (1-5) |
| `PUT` | `/api/v1/onboarding/step/{step}` | Envía/valida/persiste un paso |
| `POST` | `/api/v1/onboarding/complete` | Cierra el onboarding |

Pasos: `1=company_profile`, `2=sat_credentials`, `3=erp_connection`,
`4=billing_plan`, `5=first_cfdi`. Todos requieren que la key tenga tenant
(`403` si la key es de servicio).

---

## 10. Batch v2 y misceláneo

### 10.1 Procesar lote de CFDI — `POST /api/v2/batch`

Body (`BatchRequest`): `{ "paths": ["/data/cfdi/1.xml", ...], "folder": null,
"async": true, "webhook": true }`. Hasta 1000 CFDIs. Si `async=false`,
procesa síncrono.

### 10.2 Estado del lote — `GET /api/v2/batch/{job_id}`

---

## 11. Buenas prácticas de integración

- Enviar **siempre** `X-API-Key` en cada request.
- Usar `Idempotency-Key` en operaciones de escritura (idempotencia 24h TTL).
- Respetar el rate limit (300 req/min); reintentar con `Retry-After`.
- Para subidas grandes, usar multipart y mantener < 10 MB (docs < 15 MB).
- El aislamiento multi-tenant es automático: cada key solo ve su tenant.
- Para errores transitorios (`429`, `500`, `502`), implementar backoff
  exponencial con `Retry-After` / `Retry-After`.
- Regenerar el contrato local tras cambios de API:
  `B2B_API_KEY=<k> B2B_JWT_SECRET=<s> B2B_ENCRYPTION_KEY=<e> B2B_ENV=development python scripts/export_openapi.py`
