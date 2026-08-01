# likida-ai-enterprise — 41 críticos, uno por uno

Fuente: `docs/auditoria-1/` (auditoría 1, 1-ago-2026). Cada uno se verificó
ejecutando el código real (TestClient, Postgres en Docker, mutación de
funciones de producción), no solo leyéndolo. Ninguno resultó falso.

**Orden: seguridad y dinero primero, cosmético al final.** Manda cada bloque
`## [N] ...` como una tarea independiente al agente en Hermes — trae título,
archivo:línea, escenario reproducido, consecuencia y causa raíz probable, que
es lo que un agente necesita para arreglarlo sin tener que volver a
investigar. No traen sugerencia de fix explícita a propósito (la auditoría no
propone arreglos, solo diagnostica) — dile al agente que reproduzca el
escenario primero, luego arregle, luego confirme con la prueba.

---

## [1] likida-ai-enterprise · Seguridad
### Un desconocido se vuelve admin de cualquier despacho con una petición sin token
`b2b_ai/auth/api.py:110-117` · `b2b_ai/db/tenants.py:96-99` · `b2b_ai/db/db.py:230`

`POST /api/v1/auth/register` no exige token si el tenant "todavía no tiene
usuarios", y decide eso con `db.list_client_users(tenant_id)`. Pero
`onboard_tenant()` —el único camino de alta, tanto por `POST /api/v1/tenants`
como por `POST /api/v2/tenants`— crea el usuario con `db.create_user()`, que
inserta en la tabla **`users`**. `client_users` se queda vacía **para siempre**.
La condición de bootstrap nunca se cierra.

Escenario, ejecutado:

```
onboard_tenant("Despacho Victima", rfc="AAA010101AAA")   → tenant_id=1
db.list_client_users(1)                                  → []          ← ya aquí
POST /api/v1/auth/register  (SIN cabecera Authorization)
  {"email":"atacante@evil.com","password":"Passw0rd!23",
   "tenant_id":1,"role":"auxiliar"}
→ 200  {"user":{"id":1,"tenant_id":1,"role":"admin"}}     ← pidió auxiliar, le dieron admin
POST /portal/auth/login  {"email":"atacante@evil.com", ...,"tenant_id":1}
GET  /portal/invoices.json
→ 200  [{"id":1,"tenant_id":1,"emisor_nombre":"PROVEEDOR CONFIDENCIAL SA",
         "receptor_rfc":"AAA010101AAA","total":"116000.00"}]
GET  /portal/invoices/export.csv
→ 200  1,2026-01-15,I,A,777,UUID-1,XEXX010101000,PROVEEDOR CONFIDENCIAL SA,
       AAA010101AAA,100000.00,16000.00,116000.00,...
```

`tenant_id` es un rowid de SQLite: 1, 2, 3… Un `for` de 1 a 500 reclama todos
los despachos del sistema. Además el rol pedido se ignora y se otorga `admin`
(`auth/api.py:117`), así que el intruso también puede listar y crear usuarios
del tenant (`GET/POST /api/v1/tenants/{id}/users` respondieron 200).

Consecuencia: el despacho víctima pierde el padrón fiscal completo de **sus
clientes** —RFC emisor y receptor, razón social, montos, IVA, folio fiscal— a
manos de cualquiera con la URL. Es dato personal de terceros bajo la LFPDPPP y
el despacho es el responsable. En un demo del 6-ago, es el tipo de cosa que un
contralor con curiosidad encuentra sin proponérselo.

Causa raíz probable: el chequeo de bootstrap y el alta de onboarding hablan de
"el usuario del tenant" pero apuntan a dos tablas distintas; nadie las cruzó.


## [2] likida-ai-enterprise · Seguridad
### `/api/v2/batch` lee cualquier archivo del disco del servidor y lo importa al tenant del atacante
`b2b_ai/api/v2.py:286-314` y `v2.py:239-249` · guardarraíl ausente que sí existe en `b2b_ai/api/app.py:388-416`

`app.py:353-372` documenta este agujero con lujo de detalle y lo declara
cerrado: la ingesta por ruta local quedó opt-in tras `B2B_LOCAL_XML_DIRS` y
`_resolve_local_path()`. Ese guardarraíl se cableó **solo en `/api/v1`**
(`app.py:664`, `1246`, `1250`). `/api/v2/batch` pasa `req.paths` y
`glob.glob(req.folder + "/*.xml")` directo a `process_file()` sin validar nada.

Escenario, ejecutado (dos tenants, la clave es la del atacante):

```
B2B_LOCAL_XML_DIRS = ''            ← la ingesta local está "desactivada"

POST /api/v2/batch   X-API-Key: <clave del ATACANTE, tenant 2>
  {"paths":["/…/cfdi_privados_victima/secreto.xml"]}
→ 200  {"procesadas":1,"insertadas":1}

GET /api/v1/invoices  X-API-Key: <clave del ATACANTE>
→ [(id=1, tenant_id=2, emisor='XEXX010101000',
    receptor='AAA010101AAA', total='116000.00')]     ← el CFDI de la víctima, en el tenant 2

POST /api/v1/invoices/process   (mismo archivo, misma clave)
→ 400 "La ingesta por ruta local está desactivada."   ← la puerta que SÍ cierra
```

Y `folder` sirve de oráculo del sistema de archivos: `procesadas` cuenta cuántos
`.xml` hay en el directorio que uno nombre, sin necesidad de leerlos.

Consecuencia: un despacho cliente lee los CFDI de otro despacho cliente que
estén en disco (adjuntos de `/api/v1/webhooks/email`, temporales del portal,
respaldos) y se los queda en su propio tenant. Aislamiento multi-tenant roto
por debajo de la capa de datos, que en sí está bien filtrada.

Causa raíz probable: el arreglo se aplicó por endpoint en vez de en
`process_file()` o en una dependencia común; v2 se escribió antes o en paralelo
y nunca se revisó contra el fix.


## [3] likida-ai-enterprise · Seguridad
### Nómina y pre-auditoría están montadas sin ninguna credencial, con el `tenant_id` puesto por el cliente
`b2b_ai/api/app.py:1165,1168` · `b2b_ai/features/nomina_completa/routes.py:57,100-140,147-158` · `b2b_ai/features/pre_auditoria/routes.py:60,141-185`

`build_nomina_completa_router()`, `build_pre_auditoria_router()`,
`build_contabilidad_electronica_router()`, `build_contabilidad_router()`,
`build_reportes_router()`, `build_pagos_router()`, `build_nomina_router()` y
`build_email_processing_router()` se incluyen **sin pasarles
`require_api_key`**, a diferencia de sus 20 vecinos en el mismo bloque. Ninguna
de sus rutas declara `Depends` de auth. Sobre el OpenAPI vivo: de 220
operaciones, 60 no declaran credencial; descontando las públicas legítimas
(login, health, metrics, leads, planes) quedan ~40 que sí manejan datos.

Escenario, ejecutado, sin ninguna cabecera:

```
POST /nomina-completa/process
  {"tenant_id":4,"period":{"year":2026,"month":1},
   "employees":[{"employee_id":"E-0001","nombre":"MARIA LOPEZ HERNANDEZ",
                 "curp":"LOHM850312MDFPRR03","rfc":"LOHM850312AB1",
                 "nss":"12345678901","salario_diario":2200.0,"dias":30}]}
→ 200

GET /nomina-completa/payslip/E-0001?tenant_id=4&year=2026&month=1
→ 200 {"payslip":{"empleado":{"nombre":"MARIA LOPEZ HERNANDEZ"},
        "deducciones":{"isr":22302.0,"imss_obrero":429.0,
                       "infonavit":3300.0,"total":26031.0}}}

GET /pre-auditoria/report/7-2026-01          → 200  (composite_id = "{tenant_id}-{periodo}")
GET /pre-auditoria/history?tenant_id=7       → 200
GET /api/v1/email/history                    → 200
GET /api/v1/reportes/                        → 200
```

