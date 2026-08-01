# Modelo de datos y esquema — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa).

Riesgo mayor hoy: el repo no tiene UN esquema de Postgres coherente, tiene DOS —
uno que Alembic no puede resolver a un solo `head` (por la duplicidad `0005`) y
otro donde faltan tablas enteras (`billing_*`) que el código de `db.py` usa sin
verificar que existan. Cualquier despliegue real contra PostgreSQL (Railway,
como indica `DEPLOY-GUIDE.md`) se cae en el arranque o en el primer webhook de
cobro, no en un caso raro de borde.

## Hallazgos

### [CRÍTICO] `alembic upgrade head` no resuelve: dos heads desde 0004, y `Database._pg_migrate()` lo corre en cada arranque contra Postgres
`migrations/versions/0005_bank_reconciliation_state.py:19-22` y
`migrations/versions/0005_outstanding_unique.py:14-17`

Escenario: entra `alembic upgrade head` (invocado por
`b2b_ai/db/db.py:190-193`, dentro de `_pg_migrate()`, que se dispara desde
`Database.__init__` (línea 94, `migrate=True` por defecto) cada vez que se
crea una `Database()` con `B2B_DB_URL` apuntando a PostgreSQL — y
`b2b_ai/api/app.py:429` hace exactamente eso: `db = db or Database()` al
construir la app) → sale un `alembic.util.exc.CommandError: Multiple head
revisions are present for given argument 'head'; please specify a specific
target revision...`.

Lo verifiqué de dos formas independientes, sin tocar ninguna base real:
1. `.venv/bin/alembic heads` sobre el repo tal cual está hoy imprime:
   ```
   0005_bank_reconciliation_state (head)
   0007_collections_module (head)
   ```
   Ambos `0005_*` tienen `down_revision = "0004_audit_feature_flags"`
   (branchpoint confirmado con `alembic branches`); nada en el árbol
   referencia `0005_bank_reconciliation_state` como `down_revision`, así que
   ese archivo queda como una rama muerta que nunca se fusiona de vuelta a
   `0006_outreach → 0007_collections_module`.
2. Reproduje el error sin conexión a ninguna base (`command.upgrade(cfg,
   'head', sql=True)`, modo *offline*, solo genera SQL): el `CommandError`
   ocurre en la resolución del string `'head'`, **antes** de intentar
   conectar. Es determinista, no depende del estado de la base de destino.

`_pg_migrate()` (`db.py:189-196`) envuelve el subproceso en
`subprocess.run(..., check=True)`; el exit code no-cero del CLI de Alembic
(que hace `sys.exit(1)` sobre `CommandError`) se traduce en
`subprocess.CalledProcessError`, capturado y relanzado como
`RuntimeError(f"Fallo la migración Alembic a PostgreSQL: ...")`.

Consecuencia: cualquier despliegue nuevo contra PostgreSQL — el camino que
`DEPLOY-GUIDE.md` describe para producción vía Railway — revienta al primer
`Database()` que se instancie con un DSN de Postgres, incluida la app FastAPI
completa (`app.py:429`). No es un caso raro: pasa siempre, con cualquier base,
porque el fallo ocurre antes de tocar la base. `tests/test_pg_migrations.py`
está `skipif`-eado sin `B2B_DB_URL` (los "16 skipped" del baseline de
MAPA.md casi seguro lo incluyen), así que la suite verde de 4900 pruebas
nunca ejercita este camino.

Causa raíz probable: se creó `0005_outstanding_unique.py` (31-jul) para
resolver el bug 3 de `PG_BUG_REPORT.md`, y por separado `0005_bank_reconciliation_state.py`
(1-ago, mismo día que el resto de FASE de conciliación bancaria) sin que
quien lo generó re-encadenara `down_revision` sobre la punta real de la
cadena.

---

### [CRÍTICO] Las tablas `billing_*` no existen en ningún archivo de Alembic — solo en el esquema SQLite
`b2b_ai/db/models.py:417-478` (versión 10, `"billing"`) define
`billing_customers`, `billing_subscriptions`, `billing_invoices`,
`billing_payment_methods`; `b2b_ai/db/db.py:415-518` (`create_billing_customer`,
`create_billing_subscription`, `create_billing_invoice`,
`mark_billing_invoice_paid_by_ref`, `create_billing_payment_method`, y sus
`list_*`) y `b2b_ai/billing/api.py:94-210` las usan para el flujo real de
cobro (Stripe/Conekta).

