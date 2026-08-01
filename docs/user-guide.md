# User Guide — B&B AI

Guía práctica para contadores, auxiliares y usuarios del sistema B&B AI: cómo
procesar CFDI, usar el dashboard, configurar integraciones y resolver problemas
comunes.

> **Importante**: B&B AI **prepara y valida**; el profesional **determina y
> firma**. Ninguna salida con efecto fiscal (póliza, balanza, nómina, cancelación)
> sustituye la revisión de un contador público, y nada se presenta ante el SAT sin
> la e.firma del contribuyente.

---

## 1. Primeros pasos

### 1.1 Acceso

El sistema se accede por tres vías:

| Vía | Qué es | Para quién |
|---|---|---|
| **Dashboard web** (`/dashboard`) | Panel gerencial con KPIs y gráficas | Gerencia / contadores |
| **Portal de cliente** (`/portal`) | Subida de facturas desde el navegador | Clientes / auxiliares |
| **CLI** (`bb-ai`) | Procesamiento y reportes por terminal | Operación / batch |

### 1.2 Datos de acceso

- **Dashboard / API**: usa la **API key** de tu despacho en el header
  `X-API-Key`. El dashboard la guarda en `localStorage` la primera vez.
- **Portal**: email + password (o magic-link, si está habilitado).

Si no tienes credenciales, pídele al administrador de tu despacho que cree tu
usuario y/o te asigne la API key correspondiente a tu tenant.

---

## 2. Cómo procesar un CFDI

### 2.1 Desde el CLI

```bash
# Procesar un solo CFDI
bb-ai process /ruta/al/cfdi.xml

# Procesar todos los CFDI de una carpeta
bb-ai batch /ruta/carpeta_cfdis/

# Reporte mensual de agregados
bb-ai report --period 2026-07

# Ver el estado del sistema
bb-ai status
```

Al procesar, el CLI muestra:

```
  archivo        : factura.xml
  RFC emisor     : XAXX010101000 (Empresa X)
  Fecha          : 2026-07-15
  Subtotal/IVA   : 1000.00 / 160.00
  Total          : 1160.00
  Folio fiscal   : XXXXXXXX-....
  VALIDACIÓN     : OK (pass=5 fail=0)
  CLASIFICACIÓN  : Operativo (confianza 0.98) — Papelería de oficina
  ERP            : P-2026-001 (registered)
  Notificación   : simulated
  Revisión humana: no
```

### 2.2 Desde la API

```bash
# Multipart
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" -F "xml_file=@factura.xml"

# JSON con ruta local
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"xml_path":"/ruta/al/cfdi.xml"}'
```

### 2.3 Desde el portal del cliente

1. Inicia sesión en `/portal`.
2. Ve a **Facturas → Subir**.
3. Selecciona uno o varios archivos XML.
4. Revisa el estado de cada factura en **Facturas → Estado** (procesado, en
   revisión o con observaciones).

### 2.4 Qué pasa con cada CFDI

Cada CFDI pasa por: **parse → validación fiscal → clasificación → póliza ERP →
persistencia → notificación**. Todo queda registrado en el **audit_log** para
trazabilidad.

- Si la validación pasa **sin observaciones**, el flujo continúa y la factura se
  registra (según la política de tu tenant: `auto_register` o `hold`).
- Si hay **observaciones** o el CFDI **requiere revisión humana**, se crea una
  fila en `reviews` y se notifica. **No se registra en el ERP** hasta que un
  profesional lo revisa y aprueba.

---

## 3. Cómo usar el dashboard

El dashboard (`/dashboard`) consume `/api/v1/stats` y `/api/v1/invoices` con tu
API key y muestra:

- **KPIs**: total de facturas, montos (subtotal, IVA, total), proveedores top,
  anomalías detectadas, estado de conciliación.
- **Gráficas**: montos por categoría, montos por mes, top proveedores.
- **Listado de facturas**: como cards, con estado de validación y clasificación.

### 3.1 Offline / móvil

El sistema es una **PWA**: puedes instalarlo desde el navegador (botón
"Instalar") y usar el dashboard **offline** para las facturas ya procesadas (el
service worker cachea las respuestas). Un banner indica "sin conexión" cuando no
hay red.

### 3.2 Endpoints del dashboard

| Ruta | Qué muestra |
|---|---|
| `/api/v1/dashboard` | Panel HTML completo |
| `/api/v1/dashboard/data` | Datos en JSON |
| `/api/v1/dashboard/kpi` | KPIs |
| `/api/v1/dashboard/monthly` | Montos mensuales |
| `/api/v1/dashboard/by-provider` | Top proveedores |
| `/api/v1/dashboard/anomalies` | Anomalías |
| `/api/v1/dashboard/reconciliation` | Estado de conciliación |

---

## 4. Cómo configurar integraciones

### 4.1 ERP (CONTPAQi)

