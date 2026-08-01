# B&B AI — Agente Contable (expansión enterprise)

Agente de IA **enterprise** para despachos contables. Automatiza el ciclo de vida
de la facturación electrónica mexicana (CFDI 4.0): captura, validación fiscal,
clasificación, póliza ERP, conciliación bancaria, nómina, contabilidad
electrónica y cobranza — con un diseño **multi-tenant**, **API REST** protegida
por API key, **dashboard web** y **CLI** `bb-ai`.

> **Aviso rector**: es una herramienta que **prepara y valida**; el profesional
> **determina y firma**. No sustituye a un contador público ni presenta nada ante
> el SAT. Cada salida con efecto fiscal lleva referencia legal + supuesto + flag
> `requires_human_review`. La cancelación ejecutada y la presentación SAT exigen
> e.firma humana; nunca se auto-cancelan montos relevantes.

---

## Features

- **Procesamiento de CFDI 4.0** de punta a punta: parser completo, validación
  fiscal (aritmética, catálogos SAT, RFC, DIOT, retenciones, nómina), clasificación
  de gastos y generación de póliza ERP. El pipeline corre 100% con reglas, sin LLM.
- **LLM opcional** (OpenAI / DeepSeek / Anthropic / OpenRouter) para clasificación
  asistida, extracción y detección de anomalías, con **fallback automático a reglas**
  si el LLM falla o no hay clave. El LLM propone; la decisión fiscal es humana.
- **Multi-tenant**: onboarding por cliente (RFC, ERP, plantilla contable, canal de
  notificación, política), API keys por despacho, **aislamiento de datos** y
  bloqueo/desbloqueo de tenants.
- **API REST** (`/api/v1/*` y `/api/v2/*`) con auth por API key (`X-API-Key`),
  rate limiting, auditoría y OpenAPI interactivo en `/docs`.
- **Dashboard web** gerencial (HTML + Chart.js) y **portal de cliente** (subida de
  facturas desde el navegador, magic-link).
- **Conciliación bancaria**: parsers de estado de cuenta CSV y PDF, matching por
  monto + fecha + referencia.
- **Nómina CFDI**: cálculo ISR, IMSS, INFONAVIT, PTU, aguinaldo, vacaciones y
  prima vacacional; genera XML de nómina CFDI 4.0 con complemento Nomina 1.2.
- **Contabilidad electrónica**: catálogo de cuentas (CUC), balanza de comprobación
  y paquete SAT en XML, con SHA-1 del acuse.
- **Cobranza automatizada** (collections agent): aging, score de cobrabilidad,
  recordatorios por etapa y canal.
- **Webhooks**: inbound (facturas por email mock) y outbound con retry (backoff
  exponencial) y bitácora de entregas.
- **Computer use**: navegación de ERPs web sin API REST estable (CONTPAQi, SAP B1,
  Odoo) mediante driver vision-based; `MockBrowser` funcional para test/demo.
- **PWA** instalable y mobile-responsive: landing, dashboard y service worker
  offline.
- **Landing pages** (A y B) estáticas, responsive, con formulario de leads.
- **Contenedor Docker** + docker-compose, deploy a Railway/Vercel/Netlify.

---

## Documentación

| Guía | Para quién | Contenido |
|---|---|---|
| [docs/api-reference.md](docs/api-reference.md) | Integradores | Referencia completa de la API: endpoints, auth, errores, rate limiting, paginación. |
| [docs/architecture.md](docs/architecture.md) | Arquitectos / DevOps | Visión del sistema, componentes, flujo de datos, multi-tenant, seguridad, deploy. |
| [docs/user-guide.md](docs/user-guide.md) | Contadores / usuarios | Cómo procesar CFDI, usar el dashboard y configurar integraciones. |
| [docs/api-documentation.md](docs/api-documentation.md) | Integradores | Detalle histórico de schemas y ejemplos (legacy). |
| [docs/admin-guide.md](docs/admin-guide.md) | Administradores | Modelo multi-tenant, creación de tenants y API keys, operación. |
| [docs/developer-guide.md](docs/developer-guide.md) | Desarrolladores | Cómo extender con nuevos ERPs (API REST y computer use). |

---

## Arquitectura (diagrama)

```
                    ┌────────────────────────────────────────────────────┐
                    │                    Clientes                        │
                    │   CLI bb-ai · Dashboard · Portal · Landing · API   │
                    └───────────────┬────────────────────────────────────┘
                                    │  HTTPS  (X-API-Key / portal token)
                                    ▼
                    ┌────────────────────────────────────────────────────┐
                    │                   FastAPI app                      │
                    │  /api/v1/* · /api/v2/* · /portal/* · /dashboard/   │
                    │  auth(APIKeyAuth) · rate-limit · metrics · CORS    │
                    └───────────────┬────────────────────────────────────┘
                                    │
        ┌───────────────┬───────────┴──────────────┬───────────────┐
        ▼               ▼                          ▼               ▼
┌───────────────┐ ┌───────────────┐      ┌───────────────┐  ┌──────────────┐
│  cfdi/        │ │ services/     │      │ erp/          │  │ notifications│
│ parser·valid  │ │ pipeline      │      │ CONTPAQi mock │  │ email·WA mock│
│ catalogs·cancel│ │ classify·report│      │ CSV fallback  │  │ plantillas   │
└───────────────┘ │ reconcile     │      └───────────────┘  └──────────────┘
                  │ payroll·acctg │      ┌───────────────┐
                  │ collections   │      │ computer_use/ │  ┌──────────────┐
                  │ contabilidad  │      │ BrowserAutom. │  │ agent/loop.py│
                  └──────┬────────┘      │ MockBrowser   │  │ LLM + HITL   │
                         │               └───────────────┘  └──────────────┘
                         ▼
              ┌──────────────────────┐
              │   db/  (SQLite)      │
              │ multi-tenant schema  │
              │ tenants·users·invoices│
              │ api_keys·audit_log   │
              └──────────────────────┘
```