Escenario: entra un webhook real de Stripe confirmando un pago (
`b2b_ai/billing/api.py:210`, `db.mark_billing_invoice_paid_by_ref(...)`) o
un alta de cliente (`billing/api.py:97`, `db.create_billing_customer(...)`)
contra la base de producción (Postgres) → sale
`psycopg.errors.UndefinedTable: relation "billing_customers" does not exist`
(o `billing_invoices`, según el endpoint), porque ninguna migración de
`migrations/versions/*.py` crea esas cuatro tablas. Confirmé la ausencia
comparando el conjunto completo de `op.create_table(...)` de los 8 archivos
de Alembic contra las 36 tablas de `models.py`: las únicas 4 que faltan son
exactamente las de billing.

Consecuencia: el módulo de cobros — dinero real de Stripe/Conekta, tal como
`MAPA.md` ya señala en el punto 5 de seguridad — no puede escribir NADA en
Postgres. No es un bug de borde: es la tabla completa ausente, así que
funciona en local sobre SQLite (de ahí que la suite de 4900 pruebas esté
verde) y se cae por completo en producción la primera vez que alguien paga.

Causa raíz probable: `0001_initial.py` se escribió/reescribió para
"todas las tablas del MVP" pero el módulo de billing se agregó después a
`models.py` (SQLite) sin generar su migración Alembic equivalente.

---

### [CRÍTICO] `with self.conn:` libera la conexión de Postgres al pool, pero `Database` sigue usando la misma referencia cacheada — riesgo de dos peticiones compartiendo el mismo socket
`b2b_ai/db/db.py:845-860` (`upsert_outstanding_invoice`, el caso más claro:
dos accesos a `self.conn` en el mismo método, uno dentro y otro fuera del
`with`); patrón repetido en 20 métodos más (grep de `with self.conn:` en
`db.py`: líneas 176, 595, 627, 647, 727, 805, 845, 880, 961, 1072, 1111,
1120, 1155, 1170, 1248, 1273, 1310, 1349, 1463, 1481, 1488).
`b2b_ai/db/pg.py:138-158` (`PGConnection.__enter__`/`__exit__`) y `:181-192`
(`close()`).

Escenario: entra una petición que llama `upsert_outstanding_invoice(tenant_id=1,
factura_id="F1", monto=500.0, ...)`. Dentro del método:
```python
with self.conn:
    self.conn.execute("INSERT INTO outstanding_invoices ... ON CONFLICT ...")
row = self.conn.execute("SELECT id FROM outstanding_invoices WHERE ...")  # línea 856
```
`self.conn` es una propiedad (`db.py:111`, y para Postgres `_pg_conn()` en
`db.py:134-144`) que cachea UNA `PGConnection` por hilo en
`self._local.conn` y solo la crea si es `None` — nunca la invalida después.
`PGConnection.__exit__` (pg.py:156-158) llama `self.close()`, que llama
`self._release.__exit__(None, None, None)` (pg.py:183-185): eso reanuda el
generador `ConnectionPool.connection()` de psycopg_pool
(`.venv/lib/python3.11/site-packages/psycopg_pool/pool.py:184-190`), que hace
`commit` (correcto, contrario a lo que temía `PG_BUG_REPORT.md` §5 — ver
abajo) y **devuelve la conexión física al pool** (`self.putconn(conn)`).

O sea: al salir del bloque `with self.conn:` en la línea 850, la conexión ya
quedó libre para que el pool se la entregue a CUALQUIER OTRO hilo. Pero
`self._local.conn` (línea 140) sigue apuntando al mismo objeto `PGConnection`,
y la línea 856 (`self.conn.execute(...)`, fuera del `with`) lo vuelve a usar
como si siguiera siendo exclusivo. Y esto no se limita a este método: como
`b2b_ai/api/app.py:429` crea UNA sola `Database()` para toda la vida del
proceso, la primera vez que un hilo del threadpool de uvicorn ejecuta
cualquiera de los 21 métodos con `with self.conn:`, ese hilo queda con una
conexión "fantasma" — el pool cree que está libre, este hilo la sigue usando
para siempre en cada petición futura que le toque servir.

