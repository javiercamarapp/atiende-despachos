# AUDITORÍA DE DESTRUCCIÓN — AGENTE + PRODUCCIÓN

**Fecha:** 2026-08-01
**Alcance:** `b2b_ai/agent/`, `b2b_ai/services/`, `b2b_ai/features/`, `b2b_ai/api/`, `b2b_ai/db/`, `b2b_ai/erp/`, `b2b_ai/monitoring/`
**Objetivo:** Encontrar bugs que destruirían el sistema en producción.

---

## ÍNDICE

1. [Clasificación errónea sin override](#1-clasificación-errónea-sin-override-humano)
2. [Pipeline de CFDIs — duplicados e idempotencia](#2-pipeline-de-cfdis--duplicados-e-idempotencia)
3. [Conciliación sin audit trail ni rollback](#3-conciliación-sin-audit-trail-ni-rollback)
4. [Confidence gate inexistente](#4-confidence-gate-inexistente)
5. [Memory leaks y connection leaks](#5-memory-leaks-y-connection-leaks)
6. [Timeouts inexistentes](#6-timeouts-inexistentes)
7. [Concurrencia y race conditions](#7-concurrencia-y-race-conditions)
8. [Rollback inexistente — estado inconsistente](#8-rollback-inexistente--estado-inconsistente)
9. [Monitoreo ciego](#9-monitoreo-ciego)
10. [Recovery inexistente tras crash](#10-recovery-inexistente-tras-crash)

---

## 1. CLASIFICACIÓN ERRÓNEA SIN OVERRIDE HUMANO

### Escenario destructivo
Un gasto de viaje (aviación, hotel, uber) contiene la palabra "vehiculo" en su descripción. El clasificador por keywords (`classify.py:23`) lo mapea a `activo_fijo` con confianza alta porque `"vehiculo"` está en la lista de keywords de `activo_fijo`. La póliza se registra en el ERP con cuenta `1210 Mobiliario y equipo` en vez de `6131 Gastos generales`.

### Impacto en producción
- **Contabilidad incorrecta:** Un gasto deducible al 100% (hospedaje, CFF Art. 45) se capitaliza como activo y se deprecia. El SAT ve un activo fijo que no existe → rechaza la deducción en auditoría.
- **DIOT incorrecta:** El IVA acreditamiento se registra en la cuenta equivocada → errores en la DIOT mensual.
- **Sin override humano:** No existe endpoint para que un contador cambie la categoría de una factura ya registrada. `classify_cfdi()` es fire-and-forget.

### Código problemático
```python
# classify.py — keywords ambiguas, sin contexto
KEYWORDS = {
    "activo_fijo": ["vehiculo", "escritorio", "monitor"],  # "monitor" de TV también matchea
    "gasto_operativo": ["combustible", "gasolina"],  # "vehiculo" vence por prioridad
}
```
La prioridad `PRIORITY = ["nomina", "activo_fijo", "inversion", "gasto_operativo"]` hace que `activo_fijo` gane sobre `gasto_operativo` aunque sea un falso positivo.

### Fix
1. **Override endpoint:** `PATCH /api/v1/invoices/{id}/reclassify` que permita al contador cambiar categoría y razón.
2. **Reglas de exclusión:** Keywords negativos (e.g., `"vehiculo"` + `"viaje"` → gasto_operativo).
3. **Confidence gate duro:** Si `confianza < 0.7`, NUNCA registrar en ERP sin aprobación explícita.

---

## 2. PIPELINE DE CFDIs — DUPLICADOS E IDEMPOTENCIA

### Escenario destructivo
El agente procesa un CFDI, registra la póliza en el ERP mock, y luego falla al enviar la notificación. El retry del batch vuelve a procesar el mismo XML. En el ERP mock (`contpaqi.py:37`) hay idempotencia (devuelve la póliza existente), pero **en la DB no**:

```python
# db.py — insert_invoice
try:
    cur = self.conn.execute("""INSERT INTO invoices ...""")
    inserted = True
except Exception as exc:
    if not _is_integrity_error(exc):
        raise
    self.conn.rollback()
    existing = self.conn.execute(
        "SELECT id FROM invoices WHERE tenant_id=? AND folio_fiscal=?",
        (tenant_id, row["folio_fiscal"])).fetchone()
    invoice_id = existing["id"] if existing else None
    inserted = False
```

### Impacto en producción
- **DB:** La segunda inserción falla por UNIQUE constraint y se maneja (devuelve `inserted=False`), **pero** la póliza ya se registró en el ERP real (CONTPAQi). El retry del pipeline llama a `register_erp` ANTES de `insert_invoice`, así que el ERP recibe el registro dos veces.
- **ERP real (CONTPAQi):** El mock es idempotente, pero el conector real (`contpaqi_desktop.py`) NO tiene dedup — cada llamada crea una póliza nueva.
- **Clasificación duplicada:** El `INSERT INTO classifications` se ejecuta después del catch de integridad, así que se inserta una clasificación extra para una factura existente sin verificar.

### Fix
1. **Check-before-insert:** Antes de llamar al ERP, verificar `inserted` o el folio fiscal en DB.
2. **Idempotencia en ERP connector:** Agregar `IF NOT EXISTS` lógico en el conector real.
3. **Idempotency key:** Usar `folio_fiscal` como idempotency key en todo el pipeline.

---

## 3. CONCILIACIÓN SIN AUDIT TRAIL NI ROLLBACK

### Escenario destructivo
`ConciliationService.reconcile_bank_statement()` (`features/conciliacion/service.py`) ejecuta el matching y devuelve resultados, pero:
- **No persiste los matches** — todo es en memoria.
- **No hay "undo"** — si el matching es incorrecto (e.g., matchea un pago de $10,000 contra una factura de $10,000 de otro proveedor), no hay forma de deshacerlo.
- **No hay audit trail** — no se registra quién ejecutó la conciliación ni qué criterios usó.

### Impacto en producción
- Un contador ejecuta la conciliación, confía en los resultados, y marca todo como conciliado en el ERP.
- Si el matching fue incorrecto (monto coincidente pero proveedor diferente), los estados financieros quedan mal.
- No hay forma de revertir: los datos originales no se marcaron como "conciliado" ni "pendiente".

### Fix
1. **Persistir conciliaciones:** Tabla `conciliation_sessions` con timestamp, usuario, criterios.
2. **Persistir matches:** Tabla `conciliation_matches` con `status: proposed | confirmed | rejected`.
3. **Soft delete:** Los matches se pueden marcar como `reverted` sin perder historial.

---

## 4. CONFIDENCE GATE INEXISTENTE

### Escenario destructivo
El clasificador devuelve `confianza: 0.30` (empate entre categorías). El agente loop (`loop.py:155-170`) revisa `requires_human_review`:

```python
requiere_rev = (clasif.get("requires_human_review", False)
                or anomalia["nivel"] == "alerta")
```

Si `policy == "auto_register"`, **el agente registra en el ERP aunque la confianza sea 0.0**:

```python
if policy == "auto_register":
    erp_res = self._register(tenant_id, datos, clasif)
    inv_id, inserted = self.db.insert_invoice(...)
```

### Impacto en producción
- El tenant tiene `policy_human_review: "auto_register"` (configurado por defecto al onboarding si el admin lo cambia).
- CFDIs con confianza 0.0 se registran automáticamente en el ERP con la categoría `desconocido` → cuenta `6100 Gastos por clasificar`.
- El contador no ve estas facturas hasta que genera el balance mensual → ya es tarde para corregir.
- **En pipeline.py:** El approval gate (`evaluate_approval`) solo filtra por monto, NO por confidence. Un CFDI de $49,000 con confianza 0.0 pasa directo al ERP.

### Fix
1. **Threshold de confianza:** `confianza < 0.5` → SIEMPRE hold, sin importar la policy.
2. **Endpoint de configuración:** Permitir al tenant configurar su propio umbral de confianza.
3. **Dashboard de pendientes:** Mostrar facturas con baja confianza prominentemente.

---

## 5. MEMORY LEAKS Y CONNECTION LEAKS

### Escenario destructivo
Procesamiento batch de 10,000 CFDIs:

1. **ERP singleton global leak** (`tools.py:80-87`):
```python
_tool_erp = None
def _get_default_erp():
    global _tool_erp
    if _tool_erp is None:
        _tool_erp = MockCONTPAQi()
    return _tool_erp
```
El MockCONTPAQi acumula `self._polizas` (dict) en memoria. Tras 10,000 CFDIs, el dict tiene 10,000 entradas que nunca se liberan.

2. **DB connections por thread** (`db.py`):
```python
self._local = threading.local()
# ...
self._connections.add(conn)  # set que nunca se limpia
```
Cada hilo de uvicorn crea una conexión SQLite que se añade a `self._connections`. Si el servidor recrea threads (worker recycling), las conexiones viejas siguen en el set.

3. **Alert history en memoria** (`alerts.py:46`):
```python
_HISTORY_MAX = 500  # solo limita el historial de alertas
```
Pero las series de métricas dentro de `AlertEngine._series` no tienen límite — cada punto de datos acumula indefinidamente.

### Impacto en producción
- OOM después de procesar un batch grande.
- File descriptor exhaustion (SQLite abre un archivo por conexión).
- El health check no reporta el uso de memoria de estas estructuras internas.

### Fix
1. **LRU en ERP singleton:** Limitar `_polizas` a las últimas 1,000 entradas.
2. **Connection cleanup:** `_connections.discard(conn)` cuando el thread muere.
3. **Series trimming:** Las series de métricas deben tener maxlen como los samples de latencia.

---

## 6. TIMEOUTS INEXISTENTES

### Escenario destructivo

1. **SAT validator** (`sat/validator.py`): Es un mock determinista, pero el SAT real puede tardar 30+ segundos. No hay timeout configurado.

2. **LLM calls** (`llm.py`): Las llamadas a OpenAI/Anthropic no tienen timeout:
```python
# No se ve timeout en las llamadas HTTP del LLM
response = self.client.chat.completions.create(...)
```
Si el LLM tarda 120 segundos, el pipeline entero se bloquea.

3. **CONTPAQi real** (`contpaqi_desktop.py`): Los cursores SQL se cierran manualmente pero sin timeout. Si CONTPAQi se cuelga, el cursor queda abierto indefinidamente.

4. **Pipeline completo:** `process_file()` es síncrono y secuencial. Si cualquier paso (parse, validate, classify, register, notify) se cuelga, el worker de uvicorn queda bloqueado.

### Impacto en producción
- Worker starvation: todos los workers de uvicorn bloqueados esperando al SAT.
- El health check sigue reportando "ok" porque la DB responde.
- No hay circuit breaker — el sistema sigue intentando llamar a servicios caídos.

### Fix
1. **Timeout por paso:** SAT (10s), LLM (30s), ERP (15s), Email (5s).
2. **Circuit breaker:** Si SAT falla 3 veces, abrir circuito por 60s.
3. **Async pipeline:** Usar `asyncio` o al menos `concurrent.futures` con timeout.

---

## 7. CONCURRENCIA Y RACE CONDITIONS

### Escenario destructivo
Dos usuarios del mismo tenant procesan el mismo CFDI simultáneamente (e.g., lo subieron por duplicado al email).

**Race condition 1: DB insert**
```python
# db.py — insert_invoice
try:
    cur = self.conn.execute("INSERT INTO invoices ...")
    inserted = True
except Exception as exc:
    if not _is_integrity_error(exc):
        raise
```
Con SQLite, esto funciona por el WAL + busy_timeout. Pero con PostgreSQL, dos conexiones concurrentes pueden ambas pasar el `SELECT` y ambas intentar `INSERT` — una falla, pero la otra ya llamó al ERP.

**Race condition 2: ERP registration**
```python
# contpaqi.py — register_invoice
existing = self._polizas.get(folio)
if existing:
    return {..., "duplicate": True}
```
El dict en memoria NO es thread-safe. Dos threads pueden leer `existing = None` simultáneamente y ambas crear una póliza nueva.

**Race condition 3: Connection pool**
```python
# pool.py — _acquire_raw
try:
    return self._pool.get_nowait()
except queue.Empty:
    with self._lock:
        if self._created < self.size:
            conn = self._open()
            self._created += 1
            return conn
```
Después del `with self._lock`, se suelta el lock y hace `return conn`. Pero `_created` ya se incrementó. Si el thread es interrumpido antes de `return`, la conexión se pierde y el contador está mal.

### Impacto en producción
- Pólizas duplicadas en CONTPAQi real.
- Facturas duplicadas en la DB (con PostgreSQL sin el UNIQUE constraint correcto).
- Connection pool exhaustion.

### Fix
1. **SELECT FOR UPDATE** en PostgreSQL antes de insert.
2. **Lock en ERP mock** (o mejor, usar la DB como source of truth).
3. **Connection pool:** Hacer el incremento atómico con el return.

---

## 8. ROLLBACK INEXISTENTE — ESTADO INCONSISTENTE

### Escenario destructivo
El agente procesa un CFDI:
1. ✅ Parse exitoso
2. ✅ Validación exitosa
3. ✅ Clasificación exitosa
4. ✅ Registro en ERP exitoso (póliza POL-ABC123 creada)
5. ❌ `insert_invoice` falla por error de DB (disk full, connection lost)

**Resultado:** La póliza existe en CONTPAQi pero NO en la DB del agente. El CFDI queda en el limbo — el agente no sabe que ya lo procesó, y si se reintenta, crea una segunda póliza.

Lo mismo ocurre al revés:
1. ✅ ERP registration
2. ❌ Notification fails

El pipeline (`pipeline.py`) no tiene transacciones que agrupen ERP + DB + notification.

### Impacto en producción
- **Estado fantasma:** Pólizas en ERP sin registro en DB → el dashboard no las muestra pero el contador las ve en CONTPAQi.
- **Reintento peligroso:** Sin check de idempotencia, reintentar crea duplicados.
- **Sin compensación:** No hay saga pattern ni compensating transactions.

### Fix
1. **Orden correcto:** Insertar en DB PRIMERO, luego registrar en ERP (al revés del actual).
2. **Status field:** `invoices.erp_status = pending | registered | failed`.
3. **Compensating transaction:** Si ERP falla después de DB, marcar como `erp_failed` y reintentar.

---

## 9. MONITOREO CIEGO

### Escenario destructivo
El agente falla silenciosamente en producción. ¿Cómo nos enteramos?

**Lo que SÍ existe:**
- `audit_log` en DB (registra cada tool call con status).
- `AlertEngine` con reglas de error_rate y latency_p95.
- JSON structured logging (`monitoring/logger.py`).
- Health endpoint con DB, Redis, disco, memoria.

**Lo que NO existe:**
- **No hay alertas sobre el agente mismo.** Las reglas de alerta son sobre requests HTTP (`b2b_requests_total`, `b2b_errors_total`). Si el agente procesa CFDIs en batch (no vía HTTP), no hay métricas.
- **No hay dead man's switch.** Si el agente deja de procesar por completo, nadie se entera.
- **No hay métricas de negocio.** No se trackea: CFDIs procesados por hora, tasa de error de clasificación, tasa de aprobación humana, tiempo promedio de procesamiento.
- **Logs sin correlación.** El `request_context` usa contextvars, pero el agente loop no crea un request_context — los logs del agente no tienen request_id.
- **No hay Sentry/Datadog real.** El `sentry_adapter.py` existe pero es un stub.

### Impacto en producción
- El agente puede estar fallando el 100% de los CFDIs durante días sin que nadie lo sepa.
- No hay forma de saber cuántos CFDIs están pendientes de revisión humana.
- Los logs son inútiles para debugging porque no hay correlación entre pasos del pipeline.

### Fix
1. **Métricas del agente:** `b2b_agent_processed_total`, `b2b_agent_errors_total`, `b2b_agent_confidence_avg`.
2. **Dead man's switch:** Cron job que verifica que el agente procesó al menos 1 CFDI en las últimas 24h (si hay cola).
3. **Request context en agent loop:** `with request_context(tenant_id=tenant_id):` al inicio de `process()`.
4. **Integración real con Sentry:** El adapter existe, solo falta configurarlo.

---

## 10. RECOVERY INEXISTENTE TRAS CRASH

### Escenario destructivo
El agente procesa un batch de 500 CFDIs. Al CFDI #237, el proceso crash (OOM, segfault, kill -9).

**Lo que se pierde:**
- Los CFDIs 238-500 nunca se procesaron. No hay cola persistente — el batch era una lista en memoria.
- Los CFDIs que estaban "en vuelo" (parse hecho, ERP registrado, DB no) quedan en estado fantasma.
- No hay checkpoint — al reiniciar, no se sabe dónde se quedó.

**Lo que NO hay:**
- **No hay job queue persistente.** El procesamiento batch usa `glob.glob()` + loop for. Si el proceso muere, la lista se pierde.
- **No hay retry automático.** Los CFDIs que fallan se escalan a revisión humana pero no se reintentan.
- **No hay graceful shutdown.** No hay signal handler (SIGTERM) que termine el CFDI actual antes de morir.
- **No hay idempotency key en el pipeline.** Al reiniciar, no se puede saber qué CFDIs ya se procesaron.

### Impacto en producción
- Después de un crash, el equipo contable no sabe qué facturas quedaron pendientes.
- Si el crash fue por un CFDI malformado, el reintento crash de nuevo (poison pill).
- En un deploy (rolling update), los CFDIs en procesamiento se pierden.

### Fix
1. **Job queue persistente:** Usar Redis/Celery o una tabla `job_queue` en PostgreSQL.
2. **Checkpoint:** Guardar el progreso del batch en DB (`batch_progress(batch_id, last_processed_id)`).
3. **Poison pill handling:** Si un CFDI causa crash 3 veces, marcarlo como `poison` y saltarlo.
4. **Graceful shutdown:** Signal handler que complete el CFDI actual y guarde checkpoint.

---

## RESUMEN DE CRITICIDAD

| # | Bug | Severidad | Probabilidad | Impacto |
|---|-----|-----------|--------------|---------|
| 1 | Clasificación errónea sin override | 🔴 CRÍTICO | Alta | Contabilidad incorrecta, SAT rechaza deducción |
| 2 | Duplicados en ERP real | 🔴 CRÍTICO | Alta | Pólizas duplicadas, auditoría fallida |
| 3 | Conciliación sin rollback | 🟡 ALTO | Media | Estados financieros incorrectos |
| 4 | Confidence gate inexistente | 🔴 CRÍTICO | Alta | Facturas mal clasificadas registradas automáticamente |
| 5 | Memory leaks | 🟡 ALTO | Media | OOM en batch grande |
| 6 | Timeouts inexistentes | 🔴 CRÍTICO | Alta | Worker starvation, sistema colgado |
| 7 | Race conditions | 🟡 ALTO | Baja-Media | Duplicados bajo carga concurrente |
| 8 | Sin rollback/compensación | 🔴 CRÍTICO | Media | Estado inconsistente ERP vs DB |
| 9 | Monitoreo ciego | 🟡 ALTO | Alta | Fallos silenciosos sin alerta |
| 10 | Sin recovery tras crash | 🔴 CRÍTICO | Media | Pérdida de trabajo en cola |

**Total bugs encontrados:** 10 categorías, ~25 bugs individuales.
**Bugs críticos (bloquean producción):** 6 de 10.

---

## PLAN DE REMEDIACIÓN PRIORITIZADO

### Sprint 1 (antes de production launch)
1. Confidence gate duro (< 0.5 → siempre hold)
2. Override endpoint para reclasificar
3. Idempotencia en ERP connector real
4. Timeout en todas las llamadas externas

### Sprint 2 (primeras 2 semanas en prod)
5. Job queue persistente (Redis/Celery)
6. Métricas del agente + dead man's switch
7. Request context en agent loop
8. Orden correcto: DB primero, ERP después

### Sprint 3 (estabilización)
9. Persistir conciliaciones con audit trail
10. Connection pool hardening
11. Graceful shutdown + poison pill handling
12. Circuit breaker para servicios externos
