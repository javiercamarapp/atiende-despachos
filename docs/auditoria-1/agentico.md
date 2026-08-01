# Sistema agéntico y orquestación — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa). No hay nota que mover: esta es la
primera lectura del rubro. La escala se ancla igual que en likida.ai — 3 o
menos cuando **existe un estado donde la base dice una cosa y el usuario cree
otra**. Aquí existen cuatro, y tres de ellos los reproduje ejecutando el
pipeline real contra una DB temporal.

Riesgo mayor hoy: hay **dos orquestadores con reglas de seguridad distintas**
(`agent/loop.py` y `services/pipeline.py`), y el que está cableado a la API, al
portal, al lote v2 y al demo es el que **no tiene el portón de validez fiscal**:
registra póliza de un CFDI que falló la validación, y al que sí retiene le manda
al despacho un correo que dice "procesada, validada y registrada en el ERP".

---

## Hallazgos

### [CRÍTICO] El pipeline de producción registra póliza de un CFDI que falló la validación fiscal, y no avisa a nadie
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

---

### [CRÍTICO] La factura retenida por aprobación se guarda como "procesado" y al despacho se le escribe que fue "registrada en el ERP"
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

---

### [CRÍTICO] Reprocesar el mismo CFDI dispara una póliza nueva cada vez; la base se queda con la primera y devuelve éxito
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

---

### [CRÍTICO] El portón de confianza de la clasificación no se puede disparar: la evidencia de la categoría rival sube la confianza del ganador
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

---

### [ALTO] `loop.py` avisa "requiere revisión humana" antes de crear la fila de revisión
`b2b_ai/agent/loop.py:214` (envío) vs `b2b_ai/agent/loop.py:216-217` (escalada)

Escenario: CFDI con anomalía → `decision = "needs_review"` → línea 214 manda el
correo `invoice_review` ("🔎 Factura {folio} requiere revisión humana") → línea
216-217 crea la fila en `reviews`. Si el proceso muere en medio (deploy,
OOM, `SIGTERM` de Railway), el contador tiene en su bandeja una factura que
"requiere revisión" y `count_pending_reviews()` devuelve 0. No hay reintento ni
reconciliación que cierre la brecha, porque nada quedó registrado de que el
aviso salió.

En la misma función, el registro en ERP ocurre antes del insert en base (líneas
191-193 y 175-177), de modo que un punto de muerte más arriba deja póliza sin
factura. La rama `auto_register` encadena cuatro efectos sin transacción: ERP →
insert → correo → review.

Consecuencia: el ciclo de vida tiene tres puntos de muerte sin cierre definido
hacia el humano — exactamente lo que el rubro mide.

Causa raíz probable: el orden de los efectos se eligió por legibilidad del
flujo, no por qué es recuperable si se corta.

---

### [ALTO] `RealCONTPAQi` corre sobre un escritorio mock y su health se presenta como "real desktop"; la póliza simulada se persiste sin marca
`b2b_ai/erp/contpaqi_real.py:38,44-46,80-82` · `b2b_ai/erp/erp_automation.py:189-194`
· `b2b_ai/db/db.py:264-265` · `b2b_ai/db/tenants.py:158-165`

Escenario: `from b2b_ai.erp.contpaqi_real import health; health()` construye
`RealCONTPAQi()` sin argumentos → `driver = ContpaqiDriver(desktop=MockDesktop())`
(línea 44-46) → `DesktopERPBase.health()` devuelve
`{"ok": True, "backend": "CONTPAQi (computer use, real desktop)", "checks":
{"abierto": True, "navegable": True}, "detail": "ERP abierto y navegable."}`
en una máquina donde CONTPAQi no está instalado, porque `MockDesktop.read_window_title()`
devuelve un título fijo y `screenshot()` devuelve `{"ok": True, "path": "<mock>"}`.
La palabra "mock" no aparece en ningún campo de ese dict.

