# Quickstart — Integra Likida AI en 5 pasos

Guía rápida para que un despacho contable conecte su sistema con la API de
Likida AI. Base URL: `https://api.b2b-ai.local` (local: `http://localhost:8000`).

> **Nota sobre obtener tu API key:** la API emite una key al **crear un tenant**
> (`POST /api/v1/tenants`). No existe un `onboarding/register`; el registro de
> usuarios va por JWT (`POST /api/v1/auth/register`). El flujo de abajo usa el
> endpoint real de provisión de keys.

---

## Paso 1 — Obtén tu API key

Crea tu tenant. La respuesta incluye tu `api_key` (guárdala, no se puede
volver a leer):

```bash
curl -X POST https://api.b2b-ai.local/api/v1/tenants \
  -H "X-API-Key: B2B_API_KEY_DE_SERVICIO" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Despacho Contable XYZ",
    "rfc": "DESP820101AB1",
    "erp_type": "contpaqi",
    "plantilla_contable": "SAT",
    "notif_channel": "email",
    "user_name": "admin",
    "user_email": "admin@despacho.mx"
  }'
```

Respuesta:

```json
{
  "ok": true,
  "tenant": {
    "id": 1,
    "name": "Despacho Contable XYZ",
    "rfc": "DESP820101AB1",
    "user_id": 3,
    "api_key": "sk_likida_XXXXXXXX"
  }
}
```

Guarda la key en una variable:

```bash
export LIKIDA_API_KEY="sk_likida_XXXXXXXX"
```

> En un entorno local/demo, la key de servicio de la env `B2B_API_KEY`
> también autentica y resuelve `tenant_id=None`.

---

## Paso 2 — Sube tu primer CFDI

Procesa un XML de factura por el pipeline completo (validación, clasificación,
póliza ERP):

```bash
curl -X POST https://api.b2b-ai.local/api/v1/invoices/process \
  -H "X-API-Key: $LIKIDA_API_KEY" \
  -F "xml_file=@factura.xml"
```

Respuesta:

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

---

## Paso 3 — Ve el resultado parseado

Lista tus facturas (o consulta una por id):

```bash
curl "https://api.b2b-ai.local/api/v1/invoices?limit=10" \
  -H "X-API-Key: $LIKIDA_API_KEY"
```

```json
{
  "count": 1,
  "tenant_id": 1,
  "invoices": [
    { "id": 12, "folio_fiscal": "A1B2C3", "fecha": "2026-07-30",
      "total": "12000.00", "emisor_rfc": "XAXX010101000",
      "categoria": "Gastos", "valido": 1 }
  ]
}
```

Detalle individual:

```bash
curl https://api.b2b-ai.local/api/v1/invoices/12 -H "X-API-Key: $LIKIDA_API_KEY"
```

---

## Paso 4 — Consulta tus transacciones bancarias

Conecta una cuenta y lee sus transacciones:

```bash
# 1) Conecta la cuenta
curl -X POST https://api.b2b-ai.local/api/v1/bank-feeds/accounts \
  -H "X-API-Key: $LIKIDA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "provider": "BBVA", "clabe": "012180015000000001",
        "account_label": "Cuenta operativa" }'

# 2) Sincroniza el feed
curl -X POST "https://api.b2b-ai.local/api/v1/bank-feeds/accounts/acc-1/sync" \
  -H "X-API-Key: $LIKIDA_API_KEY"

# 3) Lista las transacciones
curl "https://api.b2b-ai.local/api/v1/bank-feeds/accounts/acc-1/transactions?limit=50" \
  -H "X-API-Key: $LIKIDA_API_KEY"
```

```json
{
  "ok": true,
  "data": [
    { "id": "txn-1", "date": "2026-07-15", "amount": 12000.0,
      "description": "Pago proveedor", "category": null }
  ]
}
```

---

## Paso 5 — Genera tu reporte mensual

Genera un reporte financiero mensual con KPIs:

```bash
curl -X POST https://api.b2b-ai.local/api/v1/reportes/monthly \
  -H "X-API-Key: $LIKIDA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "default",
    "month": 7,
    "year": 2026,
    "revenue": 250000.0,
    "expenses": 120000.0,
    "taxes_paid": 30000.0,
    "invoices_count": 45
  }'
```

```json
{
  "ok": true,
  "report": { "period": "2026-07", "revenue": 250000.0,
              "expenses": 120000.0, "gross_margin": 52.0, "net": 100000.0 }
}
```

O genera un PDF gerencial:

```bash
curl "https://api.b2b-ai.local/api/v1/reports/monthly/2026-07" \
  -H "X-API-Key: $LIKIDA_API_KEY" \
  -o resumen_mensual_2026-07.pdf
```

---

## Siguientes pasos

- Referencia completa: `docs/api-reference.md`
- Contrato OpenAPI: `docs/openapi.json` / `docs/openapi.yaml`
- Colección Postman: `docs/postman-collection.json`
- Swagger UI en vivo: `GET /docs`

Errores comunes: `401` (key inválida), `403` (key de servicio sin tenant),
`429` (rate limit — reintenta con backoff), `422` (validación del payload).
