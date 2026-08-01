# Seguridad — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa). Razón: es la primera medición, no hay
movimiento que justificar. El ancla del rubro dice *"4 o menos si existe un
camino de acceso sin autenticar a datos de un tenant"*: aquí hay **tres**
caminos distintos, dos de ellos sin credencial alguna, y los tres verificados
ejecutando el código. No baja de 3 porque el rubro sí está atendido — el JWT
falla al arrancar sin secreto, las API keys y las sesiones del portal se guardan
hasheadas, bcrypt está en 12 rondas, hay guardarraíl de path traversal en
`/api/v1`, cabeceras de seguridad y consultas parametrizadas de punta a punta.
El problema no es ausencia de defensas: es que **las defensas se cablearon en
una puerta y no en la de al lado**.

Riesgo mayor hoy: cualquiera con la URL puede volverse admin de un despacho
ajeno con una sola petición sin token, porque el "bootstrap del primer usuario"
mira la tabla `client_users` y el onboarding escribe en `users`.

---

## Contexto de la corrida

El árbol se movió: el commit base del MAPA es `f4944ab`, el `HEAD` durante esta
auditoría fue `bac6e12` (dos commits después, más 14 archivos de
`integrations/` modificados sin commitear). Nada de lo que reporto vive en esos
archivos.

**Verificación del P1 "cerrado" del JWT — confirmado cerrado.**
`command grep -rn "dev-jwt-secret\|_DEV_SECRET" b2b_ai/` devuelve una sola
línea, y es un comentario: `b2b_ai/auth/middleware.py:51`. No hay literal.
`jwt_secret()` (`middleware.py:80-103`) exige ≥32 caracteres, lanza si falta y
`B2B_ENV` no está en la lista de dev, y `check_jwt_config()` se llama desde
`create_app` (`api/app.py:435`), así que el fallo es en el arranque. El
tratamiento de `B2B_ENV` sin definir como producción es la decisión correcta y
está argumentada en el código. **No es reincidente.**

Todo lo que sigue se ejecutó con el intérprete del repo (`.venv/bin/python`) y
`TestClient`, sin tocar ningún archivo del repo ni salir a la red. Los scripts
quedaron fuera del repo, en el scratchpad de la sesión.

---

## Hallazgos

### [CRÍTICO] Un desconocido se vuelve admin de cualquier despacho con una petición sin token
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

---

### [CRÍTICO] `/api/v2/batch` lee cualquier archivo del disco del servidor y lo importa al tenant del atacante
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

---

### [CRÍTICO] Nómina y pre-auditoría están montadas sin ninguna credencial, con el `tenant_id` puesto por el cliente
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

---

### [CRÍTICO] La firma del webhook de pago no protege nada, y el atacante elige qué secreto se verifica
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

---

### [ALTO] La capa de datos marca facturas de cobro como pagadas sin filtrar por tenant
`b2b_ai/db/db.py:482-494` · llamada desde `b2b_ai/billing/api.py:209-211`

```sql
UPDATE billing_invoices SET status='paid', paid_at=?
WHERE provider_invoice_id=? AND provider=?
```

Sin `tenant_id`. Es la única escritura de `billing_invoices` sin scope de
tenant en todo `db.py`. Verificado en vivo: una factura de 49,900 MXN del
tenant 1 pasó de `open` a `paid` con una llamada que no menciona al tenant 1.

Escenario: el tenant 2, con su clave legítima, manda un webhook con
`data.object.id = "in_FACTURA_VICTIMA"` (la referencia del proveedor viaja en
correos de Stripe, PDFs de factura y el portal del cliente) y liquida la deuda
del tenant 1.

Consecuencia: cobranza silenciosamente equivocada. Nadie se entera hasta la
conciliación de fin de mes, si es que se hace. Falla silenciosa con efecto en
dinero.

Causa raíz probable: la firma del método no pide `tenant_id` y el llamador no
lo tiene a mano en el objeto del webhook; se resolvió omitiéndolo.

---

### [ALTO] Un tenant se sube su propio límite de tasa y apaga su propia revisión humana
`b2b_ai/api/v2.py:532-540` (`admin_config`) · `v2.py:212-219` (`_require_admin`) · `b2b_ai/db/tenants.py:143-147` (`set_config` sin allowlist) · leído en `v2.py:206`

