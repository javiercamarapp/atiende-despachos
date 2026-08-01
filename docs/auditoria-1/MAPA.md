# Mapa del repo — para los auditores (ronda 1)

Repo local: `~/Desktop/B2B-AI-MVP/enterprise` (GitHub:
`javiercamarapp/likida-ai-enterprise`, rama `main`). Producto: agente de IA
para **despachos contables mexicanos** — automatiza captura, validación
fiscal, clasificación, póliza ERP, conciliación bancaria, nómina, contabilidad
electrónica y cobranza de CFDI 4.0. Pre-revenue, sin clientes reales:
construido en ~14 horas (106 commits) el 31-jul/1-ago-2026, vía un pipeline de
agente disparado por WhatsApp (Hermes), con MiniMax 2.5.

**Esta es la PRIMERA auditoría de este repo — no hay ronda anterior.** No hay
nota previa que defender ni recalibrar: los doce rubros parten de cero. La
escala y las anclas son las mismas que usa `likida.ai` (0-10, ver
`references/rubros.md` de la skill `auditoria-diaria`), pero **el "dónde" de
cada rubro es distinto** porque el stack es Python/FastAPI, no TypeScript.

## El repo se está construyendo AHORA MISMO — dilo si lo notas

En las últimas dos horas este árbol tuvo archivos apareciendo y
desapareciendo entre una corrida de pruebas y la siguiente (un proceso
automatizado sigue trabajando). El commit base de esta ronda es
`f4944ab`. Si al abrir un archivo citado abajo no coincide exactamente con lo
descrito, anótalo — es información, no un error tuyo.

## Lo que YA se sabe, verificado antes de esta ronda — no lo redescubras, VERIFÍCALO o profundízalo

1. **La capa de Postgres tiene 3 bugs bloqueantes SIN aplicar al código.**
   `PG_BUG_REPORT.md` (raíz del repo, 31-jul) los documenta con traceback real
   contra un PG de verdad: `insert_invoice` usa placeholders `:nombre` que
   PostgreSQL no acepta, `log_call` escribe `''` en vez de `NULL` en una
   columna `jsonb`, y `upsert_outstanding_invoice` hace `ON CONFLICT` sin que
   exista el constraint único. Los fixes se probaron en un sandbox y **nunca
   se aplicaron**: `git log -- b2b_ai/db/pg.py` solo tiene el commit inicial.
   Todos los tests (4900+) corren contra SQLite (`db/db.py`), no contra
   `db/pg.py`. Confírmalo tú mismo si te toca el rubro de datos o backend.