Consecuencia: bajo carga concurrente real (`B2B_PG_POOL_MAX` por defecto es
10, así que con más de 10 peticiones simultáneas es prácticamente seguro que
ocurra), el pool puede entregar esa misma conexión física a un segundo hilo
mientras el primero todavía la usa. psycopg3 no soporta uso concurrente de
una misma `Connection` desde dos hilos: el resultado esperable es
`psycopg.errors` de protocolo desincronizado, o — peor para un SaaS
multi-tenant — que la consulta de un tenant se ejecute intercalada con la
transacción de otro tenant sobre el mismo socket. Nadie se entera porque no
hay ninguna prueba que ejercite Postgres bajo concurrencia (ver sección de
lo no revisado).

Causa raíz probable: `PGConnection` fue diseñada para imitar la API de
`sqlite3.Connection` (donde `with conn:` NO cierra ni libera nada, solo hace
commit/rollback y la conexión sigue siendo válida para el mismo hilo) sin
tener en cuenta que, en el wrapper de PG, `close()` sí devuelve el objeto al
pool — la sustitución "misma API, semántica distinta" es la fuente del bug.

---

### [ALTO] Dinero real en columnas `FLOAT`, no `NUMERIC`/`DECIMAL`, en dos tablas que sí existen en Postgres
`migrations/versions/0001_initial.py:221` (`outstanding_invoices.monto
sa.Float()`) y `migrations/versions/0007_collections_module.py:32`
(`collection_payments.amount sa.Float()`); escritura en
`b2b_ai/db/db.py:854` (`float(monto)` dentro de `upsert_outstanding_invoice`)
y `db.py:927` (`float(amount)` dentro de `add_collection_payment`).

Escenario: `services/collections.py:328-334` (`sync_outstanding`) sincroniza
la cartera de cuentas por cobrar cada vez que se recalcula la cobranza: toma
`inv.get("monto")` como `Decimal` (vía `_dec()`, `services/collections.py:121-130`,
que sí preserva precisión decimal) y en la línea 331 lo pasa a
`upsert_outstanding_invoice`, que en `db.py:854` hace `float(monto)` antes de
guardarlo en una columna `FLOAT` de Postgres. Ejemplo concreto: un monto de
`Decimal("1234567.89")` (una factura real de ese orden no es inusual para un
despacho con clientes medianos) se guarda como el `float` más cercano
representable en binario — no es exactamente `1234567.89`, y comparaciones o
sumas posteriores sobre esa columna (`SUM(monto)` para totalizar cartera
vencida, si algo lo hiciera) heredan ese error. Lo mismo aplica a
`collection_payments.amount`, que registra pagos reales entrantes por
webhook (`add_collection_payment`, `db.py:917-932`, con `provider` en
`spei|stripe|conekta|manual`).

Consecuencia: la cartera de cobranza y el log de pagos — los dos números que
alimentan directamente el reporte de "cuánto me deben" que un contralor
revisaría — no tienen la garantía de exactitud decimal que sí se les dio
deliberadamente a `invoices.subtotal/iva/total` (guardados como `TEXT`,
justo para evitar este problema). Es una inconsistencia de diseño dentro del
mismo esquema: unos montos se protegieron, estos dos no.

Causa raíz probable: `outstanding_invoices` y `collection_payments` se
diseñaron mirando el contrato de la app (que ya trabaja con `float` en
`services/collections.py` para el score de cobrabilidad) y no se distinguió
entre "campo numérico auxiliar" (score, confianza) y "campo que es dinero".

---

### [ALTO] El total que ve el dashboard se calcula con `CAST(... AS REAL)` — precisión simple en Postgres, doble en SQLite
`b2b_ai/db/db.py:338` y `:348-349` (`invoice_stats()`, que alimenta
`GET /api/v1/stats`, el endpoint de métricas del dashboard).

Escenario: `invoice_stats()` ejecuta
`SELECT categoria, COUNT(*) AS n, SUM(CAST(total AS REAL)) AS monto FROM
invoices ...` para armar `monto_total`, `iva_total` y `por_categoria[*].total`
— exactamente los números que se muestran en pantalla. `total` está
guardado como `TEXT` (`migrations/versions/0001_initial.py:56`) precisamente
para no perder precisión; pero el momento en que se agrega para el
dashboard, el código lo castea explícitamente a `REAL`. En SQLite (el
backend que corre los 4900 tests verdes), `CAST(x AS REAL)` produce siempre
un double de 8 bytes. En PostgreSQL, el tipo `REAL` es `float4`, de 4 bytes
(~6-7 dígitos decimales significativos) — un tipo distinto y más pobre que
`DOUBLE PRECISION`. Con muchas facturas por categoría (fácilmente >7 dígitos
significativos al sumar, p. ej. una categoría con \$1,234,567.89 acumulados),
el mismo query, con los mismos datos, puede redondear distinto entre el
backend que se prueba (SQLite) y el que se despliega (Postgres) — y ninguna
prueba lo detecta porque ninguna corre el mismo escenario contra los dos
backends y compara.