El `tenant_id` sale del cuerpo o del query string, nunca de una credencial, así
que el aislamiento no existe en absoluto en estos routers: se lee y se escribe
el compartimento del tenant que uno teclee.

Consecuencia: nombre de empleado, ISR, IMSS e INFONAVIT de la nómina de un
despacho quedan legibles sin cuenta. Y en sentido inverso, cualquiera puede
**escribir** nómina en el compartimento de un tenant real, que después el
despacho descarga y timbra. Dato personal de un trabajador expuesto — el
supuesto textual de CRÍTICO.

(El almacén de estos routers es un dict en memoria del proceso, así que sólo
está expuesto lo que se haya procesado desde el último arranque. No lo baja de
crítico: en un servidor de producción con uptime de días eso es la nómina del
periodo corriente.)

Causa raíz probable: `build_*_router(db, require_api_key)` es el patrón del
bloque y estos ocho se escribieron con la firma sin argumentos; nadie contó las
rutas del OpenAPI contra las que exigen clave.


## [4] likida-ai-enterprise · Seguridad
### La firma del webhook de pago no protege nada, y el atacante elige qué secreto se verifica
`b2b_ai/billing/api.py:59-78` (`_verify_webhook_signature`), `api.py:80-87`, `api.py:186-206` · `b2b_ai/billing/stripe_provider.py:158-164` · `conekta_provider.py:234`

Tres defectos apilados en la misma función:

1. **Sin secreto, pasa todo.** `if not secret: return True` (`api.py:71-72`).
   El despliegue por defecto no define `B2B_STRIPE_WEBHOOK_SECRET` — no aparece
   en `.env.production.example` ni en `DEPLOY-GUIDE.md` —, así que el estado de
   fábrica es *ninguna verificación*. Es exactamente el "secreto con fallback
   silencioso" del rubro.
2. **El atacante decide qué env se consulta.** `_get_webhook_secret()` se
   alimenta de `payload.provider`, un campo del **cuerpo**. Ejecutado, con
   `B2B_STRIPE_WEBHOOK_SECRET` correctamente configurado:

   ```
   POST /api/v1/billing/webhook   {"provider":"stripe",  "event_type":"invoice.paid", …}
   → 401 "Firma de webhook inválida."
   POST /api/v1/billing/webhook   {"provider":"conekta", "event_type":"invoice.paid", …}
   → 200 {"received":true, "result":{"provider":"stripe", …}}   ← ni miró la firma
   ```

   Basta declararse del proveedor cuyo secreto no está puesto. Y el evento se
   procesa igual con el proveedor **configurado** (fíjese que la respuesta dice
   `"provider":"stripe"`), no con el declarado.
3. **Aun con secreto, jamás valida un webhook real.** Se firma
   `_json.dumps(payload.model_dump())` (`api.py:202`), una **re-serialización**
   del modelo ya parseado, no el cuerpo crudo. Stripe firma
   `"{timestamp}.{raw_body}"` y su cuerpo trae `id`, `created`, `livemode`,
   `api_version`… que `WebhookPayload` descarta. El HMAC nunca puede coincidir:
   el 401 de arriba es un webhook legítimo rebotado. Tampoco hay ventana de
   tiempo, así que no hay defensa de replay.

Consecuencia: `StripeProvider.webhook_handler("invoice.paid", …)` devuelve
`{"mark_paid": True, "invoice_id": "in_…"}` (verificado), y el endpoint lo
obedece. Traducción: se dan por pagadas facturas que nadie pagó, o —peor para
el negocio— el operador pone bien el secreto, todos los cobros reales rebotan
con 401 y ninguna suscripción se marca pagada nunca. Dinero mal en ambos
sentidos. Los propios proveedores lo saben: `stripe_provider.py:162` dice "en
producción la firma del webhook se debe verificar… antes de confiar en el
payload", y no lo hace nadie.

Causa raíz probable: la verificación se escribió sobre el modelo ya parseado en
vez de sobre `await request.body()`, y la elección de secreto se ató a un campo
del cuerpo en vez de a la configuración del servidor.


## [5] likida-ai-enterprise · Backend y API
### IDOR: una API key de un tenant escribe facturas en el libro de otro tenant
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


## [6] likida-ai-enterprise · Backend y API
### `POST /api/v1/outreach/leads` revienta el 100% de las veces
`b2b_ai/api/outreach.py:49`
```python
lead_id = db.create_outreach_lead(name=lead.name, email=lead.email, ...)
```
`Database` no tiene el método `create_outreach_lead` — existe `add_outreach_lead(self, campaign_id, tenant_id, email, first_name=..., ...)`, con firma distinta (pide `campaign_id`/`tenant_id` que `LeadCreate` ni siquiera declara). Probado en vivo: `POST /api/v1/outreach/leads` con una key válida y body válido según el schema devuelve **500 Internal Server Error** siempre — `AttributeError: 'Database' object has no attribute 'create_outreach_lead'`.

Escenario: un integrador (o Likida mismo) llama al endpoint documentado en el router para dar de alta un lead de outreach → 500 sin excepción, en cada intento, sin excepción de casos borde: el método simplemente no existe.

Consecuencia: la única vía documentada para crear un lead vía API está muerta desde que se escribió. `tests/test_outreach.py` nunca la ejercita — prueba `OutreachManager`/`Database` directo, sin `TestClient`, así que 74 tests de esta zona pasan en verde sin haber llamado nunca a esta ruta.

Causa raíz probable: desalineación entre el nombre de método que `outreach.py` esperaba (`create_outreach_lead`, plausible del vocabulario REST estándar) y el que `db.py` implementó (`add_outreach_lead`), nunca detectada porque no hay prueba de integración del router.


## [7] likida-ai-enterprise · Backend y API
### La API no arranca contra PostgreSQL hoy: `alembic upgrade head` falla con dos heads
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


## [8] likida-ai-enterprise · Backend y API
### `DEPLOY-GUIDE.md` documenta una variable que el código nunca lee: en Railway la app corre en SQLite efímero, no en Postgres
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


## [9] likida-ai-enterprise · Cumplimiento fiscal
### La aportación patronal de INFONAVIT se descuenta del sueldo del trabajador
`b2b_ai/services/payroll.py:128-138`, `:260`, `:269-276`, `:398-399`

Escenario: `calculate_payroll({"salario_diario":"500"}, 15000)` →
`deducciones.infonavit = "26.13"`, restado en `neto_a_pagar`, y emitido en el CFDI
como `<nomina:Deduccion TipoDeduccion="003" Concepto="INFONAVIT">`.

El 5% del SBC del art. 29 fr. II de la Ley del INFONAVIT es una **aportación a
cargo del patrón**, no una deducción al trabajador. Lo único descontable al
trabajador es la amortización de un crédito INFONAVIT vigente (art. 29 fr. III),
cuyo monto lo fija el aviso de retención del instituto, no un 5% del SBC. La LFT
art. 110 enumera las deducciones permitidas y esta no está.

Consecuencia: el trabajador cobra de menos cada periodo por un concepto que no se
le puede descontar; el patrón sigue debiendo la aportación completa. Es una
deducción ilegal impresa en un recibo de nómina.

Causa raíz probable: se modeló una carga patronal como si fuera obrera.


## [10] likida-ai-enterprise · Cumplimiento fiscal
### Las cuotas de seguridad social se calculan sobre el SBC **diario** y se restan de una nómina **mensual**
`b2b_ai/services/payroll.py:110-125`, `:230-233`, `:252`, `:259-260`

Escenario (ejecutado): `salario_diario=500`, `sueldo_bruto=15000` →
`_sbc_desde` devuelve `522.60`, que es un SBC **diario** (500 × 1.0452). Luego
`calc_imss(522.60)` aplica las tasas sobre ese diario:
`eym=5.88`, `rcva=5.88`, **`imss total = 11.76`**, y ese es el importe restado del
neto mensual. La cuota obrera real sobre un SBC de 522.60/día por 30 días ronda
los **$370**. El código descuenta ~3% de lo debido — un factor ≈30 de error, que
es exactamente el número de días del periodo que nunca se multiplicó.

