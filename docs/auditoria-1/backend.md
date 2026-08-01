# Backend y API — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa).

El riesgo mayor hoy: una API key de un despacho puede escribir facturas fabricadas en el libro de OTRO despacho llamando a `/api/v1/webhooks/email` con `tenant_id` en el body — lo verifiqué con una petición HTTP real, no por lectura. A eso se suma un endpoint publicado que revienta el 100% de las veces (`AttributeError`) y que la capa Postgres —el backend que `DEPLOY-GUIDE.md` indica usar en producción— hoy ni siquiera logra migrar: `alembic upgrade head` falla con "Multiple head revisions" contra el Postgres real que corre en esta máquina.

## Hallazgos

### [CRÍTICO] IDOR: una API key de un tenant escribe facturas en el libro de otro tenant
`b2b_ai/api/webhooks.py:252-257`
```python
scope = auth_info.get("tenant_id")
if email.tenant_id is not None:
    scope = email.tenant_id
if scope is None:
    raise HTTPException(status_code=422, detail="No se pudo resolver el tenant.")
```
`EmailInbound.tenant_id` (línea 54) es un campo del body que el cliente controla libremente. El código lo usa para **sobreescribir** el `scope` resuelto desde la API key, sin comparar que coincida con el tenant de la key.

Escenario, probado en vivo (`fastapi.testclient.TestClient`, no simulado): tenant 1 ("Despacho A") tiene su propia API key, válida y activa. Tenant 2 ("Despacho B") existe pero Despacho A nunca tuvo acceso a él. Con la key de Despacho A:
```
POST /api/v1/webhooks/email
X-API-Key: KEY-TENANT-1
{"attachments": [...], "tenant_id": 2}
```
→ `200 OK`, `db.count_invoices(2)` pasa de 0 a 1. La factura queda insertada bajo `tenant_id=2` (RFC, montos, categoría — datos fiscales del despacho ajeno), atribuible a un adjunto que Despacho A controló por completo.

Esto contradice el propio patrón del resto del código: `app.py:689-693` (`list_invoices`) y `app.py:1243` (`process_legacy`) usan explícitamente `_scope(auth_info) or tenant_id` — solo la key de servicio (`tenant_id=None`) puede fijar el tenant; una key de tenant real nunca gana el `or`. `v2.py:26` lo declara como invariante del módulo ("nunca acepta `tenant_id` del cliente para leer datos de otro tenant"). `webhooks.py` es el único lugar del rubro que rompe ese invariante, y lo rompe para **escribir**, no solo leer.

Consecuencia: cualquier despacho con una key válida puede inyectar CFDI fabricados en la contabilidad de otro despacho — dato fiscal falso bajo el nombre de un tercero, sin que ningún log lo distinga de un email legítimo (el `log_call` interno registra `tenant_id=2`, como si Despacho B lo hubiera subido). Ningún test lo cubre: `tests/test_webhooks.py:150-162` manda `"tenant_id": 1` — el mismo tenant de la key — así que el camino cruzado nunca se ejecuta en CI.

Causa raíz probable: el override de `scope` se copió del caso de la key de servicio sin la guarda `if scope is None:` que sí tienen los demás endpoints del repo.

### [CRÍTICO] `POST /api/v1/outreach/leads` revienta el 100% de las veces
`b2b_ai/api/outreach.py:49`
```python
lead_id = db.create_outreach_lead(name=lead.name, email=lead.email, ...)
```
`Database` no tiene el método `create_outreach_lead` — existe `add_outreach_lead(self, campaign_id, tenant_id, email, first_name=..., ...)`, con firma distinta (pide `campaign_id`/`tenant_id` que `LeadCreate` ni siquiera declara). Probado en vivo: `POST /api/v1/outreach/leads` con una key válida y body válido según el schema devuelve **500 Internal Server Error** siempre — `AttributeError: 'Database' object has no attribute 'create_outreach_lead'`.

Escenario: un integrador (o Likida mismo) llama al endpoint documentado en el router para dar de alta un lead de outreach → 500 sin excepción, en cada intento, sin excepción de casos borde: el método simplemente no existe.

Consecuencia: la única vía documentada para crear un lead vía API está muerta desde que se escribió. `tests/test_outreach.py` nunca la ejercita — prueba `OutreachManager`/`Database` directo, sin `TestClient`, así que 74 tests de esta zona pasan en verde sin haber llamado nunca a esta ruta.