Consecuencia: el número que el contralor ve en el dashboard de producción no
está garantizado a coincidir con el que salió verde en la suite de pruebas
de desarrollo — una divergencia silenciosa entre "lo que se probó" y "lo que
se muestra".

Causa raíz probable: `REAL` se usó como sinónimo genérico de "número con
decimales" sin considerar que el nombre del tipo apunta a cosas distintas en
cada motor.

---

### [MEDIO] Ningún `CHECK` en las 36 tablas del esquema — un monto negativo en la cartera de cobranza no lo detiene ni la base ni la aplicación
`b2b_ai/db/models.py` (0 ocurrencias de `CHECK` en las 727 líneas) y
`migrations/versions/*.py` (0 ocurrencias de `CHECK` en los 8 archivos).
Camino concreto: `services/collections.py:121-130` (`_dec`) parsea
`inv.get("monto")` a `Decimal` sin validar signo, y `services/collections.py:328-334`
lo pasa directo a `upsert_outstanding_invoice` (`db.py:837-860`), que tampoco
valida signo antes del `INSERT`.

Escenario: entra una factura con `monto="-500.00"` (p. ej. un error de signo
al mapear una nota de crédito como si fuera una cuenta por cobrar, algo que
ya ha pasado en integraciones de bancos/ERP reales) → `_dec("-500.00")`
devuelve `Decimal("-500.00")` sin objeción → `upsert_outstanding_invoice`
la inserta tal cual (`float(-500.00)`) en una columna `monto REAL NOT NULL`
que solo exige "no nulo", no "no negativo". La fila queda viva en la
cartera de cobranza con signo invertido.

Consecuencia: nada en la base impide un monto negativo, un `status`
inventado (los 8 campos `status`/`estado` de `models.py` son `TEXT` libre,
sin `CHECK ... IN (...)`), o un `score` fuera de `[0,1]`. Coincide
exactamente con la pregunta que define este rubro: "¿la base lo impide, o
'la aplicación se encarga'?" — aquí ni la aplicación se encarga.

Causa raíz probable: todas las migraciones (SQLite y Postgres) se escribieron
con `sa.Column(...)`/`CREATE TABLE` planos, sin `CheckConstraint`; el patrón
nunca se introdujo en ninguna de las 14 migraciones.

## Lo que revisé y está bien

- **Unicidad multi-tenant, correctamente escopeada en 8 de 8 tablas
  candidatas.** `invoices` (`tenant_id, folio_fiscal` —
  `0001_initial.py:71-72`), `tenant_config` (`tenant_id, config_key` —
  `models.py:159`), `cuentas_contables` (`tenant_id, codigo` —
  `models.py:291`), `balanzas_mensuales` (`tenant_id, periodo, cuenta_id` —
  `models.py:318`), `client_users` (`tenant_id, email` — `models.py:356`,
  con comentario explícito de por qué NO es global: un mismo correo puede
  existir en dos despachos distintos), `billing_customers` (`tenant_id,
  email` — `models.py:425`), `webhook_subscriptions` (`tenant_id, event, url`
  — `models.py:270`), `feature_flags` (`tenant_id, name` —
  `0004_audit_feature_flags.py`, `uq_feature_flag`), `collection_config`
  (`tenant_id, config_key` — `0007_collections_module.py`,
  `uq_collection_config_tenant_key`). Ningún tenant puede bloquear un valor
  que otro tenant necesite en ninguna de estas tablas.
- **Las dos únicas restricciones `UNIQUE` globales (`api_keys.key_hash`,
  `portal_sessions.token_hash`) son correctas por diseño**, no un descuido:
  son hashes de credenciales/tokens que deben resolverse en O(1) sin conocer
  primero el tenant, y el comentario en `models.py:346` demuestra que el
  autor ya distinguió deliberadamente este caso del de `client_users.email`.