`_require_admin(auth_info, target_tid=tid)` autoriza "self-service": un tenant
puede configurarse a sí mismo. `TenantManager.set_config` escribe **cualquier
clave** que le manden (a diferencia de `admin_create_tenant`, que en
`v2.py:503-506` sí filtra a seis claves conocidas). Y una de las claves que
gobierna el propio antiabuso vive ahí: `_tenant_rate_limit` lee
`db.get_tenant_config(tid, "rate_limit_per_min", 300)`.

Ejecutado:

```
get_tenant_config(2,"rate_limit_per_min")  → 300
PATCH /api/v2/tenants/2   X-API-Key: <clave del tenant 2>
  {"config":{"rate_limit_per_min":100000000,"policy_human_review":"auto"}}
→ 200
get_tenant_config(2,"rate_limit_per_min")  → 100000000
```

Consecuencia: el límite por tenant —la única defensa de costo frente a un
cliente que abusa del pipeline de LLM y del procesamiento de CFDI— lo fija el
cliente. En la misma llamada se puede poner `policy_human_review: "auto"` y
saltarse el portón humano antes del ERP, o reescribir `webhook_url` y
`notif_recipient` para desviar notificaciones con datos de facturas a un
destino propio.

Causa raíz probable: `set_config` se diseñó para un llamador de confianza
(el CLI de onboarding) y después se expuso por HTTP sin ponerle la allowlist
que sí tiene su vecino de tres líneas arriba.

---

### [ALTO] Cambiar la contraseña no cierra ninguna sesión
`b2b_ai/auth/users.py:183-205` (`update_user`) · `b2b_ai/auth/middleware.py:209-214` · `b2b_ai/api/portal.py:34`

`update_user` escribe el nuevo `password_hash` y no toca nada más. No hay lista
de revocación para el `jti` que `refresh_token()` genera (`middleware.py:213`
lo emite y nadie lo consulta), y `portal_sessions` no se purga.

Escenario: al contador del despacho le roban la sesión; cambia su contraseña
por `PUT /api/v1/auth/me`. El atacante conserva el refresh token 7 días
(`REFRESH_TTL`) y, si entró por el portal, el token opaco 30 días
(`SESSION_TTL_DAYS = 30`), y los sigue canjeando por access tokens nuevos.

Consecuencia: la acción que todo el mundo ejecuta ante un incidente —cambiar
la contraseña— no lo contiene, y el usuario cree que sí. Falla silenciosa.

Causa raíz probable: no existe capa de revocación; el diseño stateless del JWT
se adoptó sin la contraparte de denylist ni de `token_version` en el usuario.

---

### [MEDIO] No hay techo al tamaño del cuerpo en ningún punto de entrada
`b2b_ai/api/portal.py:351` (`content = await up.read()`) · `b2b_ai/api/app.py:428-505` (no hay middleware de tamaño)

Barrido: `command grep -rn "content-length\|max_size\|MAX_UPLOAD\|MAX_BODY" b2b_ai/`
no devuelve ni un control de tamaño de petición (los `max_size` que salen son
del pool de Postgres). FastAPI/Starlette no traen límite por defecto.

Escenario: `POST /portal/invoices/upload` con un multipart de 2 GB — la
extensión `.xml` se valida **después** de leer (`portal.py:351` lee, `355`
valida el nombre) — carga los 2 GB en RAM del proceso. El límite de tasa
permite 300 peticiones por minuto por (IP, ruta), así que ni siquiera hace
falta un botnet.

Consecuencia: el proceso muere por OOM. En un contenedor de Railway con 512 MB
eso es la API caída; si pasa durante el demo del 6-ago, se acabó la reunión.

Causa raíz probable: se validó la extensión y el contenido, no el volumen.

---

### [MEDIO] `/portal/auth/magic-link` enumera cuentas, y el comentario dice que no
`b2b_ai/api/portal.py:213-217`

```python
user = db.get_client_user_by_email(email)
if user is None:
    # No revelamos si el email existe (evita enumeración de cuentas).
    raise HTTPException(status_code=404, detail="No hay una cuenta con ese email.")
```

El comentario afirma lo contrario de lo que hace el código. Verificado:
correo existente → `200 {"ok":true}`; correo inexistente → `404 {"detail":"No
hay una cuenta con ese email."}`.

Escenario: se prueba una lista de correos de contadores del gremio y se separa
en dos con un `if status == 200`.