Causa raíz probable: desalineación entre el nombre de método que `outreach.py` esperaba (`create_outreach_lead`, plausible del vocabulario REST estándar) y el que `db.py` implementó (`add_outreach_lead`), nunca detectada porque no hay prueba de integración del router.

### [ALTO] El router de outreach ignora la `db` inyectada por `create_app()`: lee y escribe en otra base
`b2b_ai/api/outreach.py:34-38` (`build_outreach_router(require_api_key)`, sin parámetro `db`) y cada handler, p.ej. líneas 46-48, 67-69, 79-83, 103-107, 116-120, 129-133, 149-153, 163-167:
```python
from b2b_ai.db.db import Database
db = Database()
```
Todos los demás routers del rubro (`webhooks.register_webhook_routes(app, db, ...)`, `api_v2.build_v2_router(db, ...)`, `portal_mod.build_portal_router(db)`, `build_reconciliation_router(db, ...)`) reciben la `db` de `create_app()`. Outreach es el único que se registra en `app.py:1203` como `build_outreach_router(require_api_key)` — sin `db` — y cada handler crea una `Database()` nueva, que resuelve `DEFAULT_DB` del entorno (`db.py:18-21`) en vez de usar la instancia de la app.

Probado en vivo: inserté un lead directamente en la `db` que se le pasó a `create_app(db)` (`db.add_outreach_lead(...)` → confirmado con `db.list_outreach_leads()`), y luego llamé `GET /api/v1/outreach/leads` con la key de ese mismo tenant sobre esa misma app. La API devolvió `{"leads": [], "total": 0}` — el router habla con una base de datos distinta a la que la aplicación declaró usar.

Consecuencia: en tests que inyectan una `Database(tmp_path)` aislada (el patrón que usa el resto de la suite), los endpoints de outreach caen sobre el archivo por defecto del proceso (`b2b_ai.db` en la raíz del repo, o lo que diga `B2B_DB_URL`/`B2B_DB_PATH` en ese momento) — datos de prueba que se filtran al archivo real de desarrollo, o al revés, silencio total si el archivo por defecto está vacío. En producción con Postgres, cada llamada además dispara `Database.__init__` → `self.migrate()` (línea 93 de `db.py`) contra el pool compartido, trabajo repetido innecesario por request.

Causa raíz probable: `outreach.py` se integró sin seguir el patrón `build_*_router(db, require_api_key)` que usa el resto del módulo.

### [CRÍTICO] La API no arranca contra PostgreSQL hoy: `alembic upgrade head` falla con dos heads
`migrations/versions/0005_bank_reconciliation_state.py:20` y `migrations/versions/0005_outstanding_unique.py:15` — ambos declaran `down_revision = "0004_audit_feature_flags"`, así que Alembic tiene dos ramas terminales (`0005_bank_reconciliation_state` y, vía `0006_outreach → 0007_collections_module`, `0005_outstanding_unique`) sin que ninguna decida cuál es "head". `b2b_ai/db/db.py:189-195` (`_pg_migrate`) llama `alembic upgrade head` y convierte el fallo en `RuntimeError`; `Database.__init__` (línea 93) llama `self.migrate()` siempre que `migrate=True` (el default); `app.py:429` hace `db = db or Database()` dentro de `create_app()`.

Verificado contra Postgres real, no simulado — hay un contenedor `b2b_prod_pg` corriendo en este mismo equipo (`127.0.0.1:54329`, el mismo DSN que usa `PG_BUG_REPORT.md`):
```
$ .venv/bin/python -m alembic heads
0005_bank_reconciliation_state (head)
0007_collections_module (head)

$ B2B_DB_URL=postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py -v
ERROR ... RuntimeError: Fallo la migración Alembic a PostgreSQL: ...
  ERROR [alembic.util.messaging] Multiple head revisions are present for
  given argument 'head'; ...
6 errors in 2.79s
```
Escenario: cualquier despliegue con `B2B_DB_URL` apuntando a Postgres (el caso documentado en `DEPLOY-GUIDE.md`) hace que `create_app()` — es decir, el arranque mismo del proceso `uvicorn` — lance `RuntimeError` antes de servir una sola petición.

Consecuencia: esto es estrictamente peor que lo que documentaba `PG_BUG_REPORT.md` el 31-jul (que sí lograba migrar y fallaba método por método). `MAPA.md` ya señalaba la duplicidad de `0005_*` como sospechosa para el rubro de datos; aquí queda confirmado su efecto real sobre el rubro de API: el servicio no arranca.