El resto del módulo de computer use **sí es honesto** (los docstrings de
`computer_use/browser.py:22` y `contpaqi_driver.py:22` dicen que en producción
se sustituye el mock; `MockCONTPAQi.health()` dice "sin conexión real"; el
`message` de la póliza dice "(mock)"). El problema es lo que sobrevive:
`insert_invoice` guarda solo `erp_poliza` y `erp_status` (`db.py:264-265`) y
tira el `message`. En la base, en el CSV de exportación, en el portal y en la
respuesta de v2, `POL-487BCFCD3F / registrada` es indistinguible de una póliza
real. Y `tenants.erp_factory` (`db/tenants.py:158-165`) devuelve `MockCONTPAQi`
para `erp_type` = `contpaqi` **y** `aspel`, sin advertencia: un tenant
configurado como "conectado a CONTPAQi" recibe pólizas inventadas.

Consecuencia: en el demo, un folio de póliza en pantalla que no existe en
ningún CONTPAQi; después del demo, un cliente que cree tener asientos
contables. Nadie puede distinguir por la base qué corridas fueron simuladas.

Causa raíz probable: la marca de simulación vive en campos de presentación
(`message`, `backend`) y no en el dato que se persiste.

---

### [ALTO] La procedencia de la clasificación miente en las dos direcciones
`b2b_ai/services/llm.py:672-692` y `575-589` · `b2b_ai/db/db.py:299-303`

Escenario A: sin ninguna API key configurada, `get_llm()` devuelve `MockLLM`
(línea 589). `LLMService.classify_invoice` corre el mock —que internamente
llama `classify_cfdi`, o sea reglas— y devuelve `"source": "llm"` (línea 691).
`loop.py:211` mete ese valor en el correo al despacho como
`"fuente": "llm"`. El contador lee que lo clasificó un modelo; lo clasificaron
las mismas reglas de siempre.

Escenario B: `B2B_LLM_PROVIDER=openrouter` sin `B2B_OPENROUTER_API_KEY` →
`except LLMError: return MockLLM()` (líneas 584-588). Se despliega creyendo que
hay modelo, corre el mock, y nada en el log lo dice. (Los otros tres
proveedores no degradan: levantan `LLMError` desde el constructor, que nadie
atrapa en `AgentLoop.__init__:52` — ahí el fallo es ruidoso, que es lo correcto.)

Escenario C, al revés: cuando **sí** hubo LLM, `insert_invoice` escribe el
historial con `method` en literal `'rules'` (`db.py:299-303`), sin mirar
`clasif["source"]`. La tabla `classifications` —la única traza histórica de
cómo se clasificó cada factura— afirma que todo salió de reglas.

Consecuencia: no se puede responder "¿esto lo decidió un modelo o una regla?"
sobre ninguna factura ya procesada. Para un despacho contable, esa es la
pregunta que hace el cliente cuando algo sale mal, y la que hace el auditor.

Causa raíz probable: `source` se fija por la rama del código que se ejecutó
(`try` = "llm") y no por la identidad del cliente que respondió.

---

### [ALTO] Las anomalías del pipeline se calculan, se muestran y no bloquean nada
`b2b_ai/services/pipeline.py:82-97` vs `b2b_ai/agent/loop.py:162-193`

Escenario: se sube dos veces en tres días la misma factura de $8,000 del mismo
RFC. `detect_anomalies` la marca `duplicado` con severidad `high` y la nota
"Requiere confirmar que no sea un doble cargo **antes de registrar la póliza**"
(`services/anomaly.py:94-100`). El pipeline guarda ese dict en la variable
`anomalias` (línea 82), pasa a `evaluate_approval` —que solo mira monto y tipo—
y como $8,000 < $50,000 registra la póliza. La anomalía viaja en la respuesta
JSON y en el reporte HTML, sin haber tocado ninguna decisión.

`agent/loop.py:168-169` sí la usa (`anomalia["nivel"] == "alerta"` fuerza
revisión). Otra vez: la ruta cableada a la API es la débil.

Consecuencia: la detección de duplicados y de operaciones simuladas —que el
propio código justifica citando CFF Arts. 5-A, 29-A y 113-Bis— es decorativa en
el camino que usan el portal, el lote y el demo.

Causa raíz probable: `evaluate_approval` se insertó como "el gate" y las
anomalías, que llegaron antes, quedaron huérfanas de consumidor.

---

