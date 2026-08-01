# Architecture — Likida AI Enterprise Enterprise

Documento de arquitectura del agente contable enterprise. Describe la visión del
sistema, componentes, flujo de datos, diseño multi-tenant, modelo de seguridad y
opciones de despliegue.

---

## 1. System overview

Likida AI Enterprise es un **agente de IA enterprise** que automatiza el ciclo de vida de la
facturación electrónica mexicana para despachos contables. Es un **monolito
modular** en Python (FastAPI) que expone una API REST, una CLI, un dashboard web,
un portal de cliente y landing pages, con una base de datos relacional (SQLite
por defecto, PG-ready).

**Principio rector** (de `04-leyes-fiscales.md`):

> La máquina **prepara y valida**; el profesional **determina y firma**.

Toda salida con efecto fiscal (póliza, balanza, nómina, cancelación, presentación
SAT) lleva **referencia legal + supuesto + flag `requires_human_review`**. El
agente **nunca** auto-cancela montos relevantes ni presenta ante el SAT sin
e.firma humana.

**Stack:**

- **Lenguaje/entorno:** Python 3.9+
- **API:** FastAPI + uvicorn
- **Datos:** SQLite (`b2b_ai.db`), schema multi-tenant, PG-ready
- **XML/CFDI:** lxml
- **Auth:** API keys por tenant (`X-API-Key`) + token de sesión en el portal
- **LLM opcional:** OpenAI / Anthropic / DeepSeek / OpenRouter, con fallback a reglas

---

## 2. Component diagram

