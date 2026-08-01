# Arquitectura y mantenibilidad — auditoría 1

**Nota: 2/10** (ronda 1, sin nota previa).

El riesgo mayor hoy: el mismo cálculo de ISR vive en dos archivos que ya
divergieron en el número — no en el redondeo, en el resultado — y ambos están
montados y accesibles en la misma app corriendo ahora mismo.

## Hallazgos

### [CRÍTICO] Dos calculadoras de ISR montadas en la misma app dan resultados distintos para el mismo salario
`b2b_ai/services/payroll.py:75` (`calc_isr`) vs `b2b_ai/features/nomina_completa/service.py:41` (`_calcular_isr`)

Escenario: un salario gravable mensual de **$20,000.00 MXN** entra por dos
caminos que coexisten en el mismo proceso `app.py`:

- `POST /api/v1/payroll/calculate` (montado en `b2b_ai/api/app.py:802`, y
  también expuesto al agente como la tool `calculate_payroll` en
  `b2b_ai/tools/tools.py:159-167`) llama a `calc_isr()` en `payroll.py`, que
  usa `TARIFA_ISR_2025_MENSUAL` (`payroll.py:25-35`, citada como "LISR art. 96
  (año fiscal 2025)", aritmética con `Decimal` y `ROUND_HALF_UP`). Verificado
  en vivo:
  ```
  >>> calc_isr(Decimal("20000"))
  {'impuesto': '2604.00', ..., 'referencia': 'LISR art. 96 (tarifa mensual)'}
  ```
- `/nomina-completa/*` (montado en `b2b_ai/api/app.py:1168` vía
  `build_nomina_completa_router()`) llama a `_calcular_isr()` en
  `features/nomina_completa/service.py:41-52`, que usa una tabla local
  `_ISR_TABLA` (`nomina_completa/service.py:29-37`) rotulada en el propio
  código como **"Tablas ISR 2026 (simplificadas — Mensual)"** — un año fiscal
  distinto, con brackets que no corresponden a ninguna tarifa SAT real (0% de
  ISR desde $0.01 hasta $47,071.37, luego salta a 30-39%). Verificado en vivo
  ejecutando la función tal cual está en el archivo:
  ```
  >>> _calcular_isr(20000)
  0.0
  ```

Con el mismo salario gravable de $20,000 MXN, un camino calcula **$2,604.00**
de ISR citando el artículo de ley; el otro calcula **$0.00** con una tabla que
el propio comentario del código admite que es "simplificada" y que corresponde
a un año fiscal que no es el vigente. `generate_cfdi_nomina()`
(`nomina_completa/service.py:138-193`) toma ese `$0.00` y lo escribe
directamente en `TotalRetenciones` del XML de nómina que se timbraría ante el
SAT.

Consecuencia: si un despacho usa `/nomina-completa` en vez de
`/api/v1/payroll/calculate` — y no hay ninguna señal en la API, el nombre de
ruta o la documentación que le diga cuál es "la buena" — genera y timbraría un
CFDI de nómina declarando cero retención de ISR sobre un sueldo de $20,000/mes,
una discrepancia que el SAT detecta por cruce automático contra la
declaración anual del trabajador. Ninguna prueba compara los dos caminos entre
sí: `tests/` cubre cada uno por separado, así que la suite verde no protege
contra esto.

Causa raíz probable: dos implementaciones de la tabla ISR construidas por
corridas de agente independientes (`features/nomina_completa/` es un paquete
autocontenido con su propio `models.py`/`service.py`/`routes.py`, sin importar
nada de `services/payroll.py`) que nunca se reconciliaron ni se dedicaron a un
solo lugar.

---

### [CRÍTICO] El backend Postgres no puede inicializarse hoy — dos cabezas de Alembic, no los 3 bugs ya documentados
`migrations/versions/0005_bank_reconciliation_state.py:20` y
`migrations/versions/0005_outstanding_unique.py:15` (ambos `down_revision =
"0004_audit_feature_flags"`) → `b2b_ai/db/db.py:190-196` (`_pg_migrate`)

Escenario: con un Postgres real corriendo (contenedor `b2b_prod_pg`, el mismo
DSN `postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai` que usa
`PG_BUG_REPORT.md`), corrí `alembic heads` y obtuve **dos** cabezas:
`0005_bank_reconciliation_state (head)` y `0007_collections_module (head)` —
la migración de conciliación bancaria quedó en una rama que nunca se fusionó
con la rama que sigue a `0006_outreach → 0007_collections_module`. Corrí la
suite real, `tests/test_db_pg_integration.py`, contra ese Postgres:

```
B2B_DB_URL="postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai" \
  .venv/bin/python -m pytest tests/test_db_pg_integration.py -v
→ 6 errors (los 6 tests), todos en el fixture:
RuntimeError: Fallo la migración Alembic a PostgreSQL: ... ERROR
[alembic.util.messaging] Multiple head revisions are present for given
argument 'head'; please specify a specific target revision...
```

Ningún test llega siquiera a ejecutar un `assert`: `Database(dsn)` nunca
termina de construirse porque `_pg_migrate()` corre `alembic upgrade head`
(singular) y eso revienta antes de tocar una sola tabla.

Esto **reemplaza**, no confirma, el diagnóstico de `PG_BUG_REPORT.md`.
Verifiqué los 3 bugs documentados ahí directamente contra el Postgres real,
llamando a la capa `pg.py` tal como está hoy (sin aplicar ningún fix sugerido
en el reporte):

- Bug #1 (`insert_invoice`, placeholders `:nombre`) — **NO reproducible**:
  `qmark_to_percent()` (`b2b_ai/db/pg.py:33-77`) ya traduce `:nombre` →
  `%(nombre)s` y el INSERT con un dict de params corre limpio.
- Bug #2 (`log_call`, payload vacío → `''` en `jsonb`) — **NO reproducible**:
  `b2b_ai/db/db.py:381` ya usa `if payload is not None else '{}'`, no `''`.
- Bug #3 (`upsert_outstanding_invoice`, `ON CONFLICT` sin constraint único) —
  **CONFIRMADO reproducible**: `InvalidColumnReference: there is no unique or
  exclusion constraint matching the ON CONFLICT specification`. Y el fix
  defensivo que alguien ya escribió para esto —
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_outstanding_unique` en
  `b2b_ai/db/db.py:200-206` — es **código muerto**: está colocado *después*
  de la llamada a `alembic upgrade head` que ahora siempre lanza `RuntimeError`
  primero por las cabezas duplicadas, así que nunca se ejecuta.

Consecuencia: `DEPLOY-GUIDE.md` apunta a Railway con Postgres como backend de
producción. Con el árbol de migraciones tal como está, el primer arranque de
la app contra ese Postgres falla en `Database.__init__` — no hay demo, no hay
API, no hay nada, porque el proceso ni siquiera levanta. Esto es más grave que
los 3 bugs que ya se conocían: aquellos bloqueaban 3 escrituras específicas
después de que la app arrancara; esto bloquea el arranque completo.

Causa raíz probable: dos ramas de migración (`0005_bank_reconciliation_state`
y `0005_outstanding_unique → 0006 → 0007`) creadas por trabajo paralelo sobre
`0004` sin que nadie corriera `alembic merge` antes de commitear.

---

### [CRÍTICO] `/api/v2/analytics`, `/api/v2/audit` y `/api/v2/export` truenan en cualquier despliegue con Postgres — tercera capa de conexión, hardcodeada a SQLite
`b2b_ai/db/pool.py:53` (`sqlite3.connect(self.db_path, ...)`) ←
`b2b_ai/api/v2.py:182` (`ConnectionPool(db.path, size=4)`)

Escenario: `b2b_ai/db/pool.py` es una tercera implementación de la capa de
conexión — además de `Database.conn` (que sí distingue SQLite/Postgres, ver
`db.py:110-119`) y de `PGPool` en `pg.py` — y está **hardcodeada** a
`sqlite3.connect()` (`import sqlite3` en la línea 20, sin ninguna rama para
Postgres). `build_v2_router()` la instancia con `db.path`
(`api/v2.py:182`), que en producción es exactamente el DSN de `B2B_DB_URL`
que Railway inyecta (`postgresql://...`, ver `DEPLOY-GUIDE.md:81` y
`.env.production.example:40-42`). Reproduje la llamada exacta que hace
`pool.py:53` con ese DSN:

