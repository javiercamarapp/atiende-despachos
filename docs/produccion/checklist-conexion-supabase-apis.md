# Checklist: conectar Supabase + APIs en producción

Auditoría hecha el 2026-09-09 contra `main` (`9ed0a8b`), rama
`agent/produccion-supabase-config-v4`. Cada variable de entorno listada aquí
fue verificada con `grep` contra el código real (`os.environ.get` /
`os.getenv`) — ninguna se inventó. Rutas de archivo relativas a la raíz del
repo.

## 0. Resumen ejecutivo

El código **ya soporta Postgres remoto (Supabase) sin cambios de código**:
basta con setear `DATABASE_URL` (o `B2B_DATABASE_URL`). No se encontró
ningún host de producción hardcodeado a `localhost` o a un Postgres
embebido/SQLite fuera de tests — ver §1.

El bug documentado de `psycopg2` sin declarar **ya estaba corregido en
`main`** antes de este trabajo (commit `1a9ed8e "fix(deps): usa psycopg v3
en vez de psycopg2 no declarado"`, ya integrado a `main`) — ver §2. No hizo
falta ningún cambio de código en esta tarea.

**Hallazgo importante que este documento no puede ocultar**: el PAC de CFDI
(timbrado) **no es una integración real** pese a tener variables de API key
con nombres de proveedores reales — ver §3.1. Conectar esas claves no activa
timbrado real; falta implementar las llamadas HTTP. El doc
`docs/PRODUCTION_CHECKLIST.md` existente lista "SAT: Ecodex, Finkok, SAT
Portal" como `[x]` listo — esa fila está desactualizada/optimista frente al
código real y conviene corregirla en una tarea aparte.

---

## 1. Cadena de conexión a Postgres (Supabase)

Prioridad de resolución (confirmada en `b2b_ai/api/app.py:363-376`,
`b2b_ai/db/db.py:82-86` y `b2b_ai/db/adapter_factory.py:42-68`):

1. Parámetro explícito `db_url` (uso interno/tests)
2. `B2B_DATABASE_URL`
3. `DATABASE_URL` (estándar Railway/Heroku; Supabase usa el mismo formato)
4. `B2B_DB_URL`
5. `B2B_DB_PATH`
6. Fallback: SQLite embebido `b2b_ai.db` en la raíz del repo — **solo se usa
   si ninguna de las anteriores está seteada**, es decir, nunca en
   producción si se configura la variable.

Acción para producción: setear **una sola** de estas variables (recomendado
`DATABASE_URL`, es la que Railway ya inyecta si en algún punto se migra de
proveedor) con el connection string de Supabase:

```
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
```

Notas sobre el DSN de Supabase específicamente:

- Usar el **connection pooler de Supabase (puerto 6543, modo transaction)**
  para la app web, no el puerto directo 5432 — la app abre un pool propio
  por proceso (`b2b_ai/db/pg.py`, `PGPool`, tamaño configurable con
  `B2B_PG_POOL_MIN` / `B2B_PG_POOL_MAX` / `B2B_PG_RETRIES`, default 2/10/3 —
  confirmado en `b2b_ai/db/db.py:112-118`) y duplicar pooling de pooling
  puede agotar conexiones del lado de Supabase si se usa el puerto directo
  con varios workers (`B2B_WORKERS`, default 2 en `.env.example`).
- `sslmode=require` (o `verify-full` si se agrega el certificado de Supabase)
  debe ir **dentro del DSN** — el código no fuerza SSL por su cuenta, lo
  delega a libpq/psycopg vía el DSN, así que si se omite el query param
  Supabase igual exige TLS en el pooler pero es más explícito incluirlo.
- Las migraciones Alembic corren solas en el `lifespan` de arranque en un
  hilo de fondo (`b2b_ai/api/app.py`, comentario junto a `Database(pg_url,
  migrate=False)`) para no bloquear el healthcheck — no hace falta correr
  `alembic upgrade head` a mano en el primer deploy, aunque es la forma
  recomendada de verificarlo antes de apuntar tráfico real.