El sistema integra con el ERP del despacho mediante:
- **MockCONTPAQi** (por defecto, para prueba y demo).
- **CSV fallback** (exportar/importar vía CSV).
- **Computer use** para ERPs sin API REST estable (CONTPAQi, SAP B1, Odoo): el
  agente ve la pantalla y actúa (navigate → login → upload → read_screen). En
  producción se sustituye el mock por un driver vision-based (Playwright + LLM).

Configura el tipo de ERP de tu tenant en el onboarding
(`POST /api/v1/tenants`, campo `erp_type`).

### 4.2 Notificaciones (email)

Por defecto las notificaciones se **simulan** (no se envían reales). Para envío
real por SMTP, el administrador debe configurar en el entorno:

```bash
SMTP_HOST=smtp.tu-proveedor.com
SMTP_PORT=465
SMTP_USER=agente@tu-dominio.com
SMTP_PASSWORD=********
SMTP_FROM=agente@tu-dominio.com
SMTP_USE_SSL=true
```

### 4.3 LLM opcional

El pipeline funciona **100% sin LLM** (solo reglas). Para clasificación asistida
y detección de anomalías con IA, configura:

```bash
B2B_LLM_PROVIDER=openrouter      # o openai | deepseek | anthropic
B2B_OPENROUTER_API_KEY=sk-...    # (la clave del proveedor elegido)
```

Si el LLM falla o no hay clave, el sistema **cae automáticamente a reglas** — no
bloquea el procesamiento.

### 4.4 Webhooks

Para recibir resultados automáticamente en tu aplicación:

```bash
# Registrar un webhook (v2)
curl -X POST http://localhost:8000/api/v2/webhooks \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://miapp.com/hook","events":["invoice.processed","invoice.failed"]}'
```

Los webhooks outbound entregan con **retry** (backoff exponencial) y dejan
bitácora en `webhook_deliveries`.

### 4.5 Cobranza (recordatorios)

1. Sube tu cartera pendiente con `POST /api/v1/collections/analyze`
   (`sync=true` para persistir).
2. Consulta el aging con `GET /api/v1/collections/aging`.
3. Genera recordatorios por etapa con
   `POST /api/v1/collections/send-reminder`.

> Los recordatorios se **generan** pero no se envían reales por defecto; usa el
> canal/campo adecuado y la integración de notificaciones para el envío.

---

## 5. Troubleshooting

### 5.1 "401 API key inválida o no autorizada"

- Verifica que envías el header `X-API-Key` en cada petición.
- La key debe pertenecer a tu tenant y estar activa (no bloqueada).
- En dev, la key maestra es `B2B_API_KEY` del `.env`.

### 5.2 "403 Tenant bloqueado"

Tu tenant está bloqueado por el administrador. Contacta al soporte para
desbloquearlo.

### 5.3 "429 Demasiadas peticiones"

Excediste el límite (default 300/min por IP+ruta). Espera un minuto (o al
`Retry-After`) y reintenta. Para cargas grandes, usa `/api/v2/batch` con
`async_=true` (lotes hasta 1000).

### 5.4 "422 CFDI inválido"

El XML no pasó la validación fiscal. El detalle indica qué falló (aritmética,
catálogo SAT, RFC, fechas, retenciones). Corrige el XML del proveedor o solicita
la reposición. Los montos ≤ 0 y los lotes > 1000 también dan 422.

### 5.5 El dashboard no carga datos

- Verifica la API key guardada en el navegador (`localStorage`).
- Confirma que el servidor está arriba (`/health`).
- Si es un problema de conexión, revisa los CORS: si la UI está en otro dominio,
  el admin debe definir `B2B_CORS_ORIGINS`.

### 5.6 No llegan notificaciones

- Sin credenciales SMTP, el sistema **simula** los mensajes (no los envía).
- Configura el SMTP en el entorno (ver sección 4.2) y reinicia el servicio.

### 5.7 El LLM no responde / clasificación rara

- El sistema cae a reglas automáticamente; verifica `B2B_LLM_PROVIDER` y la key
  del proveedor.
- Revisa los logs del servicio.

### 5.8 Procesos batch lentos / con errores parciales

- Un error en una factura **no rompe el lote**; el resultado marca esa factura
  con su error y sigue.
- Para lotes grandes usa `/api/v2/batch` async y consulta el estado por
  `job_id`.

### 5.9 Contacto de soporte

Para temas de credenciales, tenants o despliegue, contacta al administrador del
sistema / equipo de soporte B&B AI (`ventas@b2b-ai.local`).

---

## 6. Buenas prácticas

- **Revisión humana**: aprueba siempre los CFDI marcados como `requires_human_review`
  antes de considerarlos cerrados.
- **Trazabilidad**: consulta `/api/v2/audit` para auditar qué se hizo y con qué
  key.
- **Lotes**: agrupa los CFDI por periodo y procesa en batch para eficiencia.
- **Backups**: la DB vive en un volumen persistente; configura backups regulares
  del volumen en producción.
- **Credenciales**: nunca compartas tu API key; cada despacho tiene la suya.
