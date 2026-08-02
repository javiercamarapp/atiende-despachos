# API Reference — Likida AI Enterprise — API

## Likida AI Enterprise — API Documentation

### Authentication
All endpoints (except `/health` and `/api/v1/leads`) require authentication via the `X-API-Key` header.

#### API Key Authentication
curl -H "X-API-Key: ***" https://api.likida.ai/api/v1/stats
```

#### JWT Bearer Token (Auth endpoints)
```
curl -H "Authorization: Bearer ***" https://api.likida.ai/api/v1/stats

### Versioning
The API supports simultaneous v1 and v2 endpoints:
- `/api/v1/` — Legacy, deprecated (sunset: 2027-01-01)
- `/api/v2/` — Current, recommended

Use the `Accept-Version` header for version negotiation, or include the version in the URL path.

### Rate Limiting
Requests are rate-limited per tenant/endpoint. Check response headers:
- `X-RateLimit-Limit` — Maximum requests per window
- `X-RateLimit-Remaining` — Remaining requests
- `X-RateLimit-Reset` — Window reset timestamp
- `Retry-After` — Seconds to wait (on 429)

### Idempotency
Write endpoints accept an `Idempotency-Key` header (UUID recommended) to prevent duplicate mutations from network retries. Cached for 24 hours.

### Error Handling
All errors return structured JSON with:
- Numeric error code (by category)
- Error type identifier
- Human-readable message (no PII)
- Trace ID for debugging

### Webhooks
Register webhooks via `POST /api/v2/webhooks` to receive event notifications. Supported events:
- `invoice_processed` — When a CFDI is processed
- `batch_completed` — When a batch job finishes
- `reconciliation_done` — When reconciliation completes


- **Versión:** 0.1.0
- **Rutas:** 284 · **Schemas:** 152
- **Base URL (local):** `http://localhost:8000`
- **Base URL (producción):** `https://api.likida.ai`
- **Interactiva:** `GET /docs` (Swagger), `GET /redoc`
- **Contrato:** `GET /openapi.json`

> Documento **auto-generado** por `scripts/generate_api_docs.py` desde el spec OpenAPI real (`app.openapi()`). No editar a mano.

---

## Autenticación

La API se asegura con **API key** y, en los módulos de auth/portal, con **JWT Bearer**. Ambas viven en el contrato OpenAPI:

| Esquema | Tipo | Header |
|---|---|---|
| `ApiKeyAuth` | apiKey | `X-API-Key` (en header) |
| `BearerAuth` | http | `` (en header) |
| `IdempotencyKey` | apiKey | `Idempotency-Key` (en header) |

### Flujo API key

1. Emite una API key al crear un tenant o mediante la env `B2B_API_KEY`.
2. Envía la key en el header de cada petición:

```http
X-API-Key: demo-<key>
```

Cada key resuelve un `tenant_id` (aislamiento multi-tenant). Si la key coincide con `B2B_API_KEY` se trata como key de servicio.

### Flujo JWT (módulos de auth)

```http
Authorization: Bearer <jwt>
```

### Respuestas de error estándar

| Código | Significado |
|---|---|
| `400` | Petición mal formada / error de negocio |
| `401` | Falta o es inválida la credencial |
| `403` | Credencial válida pero sin permiso |
| `404` | Recurso no encontrado |
| `413` | Payload excede el límite |
| `422` | Validación de schemas/reglas falló |
| `429` | Rate limit superado |
| `500` | Error interno |

---

## RBAC — Permisos y roles

La plataforma implementa control de acceso por **permiso** (convención `<recurso>:<acción>`). Cada rol agrupa una lista de permisos.

### Permisos disponibles

- `cfdi:read`
- `cfdi:write`
- `nominas:read`
- `nominas:write`
- `reportes:read`
- `reportes:write`
- `billing:read`
- `billing:write`
- `settings:read`
- `settings:write`
- `users:manage`
- `pipeline:run`
- `bank_feeds:view`
- `bank_feeds:sync`
- `bank_feeds:manage`
- `documents:delete`

### Roles por defecto

| Rol | Permisos |
|---|---|
| `admin` | `cfdi:read`, `cfdi:write`, `nominas:read`, `nominas:write`, `reportes:read`, `reportes:write`, `billing:read`, `billing:write`, `settings:read`, `settings:write`, `users:manage`, `pipeline:run`, `bank_feeds:view`, `bank_feeds:sync`, `bank_feeds:manage`, `documents:delete` |
| `contador` | `cfdi:read`, `cfdi:write`, `nominas:read`, `nominas:write`, `reportes:read`, `billing:read`, `settings:read` |
| `auditor` | `cfdi:read`, `nominas:read`, `reportes:read`, `billing:read`, `settings:read` |
| `readonly` | `cfdi:read`, `reportes:read` |

> Los permisos se aplican sobre los módulos de pipeline (`pipeline:run`), bank feeds (`bank_feeds:*`) y gestión documental (`documents:delete`), entre otros.

---

## Endpoints