Consecuencia: el recibo de nómina que el despacho entrega a su cliente y al
trabajador trae un neto inflado ~$360/mes por trabajador; el patrón paga al IMSS
la cuota real y descubre el descuadre en la conciliación, o no lo descubre y la
provisión contable queda corta todo el ejercicio.

Nota adicional en la misma tabla: `RATES["imss_total_trabajador"] = 0.0175`
(`payroll.py:43`) se documenta como «≈ EYM + RCVA» pero EYM+RCVA como está
codificado suman `0.0225`. La constante no se usa en ningún lado y contradice a
las que sí. Las tasas no salen de una fuente: falta Invalidez y Vida, faltan
Gastos Médicos de Pensionados, y falta la regla del excedente de 3 UMA del art.
106 LSS.

Causa raíz probable: `dias_pagados` nunca entra al cálculo (ver siguiente
hallazgo); el SBC diario se trata como si fuera el del periodo.


## [11] likida-ai-enterprise · Cumplimiento fiscal
### El subsidio para el empleo no existe en el módulo de nómina
`b2b_ai/services/payroll.py` (módulo completo — 405 líneas, cero ocurrencias)

Escenario: verificado por búsqueda sobre el archivo — la palabra «subsidio» no
aparece. Para un trabajador con ingreso gravado de $8,000 mensuales,
`calc_isr(8000)` devuelve **`impuesto = "553.30"`** y `calculate_payroll` retiene
esos 553.30 completos. El subsidio para el empleo es de aplicación **obligatoria**
para el patrón en ese rango de ingreso, se acredita contra el ISR del periodo, y
cuando lo excede se **entrega en efectivo** al trabajador.

Consecuencia doble: (1) al trabajador se le retiene ISR que no debía retenérsele;
(2) el CFDI de nómina que emite `generate_payroll_cfdi` sale sin el nodo
`<nomina:OtroPago TipoOtroPago="002">` con `SubsidioAlEmpleo`, que el PAC exige
cuando el subsidio es aplicable — el timbrado se rechaza, o peor, se timbra sin él
y la declaración anual del trabajador queda mal.

Marco como **no verificable en esta ronda** el monto exacto del subsidio (depende
del decreto vigente y de la UMA del ejercicio), pero su **ausencia total** es
verificable y es el hallazgo.

Causa raíz probable: se implementó la tarifa del art. 96 LISR y se paró ahí; el
subsidio vive en un decreto aparte que nadie transcribió.


## [12] likida-ai-enterprise · Cumplimiento fiscal
### El ISR de una nómina quincenal se calcula con la tarifa mensual
`b2b_ai/services/payroll.py:75` (parámetro `periodicidad`), `:80`, `:258`

Escenario (ejecutado): `calc_isr(7500, periodicidad="quincenal")` →
**`impuesto = "498.90"`**. El parámetro `periodicidad` está en la firma y **nunca
se lee en el cuerpo de la función**; siempre se aplica `TARIFA_ISR_2025_MENSUAL`.
El cálculo correcto para una quincena de $7,500 pasa por la tarifa del periodo (o
por el equivalente mensual de $15,000 → ISR 1,552.78 → mitad = **776.39**). El
código retiene **277.49 menos por quincena**, ~$6,660 al año por trabajador.

No es un camino hipotético: `generate_payroll_cfdi` documenta
`periodicidad ('Mensual'|'Quincenal')` en su docstring (`payroll.py:315`) y estampa
`PeriodicidadPago="Quincenal"` en el CFDI (`payroll.py:380`). El producto ofrece
explícitamente el camino donde el número sale mal.

Consecuencia: retención insuficiente en cada quincena del ejercicio. El patrón es
responsable solidario del ISR no retenido (CFF art. 26 fr. I): la diferencia se la
cobran a él, con actualización y recargos.

Causa raíz probable: el parámetro se agregó a la firma como intención y nunca se
implementó el despacho de tarifa.


## [13] likida-ai-enterprise · Cumplimiento fiscal
### `dias_vacaciones` se equivoca de escalón a partir del sexto año (LFT art. 76 reformado)
`b2b_ai/services/payroll.py:184-196` (la línea es `extra = ((a - 5) // 5) * 2`)

Escenario (ejecutado, código vs. LFT art. 76 vigente desde 1-ene-2023):

| Antigüedad | Código | Ley |
|---|---|---|
| 1-5 años | 12/14/16/18/20 | 12/14/16/18/20 ✓ |
| **6 años** | **20** | **22** ✗ |
| 7, 8, 9 años | 20 | 22 ✗ |
| 10 años | 22 | 22 ✓ |
| **11-14 años** | **22** | **24** ✗ |
| 15 años | 24 | 24 ✓ |
| **16-19 años** | **24** | **26** ✗ |

El texto reformado dice «A partir del **sexto** año, el período de vacaciones
aumentará en dos días por cada cinco de servicios» — el escalón abre en el año 6,
no en el 10. El código lo abre cinco años tarde y sólo coincide con la ley por
casualidad en los años 5, 10 y 15.

Y arrastra la prima vacacional: `calc_prima_vacacional(500, 6)` devuelve
`{'dias': 20, 'pago_vacaciones': '10000.00', 'prima': '2500.00'}` donde la ley da
22 días, $11,000 y $2,750.

Consecuencia: a un trabajador con 6 años de antigüedad y salario diario de $500 se
le pagan **$1,250 de menos** cada año (2 días de vacaciones + su prima), con la
leyenda «referencia: LFT arts. 76-77» impresa junto a la cifra. Es exactamente el
patrón que el rubro nombra: una cifra equivocada citando un artículo que dice otra
cosa.

Causa raíz probable: se tradujo «cada cinco años» al operador `//5` sin fijar bien
el origen del escalón.


## [14] likida-ai-enterprise · Cumplimiento fiscal
### El IVA acreditable toma sólo el **primer** traslado 002: en una factura de tasa mixta reporta 0.00
`b2b_ai/cfdi/parser.py:204`, consumido en `b2b_ai/cfdi/validator.py:96` y `:236-245`

Escenario (ejecutado con un CFDI real de tasa mixta — SubTotal 10,000 = 5,000 al
16% + 5,000 al 0%, TotalImpuestosTrasladados 800.00, Total 10,800):

```
iva parseado = 0.00        ← debería ser 800.00
ISSUE: total_incoherente | SubTotal + IVA − Descuento − Retenciones = 10000.00 pero Total=10800.00
DIOT: iva_acreditable = '0'
```

`next((t["importe"] for t in traslados if t["impuesto"] == "002"), None)` se queda
con el primer nodo `Traslado` de impuesto 002 y descarta el resto. El SAT agrupa
los traslados globales por (Impuesto, TipoFactor, TasaOCuota), así que **toda**
factura con más de una tasa de IVA —una despensa, un restaurante, una farmacia—
tiene dos o tres nodos 002 y este parser lee uno. `TotalImpuestosTrasladados`, que
es el dato autoritativo, se extrae en `parser.py:314` y **nunca se lee**.

Consecuencia: el despacho acredita $0 de IVA donde tenía derecho a $800 por
factura, y además la factura sale marcada `ok=False`. En el sentido contrario (si
el nodo de 16% viene primero y hay otro mayor después) acredita de más y la
diferencia se la reclama el SAT.

Causa raíz probable: se modeló «un CFDI tiene un IVA» cuando el Anexo 20 modela
una lista.


## [15] likida-ai-enterprise · Cumplimiento fiscal
### El validador de DIOT no contrasta el IVA acreditable contra nada: un 10× pasa como válido
`b2b_ai/services/diot_validator.py:253-262` y `:264-281`