```
┌─────────────────────────── Aplicación (FastAPI) ───────────────────────────┐
│                                                                            │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ api/app.py │ │ api/v2.py  │ │ api/portal │ │api/webhooks│ │api/dash  │ │
│  │  API v1    │ │ enterprise │ │  cliente   │ │ in/out     │ │ board    │ │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────┬─────┘ │
│        │              │              │              │             │       │
│  ┌─────▼─────────────────────────────▼──────────────▼─────────────▼─────┐  │
│  │              Middleware: auth (APIKeyAuth) · rate-limit · CORS ·      │  │
│  │              metrics · auditoría de intentos fallidos                │  │
│  └─────┬────────────────────────────────────────────────────────────────┘  │
└────────┼────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────── Capa de dominio (services/) ───────────────────┐
│  pipeline (orquestador) · classify · report · reconcile · payroll          │
│  accounting · contabilidad_electronica · collections · anomaly · analytics │
│  catalogo_cuentas · balanza · exporter                                     │
└────────┬────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────── Capa de integración ────────────────────────────┐
│  cfdi/ (parser · validator · catalogs · cancellation)                      │
│  erp/ (ERPInterface · CONTPAQi mock · CSV fallback)                        │
│  computer_use/ (BrowserAutomation · MockBrowser · aspel/contpaqi drivers)  │
│  notifications/ (email SMTP · WhatsApp mock · templates)                   │
│  agent/loop.py (LLM + árbol de decisión + human-in-the-loop)               │
│  tools/ (tool calling: @tool, registry, router, logger)                    │
└────────┬────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────── Persistencia ───────────────────────────────────┐
│  db/ (db.py · models.py · pool.py · tenants.py)  →  SQLite / PG             │
│  tenants · users · invoices · classifications · audit_log · notifications   │
│  api_keys · leads · outstanding_invoices · collection_events · webhooks     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data flow — procesamiento de un CFDI

Flujo end-to-end de un CFDI a través del pipeline (tool calling, todo auditado
en `audit_log`):

```
parse_cfdi → validate_cfdi → classify_expense → register_erp → send_notification
```

1. **Ingesta**: el CFDI entra por API (`POST /api/v1/invoices/process`, multipart
   o `xml_path`), por CLI (`bb-ai process`), por **webhook de email** o por
   **subida del portal**.
2. **Parse** (`cfdi/parser.py`): extrae emisor, receptor, concepto, fechas,
   folio fiscal, subtotal, IVA, total, retenciones y complementos.
3. **Validación fiscal** (`cfdi/validator.py`):
   - Aritmética por concepto (`cantidad × valor = importe`).
   - Suma de conceptos == subtotal; total = subtotal + IVA − descuento − retenciones.
   - Catálogos SAT (UsoCFDI, FormaPago, MetodoPago, Tipo, Régimen).
   - RFC, fechas (FechaTimbrado ≥ Fecha), retenciones.
   - DIOT (proveedores reportables), nómina (método PUE, complemento).
   - Genera `requires_human_review` en decisiones con efecto fiscal.
4. **Clasificación** (`services/classify.py`): asigna categoría de gasto con
   confianza y razón. Opcionalmente asistida por LLM (`services/llm.py`), con
   fallback automático a reglas.
5. **Póliza ERP** (`services/pipeline.py` + `erp/`): registra la póliza contable
   en el ERP (CONTPAQi mock por defecto, o el driver de computer use).
6. **Persistencia**: inserta la factura + clasificación en la DB, escopado por
   tenant.
7. **Notificación**: envía email/SMS mock (o SMTP real si hay credenciales).
8. **Loop de agente** (`agent/loop.py`, si aplica): `recibir → validar →
   clasificar(LLM) → detectar anomalía → decidir → registrar → notificar`, con
   política por tenant (`hold` vs `auto_register`) y human-in-the-loop (escalas a
   `reviews`).

### Conciliación bancaria

`services/reconcile.py`: parsea estado de cuenta **CSV** y **PDF**
(`parse_bank_statement_csv` / `parse_bank_statement_pdf`, extractor PDF sin
dependencias; PDFs escaneados requieren OCR y quedan fuera de alcance). Matching
por **monto + fecha** con refuerzo por **referencia**; `build_reconciliation_report`
produce montos, pendientes y tasa de conciliación.

### Contabilidad electrónica

`services/accounting.py` + `services/contabilidad_electronica.py`:
catálogo de cuentas (CUC) → asientos contables → **balanza de comprobación** →
paquete XML SAT con hash SHA-1 del acuse.

### Cobranza

`services/collections.py`: clasifica cartera por antigüedad (buckets 0-30/31-60/
61-90/90+), calcula **score de cobrabilidad** (0..1) y genera recordatorios por
etapa/canal (sin enviar reales por defecto).

---

## 4. Multi-tenant design

El sistema es **multi-tenant** desde la base:

- **Tabla `tenants`**: un registro por cliente (despacho), con RFC, tipo de ERP,
  plantilla contable, canal de notificación, política y estado `blocked`.
- **API keys por tenant** (`api_keys`): cada key está asociada a un `tenant_id`.
  La key de servicio (env `B2B_API_KEY`) tiene `tenant_id=None`.
- **Aislamiento de datos**: toda lectura/escritura filtra por `tenant_id`. El
  hard-scoping en `app.py` (`_scope()`) garantiza que una key de tenant **nunca**
  pueda ver otro tenant, aunque el cliente mande `tenant_id` en la query.
- **Onboarding** (`db/tenants.py`): `onboard_tenant` crea tenant + config + API
  key de onboarding en un solo paso. Disponible vía `/api/v1/tenants` y
  `/api/v2/tenants`.
- **Configuración por tenant**: `set_config`/`get_config` con defaults; cada
  tenant define su política (`hold` / `auto_register`), plantilla contable y canal.
- **Bloqueo de tenants**: `block`/`unblock` (admin, `/api/v2/tenants/{tid}/block`)
  — un tenant bloqueado recibe `403` en cualquier endpoint.
- **Fábrica de ERP**: `erp_factory(tenant_id)` devuelve el ERP según la config
  del tenant (CONTPAQi, CSV, o driver de computer use).
- **Uso por tenant**: `get_usage(tenant)` cuenta calls y facturas; expuesto en
  `/api/v2/usage`.

---

## 5. Security model

**Autenticación** (`api/auth.py`):
- API keys en header `X-API-Key`, comparadas con `hmac.compare_digest`
  (a prueba de timing side-channel).
- Resolución: env `B2B_API_KEY` (servicio) → tabla `api_keys` (multi-tenant).
- Keys guardadas **hashadas** (SHA-256) en la DB.
- Intentos fallidos auditados (longitud + hash corto, nunca la key completa).
- Portal de cliente: token de sesión (email+password bcrypt o magic-link mock).

**Autorización / aislamiento**:
- Hard-scoping por tenant (una key de tenant no ve otros tenants).
- Endpoints legacy (`/invoices`, `/stats`, `/tools`, `/process`) **ahora
  protegidos por API key** (antes exponían datos financieros y lectura de archivos
  sin auth).

**Protección de abuso**:
- **Rate limiting** en memoria (300 req/min por IP+ruta por defecto, ventana
  deslizante). Endpoints exentos: health, estáticos, docs, metrics.
- Endpoints públicos mínimos: `/health`, `/metrics`, `/api/v1/leads`, landing.

**Path traversal**:
- Servido de icons validado: solo `.png`, nombre sanitizado, resolución dentro
  de `LANDING_DIR`.

**CORS**:
- Desactivado por defecto (landing same-origin). Se habilita explícitamente con
  `B2B_CORS_ORIGINS` para integraciones cross-origin.

**Riesgos residuales (a documentar en deploy)**:
- El rate limiter es en memoria (single-node); en multi-replica debe migrar a Redis.
- PDFs escaneados requieren OCR (fuera de alcance).
- La cancelación ejecutada y la presentación SAT requieren e.firma humana.
- El envío SAT (`/accounting/sat/send`) es **mock**.

---

## 6. Deployment options

El sistema se despliega como un solo servicio (API + landing + dashboard),
con la DB en un volumen persistente.

### Opción A — Docker Compose (recomendado)

```bash
cd enterprise
cp .env.example .env && vi .env   # define B2B_API_KEY
docker compose up --build -d
# API en http://localhost:8000 · Docs en /docs · DB persistente en volumen
```

`docker-compose.yml` levanta la API + volumen de DB nombrado. El `Dockerfile` es
multi-stage; la landing se copia a `/app/landing`. `docker-compose.prod.yml`
incluye nginx para producción.

### Opción B — Local (venv + uvicorn)

```bash
./start.sh --local                # crea .venv e instala deps si faltan
uvicorn b2b_ai.api.app:app --reload
```

### Opción C — PaaS (Railway / Render)

`railway.json` + `Procfile` + `runtime.txt` listos. La DB debe montarse en un
volumen persistente; para alta concurrencia se recomienda migrar a **PostgreSQL**
(la app es PG-ready).

### Opción D — VPS / cloud

Ver `DEPLOY.md` (Vercel/Netlify para landing, VPS para API) y
`README-DEPLOY.md` (opciones VPS vs cloud). `deploy.sh` automatiza el despliegue.

**Arquitectura de despliegue típica (producción):**

```
Clientes ──HTTPS──▶ Nginx (TLS) ──▶ uvicorn (FastAPI) ──▶ SQLite/PostgreSQL
                      │                                     (volumen persistente)
                      └─▶ /static (landing, dashboard, PWA)