| Método | Ruta | Resumen |
|---|---|---|
| `GET` | `/admin/dashboard/clients` | Paginated list of clients with sorting and filtering. |
| `GET` | `/admin/dashboard/clients/{client_id}` | Detailed view of a single client. |
| `GET` | `/admin/dashboard/health` | System health check. |
| `GET` | `/admin/dashboard/overview` | Admin dashboard overview: clients, revenue, CFDI counts. |
| `GET` | `/admin/dashboard/revenue` | Revenue report: MRR, ARR, churn, per-client average. |
| `GET` | `/admin/dashboard/usage` | Usage metrics for the last N days. |
| `GET` | `/api/v1/accounting/balance` | Balanza de comprobación desde facturas de la DB. |
| `GET` | `/api/v1/accounting/catalog` | Catálogo de cuentas (CUC). |
| `POST` | `/api/v1/accounting/sat/send` | Envía la balanza al SAT (MOCK). |
| `GET` | `/api/v1/alerts` | List alerts with optional filters. |
| `GET` | `/api/v1/alerts/deadlines` | Próximos vencimientos fiscales SAT (30 días). |
| `POST` | `/api/v1/alerts/evaluate` | Evaluate data against rules and return new alerts. |
| `GET,POST` | `/api/v1/alerts/rules` | List alert rules. |
| `GET` | `/api/v1/alerts/stats` | Alert statistics by severity and type. |
| `GET,DELETE` | `/api/v1/alerts/{alert_id}` | Get alert detail by ID. |
| `POST` | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge an alert. |
| `POST` | `/api/v1/alerts/{alert_id}/dismiss` | Dismiss an alert. |
| `GET` | `/api/v1/alerts/{alert_id}/history` | Get history / audit trail for an alert. |
| `GET` | `/api/v1/ap/aging` | AP aging report |
| `GET,POST` | `/api/v1/ap/invoices` | List AP invoices |
| `POST` | `/api/v1/ap/pay` | Schedule and/or execute AP payments |
| `GET` | `/api/v1/ar/aging` | AR aging report |
| `POST` | `/api/v1/ar/collect` | Process AR collection |
| `POST` | `/api/v1/ar/complement` | Generate payment complement |
| `GET,POST` | `/api/v1/ar/invoices` | List AR invoices |
| `POST` | `/api/v1/arco/cancelacion/{email}` | Cancelación ARCO: elimina datos personales del titular. |
| `GET` | `/api/v1/arco/datos/{email}` | Acceso ARCO: devuelve datos personales del titular. |
| `GET` | `/api/v1/arco/estatus/{email}` | Consultar estatus de solicitudes ARCO. |
| `POST` | `/api/v1/arco/solicitud` | Enviar solicitud ARCO (Acceso/Rectificación/Cancelación/Oposición). |
| `POST` | `/api/v1/auth/login` | Login email+password → tokens JWT. |
| `GET,PUT` | `/api/v1/auth/me` | Usuario autenticado. |
| `POST` | `/api/v1/auth/refresh` | Refresca la sesión con un refresh token. |
| `POST` | `/api/v1/auth/register` | Alta de usuario (bootstrap o admin). |
| `GET,POST` | `/api/v1/bank-feeds/accounts` | Lista cuentas bancarias del tenant. |
| `GET` | `/api/v1/bank-feeds/accounts/{account_id}` | Detalle de una cuenta. |
| `POST` | `/api/v1/bank-feeds/accounts/{account_id}/sync` | Ejecuta una sincronización del feed. |
| `GET` | `/api/v1/bank-feeds/accounts/{account_id}/syncs` | Historial de sincronizaciones de la cuenta. |
| `GET` | `/api/v1/bank-feeds/accounts/{account_id}/transactions` | Lista transacciones de una cuenta. |
| `POST` | `/api/v1/bank-feeds/reconcile` | Cruza transacciones con CFDI/pólizas. |
| `POST` | `/api/v1/bank-feeds/transactions/{txn_id}/categorize` | Categoriza una transacción. |
| `POST` | `/api/v1/billing/checkout` | Inicia un checkout y procesa el pago. |
| `GET` | `/api/v1/billing/invoices` | Lista las facturas del tenant. |
| `GET` | `/api/v1/billing/plans` | Lista los planes y precios. |
| `POST` | `/api/v1/billing/subscription` | Crea/activa una suscripción a un plan. |
| `POST` | `/api/v1/billing/webhook` | Recibe eventos del proveedor de pagos. |
| `POST` | `/api/v1/bookkeeping/override` | Submit a human override for a CFDI classification |
| `POST` | `/api/v1/bookkeeping/pipeline/run` | Ejecutar el pipeline de contabilidad (alias de /process) |
| `POST` | `/api/v1/bookkeeping/process` | Process CFDIs through the bookkeeping pipeline |
| `GET` | `/api/v1/bookkeeping/status` | Get bookkeeping pipeline status |
| `GET` | `/api/v1/bookkeeping/suggestions` | Get CFDIs needing human review with suggestions |
| `POST` | `/api/v1/clientes/deductibility` | Get deductibility information for an expense concept. |
| `GET` | `/api/v1/clientes/faq` | List FAQ entries, optionally filtered by category. |
| `POST` | `/api/v1/clientes/query` | Process a client query and generate a draft response. |
| `GET` | `/api/v1/clientes/status/{cfdi_id}` | Get invoice status by CFDI UUID. |
| `POST` | `/api/v1/close/approve-step` | Approve or reject a close checklist step |
| `POST` | `/api/v1/close/finalize` | Finalize (close) the accounting period |
| `GET` | `/api/v1/close/list` | List all close periods |
| `POST` | `/api/v1/close/run-automatic` | Execute all automatic close steps |
| `POST` | `/api/v1/close/start` | Start a monthly close process |
| `GET` | `/api/v1/close/status` | Get close status and progress |
| `GET` | `/api/v1/collections/aging` | Reporte de antigüedad de la cartera. |
| `POST` | `/api/v1/collections/analyze` | Analiza la cartera pendiente (clasifica por antigüedad y calcula score). |
| `GET` | `/api/v1/collections/score/{invoice_id}` | Score de cobrabilidad de una factura. |
| `POST` | `/api/v1/collections/send-reminder` | Genera (y opcionalmente registra) un recordatorio. |
| `GET` | `/api/v1/conciliacion/adjustments` | List all proposed adjustments. |
| `POST` | `/api/v1/conciliacion/apply` | Apply approved reconciliation adjustments. |
| `GET` | `/api/v1/conciliacion/discrepancies` | List all discrepancies across all periods. |
| `POST` | `/api/v1/conciliacion/export` | Export reconciliation results to CSV. |
| `POST` | `/api/v1/conciliacion/export/download` | Download reconciliation CSV as a file. |
| `POST` | `/api/v1/conciliacion/match` | Match bank transactions with polizas and/or CFDI references. |
| `POST` | `/api/v1/conciliacion/match/csv` | Upload a bank statement CSV file for matching. |
| `POST` | `/api/v1/conciliacion/reconcile` | Run full bank reconciliation with polizas and/or CFDI. |
| `GET` | `/api/v1/conciliacion/report/{period}` | Get reconciliation report for a period. |
| `POST` | `/api/v1/conciliacion/upload` | Upload a bank statement file (CSV) for reconciliation. |
| `POST` | `/api/v1/contabilidad/asientos` | Registra un asiento contable. |
| `GET,POST` | `/api/v1/contabilidad/balanza/{periodo}` | Descarga la balanza de comprobación en XML (SAT). |
| `GET,POST` | `/api/v1/contabilidad/catalogo` | Lista el catálogo de cuentas del tenant. |
| `POST` | `/api/v1/contabilidad/electronica/{periodo}` | Genera el paquete de contabilidad electrónica del mes. |
| `GET` | `/api/v1/contabilidad/electronica/{periodo}/download` | Descarga el XML listo para el SAT (catálogo + balanza). |
| `GET` | `/api/v1/dashboard` | Dashboard web con métricas en vivo. |
| `GET` | `/api/v1/dashboard/analytics` | Analytics dashboard: cross-module aggregation with period comparison and insights. |
| `GET` | `/api/v1/dashboard/anomalies` | Anomalías detectadas por severidad y tipo. |
| `GET` | `/api/v1/dashboard/by-provider` | Facturas por proveedor (top 10 por monto). |
| `GET` | `/api/v1/dashboard/data` | Datos del dashboard en JSON (refresh en vivo). |
| `GET` | `/api/v1/dashboard/kpi` | Métricas clave (tiempo, error, % automático). |
| `GET` | `/api/v1/dashboard/monthly` | Facturas, montos y anomalías agrupados por mes. |
| `GET` | `/api/v1/dashboard/reconciliation` | Estado de la conciliación bancaria. |
| `GET` | `/api/v1/dashboard/summary` | Totales de facturas procesadas, monto total y estado. |
| `GET` | `/api/v1/declaraciones/deadlines` | Get upcoming deadlines for a tenant. |
| `POST` | `/api/v1/declaraciones/isr-anual` | Generate an annual ISR declaration. |
| `POST` | `/api/v1/declaraciones/isr-provisional` | Generate a monthly ISR provisional declaration. |
| `POST` | `/api/v1/declaraciones/iva` | Generate a monthly IVA declaration draft. |
| `POST` | `/api/v1/declaraciones/reminders` | Send reminders for upcoming deadlines. |
| `GET` | `/api/v1/declaraciones/tenant/{tenant_id}` | List all declarations for a tenant. |
| `GET` | `/api/v1/declaraciones/{declaracion_id}` | Get a declaration by ID. |
| `PUT` | `/api/v1/declaraciones/{declaracion_id}/status` | Update declaration status. |
| `POST` | `/api/v1/declarations/calculate` | Calculate taxes (IVA, ISR, IEPS, DIOT) |
| `POST` | `/api/v1/declarations/generate` | Generate XML declaration or DIOT pipe-delimited file |
| `GET` | `/api/v1/declarations/status` | Check declaration submission status |
| `POST` | `/api/v1/declarations/submit` | Submit signed declaration to SAT |
| `POST` | `/api/v1/devolucion-iva/calcular` | Calculate IVA refund amount from declarations. |
| `POST` | `/api/v1/devolucion-iva/conciliar` | Run conciliation CFDI ↔ DIOT ↔ Declarations. |
| `POST` | `/api/v1/devolucion-iva/diot` | Generate DIOT entries from invoice data. |
| `GET` | `/api/v1/devolucion-iva/historical` | List all past refund requests. |
| `GET` | `/api/v1/devolucion-iva/papel-trabajo/{periodo}` | Generate and retrieve the conciliation working paper. |
| `POST` | `/api/v1/devolucion-iva/recopilar` | Collect and classify invoices for a period. |
| `POST` | `/api/v1/devolucion-iva/solicitud` | Prepare a refund request for SAT submission. |
| `GET` | `/api/v1/devolucion-iva/status/{solicitud_id}` | Check the status of a refund request. |
| `GET` | `/api/v1/diot/download/{report_id}` | Download DIOT as XML file. |
| `POST` | `/api/v1/diot/generate` | Generate DIOT report from invoice data. |
| `GET` | `/api/v1/diot/history` | List DIOT generation history. |
| `POST` | `/api/v1/diot/validate` | Validate invoice data before DIOT generation. |
| `GET` | `/api/v1/documents/search` | Busca documentos. |
| `POST` | `/api/v1/documents/upload` | Sube un documento. |
| `GET,DELETE` | `/api/v1/documents/{document_id}` | Obtiene metadata de un documento. |
| `GET` | `/api/v1/documents/{document_id}/content` | Descarga el contenido del documento. |
| `POST` | `/api/v1/documents/{document_id}/share` | Comparte un documento. |
| `GET` | `/api/v1/documents/{document_id}/shares` | Lista comparticiones. |
| `POST` | `/api/v1/documents/{document_id}/tags` | Añade un tag a un documento. |
| `GET` | `/api/v1/documents/{document_id}/versions` | Historial de versiones. |
| `POST` | `/api/v1/email/add` | Add an email to the processing queue. |
| `GET` | `/api/v1/email/history` | Get processing history for a tenant. |
| `POST` | `/api/v1/email/process` | Process a batch of extracted invoices. |
| `POST` | `/api/v1/email/scan` | Scan inbox for emails with XML/PDF attachments. |
| `GET` | `/api/v1/email/stats` | Get processing statistics across all batches. |
| `POST` | `/api/v1/fiscal/compare` | Compare ERP records against SAT declarations. |
| `GET` | `/api/v1/fiscal/report/{report_id}` | Get a fiscal conciliation report. |
| `POST` | `/api/v1/fiscal/resolve` | Mark an omission or discrepancy as resolved. |
| `GET` | `/api/v1/invoices` | Lista facturas con filtros. |
| `POST` | `/api/v1/invoices/process` | Procesa un CFDI (XML) por el pipeline completo. |
| `GET` | `/api/v1/invoices/{invoice_id}` | Detalle de una factura por id. |
| `POST` | `/api/v1/leads` | Alta de lead desde la landing (público). |
| `POST` | `/api/v1/notas-credito` | Create a credit note |
| `POST` | `/api/v1/notifications/config` | Guarda configuración de WhatsApp del tenant. |
| `POST` | `/api/v1/notifications/email` | Envía un email (SMTP) o lo encola. |
| `GET` | `/api/v1/notifications/history` | Historial de notificaciones persistidas. |
| `PUT` | `/api/v1/notifications/preferences` | Guarda preferencias de notificación del tenant. |
| `POST` | `/api/v1/notifications/send` | Encola/envía una notificación WhatsApp. |
| `POST` | `/api/v1/onboarding/complete` | Cierra el onboarding (valida que todos los pasos estén completos). |
| `GET` | `/api/v1/onboarding/erp-options` | Opciones de ERP disponibles. |
| `GET` | `/api/v1/onboarding/plans` | Opciones de planes de facturación con precios. |
| `GET` | `/api/v1/onboarding/status` | Estado del onboarding + score de readiness. |
| `GET,PUT` | `/api/v1/onboarding/step/{step}` | Lee los datos de un paso específico. |
| `GET` | `/api/v1/onboarding/steps` | Lista de definiciones de todos los pasos del wizard. |
| `POST` | `/api/v1/outreach/campaigns` | Launch Campaign |
| `POST` | `/api/v1/outreach/campaigns/{campaign_id}/pause` | Pause Campaign |
| `POST` | `/api/v1/outreach/campaigns/{campaign_id}/resume` | Resume Campaign |
| `GET` | `/api/v1/outreach/lead-score/{lead_id}` | Lead Score |
| `GET,POST` | `/api/v1/outreach/leads` | List Leads |
| `POST` | `/api/v1/outreach/send` | Send Email |
| `GET` | `/api/v1/outreach/stats/{campaign_id}` | Campaign Stats |
| `POST` | `/api/v1/outreach/track/click` | Track Click |
| `POST` | `/api/v1/outreach/track/open` | Track Open |
| `POST` | `/api/v1/payroll/calculate` | Calcula una nómina (ISR, IMSS, INFONAVIT) y opcional nómina CFDI. |
| `POST` | `/api/v1/pipeline/run` | Ejecuta el flujo completo CFDI → bookkeeping → conciliación. |
| `POST` | `/api/v1/reconcile/approve` | Approve or reject a reconciliation match |
| `POST` | `/api/v1/reconcile/run` | Ejecuta una conciliación bancaria. |
| `GET` | `/api/v1/reconcile/status` | Get reconciliation status and results |
| `POST` | `/api/v1/reconcile/upload` | Upload bank statement and run auto-reconciliation |
| `POST` | `/api/v1/reconciliacion-ingresos/balance-iva` | Calcular balance de IVA para un período. |
| `POST` | `/api/v1/reconciliacion-ingresos/clasificar` | Clasificar depósitos bancarios por tipo fiscal. |
| `POST` | `/api/v1/reconciliacion-ingresos/conciliar` | Conciliar depósitos bancarios con auxiliares contables. |
| `GET` | `/api/v1/reconciliacion-ingresos/discrepancias/{periodo}` | Obtener discrepancias de conciliación para un período. |
| `GET` | `/api/v1/reconciliacion-ingresos/papel-trabajo/{periodo}` | Obtener papel de trabajo de conciliación. |
| `POST` | `/api/v1/reconciliacion-ingresos/recopilar` | Recopilar depósitos bancarios y auxiliares contables. |
| `POST` | `/api/v1/reconciliation/confirm` | Confirma manualmente un cruce transacción-factura. |
| `GET` | `/api/v1/reconciliation/matches` | Cruces automáticos calculados (con confidence). |
| `GET` | `/api/v1/reconciliation/report` | Reporte de conciliación de la sesión actual. |
| `POST` | `/api/v1/reconciliation/upload` | Sube un estado de cuenta (CSV/PDF) y lo carga. |
| `GET` | `/api/v1/reportes/` | List all available report periods. |
| `POST` | `/api/v1/reportes/cash-flow` | Generate cash flow analysis. |
| `GET` | `/api/v1/reportes/download/{period}` | Download a report in the specified format. |
| `POST` | `/api/v1/reportes/kpi` | Generate a KPI dashboard for the given period. |
| `POST` | `/api/v1/reportes/monthly` | Generate a monthly financial report. |
| `POST` | `/api/v1/reportes/profit-loss` | Generate a Profit & Loss (Estado de Resultados) statement. |
| `POST` | `/api/v1/reports/custom` | Genera un reporte personalizado a partir de JSON (data + template). Devuelve PDF por defecto. |
| `GET` | `/api/v1/reports/{report_id}/download` | Descarga un reporte previamente generado por id. |
| `GET` | `/api/v1/reports/{report_type}/{period}` | Genera un reporte PDF del periodo (tipo en invoices/monthly/reconciliation/anomaly/tax). |
| `GET` | `/api/v1/retenciones/calcular` | Calculate ISR retention |
| `GET` | `/api/v1/roles` | Lista los roles (builtin + custom del tenant). |
| `POST` | `/api/v1/roles/assign` | Asigna un rol a un usuario del tenant. [users:manage] |
| `DELETE` | `/api/v1/roles/assignments/{user_role_id}` | Quita una asignación de rol. [users:manage] |
| `GET` | `/api/v1/roles/check` | Verifica si el usuario autenticado tiene un permiso. |
| `POST` | `/api/v1/roles/custom` | Crea un rol custom para el tenant. [users:manage] |
| `GET` | `/api/v1/roles/me/permissions` | Permisos efectivos del usuario autenticado en su tenant. |
| `GET` | `/api/v1/roles/permissions` | Catálogo de permisos reconocidos por la plataforma. |
| `POST` | `/api/v1/roles/seed` | Siembra los roles por defecto (idempotente). [users:manage] |
| `GET` | `/api/v1/roles/users/{user_id}` | Roles efectivos de un usuario en el tenant. |
| `GET,PUT,DELETE` | `/api/v1/roles/{role_id}` | Detalle de un rol. |
| `POST` | `/api/v1/sat/download` | Descarga masiva de CFDI por rango. |
| `POST` | `/api/v1/sat/schedule` | Programa descarga diaria / verificación semanal. |
| `GET` | `/api/v1/sat/status` | Estado de sesión y scheduler SAT. |
| `POST` | `/api/v1/sat/verify` | Verifica estatus y cadena de un CFDI. |
| `GET` | `/api/v1/stats` | Métricas agregadas (totales y por categoría). |
| `POST` | `/api/v1/tenants` | Onboarding de un nuevo cliente (tenant). |
| `GET,POST` | `/api/v1/tenants/{tenant_id}/users` | Lista los usuarios del tenant. |
| `PUT` | `/api/v1/tenants/{tenant_id}/users/{user_id}/role` | Cambia el rol de un usuario (admin). |
| `GET` | `/api/v1/tools` | Tools registradas en el agente. |
| `POST` | `/api/v1/vencimientos/acknowledge` | Mark a deadline as completed. |
| `POST` | `/api/v1/vencimientos/calculate` | Calculate fiscal deadlines for a period. |
| `GET` | `/api/v1/vencimientos/escalations` | Get escalation history. |
| `GET` | `/api/v1/vencimientos/overdue` | Get overdue fiscal deadlines. |
| `GET` | `/api/v1/vencimientos/summary` | Get deadline summary. |
| `GET` | `/api/v1/vencimientos/upcoming` | Get upcoming fiscal deadlines. |
| `POST` | `/api/v1/webhooks/email` | Recibe facturas por email (mock Mailgun/SendGrid). |
| `POST` | `/api/v1/webhooks/notify` | Entrega un resultado de factura al webhook del tenant. |
| `POST` | `/api/v1/webhooks/retry` | Reintenta entregas de webhook pendientes (worker). |
| `GET,POST` | `/api/v1/webhooks/subscriptions` | Lista la URL de webhook del tenant. |
| `GET` | `/api/v2/analytics` | Analytics avanzado por tenant (cache TTL). |
| `GET` | `/api/v2/audit` | Log completo de auditoría por tenant. |
| `POST` | `/api/v2/batch` | Procesa hasta 1000 CFDI en lote. |
| `GET` | `/api/v2/batch/{job_id}` | Estado y resultado de un lote async. |
| `POST` | `/api/v2/export` | Exporta datos a CSV/XLSX/PDF. |
| `GET` | `/api/v2/health` | Health detallado del servicio. |
| `POST` | `/api/v2/retention/purge` | Aplica la política de retención de datos (admin). |
| `GET,POST` | `/api/v2/tenants` | Lista tenants + uso (admin). |
| `PATCH` | `/api/v2/tenants/{tid}` | Configura un tenant (admin). |
| `POST` | `/api/v2/tenants/{tid}/block` | Bloquea un tenant (deja de poder autenticarse). |
| `POST` | `/api/v2/tenants/{tid}/unblock` | Desbloquea un tenant. |
| `GET` | `/api/v2/tenants/{tid}/usage` | Uso de un tenant (admin). |
| `GET` | `/api/v2/usage` | Uso del tenant (calls, facturas). |
| `GET,POST` | `/api/v2/webhooks` | Lista las suscripciones de webhook del tenant. |
| `DELETE` | `/api/v2/webhooks/{subscription_id}` | Elimina una suscripción de webhook. |
| `POST` | `/contabilidad-electronica/balanza` | Genera el XML de Balanza de Comprobación SAT. |
| `POST` | `/contabilidad-electronica/catalogo` | Genera el XML de Catálogo de Cuentas SAT. |
| `GET` | `/contabilidad-electronica/obligaciones/{rfc}` | Consulta las obligaciones fiscales de un RFC. |
| `POST` | `/contabilidad-electronica/validate` | Valida balanza y/o catálogo antes de envío al SAT. |
| `POST` | `/contabilidad/balanza` | Parsea Balanza de Comprobación de un XML SAT. |
| `GET` | `/contabilidad/catalog` | Catálogo SAT de contabilidad electrónica. |
| `POST` | `/contabilidad/catalogo` | Parsea Catálogo de Cuentas de un XML SAT. |
| `POST` | `/contabilidad/electronica/hash` | Calcula el hash SHA-1 de un contenido (requisito SAT). |
| `POST` | `/contabilidad/electronica/package` | Genera el paquete de contabilidad electrónica del mes. |
| `GET` | `/contabilidad/electronica/status/{package_id}` | Obtiene el estado de un paquete de contabilidad electrónica. |
| `GET` | `/contabilidad/electronica/summary/{package_id}` | Resumen mensual de contabilidad electrónica. |
| `POST` | `/contabilidad/electronica/transition` | Avanza el estado de un paquete de contabilidad electrónica. |
| `POST` | `/contabilidad/estado-resultados` | Parsea Estado de Resultados de un XML SAT. |
| `GET` | `/health` | Health |
| `GET` | `/health/detailed` | Health Detailed |
| `GET` | `/invoices` | Invoices Legacy |
| `GET` | `/metrics` | Metrics Endpoint |
| `GET` | `/metrics/prometheus` | Metrics Prometheus |
| `POST` | `/nomina-completa/cfdi` | Genera un CFDI de Nómina 1.2. |
| `GET` | `/nomina-completa/payslip/{employee_id}` | Descarga el recibo de nómina de un empleado. |
| `POST` | `/nomina-completa/process` | Procesa nómina completa para un periodo. |
| `GET` | `/nomina-completa/summary` | Resumen de nómina procesada por periodo. |
| `POST` | `/nomina-completa/taxes` | Calcula impuestos individuales (ISR, IMSS, INFONAVIT). |
| `GET` | `/nomina/catalog` | Catálogo SAT de códigos de nómina. |
| `POST` | `/nomina/parse` | Parsea complemento Nomina 1.2 de un CFDI XML. |
| `POST` | `/nomina/validate` | Valida un CFDI con complemento Nomina 1.2 contra reglas SAT. |
| `GET` | `/pagos/catalog` | Catálogo SAT de códigos de pagos. |
| `POST` | `/pagos/parse` | Parsea complemento Pagos 1.1 de un CFDI XML. |
| `POST` | `/pagos/validate` | Valida un CFDI con complemento Pagos 1.1 contra reglas SAT. |
| `GET` | `/portal/activity` | Portal Activity |
| `GET` | `/portal/alertas` | Portal Alertas |
| `POST` | `/portal/auth/confirm` | Portal Confirm |
| `POST` | `/portal/auth/login` | Portal Login |
| `POST` | `/portal/auth/logout` | Portal Logout |
| `POST` | `/portal/auth/magic-link` | Portal Magic Link |
| `GET` | `/portal/auth/me` | Portal Me |
| `GET` | `/portal/cfdis` | Portal Cfdis |
| `GET` | `/portal/dashboard/stats` | Portal Stats |
| `GET` | `/portal/declaraciones` | Portal Declaraciones |
| `GET` | `/portal/invoices.json` | Portal Invoices |
| `GET` | `/portal/invoices/export.csv` | Portal Export |
| `POST` | `/portal/invoices/upload` | Portal Upload |
| `GET` | `/portal/invoices/{job_or_id}/status` | Portal Invoice Status |
| `GET` | `/portal/metrics` | Portal Metrics |
| `GET` | `/portal/notifications` | Notifications Json |
| `PUT` | `/portal/settings` | Settings Update |
| `GET` | `/portal/summary` | Portal Summary |
| `POST` | `/pre-auditoria/cff-compliance` | Verifica compliance con el CFF. |
| `POST` | `/pre-auditoria/consistency` | Verifica la consistencia del libro de contabilidad. |
| `POST` | `/pre-auditoria/deductibility` | Verifica la deducibilidad de gastos (Art. 28 LISR). |
| `GET` | `/pre-auditoria/history` | Historial de auditorías previas. |
| `GET` | `/pre-auditoria/report/{composite_id}` | Obtiene un reporte de auditoría guardado. |
| `POST` | `/pre-auditoria/run` | Ejecuta una pre-auditoría contable completa. |
| `POST` | `/process` | Process Legacy |
| `POST` | `/reportes/balance` | Genera un Balance General (Estado de Situación Financiera). |
| `POST` | `/reportes/conciliacion` | Genera un reporte de Conciliación Bancaria. |
| `POST` | `/reportes/estado-resultados` | Genera un Estado de Resultados. |
| `GET` | `/reportes/formats` | Lista los formatos de salida disponibles. |
| `POST` | `/reportes/nomina` | Genera un Reporte de Nómina por periodo. |
| `GET` | `/stats` | Stats Legacy |
| `GET` | `/tools` | Tools Legacy |

