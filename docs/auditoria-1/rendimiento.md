# Rendimiento y costo — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa)

El riesgo mayor hoy: dos caminos de "peor caso" no caben en su propio límite y fallan — uno de forma ruidosa (3 endpoints enterprise mueren en la configuración de producción recomendada), otro de forma silenciosa (una sola llamada GET puede disparar miles de llamadas a un LLM de pago y agotar, para todos los tenants, el presupuesto de IA del proceso entero).

## Hallazgos

### [CRÍTICO] El pool de conexiones de `db/pool.py` es SQLite-only pero se conecta con el DSN de Postgres en el despliegue que recomienda el propio DEPLOY-GUIDE
`b2b_ai/db/pool.py:53-58` (`ConnectionPool._open`), instanciado en `b2b_ai/api/v2.py:182` (`pool = ConnectionPool(db.path, size=4)`)

Escenario: en producción (Railway, según `DEPLOY-GUIDE.md`, que es exactamente lo que el punto 1 del MAPA ya marcó como pendiente), `B2B_DB_URL` es un DSN `postgresql://user:pass@host:5432/dbname`. La clase `Database` sí distingue Postgres de SQLite (`_is_postgres`, `db/db.py:33-36`) y usa el pool correcto (`PGPool`/`psycopg_pool`, con tamaño configurable por `B2B_PG_POOL_MIN`/`MAX`). Pero `build_v2_router` construye un **segundo pool, distinto y sin esa lógica**: `ConnectionPool(db.path, size=4)` pasa el mismo DSN a una clase que en `_open()` llama `sqlite3.connect(self.db_path, ...)` sin condicional alguno. Verifiqué el comportamiento exacto en un sandbox aislado (no toqué el repo): `sqlite3.connect("postgresql://user:pass@host:5432/dbname")` lanza `sqlite3.OperationalError: unable to open database file` — no crea nada, no falla en silencio, simplemente revienta.

Como el pool abre conexiones de forma perezosa (`_acquire_raw`, línea 60-68), esto no truena al arrancar la app: truena la **primera vez** que alguien pega a uno de los tres endpoints que usan `pool.run(...)`: `GET /api/v2/analytics` (línea 356-360), `GET /api/v2/audit` (línea 417-420) y `POST /api/v2/export` (línea 441-447). Con Postgres en producción, esos tres endpoints — parte del pitch "enterprise" del producto — devuelven 500 el 100% de las veces, para el 100% de los tenants, sin excepción.

Consecuencia: si el contralor pide ver analytics, auditoría o exportar un CSV mientras el backend corre contra Postgres (que es la configuración que el propio repo recomienda para producción), la demo se cae ahí mismo. Y como toda la suite de 4900+ pruebas corre contra SQLite (confirmado en MAPA punto 1), nada en CI puede detectar esto.

Causa raíz probable: `v2.py` se escribió asumiendo SQLite y reimplementó un pool en vez de reusar la conexión ya pooleada de `db.conn`/`Database`.

### [CRÍTICO] `_pass_ai` hace una llamada al LLM por cada par (factura, movimiento bancario) dentro de un GET que recalcula por defecto
`b2b_ai/services/bank_reconciliation.py:417-436` (`_pass_ai`), llamando a `_ai_confidence` en la línea 427, que en la línea 445 hace `self.llm.classify_invoice(...)`. Disparado desde `b2b_ai/api/reconciliation.py:140-152` (`GET /api/v1/reconciliation/matches`, con `refresh: bool = Query(default=True)` — se recalcula SIEMPRE salvo que el cliente pase `refresh=false` explícitamente) y desde `b2b_ai/api/reconciliation.py:178-198` (`GET /api/v1/reconciliation/report`, que llama `svc.auto_match()` incondicionalmente en la línea 195, sin parámetro para evitarlo).