```
>>> sqlite3.connect("postgresql://b2b:b2bpass@127.0.0.1:54329/b2b_ai", timeout=5.0)
sqlite3.OperationalError: unable to open database file
```

Ese `ConnectionPool` alimenta directamente tres rutas — todas bajo el tag
`"enterprise"` de `api/v2.py` — que no envuelven la llamada en ningún
`try/except`:
- `GET /api/v2/analytics` → `pool.run("SELECT * FROM invoices WHERE
  tenant_id=?", ...)` en `api/v2.py:356`.
- `GET /api/v2/audit` → `pool.run("SELECT * FROM audit_log WHERE
  tenant_id=?...")` en `api/v2.py:417`.
- `POST /api/v2/export` (scope `invoices` o `audit`) → mismo patrón en
  `api/v2.py:441` y `445`.

Consecuencia: en el despliegue de producción que `DEPLOY-GUIDE.md` describe,
la primera llamada a cualquiera de estos tres endpoints lanza
`sqlite3.OperationalError` sin capturar dentro del handler — un 500 duro, no
un dato vacío silencioso. El tier "enterprise" de la API (analytics, auditoría
exportable, export de facturas) queda inservible apenas se conecta a la base
de datos que el propio `DEPLOY-GUIDE.md` recomienda.

Causa raíz probable: `pool.py` se escribió (según su propio docstring, línea
11) asumiendo que "el mismo contrato es el que usaría un pool real de
PostgreSQL... cuando se migre a PG" — la migración de contrato nunca pasó;
solo se escribió el contrato, no la implementación Postgres.