Consecuencia: se confirma qué despachos son clientes de Likida — inteligencia
para phishing dirigido — y se acota la lista de objetivos del hallazgo crítico
del bootstrap. El comentario es lo grave: la próxima revisión lee "evita
enumeración" y pasa de largo.

Causa raíz probable: el 404 se puso para que el SPA mostrara un mensaje útil y
el comentario quedó del diseño anterior.

---

### [MEDIO] El cifrado en reposo se apaga solo si falta la clave, y también si es corta
`b2b_ai/api/security.py:205-236` · `b2b_ai/db/db.py:722-735`

`_encryption_key()` devuelve `None` si `B2B_ENCRYPTION_KEY` no está **o mide
menos de 16 caracteres**, y `encrypt_field()` entonces guarda el texto en claro
sin avisar. `B2B_ENCRYPTION_KEY` no aparece en `.env.production.example`.

Escenario: se despliega sin la variable (o con una clave de 12 caracteres, que
es el fallo de configuración más plausible). `webhook_url` y `notif_recipient`
de cada tenant —URLs de integración con token en el query string y correos del
despacho— quedan en claro en `tenant_config`, y una lectura de la base los
entrega. Nada distingue esa base de una cifrada: `decrypt_field` acepta ambas
por diseño.

Consecuencia: el control de cifrado en reposo existe en el código y no existe
en el despliegue, y el equipo no tiene forma de notarlo. La clave corta es peor
que ausente: parece configurada.

Causa raíz probable: "modo degradado que nunca rompe lecturas" es la decisión
correcta para *descifrar* datos viejos, pero se extendió también a *cifrar*
datos nuevos.

---

### [MEDIO] Login sin bloqueo de cuenta y con un contador de tasa que no sobrevive a la segunda réplica
`b2b_ai/api/app.py:272-318` (`RateLimiter` en memoria) · `app.py:496` (clave `(ip, ruta)`) · `b2b_ai/auth/users.py:134-143`