Escenario con valores: un despacho con 200 facturas sin conciliar y un estado de cuenta con 150 movimientos sin conciliar (tras los pases `_pass_exact`/`_pass_partial`, que sí filtran antes de llegar aquí — ese diseño está bien y reduce N y M). `_pass_ai` itera 200 × 150 = 30,000 pares, y por cada uno intenta una llamada de red real al proveedor LLM configurado (`_http_post_json`, timeout de 15s por llamada). Con `B2B_LLM_MAX_CALLS` por default en 100 (`llm.py:128`), las primeras ~100 llamadas sí salen a red — a ritmo conservador de 1-2s cada una, son 100-200 segundos solo en esas, casi seguro por encima del timeout típico de un load balancer/reverse proxy (30-60s) — y las ~29,900 restantes fallan instantáneamente contra el presupuesto agotado (ver hallazgo siguiente), cayendo al overlap de tokens. El request de `GET /matches` (una acción tan cotidiana como refrescar un dashboard, sin ningún job asíncrono como sí existe para `/api/v2/batch`) no tiene forma de completarse dentro de un tiempo razonable con un volumen realista de un despacho activo.

Consecuencia: si el contralor sube un estado de cuenta con más de unas pocas decenas de movimientos pendientes durante la demo y pide ver los cruces, la pantalla se queda cargando indefinidamente. Es exactamente el "el demo se cae" que define un CRÍTICO en este rubro. Además, cada una de esas llamadas cuesta dinero real por lo que ya es información redundante: la misma función ya calcula `tok_conf` (overlap de tokens, gratis) y lo combina con `max()` — el LLM añade poco valor marginal a cambio de mucho costo y tiempo.

Causa raíz probable: falta un límite superior al tamaño de `invoices × stmt` antes de decidir usar LLM, y falta el patrón asíncrono (job + polling) que `/api/v2/batch` sí implementa.

### [ALTO] El presupuesto de tokens es un singleton de proceso sin reset — una sola llamada cara apaga el LLM para todos los tenants
`b2b_ai/services/llm.py:193-199` (`_global_budget = TokenBudget()` a nivel de módulo, `get_token_budget()` siempre devuelve la misma instancia), consumido en `b2b_ai/services/llm.py:633` (`LLMService.__init__`: `self.budget = get_token_budget()`) desde **todos** los sitios que crean `LLMService()`: `b2b_ai/agent/loop.py:52`, `b2b_ai/api/reconciliation.py:51` (una instancia nueva por request, pero **el budget que usa es el mismo objeto global**), `b2b_ai/services/bank_reconciliation.py:204`.

Escenario: el docstring de la clase (`llm.py:113-114`) dice "máximo de llamadas **por sesión**", pero no existe ningún concepto de sesión ni ningún `reset()` en todo el repo (verificado por grep) — es un contador que solo sube, para siempre, hasta que el proceso se reinicia. `B2B_LLM_MAX_CALLS` por default es 100. El hallazgo anterior (`_pass_ai`) por sí solo agota ese presupuesto con una sola llamada de un solo tenant. A partir de la llamada 101, `check_allowance()` (línea 135-146) lanza `LLMError` **antes** de intentar red, así que cada `classify_invoice`/`extract_data`/`summarize`/`detect_anomaly` de **cualquier tenant**, en cualquier endpoint (agente conversacional, clasificación de facturas vía `BankReconciliation`, etc.) empieza a caer al fallback de reglas — silenciosamente: revisé `_failed()` (línea 667-669) y no hay ningún `logging`/`log_call` ni alerta, solo se guarda `self.last_error` en la instancia, que nadie más lee.

Consecuencia: un tenant con una reconciliación pesada apaga, sin saberlo nadie, la inteligencia LLM para el resto de los tenants del mismo proceso hasta el próximo restart/redeploy. El equipo que opera esto no tiene ninguna señal de que esto ocurrió: `source: "rules"` queda en cada respuesta individual, pero no hay agregación ni alerta.

Causa raíz probable: el budget se diseñó pensando en una sesión de agente, pero se cableó como singleton de proceso sin mecanismo de expiración/reset ni logging al agotarse.