## Grupo: `/admin`

### `/admin/dashboard/clients`

#### **GET** `/admin/dashboard/clients`

_Paginated list of clients with sorting and filtering._

Returns a paginated, sortable, filterable list of clients.

**Tags:** `admin-dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `page` | query | `integer` | no | Page number |
| `page_size` | query | `integer` | no | Items per page |
| `sort_by` | query | `string` | no | Sort field: name, id, invoice_count, monto_total, api_calls |
| `sort_order` | query | `string` | no | Sort order: asc or desc |
| `search` | query | `any` | no | Search by name or RFC |
| `active_only` | query | `boolean` | no | Only active clients |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/admin/dashboard/clients/{client_id}`

#### **GET** `/admin/dashboard/clients/{client_id}`

_Detailed view of a single client._

Returns detailed metrics for a specific client.

**Tags:** `admin-dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `client_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/admin/dashboard/health`

#### **GET** `/admin/dashboard/health`

_System health check._

Returns system health: uptime, DB size, error rate.

**Tags:** `admin-dashboard`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/admin/dashboard/overview`

#### **GET** `/admin/dashboard/overview`

_Admin dashboard overview: clients, revenue, CFDI counts._

Returns top-level admin metrics: total clients, active clients, MRR, CFDIs this month.

**Tags:** `admin-dashboard`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/admin/dashboard/revenue`

#### **GET** `/admin/dashboard/revenue`

_Revenue report: MRR, ARR, churn, per-client average._

Returns revenue metrics for the admin.

**Tags:** `admin-dashboard`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/admin/dashboard/usage`

#### **GET** `/admin/dashboard/usage`

_Usage metrics for the last N days._

Returns usage metrics: daily CFDIs, avg processing time, error rate.

**Tags:** `admin-dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `days` | query | `integer` | no | Number of days |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/api`

### `/api/v1/accounting/balance`

#### **GET** `/api/v1/accounting/balance`

_Balanza de comprobación desde facturas de la DB._

**Tags:** `accounting`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/accounting/catalog`

#### **GET** `/api/v1/accounting/catalog`

_Catálogo de cuentas (CUC)._

**Tags:** `accounting`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/accounting/sat/send`

#### **POST** `/api/v1/accounting/sat/send`

_Envía la balanza al SAT (MOCK)._

Presenta la balanza de comprobación al SAT en modo MOCK (acuse simulado). La presentación real requiere e.firma del contribuyente.

**Tags:** `accounting`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `ejercicio` | query | `integer` | sí |  |
| `mes` | query | `integer` | sí |  |
| `rfc` | query | `string` | no |  |
| `periodo` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts`

#### **GET** `/api/v1/alerts`

_List alerts with optional filters._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `severity` | query | `any` | no | Filter by severity |
| `type` | query | `any` | no | Filter by type |
| `status` | query | `any` | no | Filter by status |
| `date_from` | query | `any` | no | Filter by created_at >= (ISO date) |
| `date_to` | query | `any` | no | Filter by created_at <= (ISO date) |
| `limit` | query | `integer` | no | Max results |
| `offset` | query | `integer` | no | Offset for pagination |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/deadlines`

#### **GET** `/api/v1/alerts/deadlines`

_Próximos vencimientos fiscales SAT (30 días)._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `days` | query | `integer` | no | Horizonte en días |
| `companies` | query | `any` | no | JSON list of {rfc, name} company records |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/evaluate`

#### **POST** `/api/v1/alerts/evaluate`

_Evaluate data against rules and return new alerts._

**Tags:** `alerts`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EvaluateRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/rules`

#### **GET** `/api/v1/alerts/rules`

_List alert rules._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `enabled_only` | query | `boolean` | no | Only enabled rules |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/alerts/rules`

_Create an alert rule._

**Tags:** `alerts`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CreateRuleRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/stats`

#### **GET** `/api/v1/alerts/stats`

_Alert statistics by severity and type._

**Tags:** `alerts`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/{alert_id}`

#### **GET** `/api/v1/alerts/{alert_id}`

_Get alert detail by ID._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `alert_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **DELETE** `/api/v1/alerts/{alert_id}`

_Permanently delete an alert._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `alert_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/{alert_id}/acknowledge`

#### **POST** `/api/v1/alerts/{alert_id}/acknowledge`

_Acknowledge an alert._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `alert_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__alertas__routes__AcknowledgeRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/{alert_id}/dismiss`

#### **POST** `/api/v1/alerts/{alert_id}/dismiss`

_Dismiss an alert._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `alert_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `DismissRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/alerts/{alert_id}/history`

#### **GET** `/api/v1/alerts/{alert_id}/history`

_Get history / audit trail for an alert._

**Tags:** `alerts`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `alert_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ap/aging`

#### **GET** `/api/v1/ap/aging`

_AP aging report_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `by_supplier` | query | `boolean` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ap/invoices`

#### **GET** `/api/v1/ap/invoices`

_List AP invoices_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `status` | query | `any` | no |  |
| `rfc_emisor` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/ap/invoices`

_Receive & register a supplier CFDI_

**Tags:** `ap-ar`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `APInvoiceCreate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ap/pay`

#### **POST** `/api/v1/ap/pay`

_Schedule and/or execute AP payments_

**Tags:** `ap-ar`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PayRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ar/aging`

#### **GET** `/api/v1/ar/aging`

_AR aging report_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `by_client` | query | `boolean` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ar/collect`

#### **POST** `/api/v1/ar/collect`

_Process AR collection_

**Tags:** `ap-ar`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CollectRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ar/complement`

#### **POST** `/api/v1/ar/complement`

_Generate payment complement_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `invoice_id` | query | `integer` | sí |  |
| `monto` | query | `number` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/ar/invoices`

#### **GET** `/api/v1/ar/invoices`

_List AR invoices_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `status` | query | `any` | no |  |
| `rfc_receptor` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/ar/invoices`

_Register an issued AR invoice_

**Tags:** `ap-ar`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ARInvoiceCreate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/arco/cancelacion/{email}`

#### **POST** `/api/v1/arco/cancelacion/{email}`

_Cancelación ARCO: elimina datos personales del titular._

Cancelación ARCO — LFPDPPP Art. 33: eliminar datos personales. Nota: Se conservan datos con obligación legal de retención (CFDI, contabilidad electrónica — CFF Art. 82-89, 5 años).

**Tags:** `arco`, `arco`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `email` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/arco/datos/{email}`

#### **GET** `/api/v1/arco/datos/{email}`

_Acceso ARCO: devuelve datos personales del titular._