Escenario (ejecutado): una operación con `Monto=10000.00`,
`IVATrasladado=1600.00`, **`IVAAcreditable=16000.00`** (un cero de más) →

```
valid = True   errores = 0   warnings = 0
total_iva_acreditable = 16000.0
```

La única validación sobre `IVAAcreditable` es `validate_non_negative_float`. La
comprobación de tasa efectiva de las líneas 264-281 mira sólo `IVATrasladado` /
`Monto`. No hay ninguna regla que diga que el acreditable no puede exceder al
trasladado, ni que deba guardar relación con el monto.

Consecuencia: el despacho presenta una DIOT declarando $16,000 de IVA acreditable
sobre una operación de $10,000, el producto le dijo «válido, 0 errores», y el
cruce del SAT contra la DIOT del proveedor lo detecta. Diferencia acreditada
indebidamente: $14,400 en una sola línea. Es el error que este módulo existe para
atrapar.

Causa raíz probable: se validaron tipos y signos, no relaciones aritméticas entre
campos.


## [16] likida-ai-enterprise · Cumplimiento fiscal
### Los catálogos SAT están inventados: se aceptan claves que no existen y se rechazan las que sí
`b2b_ai/cfdi/catalogs.py:53-91` (c_UsoCFDI) y `b2b_ai/services/diot_validator.py:38-43` (TipoOperacion)

Escenario A (ejecutado) — c_UsoCFDI. El catálogo oficial del Anexo 20 para CFDI
4.0 tiene G01, G02, G03, I01–I08, D01–D10, S01, CP01, CN01. El archivo agrega
**doce claves que no existen** y `is_valid_uso_cfdi` las aprueba:

```
G04=True  G07=True  G11=True  G13=True  G24=True  G25=True  P01=True
```

`P01` además es de CFDI **3.3** y quedó fuera en 4.0. Y las descripciones de las
que sí existen están cambiadas: el archivo pone I05 = «Dientes, piezas, accesorios
y aparatos de ajuste» (es «Dados, troqueles, moldes, matrices y herramental»), I06
= «Otros bienes o servicios» (es «Comunicaciones telefónicas»), I07 = «Bienes no
identificados» (es «Comunicaciones satelitales»), S01 = «Sin obligaciones
fiscales» (es «Sin efectos fiscales» — el nombre que copió es el del régimen 616).

Escenario B (ejecutado) — DIOT. El catálogo de Tipo de Operación de la DIOT es
**03** (prestación de servicios profesionales), **06** (arrendamiento de
inmuebles) y **85** (otros). El módulo declara `VALID_TIPO_OPERACION = {"01",
"02", "03"}` con etiquetas IVA/IEPS/Exento, que no es ese catálogo:

```
TipoOperacion='06' -> valid=False    ← clave real del SAT, rechazada
TipoOperacion='85' -> valid=False    ← la más común de las tres, rechazada
TipoOperacion='01' -> valid=True     ← clave inventada, aceptada
```

Y el docstring del módulo (`diot_validator.py:10-22`) declara una estructura
`<DIOT><Operacion>` como «SAT XML structure expected». La DIOT no se presenta en
ese XML.

Consecuencia: el módulo que dice «validates DIOT XML files against SAT
requirements» valida contra requisitos que no son los del SAT. Un despacho que
confíe en el «válido» presenta un archivo que la autoridad no acepta, o corrige
claves correctas por incorrectas porque la herramienta se las marcó mal.

Causa raíz probable: los catálogos se escribieron de memoria en vez de
descargarse; el propio archivo lo admite en `catalogs.py:8-11` («Marcado como ?
INFERIDO») pero las funciones `is_valid_*` se usan igual para **reprobar** un
CFDI.


## [17] likida-ai-enterprise · Cumplimiento fiscal
### `validate_cfdi` devuelve `ok=True` y «12/12 checks» sobre un XML al que le faltan todos los requisitos del CFF 29-A
`b2b_ai/cfdi/validator.py:165-194` (las cinco ramas `else: _ok(...)`)

Escenario (ejecutado): un `<cfdi:Comprobante>` **sin** `TipoDeComprobante`, sin
`MetodoPago`, sin `FormaPago`, sin `UsoCFDI`, sin `RegimenFiscal` del emisor, sin
`Sello`, sin `NoCertificado` y sin `TimbreFiscalDigital` →

```
ok=True   checks={'pass': 12, 'fail': 0}
```

El patrón `if campo and not es_valido(campo): _fail(...) else: _ok(...)` trata el
campo **ausente** como aprobado, y encima le suma uno al contador de aciertos. Las
cinco validaciones de catálogo fallan abiertas. Los cinco atributos son
obligatorios en el Anexo 20 y sus equivalentes son requisitos del CFF art. 29-A.

Consecuencia: el despacho ve «válido, 12 de 12» sobre un documento que ni siquiera
está timbrado, lo clasifica y lo asienta como gasto deducible. El comprobante no
ampara la deducción ni el acreditamiento (CFF 29-A último párrafo), y eso se
descubre en la revisión, no antes.

Causa raíz probable: se confundió «no aplica» con «cumple»; no hay una lista de
campos obligatorios separada de la validación de contenido.


## [18] likida-ai-enterprise · Cumplimiento fiscal
### Ningún camino verifica el 69-B ni el estatus de cancelación antes de asentar la póliza
`b2b_ai/services/pipeline.py:63-101`; `b2b_ai/sat/validator.py:47-72`; cero referencias a 69-B en todo el código

Esto responde las dos preguntas del encargo, y las dos respuestas son «sí, existe
ese camino».

**EFOS (69-B).** `command grep -rn -E "69-B|69B|EFOS|EDOS" --include="*.py" .`
devuelve **cero** coincidencias en código. No hay lista, ni descarga, ni bandera,
ni consulta. Un CFDI emitido por un contribuyente en la lista **definitiva** del
art. 69-B del CFF entra por `parse_cfdi`, sale `ok=True` de `validate_cfdi`, se
clasifica, se registra en la póliza del ERP (`pipeline.py:89`) y se anota como
`iva_acreditable` en la línea de DIOT (`validator.py:236-245`). Las operaciones
amparadas por esos comprobantes **no producen efecto fiscal alguno** salvo que se
acredite la materialidad: la deducción y el acreditamiento son inexistentes.

**Cancelado.** `SATValidator` sólo lo usan `sat/api.py:108` y `sat/scheduler.py:121`.
**`pipeline.py` nunca lo llama**: el flujo es
`parse_cfdi → validate_cfdi → detect_pii → classify → detect_anomalies →
evaluate_approval → register_erp → insert_invoice`, sin una sola consulta de
estatus. Y cuando sí se llama, `check_status` es un mock que decide por el último
carácter del UUID (`sat/validator.py:63`): «folios que terminan en '0' →
cancelado». Sobre UUIDs hexadecimales eso declara **vigente ~15 de cada 16
comprobantes cancelados** y grita «Factura cancelada detectada (SAT)» por correo
(`sat/scheduler.py:144`) sobre facturas vigentes cuyo UUID acabe en 0. En el mismo
archivo, `verify_rfc` (`:105`) reporta `registrado=True` para cualquier RFC que no
empiece con XAXX — un RFC inventado con formato correcto sale «registrado».

Consecuencia: un CFDI cancelado por el emisor sigue soportando una deducción y un
IVA acreditable en la contabilidad que el despacho presenta. Con EFOS, además de
la corrección, el riesgo es el del art. 69-B tercer párrafo para el receptor.

Causa raíz probable: la verificación ante el SAT se diseñó como un módulo aparte,
mock-first, y nunca se conectó al pipeline que produce el efecto fiscal.