---

### [ALTO] La "contabilidad electrónica" del SAT existe en tres implementaciones independientes, montadas en dos rutas casi idénticas
`b2b_ai/services/contabilidad_electronica.py` + `b2b_ai/services/balanza.py`
vs `b2b_ai/features/contabilidad/electronica_routes.py` (prefix
`/contabilidad/electronica`, `app.py:1146`) vs
`b2b_ai/features/contabilidad_electronica/` (prefix
`/contabilidad-electronica`, `app.py:1162`)

Escenario: las tres generan el mismo entregable regulatorio (Balanza de
Comprobación + Catálogo de Cuentas en XML conforme al esquema del SAT, ver
`features/contabilidad_electronica/generator.py:3-11`). Las dos rutas HTTP
difieren solo en un guion (`/contabilidad/electronica` vs
`/contabilidad-electronica`) — un nombre de ruta que un cliente de la API
puede confundir fácilmente. Verifiqué que **no** comparten el mismo modelo de
catálogo de cuentas: `features/contabilidad/electronica_routes.py:27` importa
y reutiliza `CatalogoCuentas` de `services/catalogo_cuentas.py` (hay
disciplina ahí), pero `features/contabilidad_electronica/generator.py:18-21`
importa su propia clase `CatalogoCuenta`, definida en
`features/contabilidad_electronica/models.py` — un tercer modelo de datos
para el mismo catálogo SAT.

Consecuencia: no evalué si los tres producen el mismo XML byte a byte para el
mismo input (no alcancé a montar ese caso), pero el patrón — tres paquetes
de código que reclaman resolver el mismo requisito regulatorio, con al menos
dos modelos de datos distintos para "catálogo de cuentas" — es exactamente el
que hace que una corrección de esquema aplicada a uno no llegue a los otros
dos la próxima vez que el SAT cambie el XSD.

Causa raíz probable: mismo patrón que el hallazgo de nómina — paquetes
`features/*` construidos por corridas independientes sin catálogo de qué ya
existía en `services/`.

---

### [ALTO] El mapa de la auditoría apunta a un DIOT muerto; el DIOT que corre de verdad no está en ningún documento
`b2b_ai/services/diot_service.py` + `b2b_ai/services/diot_validator.py`
(citados en `docs/auditoria-1/MAPA.md` punto 6 como "el" código fiscal DIOT)
vs `b2b_ai/features/diot/service.py` (montado en vivo en `/api/v1/diot`,
`app.py:1189`)

Escenario: busqué quién importa `services/diot_service.py` o
`services/diot_validator.py` fuera de sus propios archivos de prueba
(`tests/test_diot_service.py`, `tests/test_diot_validator.py`) en todo el
repo — cero resultados. No los importa `app.py`, no los importa
`agent/loop.py`, no los importa `tools/tools.py`, no los importa
`services/pipeline.py`. Es decir: **794 líneas de lógica DIOT
(diot_service.py + diot_validator.py), con su propia suite de pruebas verde,
nunca se ejecutan cuando alguien llama a la API real.** El DIOT que sí
responde en `/api/v1/diot` es `features/diot/service.py`, con su propio
sistema de tipos (`DiotEntry`, `DiotReport`, `DiotSummary`, `EstatusDIOT`,
`TipoIva`, `TipoOperacion` en `features/diot/models.py`) completamente
distinto al de `services/diot_service.py` (`DIOTOperation`, `RFCSummary`,
`DIOTSummary`, `DIOTReport`).

Consecuencia: `MAPA.md` — escrito por el propio orquestador de esta ronda —
le dice al rubro fiscal (6) que audite `services/diot_validator.py` y
`services/diot_service.py` como "la" lógica DIOT. Un auditor fiscal que siga
esa instrucción al pie de la letra audita código que nadie en producción
ejecuta jamás, mientras el motor DIOT que sí genera el XML que se manda al
SAT (`features/diot/service.py`) queda sin revisar. No pude verificar si
`features/diot/service.py` calcula IVA trasladado/acreditable de forma
correcta — eso es trabajo del rubro fiscal, pero con la ruta correcta esta
vez.