- `migrations/env.py` fuerza el driver `psycopg` (v3) para SQLAlchemy en vez
  del `psycopg2` por defecto — coherente con §2, ningún ajuste adicional
  necesario para Supabase.

Verificación manual recomendada tras configurar `DATABASE_URL`:

```bash
DATABASE_URL="postgresql://...supabase..." python scripts/deployment_readiness.py
```

(`scripts/deployment_readiness.py:24-47` ya soporta `B2B_DATABASE_URL` /
Postgres explícitamente para este propósito.)

---

## 2. Bug `psycopg2` sin declarar — ya corregido en `main`

Estado verificado en esta rama:

```
$ grep -rn "psycopg2" **/*.py
migrations/env.py:27       # comentario, no import
b2b_ai/db/adapter_factory.py:84   # comentario en docstring, no import
tests/test_postgres_adapter_integration.py:13  # comentario ("simula psycopg2 con mock"), no import real
```

No queda ningún `import psycopg2` / `from psycopg2` en el repo.
`tests/production/conftest.py:117` y `scripts/seed_demo.py:651-655` ya
importan `psycopg` (v3), que sí está declarado en `pyproject.toml` y
`requirements-production.txt` (`psycopg[binary]>=3.1`, `psycopg-pool>=3.2`).

`git log --oneline -- tests/production/conftest.py scripts/seed_demo.py`
muestra el commit `1a9ed8e "fix(deps): usa psycopg v3 en vez de psycopg2 no
declarado"`, y `git merge-base --is-ancestor 1a9ed8e HEAD` confirma que ya
es ancestro de `main` (`9ed0a8b`). **No se necesitó ningún cambio de código
en esta tarea para este punto** — se deja documentado para que quede
constancia de que se verificó, no se asumió.

---

## 3. Credenciales / API keys por integración real

Todas las variables de esta sección se confirmaron con `grep` contra el
código que las lee. Ninguna se documenta "por si acaso" sin evidencia.

### 3.1 PAC de CFDI (timbrado) — NO es una integración real todavía

Archivos: `b2b_ai/integrations/sat/pacs/{corefi,facturapi,multifactura,
paxfacturas}_adapter.py`, `b2b_ai/integrations/sat/ecodex.py`,
`b2b_ai/integrations/sat/finkok.py`.

Cada adaptador sí lee una variable de entorno con nombre de proveedor real:

| Proveedor | Variable |
|---|---|
| COREFI | `COREFI_API_KEY` |
| Facturapi | `FACTURAPI_API_KEY` |
| Multifactura | `MULTIFACTURA_API_KEY` |
| PAXFACTURAS | `PAXFACTURAS_API_KEY` |
| Ecodex | `ECODEX_API_KEY` |
| Finkok | (no lee env var — ver abajo) |

**Pero ninguno hace una llamada de red real.** Verificado explícitamente:

```
$ grep -c "httpx\.\(post\|get\|Client\)(" b2b_ai/integrations/sat/pacs/*.py b2b_ai/integrations/sat/ecodex.py b2b_ai/integrations/sat/finkok.py
→ 0 en los 6 archivos
```

El docstring de `corefi_adapter.py` lo dice explícitamente: *"Implementa la
interfaz SATAdapter con respuestas simuladas. En producción, se conectaría a
la API SOAP/REST de COREFI."* — es decir, es un placeholder que nunca se
terminó de conectar a la API real, no una integración construida esperando
credenciales. `connect()` acepta la API key pero cae siempre a "mock mode".
`finkok.py` genera folios/sellos con el prefijo `MOCK-` de forma
incondicional.

Tampoco hay ningún llamador en `b2b_ai/api/`, `b2b_ai/features/` o
`b2b_ai/services/` que instancie estos adaptadores para timbrar una factura
real — sólo aparecen en su propio módulo y en tests.

**Conclusión**: configurar `COREFI_API_KEY` / `FACTURAPI_API_KEY` / etc. en
Supabase/producción **no habilita timbrado real de CFDI**. Esto es un
faltante de código (implementar las llamadas HTTP reales a un PAC), no un
faltante de configuración — no se puede resolver con las tareas de esta
rama y hay que decírselo al dueño explícitamente para que no asuma que "solo
falta la API key".

