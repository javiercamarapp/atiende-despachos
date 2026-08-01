# SDK de Python — likida-sdk

Cliente oficial de Python para la API REST de B&B AI (Likida) Enterprise.
Envuelve todos los endpoints del contrato OpenAPI (`docs/openapi.json`) en una
API tipada, con reintentos, manejo de errores y helpers para facturas, reportes
y webhooks.

> **Estado:** este documento define la superficie del SDK `likida-sdk` tal como
> se distribuye a los clientes del despacho. La referencia de endpoints y
> payloads se deriva 1:1 del contrato OpenAPI real de la API (nunca de memoria),
> de modo que los ejemplos siempre funcionan contra la API actual.

---

## 1. Instalación

```bash
pip install likida-sdk
```

Requiere Python ≥ 3.9. Dependencias: `requests` (HTTP), `pydantic>=2`
(tipado de modelos).

---

## 2. Client setup

```python
from likida import Client

client = Client(
    api_key="sk_live_xxxxxxxxxxxxxxxx",   # API key del despacho (header X-API-Key)
    base_url="https://api.b2b-ai.local",  # default producción
    timeout=30,                           # segundos
    max_retries=3,                        # reintentos en errores 429/5xx
)
```

La key se manda en el header `X-API-Key` en todas las llamadas. Para operar
sobre un tenant específico desde la key de servicio, pasa `tenant_id=` en cada
método o fija `client.tenant_id = 1`.

---

## 3. Invoice processing

Procesar un CFDI (XML/PDF). Acepta una ruta local o bytes:

```python
# Multipart (subida de archivo)
result = client.process_invoice_file("factura.xml", tenant_id=1)
# o desde bytes
result = client.process_invoice_bytes(open("factura.xml", "rb").read(),
                                      filename="factura.xml", tenant_id=1)

print(result.valido)                # True
print(result.categoria)             # "gastos"
print(result.confianza)             # 0.97
print(result.erp_poliza)            # "P-00123"
print(result.total)                 # 12000.0
```

Si el XML ya está en el servidor, usa la ruta:

```python
result = client.process_invoice(xml_path="/data/cfdi/factura.xml", tenant_id=1)
```

### Listar y consultar

```python
invoices = client.list_invoices(
    categoria="gastos",
    valido=True,
    fecha_desde="2026-07-01",
    fecha_hasta="2026-07-31",
    limit=100,
)
print(invoices.count)                 # número devuelto
for inv in invoices.invoices:
    print(inv["id"], inv["emisor_rfc"], inv["total"])

one = client.get_invoice(42)
print(one.invoice["categoria"])
```

### Lotes (v2) — síncronos y asíncronos

```python
# Síncrono (espera a terminar)
out = client.batch(paths=["/data/cfdi/1.xml", "/data/cfdi/2.xml"])
print(out.summary)   # {procesadas, validas, insertadas, por_categoria, ...}

# Asíncrono (job + polling)
job = client.batch_async(paths=[...], webhook=True)
print(job.job_id)                      # "3f2a1c9b7d41"
status = client.batch_status(job.job_id)
while status.status == "running":
    time.sleep(2)
    status = client.batch_status(job.job_id)
print(status.status, status.summary)
```

---

## 4. Report generation

### Stats agregados

```python
stats = client.stats()
print(stats.report)               # reporte por categoría / mes
print(stats.tools_registered)     # tools del agente
```

### Dashboard

```python
data = client.dashboard_data()            # JSON del dashboard
kpi = client.dashboard_kpi()              # KPIs (tiempo, error %, % automático)
monthly = client.dashboard_monthly()      # por mes
anomalies = client.dashboard_anomalies()  # anomalías
top_providers = client.dashboard_by_provider()
```

### Analytics avanzado (v2)

```python
ana = client.analytics(periodo="2026-07")
print(ana.tenant_id, ana.cached, ana.data)
```

### Exportar a archivo

```python
csv_data = client.export(format="csv", scope="invoices", limit=1000)
open("export.csv", "wb").write(csv_data)

xlsx_data = client.export(format="xlsx", scope="invoices")
```

### Contabilidad y nómina

```python
balanza = client.accounting_balance(periodo="2026-07")
catalogo = client.accounting_catalog()
nomina = client.payroll_calculate(
    empleado={"nombre": "Juan Pérez", "rfc": "PEJA850101XXX"},
    periodo={"sueldo_bruto": 25000.0, "dias_pagados": 30},
)
print(nomina["isr"], nomina["neto"])
```

---

## 5. Webhook handling

### Recibir eventos (servidor)

El SDK incluye un helper para montar un endpoint receptor con FastAPI que
valida el payload y responde `2xx` para confirmar la entrega:

```python
from fastapi import FastAPI, Request
from likida.webhooks import WebhookReceiver

app = FastAPI()
receiver = WebhookReceiver()

@app.post("/hooks/b2b")
async def on_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event") or "batch_completed"
    receiver.handle(event, payload)

    # ... tu lógica de negocio (idempotente por invoice_id/batch) ...

    return {"received": True}  # 2xx → detiene los reintentos
```

El receptor confirma con `200`; si tu handler devuelve otro código o lanza, el
agente reintenta con backoff exponencial (0.5s, 1s, 2s; hasta 3 intentos). Diseña
el handler para ser **idempotente** (usa `invoice_id`/`batch` como clave).

### Suscribirse a eventos

```python
subs = client.register_webhook(
    url="https://cliente.example.com/hooks/b2b",
    events=["invoice_processed", "batch_completed"],
)
print(subs.subscriptions)

client.delete_webhook(subscription_id=subs.subscriptions[0]["id"])
```

### Notificación manual y retry

```python
# Entregar un resultado al webhook del tenant
res = client.notify_webhook(event="invoice_processed", invoice_id=42)

# Reintentar entregas pendientes
retried = client.retry_webhooks()
print(retried.reintentadas)
```

---

## 6. Auth enterprise (JWT)

```python
from likida import Client

api = Client(api_key="sk_live_xxx")   # para registrar el 1er admin del tenant

# Bootstrap: primer usuario del tenant = admin
api.register(email="admin@despacho.com", password="supersecreto",
             tenant_id=1, name="María")

# Login → tokens JWT
session = api.auth_login(email="admin@despacho.com", password="supersecreto",
                         tenant_id=1)
print(session.access_token)

# A partir de aquí usa el token en lugar de la API key
jwt_client = Client(jwt_token=session.access_token, base_url=api.base_url)
me = jwt_client.auth_me()
```

---

## 7. Errores y manejo

El SDK lanza excepciones tipadas por código HTTP:

| Excepción | Código | Cuándo |
|---|---|---|
| `UnauthorizedError` | 401 | Key/token inválido o faltante |
| `ForbiddenError` | 403 | Sin permiso / tenant bloqueado |
| `NotFoundError` | 404 | Recurso no encontrado |
| `ValidationError` | 422 | Payload inválido |
| `RateLimitError` | 429 | Rate limit excedido (revisa `retry_after`) |
| `APIClientError` | 4xx | Otro error de cliente |
| `APIServerError` | 5xx | Error de servidor |

```python
from likida import Client, RateLimitError

try:
    client.process_invoice_file("factura.xml")
except RateLimitError as e:
    print(f"Espera {e.retry_after}s")   # header Retry-After
except ValidationError as e:
    print(e.detail)                     # detalle del error
```

El cliente reintenta automáticamente en `429` y `5xx` con backoff (respeta
`Retry-After`), hasta `max_retries`.

---

## 8. Timeouts y rate limiting

- El rate limit por IP+ruta es **300 peticiones/min** (configurable). En v2
  hay rate limit adicional **por tenant** (default 300/min).
- El SDK reintenta en `429` esperando `Retry-After`.
- Para lotes grandes usa `batch_async` (no consume tu cuota de forma síncrona).
- Consulta tu consumo con `client.usage()` (`GET /api/v2/usage`).

---

## 9. Referencia rápida de métodos

| Método SDK | Endpoint HTTP |
|---|---|
| `process_invoice_file` / `process_invoice_bytes` / `process_invoice` | `POST /api/v1/invoices/process` |
| `list_invoices` | `GET /api/v1/invoices` |
| `get_invoice(id)` | `GET /api/v1/invoices/{id}` |
| `stats()` | `GET /api/v1/stats` |
| `dashboard_data` / `dashboard_kpi` / `dashboard_monthly` | `GET /api/v1/dashboard/*` |
| `payroll_calculate` | `POST /api/v1/payroll/calculate` |
| `accounting_balance` / `accounting_catalog` | `GET /api/v1/accounting/*` |
| `reconcile` | `POST /api/v1/reconcile/run` |
| `collections_analyze` | `POST /api/v1/collections/analyze` |
| `batch` / `batch_async` / `batch_status` | `POST /api/v2/batch` · `GET /api/v2/batch/{id}` |
| `analytics` | `GET /api/v2/analytics` |
| `export` | `POST /api/v2/export` |
| `usage()` | `GET /api/v2/usage` |
| `register_webhook` / `delete_webhook` | `POST/DELETE /api/v2/webhooks` |
| `notify_webhook` | `POST /api/v1/webhooks/notify` |
| `retry_webhooks` | `POST /api/v1/webhooks/retry` |
| `register` / `auth_login` / `auth_refresh` / `auth_me` | `/api/v1/auth/*` |

Para el contrato exacto de cada endpoint (schemas, parámetros, ejemplos) consulta
`docs/api-reference.md` y `docs/openapi.json`.