Causa raíz probable: el mapa de rubros se escribió leyendo nombres de archivo
por convención (`diot_service.py` "suena" a la implementación) sin verificar
imports reales; el mismo error de método que este rubro le exige a los demás
evitar.

## Lo que revisé y está bien

- **El parseo de CFDI 4.0 SÍ está centralizado.** `b2b_ai/cfdi/parser.py` es
  la única definición de `parse_cfdi()` en todo el repo (confirmado con
  `grep` de `def parse_cfdi`), y los 6 archivos que necesitan leer un CFDI
  (`tools/tools.py`, `tools/registry.py`, `cfdi/validator.py`,
  `services/classify.py`, `services/llm.py`) importan de ahí, no reimplementan
  el parseo. Este es exactamente el patrón que el resto del repo debería
  seguir y no sigue.
- **No hay acceso a datos crudo fuera de `db/`.** Busqué `sqlite3.` y
  `psycopg.` en todo `b2b_ai/` excluyendo `b2b_ai/db/` — cero resultados
  (aparte del propio `pool.py`, que sí cuenta como una fuga, ver hallazgo
  arriba). `features/flags.py`, `audit/trail.py` y `monitoring/health.py`
  llaman `.execute()` directo sobre `db.conn` con su propio SQL en vez de usar
  métodos nombrados de `Database`, pero pasan por la propiedad `.conn` que sí
  resuelve SQLite/Postgres correctamente — no es una fuga de dialecto, es
  fragmentación de dónde vive el SQL (deuda menor, no un hallazgo con
  escenario de falla).
- **El aislamiento multi-tenant es una convención respetada en lo que
  muestreé.** `get_invoice`, `list_bank_transactions`,
  `set_bank_confirmation`, `list_bank_confirmations` (todos en `db.py`)
  filtran consistentemente por `tenant_id` con el patrón
  `COALESCE(tenant_id, -1)=COALESCE(?, -1)`. `db/tenants.py` documenta la
  convención `scoped_*` explícitamente en su docstring.
- **La duplicación de `_dec()`/`_round2()` entre `services/payroll.py:54-64` y
  `services/balanza.py:29-39` es texto casi idéntico** (un solo carácter de
  diferencia: el guard `v == ""`) **pero no encontré ningún valor de entrada
  para el que hoy produzcan resultados distintos** — la excepción capturada
  en `payroll.py` termina devolviendo el mismo default que el guard explícito
  de `balanza.py`. Lo dejo fuera de los hallazgos porque no puedo escribir el
  escenario "entra X → sale Y mal" que el formato exige, pero es la clase de
  duplicación que un cambio futuro en un archivo y no el otro convertiría en
  bug real sin aviso.

## Lo que NO alcancé a revisar

- Las cuatro implementaciones de "conciliación" (`services/bank_reconciliation.py`,
  `features/conciliacion/`, `features/conciliacion_fiscal/`,
  `features/reconciliacion_ingresos_egresos/`) — leí sus docstrings y
  *parecen* resolver problemas distintos (facturas-vs-banco,
  ERP-vs-declaración-SAT, ingresos-egresos-vs-auxiliares contables), así que
  no las reporto como duplicado, pero no verifiqué si sus algoritmos de
  matching producen resultados distintos ante el mismo par de registros.
- Las ~35 integraciones bajo `b2b_ai/integrations/` (bancos, pagos, CRM,
  storage, firmas, SAT) — confirmé que el paquete existe, está enganchado vía
  `hub.py`, y que `integrations/nomina/` es una *quinta* superficie con la
  palabra "nómina" en el nombre, pero no abrí cada adaptador para juzgar
  calidad; es más trabajo de los rubros de backend/integraciones específicas.
- No diferencié entre las fórmulas de IMSS/INFONAVIT/PTU/aguinaldo de
  `payroll.py` contra las de `nomina_completa/service.py` más allá de ISR —
  encontré la divergencia de ISR y prioricé verificarla a fondo con números
  reales; es probable que IMSS/INFONAVIT tengan el mismo problema, sin
  confirmar.
- No corrí la suite completa de `pytest` yo mismo (usé la línea base del
  orquestador: 4900 passed / 16 skipped / 0 failed sobre SQLite); sí corrí
  específicamente `tests/test_db_pg_integration.py` contra Postgres real,
  que no está en esa línea base porque se salta (`skipif`) sin
  `B2B_DB_URL`.
- No até el hallazgo del ConnectionPool a un test que lo cubra o no —
  plausible que no exista ningún test de `api/v2.py` que corra con
  `B2B_DB_URL` apuntando a Postgres real, lo que explicaría por qué nadie lo
  detectó; no confirmé la ausencia exacta de ese test.