### [ALTO] El efecto de la tool se consuma antes de su registro de auditoría; un fallo posterior le reporta al usuario "Error al procesar" sobre una póliza que ya existe
`b2b_ai/services/pipeline.py:39-47` · `b2b_ai/api/portal.py:363-380`

Escenario: `_tool` ejecuta `call_tool("register_erp", ...)`, la póliza se crea,
y **después** intenta `logger_.log(...)`, que escribe en `audit_log`. Con SQLite
en WAL y varios hilos (el portal lanza un hilo por subida, `api/v2.py:305-310`
lanza otro por lote), un `database is locked` en esa escritura levanta la
excepción; el `except` intenta loguear el error —que vuelve a fallar— y
propaga. `portal._run` la atrapa y marca el job `status="error"`, mensaje
"Error al procesar." El usuario reintenta y se produce la segunda póliza del
hallazgo anterior.

Consecuencia: un fallo de la bitácora se le presenta al humano como si el
trabajo no se hubiera hecho. Es la peor forma de mentir sobre un efecto: la que
invita al reintento.

Causa raíz probable: la auditoría es parte del camino de éxito en vez de un
efecto separado y tolerante a fallo.

---

### [ALTO] Si el proceso muere a media subida, el trabajo desaparece de memoria y el cliente queda con 404 permanente
`b2b_ai/api/portal.py:84-118` y `298-322` · `b2b_ai/api/v2.py:306-333`

Escenario: el cliente sube un CFDI, recibe `job_id = "a3f9…"` y empieza a hacer
polling cada 2s. Railway recicla el contenedor. `_JobStore._jobs` es un dict en
memoria: al volver, `JOBS.get(job_id)` devuelve `None`, `int(job_id)` revienta y
la respuesta es `404 "Job o factura no encontrado."` — para siempre, sin
recuperación. Mientras tanto la factura puede estar ya en la base (si el hilo
alcanzó a llegar al insert) o no, y en el ERP puede haber póliza. El cliente
no tiene forma de saber cuál de los tres estados le tocó.

Lo mismo en `v2`: `_JOBS` en memoria; `GET /batch/{job_id}` devuelve 404 tras
reinicio, con N facturas ya registradas.

Consecuencia: el caso "se trabó" no tiene cierre. El usuario nunca recibe su
salida y el sistema no sabe que se la debe.

Causa raíz probable: el estado del trabajo asíncrono vive solo en el proceso;
no hay tabla de jobs ni reconciliación al arranque.

---

### [ALTO] El webhook de email deja que el cuerpo de la petición sobrescriba el tenant de la API key
`b2b_ai/api/webhooks.py:252-254`

```python
scope = auth_info.get("tenant_id")
if email.tenant_id is not None:
    scope = email.tenant_id      # ← sin comprobar que coincida con la key
```

Escenario: el despacho A, con su API key legítima, hace `POST
/api/v1/webhooks/email` con `{"tenant_id": 7, "xml": "<Comprobante…>"}`. El
`AgentLoop` procesa el CFDI **en los libros del tenant 7**, y `_send` lee
`cfg["notif_recipient"]` del tenant 7 (`loop.py:79-80`): el aviso —con folio,
emisor y monto de la factura— se le manda al despacho ajeno.
`process_email_inbound` solo hace `tm.get_tenant(tenant_id)`, que valida
existencia, no pertenencia.

Consecuencia: es el "destinatario equivocado" del rubro, con contenido fiscal
de un tercero. (Se solapa con el rubro 5; lo reporto aquí porque el daño es la
ejecución del agente contra el tenant equivocado, no solo la lectura.)

Causa raíz probable: el `tenant_id` opcional del cuerpo se pensó para la
consola de administración y quedó vivo para cualquier key.

---

### [ALTO] Ninguna ruta HTTP resuelve una revisión: la cola humana no tiene salida por producto
`b2b_ai/db/db.py:776` (definida) — sin llamadores fuera de `tests/test_agent_loop.py:126`