Acceso ARCO — LFPDPPP Art. 28: devuelve todos los datos personales que el responsable tiene del titular.

**Tags:** `arco`, `arco`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `email` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/arco/estatus/{email}`

#### **GET** `/api/v1/arco/estatus/{email}`

_Consultar estatus de solicitudes ARCO._

Devuelve las solicitudes ARCO registradas para un email.

**Tags:** `arco`, `arco`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `email` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/arco/solicitud`

#### **POST** `/api/v1/arco/solicitud`

_Enviar solicitud ARCO (Acceso/Rectificación/Cancelación/Oposición)._

Endpoint público para recibir solicitudes ARCO de titulares. LFPDPPP Art. 29: el responsable debe registrar cada solicitud y responder en un plazo máximo de 20 días hábiles.

**Tags:** `arco`, `arco`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ARCORequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/auth/login`

#### **POST** `/api/v1/auth/login`

_Login email+password → tokens JWT._

**Tags:** `auth`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `LoginBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/auth/me`

#### **GET** `/api/v1/auth/me`

_Usuario autenticado._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **PUT** `/api/v1/auth/me`

_Actualiza el perfil del usuario autenticado._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `UpdateMeBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/auth/refresh`

#### **POST** `/api/v1/auth/refresh`

_Refresca la sesión con un refresh token._

**Tags:** `auth`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `RefreshBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/auth/register`

#### **POST** `/api/v1/auth/register`

_Alta de usuario (bootstrap o admin)._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `RegisterBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/accounts`

#### **GET** `/api/v1/bank-feeds/accounts`

_Lista cuentas bancarias del tenant._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/bank-feeds/accounts`

_Conecta una cuenta bancaria._

Registra una cuenta bancaria para importar transacciones.

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ConnectAccountRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/accounts/{account_id}`

#### **GET** `/api/v1/bank-feeds/accounts/{account_id}`

_Detalle de una cuenta._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `account_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/accounts/{account_id}/sync`

#### **POST** `/api/v1/bank-feeds/accounts/{account_id}/sync`

_Ejecuta una sincronización del feed._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `account_id` | path | `string` | sí |  |
| `from_date` | query | `any` | no | YYYY-MM-DD |
| `to_date` | query | `any` | no | YYYY-MM-DD |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/accounts/{account_id}/syncs`

#### **GET** `/api/v1/bank-feeds/accounts/{account_id}/syncs`

_Historial de sincronizaciones de la cuenta._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `account_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/accounts/{account_id}/transactions`

#### **GET** `/api/v1/bank-feeds/accounts/{account_id}/transactions`

_Lista transacciones de una cuenta._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `account_id` | path | `string` | sí |  |
| `status` | query | `any` | no |  |
| `category` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/reconcile`

#### **POST** `/api/v1/bank-feeds/reconcile`

_Cruza transacciones con CFDI/pólizas._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__bank_feeds__routes__ReconcileRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bank-feeds/transactions/{txn_id}/categorize`

#### **POST** `/api/v1/bank-feeds/transactions/{txn_id}/categorize`

_Categoriza una transacción._

**Tags:** `bank-feeds`, `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `txn_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CategorizeRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/billing/checkout`

#### **POST** `/api/v1/billing/checkout`

_Inicia un checkout y procesa el pago._

**Tags:** `billing`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CheckoutRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/billing/invoices`

#### **GET** `/api/v1/billing/invoices`

_Lista las facturas del tenant._

**Tags:** `billing`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/billing/plans`

#### **GET** `/api/v1/billing/plans`

_Lista los planes y precios._

**Tags:** `billing`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/billing/subscription`

#### **POST** `/api/v1/billing/subscription`

_Crea/activa una suscripción a un plan._

**Tags:** `billing`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CheckoutRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/billing/webhook`

#### **POST** `/api/v1/billing/webhook`

_Recibe eventos del proveedor de pagos._

Procesa un evento de webhook del proveedor. Verifica la firma HMAC del webhook contra el body crudo antes de procesar. La firma se extrae del header correspondiente al proveedor configurado (Stripe-Signature, Conekta-Signature).

**Tags:** `billing`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bookkeeping/override`

#### **POST** `/api/v1/bookkeeping/override`

_Submit a human override for a CFDI classification_

Allow a human accountant to correct the agent's classification. The agent learns from feedback: repeated corrections for the same RFC improve future predictions.

**Tags:** `bookkeeping`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `OverrideRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bookkeeping/pipeline/run`

#### **POST** `/api/v1/bookkeeping/pipeline/run`

_Ejecutar el pipeline de contabilidad (alias de /process)_

Alias de `/api/v1/bookkeeping/process` para retrocompatibilidad. Ejecuta el pipeline completo: CFDI → clasificación → póliza → ERP.

**Tags:** `bookkeeping`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__bookkeeping__routes__ProcessRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bookkeeping/process`

#### **POST** `/api/v1/bookkeeping/process`

_Process CFDIs through the bookkeeping pipeline_

Process a batch of CFDIs through the full bookkeeping pipeline: CFDI → classification → journal entry → ERP registration. Returns the pipeline job with all results.

**Tags:** `bookkeeping`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__bookkeeping__routes__ProcessRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bookkeeping/status`

#### **GET** `/api/v1/bookkeeping/status`

_Get bookkeeping pipeline status_

Get pipeline status. If job_id is provided, returns that job's details. Otherwise returns overall pipeline status.

**Tags:** `bookkeeping`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Filter by tenant |
| `job_id` | query | `any` | no | Specific job ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/bookkeeping/suggestions`

#### **GET** `/api/v1/bookkeeping/suggestions`

_Get CFDIs needing human review with suggestions_

Get CFDIs that the agent couldn't classify with high confidence, along with alternative suggestions.

**Tags:** `bookkeeping`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Filter by tenant |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/clientes/deductibility`

#### **POST** `/api/v1/clientes/deductibility`

_Get deductibility information for an expense concept._

Return deductibility information for a given expense concept.

**Tags:** `clientes`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Tenant ID |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__clientes__routes__DeductibilityRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/clientes/faq`

#### **GET** `/api/v1/clientes/faq`

_List FAQ entries, optionally filtered by category._

Return FAQ entries. Optionally filter by category.

**Tags:** `clientes`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `category` | query | `any` | no | Filter by category |
| `tenant_id` | query | `string` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/clientes/query`

#### **POST** `/api/v1/clientes/query`

_Process a client query and generate a draft response._

Receive a client query, route it to the correct handler, and return a draft response.

**Tags:** `clientes`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `QueryRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/clientes/status/{cfdi_id}`

#### **GET** `/api/v1/clientes/status/{cfdi_id}`

_Get invoice status by CFDI UUID._

Look up invoice status by CFDI UUID.

**Tags:** `clientes`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `cfdi_id` | path | `string` | sí |  |
| `tenant_id` | query | `string` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/approve-step`

#### **POST** `/api/v1/close/approve-step`

_Approve or reject a close checklist step_

Approve or reject a specific step. Steps that require human approval (e.g., inventory adjustments, declaration drafts) must be explicitly approved before the period can be finalized.

**Tags:** `close-management`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CloseApproveStepRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/finalize`

#### **POST** `/api/v1/close/finalize`

_Finalize (close) the accounting period_

Finalize and close the period. All steps must be approved/skipped and all validations must pass. Use force=true to close despite warnings (not recommended).

**Tags:** `close-management`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CloseFinalizeRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/list`

#### **GET** `/api/v1/close/list`

_List all close periods_

List all close periods for the tenant.

**Tags:** `close-management`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/run-automatic`

#### **POST** `/api/v1/close/run-automatic`

_Execute all automatic close steps_

Execute all automatic close steps with default/empty data. In production, the data comes from the database and integrated agents. This endpoint triggers the full automatic pipeline.

**Tags:** `close-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `close_id` | query | `string` | sí | Close ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/start`

#### **POST** `/api/v1/close/start`

_Start a monthly close process_

Start a new monthly close. Creates the checklist (17 steps) and marks the period as in_progress. Use POST /close/approve-step to advance steps, then POST /close/finalize to close the period.

**Tags:** `close-management`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CloseStartRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/close/status`

#### **GET** `/api/v1/close/status`

_Get close status and progress_

Get the current status of a close process. Returns checklist progress, adjustments, validations, and summary.

**Tags:** `close-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `close_id` | query | `string` | sí | Close ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/collections/aging`

#### **GET** `/api/v1/collections/aging`

_Reporte de antigüedad de la cartera._

Reporte de antigüedad de la cartera persistida en `outstanding_invoices` (requiere haber hecho un analyze con sync=True).

**Tags:** `collections`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/collections/analyze`

#### **POST** `/api/v1/collections/analyze`

_Analiza la cartera pendiente (clasifica por antigüedad y calcula score)._

Recibe la cartera de cuentas por cobrar y la clasifica por antigüedad (0-30, 31-60, 61-90, 90+), calculando el score de cobrabilidad por factura. Si `sync` es True, persiste la cartera en la tabla `outstanding_invoices`.

**Tags:** `collections`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CollectionsAnalyzeRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/collections/score/{invoice_id}`

#### **GET** `/api/v1/collections/score/{invoice_id}`

_Score de cobrabilidad de una factura._

Score de cobrabilidad (0..1) para una factura de la cartera persistida, junto con su historial de intentos de cobranza.

**Tags:** `collections`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `invoice_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/collections/send-reminder`

#### **POST** `/api/v1/collections/send-reminder`

_Genera (y opcionalmente registra) un recordatorio._

Genera el contenido del recordatorio para la etapa y canal dados. NO envía mensajes reales. Si `record` es True, registra el intento en `collection_events` con timestamp.

**Tags:** `collections`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CollectionsSendReminderRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/adjustments`

#### **GET** `/api/v1/conciliacion/adjustments`

_List all proposed adjustments._

List adjustment proposals with optional status filter. SECURITY (P1-3): solo ajustes del tenant autenticado.

**Tags:** `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `status` | query | `any` | no | Filter by status: PROPOSED, APPROVED, REJECTED, APPLIED |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/apply`

#### **POST** `/api/v1/conciliacion/apply`

_Apply approved reconciliation adjustments._

Apply approved adjustments. Updates status to APPLIED. SECURITY (P1-3): solo ajustes del tenant autenticado; un adjustment_id de otro tenant se reporta como not_found.

**Tags:** `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ApplyAdjustmentsRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/discrepancies`

#### **GET** `/api/v1/conciliacion/discrepancies`

_List all discrepancies across all periods._

List discrepancy records with optional period, type, and variance filters. SECURITY (P1-3): solo discrepancias del tenant autenticado.

**Tags:** `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `period` | query | `any` | no | Filter by period |
| `discrepancy_type` | query | `any` | no | Filter by type: monto, fecha, faltante, sobrante, duplicado |
| `min_variance` | query | `number` | no | Minimum variance % to include |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/export`

#### **POST** `/api/v1/conciliacion/export`

_Export reconciliation results to CSV._

Export match results and discrepancies to CSV format.

**Tags:** `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__conciliacion__routes__ExportRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/export/download`

#### **POST** `/api/v1/conciliacion/export/download`

_Download reconciliation CSV as a file._

Download the CSV export as a file attachment.

**Tags:** `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__conciliacion__routes__ExportRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/match`

#### **POST** `/api/v1/conciliacion/match`

_Match bank transactions with polizas and/or CFDI references._

Upload bank transactions and polizas/CFDI list, run matching algorithm, and return match results with confidence scores.

**Tags:** `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `MatchRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/match/csv`

#### **POST** `/api/v1/conciliacion/match/csv`

_Upload a bank statement CSV file for matching._

Upload a bank statement CSV and match against provided CFDI/polizas. CSV should have columns: id, date, description, amount, type, reference, bank_account.

**Tags:** `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `cfdi_json` | query | `string` | no | CFDI list as JSON string |
| `polizas_json` | query | `any` | no | Polizas list as JSON string |
| `date_tolerance_days` | query | `integer` | no |  |

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_match_from_csv_api_v1_conciliacion_match_csv_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/reconcile`

#### **POST** `/api/v1/conciliacion/reconcile`

_Run full bank reconciliation with polizas and/or CFDI._

Full reconciliation: match, detect discrepancies, propose adjustments.

**Tags:** `conciliacion`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__conciliacion__routes__ReconcileRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/report/{period}`

#### **GET** `/api/v1/conciliacion/report/{period}`

_Get reconciliation report for a period._

Retrieve a previously generated reconciliation report by period (YYYY-MM). SECURITY (P1-3): el reporte se lee SOLO del namespace del tenant autenticado; un periodo de otro tenant responde 404.

**Tags:** `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `period` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/conciliacion/upload`

#### **POST** `/api/v1/conciliacion/upload`

_Upload a bank statement file (CSV) for reconciliation._

Upload a bank statement CSV file. CSV should have columns: id, date, description, amount, type, reference, bank_account.

