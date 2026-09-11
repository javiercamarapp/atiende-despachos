<p align="center"><img src="docs/brand/atiende-wordmark.svg" width="240" alt="atiende" /></p>

<h3 align="center">El agente de IA que procesa CFDI, captura en CONTPAQi/Aspel y prepara la contabilidad de un despacho — para que el contador solo firme.</h3>

---

> **Antes: un despacho captura CFDI a mano, factura por factura, en CONTPAQi.
> Después: el agente valida, clasifica y prepara la póliza — el contador
> revisa y firma.**

**No sustituye al contador público: prepara y valida para que él decida.**
Toda salida con efecto fiscal lleva referencia legal, supuesto explícito y
la marca `requires_human_review`. La cancelación de un CFDI y la
presentación ante el SAT siempre requieren e.firma humana.

## El problema

Un despacho contable mexicano vive del CFDI 4.0: cada factura que entra o
sale debe validarse contra el SAT, clasificarse contablemente, capturarse en
el ERP del cliente y conciliarse contra el banco — y casi ningún despacho
tiene una vía distinta a la captura manual para lograrlo. La mayoría opera
sobre CONTPAQi o Aspel, sistemas de escritorio sin una API pública estable,
así que cada factura significa que alguien la abre, la lee y la vuelve a
teclear. La nómina, la DIOT, la contabilidad electrónica y la cobranza
corren en paralelo con el mismo patrón: trabajo repetitivo de alto riesgo
fiscal que un humano hace por volumen, no por juicio profesional. El costo
no es solo el tiempo — es el error de captura que nadie detecta hasta la
auditoría.

## Mercado