## [19] likida-ai-enterprise · Cumplimiento legal
### El aviso de privacidad no existe para el titular — solo en el repo
`landing/index.html:894`, `docs/legal/PRIVACY-POLICY.md` (documento completo, nunca enlazado ni servido)
Escenario: un visitante entra a `landing/index.html`, ve la tarjeta "LFPDPPP" que dice literalmente *"Cumplimiento total de la Ley Federal de Protección de Datos Personales en Posesión de los Particulares. Aviso de privacidad incluido."* (línea 894) y busca el aviso — no hay ningún `<a href>` hacia él en `landing/index.html` ni en `landing-b/` (confirmado por grep de `href=` contra "privac|legal|terms"), y ninguna ruta de `b2b_ai/api/*.py` ni `b2b_ai/portal/routes.py` sirve `docs/legal/PRIVACY-POLICY.md` como página web (confirmado por grep de `PRIVACY-POLICY|privacy-policy|/legal/` contra las rutas). El documento real vive solo como Markdown en `docs/legal/`, con `RFC: [PENDIENTE — completar con RFC legal de la empresa]` sin rellenar (línea 6), y el formulario de contacto de la landing (`landing/index.html:995-1028`) no tiene checkbox de aceptación de aviso ni enlace a él.
Consecuencia: la afirmación "Aviso de privacidad incluido" es falsa tal como se despliega hoy. Cualquier dato que entre por el formulario de contacto, por el registro del portal o por la carga de documentos se recaba sin que el titular haya tenido oportunidad de leer el aviso — el requisito more básico de la LFPDPPP (que el aviso esté "a su disposición" antes o al momento de la recolección) no se cumple. Para el despacho cliente esto es una responsabilidad heredada: si el titular de un dato de un CFDI reclama, Likida no puede probar que hubo aviso.
Causa raíz probable: el documento se redactó pero nunca se conectó a ninguna ruta ni a la landing.


## [20] likida-ai-enterprise · Cumplimiento legal
### Datos de nómina de un tercero (no del Cliente) viajan sin filtrar a un LLM externo
`b2b_ai/agent/loop.py:156`, `b2b_ai/cfdi/parser.py:250-267`, `b2b_ai/services/llm.py:69-88,222-226`
Escenario: el pipeline procesa un CFDI tipo nómina. `cfdi/parser.py:250-267` extrae del complemento Nomina el `curp`, `num_empleado`, `salario_diario` (SBC) y `total_percepciones`/`total_deducciones` del trabajador y los mete en `datos["nomina"]`. Ese `datos` completo — sin quitar el sub-dict `nomina` — se pasa tal cual a `self.llm.classify_invoice(datos)` en `agent/loop.py:156`. Dentro de `llm.py`, `_sanitize_payload()` (líneas 69-88) recorre dicts anidados y los deja pasar — solo trunca longitud y quita tags XML, no redacta CURP ni salario — y `_render_prompt` (líneas 222-226) serializa ese payload completo dentro del `[DATOS]...[/DATOS]` del prompt `user`. Si el tenant tiene `B2B_LLM_PROVIDER=openai|anthropic|deepseek|openrouter` configurado (los cuatro proveedores reales existen en el mismo archivo, líneas 356-573), ese prompt —con CURP, salario y percepciones/deducciones de un trabajador real— sale por HTTP hacia la API de un tercero fuera de México.
Consecuencia: el titular de esos datos no es "el Cliente" (el despacho, que sí firmó el ToS) sino el trabajador del cliente del despacho — un tercero que nunca vio ni el ToS ni el aviso de privacidad de Likida. `PRIVACY-POLICY.md §4.1` (líneas 81-87) solo contempla transferencias a "proveedores de infraestructura tecnológica (cloud providers)" para "la operación de la Plataforma" — no nombra ni contempla el envío de datos de nómina a un proveedor de modelos de lenguaje para clasificación. Es una transferencia de datos personales sin base ni cobertura, del tipo que el propio rubro marca como techo de 3/10.
Causa raíz probable: `classify_invoice` recibe el `datos` completo del parser en vez de una vista filtrada por tipo de comprobante (el `tipo == "N"` ya se distingue en otras partes del código, p. ej. `services/llm.py:604-605`, pero no se usa para excluir el sub-dict `nomina` antes de mandarlo al LLM).

## Hallazgos adicionales


## [21] likida-ai-enterprise · Arquitectura
### Dos calculadoras de ISR montadas en la misma app dan resultados distintos para el mismo salario
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


## [22] likida-ai-enterprise · Arquitectura
### El backend Postgres no puede inicializarse hoy — dos cabezas de Alembic, no los 3 bugs ya documentados
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


## [23] likida-ai-enterprise · Arquitectura
### `/api/v2/analytics`, `/api/v2/audit` y `/api/v2/export` truenan en cualquier despliegue con Postgres — tercera capa de conexión, hardcodeada a SQLite
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


## [24] likida-ai-enterprise · Modelo de datos
### `alembic upgrade head` no resuelve: dos heads desde 0004, y `Database._pg_migrate()` lo corre en cada arranque contra Postgres
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


## [25] likida-ai-enterprise · Modelo de datos
### Las tablas `billing_*` no existen en ningún archivo de Alembic — solo en el esquema SQLite
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


## [26] likida-ai-enterprise · Modelo de datos
### `with self.conn:` libera la conexión de Postgres al pool, pero `Database` sigue usando la misma referencia cacheada — riesgo de dos peticiones compartiendo el mismo socket
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


## [27] likida-ai-enterprise · Operabilidad y DX
### El camino Railway+Postgres de DEPLOY-GUIDE.md nunca toca Postgres — pérdida silenciosa de datos en cada redeploy
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


## [28] likida-ai-enterprise · Operabilidad y DX
### Aun corrigiendo lo anterior, la API muere al arrancar contra Postgres real por migraciones con dos heads
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


## [29] likida-ai-enterprise · Operabilidad y DX
### `/health` y `/health/detailed` mienten sobre el backend de base de datos
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


## [30] likida-ai-enterprise · Rendimiento y costo
### El pool de conexiones de `db/pool.py` es SQLite-only pero se conecta con el DSN de Postgres en el despliegue que recomienda el propio DEPLOY-GUIDE
`b2b_ai/db/pool.py:53-58` (`ConnectionPool._open`), instanciado en `b2b_ai/api/v2.py:182` (`pool = ConnectionPool(db.path, size=4)`)

Escenario: en producción (Railway, según `DEPLOY-GUIDE.md`, que es exactamente lo que el punto 1 del MAPA ya marcó como pendiente), `B2B_DB_URL` es un DSN `postgresql://user:pass@host:5432/dbname`. La clase `Database` sí distingue Postgres de SQLite (`_is_postgres`, `db/db.py:33-36`) y usa el pool correcto (`PGPool`/`psycopg_pool`, con tamaño configurable por `B2B_PG_POOL_MIN`/`MAX`). Pero `build_v2_router` construye un **segundo pool, distinto y sin esa lógica**: `ConnectionPool(db.path, size=4)` pasa el mismo DSN a una clase que en `_open()` llama `sqlite3.connect(self.db_path, ...)` sin condicional alguno. Verifiqué el comportamiento exacto en un sandbox aislado (no toqué el repo): `sqlite3.connect("postgresql://user:pass@host:5432/dbname")` lanza `sqlite3.OperationalError: unable to open database file` — no crea nada, no falla en silencio, simplemente revienta.

Como el pool abre conexiones de forma perezosa (`_acquire_raw`, línea 60-68), esto no truena al arrancar la app: truena la **primera vez** que alguien pega a uno de los tres endpoints que usan `pool.run(...)`: `GET /api/v2/analytics` (línea 356-360), `GET /api/v2/audit` (línea 417-420) y `POST /api/v2/export` (línea 441-447). Con Postgres en producción, esos tres endpoints — parte del pitch "enterprise" del producto — devuelven 500 el 100% de las veces, para el 100% de los tenants, sin excepción.