**Tags:** `conciliacion`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `period` | query | `any` | no | Period (YYYY-MM). Auto-detected from data. |

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_upload_bank_statement_api_v1_conciliacion_upload_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/contabilidad/asientos`

#### **POST** `/api/v1/contabilidad/asientos`

_Registra un asiento contable._

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `AsientoRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/contabilidad/balanza/{periodo}`

#### **GET** `/api/v1/contabilidad/balanza/{periodo}`

_Descarga la balanza de comprobación en XML (SAT)._

**Tags:** `contabilidad`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |
| `rfc` | query | `string` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/contabilidad/balanza/{periodo}`

_Genera la balanza de comprobación del mes._

**Tags:** `contabilidad`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/contabilidad/catalogo`

#### **GET** `/api/v1/contabilidad/catalogo`

_Lista el catálogo de cuentas del tenant._

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/contabilidad/catalogo`

_Importa/crea el catálogo de cuentas del SAT._

Carga el catálogo de cuentas del tenant. Acepta la lista de cuentas en el body (cuentas=[{codigo, descripcion, nivel, naturaleza}]). Si no viene, se usa el catálogo SAT por defecto. Reemplaza el anterior.

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CatalogoRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/contabilidad/electronica/{periodo}`

#### **POST** `/api/v1/contabilidad/electronica/{periodo}`

_Genera el paquete de contabilidad electrónica del mes._

**Tags:** `contabilidad`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ContabilidadRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/contabilidad/electronica/{periodo}/download`

#### **GET** `/api/v1/contabilidad/electronica/{periodo}/download`

_Descarga el XML listo para el SAT (catálogo + balanza)._

**Tags:** `contabilidad`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |
| `rfc` | query | `string` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard`

#### **GET** `/api/v1/dashboard`

_Dashboard web con métricas en vivo._

**Tags:** `dashboard`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `text/html` · `string` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/analytics`

#### **GET** `/api/v1/dashboard/analytics`

_Analytics dashboard: cross-module aggregation with period comparison and insights._

**Tags:** `analytics`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `year` | query | `any` | no | Year (YYYY). Default: current. |
| `month` | query | `any` | no | Month (1-12). Default: current. |
| `tenant_id` | query | `any` | no | Tenant override (service key only). |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `AnalyticsResponse` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/anomalies`

#### **GET** `/api/v1/dashboard/anomalies`

_Anomalías detectadas por severidad y tipo._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/by-provider`

#### **GET** `/api/v1/dashboard/by-provider`

_Facturas por proveedor (top 10 por monto)._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/data`

#### **GET** `/api/v1/dashboard/data`

_Datos del dashboard en JSON (refresh en vivo)._

**Tags:** `dashboard`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/kpi`

#### **GET** `/api/v1/dashboard/kpi`

_Métricas clave (tiempo, error, % automático)._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/monthly`

#### **GET** `/api/v1/dashboard/monthly`

_Facturas, montos y anomalías agrupados por mes._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |
| `fecha_desde` | query | `any` | no |  |
| `fecha_hasta` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/reconciliation`

#### **GET** `/api/v1/dashboard/reconciliation`

_Estado de la conciliación bancaria._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/dashboard/summary`

#### **GET** `/api/v1/dashboard/summary`

_Totales de facturas procesadas, monto total y estado._

**Tags:** `dashboard`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no | Tenant (solo key de servicio). |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/deadlines`

#### **GET** `/api/v1/declaraciones/deadlines`

_Get upcoming deadlines for a tenant._

Get upcoming fiscal deadlines for a tenant. Deadlines are sorted by fecha_limite ascending. Status is auto-updated: PENDING → URGENT (≤5 days) → OVERDUE.

**Tags:** `declaraciones`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | sí | Tenant identifier |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/isr-anual`

#### **POST** `/api/v1/declaraciones/isr-anual`

_Generate an annual ISR declaration._

Generate an ISR annual declaration for a given year. ISR Anual is due by April 30th of the following year. Uses the annual progressive tax table (CFF Art. 113).

**Tags:** `declaraciones`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `IsrAnualRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/isr-provisional`

#### **POST** `/api/v1/declaraciones/isr-provisional`

_Generate a monthly ISR provisional declaration._

Generate an ISR provisional declaration for a given month/year. ISR calculation uses the progressive tax table (CFF Art. 113).

**Tags:** `declaraciones`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `IsrProvisionalRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/iva`

#### **POST** `/api/v1/declaraciones/iva`

_Generate a monthly IVA declaration draft._

Generate an IVA declaration draft for a given month/year. IVA calculation: - iva_cobrado: IVA collected from sales - iva_pagado: IVA paid on purchases - saldo_favor: If iva_pagado > iva_cobrado (credit) - saldo_contra: If iva_cobrado > iva_pagado (debit)

**Tags:** `declaraciones`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `IvaRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/reminders`

#### **POST** `/api/v1/declaraciones/reminders`

_Send reminders for upcoming deadlines._

Send reminder notifications for deadlines approaching within days_before. Only sends one reminder per deadline (track via recordatorio_enviado).

**Tags:** `declaraciones`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ReminderRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/tenant/{tenant_id}`

#### **GET** `/api/v1/declaraciones/tenant/{tenant_id}`

_List all declarations for a tenant._

List all declarations for a tenant, optionally filtered by type.

**Tags:** `declaraciones`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | path | `string` | sí |  |
| `tipo` | query | `any` | no | Filter by type (iva, isr_provisional, isr_anual) |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/{declaracion_id}`

#### **GET** `/api/v1/declaraciones/{declaracion_id}`

_Get a declaration by ID._

Retrieve a declaration by its unique ID.

**Tags:** `declaraciones`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `declaracion_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declaraciones/{declaracion_id}/status`

#### **PUT** `/api/v1/declaraciones/{declaracion_id}/status`

_Update declaration status._

Update the status of a declaration. Valid transitions: - draft → pending → filed → accepted/rejected

**Tags:** `declaraciones`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `declaracion_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `UpdateStatusRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declarations/calculate`

#### **POST** `/api/v1/declarations/calculate`

_Calculate taxes (IVA, ISR, IEPS, DIOT)_

Calculate all applicable taxes for a period. Supports: - ISR provisional (PM 30% / PF progressive table) - IVA monthly (trasladado – acreditable) - IEPS (per-product tasa/tarifa) - DIOT aggregation (if invoices provided)

**Tags:** `declarations`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__declaraciones__declaration_api__CalculateRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `CalculateResponse` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declarations/generate`

#### **POST** `/api/v1/declarations/generate`

_Generate XML declaration or DIOT pipe-delimited file_

Generate the declaration file. For IVA/ISR: generates SAT-compliant XML. For DIOT: generates pipe-delimited TXT per RMF 3.10.7.

**Tags:** `declarations`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `GenerateRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `GenerateResponse` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declarations/status`

#### **GET** `/api/v1/declarations/status`

_Check declaration submission status_

Check the status of a submitted declaration.

**Tags:** `declarations`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `declaration_id` | query | `string` | sí | Declaration ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `StatusResponse` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/declarations/submit`

#### **POST** `/api/v1/declarations/submit`

_Submit signed declaration to SAT_

Submit a signed declaration to SAT. Requires: - Signed XML (base64-encoded with Sello, Certificado, NoCertificado) - FIEL/CSD certificate paths (server-side only) Returns: - Status (accepted/rejected/error) - SAT folio (if accepted) - Error details (if rejected)

**Tags:** `declarations`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SubmitRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `SubmitResponse` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/calcular`

#### **POST** `/api/v1/devolucion-iva/calcular`

_Calculate IVA refund amount from declarations._

**Tags:** `devolucion-iva`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CalcularRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/conciliar`

#### **POST** `/api/v1/devolucion-iva/conciliar`

_Run conciliation CFDI ↔ DIOT ↔ Declarations._

**Tags:** `devolucion-iva`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__devolucion_iva__routes__ConciliarRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/diot`

#### **POST** `/api/v1/devolucion-iva/diot`

_Generate DIOT entries from invoice data._

**Tags:** `devolucion-iva`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `DIOTRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/historical`

#### **GET** `/api/v1/devolucion-iva/historical`

_List all past refund requests._

**Tags:** `devolucion-iva`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no | Filter by tenant |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/papel-trabajo/{periodo}`

#### **GET** `/api/v1/devolucion-iva/papel-trabajo/{periodo}`

_Generate and retrieve the conciliation working paper._

**Tags:** `devolucion-iva`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |
| `facturas_json` | query | `any` | no | JSON facturas |
| `diot_json` | query | `any` | no | JSON DIOT entries |
| `declaraciones_json` | query | `any` | no | JSON declaraciones |
| `tenant_id` | query | `any` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/recopilar`

#### **POST** `/api/v1/devolucion-iva/recopilar`

_Collect and classify invoices for a period._

**Tags:** `devolucion-iva`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__devolucion_iva__routes__RecopilarRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/solicitud`

#### **POST** `/api/v1/devolucion-iva/solicitud`

_Prepare a refund request for SAT submission._

**Tags:** `devolucion-iva`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SolicitudRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/devolucion-iva/status/{solicitud_id}`

#### **GET** `/api/v1/devolucion-iva/status/{solicitud_id}`

_Check the status of a refund request._

**Tags:** `devolucion-iva`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `solicitud_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/diot/download/{report_id}`

#### **GET** `/api/v1/diot/download/{report_id}`

_Download DIOT as XML file._

Download the DIOT report as SAT XML.

**Tags:** `diot`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `report_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `text/plain` · `string` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/diot/generate`

#### **POST** `/api/v1/diot/generate`

_Generate DIOT report from invoice data._

Generate a DIOT report for the given period from invoice data.

**Tags:** `diot`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `GenerateDiotRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/diot/history`

#### **GET** `/api/v1/diot/history`

_List DIOT generation history._

Get list of all DIOT reports.

**Tags:** `diot`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no | Filter by tenant |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/diot/validate`

#### **POST** `/api/v1/diot/validate`

_Validate invoice data before DIOT generation._

Validate invoice data for DIOT compliance.

**Tags:** `diot`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ValidateDiotRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/search`

#### **GET** `/api/v1/documents/search`

_Busca documentos._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `q` | query | `any` | no | Texto de búsqueda |
| `category` | query | `any` | no |  |
| `tag` | query | `any` | no | Tag a filtrar (repetible) |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/upload`

#### **POST** `/api/v1/documents/upload`

_Sube un documento._

**Tags:** `document-management`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_upload_document_api_v1_documents_upload_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}`

#### **GET** `/api/v1/documents/{document_id}`

_Obtiene metadata de un documento._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **DELETE** `/api/v1/documents/{document_id}`

_Elimina físicamente un documento. [documents:delete]_

Hard delete: borra la fila de `documents` y sus dependencias (versions + shares) junto con el blob de storage.

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}/content`

#### **GET** `/api/v1/documents/{document_id}/content`

_Descarga el contenido del documento._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}/share`

#### **POST** `/api/v1/documents/{document_id}/share`

_Comparte un documento._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `object`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}/shares`

#### **GET** `/api/v1/documents/{document_id}/shares`

_Lista comparticiones._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}/tags`

#### **POST** `/api/v1/documents/{document_id}/tags`

_Añade un tag a un documento._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `object`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/documents/{document_id}/versions`

#### **GET** `/api/v1/documents/{document_id}/versions`

_Historial de versiones._

**Tags:** `document-management`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `document_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/email/add`

#### **POST** `/api/v1/email/add`

_Add an email to the processing queue._

Add an email with attachments for processing.

**Tags:** `email_processing`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EmailAddRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/email/history`

#### **GET** `/api/v1/email/history`

_Get processing history for a tenant._

Return recent processing results.

**Tags:** `email_processing`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Tenant ID |
| `limit` | query | `integer` | no | Max results |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/email/process`

#### **POST** `/api/v1/email/process`

_Process a batch of extracted invoices._

Validate and process extracted CFDI invoices.

**Tags:** `email_processing`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__email_processing__routes__ProcessRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/email/scan`

#### **POST** `/api/v1/email/scan`

_Scan inbox for emails with XML/PDF attachments._

Scan a list of emails for attachments that could be CFDI invoices.

**Tags:** `email_processing`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ScanRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/email/stats`

#### **GET** `/api/v1/email/stats`

_Get processing statistics across all batches._

Return aggregate processing statistics.

**Tags:** `email_processing`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/fiscal/compare`

#### **POST** `/api/v1/fiscal/compare`

_Compare ERP records against SAT declarations._

Compare ERP and SAT records for a given period, detecting omissions and discrepancies.

**Tags:** `fiscal`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CompareRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/fiscal/report/{report_id}`

#### **GET** `/api/v1/fiscal/report/{report_id}`

_Get a fiscal conciliation report._

Retrieve a fiscal conciliation report by ID.

**Tags:** `fiscal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `report_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/fiscal/resolve`

#### **POST** `/api/v1/fiscal/resolve`

_Mark an omission or discrepancy as resolved._

Resolve an omission or discrepancy in a fiscal comparison.

**Tags:** `fiscal`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ResolveRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/invoices`