### [ALTO] El costo por proveedor está hardcodeado con una sola tarifa combinada, y cualquier modelo fuera de la lista usa un default arbitrario
`b2b_ai/services/llm.py:116-123` (`DEFAULT_COST_PER_1K`, 5 entradas) y línea 154 (`cost_per_1k = self.DEFAULT_COST_PER_1K.get(model, 0.001)`), aplicado en la línea 155 a `(input_tokens + output_tokens)` combinados.

Escenario con valores: los cuatro proveedores (`OpenAIProvider`, `AnthropicProvider`, `DeepSeekProvider`, `OpenRouterLLM`) exponen `model` configurable vía `B2B_LLM_MODEL` — es una ruta soportada explícitamente, documentada en cada constructor (`llm.py:365`, `:388`, `:411-412`, `:550-551`). Si un despacho pide un modelo distinto a los 4 nombres exactos del diccionario (p. ej. una variante más nueva o más cara de cualquiera de los 4 proveedores), `record_call` cae al default `0.001`/1K tokens — una cifra que no tiene relación con el proveedor real elegido. Además, para los 4 modelos que sí están en la tabla, la tarifa es **una sola** por modelo aplicada por igual a tokens de entrada y de salida, cuando los 4 proveedores cobran la salida varias veces más cara que la entrada (estructuralmente distinto, no es un tema de "se movió el precio"): el código no tiene forma de representar esa asimetría aunque quisiera.

Consecuencia: `B2B_LLM_MAX_COST_USD` (default $5.00, línea 129) es el único guardarraíl de gasto real del sistema, y su lectura de "cuánto llevamos gastado" puede estar sistemáticamente descalibrada frente al gasto real — de forma silenciosa, sin ningún log que compare lo estimado contra una factura real del proveedor. Es dinero mal contado, que es justo lo que este rubro pide sumar a mano contra el límite escrito.

Causa raíz probable: tabla de precios estática sin fecha de referencia ni prueba que la compare contra algo, y sin distinguir tarifa de entrada vs. salida.
(No cito cifras de mercado "actuales" para no inventar una comparación que no puedo verificar en esta ronda — el punto verificable por código, con certeza, es que la tarifa es una sola por modelo y que el fallback es un número arbitrario sin relación al proveedor configurado.)

### [ALTO] N+1: `process_file` relee hasta 200 facturas de la DB en cada iteración de un lote de hasta 1000 CFDI
`b2b_ai/services/pipeline.py:80-81` (`historico = db.list_invoices(tenant_id=tenant_id, limit=200) if db is not None and tenant_id else []`), dentro de `process_file`, llamada en loop desde `b2b_ai/api/v2.py:239-249` (`_process_batch_items`/`_process_one`, hasta `MAX_BATCH=1000` según línea 56) y desde `b2b_ai/services/pipeline.py:150-156` (`process_batch`).

Escenario con valores: `POST /api/v2/batch` (síncrono, que es el modo por default salvo que el cliente pida `async: true`) con 1000 rutas de CFDI ejecuta hasta 1000 `SELECT * FROM invoices WHERE tenant_id=? ORDER BY id DESC LIMIT 200` — uno por factura, cada uno trayendo y deserializando hasta 200 filas completas a dict (`db/db.py:308-334`). La consulta sí usa el índice `idx_invoices_tenant` (confirmado tanto en `migrations/versions/0002_indexes.py` como en `b2b_ai/db/models.py:74`), así que no es un table scan — pero son hasta 200,000 lecturas de fila acumuladas, secuenciales, sobre una sola conexión sin poolear, encima de las otras ~6 operaciones por factura que ya hace el pipeline (parse, validar, clasificar, aprobar, insertar, notificar). El propósito de `historico` es alimentar `detect_anomalies` contra duplicados recientes — un dato que cambia poco entre facturas consecutivas del mismo lote, salvo por las que el propio lote va insertando.