### 3.2 Pagos: Stripe / Conekta — sí es real

A diferencia de §3.1, `b2b_ai/billing/stripe_provider.py` y
`b2b_ai/billing/conekta_provider.py` sí hacen `httpx.post` contra
`https://api.stripe.com` / `https://api.conekta.io` cuando no está en modo
mock. Router montado en producción: `b2b_ai/api/app.py` →
`build_billing_router` (de `b2b_ai/billing/api.py`).

| Variable | Uso | Dónde |
|---|---|---|
| `B2B_STRIPE_KEY` | API key secreta de Stripe | `b2b_ai/billing/base.py:181`, `stripe_provider.py` |
| `B2B_CONEKTA_KEY` | API key de Conekta | `b2b_ai/billing/base.py`, `conekta_provider.py`, `conekta_gateway.py` |
| `B2B_PAYMENTS_PROVIDER` | `conekta` fuerza Conekta aunque haya `B2B_STRIPE_KEY`; si no, Stripe si hay key | `b2b_ai/billing/base.py:169-181` |
| `B2B_PAYMENTS_MOCK` | `1` = modo mock sin red (usar solo en demo/tests, **no** en producción) | `b2b_ai/billing/base.py:50` |
| `B2B_CONEKTA_WEBHOOK_SECRET` | Verifica firma HMAC-SHA256 del webhook de Conekta (`POST /api/v1/billing/webhook`); si falta, el receptor **rechaza todo** en vez de aceptar sin verificar | `b2b_ai/billing/webhook_receiver.py:96` |