#### **GET** `/api/v1/invoices`

_Lista facturas con filtros._

**Tags:** `invoices`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |
| `categoria` | query | `any` | no |  |
| `valido` | query | `any` | no |  |
| `fecha_desde` | query | `any` | no |  |
| `fecha_hasta` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/invoices/process`

#### **POST** `/api/v1/invoices/process`

_Procesa un CFDI (XML) por el pipeline completo._

Recibe el XML de un CFDI — como subida multipart (campo xml_file) o como JSON con xml_path — y devuelve el resultado del pipeline: validación, clasificación, póliza ERP y el id de la factura en la DB.

**Tags:** `invoices`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/invoices/{invoice_id}`

#### **GET** `/api/v1/invoices/{invoice_id}`

_Detalle de una factura por id._

**Tags:** `invoices`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `invoice_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/leads`

#### **POST** `/api/v1/leads`

_Alta de lead desde la landing (público)._

Registra un lead de la landing. Endpoint público (no requiere key).

**Tags:** `crm`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `LeadRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notas-credito`

#### **POST** `/api/v1/notas-credito`

_Create a credit note_

**Tags:** `ap-ar`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CreditNoteCreate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notifications/config`

#### **POST** `/api/v1/notifications/config`

_Guarda configuración de WhatsApp del tenant._

**Tags:** `notifications`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `NotificationConfigRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notifications/email`

#### **POST** `/api/v1/notifications/email`

_Envía un email (SMTP) o lo encola._

**Tags:** `notifications`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EmailSendRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notifications/history`

#### **GET** `/api/v1/notifications/history`

_Historial de notificaciones persistidas._

**Tags:** `notifications`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notifications/preferences`

#### **PUT** `/api/v1/notifications/preferences`

_Guarda preferencias de notificación del tenant._

**Tags:** `notifications`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `NotificationPreferencesRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/notifications/send`

#### **POST** `/api/v1/notifications/send`

_Encola/envía una notificación WhatsApp._

**Tags:** `notifications`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `NotificationSendRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/complete`

#### **POST** `/api/v1/onboarding/complete`

_Cierra el onboarding (valida que todos los pasos estén completos)._

**Tags:** `onboarding`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/erp-options`

#### **GET** `/api/v1/onboarding/erp-options`

_Opciones de ERP disponibles._

**Tags:** `onboarding`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/plans`

#### **GET** `/api/v1/onboarding/plans`

_Opciones de planes de facturación con precios._

**Tags:** `onboarding`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/status`

#### **GET** `/api/v1/onboarding/status`

_Estado del onboarding + score de readiness._

**Tags:** `onboarding`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/step/{step}`

#### **GET** `/api/v1/onboarding/step/{step}`

_Lee los datos de un paso específico._

**Tags:** `onboarding`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `step` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **PUT** `/api/v1/onboarding/step/{step}`

_Envía y valida un paso del wizard._

**Tags:** `onboarding`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `step` | path | `integer` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `object`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/onboarding/steps`

#### **GET** `/api/v1/onboarding/steps`

_Lista de definiciones de todos los pasos del wizard._

**Tags:** `onboarding`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/campaigns`

#### **POST** `/api/v1/outreach/campaigns`

_Launch Campaign_

Lanzar campaña de outreach.

**Tags:** `outreach`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CampaignCreate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/campaigns/{campaign_id}/pause`

#### **POST** `/api/v1/outreach/campaigns/{campaign_id}/pause`

_Pause Campaign_

Pausar campaña.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `campaign_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/campaigns/{campaign_id}/resume`

#### **POST** `/api/v1/outreach/campaigns/{campaign_id}/resume`

_Resume Campaign_

Reanudar campaña.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `campaign_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/lead-score/{lead_id}`

#### **GET** `/api/v1/outreach/lead-score/{lead_id}`

_Lead Score_

Score de un lead.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `lead_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/leads`

#### **GET** `/api/v1/outreach/leads`

_List Leads_

Listar leads de outreach.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `campaign_id` | query | `any` | no |  |
| `status` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/outreach/leads`

_Create Lead_

Crear un lead para outreach.

**Tags:** `outreach`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `LeadCreate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/send`

#### **POST** `/api/v1/outreach/send`

_Send Email_

Enviar email individual.

**Tags:** `outreach`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EmailSend`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/stats/{campaign_id}`

#### **GET** `/api/v1/outreach/stats/{campaign_id}`

_Campaign Stats_

Estadísticas de campaña.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `campaign_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/track/click`

#### **POST** `/api/v1/outreach/track/click`

_Track Click_

Trackear click en link.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `lead_id` | query | `integer` | sí |  |
| `email_id` | query | `integer` | sí |  |
| `link_id` | query | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/outreach/track/open`

#### **POST** `/api/v1/outreach/track/open`

_Track Open_

Trackear apertura de email.

**Tags:** `outreach`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `lead_id` | query | `integer` | sí |  |
| `email_id` | query | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/payroll/calculate`

#### **POST** `/api/v1/payroll/calculate`

_Calcula una nómina (ISR, IMSS, INFONAVIT) y opcional nómina CFDI._

**Tags:** `payroll`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PayrollRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/pipeline/run`

#### **POST** `/api/v1/pipeline/run`

_Ejecuta el flujo completo CFDI → bookkeeping → conciliación._

Un solo endpoint que hace todo el flujo. parse → adapt → generate_entries → reconcile_with_bank. El tenant se toma del token autenticado.

**Tags:** `pipeline`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PipelineRunRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconcile/approve`

#### **POST** `/api/v1/reconcile/approve`

_Approve or reject a reconciliation match_

Approve or reject a specific match in a reconciliation job. Approved matches are persisted to the database.

**Tags:** `reconcile-agent`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ApprovalRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconcile/run`

#### **POST** `/api/v1/reconcile/run`

_Ejecuta una conciliación bancaria._

Cruza facturas contra movimientos bancarios (monto+fecha+referencia) y devuelve el reporte completo de conciliación.

**Tags:** `reconcile`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__api__app__ReconcileRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconcile/status`

#### **GET** `/api/v1/reconcile/status`

_Get reconciliation status and results_

Get the status and results of a reconciliation job. Returns the full reconciliation result including matches, unmatched items, and alerts.

**Tags:** `reconcile-agent`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `job_id` | query | `string` | sí | Job ID from upload |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconcile/upload`

#### **POST** `/api/v1/reconcile/upload`

_Upload bank statement and run auto-reconciliation_

Upload a bank statement (CSV, OFX, QIF, MT940, PDF) and automatically reconcile against book records. Returns a job_id to poll via GET /reconcile/status.

**Tags:** `reconcile-agent`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_reconcile_upload_api_v1_reconcile_upload_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/balance-iva`

#### **POST** `/api/v1/reconciliacion-ingresos/balance-iva`

_Calcular balance de IVA para un período._

Calculate IVA balance from declarations and classified deposits.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `BalanceIVARequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/clasificar`

#### **POST** `/api/v1/reconciliacion-ingresos/clasificar`

_Clasificar depósitos bancarios por tipo fiscal._

Classify deposits as income, financing, partner contribution, guarantee, or other.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ClasificarRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/conciliar`

#### **POST** `/api/v1/reconciliacion-ingresos/conciliar`

_Conciliar depósitos bancarios con auxiliares contables._

Run full reconciliation between bank deposits and auxiliary entries.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__reconciliacion_ingresos_egresos__routes__ConciliarRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/discrepancias/{periodo}`

#### **GET** `/api/v1/reconciliacion-ingresos/discrepancias/{periodo}`

_Obtener discrepancias de conciliación para un período._

Retrieve discrepancies found during reconciliation for a period.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |
| `tenant_id` | query | `any` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/papel-trabajo/{periodo}`

#### **GET** `/api/v1/reconciliacion-ingresos/papel-trabajo/{periodo}`

_Obtener papel de trabajo de conciliación._

Retrieve the working paper for a given period.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | path | `string` | sí |  |
| `tenant_id` | query | `any` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliacion-ingresos/recopilar`

#### **POST** `/api/v1/reconciliacion-ingresos/recopilar`

_Recopilar depósitos bancarios y auxiliares contables._

Collect and validate bank deposits and auxiliary entries for a period.

**Tags:** `reconciliacion-ingresos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__reconciliacion_ingresos_egresos__routes__RecopilarRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliation/confirm`

#### **POST** `/api/v1/reconciliation/confirm`

_Confirma manualmente un cruce transacción-factura._

Confirma que la transacción `transaction_id` concilia la factura `invoice_id`. El cruce queda marcado method=manual, confidence=100.

**Tags:** `reconciliation`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ConfirmRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliation/matches`

#### **GET** `/api/v1/reconciliation/matches`

_Cruces automáticos calculados (con confidence)._

Recalcula (si `refresh=True`) y devuelve los cruces con su confidence score 0-100. Cruza contra las facturas del tenant en DB.

**Tags:** `reconciliation`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `refresh` | query | `boolean` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliation/report`

#### **GET** `/api/v1/reconciliation/report`

_Reporte de conciliación de la sesión actual._

Genera el reporte agregado de conciliación (conciliados, pendientes, tasas, por método) para el tenant.

**Tags:** `reconciliation`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reconciliation/upload`

#### **POST** `/api/v1/reconciliation/upload`

_Sube un estado de cuenta (CSV/PDF) y lo carga._

Sube el estado de cuenta como multipart (campo `file`) e indica el banco (campo `bank`): bbva, banorte, santander, hsbc o generico. Parsea los movimientos y los carga en la sesión del tenant.

**Tags:** `reconciliation`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_upload_statement_api_v1_reconciliation_upload_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/`

#### **GET** `/api/v1/reportes/`

_List all available report periods._

List all available report periods for a tenant.

**Tags:** `reportes_gerenciales`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `string` | no | Tenant ID |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/cash-flow`

#### **POST** `/api/v1/reportes/cash-flow`

_Generate cash flow analysis._

Generate cash flow with optional forward projection.

**Tags:** `reportes_gerenciales`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CashFlowRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/download/{period}`

#### **GET** `/api/v1/reportes/download/{period}`

_Download a report in the specified format._

Export a report in the specified format.

**Tags:** `reportes_gerenciales`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `period` | path | `string` | sí |  |
| `tenant_id` | query | `string` | no | Tenant ID |
| `report_type` | query | `string` | no | Report type: monthly, cash-flow, profit-loss |
| `format` | query | `string` | no | Export format: json, csv, pdf |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/kpi`

#### **POST** `/api/v1/reportes/kpi`

_Generate a KPI dashboard for the given period._

Generate a KPI dashboard with alerts for out-of-target metrics.

**Tags:** `reportes_gerenciales`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `KPIRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/monthly`

#### **POST** `/api/v1/reportes/monthly`

_Generate a monthly financial report._

Generate a monthly financial summary with KPIs.

**Tags:** `reportes_gerenciales`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `MonthlyReportRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reportes/profit-loss`

#### **POST** `/api/v1/reportes/profit-loss`

_Generate a Profit & Loss (Estado de Resultados) statement._

Generate P&L with ISR/IVA estimation.

**Tags:** `reportes_gerenciales`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ProfitLossRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reports/custom`

#### **POST** `/api/v1/reports/custom`

_Genera un reporte personalizado a partir de JSON (data + template). Devuelve PDF por defecto._

**Tags:** `reports`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CustomReportRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reports/{report_id}/download`

#### **GET** `/api/v1/reports/{report_id}/download`

_Descarga un reporte previamente generado por id._

**Tags:** `reports`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `report_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/reports/{report_type}/{period}`

#### **GET** `/api/v1/reports/{report_type}/{period}`

_Genera un reporte PDF del periodo (tipo en invoices/monthly/reconciliation/anomaly/tax)._

Genera y devuelve el PDF de un reporte. Cabecera X-Report-Id.

**Tags:** `reports`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `report_type` | path | `string` | sí |  |
| `period` | path | `string` | sí |  |
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/retenciones/calcular`

#### **GET** `/api/v1/retenciones/calcular`

_Calculate ISR retention_

**Tags:** `ap-ar`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `proveedor_rfc` | query | `string` | sí |  |
| `tipo_servicio` | query | `string` | no |  |
| `monto_factura` | query | `number` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles`

#### **GET** `/api/v1/roles`

_Lista los roles (builtin + custom del tenant)._

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/assign`

#### **POST** `/api/v1/roles/assign`

_Asigna un rol a un usuario del tenant. [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `AssignRoleRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/assignments/{user_role_id}`

#### **DELETE** `/api/v1/roles/assignments/{user_role_id}`

_Quita una asignación de rol. [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `user_role_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/check`

#### **GET** `/api/v1/roles/check`

_Verifica si el usuario autenticado tiene un permiso._

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `permission` | query | `string` | sí | Permiso a verificar, ej: cfdi:write |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/custom`

#### **POST** `/api/v1/roles/custom`

