# Webhooks — B&B AI Enterprise

Documentación del sistema de webhooks del agente contable. Cubre las dos
direcciones del tráfico:

1. **Inbound** — cómo el agente recibe facturas (por email, mock Mailgun/SendGrid).
2. **Outbound** — cómo el agente te notifica resultados (eventos entregados a
   tu URL), con firma, reintentos y bitácora.

Código de referencia: `b2b_ai/api/webhooks.py`, `b2b_ai/api/v2.py`.

---

## 1. Event types (outbound)

Los eventos que el agente puede entregar a tu URL de webhook. Se registran
por suscripción vía `/api/v2/webhooks` (por evento) o una sola URL global via
`/api/v1/webhooks/subscriptions` o la config del tenant (`webhook_url`).

| Evento | Cuándo se dispara | Payload clave |
|---|---|---|
| `invoice_processed` | Una factura terminó de procesarse (validación + clasificación + póliza ERP) | `invoice_id`, `summary` |
| `batch_completed` | Un lote async (`/api/v2/batch`) terminó | `batch`, `summary` |

Nota: el sistema de entrega en el MVP arranca en **modo mock-safe**: por
defecto la entrega se registra en `webhook_deliveries` sin salir a la red. En
producción se apunta al POST real (ver §5).

---

## 2. Payload format

Todos los payloads se entregan como `POST application/json`.

### 2.1 `invoice_processed` (lote)

Cuando un lote se procesa con `webhook: true`, el payload es:

```json
{
  "batch": "3f2a1c9b7d41",
  "summary": {
    "procesadas": 120,
    "validas": 118,
    "con_observaciones": 2,
    "insertadas": 120,
    "por_categoria": {"gastos": 80, "honorarios": 40},
    "errores": 0
  }
}
```

### 2.2 `invoice_processed` (notificación directa)

Cuando usas `POST /api/v1/webhooks/notify`, el payload entregado al webhook
del tenant es:

```json
{
  "event": "invoice_processed",
  "invoice": {
    "id": 42,
    "folio_fiscal": "UUID-1234",
    "emisor_rfc": "XAXX010101000",
    "fecha": "2026-07-30",
    "total": 12000.0,
    "categoria": "gastos",
    "valido": true,
    "status": "procesado"
  },
  "notified_at": "2026-07-31T21:00:00"
}
```

---

## 3. Signature verification

El sistema usa **firma por URL configurada + validación de esquema**, no una
firma HMAC por defecto en el MVP. Las medidas de seguridad que SÍ están activas:

1. **Restricción de esquema (anti-SSRF):** la URL de suscripción debe empezar
   por `http://` o `https://`. Esquemas como `file:`, `gopher:` etc. se
   rechazan (`_assert_http_scheme`). Esto evita que un atacante use la
   integración para leer archivos locales (SSRF).
2. **Validación en registro:** `/api/v2/webhooks` rechaza URLs sin esquema
   válido (`422`); `/api/v1/webhooks/subscriptions` igual.
3. **Bitácora completa:** cada intento de entrega se registra en
   `webhook_deliveries` (evento, URL, payload, intentos, status, error).

### Para confirmar que la entrega es legítima, tu receptor debe:

1. Verificar que el `Content-Type` sea `application/json`.
2. Validar que el `event` y el `tenant_id`/`batch` correspondan a tu suscripción.
3. Responder `2xx` para confirmar recepción (si respondes otro código, el
   agente reintenta — ver §4).

> **Roadmap (producción):** añadir cabecera de firma HMAC (p. ej.
> `X-B2B-Signature: <hmac-sha256(payload, webhook_secret)>`) con secret por
> suscripción, expuesta en la respuesta de registro. Hasta entonces, la
> integridad del canal depende de TLS + restricción de esquema + validación
> de evento.

---

## 4. Retry policy

La entrega de webhooks usa **reintentos con backoff exponencial**
(`retry_deliver` en `b2b_ai/api/webhooks.py`):

- **Máximo de intentos:** `max_attempts = 3` (por defecto).
- **Backoff exponencial:** el espera entre intentos es
  `base_delay * 2^(n-1)`, con `base_delay = 0.5s` por defecto. Intentos en
  `0.5s`, `1s`, `2s`.
- **Timeouts:** cada POST usa un timeout de 15s.
- **Condición de éxito:** el receptor debe responder con un código HTTP
  `2xx`. Cualquier otro código o una excepción de red cuenta como fallo y se
  reintenta.
- **Resultado:** se devuelve `{ok, attempts, last_status, last_error}`.