---

## Instalación

### Requisitos

- Python **3.9+**
- Opcional: Docker + Docker Compose

### Local (venv)

```bash
cd enterprise
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # instala b2b-ai y la CLI `bb-ai`
cp .env.example .env      # luego edita .env
```

### Docker

```bash
cd enterprise
cp .env.example .env && vi .env   # define B2B_API_KEY
docker compose up --build -d
# API en http://localhost:8000 · Docs en /docs · DB persistente en volumen
```

Solo la imagen:

```bash
docker build -t b2b-ai:1.0.0 .
docker run --rm -p 8000:8000 -e B2B_API_KEY=secret b2b-ai:1.0.0
```

---

## Quick start

```bash
cd enterprise
cp .env.example .env && vi .env      # 1. define B2B_API_KEY (openssl rand -hex 32)
./start.sh                           # 2. levanta landing + API + DB
./test.sh --smoke                    # 3. verifica que todo responde
```

Tras arrancar:

| URL | Qué es |
|---|---|
| `http://localhost:8000/` | Landing page (mismo origen) |
| `http://localhost:8000/docs` | Swagger / OpenAPI interactivo |
| `http://localhost:8000/health` | Health check + versión + estado DB |
| `http://localhost:8000/api/v1/stats` | Métricas (requiere `X-API-Key`) |

Probar la API:

```bash
KEY=$(grep B2B_API_KEY .env | cut -d= -f2)
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/stats

# Procesar un CFDI (multipart)
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" \
  -F "xml_file=@fixtures/cfdis/01_gasto_operativo_papeleria.xml"
```

Detener / probar / limpiar:

```bash
./stop.sh            # detiene (conserva la DB en el volumen)
./stop.sh --purge    # detiene Y borra la DB persistente
./test.sh            # suite completa (pytest)
./test.sh --all      # tests + smoke test sobre el contenedor
```

> **Sin Docker**: `./start.sh --local` arranca uvicorn directamente; crea `.venv`
> e instala dependencias automáticamente si no existen.

---

## Configuration (variables de entorno)

Copia `.env.example` a `.env`. Resumen:

| Variable | Default | Descripción |
|---|---|---|
| `B2B_API_KEY` | `change-me` | Key maestra de servicio. Exigida en header `X-API-Key` para `/api/v1/*`. Genera una con `openssl rand -hex 32`. |
| `B2B_DB_PATH` | `./b2b_ai.db` | Ruta del archivo SQLite. En Docker se fuerza `/data/b2b_ai.db`. |
| `B2B_LANDING_DIR` | auto | Ruta a la landing estática (auto-detectada). |
| `B2B_LLM_PROVIDER` | (vacío) | `openai \| deepseek \| anthropic \| openrouter` o vacío = sin LLM (solo reglas). |
| `B2B_LLM_MODEL` | por proveedor | Modelo a usar (ver `.env.example`). |
| `B2B_LLM_BASE_URL` | — | Base URL para gateways/proxies OpenAI-compatibles. |
| `B2B_OPENAI_API_KEY` / `B2B_DEEPSEEK_API_KEY` / `B2B_ANTHROPIC_API_KEY` / `B2B_OPENROUTER_API_KEY` | — | Clave del proveedor elegido. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_USE_SSL` | — | SMTP para notificaciones reales. Sin ellas, el sistema simula los mensajes (modo seguro). |
| `B2B_HOST` | `0.0.0.0` | Host del servidor uvicorn. |
| `B2B_PORT` | `8000` | Puerto del servidor uvicorn. |
| `B2B_CORS_ORIGINS` | (vacío) | Orígenes CORS permitidos, separados por coma. Vacío = CORS off (same-origin). |
| `B2B_CORS_ALLOW_CREDENTIALS` | `false` | `true` para cookies cross-origin. |
| `B2B_RATE_LIMIT` | `on` | `off` desactiva el rate limiting. |
| `B2B_RATE_LIMIT_PER_MIN` | `300` | Peticiones por IP+ruta por minuto. `0` desactiva. |
| `DEBUG` | `false` | Logs más verbosos. |
| `ENV` | — | `production` aplica restricciones de seguridad. |

---

## CLI reference (`bb-ai`)

| Comando | Descripción |
|---|---|
| `bb-ai status` | Estado del sistema: versión, DB, esquema, tenants, facturas, audit, tools y rutas registradas. |
| `bb-ai process <archivo.xml>` | Procesa un CFDI por el pipeline completo (validación, clasificación, póliza, notificación). |
| `bb-ai batch <carpeta/>` | Procesa todos los CFDI `*.xml` de una carpeta y muestra un resumen agregado. |
| `bb-ai report --period YYYY-MM` | Genera un reporte mensual de agregados (subtotal, IVA, total, por categoría). |

Flags globales: `--version`, `--db <ruta>` (base SQLite alternativa),
`--tenant-id <id>` (tenant a usar).

---

## API reference (resumen)

Documentación interactiva OpenAPI: **`http://localhost:8000/docs`** (y
`/openapi.json`). Referencia completa en [docs/api-reference.md](docs/api-reference.md).

