# Operabilidad y DX — auditoría 1

**Nota: 3/10 (ronda 1, sin nota previa)**

Seguir `DEPLOY-GUIDE.md` tal cual está escrito hoy produce uno de dos desenlaces
según qué tan literal se siga: si nadie toca `B2B_DB_URL` a mano (que es
exactamente lo que la guía pide — "no configures `DATABASE_URL`
manualmente"), la API arranca sin error y pierde en silencio cada factura
procesada en el próximo redeploy, porque nunca llegó a tocar el Postgres que
Railway factura; si alguien sí conecta bien `B2B_DB_URL`, la API entra en
crash-loop en el primer arranque por una colisión de migraciones. Y el único
endpoint que debería avisar cuál de los dos escenarios está pasando —
`/health`, el que Railway sondea cada 15s — miente siempre diciendo
`"backend": "sqlite"`, pase lo que pase.

## Hallazgos

### [CRÍTICO] El camino Railway+Postgres de DEPLOY-GUIDE.md nunca toca Postgres — pérdida silenciosa de datos en cada redeploy
`b2b_ai/db/db.py:18-21`, `Dockerfile:50`, `railway.toml:15-29`, `.env.railway.example:16-19`, `.env.production.example:40-42`

Escenario: un operador sigue `DEPLOY-GUIDE.md` §2.1 y §4 al pie de la letra —
agrega el add-on de PostgreSQL (`railway add --plugin postgresql`) y **no**
configura `DATABASE_URL` a mano porque la guía se lo prohíbe explícitamente
dos veces ("Railway crea automáticamente las variables `DATABASE_URL`... No
las configures manualmente"; tabla "Variables que NO debes tocar" en la
§4). Railway inyecta `DATABASE_URL=postgresql://postgres:***@postgres.railway.internal:5432/railway`.
Pero `DEFAULT_DB` (`db.py:18-20`) solo lee `os.environ.get("B2B_DB_URL")` o
`os.environ.get("B2B_DB_PATH")` — nunca `DATABASE_URL`. Ninguno de los dos
existe, así que cae al tercer default: el `Dockerfile` fija
`ENV ... B2B_DB_PATH=/data/b2b_ai.db` (línea 50) a nivel de imagen. El
contenedor arranca sin error, `/health` responde 200, la API procesa
facturas con normalidad — todo escrito en un SQLite dentro del filesystem
efímero del contenedor (`railway.toml` no declara ningún volumen). En el
siguiente deploy o restart, Railway reemplaza el contenedor:
`/data/b2b_ai.db` desaparece con todas las facturas procesadas desde el
deploy anterior, sin error, log ni alerta.

Consecuencia: el despacho contable pierde silenciosamente cada factura
procesada entre dos deploys; nadie se entera hasta que falta un CFDI en una
auditoría fiscal real. El Postgres que la propia guía cotiza en ~$20/mes
(§10) nunca recibe una sola fila.

Causa raíz probable: nadie mapeó `DATABASE_URL` (el nombre que usa Railway
por convención) a `B2B_DB_URL` (el nombre que lee el código).
`.env.railway.example:18` y `.env.production.example:41` afirman
literalmente "la app lo lee como B2B_DB_URL internamente" / "the app reads
this internally as B2B_DB_URL" — verifiqué que eso es falso: ningún archivo
del repo hace esa traducción (`grep -rn DATABASE_URL` fuera de los scripts
de deploy no aparece en ningún `.py`).

### [CRÍTICO] Aun corrigiendo lo anterior, la API muere al arrancar contra Postgres real por migraciones con dos heads
`migrations/versions/0005_bank_reconciliation_state.py:19-20`, `migrations/versions/0005_outstanding_unique.py:14-15`, `b2b_ai/db/db.py:181-193`, `b2b_ai/api/app.py:428-429,1358`

Escenario: asumiendo que el hallazgo anterior se corrige y `B2B_DB_URL`
apunta de verdad a Postgres. `app = create_app()` (`app.py:1358`) instancia
`Database()` al importar el módulo (`app.py:429`), y `Database.__init__`
llama a `self.migrate()` en el constructor (`db.py:93-94`), que para
Postgres ejecuta literalmente `alembic upgrade head` vía subprocess con
`check=True` (`db.py:190-193`). Lo reproduje contra un Postgres 16 real y
vacío en Docker (idéntico a un add-on de Railway recién creado, sin ninguna
tabla previa):

```
$ B2B_DB_URL="postgresql://postgres:pw@127.0.0.1:55432/b2b_ai" \
  .venv/bin/alembic -c alembic.ini upgrade head
ERROR [alembic.util.messaging] Multiple head revisions are present for
  given argument 'head'; please specify a specific target revision,
  '<branchname>@head' to narrow to a specific head, or 'heads' for all heads
FAILED: Multiple head revisions are present for given argument 'head'
```

Confirmado también con `alembic heads` (sin tocar ninguna DB): dos heads,
`0005_bank_reconciliation_state (head)` y `0007_collections_module (head)`,
porque `0005_bank_reconciliation_state.py:20` y
`0005_outstanding_unique.py:15` declaran el mismo
`down_revision = "0004_audit_feature_flags"`, y solo `0006_outreach.py:11`
encadena desde uno de los dos (`0005_outstanding_unique`), dejando al otro
como una rama huérfana. El subprocess de `_pg_migrate` sale con código de
error, se relanza como `RuntimeError` (`db.py:194-196`) y sube sin capturar
por `Database.__init__` → `create_app()` → la asignación de módulo
`app = create_app()`: el *import* del módulo falla, uvicorn nunca levanta.

Consecuencia: crash-loop total de la API para todos los tenants. `railway
logs` muestra un traceback de Alembic sin ninguna pista de negocio;
`restartPolicyMaxRetries = 5` (`railway.toml:26`) se agota y Railway se
rinde. Nada en el mensaje de error apunta a los dos archivos `0005_*`.

Causa raíz probable: dos migraciones creadas el mismo día (31-jul y 1-ago)
numeradas ambas `0005` y ambas encadenadas a `0004`, sin que nadie corriera
`alembic heads` antes de comitear. Nota importante: esto significa que la
migración que sí corrige el bug 3 de `PG_BUG_REPORT.md` —
`0005_outstanding_unique.py`, que agrega el `UNIQUE(tenant_id, factura_id)`
correcto— nunca llega a aplicarse por la vía automática que usa la app,
aunque el archivo en sí esté bien escrito.

### [CRÍTICO] `/health` y `/health/detailed` mienten sobre el backend de base de datos
`b2b_ai/api/app.py:577`, `b2b_ai/monitoring/health.py:23-38` (literal en línea 31)

Escenario: asumiendo que los dos hallazgos anteriores se corrigen y la API
sí corre sobre Postgres en producción. `GET /health` — el endpoint que
`railway.toml:20-22` sondea cada 15 segundos para decidir si el deploy está
sano — responde siempre `"backend": "sqlite"` (`app.py:577`), un literal
fijo que nunca consulta `db._is_pg`. `GET /health/detailed` hace lo mismo en
`_db_status()` (`monitoring/health.py:23-38`): arma el dict con
`"backend": "sqlite"` (línea 31) sin importar qué backend respondió
realmente al `db.conn.execute("SELECT 1")` de la línea 27 — en Postgres esa
consulta pasa igual de "ok" y el `status` general queda en `"ok"`, pero el
campo `backend` sigue clavado en `"sqlite"`. Un ingeniero que entra a
diagnosticar un incidente y consulta `/health/detailed` para confirmar "¿de
verdad estamos en Postgres?" recibe una respuesta que dice que no, sin
importar la realidad.

Consecuencia: el único endpoint diseñado para contestar "¿en qué backend
estoy corriendo" miente siempre; ni Railway ni un humano pueden usarlo para
distinguir el escenario del CRÍTICO 1 (SQLite efímero perdiendo datos) del
escenario correcto (Postgres real) — exactamente la pregunta que este rubro
pide poder contestar a las 3am.

Causa raíz probable: el string se dejó hardcodeado cuando el endpoint se
escribió (antes de que existiera el backend Postgres) y nadie lo actualizó
al agregar `_is_pg` a `Database`.

### [ALTO] Un fallo al escribir una factura no deja ningún rastro: sin audit_log, sin log JSON, sin ID de correlación
`b2b_ai/services/pipeline.py:37-47`, `b2b_ai/services/pipeline.py:100`, `b2b_ai/api/app.py` (sin `@app.exception_handler` global)

Escenario: dentro de `process_file()`, cada paso del pipeline (parse_cfdi,
validate_cfdi, classify_expense, detect_anomalies, evaluate_approval,
register_erp) pasa por el helper `_tool()` (`pipeline.py:37-47`), que
**siempre** escribe una fila en `audit_log` con `tenant_id`, `status` y el
error si lo hay — incluso en éxito. Pero el único paso que persiste dinero
de verdad, `db.insert_invoice(tenant_id, datos, clasif, validacion,
erp=erp_res)` (`pipeline.py:100`), se llama directo, sin pasar por
`_tool()`. Si ese INSERT lanza — por ejemplo, exactamente el escenario del
CRÍTICO 2, o cualquier error transitorio de red contra Postgres — la
excepción sube sin que nada la registre: no hay fila nueva en `audit_log`,
no hay línea en el log JSON estructurado (nadie llama a `log.error(...)` en
ese punto), y no existe ningún `@app.exception_handler` en `app.py` que la
intercepte antes de que Starlette la convierta en un 500 genérico. Confirmé
además que ningún response lleva un header de correlación: `grep -n
"X-Request-Id\|x-request-id"` sobre `app.py` y `monitoring/*.py` no
devuelve nada — el `request_id` que sí se genera por request
(`monitoring/logger.py:93-118`) nunca sale de vuelta al cliente. Un cliente
que manda `CFDI-00842.xml` y recibe un 500 no tiene absolutamente nada que
darle a soporte.

Consecuencia: cuando una factura falla al escribirse — el momento exacto
que le importa a un contralor — no queda ningún rastro de cuál factura fue,
para qué tenant, ni con qué error, ni en la base ni en logs ni en la
respuesta al cliente.

Causa raíz probable: `db.insert_invoice` se agregó al pipeline fuera del
patrón `_tool()` que ya existe y ya audita todo lo demás en la misma
función.

### [ALTO] Los tres documentos de deploy se contradicen sobre si Postgres funciona, y dos citan un `railway.json` que no existe
`DEPLOY.md:27,139,166`, `README-DEPLOY.md:139,201`, `docker-compose.prod.yml:11-17`, `railway.toml:11-13`

Escenario: `DEPLOY.md` (actualizado 31-jul) y `README-DEPLOY.md`
(actualizado 1-ago, el mismo día que `DEPLOY-GUIDE.md`) le dicen al
operador "El repo ya trae `railway.json`, `Procfile` y `runtime.txt`"
(`DEPLOY.md:27`) y "Railway detecta `railway.json` y `Procfile`
automáticamente" (`README-DEPLOY.md:139`, repetido en el árbol de archivos
de la línea 201). Verifiqué con `find . -iname railway.json` en todo el
repo: cero resultados. Lo que existe es `railway.toml`, que fija `builder =
"DOCKERFILE"` (`railway.toml:11-13`) — es decir, Railway construye con el
Dockerfile y **no** lee `Procfile` ni `runtime.txt` en absoluto (esos solo
aplican al builder Nixpacks, que aquí no se usa). Al mismo tiempo, la
propia `DEPLOY.md:166` es honesta: "hoy la app usa SQLite nativamente. El
adaptador Postgres requiere migración del código" — y
`docker-compose.prod.yml:11-17` repite la misma advertencia para la ruta
VPS ("Mientras no exista el adaptador Postgres, el API persiste en
SQLite"). Pero `DEPLOY-GUIDE.md`, escrito el mismo 1-ago, más largo y más
autoritativo que los otros dos, no trae ninguna de esas dos advertencias:
presenta el flujo Railway+Postgres como si funcionara de punta a punta, con
checklist final incluido.

Consecuencia: un operador que abre los tres archivos ve instrucciones
contradictorias sobre el punto más importante (¿Postgres funciona o no?)
sin ninguna señal de cuál es la vigente. Quien siga la guía más nueva y más
detallada — la elección razonable — cae de lleno en los tres CRÍTICOS de
arriba sin ninguna advertencia, porque las dos únicas advertencias honestas
del repo sobre este tema viven en los documentos que esa misma guía trata
como "resúmenes ejecutivos" ya superados (ver tabla de "Archivos de
referencia" al final de `DEPLOY-GUIDE.md`).

Causa raíz probable: `DEPLOY-GUIDE.md` se escribió después sin revisar si
las afirmaciones de `DEPLOY.md`/`README-DEPLOY.md` sobre el estado del
adaptador Postgres seguían vigentes, y sin correr `find . -iname
railway.json` para confirmar que el archivo que documentan existe.

### [MEDIO] Sentry es enteramente un mock — no hay error tracking externo real
`b2b_ai/integrations/monitoreo/sentry_adapter.py:1-100`, `pyproject.toml:12-22`

Escenario: todo el "error tracking" con nombre Sentry es, por diseño y por
su propio docstring, un mock: "sentry_adapter.py — Adaptador mock para
Sentry error tracking... En producción, se conectaría a la Sentry SDK/REST
API" (`sentry_adapter.py:3-6`). `connect()` solo hace `logger.info(...
(mock)...)`; `capture_exception()` genera un `error_id` local tipo
`sentry_{uuid}` sin llamar a ningún servicio externo
(`sentry_adapter.py:63-73`). Confirmé que `pyproject.toml` (líneas 12-22,
lista completa de dependencias) no declara `sentry-sdk`, y ningún
`.env*.example` define `SENTRY_DSN`. Si una excepción no capturada revienta
en producción — como la del CRÍTICO 2 —, no hay ningún sistema externo que
la agrupe, la deduplique o la empuje a un humano fuera del propio proceso.

Consecuencia: el equipo depende 100% de leer `railway logs` a mano o de que
el `AlertManager` interno dispare por tasa de error/latencia (ver "lo que
revisé y está bien" — ese motor sí es real) — sin agrupación de
excepciones, sin stack trace navegable, sin push nativo a un humano dormido
a las 3am salvo que además se configure `B2B_ALERT_WEBHOOK_URL` a mano.

Causa raíz probable: el adaptador se dejó como mock de la capa de
integraciones (probablemente para no depender de una cuenta real de Sentry
en el MVP) y nunca se promovió a integración real ni se documentó como
pendiente en los README de deploy.

### [BAJO] 12 markdown de estado en la raíz sin índice de cuál es vigente
`DEPLOY.md`, `DEPLOY-GUIDE.md`, `README-DEPLOY.md`, `QA_REPORT.md`, `QA_REPORT_BASELINE.md`, `QA_REPORT_CURRENT.md`, `QA_REPORT_FINAL.md`, `QA_REPORT_LANDING_FIX.md`, `PG_BUG_REPORT.md`, `FIX_REPORT.md`, `MODULE_REPORT.md` (raíz del repo)

Escenario: 12 archivos markdown en la raíz documentan estado o deploy,
cinco de ellos variantes de "QA_REPORT" y tres de deploy, sin ningún
`INDEX.md` ni cabecera que diga cuál es la fuente de verdad vigente ni cuál
quedó obsoleto tras el rebrand "B&B AI → Likida AI" que `MAPA.md` (punto 3)
señala en curso.

Consecuencia: cualquier persona nueva —o el propio equipo, meses después—
tiene que abrir varios archivos y comparar fechas de "Última actualización"
a mano para saber cuál seguir. Es exactamente el trabajo que el hallazgo
ALTO de arriba muestra que sale mal cuando se hace deprisa.

Causa raíz probable: cada corrida del pipeline de agente generó su propio
reporte de estado sin depreciar ni fusionar el anterior.

## Lo que revisé y está bien

- **Dockerfile** (`Dockerfile:1-96`): build multi-stage real
  (builder→runtime), base fijada (`python:3.11-slim-bookworm`), usuario no
  root (`Dockerfile:80-82`), `HEALTHCHECK` vía `curl` (líneas 87-88), capas
  cacheables (dependencias antes que código). De los mejores que he visto en
  un MVP de este tamaño.
- **`b2b_ai/monitoring/logger.py`**: logging JSON estructurado real, con
  máscara de PII por regex (RFC, CURP, email, teléfono, tarjeta —
  `logger.py:39-49`) y contexto de request por `contextvar`
  (`request_context`, líneas 101-118) que se puede envolver por hilo/tarea
  sin contaminar peticiones concurrentes. Buena base — el problema no es
  esta pieza, es que no se invoca en el punto que importa (ver ALTO 1).
- **`b2b_ai/monitoring/metrics.py`** y **`alerts.py`**: registro de
  métricas Prometheus real (contadores, gauges, summaries con p95/p99) y un
  motor de alertas con reglas configurables, semántica de
  disparo-en-transición con cooldown, e historial acotado
  (`alerts.py:213-297`). No es aspiracional: está implementado y es
  razonable para un MVP sin presupuesto de APM.
- **`scripts/deploy-production.sh`**: verificado que los flags que
  `DEPLOY-GUIDE.md` cita (`--dry-run`, `--health`, `--rollback`,
  `--rollback=<N>`, `--logs`, `--status`, `--prereqs`, `--env-only`) existen
  de verdad en el script (551 líneas, dispatcher real), no son solo
  mencionados en la guía.
- **`PG_BUG_REPORT.md` bugs 1 y 2 — ya corregidos en el código actual,
  contrario a como los describe el propio reporte y a la lectura literal de
  `MAPA.md` punto 1.** Verifiqué línea por línea: `qmark_to_percent`
  (`b2b_ai/db/pg.py:63-74`) **sí** traduce `:nombre` → `%(nombre)s`
  (el reporte decía que solo traducía `?`→`%s`); `_is_integrity_error`
  (`b2b_ai/db/db.py:52-60`) **sí** atrapa `psycopg.errors.UniqueViolation`
  además de `sqlite3.IntegrityError`; y `log_call`
  (`b2b_ai/db/db.py:381`) **sí** escribe `'{}'` en vez de `''` cuando el
  payload es `None`. Los tres coinciden exactamente con los fixes que el
  propio `PG_BUG_REPORT.md` proponía. La migración que corrige el bug 3
  (`0005_outstanding_unique.py`) también existe y está bien escrita — su
  problema no es el contenido, es que nunca llega a aplicarse (ver CRÍTICO
  2). No pude correr `tests/test_db_pg_integration.py` completo contra el
  PG real para confirmar esto end-to-end con el pipeline de la app (ver
  abajo), pero la lectura estática de los tres puntos exactos que el
  reporte señala como rotos muestra que ya no lo están.
- **`start.sh --local`**: sí deja el proyecto corriendo en una máquina
  limpia. Crea `.venv`, corre `pip install -e .`, y todas las dependencias
  que necesita el arranque en modo SQLite están declaradas en
  `pyproject.toml:12-22` (incluye `psycopg[binary]` y `psycopg-pool` como
  dependencias base, así que ni siquiera falla si alguien fuerza el modo
  Postgres localmente). Las migraciones de SQLite corren automáticamente y
  son idempotentes vía `Database.migrate()` (`db.py:93-95, 130-131`).

## Lo que NO alcancé a revisar

- No corrí la suite completa `tests/test_db_pg_integration.py` contra el PG
  real ya corriendo en este entorno (contenedor `b2b_prod_pg`, puerto
  54329) ejercitando el pipeline completo de la app (`process_file` →
  `insert_invoice`) — solo verifiqué estáticamente `pg.py`/`db.py` para los
  bugs 1 y 2, y reproduje el bug de migraciones (CRÍTICO 2) en un contenedor
  Postgres nuevo y desechable que levanté y eliminé para esta auditoría, sin
  tocar el contenedor compartido `b2b_prod_pg` para no interferir con otro
  trabajo que pudiera estar corriendo sobre él en paralelo.
- No revisé `nginx/nginx.conf` ni el flujo de TLS de la opción VPS más allá
  de leer las referencias en `docker-compose.prod.yml` y `README-DEPLOY.md`.
- No revisé `.github/workflows/ci.yml` en profundidad — no está en la lista
  explícita de archivos de este rubro en `MAPA.md`.
- No probé `deploy-railway.sh` ni `deploy.sh` (raíz) línea por línea, solo
  `scripts/deploy-production.sh`, que es el que `DEPLOY-GUIDE.md` usa como
  script principal.
- No tuve una cuenta real de Railway para probar el deploy de punta a
  punta; toda la verificación de "qué pasaría en Railway" es por lectura de
  código más reproducción equivalente contra un Postgres real local — no
  descarto que Railway tenga algún comportamiento adicional (p. ej. variable
  de entorno propia) que no esté documentado en ningún archivo del repo.