**Qué cambió desde el 31-jul, para responder lo que pide esta ronda:** el código de los 3 bugs puntuales del reporte muestra intentos de arreglo — `qmark_to_percent` en `b2b_ai/db/pg.py:63-74` ahora traduce `:nombre` → `%(nombre)s` (la Opción B del reporte, para el bug de `insert_invoice`); `_is_integrity_error` en `db.py:52-60` ya distingue `psycopg.errors.UniqueViolation`; `log_call` (`db.py:381`) ya escribe `'{}'` en vez de `''` cuando el payload es vacío (bug 2, cerrado en la práctica aunque con un valor distinto al que sugería el reporte); y existe una migración nueva, `0005_outstanding_unique.py`, que agrega el constraint que le faltaba a `outstanding_invoices` (bug 3). Pero **ninguno de los tres se puede verificar de punta a punta** porque esa misma migración quedó en una rama alterna que nunca converge a un solo head — el hallazgo 5 del reporte original (`with self.conn:` sin commit en `PGConnection.__exit__`, `pg.py:156-158`) tampoco se pudo probar por la misma razón: la migración nunca llega a aplicarse.

### [CRÍTICO] `DEPLOY-GUIDE.md` documenta una variable que el código nunca lee: en Railway la app corre en SQLite efímero, no en Postgres
`b2b_ai/db/db.py:18-21`:
```python
DEFAULT_DB = (os.environ.get("B2B_DB_URL")
              or os.environ.get("B2B_DB_PATH")
              or os.path.join(..., "b2b_ai.db"))
```
`DATABASE_URL` no aparece en ningún `.py` del repo (`grep -rln "DATABASE_URL" --include="*.py" .` → cero resultados fuera de `.env.production.example`, que es un comentario). Pero `DEPLOY-GUIDE.md:81,219,281` y `.env.production.example:40-42` son explícitos: Railway inyecta `DATABASE_URL` automáticamente al agregar el add-on de PostgreSQL, y la guía instruye **no** configurar nada manualmente ("Railway crea automáticamente las variables `DATABASE_URL`... No las configures manualmente" / "NO configurar DATABASE_URL manualmente").

Escenario: se sigue `DEPLOY-GUIDE.md` al pie de la letra en Railway. Railway inyecta `DATABASE_URL`. El proceso arranca, `DEFAULT_DB` evalúa `os.environ.get("B2B_DB_URL")` → no existe → cae a `B2B_DB_PATH` → tampoco existe → cae al archivo SQLite local del contenedor. La app **arranca sin error** (a diferencia del hallazgo anterior) y sirve tráfico con normalidad — sobre un archivo SQLite dentro del filesystem efímero del contenedor.

Consecuencia: cada redeploy, restart o escalado en Railway borra el archivo SQLite (filesystem efímero) y el despacho pierde su historial de facturas sin ningún error visible — el add-on de Postgres que se está pagando nunca recibe una sola escritura. Es el peor tipo de bug para este rubro porque no hay excepción, ni log de error, ni test que lo detecte: el "camino feliz" es exactamente el que pierde los datos.

Causa raíz probable: el código se escribió contra `B2B_DB_URL` (nombre propio del proyecto) y nunca se agregó el alias/mapeo hacia `DATABASE_URL` (el nombre que efectivamente usan Railway/Heroku-style add-ons), pese a que la documentación de despliegue asume que sí existe.

### [ALTO] Los jobs async en memoria de `/api/v2/batch` y del portal no sobreviven ni son visibles entre workers
`b2b_ai/api/v2.py:94-118` (`_JOBS: dict = {}`, módulo-global, sin persistencia) y `b2b_ai/api/portal.py:84-118` (`_JobStore`, mismo patrón). `Dockerfile:90-93` documenta la topología recomendada: "el backend Postgres... puede escalar a N [workers]" vía `B2B_WORKERS=$(nproc)`.

Escenario: con `B2B_WORKERS>1` (la topología que el propio Dockerfile recomienda para Postgres), un `POST /api/v2/batch` con `"async": true` crea el job en el diccionario del worker que atendió esa petición y lanza un hilo en ese mismo proceso. Un `GET /api/v2/batch/{job_id}` posterior que el balanceador enruta a otro worker no encuentra el job en su propio `_JOBS` → `404 Lote no encontrado`, aunque el lote siga procesándose (o ya haya terminado) en el primer worker. Mismo patrón en `portal.py:298-316` (`portal_invoice_status`): si el job no está en el `_JobStore` de ese worker, intenta parsear `job_or_id` como `invoice_id` entero y, al fallar (es un UUID hex), devuelve 404 aunque la factura del cliente del portal se esté procesando con normalidad.