Los endpoints `/api/v1/*` requieren una API key en el header `X-API-Key`. La
key se resuelve contra la tabla `api_keys` (multi-tenant) o contra `B2B_API_KEY`
(servicio/standalone). Endpoints públicos: `/health`, `/metrics`, `/api/v1/leads`,
landing y estáticos.

| Endpoint | Método | Descripción | Auth |
|---|---|---|---|
| `/health` | GET | Health check + versión + estado DB. | — |
| `/metrics` | GET | Métricas operativas (count, latencia por ruta, códigos). | — |
| `/api/v1/invoices/process` | POST | Procesa un CFDI (multipart `xml_file` o JSON `xml_path`). | API key |
| `/api/v1/invoices` | GET | Lista facturas con filtros + paginación. | API key |
| `/api/v1/invoices/{id}` | GET | Detalle de una factura. | API key |
| `/api/v1/stats` | GET | Métricas agregadas. | API key |
| `/api/v1/tools` | GET | Tools registradas. | API key |
| `/api/v1/leads` | POST | Alta de lead desde la landing (público). | — |
| `/api/v1/reconcile/run` | POST | Conciliación bancaria. | API key |
| `/api/v1/accounting/catalog` | GET | Catálogo de cuentas (CUC). | API key |
| `/api/v1/accounting/balance` | GET | Balanza de comprobación. | API key |
| `/api/v1/accounting/sat/send` | POST | Envío de balanza al SAT (mock). | API key |
| `/api/v1/payroll/calculate` | POST | Cálculo de nómina (+ CFDI opcional). | API key |
| `/api/v1/collections/*` | varios | Análisis, recordatorios, aging y score de cobranza. | API key |
| `/api/v1/contabilidad/*` | varios | Catálogo, asientos, balanza y paquete SAT. | API key |
| `/api/v1/dashboard*` | GET | Dashboard HTML + datos JSON. | API key |
| `/api/v1/tenants` | POST | Onboarding de un cliente (tenant). | API key |
| `/api/v1/webhooks/*` | varios | Webhooks inbound/outbound. | API key |
| `/api/v2/*` | varios | API enterprise: batch, analytics, webhooks, audit, export, usage, admin tenants. | API key |
| `/portal/*` | varios | Portal de cliente: auth, subida de facturas, dashboard. | portal token |

---

## Testing

```bash
python -m pytest -q        # suite completa (unit + integración)
./test.sh --all            # tests + smoke sobre contenedor
```

La suite cubre: parser CFDI, validación fiscal, tool calling + router + auditoría,
ERP mock + CSV, multi-tenant, notificaciones, conciliación, reportes, API con auth,
computer use (mock), landing/PWA, LLM con fallback, loop de agente, webhooks,
seguridad (e2e) y dashboard.

---

## Contributing

1. **Fork y rama**: trabaja en una rama descriptiva (`feat/`, `fix/`, `docs/`).
2. **Diseño rector**: la máquina prepara y valida; el profesional determina y
   firma. Toda salida con efecto fiscal debe llevar referencia legal + supuesto +
   flag `requires_human_review`.
3. **Tests**: añade o actualiza tests en `tests/` (pytest). La suite completa debe
   pasar: `python -m pytest -q`.
4. **Verificación**: no declares "listo" sin correr los tests y ver la salida.
5. **PR**: describe el cambio, los tests corridos y el alcance de verificación.
6. **Documentación**: actualiza README / docs si cambias la API o la arquitectura.

## License

**Proprietary** (ver `pyproject.toml`). Uso interno del proyecto B&B AI; no
redistribuible sin autorización expresa.

---

## Estado y límites conocidos

**Verificado**: parser CFDI completo, validación fiscal (incl. DIOT/retenciones),
tool calling con router + auditoría, ERP mock + CSV, multi-tenant, notificaciones,
conciliación, reportes, API (`/api/v1/*` y `/api/v2/*` con auth), computer use
(mock), landing/PWA, LLM con fallback a reglas, loop de agente con decisión y
HITL, webhooks (inbound email + outbound con retry) y onboarding multi-tenant.

**Qué NO cubre esto**: conexión real a CONTPAQi/contaDIGITAL, driver real de
computer use (Playwright/vision), WhatsApp Business y SMTP requieren credenciales;
la cancelación ejecutada y la presentación SAT requieren e.firma humana.