Los contribuyentes mexicanos emitieron **más de 10,323 millones de CFDI en
2023** (327 facturas por segundo, en promedio), según cifras oficiales del
[SAT](https://www.gob.mx/sat/prensa/contribuyentes-emiten-mas-de-10-mil-millones-de-facturas-electronicas-en-2023-018-2024).
Cada uno de esos documentos es, en algún despacho contable, un CFDI que hay
que validar, clasificar y capturar. No tenemos todavía una cifra propia y
verificada del número de despachos contables en México ni del tamaño en
pesos de ese mercado — antes que fabricar un TAM, preferimos dejarlo
pendiente hasta tener una fuente primaria que lo sostenga.

## Qué hace hoy

- **Pipeline de CFDI 4.0 determinista**: parser completo, validación fiscal
  (aritmética, catálogos SAT, RFC, retenciones, DIOT), clasificación de
  gastos y generación de póliza ERP — corre 100% con reglas, sin LLM en el
  camino crítico.
- **LLM opcional** (OpenAI, DeepSeek, Anthropic u OpenRouter vía
  `B2B_LLM_PROVIDER`) para clasificación asistida y detección de anomalías,
  con **fallback automático a reglas** si el LLM falla o no hay clave. El
  LLM propone; la decisión fiscal siempre es de código auditable o humana.
- **Multi-tenant real**: onboarding por cliente (RFC, ERP, plantilla
  contable, canal de notificación), API keys por despacho y aislamiento de
  datos entre tenants.
- **API REST** (`/api/v1/*` y `/api/v2/*`) con auth por `X-API-Key`, rate
  limiting por tenant (Redis o PostgreSQL) y OpenAPI interactivo en `/docs`.
- **Dashboard web** gerencial y **portal de cliente** en React (`apps/web`)
  para que el cliente suba sus facturas desde el navegador.
- **Nómina CFDI**: ISR, IMSS, INFONAVIT, PTU, aguinaldo y prima vacacional,
  con generación del XML de nómina (complemento Nómina 1.2).
- **Contabilidad electrónica**: catálogo de cuentas (CUC), balanza de
  comprobación y paquete SAT en XML.
- **Conciliación bancaria** (CSV/PDF) y **cobranza automatizada** (aging,
  score de cobrabilidad, recordatorios por etapa).
- **Integraciones de gobierno y comunicación**: adaptadores para IMSS,
  INFONAVIT, CONDUSEF, Google/Microsoft (Sheets, Calendar, Excel, Outlook) y
  proveedores de email/SMS (SendGrid, Twilio, Mailgun, AWS SES, entre otros).
- **Facturación del propio servicio**: cobro por Stripe y Conekta.
- **Webhooks** inbound y outbound con reintentos (backoff exponencial) y
  bitácora de entregas.
- **290 archivos de test** (`pytest`) cubriendo parser, validación fiscal,
  multi-tenant, API, nómina, conciliación, cobranza, seguridad y el loop del
  agente.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11 · FastAPI · Pydantic v2 · uvicorn |
| Datos | PostgreSQL (`psycopg`) con fallback a SQLite · Alembic · Redis opcional |
| CFDI / fiscal | `lxml` · `defusedxml` · `signxml` · `pdfplumber` · catálogos SAT propios |
| LLM | OpenAI, DeepSeek, Anthropic u OpenRouter — opcional, con fallback a reglas |
| Portal cliente | React 18 · Vite · TypeScript · Tailwind · Radix UI (`apps/web`) |
| Computer use | Driver propio (`ComputerUseDriver`) sobre Playwright / pywinauto |
| Pagos | Stripe · Conekta |
| Infra | Docker + docker-compose (app, Redis, nginx) · Railway |
| CI | GitHub Actions — pytest + Playwright + Bandit en cada push a `main` |

## Estado

**En producción / verificado**: el pipeline de CFDI (parser, validación
fiscal, DIOT, retenciones), el motor multi-tenant, la API (`/api/v1` y
`/api/v2` con auth), nómina, conciliación, cobranza, contabilidad
electrónica, webhooks y el portal React — todo con suite de pytest
pasando en CI en cada push.

**Escrito, corriendo solo contra simuladores locales — pendiente de
credenciales o cuenta real, no de código**:

- El adaptador de **FacturAPI** (PAC de timbrado) hace llamadas HTTP reales
  a su API pública, pero nunca se ha corrido contra una cuenta real de
  FacturAPI — solo contra un simulador local.
- El driver de **CONTPAQi** vía RPA de escritorio (`pywinauto`) está escrito
  contra el flujo público y documentado de "Captura de pólizas", pero nunca
  se ha ejecutado contra una instalación real de CONTPAQi; en este entorno
  corre contra un simulador HTTP.
- El driver de **Aspel** vía Playwright tiene el mismo estado: código
  completo, sin verificación contra un Aspel real.
- El RPA sobre el **portal público del SAT** para DIOT (para evitar un PAC
  de pago) nunca se ha corrido contra `sat.gob.mx`; un control técnico
  explícito (`_assert_host_is_not_real_sat`) le impide conectarse a
  cualquier host `*.gob.mx` por error de configuración, y solo corre contra
  un simulador local.

Cada uno de estos módulos declara en su propio código una constante como
`VERIFICADO_CONTRA_REAL = False` para que ningún llamador confunda "código
completo" con "probado contra el sistema real". Actualizarla a `True`
requiere correrlo una vez contra la cuenta o el sistema real y documentarlo.

**Pendiente de decisión de negocio**: WhatsApp Business y SMTP reales
(hoy el sistema simula las notificaciones si no hay credenciales
configuradas); la cancelación ejecutada de un CFDI y la presentación ante
el SAT siempre exigen e.firma humana y no se automatizan.

---

## Documentación

| Guía | Para quién | Contenido |
|---|---|---|
| [docs/api-reference.md](docs/api-reference.md) | Integradores | Referencia completa de la API: endpoints, auth, errores, rate limiting, paginación. |
| [docs/architecture.md](docs/architecture.md) | Arquitectos / DevOps | Visión del sistema, componentes, flujo de datos, multi-tenant, seguridad, deploy. |
| [docs/user-guide.md](docs/user-guide.md) | Contadores / usuarios | Cómo procesar CFDI, usar el dashboard y configurar integraciones. |
| [docs/admin-guide.md](docs/admin-guide.md) | Administradores | Modelo multi-tenant, creación de tenants y API keys, operación. |
| [docs/developer-guide.md](docs/developer-guide.md) | Desarrolladores | Cómo extender con nuevos ERPs (API REST y computer use). |

## Desarrollo local

### Requisitos

- Python **3.11+**
- Opcional: Docker + Docker Compose, Node.js 18+ (para `apps/web`)

### Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # instala b2b-ai y la CLI `bb-ai`
cp .env.example .env      # luego edita .env
```

### Docker

```bash
cp .env.example .env && vi .env   # define B2B_API_KEY
docker compose up --build -d
# API en http://localhost:8000 · Docs en /docs · DB persistente en volumen
```

### Quick start

```bash
cp .env.example .env && vi .env      # 1. define B2B_API_KEY (openssl rand -hex 32)
./start.sh                           # 2. levanta landing + API + DB
./test.sh --smoke                    # 3. verifica que todo responde
```

```bash
KEY=$(grep B2B_API_KEY .env | cut -d= -f2)
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/stats

# Procesar un CFDI (multipart)
curl -X POST http://localhost:8000/api/v1/invoices/process \
  -H "X-API-Key: $KEY" \
  -F "xml_file=@fixtures/cfdis/01_gasto_operativo_papeleria.xml"
```

### Testing

```bash
python -m pytest -q        # suite completa (unit + integración)
./test.sh --all            # tests + smoke sobre contenedor
```

### CLI (`bb-ai`)

| Comando | Descripción |
|---|---|
| `bb-ai status` | Estado del sistema: versión, DB, esquema, tenants, facturas, audit, tools y rutas registradas. |
| `bb-ai process <archivo.xml>` | Procesa un CFDI por el pipeline completo. |
| `bb-ai batch <carpeta/>` | Procesa todos los CFDI `*.xml` de una carpeta. |
| `bb-ai report --period YYYY-MM` | Genera un reporte mensual de agregados. |

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

**Proprietary** (ver `pyproject.toml`). Uso interno del proyecto Atiende Despachos; no
redistribuible sin autorización expresa.