```

**Consideraciones de escala:**
- El rate limiter en memoria → mover a **Redis** en multi-replica.
- SQLite → **PostgreSQL** para concurrencia.
- Jobs async de batch (`/api/v2/batch`) corren en threads; para cargas pesadas
  migrar a un worker real (Celery/ARQ).
- `B2B_CORS_ORIGINS` debe apuntar al dominio real de la UI si se separan.

---

## 7. Directories

```
b2b_ai/
├── cfdi/            # parser CFDI 4.0 · catálogos SAT · validador fiscal (DIOT, IVA, retenciones) · cancelación
├── tools/           # framework de tool calling: @tool, registry, router, logger de auditoría
├── erp/             # ERPInterface (abstracta) · MockCONTPAQi · CSV fallback
├── computer_use/    # BrowserAutomation (abstracta) · MockBrowser · navigate/login/upload/read_screen · drivers aspel/contpaqi
├── db/              # schema multi-tenant + migraciones · tenants · pool
├── notifications/   # email SMTP · WhatsApp mock · plantillas por evento
├── services/        # pipeline (orquestador) · classify · reconcile · report · payroll · accounting · contabilidad_electronica · collections · analytics · anomaly
├── agent/           # loop.py — LLM + árbol de decisión + human-in-the-loop
├── api/             # app.py (FastAPI) · auth.py · v2.py · portal.py · webhooks.py · dashboard.py · metrics.py · static/
├── cli.py           # comando `bb-ai`
landing/             # landing page A (principal + dashboard)
landing-b/           # landing page B (alternativa estática + vercel.json)
docs/                # documentación
tests/               # unit + integración
fixtures/cfdis/      # CFDIs de ejemplo
```