Escenario: llega un CFDI por webhook, el `AgentLoop` escala y crea la fila en
`reviews` con `status='pending'`. El contador entra al portal a resolverla: no
hay endpoint. `resolve_review` existe en la capa de datos y solo la invoca una
prueba. Los contadores de `api/analytics.py:281,301` reportan
`revisiones_pendientes`, así que el número sube y no baja nunca.

Consecuencia: la mitad "human in the loop" existe como escritura y no como
lectura ni resolución. La única forma de cerrar una revisión es SQL a mano.

Causa raíz probable: se construyó la creación de la revisión y no su ciclo de
vida.

---

### [MEDIO] La consola del demo reporta "2 anomalías" en toda factura, y el reporte HTML de la misma corrida dice otra cosa
`b2b_ai/services/demo.py:748` y `773` vs `b2b_ai/services/demo.py:438-445`

Escenario: `pipeline` devuelve `anomalias` como el dict de la tool
`{"anomalies": [...], "summary": {...}}` (`tools/tools.py:199-202`). La consola
hace `anom_count = len(res.get("anomalias", []))` → `len` de un dict con dos
llaves → **2, siempre**, incluso para una factura impecable; y la línea 773
cuenta como "con anomalías" toda factura, porque un dict no vacío es verdadero.
El generador del HTML sí desempaqueta bien (`_get_anomalies`, líneas 438-445).

Consecuencia: en la demo, la terminal dice "12 con anomalías" y el reporte que
se entrega dice "2". Quien esté mirando la pantalla pregunta cuál de los dos
miente.

Causa raíz probable: el contrato de la tool cambió a `{anomalies, summary}` y
solo se actualizó uno de los dos consumidores.

---

### [MEDIO] `send_notifications` muta el estado de la instancia y se queda pegado
`b2b_ai/agent/loop.py:98-99`

```python
notify = self.notify if send_notifications is None else send_notifications
self.notify = notify        # ← el override de UNA llamada persiste
```

Escenario: `process_email_inbound` reutiliza el mismo `AgentLoop` para todos los
CFDI del correo (`api/webhooks.py:216-224`). Una llamada con
`send_notifications=False` apaga las notificaciones de todas las siguientes de
esa instancia, incluidas las escaladas. Hoy la ruta pasa siempre el mismo valor,
así que está latente; en cuanto alguien reutilice el loop con valores mixtos
(un lote donde la primera pasada es silenciosa), las escaladas dejan de avisar
sin ningún error.

Consecuencia: una bomba de tiempo sobre el único canal que convoca al humano.

Causa raíz probable: un parámetro por llamada escrito sobre un atributo de
instancia.

---

### [MEDIO] El lote de v2 entrega el evento `invoice_processed` aunque haya facturas retenidas o inválidas
`b2b_ai/api/v2.py:266-269`

Escenario: lote de 100 CFDI donde 12 quedan `pending_approval` y 3 inválidas.
`_deliver_events(..., "invoice_processed", {"batch": job_id, "summary": summary})`
manda un solo evento con un resumen que cuenta `validas` e `insertadas` y no
tiene ninguna llave para retenidas. El integrador que escucha ese webhook marca
las 100 como contabilizadas.

Consecuencia: el estado real del lote no viaja por el canal que un cliente
enterprise usa para automatizar aguas abajo.

Causa raíz probable: un único tipo de evento para un resultado que tiene tres
desenlaces.

---

### [BAJO] El desempate entre categorías se resuelve por orden fijo y no queda registrado que hubo empate
`b2b_ai/services/classify.py:85-89`

`for cat in PRIORITY: if scores[cat] > best_score` — el `>` estricto sobre una
lista ordenada `nomina > activo_fijo > inversion > gasto_operativo` significa
que todo empate lo gana el que está más arriba, y ni el resultado ni la
`razon` dejan constancia. Es la deuda que sostiene al CRÍTICO de la confianza:
aunque se arregle el cálculo de `n_matches`, sin registrar el empate no hay
forma de que un humano sepa que la decisión fue un volado.

---

## Lo que revisé y está bien

- **`agent/loop.py:117-153` — el árbol de decisión del loop, en sus dos primeras
  ramas, sí cierra el ciclo.** `parse_failed` escala, no registra y notifica
  (123-127); `invalid` inserta con categoría `desconocido`, escala, notifica
  `invoice_rejected` y **retorna antes de tocar el ERP** (139-152). Esa es la
  forma correcta, y es la que le falta a `pipeline.py`.