Consecuencia: si el contralor pide ver analytics, auditoría o exportar un CSV mientras el backend corre contra Postgres (que es la configuración que el propio repo recomienda para producción), la demo se cae ahí mismo. Y como toda la suite de 4900+ pruebas corre contra SQLite (confirmado en MAPA punto 1), nada en CI puede detectar esto.

Causa raíz probable: `v2.py` se escribió asumiendo SQLite y reimplementó un pool en vez de reusar la conexión ya pooleada de `db.conn`/`Database`.


## [31] likida-ai-enterprise · Rendimiento y costo
### `_pass_ai` hace una llamada al LLM por cada par (factura, movimiento bancario) dentro de un GET que recalcula por defecto
`b2b_ai/services/bank_reconciliation.py:417-436` (`_pass_ai`), llamando a `_ai_confidence` en la línea 427, que en la línea 445 hace `self.llm.classify_invoice(...)`. Disparado desde `b2b_ai/api/reconciliation.py:140-152` (`GET /api/v1/reconciliation/matches`, con `refresh: bool = Query(default=True)` — se recalcula SIEMPRE salvo que el cliente pase `refresh=false` explícitamente) y desde `b2b_ai/api/reconciliation.py:178-198` (`GET /api/v1/reconciliation/report`, que llama `svc.auto_match()` incondicionalmente en la línea 195, sin parámetro para evitarlo).

Escenario con valores: un despacho con 200 facturas sin conciliar y un estado de cuenta con 150 movimientos sin conciliar (tras los pases `_pass_exact`/`_pass_partial`, que sí filtran antes de llegar aquí — ese diseño está bien y reduce N y M). `_pass_ai` itera 200 × 150 = 30,000 pares, y por cada uno intenta una llamada de red real al proveedor LLM configurado (`_http_post_json`, timeout de 15s por llamada). Con `B2B_LLM_MAX_CALLS` por default en 100 (`llm.py:128`), las primeras ~100 llamadas sí salen a red — a ritmo conservador de 1-2s cada una, son 100-200 segundos solo en esas, casi seguro por encima del timeout típico de un load balancer/reverse proxy (30-60s) — y las ~29,900 restantes fallan instantáneamente contra el presupuesto agotado (ver hallazgo siguiente), cayendo al overlap de tokens. El request de `GET /matches` (una acción tan cotidiana como refrescar un dashboard, sin ningún job asíncrono como sí existe para `/api/v2/batch`) no tiene forma de completarse dentro de un tiempo razonable con un volumen realista de un despacho activo.

Consecuencia: si el contralor sube un estado de cuenta con más de unas pocas decenas de movimientos pendientes durante la demo y pide ver los cruces, la pantalla se queda cargando indefinidamente. Es exactamente el "el demo se cae" que define un CRÍTICO en este rubro. Además, cada una de esas llamadas cuesta dinero real por lo que ya es información redundante: la misma función ya calcula `tok_conf` (overlap de tokens, gratis) y lo combina con `max()` — el LLM añade poco valor marginal a cambio de mucho costo y tiempo.

Causa raíz probable: falta un límite superior al tamaño de `invoices × stmt` antes de decidir usar LLM, y falta el patrón asíncrono (job + polling) que `/api/v2/batch` sí implementa.


## [32] likida-ai-enterprise · Sistema agéntico
### El pipeline de producción registra póliza de un CFDI que falló la validación fiscal, y no avisa a nadie
`b2b_ai/services/pipeline.py:66-101` (validación en 66, registro en 88-90, sin
portón entre las dos) · `b2b_ai/services/pipeline.py:106`

Escenario — ejecutado, no inferido. Tomé `fixtures/cfdis/01_gasto_operativo_papeleria.xml`,
le cambié el total a `Total="99999.00"` y lo pasé por `process_file`:

```
valido: False
issues: ['Suma de conceptos 1000.00 != SubTotal 99999.00',
         'SubTotal + IVA − Descuento − Retenciones = 100159.00 pero Total=1160.00']
aprobacion: auto_approved
ERP: {"ok": true, "poliza": "POL-487BCFCD3F",
      "cuenta_cargo": "6131 Gastos generales", "cuenta_abono": "1130 Bancos",
      "status": "registrada"}
notificacion: {'status': 'skipped'}
fila en DB -> status: procesado | erp_status: registrada | valido: 0
reviews pendientes: 0
```

`process_file` nunca consulta `validacion["ok"]` antes de `register_erp`. El
único portón es `evaluate_approval`, que solo mira el monto y si es comprobante
de pago. Y como la notificación está dentro de `if validacion.get("ok"):`
(línea 106), la factura inválida **es la única que no genera ningún aviso**: se
registra en silencio absoluto. La plantilla `invoice_rejected` —"No se registró
en el ERP. Se requiere revisión humana"— existe (`notifications/templates/__init__.py:34-42`)
y el pipeline nunca la dispara; solo la usa `agent/loop.py:145`, que sí corta.

Consecuencia: el despacho deduce un gasto amparado por un CFDI aritméticamente
inconsistente, con póliza contra 6131/1130, y no hay correo, ni fila en
`reviews`, ni bandera en la UI que lo delate. El contador se entera en la
revisión del SAT.

Causa raíz probable: `agent/loop.py` (que sí corta en inválida, línea 137-152)
y `services/pipeline.py` se escribieron como dos árboles de decisión
independientes; el que quedó cableado a la API es el que no heredó el portón.


## [33] likida-ai-enterprise · Sistema agéntico
### La factura retenida por aprobación se guarda como "procesado" y al despacho se le escribe que fue "registrada en el ERP"
`b2b_ai/services/pipeline.py:88-101` · `b2b_ai/db/db.py:266` ·
`b2b_ai/notifications/templates/__init__.py:12-24` · `b2b_ai/tools/tools.py:211-213`

Escenario — ejecutado. CFDI válido de **$290,000** (arriba del umbral de
$50,000 de `services/approval.py:33`):

```
aprobacion: requires_approval | efirma: True
notif de aprobacion: {'status': 'queued', 'channel': 'none', ...}
erp: pending_approval | poliza: None
FILA DB -> status: procesado | erp_status: 'pending_approval' | erp_poliza: None
reviews pendientes: 0
notificacion al despacho: subject 'Factura e912bc6b-cf2 procesada y registrada'
```

Tres cosas rompen a la vez:

1. `db.insert_invoice` escribe `"status": "procesado"` como literal
   (`db/db.py:266`), sin mirar el `erp_status`. El comentario de
   `api/portal.py:287` afirma que la columna vale "procesado / pending_approval":
   nunca vale lo segundo, así que el filtro `?estado=pending_approval` del
   portal devuelve cero para siempre.
2. `tools.py:211-213` construye un `ApprovalManager` nuevo **sin notifier** en
   cada llamada, así que `_notify_approval` devuelve `{"status":"queued",
   "channel":"none"}` — nadie recibe nada — y la bitácora `self.decisions` vive
   en un objeto que se descarta en la misma línea.
3. El correo que sí sale usa la plantilla `invoice_processed`, cuyo cuerpo dice
   textualmente *"fue procesada, validada y **registrada en el ERP**"*, para una
   factura sin póliza.

Consecuencia: $290,000 quedan sin asiento contable mientras el contralor tiene
por escrito que se registró. La cola de pendientes de aprobación no existe en
ninguna tabla, ningún endpoint y ninguna pantalla: el estado solo vive en la
columna `erp_status`, que la UI no filtra. Es exactamente el estado donde la
base dice una cosa y el humano cree otra.

Causa raíz probable: el gate de aprobación se diseñó como función pura
(`services/approval.py`) y nunca se le dio persistencia ni destinatario; el
pipeline consume su veredicto pero no lo materializa.


## [34] likida-ai-enterprise · Sistema agéntico
### Reprocesar el mismo CFDI dispara una póliza nueva cada vez; la base se queda con la primera y devuelve éxito
`b2b_ai/services/pipeline.py:89-101` · `b2b_ai/db/db.py:286-297` ·
`b2b_ai/erp/contpaqi.py:36`