### Entrega fallida tras 3 intentos

- La entrega queda como pendiente en `webhook_deliveries`.
- Puedes reintentarla manualmente con `POST /api/v1/webhooks/retry` (worker),
  que toma todas las entregas pendientes del tenant y las vuelve a intentar:

```bash
curl -X POST https://api.b2b-ai.local/api/v1/webhooks/retry \
  -H "X-API-Key: sk_live_xxx"
```

```json
{
  "reintentadas": 2,
  "results": [
    {"delivery_id": 7, "ok": true, "attempts": 1, "last_status": "delivered", "last_error": ""}
  ]
}
```

### Si no tienes URL configurada

`POST /api/v1/webhooks/notify` devuelve `409`:

```json
{"detail": "El tenant no tiene webhook_url configurada."}
```

Configúrala con:

```bash
curl -X POST https://api.b2b-ai.local/api/v1/webhooks/subscriptions \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"url": "https://cliente.example.com/hooks/b2b"}'
```

---

## 5. Configurar tu URL de recepción

### Opción A — una sola URL por tenant (v1)

```bash
curl -X POST https://api.b2b-ai.local/api/v1/webhooks/subscriptions \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"url": "https://cliente.example.com/hooks/b2b"}'
```

```json
{"ok": true, "tenant_id": 1, "webhook_url": "https://cliente.example.com/hooks/b2b"}
```

### Opción B — suscripciones por evento (v2)

```bash
curl -X POST https://api.b2b-ai.local/api/v2/webhooks \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"url": "https://cliente.example.com/hooks/b2b", "events": ["invoice_processed", "batch_completed"]}'
```

```json
{
  "ok": true,
  "tenant_id": 1,
  "subscriptions": [
    {"id": 1, "event": "invoice_processed", "url": "https://cliente.example.com/hooks/b2b"},
    {"id": 2, "event": "batch_completed", "url": "https://cliente.example.com/hooks/b2b"}
  ]
}
```

### Listar y eliminar suscripciones

```http
GET /api/v2/webhooks
GET /api/v2/webhooks?event=invoice_processed
DELETE /api/v2/webhooks/{subscription_id}
```

---

## 6. Inbound: recibir facturas por email

El endpoint `POST /api/v1/webhooks/email` simula el inbound parse de
**Mailgun / SendGrid**: recibe un payload con adjuntos de CFDI (XML) y el
agente los procesa de punta a punta.

```bash
curl -X POST https://api.b2b-ai.local/api/v1/webhooks/email \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{
    "from": "proveedor@x.com",
    "subject": "Factura CFDI",
    "text": "Adjunto factura",
    "attachments": [
      {"filename": "factura.xml", "content_base64": "<base64 del XML>"}
    ]
  }'
```

El adjunto acepta `content` (XML crudo) o `content_base64`. También admite XML
embebido en el campo raíz `xml` o `content`.

Respuesta:

```json
{
  "procesadas": 1,
  "results": [
    {
      "decision": "aprobar",
      "invoice_id": 42,
      "archivo": "factura.xml",
      "adjunto": "factura.xml",
      "categoria": "gastos",
      "review_id": "rev-abc123"
    }
  ]
}
```

Errores:
- `422` — no se encontraron CFDI XML adjuntos, o no se pudo resolver el tenant.

---

## 7. Notificar un resultado a mano

`POST /api/v1/webhooks/notify` entrega un evento específico al webhook del
tenant:

```bash
curl -X POST https://api.b2b-ai.local/api/v1/webhooks/notify \
  -H "X-API-Key: sk_live_xxx" -H "Content-Type: application/json" \
  -d '{"event": "invoice_processed", "invoice_id": 42}'
```

Respuesta de éxito:

```json
{
  "ok": true,
  "delivery_id": 5,
  "event": "invoice_processed",
  "url": "https://cliente.example.com/hooks/b2b",
  "attempts": 1,
  "last_status": "delivered",
  "last_error": ""
}
```

---

## 8. Buenas prácticas para tu endpoint receptor

- **Responde rápido** (`200`) y procesa de forma asíncrona: el agente espera
  tu `2xx` para marcar la entrega como exitosa y detener los reintentos.
- **Idempotencia:** diseña tu receptor para tolerar duplicados (usa
  `invoice_id`/`batch` como clave), porque los reintentos re-entregan el mismo
  payload.
- **Valida el evento** antes de actuar y responde no-2xx si el evento no te
  aplica.
- **Timeout:** responde en < 15s.