- **Verifiqué y descarté los 3 bugs bloqueantes de `PG_BUG_REPORT.md` contra
  el código actual — ya no reproducen, aunque por rutas distintas a las que
  el reporte recomendaba:**
  - Bug 1 (`insert_invoice`, placeholders `:nombre`): `qmark_to_percent`
    (`pg.py:33-77`) SÍ traduce `:nombre` → `%(nombre)s` hoy (líneas 63-74) —
    el reporte decía que solo traducía `?`. Ya no es cierto.
  - Bug 2 (`log_call`, payload vacío → `''` inválido en jsonb):
    `db.py:381` hoy escribe `'{}'` (JSON válido) cuando `payload is None`,
    no `''`. Además `audit_log.payload` en `0001_initial.py:100` es
    `sa.Text()`, no `jsonb` — el reporte lo vio como `jsonb` porque el
    Postgres de prueba había derivado del esquema actual (su propio hallazgo
    #4), no porque las migraciones lo definan así hoy.
  - Bug 3 (`upsert_outstanding_invoice`, `ON CONFLICT` sin constraint):
    `0001_initial.py:218-232` ya define `uq_outstanding_unique` directo en
    el `CREATE TABLE` de `outstanding_invoices` — cualquier Postgres
    desplegado desde cero con las migraciones actuales lo tiene desde el
    principio.
  - El hallazgo #5 del mismo reporte ("`with self.conn:` no hace commit en
    PG", marcado ahí mismo como "inferido, no reproducido") lo revisé leyendo
    el código fuente instalado de `psycopg_pool` 3.3.1
    (`psycopg_pool/pool.py:172-192`) y es **incorrecto**: sí hace commit. El
    problema real es el de mi hallazgo CRÍTICO de arriba (libera la conexión
    al pool, no que falle el commit) — una causa distinta y más grave que la
    que el reporte había sospechado.
- **Las migraciones de Alembic sí son reversibles**: los 8 archivos en
  `migrations/versions/` definen `downgrade()` completo y simétrico a su
  `upgrade()`. (La lista `MIGRATIONS` de SQLite en `models.py` no tiene
  downgrade — es solo forward — pero es un backend de dev/test, no el de
  producción; no lo cuento como hallazgo de este rubro.)
- **Los tipos `sa.BigInteger()`/`INTEGER PRIMARY KEY` y las claves foráneas
  explícitas coinciden 1:1 entre `models.py` y las tablas que sí están en
  Alembic** — para las 32 tablas que existen en ambos lados, no encontré
  columnas con tipo distinto entre SQLite y Postgres más allá de lo ya
  reportado (Float/REAL de dinero).

## Lo que NO alcancé a revisar

- **No pude ejecutar `alembic upgrade head` contra un Postgres real** — el
  entorno de esta auditoría bloqueó el comando por su potencial de escribir
  en una base (clasificador de auto-mode). Sustituí con dos verificaciones
  sin conexión (`alembic heads`/`branches`/`history`, y
  `command.upgrade(cfg, 'head', sql=True)` en modo offline) que ya bastan
  para probar el `CommandError`, pero no vi el mensaje de stderr exacto que
  produciría el subproceso real que lanza `_pg_migrate()`, ni si algún
  `except` más arriba en `app.py`/`create_app()` lo convierte en un 500
  limpio o en un crash duro del proceso.
- **No reproduje el hallazgo de la conexión reutilizada bajo concurrencia
  real contra Postgres** (no hay instancia PG viva en este entorno). El
  trazo del código y de `psycopg_pool` es exacto y verificado línea por
  línea, pero el efecto exacto bajo carga (excepción de protocolo vs.
  mezcla silenciosa de resultados entre tenants) es una inferencia razonable
  a partir de la mecánica, no algo que haya visto ocurrir.
- **No comparé columna por columna las 32 tablas compartidas** entre
  `models.py` y Alembic más allá de nombres de tabla, tipos de dinero y
  unicidad — pudieron quedar diferencias menores de nullability o default
  que no alcancé a listar una por una.
- **No revisé RLS** porque este proyecto no usa Supabase ni políticas RLS de
  Postgres — el aislamiento multi-tenant depende enteramente de que cada
  query en `db.py` filtre por `tenant_id` a mano (lo cual es responsabilidad
  del rubro de backend/seguridad, no de este). Lo dejo anotado porque el
  rubro de datos lo menciona explícitamente y quiero que quede claro que no
  aplica aquí, no que se me olvidó.
- **No corrí yo mismo la suite completa de 4900 pruebas** — confié en la
  línea base ya verificada por el orquestador en `MAPA.md`.