Consecuencia: en el escenario de mayor volumen que el propio endpoint anuncia soportar ("Procesa hasta 1000 CFDI en lote"), esta única función añade una cola de miles de queries redundantes al camino síncrono, sin que el cliente que llamó `POST /api/v2/batch` sin `async` tenga ninguna señal de progreso mientras espera.

Causa raíz probable: `historico` se recalcula por factura en vez de una vez por lote (o refrescarse solo cada N facturas).

### [MEDIO] El tamaño del pool (4) es fijo, no configurable, y su ruta de timeout no está manejada
`b2b_ai/db/pool.py:60-68` (`_acquire_raw`: `return self._pool.get(timeout=self.timeout)`, sin try/except) y `b2b_ai/api/v2.py:182` (`size=4` hardcodeado, sin variable de entorno).

Escenario: incluso ignorando el hallazgo CRÍTICO de Postgres (es decir, en un despliegue puramente SQLite), el pool de 4 conexiones de solo-lectura sirve **únicamente** `/api/v2/analytics`, `/api/v2/audit` y `/api/v2/export` — el endpoint de mayor volumen (`/batch`) no pasa por él, usa `db` directo. `queue.Queue.get(timeout=...)` lanza `queue.Empty` cuando el timeout (5.0s por default) se cumple sin conexión disponible; no hay ningún `try/except queue.Empty` en `pool.py` ni en `v2.py`, y no hay manejador de excepciones global en `app.py` para esta clase de error. Con 5 tenants refrescando dashboards de analytics casi al mismo tiempo (`TTLCache` de 30s hace que las lecturas se agrupen justo después de expirar el cache — es plausible que varias caduquen junto), el 5º request en adelante espera hasta 5s y, si sigue sin conexión libre, revienta con un 500 sin mensaje útil para operaciones.

Consecuencia: burst razonable de tráfico entre tenants → error genérico sin diagnóstico, en vez de un 503 con Retry-After como sí tiene el rate limiter por tenant (`v2.py:207-210`, que es el patrón correcto que faltó replicar aquí).

Causa raíz probable: `queue.Empty` no se traduce a una excepción HTTP legible.

### [BAJO] `BrowserAutomation` no define un método de cierre/liberación, y el único driver real ya escrito (para una interfaz hermana) no muestra reuso de sesión
`b2b_ai/computer_use/browser.py:39-77` (contrato `BrowserAutomation`: `navigate_to_erp`, `login`, `upload_cfdi`, `read_screen`, `click_element`, `type_text`, `health` — ningún `close()`/teardown) y `:221-228` (`_DEFAULT_BROWSER` como singleton de módulo compartido por todos los tenants/hilos).

Hoy `MockBrowser` no cuesta nada: es un dict en memoria, no hay proceso que arrancar ni cerrar, y esto lo confirma la propia clase (nada que crear más allá de atributos Python). Pero ya existe en el repo un driver real para automatización de navegador — `b2b_ai/computer_use/playwright_desktop.py` (interfaz hermana `DesktopAutomation`, no esta) — donde cada instancia de `PlaywrightDesktop(headless=True)` arranca su propio Chromium vía `async_playwright().start()` + `chromium.launch()` (líneas 80-81), sin ningún registro de pool o reuso entre llamadas visible en el archivo. Un arranque de Chromium headless típicamente toma un par de segundos y consume del orden de cientos de MB de RAM por instancia — cifras de referencia general de Playwright/Chromium, no medidas en este repo. Si el patrón de cableo que ya usa `browser.py` (`get_default_browser()` reutilizando una única instancia global) NO se replica al conectar el driver real, y en cambio se instancia un `PlaywrightDesktop` por request (el patrón que sí usa `_session()` en `reconciliation.py` para reconstruir servicios por request), cada subida de CFDI a CONTPAQi pagaría ese arranque completo.

Consecuencia: no hay bug hoy — es deuda que cobra factura el día que se conecte el driver real, y el contrato abstracto actual no obliga a nadie a diseñarlo con reuso de sesión.