_Crea un rol custom para el tenant. [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CreateCustomRoleRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/me/permissions`

#### **GET** `/api/v1/roles/me/permissions`

_Permisos efectivos del usuario autenticado en su tenant._

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/permissions`

#### **GET** `/api/v1/roles/permissions`

_Catálogo de permisos reconocidos por la plataforma._

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/seed`

#### **POST** `/api/v1/roles/seed`

_Siembra los roles por defecto (idempotente). [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/users/{user_id}`

#### **GET** `/api/v1/roles/users/{user_id}`

_Roles efectivos de un usuario en el tenant._

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `user_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/roles/{role_id}`

#### **GET** `/api/v1/roles/{role_id}`

_Detalle de un rol._

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `role_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **PUT** `/api/v1/roles/{role_id}`

_Actualiza un rol (permisos/descripción/nombre). [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `role_id` | path | `string` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `UpdateRoleRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **DELETE** `/api/v1/roles/{role_id}`

_Elimina un rol custom. [users:manage]_

**Tags:** `roles`, `rbac`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `role_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `object` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/sat/download`

#### **POST** `/api/v1/sat/download`

_Descarga masiva de CFDI por rango._

**Tags:** `sat`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SATDownloadRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/sat/schedule`

#### **POST** `/api/v1/sat/schedule`

_Programa descarga diaria / verificación semanal._

**Tags:** `sat`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SATScheduleRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/sat/status`

#### **GET** `/api/v1/sat/status`

_Estado de sesión y scheduler SAT._

**Tags:** `sat`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/sat/verify`

#### **POST** `/api/v1/sat/verify`

_Verifica estatus y cadena de un CFDI._

**Tags:** `sat`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SATVerifyRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/stats`

#### **GET** `/api/v1/stats`

_Métricas agregadas (totales y por categoría)._

**Tags:** `stats`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/tenants`

#### **POST** `/api/v1/tenants`

_Onboarding de un nuevo cliente (tenant)._

Crea un tenant + su configuración + API key de onboarding.

**Tags:** `tenants`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `TenantOnboardRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/tenants/{tenant_id}/users`

#### **GET** `/api/v1/tenants/{tenant_id}/users`

_Lista los usuarios del tenant._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | path | `integer` | sí |  |
| `authorization` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/tenants/{tenant_id}/users`

_Crea un usuario en el tenant._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | path | `integer` | sí |  |
| `authorization` | header | `any` | no |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CreateUserBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/tenants/{tenant_id}/users/{user_id}/role`

#### **PUT** `/api/v1/tenants/{tenant_id}/users/{user_id}/role`

_Cambia el rol de un usuario (admin)._

**Tags:** `auth`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | path | `integer` | sí |  |
| `user_id` | path | `integer` | sí |  |
| `authorization` | header | `any` | no |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ChangeRoleBody`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/tools`

#### **GET** `/api/v1/tools`

_Tools registradas en el agente._

**Tags:** `system`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/acknowledge`

#### **POST** `/api/v1/vencimientos/acknowledge`

_Mark a deadline as completed._

Mark a deadline as completed with optional proof.

**Tags:** `vencimientos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__vencimientos__routes__AcknowledgeRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/calculate`

#### **POST** `/api/v1/vencimientos/calculate`

_Calculate fiscal deadlines for a period._

Calculate standard fiscal deadlines for a given period.

**Tags:** `vencimientos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__vencimientos__routes__CalculateRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/escalations`

#### **GET** `/api/v1/vencimientos/escalations`

_Get escalation history._

Get all escalation events.

**Tags:** `vencimientos`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/overdue`

#### **GET** `/api/v1/vencimientos/overdue`

_Get overdue fiscal deadlines._

Get deadlines that are past their due date.

**Tags:** `vencimientos`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/summary`

#### **GET** `/api/v1/vencimientos/summary`

_Get deadline summary._

Get a summary of all deadlines.

**Tags:** `vencimientos`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/vencimientos/upcoming`

#### **GET** `/api/v1/vencimientos/upcoming`

_Get upcoming fiscal deadlines._

Get deadlines that are approaching within N days.

**Tags:** `vencimientos`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `days_ahead` | query | `integer` | no | Días a proyectar |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/webhooks/email`

#### **POST** `/api/v1/webhooks/email`

_Recibe facturas por email (mock Mailgun/SendGrid)._

**Tags:** `webhooks`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EmailInbound`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/webhooks/notify`

#### **POST** `/api/v1/webhooks/notify`

_Entrega un resultado de factura al webhook del tenant._

**Tags:** `webhooks`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `NotifyRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/webhooks/retry`

#### **POST** `/api/v1/webhooks/retry`

_Reintenta entregas de webhook pendientes (worker)._

**Tags:** `webhooks`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v1/webhooks/subscriptions`

#### **GET** `/api/v1/webhooks/subscriptions`

_Lista la URL de webhook del tenant._

**Tags:** `webhooks`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v1/webhooks/subscriptions`

_Registra la URL de webhook del tenant._

**Tags:** `webhooks`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `Subscription`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/analytics`

#### **GET** `/api/v2/analytics`

_Analytics avanzado por tenant (cache TTL)._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `periodo` | query | `any` | no |  |
| `desde` | query | `any` | no |  |
| `hasta` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/audit`

#### **GET** `/api/v2/audit`

_Log completo de auditoría por tenant._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tool` | query | `any` | no |  |
| `action` | query | `any` | no |  |
| `entity` | query | `any` | no |  |
| `desde` | query | `any` | no |  |
| `hasta` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |
| `offset` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/batch`

#### **POST** `/api/v2/batch`

_Procesa hasta 1000 CFDI en lote._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `BatchRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/batch/{job_id}`

#### **GET** `/api/v2/batch/{job_id}`

_Estado y resultado de un lote async._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `job_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/export`

#### **POST** `/api/v2/export`

_Exporta datos a CSV/XLSX/PDF._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__api__v2__ExportRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/health`

#### **GET** `/api/v2/health`

_Health detallado del servicio._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/retention/purge`

#### **POST** `/api/v2/retention/purge`

_Aplica la política de retención de datos (admin)._

Ejecuta enforce_retention(days): borra audit_log, webhooks, notificaciones y sesiones del portal más viejos que `days` días. Solo para la key de servicio (tenant_id=None). Las facturas (datos fiscales) NO se tocan.

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `days` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/tenants`

#### **GET** `/api/v2/tenants`

_Lista tenants + uso (admin)._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v2/tenants`

_Onboarding de un tenant (admin)._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `name` | query | `string` | sí |  |
| `rfc` | query | `string` | no |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `TenantConfigRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/tenants/{tid}`

#### **PATCH** `/api/v2/tenants/{tid}`

_Configura un tenant (admin)._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tid` | path | `integer` | sí |  |

**Request body**

**Content-Type:** `application/json`  
**Schema:** `TenantConfigRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/tenants/{tid}/block`

#### **POST** `/api/v2/tenants/{tid}/block`

_Bloquea un tenant (deja de poder autenticarse)._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tid` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/tenants/{tid}/unblock`

#### **POST** `/api/v2/tenants/{tid}/unblock`

_Desbloquea un tenant._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tid` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/tenants/{tid}/usage`

#### **GET** `/api/v2/tenants/{tid}/usage`

_Uso de un tenant (admin)._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tid` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/usage`

#### **GET** `/api/v2/usage`

_Uso del tenant (calls, facturas)._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/webhooks`

#### **GET** `/api/v2/webhooks`

_Lista las suscripciones de webhook del tenant._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `event` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

#### **POST** `/api/v2/webhooks`

_Registra webhooks para eventos del tenant._

**Tags:** `enterprise`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `WebhookRegister`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/api/v2/webhooks/{subscription_id}`

#### **DELETE** `/api/v2/webhooks/{subscription_id}`

_Elimina una suscripción de webhook._

**Tags:** `enterprise`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `subscription_id` | path | `integer` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/contabilidad-electronica`

### `/contabilidad-electronica/balanza`

#### **POST** `/contabilidad-electronica/balanza`

_Genera el XML de Balanza de Comprobación SAT._

Genera el XML de Balanza de Comprobación conforme al XSD del SAT. Recibe periodo, ejercicio, mes y las líneas de la balanza. Retorna el XML listo para envío o errores de validación.

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `BalanzaRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad-electronica/catalogo`

#### **POST** `/contabilidad-electronica/catalogo`

_Genera el XML de Catálogo de Cuentas SAT._

Genera el XML del Catálogo de Cuentas conforme al XSD del SAT. Recibe la lista de cuentas y el ejercicio fiscal. Retorna el XML listo para envío o errores de validación.

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `array[CatalogoCuenta]`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad-electronica/obligaciones/{rfc}`

#### **GET** `/contabilidad-electronica/obligaciones/{rfc}`

_Consulta las obligaciones fiscales de un RFC._

Retorna las obligaciones fiscales mensuales y anuales de un RFC, incluyendo si requiere contabilidad electrónica.

**Tags:** `contabilidad-electronica`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `rfc` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad-electronica/validate`

#### **POST** `/contabilidad-electronica/validate`

_Valida balanza y/o catálogo antes de envío al SAT._

Valida balanza y/o catálogo contra las reglas del SAT. Retorna ok=true si todo está válido, o la lista de errores.

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `Body_validate_endpoint_contabilidad_electronica_validate_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/contabilidad`

### `/contabilidad/balanza`

#### **POST** `/contabilidad/balanza`

_Parsea Balanza de Comprobación de un XML SAT._

Recibe un archivo XML de contabilidad electrónica y extrae la Balanza de Comprobación. Retorna los datos como JSON o 404 si no hay nodo Balanza.

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_parse_balanza_endpoint_contabilidad_balanza_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/catalog`

#### **GET** `/contabilidad/catalog`

_Catálogo SAT de contabilidad electrónica._

Retorna los catálogos SAT para naturaleza de cuenta y tipo de balance.

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/catalogo`

#### **POST** `/contabilidad/catalogo`

_Parsea Catálogo de Cuentas de un XML SAT._

Recibe un archivo XML de contabilidad electrónica y extrae el Catálogo de Cuentas. Retorna los datos como JSON o 404 si no hay nodo Catalogo.

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_parse_catalogo_endpoint_contabilidad_catalogo_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/electronica/hash`

#### **POST** `/contabilidad/electronica/hash`

_Calcula el hash SHA-1 de un contenido (requisito SAT)._

Calcula el hash SHA-1 en hexadecimal del contenido enviado. El SAT exige SHA-1 como checksum del archivo de catálogo/balanza.

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `HashRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/electronica/package`

#### **POST** `/contabilidad/electronica/package`

_Genera el paquete de contabilidad electrónica del mes._

Genera un paquete de contabilidad electrónica SAT para el período dado, incluyendo catálogo de cuentas, balanza de comprobación y sus hashes SHA-1. Devuelve el paquete completo con un `package_id` único para consultas posteriores.

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PackageRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/electronica/status/{package_id}`

#### **GET** `/contabilidad/electronica/status/{package_id}`

_Obtiene el estado de un paquete de contabilidad electrónica._

Devuelve el estado actual de un paquete previamente generado.

**Tags:** `contabilidad-electronica`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `package_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/electronica/summary/{package_id}`

#### **GET** `/contabilidad/electronica/summary/{package_id}`

_Resumen mensual de contabilidad electrónica._

Devuelve el resumen mensual (totales debe/haber, cuentas, si cuadra) de un paquete previamente generado.

**Tags:** `contabilidad-electronica`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `package_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/electronica/transition`

#### **POST** `/contabilidad/electronica/transition`

_Avanza el estado de un paquete de contabilidad electrónica._

Transita el paquete al estado indicado. Transiciones válidas: borrador → listo_para_timbrar → timbrado → enviado

**Tags:** `contabilidad-electronica`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `TransitionRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/contabilidad/estado-resultados`

#### **POST** `/contabilidad/estado-resultados`

_Parsea Estado de Resultados de un XML SAT._

Recibe un archivo XML de contabilidad electrónica y extrae el Estado de Resultados. Retorna los datos como JSON o 404 si no hay nodo EstadoResultados.

**Tags:** `contabilidad`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_parse_estado_resultados_endpoint_contabilidad_estado_resultados_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/health`

### `/health`

#### **GET** `/health`

_Health_

**Tags:** `system`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/health/detailed`

#### **GET** `/health/detailed`

_Health Detailed_

Estado detallado del servicio: DB, Redis, disco, memoria, uptime. Requiere API key. `status` es "ok" o "degraded"; los componentes en falla se listan en `degraded_components`.

**Tags:** `system`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/invoices`

### `/invoices`

#### **GET** `/invoices`

_Invoices Legacy_

DEPRECATED: use GET /api/v1/invoices instead.

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/metrics`

### `/metrics`

#### **GET** `/metrics`

_Metrics Endpoint_

Métricas operativas básicas (request count, latencia por ruta, códigos de estado). Requiere API key. Exento de rate-limit.

**Tags:** `system`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/metrics/prometheus`

#### **GET** `/metrics/prometheus`

_Metrics Prometheus_

Métricas en formato Prometheus text exposition (operativas, de negocio y custom por tenant). Público, exento de rate-limit y de CORS para que Prometheus pueda scrapearlo sin auth.

**Tags:** `system`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/nomina-completa`

### `/nomina-completa/cfdi`

#### **POST** `/nomina-completa/cfdi`

_Genera un CFDI de Nómina 1.2._

Genera un CFDI de nómina a partir de datos procesados. En producción incluiría timbrado SAT.

**Tags:** `nomina-completa`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CFDINominaRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina-completa/payslip/{employee_id}`

#### **GET** `/nomina-completa/payslip/{employee_id}`

_Descarga el recibo de nómina de un empleado._

Retorna el recibo de nómina individual de un empleado. El tenant se deriva SIEMPRE del contexto autenticado (auth_info), no del query param del cliente, para evitar IDOR multi-tenant.

**Tags:** `nomina-completa`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `employee_id` | path | `string` | sí |  |
| `month` | query | `integer` | sí |  |
| `year` | query | `integer` | sí |  |
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina-completa/process`

#### **POST** `/nomina-completa/process`

_Procesa nómina completa para un periodo._

Calcula ISR, IMSS e INFONAVIT para cada empleado. Retorna el periodo de nómina con desglose por empleado y totales.

**Tags:** `nomina-completa`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ProcessPayrollRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina-completa/summary`

#### **GET** `/nomina-completa/summary`

_Resumen de nómina procesada por periodo._

Retorna el resumen agregado de un periodo de nómina. El tenant se deriva SIEMPRE del contexto autenticado (auth_info), no del query param del cliente, para evitar IDOR multi-tenant.

**Tags:** `nomina-completa`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `month` | query | `integer` | sí |  |
| `year` | query | `integer` | sí |  |
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina-completa/taxes`

#### **POST** `/nomina-completa/taxes`

_Calcula impuestos individuales (ISR, IMSS, INFONAVIT)._

Calcula los impuestos de nómina para un salario individual.

**Tags:** `nomina-completa`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `TaxesRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/nomina`

### `/nomina/catalog`

#### **GET** `/nomina/catalog`

_Catálogo SAT de códigos de nómina._

Retorna los catálogos SAT para código de periodicidad, tipo nómina, tipo de jornada y riesgo del puesto.

**Tags:** `nomina`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina/parse`

#### **POST** `/nomina/parse`

_Parsea complemento Nomina 1.2 de un CFDI XML._

Recibe un archivo CFDI 4.0 (XML) y extrae el complemento Nomina 1.2. Retorna los campos de nómina como JSON o 404 si no hay complemento.

**Tags:** `nomina`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_parse_nomina_endpoint_nomina_parse_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/nomina/validate`

#### **POST** `/nomina/validate`

_Valida un CFDI con complemento Nomina 1.2 contra reglas SAT._

Recibe un archivo CFDI 4.0 (XML) y valida su complemento Nomina. Retorna errores de validación (lista vacía = válido).

**Tags:** `nomina`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_validate_nomina_endpoint_nomina_validate_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/pagos`

### `/pagos/catalog`

#### **GET** `/pagos/catalog`

_Catálogo SAT de códigos de pagos._

Retorna los catálogos SAT para forma de pago, tipo de cadena de pago y monedas ISO 4217.

**Tags:** `pagos`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pagos/parse`

#### **POST** `/pagos/parse`

_Parsea complemento Pagos 1.1 de un CFDI XML._

Recibe un archivo CFDI 4.0 (XML) y extrae el complemento Pagos 1.1. Retorna los campos de pagos como JSON o 404 si no hay complemento.

**Tags:** `pagos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_parse_pagos_endpoint_pagos_parse_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pagos/validate`

#### **POST** `/pagos/validate`

_Valida un CFDI con complemento Pagos 1.1 contra reglas SAT._

Recibe un archivo CFDI 4.0 (XML) y valida su complemento de Pagos. Retorna errores de validación (lista vacía = válido).

**Tags:** `pagos`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `multipart/form-data`  
**Schema:** `Body_validate_pagos_endpoint_pagos_validate_post`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/portal`

### `/portal/activity`

#### **GET** `/portal/activity`

_Portal Activity_

Timeline de actividad reciente del tenant.

**Tags:** `portal-pages`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/alertas`

#### **GET** `/portal/alertas`

_Portal Alertas_

Alertas activas y resueltas del tenant.

**Tags:** `portal-pages`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/auth/confirm`

#### **POST** `/portal/auth/confirm`

_Portal Confirm_

Valida un token (magic link) y devuelve la sesión activa.

**Tags:** `portal`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PortalTokenRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/auth/login`

#### **POST** `/portal/auth/login`

_Portal Login_

Autentica un cliente por email+password (bcrypt) y devuelve un token de sesión multi-tenant.

**Tags:** `portal`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PortalLogin`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/auth/logout`

#### **POST** `/portal/auth/logout`

_Portal Logout_

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/auth/magic-link`

#### **POST** `/portal/auth/magic-link`

_Portal Magic Link_

Emite una sesión sin password y la 'envía' por email. NUNCA devuelve el token en la respuesta HTTP (salvo B2B_ENV=dev). En producción el token se envía exclusivamente por email.

**Tags:** `portal`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PortalMagicLink`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/auth/me`

#### **GET** `/portal/auth/me`

_Portal Me_

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/cfdis`

#### **GET** `/portal/cfdis`

_Portal Cfdis_

Lista de CFDIs del cliente con filtros (fecha, estatus, monto).

**Tags:** `portal-pages`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `fecha_desde` | query | `any` | no |  |
| `fecha_hasta` | query | `any` | no |  |
| `estatus` | query | `any` | no |  |
| `monto_min` | query | `any` | no |  |
| `monto_max` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/dashboard/stats`

#### **GET** `/portal/dashboard/stats`

_Portal Stats_

Métricas del tenant autenticado.

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/declaraciones`

#### **GET** `/portal/declaraciones`

_Portal Declaraciones_

Declaraciones mensuales con estatus.

**Tags:** `portal-pages`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/invoices.json`

#### **GET** `/portal/invoices.json`

_Portal Invoices_

Lista las facturas del tenant autenticado con filtros.

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `categoria` | query | `any` | no |  |
| `estado` | query | `any` | no |  |
| `fecha_desde` | query | `any` | no |  |
| `fecha_hasta` | query | `any` | no |  |
| `valido` | query | `any` | no |  |
| `limit` | query | `integer` | no |  |
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/invoices/export.csv`

#### **GET** `/portal/invoices/export.csv`

_Portal Export_

Exporta el historial del tenant a CSV.

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `categoria` | query | `any` | no |  |
| `fecha_desde` | query | `any` | no |  |
| `fecha_hasta` | query | `any` | no |  |
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/invoices/upload`

#### **POST** `/portal/invoices/upload`

_Portal Upload_

Sube CFDI (XML/PDF) y lo procesa por el pipeline en segundo plano. Devuelve job_id para que el portal haga polling del estado.

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/invoices/{job_or_id}/status`

#### **GET** `/portal/invoices/{job_or_id}/status`

_Portal Invoice Status_

Estado de procesamiento. Acepta un job_id (procesamiento en vuelo) o un invoice_id ya persistido.

**Tags:** `portal`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `job_or_id` | path | `string` | sí |  |
| `authorization` | header | `any` | no |  |
| `x-portal-token` | header | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/metrics`

#### **GET** `/portal/metrics`

_Portal Metrics_

Métricas de ahorro: horas ahorradas, errores evitados, ROI.

**Tags:** `portal-pages`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/notifications`

#### **GET** `/portal/notifications`

_Notifications Json_

**Tags:** `portal-pages`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `limit` | query | `integer` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/settings`

#### **PUT** `/portal/settings`

_Settings Update_

**Tags:** `portal-pages`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `SettingsUpdate`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/portal/summary`

#### **GET** `/portal/summary`

_Portal Summary_

Resumen: CFDIs procesados, declaraciones pendientes, alertas.

**Tags:** `portal-pages`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/pre-auditoria`

### `/pre-auditoria/cff-compliance`

#### **POST** `/pre-auditoria/cff-compliance`

_Verifica compliance con el CFF._

Valida RFC, CFDI, contabilidad electrónica y periodos cerrados.

**Tags:** `pre-auditoria`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `CFFComplianceRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pre-auditoria/consistency`

#### **POST** `/pre-auditoria/consistency`

_Verifica la consistencia del libro de contabilidad._

Detecta errores de partida doble, fechas y cuentas incompletas.

**Tags:** `pre-auditoria`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ConsistencyRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pre-auditoria/deductibility`

#### **POST** `/pre-auditoria/deductibility`

_Verifica la deducibilidad de gastos (Art. 28 LISR)._

Analiza si cada gasto es deducible según la legislación fiscal.

**Tags:** `pre-auditoria`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__features__pre_auditoria__routes__DeductibilityRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pre-auditoria/history`

#### **GET** `/pre-auditoria/history`

_Historial de auditorías previas._

Lista reportes de auditoría generados.

**Tags:** `pre-auditoria`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `tenant_id` | query | `any` | no |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pre-auditoria/report/{composite_id}`

#### **GET** `/pre-auditoria/report/{composite_id}`

_Obtiene un reporte de auditoría guardado._

Retorna un reporte de auditoría previamente generado. ``composite_id`` tiene formato ``{tenant_id}-{period}`` (p.ej. ``5-2026-08``).

**Tags:** `pre-auditoria`

**Parámetros**

| Parámetro | En | Tipo | Requerido | Descripción |
|---|---|---|---|---|
| `composite_id` | path | `string` | sí |  |

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/pre-auditoria/run`

#### **POST** `/pre-auditoria/run`

_Ejecuta una pre-auditoría contable completa._

Ejecuta un escaneo pre-audit sobre facturas, contabilidad y CFF. Retorna un reporte con hallazgos, score y recomendaciones.

**Tags:** `pre-auditoria`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `PreAuditRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/process`

### `/process`

#### **POST** `/process`

_Process Legacy_

DEPRECATED: use POST /api/v1/invoices/process instead.

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `b2b_ai__api__routes_invoices__ProcessRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/reportes`

### `/reportes/balance`

#### **POST** `/reportes/balance`

_Genera un Balance General (Estado de Situación Financiera)._

Genera un Balance General con activos, pasivos y capital contable. Acepta datos en JSON y retorna el reporte en el formato solicitado (json, csv o html).

**Tags:** `reportes`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `BalanceRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/reportes/conciliacion`

#### **POST** `/reportes/conciliacion`

_Genera un reporte de Conciliación Bancaria._

Genera un reporte de Conciliación Bancaria comparando movimientos del banco contra los de contabilidad. Acepta datos en JSON y retorna el reporte en el formato solicitado.

**Tags:** `reportes`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `ConciliacionRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/reportes/estado-resultados`

#### **POST** `/reportes/estado-resultados`

_Genera un Estado de Resultados._

Genera un Estado de Resultados con ingresos, costos, gastos y cálculo de utilidad neta. Acepta datos en JSON y retorna el reporte en el formato solicitado.

**Tags:** `reportes`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `EstadoResultadosRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/reportes/formats`

#### **GET** `/reportes/formats`

_Lista los formatos de salida disponibles._

Retorna los formatos soportados por los endpoints de reportes.

**Tags:** `reportes`

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

### `/reportes/nomina`

#### **POST** `/reportes/nomina`

_Genera un Reporte de Nómina por periodo._

Genera un reporte de nómina con resumen por empleado y departamento. Acepta datos en JSON y retorna el reporte en el formato solicitado.

**Tags:** `reportes`

**Parámetros**

_Sin parámetros._

**Request body**

**Content-Type:** `application/json`  
**Schema:** `NominaRequest`  

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `422` | Validation Error | `application/json` · `HTTPValidationError` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/stats`

### `/stats`

#### **GET** `/stats`

_Stats Legacy_

DEPRECATED: use GET /api/v1/stats instead.

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

## Grupo: `/tools`

### `/tools`

#### **GET** `/tools`

_Tools Legacy_

DEPRECATED: use GET /api/v1/tools instead.

**Parámetros**

_Sin parámetros._

**Responses**

| Código | Descripción | Contenido |
|---|---|---|
| `200` | Successful Response | `application/json` · `any` |
| `401` | Authentication required or API key invalid | `application/json` · `ErrorResponse` · ver ejemplo abajo |
| `403` | Tenant blocked or insufficient permissions | `application/json` · `ErrorResponse` |
| `429` | Rate limit exceeded | `application/json` · `RateLimitResponse` · ver ejemplo abajo |
| `500` | Internal server error | `application/json` · `ErrorResponse` |

**Ejemplo respuesta `401`:**
```json
{
  "error": {
    "code": 1002,
    "type": "auth_error",
    "message": "API key inválida o no autorizada.",
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```

**Ejemplo respuesta `429`:**
```json
{
  "error": {
    "code": 7001,
    "type": "rate_limit_exceeded",
    "message": "Too many requests. Please retry later.",
    "retry_after_seconds": 42,
    "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
  }
}
```