Consecuencia: el cliente del portal o el integrador de `/api/v2/batch` ve "no encontrado" para un trabajo que sí se completó, y no tiene forma de saber si reintentar (posible reprocesamiento/duplicado) o esperar. Es exactamente la clase de bug que `reconciliation.py:32-49` ya documenta haber corregido para las sesiones de conciliación bancaria ("se rompía con más de un worker... la función entera era inservible en cualquier despliegue con réplicas") — el mismo defecto sigue vivo, sin corregir, en `v2.py` y `portal.py`.

Causa raíz probable: el patrón de estado en memoria por proceso se replicó para jobs async sin aplicar la misma corrección que ya se hizo para `BankReconciliation`.

## Lo que revisé y está bien

- **Tenant scoping consistente en casi todo el rubro.** `app.py:689-693` (`list_invoices`), `app.py:702-707` (`get_invoice`), `app.py:1243` (`process_legacy`), y **todas** las rutas de `v2.py` (`_tenant()`, línea 190-200, usada en cada handler) resuelven el tenant exclusivamente desde `auth_info["tenant_id"]`, con el patrón seguro `_scope(auth_info) or param` que solo cede ante la key de servicio. Confirmado leyendo cada ruta de `v2.py` una por una, no solo el docstring.
- **`_resolve_local_path` (`app.py:388-416`) cierra path traversal correctamente**: resuelve symlinks/`..` y verifica pertenencia a una lista fija de directorios permitidos (`_allowed_xml_roots`, línea 373-387), con mensaje que no hace eco de la ruta pedida ni de la lista permitida.
- **`RateLimiter` (`app.py:272-320`) y `_StatsCache` (`app.py:134-165`) son thread-safe** (lock explícito) y el cache de stats usa `data_version` como parte de la key — una escritura de facturas invalida el cache al instante sin necesidad de purga activa. Revisé la lógica de invalidación y es correcta.
- **`retry_deliver` (`webhooks.py:95-121`) implementa backoff exponencial real** y separa `post` como dependencia inyectable — el diseño para test es correcto, aunque (ver arriba) el endpoint que más lo necesita tiene el bug de tenant primero.
- **`reconciliation.py` ya no tiene estado en memoria** (comentario explícito en líneas 30-49 documentando el bug anterior y su fix): cada request reconstruye el servicio desde la base (`_session`, línea 50-54). Correcto, y es la referencia de cómo debieron resolverse los casos de `v2.py`/`portal.py` arriba.
- **`process_invoice` / `process_legacy` capturan `CFDIError` y devuelven 422** en vez de dejar escapar un 500 por XML inválido (`app.py:648-650`, `667-671`, `1255-1257`) — el comentario en el código indica que esto también fue un fix deliberado sobre un bug anterior (500 por XML truncado).

## Lo que NO alcancé a revisar

- Los 574 archivos/endpoints de `dashboard.py` (frontend, rubro ajeno) no se tocaron.
- No verifiqué contra Postgres los métodos `insert_invoice`/`log_call`/`upsert_outstanding_invoice` de punta a punta (el hallazgo CRÍTICO de arriba explica por qué: la migración nunca llega a aplicarse). Si se corrige la migración duplicada, esos tres caminos deberían re-probarse contra PG real antes de dar por buena la capa.
- No audité `contpaqi_driver.py`/`aspel_driver.py` (computer use) ni `billing/stripe_provider.py`/`conekta_provider.py` — quedan fuera de los archivos asignados a este rubro (seguridad/fiscal los cubren).
- No revisé si el patrón IDOR de `webhooks.py` se repite en otros endpoints que acepten `tenant_id` en el body fuera de los 8 archivos de este rubro (p. ej. otros routers montados en `app.py` líneas 1100-1200 que no están en mi lista, como `build_reportes_router`, `build_vencimientos_router`, etc.) — vale la pena que el rubro de seguridad o una ronda 2 lo verifique explícitamente en esos archivos también.
- No medí el rendimiento del re-`migrate()` por request en `outreach.py` bajo carga real; solo confirmé que ocurre por lectura de código.