Causa raíz probable: la interfaz `BrowserAutomation` no incluye lifecycle (`close`/`__aexit__`), así que nada fuerza a un futuro implementador a pensar en el costo de arranque.

## Lo que revisé y está bien

- `db/pool.py:70-78` (`_release_raw`): hace `rollback()` antes de devolver la conexión al pool y cierra la conexión en vez de reciclarla si algo falla — evita que una transacción a medias contamine al siguiente que la tome. Diseño correcto para lo que sí gobierna.
- `b2b_ai/services/bank_reconciliation.py:329-341` (`match_transactions`): los pases `_pass_exact` y `_pass_partial` corren ANTES que `_pass_ai` y consumen los pares ya resueltos (`_consumed`), así que el N×M del hallazgo CRÍTICO ya está reducido por diseño a solo lo que quedó sin conciliar — la intención de abaratar el camino caro está ahí, solo que no basta.
- `b2b_ai/services/llm.py:645-658` (`LLMService._run`): el gate de presupuesto se revisa ANTES de intentar red (`check_allowance()` primero), y toda excepción cae a reglas sin tumbar el pipeline — el patrón defensivo en sí (nunca crashear por culpa del LLM) está bien construido; el problema es la configuración del budget, no el patrón.
- `b2b_ai/api/v2.py:279-284` (`_process_one`): cada archivo del batch se envuelve en su propio try/except, así que una factura corrupta no tumba el lote completo de 1000 — buen manejo del peor caso de UNA factura, aunque no del peor caso agregado (hallazgo de N+1).
- `b2b_ai/api/v2.py` `/analytics` (línea 345-362): usa `TTLCache(ttl_seconds=30)` para no recalcular en cada request — mecanismo de ahorro de cómputo genuino, ya presente.
- `b2b_ai/db/db.py:117-126`: `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000` en cada conexión SQLite — mitigación correcta y deliberada para escritura concurrente, apropiada para el volumen que maneja hoy.
- `b2b_ai/db/db.py:39-49` (`_get_pg_pool`/`PGPool`): el pool correcto para Postgres SÍ existe en el repo, con tamaño configurable por env (`B2B_PG_POOL_MIN`/`MAX`/`B2B_PG_RETRIES`) — la pieza que falta no es diseñarlo, es que `v2.py` lo use en vez de reinventar uno SQLite-only (ver CRÍTICO #1).

## Lo que NO alcancé a revisar

- Latencia/timeout real contra los cuatro proveedores LLM en vivo — no hay API keys configuradas en este entorno de auditoría, todo lo anterior se verificó leyendo código y con una prueba de sandbox aislada (no repo) para el bug de `sqlite3.connect` contra un DSN Postgres.
- El contenido interno de `services/analytics.py` (`TTLCache`, `build_analytics`) — solo se revisó su uso desde `v2.py`, no su implementación.
- Cifras de mercado actuales de precio por proveedor — no las cité como comparación directa porque no puedo verificarlas en esta ronda sin salir a la red; el hallazgo de costo se sostiene solo con lo que el código permite demostrar por sí mismo (tarifa única combinada + fallback arbitrario).
- El comportamiento bajo concurrencia real (varios workers/procesos simultáneos) del singleton `_global_budget` — con `B2B_WORKERS>1` cada worker tendría su propio proceso y por tanto su propio singleton, lo que cambia el radio del hallazgo (por-worker en vez de por-flota); no confirmé cuántos workers usa el despliegue real.
- `b2b_ai/db/pg.py` en profundidad (los 3 bugs de Postgres ya documentados en `PG_BUG_REPORT.md` son del rubro de datos/arquitectura, no de este).
- Impacto de rendimiento de `computer_use/contpaqi_driver.py`/`aspel_driver.py`/`contpaqi_real_driver.py`/`aspel_real_driver.py` — se abrió solo `playwright_desktop.py` como evidencia de apoyo para el hallazgo BAJO; los demás no se leyeron completos.