No hay bloqueo por intentos fallidos: `_audit_failed()` registra y sigue. El
único freno es el limitador por `(IP, ruta)` a 300/min, con el diccionario
dentro del proceso. `Procfile` y `docker-compose.prod.yml` levantan uvicorn con
workers, y el propio comentario de `app.py:269-270` lo admite ("en producción
multi-réplica conviene moverlo a Redis").

Escenario: 4 workers = 4 diccionarios independientes = 1200 intentos/min desde
una sola IP contra `/api/v1/auth/login`, y sin techo desde varias. La política
de contraseñas (10 caracteres, 4 clases) es buena, así que el ataque realista
es de credenciales reusadas, no de fuerza bruta; y contra eso el bloqueo por
cuenta es la defensa que falta.

Consecuencia: una capa antiabuso que se reporta como activa y rinde 1/N de lo
que dice, sin ninguna señal que lo delate.

Causa raíz probable: el estado del limitador vive en el proceso; es deuda
declarada, no descuido.

---

### [BAJO] Un token sin `exp` no caduca nunca
`b2b_ai/auth/middleware.py:170`

`if payload.get("exp") and now > float(payload["exp"])`. Un `exp` ausente, `0`,
`null` o `""` es falso y salta la comprobación entera; el token vale para
siempre.

Hoy no es explotable: `encode_token` siempre pone `exp` con `setdefault`
(`middleware.py:144`) y forjar un token sin él exige el secreto. Es una mina
para el día en que alguien emita un token por otra vía —un script de soporte,
una migración, un test que se cuela a producción.

Consecuencia: el equipo que mantenga esto.

Causa raíz probable: se quiso tolerar tokens sin expiración en vez de
rechazarlos.

---

### [BAJO] La CSP obliga a `unsafe-inline` y confía en un CDN externo
`b2b_ai/api/security_headers.py:28-39`

`script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net`. `unsafe-inline`
anula la CSP como defensa anti-XSS, y jsdelivr es un tercero que puede servir
JS arbitrario en el mismo origen que el dashboard con las facturas. El propio
docstring lo reconoce y ofrece `B2B_CSP` para endurecerla.

El vector de XSS almacenado que motivaría esto está cerrado aparte y bien
(`api/dashboard.py:452-453` escapa `<` y `>` del JSON embebido, con el
razonamiento escrito). Por eso es BAJO: es la red de seguridad la que está
floja, no la defensa principal.

Consecuencia: el día que entre un XSS por otra ruta, la CSP no lo frena.

---

## Lo que revisé y está bien

- **JWT, confusión de algoritmo.** `decode_token` (`middleware.py:152-172`)
  recalcula siempre `HMAC-SHA256` sobre `header.payload` e ignora el `alg` del
  header. `alg: none` y `alg: RS256` no compran nada sin el secreto. Está
  cerrado estructuralmente, no por validación. Comparación con
  `hmac.compare_digest` (`:161`).
- **`require_tenant_admin`.** (`middleware.py:288-303`) Compara
  `ctx["tenant_id"] != tenant_id` y además exige `users.manage`: dos capas. La
  trampa que buscaba —que FastAPI inyecte `tenant_id` como *query param* si el
  path no lo declara con ese nombre, dejando que el atacante lo elija— no
  ocurre: sus tres únicos usos (`auth/api.py:180, 186, 204`) están todos en
  rutas `/tenants/{tenant_id}/...`.
- **`change_role`.** (`auth/api.py:208-221`) Verifica que el objetivo sea del
  mismo tenant (404 si no) y protege al último admin. Sin IDOR.
- **Aislamiento en la capa de datos.** `get_invoice`, `list_invoices`,
  `count_invoices`, `invoice_stats`, `list_audit`, `list_api_keys`,
  `list_client_users` (`db/db.py:308-434`, `1421`) filtran por `tenant_id`. La
  única escritura sin filtro es la del hallazgo ALTO de billing.
- **API v2, scope de tenant.** `_tenant()` (`v2.py:190-200`) toma el tenant de
  la clave y nunca del cliente; `/analytics`, `/audit`, `/export`, `/usage`
  llevan `WHERE tenant_id=?` con parámetro (`v2.py:357, 418, 442, 446`);
  `/batch/{job_id}` compara el tenant del job (`v2.py:338`).
- **Override `?tenant_id=` del dashboard y de analytics.** Parecía IDOR:
  `tenant = auth_info.get("tenant_id") or query_tenant` (`dashboard.py:485`,
  `analytics.py:508`). No lo es — con clave de tenant el primer operando es un
  entero ≥1, siempre truthy, y el `or` cortocircuita antes de mirar el query
  param. Sólo la clave de servicio (`tenant_id=None`) llega al override, que es
  lo documentado. Descartado.
- **Portal server-rendered.** Los 12 endpoints de `portal/routes.py` resuelven
  al usuario por cookie (`_resolve_user`) y filtran por su tenant, incluido
  `GET /portal/invoices/{invoice_id}` (`:392`, pasa `tenant_id=user[...]`).
  Salen sin `Depends` declarado en el OpenAPI —por eso aparecían en mi barrido—
  pero la comprobación está dentro del handler: verificado en vivo,
  `GET /portal/notifications` y `PUT /portal/settings` sin cookie devuelven
  `401 "Se requiere sesión del portal."`.
- **CSRF del portal.** La cookie de sesión se emite con `httponly=True`,
  `samesite="lax"` (`portal/routes.py:254-255`), lo que bloquea el `PUT
  /portal/settings` cross-site. No hace falta token CSRF.
- **XXE y bombas de entidades en el parser de CFDI.** Era mi hipótesis más
  fuerte: `parse_cfdi` usa `etree.parse()` de lxml con el parser por defecto
  (`cfdi/parser.py:86`), sin `resolve_entities=False` ni `defusedxml`. **La
  refuté ejecutándola.** Con lxml 6.1.1: la entidad externa
  `<!ENTITY xxe SYSTEM "file://…">` en el subconjunto interno falla con
  `Entity 'xxe' not defined`; un DOCTYPE con DTD externa se ignora sin
  buscarla; y *billion laughs* muere en
  `Maximum entity amplification factor exceeded`. Sólo expanden las entidades
  internas. Está a salvo por los defaults de la librería, no por el código —
  vale anotarlo por si alguien fija una versión vieja.
- **SQL.** Barrido de todo `b2b_ai/`: cada valor va parametrizado. Las cuatro
  interpolaciones de f-string en SQL construyen sólo *nombres de columna* desde
  allowlists fijas (`db.py:1472-1483`, `db.py:1062-1075`) o nombres de tabla
  literales (`db.py:548`, `650`); `LIMIT` pasa por `int()` (`db.py:333`). Sin
  vector de inyección.
- **Custodia de secretos en reposo.** Las API keys se guardan como SHA-256 y se
  buscan por hash (`db.py:655-672`); las sesiones del portal igual
  (`db.py:1430-1439`); las contraseñas con bcrypt a 12 rondas
  (`users.py:25`, `portal.py:61`); el hash nunca sale en una respuesta
  (`_public_user`, `middleware.py:184-188`); la clave de servicio se compara en
  tiempo constante (`api/auth.py:30-34`) y los intentos fallidos se registran
  con hash truncado, no con la clave (`api/auth.py:101-112`).
- **Proxy y `X-Forwarded-For`.** `_client_ip` (`app.py:321-350`) sólo cree en
  XFF si la IP de origen está en `B2B_TRUST_PROXY`; sin esa lista usa
  `REMOTE_ADDR`. Cierra el bypass trivial del limitador de tasa. Mismo criterio
  en `security_headers.py:47-52`.
- **CORS.** Desactivado salvo que se defina `B2B_CORS_ORIGINS`
  (`app.py:466-478`); el default es same-origin. La combinación peligrosa
  (`"*"` con `allow_credentials=true`) está documentada como posible pero exige
  dos decisiones explícitas del operador, y la API autentica por header, no por
  cookie. No lo reporto.
- **CVE de dependencias — descartado por escrito.** `requirements.txt` fija
  versiones y comenta los PYSEC que motivaron cada subida
  (`python-multipart==0.0.31`, `starlette==1.3.1`). Lo instalado coincide con
  lo fijado: fastapi 0.141.1, starlette 1.3.1, pydantic 2.13.4, lxml 6.1.1,
  cryptography 50.0.0, bcrypt 5.0.0, urllib3 2.7.0, requests 2.33.0. Todas
  contemporáneas o posteriores a mi corte de conocimiento; **no encontré un CVE
  con camino de explotación real en esta app**. Aviso honesto: es revisión de
  pines, no un escaneo — no corrí `pip-audit` ni `safety` porque implicaba
  salir a la red.

---

## Lo que NO alcancé a revisar

- **Los ~40 endpoints restantes sin credencial** del inventario del OpenAPI.
  Probé nómina, pre-auditoría, email y reportes; `/contabilidad-electronica/*`,
  `/pagos/*` y `/api/v1/reportes/*` los confirmé abiertos pero no seguí el dato
  hasta ver qué expone cada uno. La cuenta exacta de rutas explotables está sin
  cerrar, y probablemente sea mayor que las tres que documenté.
- **`b2b_ai/db/pg.py`** (Postgres, la ruta de producción según
  `DEPLOY-GUIDE.md`). Todo lo que verifiqué corrió contra SQLite. Si el
  aislamiento por tenant difiere en `pg.py`, no lo sé. Cruza con el punto 1 del
  MAPA.
- **RLS y `GRANT` de la base.** No hay `migrations/*seguridad*` ni políticas de
  fila: la autorización descansa **entera** en la capa de aplicación. Eso ya es
  una sola capa, no dos, en todo el producto — no lo cuento como hallazgo
  porque es una decisión de arquitectura, pero es la razón de fondo por la que
  cada uno de los cuatro críticos de arriba llega hasta los datos sin
  encontrarse un segundo portón.
- **`auth/roles.py` frente a los permisos que cada endpoint declara.** Verifiqué
  la matriz (`roles.py:22-50`) y `users.manage`, pero no crucé rol por rol
  contra los `require_permission` del código. En particular `invoices.view_own`
  del rol `auxiliar` no lo comprueba nadie que yo haya visto: `/portal/*`
  filtra por tenant, no por autor. Sospecha sin escenario verificado, por eso
  no la reporto.
- **La entrega saliente de webhooks** (`api/webhooks.py`, `v2.py:160-175`):
  `register_webhook` acepta cualquier `http(s)://` sin lista blanca ni bloqueo
  de rangos privados. El SSRF es plausible —`default_post` de v2 es un mock,
  pero `wh.default_post` sale con urllib de verdad— y no llegué a determinar
  cuál se usa en producción.
- **`computer_use/`, `integrations/` y `erp/`.** Fuera de mi rubro por el mapa,
  y `integrations/` tenía 14 archivos modificados sin commitear durante la
  corrida.
- **Cabeceras y TLS en el despliegue real.** Sólo leí el middleware; no verifiqué
  qué llega por la red en Railway.