2. **El landing (`landing/index.html`) tiene un testimonio inventado** ("—
   Socio de despacho contable, plan Pro", sin cliente real) y una cifra "56%
   menos tiempo en captura" sin fuente en el `<title>` y meta description.
3. **El producto tiene tres nombres en el mismo repo:** el README dice "B&B
   AI", el landing dice "Likida AI", el repo de GitHub es
   `likida-ai-enterprise`. Verifica si ya se corrigió (hay un commit reciente
   de "rebrand B&B AI → Likida AI Enterprise across codebase").
4. **"Computer use" sobre CONTPAQi/Aspel está mockeado, no es real** —
   `computer_use/browser.py` es un `MockBrowser`; `contpaqi_driver.py` y
   `aspel_driver.py` existen pero el README lo admite: "conexión real a
   CONTPAQi/contaDIGITAL" y "driver real de computer use (Playwright/vision)"
   están en la lista de lo que NO cubre el repo.
5. **Migraciones duplicadas:** `migrations/versions/` tiene DOS archivos
   `0005_*` (`0005_bank_reconciliation_state.py` y
   `0005_outstanding_unique.py`). Alembic puede aceptar esto por casualidad de
   orden alfabético/timestamp o puede estar rompiendo la cadena de head —
   verifícalo si te toca datos u operabilidad.
6. **No existe un sistema de trazabilidad normativa como el de likida.ai.**
   No hay `normas/*.yaml` con `verificado_fuente_primaria`. La lógica fiscal
   (ISR, IMSS, DIOT, requisitos de CFDI) vive directo en el código
   (`cfdi/validator.py`, `services/payroll.py`, `services/diot_validator.py`)
   sin ficha que cite el artículo exacto. Si el rubro fiscal encuentra una
   cifra mal calculada, es doblemente grave: no hay ni el mecanismo para
   rastrear de dónde salió la regla.
7. **`ruff check .` da 6,365 hallazgos** con el ruleset por default — no tiene
   config propia (`pyproject.toml` no trae sección `[tool.ruff]`), así que ese
   número por sí solo no es informativo. No lo repitas como si fuera una nota;
   si quieres usarlo, filtra por regla y di cuáles importan.

## Dónde está todo, por rubro

- **1 Frontend:** `landing/`, `landing-b/` (dos landings), `b2b_ai/portal/`
  (portal de cliente, templates Jinja2 si los hay), `b2b_ai/api/dashboard.py`
  (dashboard HTML + Chart.js).
- **2 Backend y API:** `b2b_ai/api/app.py` (FastAPI app, rutas, CORS,
  rate-limit), `api/v2.py` (API enterprise: batch, analytics, webhooks, audit,
  export), `api/webhooks.py`, `api/reconciliation.py`, `api/outreach.py`,
  `api/portal.py`, `api/analytics.py`, `api/metrics.py`.
- **3 Sistema agéntico y orquestación:** `b2b_ai/agent/loop.py` (el loop del
  agente, HITL), `b2b_ai/services/pipeline.py` (el pipeline CFDI→validar→
  clasificar→póliza), `services/classify.py`.
- **4 Tool calling:** `b2b_ai/tools/registry.py`, `tools/router.py`,
  `tools/tools.py`, `b2b_ai/services/llm.py` (fallback entre OpenAI/DeepSeek/
  Anthropic/OpenRouter, y el fallback a reglas si no hay LLM).
- **5 Seguridad:** `b2b_ai/auth/middleware.py` (303 líneas — aquí vivía el
  hallazgo P1 ya cerrado del JWT hardcodeado, confirma que sigue cerrado),
  `auth/roles.py`, `auth/users.py`, `api/security.py`, `api/security_headers.py`,
  `billing/stripe_provider.py` + `conekta_provider.py` (firma de webhooks de
  pago — dinero real si esto se conecta).
- **6 Cumplimiento fiscal:** `b2b_ai/cfdi/validator.py`, `cfdi/parser.py`,
  `cfdi/cancellation.py`, `cfdi/catalogs.py`, `b2b_ai/sat/validator.py`,
  `services/diot_validator.py`, `services/diot_service.py`,
  `services/payroll.py` (ISR/IMSS/INFONAVIT/PTU/aguinaldo),
  `services/contabilidad_electronica.py`, `services/balanza.py`. **No hay
  fichas normativas — la comparación es contra la ley directamente, citando
  artículo si el código lo hace.**
- **7 Cumplimiento legal:** datos personales de CLIENTES del despacho (RFC,
  domicilio fiscal, información bancaria en conciliación). `auth/users.py`,
  `notifications/` (SMTP/WhatsApp — toda salida a un proveedor externo es una
  transferencia), `portal/routes.py` (subida de documentos del cliente),
  `db/models.py` (qué se guarda y por cuánto tiempo). No hay aviso de
  privacidad ni política visible en el landing — confírmalo.
- **8 Arquitectura y mantenibilidad:** `b2b_ai/db/db.py` (1,508 líneas,
  SQLite — la fuente real hoy) vs `db/pg.py` (289 líneas, Postgres — la que
  se supone se usaría en producción vía Railway, con los 3 bugs del punto 1).
  ¿Hay una tercera copia de la misma lógica de negocio en otro lado?
- **9 Pruebas:** `tests/` (100+ archivos). Igual que en likida.ai: toma 3-4
  pruebas que protejan dinero o fiscal y mídeles mutantes de verdad —
  cambiar la función y ver si la prueba sigue verde.
- **10 Operabilidad y DX:** `DEPLOY-GUIDE.md`, `Dockerfile`,
  `docker-compose.prod.yml`, `Procfile`, `railway.toml`, `b2b_ai/monitoring/`,
  `.env.production.example`, `start.sh`/`stop.sh`/`test.sh`. Si el DEPLOY-GUIDE
  apunta a Railway con Postgres, cruza con el punto 1: seguirla tal cual hoy
  rompe en el primer insert.
- **11 Rendimiento y costo:** `services/llm.py` (costo por proveedor),
  `db/pool.py`, `computer_use/browser.py` (el MockBrowser no tiene costo real
  todavía, pero el driver real si se conecta sí).
- **12 Modelo de datos y esquema:** `migrations/versions/` (12+ archivos,
  incluida la duplicidad `0005`), `db/models.py`, `alembic.ini`. Compara contra
  `db/pg.py` para la deriva de esquema del punto 1.

## Línea base verificada por el orquestador, hoy, en esta máquina

```
python -m pytest -q     4900 passed, 16 skipped, 0 failed   (141.65s)
ruff check .             6,365 hallazgos, sin config propia — no citar como nota
```

No se corrió `mypy` (sin config visible de tipo estricto) ni `docker build`.

## Restricciones

- **No modifiques NINGÚN archivo del repo.** Solo lectura: tú encuentras y
  calificas, el orquestador decide si arregla — y esta ronda, por el árbol
  cambiando bajo la mano y por ser la primera ronda sin precedente, **NO se
  van a arreglar críticos hoy**. Es una auditoría de diagnóstico, no de
  arreglo.
- Puedes correr `python -m pytest`, `ruff check`, leer y buscar.
- No corras nada que mande correos, SMS o llamadas reales (`notifications/`,
  `billing/*_provider.py` en modo real) ni que pegue a APIs de pago.
- No escribas fuera de `docs/auditoria-1/<tu-rubro>.md`.

## No hay auditoría anterior

Esta es la ronda 1. No hay `docs/auditoria-0/` que leer.