Escenario — ejecutado. El mismo archivo por `process_file` dos veces seguidas
(mismo `folio_fiscal`, mismo tenant):

```
A1 poliza: POL-ED120A5465  insertado: False  invoice_id: 1
A2 poliza: POL-1EDB1034C1  insertado: False  invoice_id: 1
fila en DB -> erp_poliza: POL-487BCFCD3F   (las otras dos no quedaron en ningún lado)
```

El orden es `register_erp` → `insert_invoice`. El ERP es un efecto externo sin
llave de idempotencia (`contpaqi.py:36` genera `"POL-" + uuid4().hex[:10]` en
cada llamada), y el dedup vive solo del lado de la base: `insert_invoice`
atrapa el `IntegrityError` por `folio_fiscal`, devuelve la fila existente con
`inserted=False` y **no actualiza `erp_poliza` ni `erp_status`**. Ni el portal
ni v2 tratan `insertado: False` como error — el portal responde "Procesado
correctamente." (`api/portal.py:371`).

Este no es un caso de laboratorio: el webhook de email
(`api/webhooks.py:252-265`) procesa síncronamente dentro del request, y los
proveedores de correo reintentan la entrega ante timeout; el portal reintenta
por acción del usuario. Con el driver real de CONTPAQi conectado, cada
reintento es una póliza duplicada — doble deducción del mismo CFDI.

Además, si el proceso muere **entre** `register_erp` y `insert_invoice` (líneas
89-101 del pipeline, 191-193 de `loop.py`), el ERP queda con póliza y la base
sin fila: el reintento no encuentra nada que lo detenga y registra otra vez.

Causa raíz probable: el efecto externo se ejecuta antes que el registro local y
nadie posee la llave de idempotencia; el dedup se delegó a un constraint de la
base que corre después del efecto.


## [35] likida-ai-enterprise · Sistema agéntico
### El portón de confianza de la clasificación no se puede disparar: la evidencia de la categoría rival sube la confianza del ganador
`b2b_ai/services/classify.py:95-98`

```python
n_matches = sum(len(m) for m in matched.values())   # ← suma TODAS las categorías
confianza = min(0.98, 0.55 + 0.20 * n_matches)
requires = confianza < 0.70 or best_cat == "desconocido"
```

Escenario — ejecutado:

| descripción del concepto | salida |
|---|---|
| `"renta de laptop"` | `activo_fijo`, **confianza 0.95**, `requires_human_review: False` |
| `"Servicio de consultoria y mantenimiento"` | `inversion`, **confianza 0.95**, `requires_human_review: False` |
| `"papeleria"` | `gasto_operativo`, confianza 0.75, `requires_human_review: False` |

"renta de laptop" empata 1-1 entre `gasto_operativo` (*renta*) y `activo_fijo`
(*laptop*); gana `activo_fijo` por el orden fijo de `PRIORITY` (línea 39), y la
palabra que apoyaba a la categoría perdedora **sube la confianza del ganador a
0.95**. La `razon` que ve el contador dice solo `"Coincidencias: laptop"`: el
empate es invisible.

El portón es matemáticamente inalcanzable: si `best_score > 0` entonces
`n_matches >= 1`, luego `confianza >= 0.75 > 0.70`, luego `requires` es
siempre `False`. La única forma de que `requires_human_review` sea `True` es el
retorno temprano de `desconocido` (línea 91-93), es decir, cero coincidencias.
Dicho de otro modo: **el clasificador de reglas nunca escala por baja
confianza**; solo escala cuando no entiende nada.

Consecuencia: `activo_fijo` manda la póliza a `1210 Mobiliario y equipo`
(`erp/contpaqi.py:73`) y el gasto se deprecia en vez de deducirse en el
ejercicio. El README promete "el pipeline corre 100% con reglas" para lo
crítico y "el LLM propone, la decisión fiscal es humana"; la primera mitad se
cumple, la segunda no: la propuesta se convierte en póliza sin que ningún
humano la vea, porque la señal que debía convocarlo está apagada por
aritmética.

Causa raíz probable: `n_matches` debía contar las coincidencias de la categoría
ganadora y cuenta las de todas; el empate entre categorías, que es la señal más
fuerte de ambigüedad, se convirtió en evidencia a favor.


## [36] likida-ai-enterprise · Pruebas
### La tasa de cuota IMSS del trabajador puede estar mal por un factor de 4× y las 441 pruebas de nómina siguen verdes
`b2b_ai/services/payroll.py:41` (`RATES["imss_trabajador_eym"]`), consumida en `calc_imss` (`payroll.py:110-125`, uso en línea 117).
Escenario: con el valor real `Decimal("0.01125")` un trabajador con SBC=$1000 paga $11.25 de EyM. Cambié la constante a `Decimal("0.05")` (4.4× el valor real) y corrí las 441 pruebas de `test_payroll.py`, `services/test_payroll.py`, `test_services_coverage.py`, `test_nomina.py` y `test_nomina_completa.py`: **las 441 pasaron**. Las pruebas que tocan `calc_imss` (`services/test_payroll.py:46-58`, `test_payroll.py:27-30`, `test_services_coverage.py:444-448`) solo verifican `total > 0` y `total == eym + rcva` — una consistencia interna con la propia fórmula, no un valor ancla contra la ley (LSS). Cualquier cambio a la tasa, en cualquier dirección, pasa igual.
Consecuencia: si alguien (agente o humano) toca esa constante por error — o si cambia el año fiscal y alguien copia mal el valor — la nómina real del despacho retiene de más o de menos al trabajador y nadie lo nota hasta que el trabajador o el IMSS lo reclamen. Es dinero de un tercero (el empleado), no del despacho.
Causa raíz probable: las pruebas de IMSS verifican la forma del resultado (`eym + rcva == total`), no el valor esperado contra un caso de la ley.


## [37] likida-ai-enterprise · Pruebas
### La tasa general de IVA usada para validar CFDI puede estar a la mitad de su valor legal y las 552 pruebas del validador siguen verdes
`b2b_ai/cfdi/validator.py:30` (`IVA_TASA_GENERAL = Decimal("0.16")`), usada en la línea 144 dentro de `validate_cfdi`.
Escenario: cambié la constante a `Decimal("0.08")` (la mitad) y corrí las 552 pruebas que tocan `cfdi`/`validator`/`validate` en todo `tests/`: **las 552 pasaron**. La razón estructural: el chequeo de IVA global (`validator.py:142-150`) solo agrega un *warning* (`warnings.append(...)`), nunca marca `ok=False` ni incrementa `checks["fail"]`. Ninguna prueba en el repo compara el valor numérico exacto de `esperado` contra el 16% real — `test_iva_global_mismatch` (`tests/test_cfdi_coverage.py:521-525`) solo verifica que *algún* warning con el texto "IVA global" aparezca, y con la tasa mutada a 8% ese warning también dispara (por una razón distinta), así que la prueba no distingue entre "la tasa está mal" y "el warning existe".
Consecuencia: un CFDI de ingreso con IVA facturado al 16% legítimo generaría un warning falso (o uno real se dejaría de generar), y como es solo warning, el campo `ok` del validador seguiría en `True`. El despacho podría reportar coherencia fiscal falsa en un CFDI cuyo IVA no cuadra con la tasa real, sin que la suite ni el flujo de aprobación lo detecten (el warning no bloquea nada en `pipeline.py`).
Causa raíz probable: la comparación contra `IVA_TASA_GENERAL` es un *warning*, no un *fail*, y ninguna prueba ancla el valor numérico esperado a la tasa legal real.


