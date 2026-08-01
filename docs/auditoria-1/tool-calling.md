# Tool calling — auditoría 1

**Nota: 4/10** (ronda 1, sin nota previa). Razón: primera mirada del rubro — no hay
nota anterior que defender ni recalibrar.

El riesgo mayor hoy: `register_erp` no es idempotente contra `folio_fiscal`, y
nada en el pipeline evita llamarla dos veces para la misma factura — un
reproceso (retry tras error, correr el batch dos veces, reenvío de un CFDI)
duplica el asiento contable real en el conector CSV de producción, verificado
en vivo.

## Hallazgos

### [CRÍTICO] `register_erp` duplica el asiento contable en cada reproceso — verificado en vivo contra `CSVErp`
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

---

### [ALTO] El presupuesto de tokens es un contador global de por vida del proceso, no "por sesión" como dice su propio docstring — y cobra costo falso por MockLLM
`b2b_ai/services/llm.py:107-133` (`TokenBudget.__init__`, docstring dice "por
sesión" en la línea 113), `b2b_ai/services/llm.py:194` (`_global_budget =
TokenBudget()`, singleton de módulo), `b2b_ai/services/llm.py:629-633`
(`LLMService.__init__`: `self.budget = get_token_budget()` — siempre el
mismo objeto, se inyecte o no un cliente), `b2b_ai/services/llm.py:636-658`
(`_run`: `check_allowance()` antes de llamar al proveedor, `record_call()`
después), `b2b_ai/services/llm.py:154` (`cost_per_1k =
self.DEFAULT_COST_PER_1K.get(model, 0.001)`)

Escenario: con `B2B_LLM_MAX_CALLS` en su default (100) y cada factura
consumiendo 2 llamadas LLM (`classify_invoice` + `detect_anomaly`, ver
`agent/loop.py:156` y `:162`), la factura #51 procesada en la vida de ese
proceso (sin reinicio, sin ventana de tiempo, sin scoping por tenant ni por
request) dispara `check_allowance()` → `LLMError("Presupuesto LLM agotado:
100 llamadas...")` **antes** de siquiera intentar la llamada. Esto ocurre
igual con `B2B_LLM_PROVIDER` vacío (`MockLLM`, el default documentado en el
propio README como "sin LLM"), porque `record_call()` se ejecuta para
cualquier proveedor y `MockLLM` no tiene atributo `.model` — cae en el costo
por default `0.001` USD/1K vía `getattr(self.client, "model", "")` →
`""` → no está en `DEFAULT_COST_PER_1K` → 0.001. Es decir: el gasto
simulado de un cliente que no cuesta un centavo real cuenta contra el mismo
techo de $5.00 USD (`B2B_LLM_MAX_COST_USD`) que un proveedor real pagado.
Una vez cruzado cualquiera de los dos límites, **cada** llamada posterior en
ese proceso —incluidas las de un proveedor real ya pagado— cae al
`except` de `classify_invoice`/`detect_anomaly`/`summarize`/`extract_data`
y regresa `source: "rules"` de forma silenciosa, sin log de nivel alerta,
sin reset, sin ningún consumidor del código que lea
`get_token_budget().to_dict()` (confirmé por grep: ninguna ruta de API ni
dashboard lo expone).

Consecuencia: un despacho que paga por clasificación asistida por LLM deja
de recibirla después de ~50 facturas por vida del proceso del servidor
(cada request en un worker que no se reinicia lo hereda), sin que nadie lo
note — el pipeline sigue "funcionando" con reglas, que es exactamente el
diseño de fallback documentado, pero por la razón equivocada (un contador
compartido y no reseteable, no un fallo real del proveedor).

Causa raíz probable: `TokenBudget` se implementó como singleton de módulo en
vez de scoping real por sesión/request, y `record_call` no distingue gasto
simulado (`MockLLM`) de gasto real.

---

### [ALTO] `evaluate_approval` deja que quien la invoque suba el umbral de aprobación humana sin límite — el schema de la tool no lo impide
`b2b_ai/tools/tools.py:205-213` (definición y parámetros de la tool),
`b2b_ai/services/approval.py:61-65` (`ApprovalManager.__init__`, sin
validación de rango), `b2b_ai/services/approval.py:80-87` (la comparación
`amount < self.auto_threshold` decide todo)

Escenario, reproducido contra el código real:

```
invoice total = $800,000.00
call_tool("evaluate_approval", invoice=invoice)                       -> requires_approval, threshold=50000.0
call_tool("evaluate_approval", invoice=invoice, auto_threshold=999999999) -> auto_approved, threshold=999999999.0
```

El parámetro `auto_threshold` está declarado en el schema de la tool con
`"required": False` y sin mínimo, máximo, ni verificación posterior contra
la configuración del tenant o un valor canónico server-side. Hoy no es
explotable en la práctica: verifiqué que ninguno de los dos únicos
invocadores en producción (`pipeline.py:86-87`, que solo pasa `invoice=`; y
`agent/loop.py`, que no llama `evaluate_approval` como tool en absoluto)
pasa `auto_threshold` desde una fuente externa. Pero el propio docstring de
`registry.py:1-14` declara la intención explícita del módulo: "el router y
el orquestador usan el registro para descubrir y llamar tools de forma
dinámica" — es decir, la conexión a un caller LLM real (function calling)
es el destino declarado de esta pieza, no un accidente. El día que eso pase,
esta tool es la que decide si una factura de $800,000 pasa sin e.firma ni
revisión humana, y el `float(auto_threshold)` de `approval.py:63` acepta
cualquier número, incluido uno absurdamente alto.

Consecuencia: el único freno real hoy es que `_is_payment()`
(`approval.py:48-55`) obliga aprobación para comprobantes de pago sin
importar el umbral — pero para cualquier otro tipo de CFDI (gasto,
ingreso), el umbral es el único control, y ese control es un parámetro
abierto de la tool.

Causa raíz probable: la tool expone un parámetro de control de riesgo
(`auto_threshold`) al mismo nivel que sus parámetros de datos (`invoice`),
en vez de resolverlo server-side desde la config del tenant como hace
`agent/loop.py` con `notif_recipient`.

---

### [MEDIO] `call_tool()` no valida tipos ni forma contra el schema declarado — argumentos basura producen una nómina de $0.00 con apariencia legítima, no un error
`b2b_ai/tools/registry.py:92-97` (`call_tool`: `tdef(**kwargs)` sin
validar nada contra `t.parameters`), `b2b_ai/tools/tools.py:159-167`
(`calculate_payroll`)

Escenario, reproducido contra el código real:

```python
call_tool("calculate_payroll", empleado={"nombre": "demo"},
          sueldo_bruto="diez mil pesos")
```

No lanza excepción. Devuelve un dict completo y bien formado:
`salario_diario: "0.00"`, `percepciones.total: "0.00"`,
`deducciones.isr: "0.00"`, `neto_a_pagar: "0.00"` — con
`requires_human_review: True` como único indicio de que algo salió mal. El
schema declarado en `tools.py:162-164` marca `sueldo_bruto` como
`{"type": "number", "required": True}`, pero `registry.py` nunca lo
compara contra el valor recibido; la coerción numérica ocurre —o no—
adentro de cada función de negocio (`services/payroll.py`), con resultados
distintos tool por tool. El mismo patrón aplica a cualquier otra tool: el
schema es documentación, no un contrato exigible.

Consecuencia: si esta tool llega a alimentarse de un valor mal extraído
(por un LLM, por un OCR, por un integrador de terceros), el fallo se ve
igual que una nómina de $0.00 legítima en vez de un error explícito — y
`requires_human_review: True` es una bandera silenciosa entre docenas de
registros normales, no una alerta.

Causa raíz probable: el decorator `@tool` guarda `parameters` como
metadata descriptiva (para `to_dict()`/introspección) y nunca la conecta a
`call_tool()` como validación de entrada.

---

### [MEDIO] El router de "tool calling por intención" (`router.py`) no corre en ningún camino de producción — el modelo nunca elige tool ni argumentos hoy
`b2b_ai/tools/router.py:49-64` (`route`), `:67-88` (`dispatch`)

Verificado por grep en todo el repo (excluyendo `.venv`): las únicas
llamadas a `route()`/`dispatch()` están en `tests/test_router.py` y
`tests/test_pipeline_fase2.py`. Ni `app.py`, ni `pipeline.py`, ni
`agent/loop.py` lo importan. Los dos caminos reales de producción
(`pipeline.py:37-47`, `agent/loop.py:58-68`) llaman `call_tool()`
directamente con nombre de tool y argumentos **hardcodeados en Python**,
poblados desde el CFDI ya parseado — nunca desde una salida de LLM. El LLM
real (`LLMService`) está confinado a cuatro tareas de completado
estructurado (`classify`/`extract`/`summarize`/`anomaly`, todas con salida
parseada a JSON y validada contra un whitelist o rango cerrado) y nunca
elige qué tool invocar ni con qué argumentos.

Esto **no es un hallazgo de seguridad** — de hecho es la razón por la que
los tres hallazgos de arriba sobre "el modelo decide con qué datos actuar"
no son explotables hoy. Pero sí es un hallazgo de arquitectura: el propio
docstring de `router.py:1-9` describe esta pieza como "la que convierte
'el agente decide qué tool llamar' en lógica determinística y testeable" —
y en la práctica es código muerto que solo los tests ejercitan. Si un
futuro mantenedor lee `router.py` para entender cómo el agente decide,
entiende mal cómo funciona el sistema real.

Consecuencia: para el equipo que dé mantenimiento, confundir "lo que el
código dice que hace" con "lo que el código realmente hace" en la pieza
central del rubro es exactamente el tipo de deuda que rubros.md pide
cobrar antes de que la cobre un cliente — en este caso, antes de que la
cobre el primer ingeniero que conecte de verdad un LLM function-calling
sobre este registry sin saber que nadie probó esa ruta.

Causa raíz probable: el router se escribió como la interfaz "correcta" de
tool calling pero el pipeline real se armó aparte, más rápido, llamando
`call_tool()` a mano.

## Lo que revisé y está bien

- **Los montos, RFC y demás cifras que alimentan el gate de aprobación y el
  registro en ERP vienen del parseo determinístico del CFDI
  (`parse_cfdi`), nunca de un campo controlado por el LLM.**
  `pipeline.py:77-79` construye `invoice = dict(datos)` sobre la salida de
  `parse_cfdi`, y lo único que el LLM aporta es `categoria`/`confianza`/
  `razon`. Verificado.
- **La categoría contable elegida por el LLM está acotada a un whitelist
  cerrado de 5 valores** (`CATEGORIA_NOMBRE`, `services/classify.py:41-47`)
  y se mapea a solo 5 pares fijos de cuenta cargo/abono
  (`erp/contpaqi.py:70-77`, `_cuentas_para_categoria`) — el modelo no puede
  escribir una cuenta contable arbitraria, solo elegir entre 5
  precargadas. `LLMService.classify_invoice` (`llm.py:672-697`) fuerza
  `cat = "desconocido"` si la categoría devuelta no está en el whitelist, y
  clampa la confianza a `[0,1]`.
- **Confianza baja o categoría no mapeable dispara
  `requires_human_review`** (`llm.py:690`, umbral 0.70) y ese flag decide
  en `agent/loop.py:168-169` si la factura se sostiene para revisión en
  vez de registrarse automáticamente.
- **Los comprobantes de pago (tipo P / complemento de pago) exigen
  aprobación humana + e.firma sin importar el monto ni el umbral
  configurado** — `approval.py:48-55` (`_is_payment`) y `:77-79`. Este
  candado no depende de `auto_threshold` y por tanto no lo rompe el
  hallazgo ALTO de arriba.
- **Sanitización de prompt injection antes de construir el prompt del
  LLM**: `llm.py:58-101` (`_sanitize_field`, `_sanitize_payload`,
  `_strip_xml_tags`, `_detect_injection`) trunca campos largos, quita tags
  XML/HTML y detecta patrones de instrucción ("ignore previous",
  "system prompt", etc.) antes de que cualquier dato del CFDI llegue al
  LLM — usado de verdad en `_render_prompt` (`llm.py:269-275`), no solo
  declarado.
- **`_http_post_json` restringe el esquema de URL a http/https**
  (`llm.py:338-341`) antes de hacer la llamada saliente al proveedor,
  cerrando el vector obvio de SSRF vía `file://` si `B2B_LLM_BASE_URL`
  llegara mal configurada.
- **El fallback documentado ("LLM opcional... con fallback automático a
  reglas", README.md:22-23, docs/architecture.md:33/103) coincide con el
  código**: no hay una cascada real entre OpenAI/DeepSeek/Anthropic/
  OpenRouter (cada uno se selecciona por una sola variable de entorno,
  `get_llm()` en `llm.py:575-589`), y el único fallback entre
  "proveedores" es OpenRouter→MockLLM si falta la API key
  (`llm.py:584-588`) — el resto de los "fallbacks" son siempre
  LLM→reglas, tal como documenta el README. No encontré una afirmación de
  failover multi-proveedor que el código contradiga.
- **`/api/v2/batch` aísla el fallo de un archivo individual**
  (`api/v2.py:279-283`, `_process_one` con try/except) a diferencia del
  endpoint legacy `POST /process?folder=...`, que sí propaga sin aislar
  (mencionado como parte del hallazgo CRÍTICO, no como hallazgo aparte).
- **`db.insert_invoice` deduplica correctamente a nivel SQLite** por
  `UNIQUE(tenant_id, folio_fiscal)` (`db.py:269-286`) — el problema del
  hallazgo CRÍTICO es que esa defensa llega un paso tarde, no que no
  exista.

## Lo que NO alcancé a revisar

- El driver real de computer use para CONTPAQi
  (`computer_use/contpaqi_driver.py`, `erp/contpaqi_real.py`) más allá de
  confirmar que `register_invoice` tampoco tiene chequeo de idempotencia
  en su firma — no ejecuté el driver real (requiere escritorio) ni revisé
  a fondo `erp_automation.py`/`DesktopERPBase`.
- El comportamiento real de red de `OpenAIProvider`/`AnthropicProvider`/
  `DeepSeekProvider` contra un endpoint real (reintentos, timeouts, rate
  limits) — no hay credenciales activas en este entorno de auditoría.
- Si algún webhook entrante (`api/webhooks.py`, `api/outreach.py`) alguna
  vez alimenta `call_tool`/`dispatch` con datos de un remitente externo —
  hice grep de los símbolos y no encontré ninguna referencia, pero no leí
  esos dos archivos línea por línea.
- Si el orden de ejecución real de la suite de pytest (4900+ tests, un
  solo proceso o paralelizado vía xdist) llega a disparar en la práctica
  el agotamiento de `_global_budget` descrito en el hallazgo ALTO — tengo
  la prueba de que el mecanismo existe y no se resetea entre tests, pero
  no corrí la suite completa instrumentada para confirmar si ya ocurre
  hoy dentro de la corrida de referencia (4900 passed).
- `services/report.py` / la tool `generate_report` y su parámetro
  `tenant_id` — confirmé que la tool no tiene ningún invocador en
  producción (solo tests/router muerto), pero no revisé si algún endpoint
  fuera de mi rubro asignado la usa de forma que un `tenant_id` externo
  pudiera cruzar el aislamiento multi-tenant.