Nota: existe un módulo paralelo `b2b_ai/integrations/pagos/{stripe,conekta}
_adapter.py` con nombres de variable distintos (`STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `CONEKTA_KEY`) que **no está montado como router en
`app.py`** — sólo se usa desde `b2b_ai/integrations/hub.py`. No configurar
esas variables pensando que son las que usa el flujo de cobro real; las que
importan para el router activo son las de la tabla de arriba.

No hay verificación de firma de webhook de Stripe en el router montado (solo
Conekta la tiene) — si en el futuro se activa Stripe en producción y se
reciben sus webhooks, revisar si hace falta añadir esa verificación.

### 3.3 SAT — declaraciones automatizadas (scheduler interno)

Estas tres variables **ya están fusionadas en `main`** (confirmado con
`grep`, no se tocaron en esta rama):

| Variable | Default | Uso | Dónde |
|---|---|---|---|
| `SAT_PORTAL_URL` | vacío (RPA deshabilitado) | URL del portal SAT (simulador o real) para el driver RPA de declaraciones | `b2b_ai/features/declaraciones/sat_rpa_bridge.py:269`, `sat_portal_rpa_driver.py` |
| `B2B_SAT_SUBMIT_MODE` | `stub` | `stub` = nunca toca red, siempre `simulado=True`; `rpa` = usa el driver real solo para DIOT | `b2b_ai/features/declaraciones/sat_rpa_bridge.py:66-75` |
| `B2B_SCHEDULER_ENABLED` | `true` | Flag maestro que apaga/prende el scheduler interno que dispara SAT y CFDIs pendientes | `b2b_ai/scheduler/internal_scheduler.py:83-89` |

**Barrera de seguridad ya existente en el código, y que es intencional, no
un bug**: `sat_portal_rpa_driver.py` implementa
`_assert_host_is_not_real_sat()`, que **lanza una excepción y bloquea** si
`SAT_PORTAL_URL` resuelve a cualquier host bajo `*.gob.mx` (incluido
`sat.gob.mx`) — confirmado en `sat_portal_rpa_driver.py:121-137` y reforzado
"en profundidad" en dos puntos distintos del archivo. El propio
`sat_rpa_bridge.py` documenta que nunca se debe debilitar esa defensa.

Esto significa que **el modo `rpa` de este scheduler nunca podrá presentar
nada ante el SAT real** apuntando `SAT_PORTAL_URL` al dominio verdadero —
ese bloqueo es deliberado (evita que un error de configuración dispare un
trámite fiscal real sin supervisión). Y aunque no lo estuviera,
`SATPortalRPADriver` sólo sabe presentar DIOT (sube un archivo), no
IVA/ISR mensual/anual — para esos tipos, `declaration_api.py` sigue usando
siempre el stub, incluso con `B2B_SAT_SUBMIT_MODE=rpa`.

Ver §4 — esto es la raíz del bloqueo de negocio, no algo que
`SAT_PORTAL_URL` pueda resolver por sí solo.

### 3.4 Otras variables ya soportadas (sin cambios, listadas por completitud)

Confirmadas contra `.env.example` y el código; no fusionadas en esta rama,
sólo documentadas porque son necesarias para el arranque en producción:

| Variable | Uso |
|---|---|
| `B2B_JWT_SECRET` | Firma de tokens. Fail-fast: sin ella y `B2B_ENV` != dev, el arranque falla (`b2b_ai/auth/middleware.py:120-125`) |
| `B2B_ENCRYPTION_KEY` | Cifrado AES-GCM en reposo (PII/config sensible). Fail-fast si falta o < 16 chars y no es dev (`b2b_ai/api/app.py:387-393`) |
| `B2B_API_KEY` | API key de acceso a la API pública |
| `B2B_ENV` | `development` \| `production` \| `test` — gatea todos los fail-fast anteriores |
| `B2B_REDIS_URL` | Opcional; rate limiter usa memoria si no está |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Notificaciones por correo (`b2b_ai/features/alertas/notification_service.py`) |
| `CONTPAQI_URL` / `CONTPAQI_USERNAME` / `CONTPAQI_PASSWORD` | Sólo si `B2B_COMPUTER_USE_MODE=playwright` — ver §4 |

---

## 4. Bloqueo NO resuelto por código (bloqueo de negocio, no técnico)

No existe combinación de variables de entorno ni configuración de Supabase
que resuelva esto — requiere una acción humana recurrente de Javier:

1. **VM Windows con CONTPAQi real.** `b2b_ai/computer_use/config.py` sólo
   activa automatización de escritorio real cuando
   `B2B_COMPUTER_USE_MODE=playwright` (default: `disabled`), y sólo apunta a
   una instancia real de CONTPAQi si se configuran `CONTPAQI_URL` /
   `CONTPAQI_USERNAME` / `CONTPAQI_PASSWORD` contra una VM Windows con
   CONTPAQi instalado y con licencia — eso no es algo que Supabase, una API
   key o una variable de entorno puedan crear. Sin esa VM, el sistema sigue
   funcionando contra el simulador (`contpaqi_simulator_server.py`), que es
   deliberadamente no-real.

2. **Sesión manual de Javier en el portal del SAT.** Por diseño (§3.3), el
   código **bloquea activamente** cualquier intento de que el RPA toque
   `*.gob.mx`, y aunque no lo bloqueara, el driver RPA solo cubre DIOT. La
   presentación real de declaraciones (IVA/ISR) y cualquier trámite que
   dependa de la FIEL/e.firma de un contribuyente en el portal real del SAT
   sigue requiriendo que Javier (o quien tenga la e.firma) entre y lo haga a
   mano. Esto es intencional y de seguridad, no un TODO pendiente de
   codificar.

Ninguno de los dos bloqueos anteriores se resuelve conectando Supabase ni
configurando APIs — son limitaciones operativas/de negocio explícitas en el
diseño actual del código, y deben comunicarse como tales al dueño del
proyecto en vez de presentarse como "falta configurar X".

---

## 5. Verificación ejecutada en esta rama

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[test]" -r requirements-production.txt
.venv/bin/python -m pytest tests/production/ -q
# → 24 passed, 4 skipped (skips: fixtures de infra real Postgres/Redis vía
#   docker, se saltan solas si docker no está disponible — ver
#   tests/production/conftest.py), 27.70s

.venv/bin/python -m pytest tests/test_db_pg_failfast.py tests/test_postgres_adapter_integration.py -q
# → 124 passed

.venv/bin/python -m pytest tests/test_internal_scheduler.py tests/test_sat_submit_rpa_bridge.py -q
# → 49 passed
```

No se corrió la suite completa (7800+ tests) — fuera del alcance pedido
para esta tarea.