## [38] likida-ai-enterprise · Pruebas
### El Total del XML de nómina (CFDI que se manda a timbrar) puede omitir las deducciones sin que ninguna prueba lo note
`b2b_ai/services/payroll.py:359` (`Total="{_fmt(_round2(total - total_ded))}"` dentro de `generate_payroll_cfdi`).
Escenario: cambié el atributo `Total` del `cfdi:Comprobante` para que fuera igual a `SubTotal` (ignorando `TotalDeducciones`, es decir, ISR+IMSS+INFONAVIT no se restan del monto reportado como Total). Corrí las dos únicas pruebas que ejercitan `generate_payroll_cfdi` (`tests/test_payroll.py:80-91` y `tests/test_services_coverage.py:524-532`): **ambas pasaron**. Ambas pruebas solo verifican presencia de subcadenas (`"Comprobante" in xml`, `"TotalDeducciones" in xml`, el RFC del empleado en el string) — ninguna parsea el XML y compara el atributo `Total` contra `SubTotal − TotalDeducciones`.
Consecuencia: el CFDI de nómina es el documento que un PAC timbraría y el SAT recibiría. Un `Total` que no descuenta ISR/IMSS/INFONAVIT es una inconsistencia fiscal visible para cualquier contador o para el propio SAT en la validación del complemento de Nómina 1.2, y el repo la generaría sin aviso.
Causa raíz probable: las únicas dos pruebas de esta función verifican forma (tags presentes), no aritmética del documento generado.


## [39] likida-ai-enterprise · Tool calling
### `register_erp` duplica el asiento contable en cada reproceso — verificado en vivo contra `CSVErp`
`b2b_ai/erp/csv_erp.py:44-63` (`register_invoice`), `b2b_ai/erp/csv_erp.py:65-68`
(`get_invoice`, existe y no se usa), `b2b_ai/agent/loop.py:224-229` (`_register`),
`b2b_ai/services/pipeline.py:85-101` (orden: `evaluate_approval` → `register_erp`
→ `db.insert_invoice`)

Escenario: entra la misma factura (folio `AAAA1111-DEMO`, total $50,000.00) dos
veces al pipeline — por un reintento tras un fallo aguas abajo, por correr
`POST /process?folder=...` o `python -m b2b_ai.cli batch` dos veces sobre la
misma carpeta (nada marca los archivos como ya procesados y los quita), o por
un reenvío del mismo CFDI vía webhook. Lo reproduje contra el código real
(`CSVErp`, el backend documentado como "Producción (fallback)" en
`docs/developer-guide.md:311`, no un mock):

```
1er registro: CSV-044CB25C  ok=True
2o  registro: CSV-9E555181  ok=True   (mismo folio, mismo monto)
filas en erp_export.csv para AAAA1111-DEMO: 2
```

`register_invoice()` nunca consulta `self._rows` ni llama a su propio método
`get_invoice(folio_fiscal)` — que existe exactamente para esto — antes de
anexar la fila. Cada llamada genera un `poliza_id` nuevo (UUID) y lo persiste.
`MockCONTPAQi.register_invoice()` (`b2b_ai/erp/contpaqi.py:27-52`) tiene el
mismo hueco. La única defensa contra duplicados vive en
`db.insert_invoice()` (constraint `UNIQUE(tenant_id, folio_fiscal)`,
`b2b_ai/db/db.py:269-296`) — pero esa verificación corre **después** de
`register_erp` en ambos caminos de producción (`pipeline.py:88-101`,
`agent/loop.py` vía `_register()` llamado en las líneas 175 y 191 de
`process()`), así que solo evita la segunda fila en SQLite. La fila
duplicada en `erp_export.csv` — el archivo que el despacho importa a su
contabilidad real — ya existe, y `insert_invoice` devuelve el `invoice_id`
viejo sin siquiera reportar el nuevo `poliza_id` generado en el segundo
intento, así que ni el propio sistema se entera de la divergencia.

Consecuencia: el despacho contable termina con un gasto de $50,000
deducido/registrado dos veces en su contabilidad real (dos pólizas por la
misma factura), sin ninguna alerta, y sin que la tabla `invoices` de B2B AI
lo refleje — quien reconcilie contra `erp_export.csv` encuentra el
desfase, quien confíe en el dashboard de B2B AI no lo ve. Es exactamente el
patrón que la propia suite de tests documenta pero no cubre:
`tests/test_erp.py:53-60` (`test_csv_erp_accumula`) prueba que dos folios
**distintos** se acumulan correctamente, pero no existe ningún test que
llame `register_invoice()` dos veces con el **mismo** folio.

Causa raíz probable: `register_erp` se diseñó como operación "crear", nunca
como "crear-si-no-existe", y el pipeline nunca consulta el estado ya
persistido antes de invocarla.


## [40] likida-ai-enterprise · Frontend
### El landing vende "computer use sobre tu ERP" con checkmarks; el código es un mock sin driver real
`landing/index.html:759`, `landing/index.html:787-793`, `landing-b/index.html:1` (feature "Computer use sobre tu ERP", hero-note "Computer use sobre tu ERP actual", marquee con CONTPAQi/SAP/Odoo), `README.md:295-296`, `b2b_ai/computer_use/browser.py:83,227`

Escenario: el contralor lee en el landing "Navega, hace login y sube/extrae CFDI
de cualquier ERP web — sin integraciones API frágiles" junto a una lista de
integraciones con ✓ verde para CONTPAQi, Aspel, QuickBooks y Xero
(`landing/index.html:789-792`). Pide ver una conexión en vivo contra su
CONTPAQi real → `computer_use/browser.py:83` sólo tiene `MockBrowser`, una
simulación en memoria; el propio `README.md:295-296` dice explícitamente
"Qué NO cubre esto: conexión real a CONTPAQi/contaDIGITAL, driver real de
computer use (Playwright/vision)". No hay ningún camino de código que cumpla
lo que el landing promete.

Consecuencia: el contralor o el socio del despacho descubre en la sala que la
funcionalidad central anunciada con checkmarks no existe. Esto no es un typo:
es la promesa de producto más visible de la página, repetida en ambos landings
(`landing-b/index.html:1` tiene la misma frase y el mismo marquee de ERPs).

Causa raíz probable: el copy del landing se escribió para el estado final del
producto, no para el estado actual (mock), y nadie lo revisó contra
`README.md` antes de publicar.


## [41] likida-ai-enterprise · Frontend
### Landing B tiene testimonio inventado y "56%" repetido sin fuente — vivo en un target de despliegue real, no un borrador
`landing-b/index.html:1` (title, meta description, og:description, twitter:description ×2, hero-stat "56% · menos tiempo en captura"), `landing-b/index.html:18` (blockquote + "— Socio de despacho contable, plan Pro")

Escenario: en `landing/index.html` este mismo problema (documentado antes de
esta ronda) ya se corrigió — el commit `18660c7` ("simplify landing markup",
hoy) quitó el testimonio y el "56%". Pero **nadie tocó `landing-b/index.html`**,
que sigue teniendo el testimonio con atribución falsa (no hay clientes reales,
ver `docs/auditoria-1/MAPA.md` y el hecho de que el proyecto es pre-revenue) y
la cifra "56% menos tiempo en captura" repetida **seis veces** en la misma
página (title, meta description, og:description, twitter:description dos
veces, y el stat destacado del hero) sin una sola nota, footnote o metodología
que la respalde. `landing-b/` no es un experimento descartado: `DEPLOY.md:15`
lo documenta como "Landing alternativa... Vercel/Netlify (static,
standalone)" con su propio `vercel.json` y `netlify.toml` listos para
desplegar tal cual.

Consecuencia: si se despliega o se comparte Landing B — el propio repo lo deja
listo para eso — un prospecto ve un testimonio de un cliente que no existe y
una cifra de ahorro sin ninguna base, exactamente el patrón que ya se sabía
que estaba mal en la otra landing y se corrigió ahí pero no aquí.

Causa raíz probable: el fix de hoy (`18660c7`) se aplicó a un solo archivo
(`landing/index.html`) sin buscar el mismo texto en `landing-b/index.html`.