- **`services/llm.py` — el fallback a reglas está bien construido.** Todas las
  tareas (`classify_invoice`, `extract_data`, `summarize`, `detect_anomaly`,
  672-753) envuelven la llamada y caen a determinístico ante cualquier
  excepción; el pipeline no se cae por culpa del modelo. La sanitización contra
  inyección de prompt (`llm.py:44-100`) trunca campos, elimina tags y detecta
  patrones antes de mandar el CFDI — el texto del proveedor no llega crudo al
  modelo.
- **El presupuesto de tokens es un portón real, no un contador.**
  `TokenBudget.check_allowance()` se invoca **antes** de cada llamada
  (`llm.py:_run`), no después, y recorta `max_tokens` e input. Un CFDI con un
  concepto de 50 KB no dispara una llamada cara.
- **`services/approval.py:130-148` — `approve()` exige e.firma de verdad.**
  Devuelve `blocked_efirma` y registra la decisión bloqueada; no es un
  parámetro decorativo. El problema del hallazgo 2 no es esta clase, es que
  nadie persiste ni entrega su veredicto.
- **`db/db.py:80-95` — el aislamiento de conexiones por hilo es correcto** y
  está justificado en el comentario (una `sqlite3.Connection` compartida
  revienta bajo el threadpool). `api/v2.py:307` abre además una conexión
  dedicada para el hilo del lote.
- **`computer_use/` es honesto en su documentación.** `browser.py:22`,
  `contpaqi_driver.py:22` y los `health()` de `MockBrowser`/`MockDesktop`/
  `MockCONTPAQi` dicen explícitamente "sin conexión real" / "sin escritorio
  real", y ningún driver afirma haber presentado nada ante el SAT. El problema
  del hallazgo 6 es acotado: `RealCONTPAQi` y el dato persistido, no el módulo.
- **Existe una prueba del gate de aprobación:** `tests/test_e2e_security.py:65`
  asegura `erp_status == "pending_approval"`. Verifica que el ERP no se toque;
  no verifica nada de lo que pasa después con el humano — por eso el CRÍTICO 2
  convive con la suite en verde.
- **`tools/logger.py`** registra siempre, con lock y buffer, y devuelve id 0 en
  vez de reventar cuando no hay DB (línea 43-46).

## Lo que NO alcancé a revisar

- **`services/demo.py` completo** (35 KB): solo abrí el bucle de procesamiento
  (720-780) y el generador de anomalías del reporte (438-486). El resto del
  guion del demo —el orden de las escenas, los textos en pantalla— no lo leí, y
  es donde más barato sale un error visible.
- **`api/v2.py` fuera de `/batch`**: analytics, webhooks salientes, audit y
  export. Solo verifiqué el camino del lote.
- **El comportamiento bajo concurrencia real.** No lancé el servidor ni corrí
  dos subidas simultáneas: el hallazgo del `database is locked` está razonado
  desde el código (WAL + hilos + escritura en el camino de éxito), no
  reproducido. La carrera exacta entre `_run_job`/`dbx.close()` y el `logger`
  global (`tools/logger.py:64`, singleton mutable que cada `process_file`
  re-apunta con `set_db`) la dejé sin cerrar: creo que no corrompe datos porque
  todas las conexiones apuntan al mismo archivo, pero no lo probé.
- **`agent/loop.py` contra el ERP CSV** (`erp/csv_erp.py`): solo recorrí la
  ruta `MockCONTPAQi`. Un ERP que escribe a disco cambia el análisis de
  idempotencia del hallazgo 3.
- **Cancelaciones** (`cfdi/cancellation.py`): no verifiqué qué hace el
  orquestador cuando llega un CFDI ya cancelado. `demo-data/factura_cancelada.xml`
  existe, no lo pasé por el pipeline.
- **No corrí la suite completa.** Me apoyé en la línea base del MAPA (4900
  passed). Las ejecuciones que hice fueron contra DBs temporales en el
  scratchpad; no toqué ningún archivo del repo.
