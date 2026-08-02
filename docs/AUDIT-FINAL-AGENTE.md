# AUDITORÍA FINAL — Sistema Agéntico & Tool Calling
**Fecha:** 2026-08-01
**Alcance:** `b2b_ai/agent/`, `b2b_ai/tools/`, `b2b_ai/services/`, `b2b_ai/features/bookkeeping/`, `b2b_ai/infrastructure/`, `b2b_ai/monitoring/`

---

## Resumen Ejecutivo

| Categoría | Hallazgos | Críticos | Altos | Medios | Bajos |
|-----------|-----------|----------|-------|--------|-------|
| 1. Agent Loop | 3 | 0 | 1 | 1 | 1 |
| 2. Tool Registry | 3 | 0 | 1 | 1 | 1 |
| 3. Confidence Gate | 2 | 0 | 1 | 1 | 0 |
| 4. Classification ML | 4 | 0 | 1 | 2 | 1 |
| 5. Pipeline Orchestration | 4 | 1 | 1 | 1 | 1 |
| 6. LLM Integration | 3 | 0 | 1 | 1 | 1 |
| 7. Error Recovery | 3 | 1 | 1 | 1 | 0 |
| 8. Human Override | 3 | 0 | 1 | 1 | 1 |
| 9. Monitoring | 2 | 0 | 0 | 1 | 1 |
| 10. Cost Control | 2 | 0 | 0 | 1 | 1 |
| **TOTAL** | **29** | **2** | **8** | **11** | **8** |

**Veredicto:** El sistema tiene una arquitectura sólida con fallbacks y circuit breaker, pero tiene **2 problemas críticos** (estado inconsistente en fallo parcial del pipeline de producción y sin rollback real) y **8 problemas altos** que deben corregirse antes de producción con datos reales.

---

## 1. Agent Loop (`b2b_ai/agent/loop.py`)

### AG-01 — Sin retry en tool calls del agent loop
- **Archivo:** `b2b_ai/agent/loop.py:67-77`
- **Severidad:** 🟠 ALTO
- **Descripción:** `_call()` ejecuta `call_tool()` una sola vez. Si una tool falla por error transitorio (timeout de red al ERP, SAT no responde), el agente la marca como error y escala a humano inmediatamente. No hay retry con backoff.
- **Impacto:** Facturas válidas escaladas innecesariamente a revisión humana por errores transitorios.
- **Fix:** Envolver `_call()` con el decorator `@with_retry` ya existente en `infrastructure/retry.py`:
```python
from b2b_ai.infrastructure.retry import with_retry, SERVICE_RETRY_CONFIGS

def _call(self, name, tenant_id, **kwargs):
    @with_retry(service="tool_call", config=SERVICE_RETRY_CONFIGS.get("llm_calls"))
    def _do_call():
        return call_tool(name, **kwargs)
    # ... logging y error handling
```

### AG-02 — Timeout no aplicado a todas las tool calls
- **Archivo:** `b2b_ai/agent/loop.py:67-77` vs `b2b_ai/agent/loop.py:175-177`
- **Severidad:** 🟡 MEDIO
- **Descripción:** El timeout con `with_timeout()` solo se aplica a `classify_invoice` y `detect_anomaly` (llamadas LLM). Las tool calls directas (`parse_cfdi`, `validate_cfdi`, `register_erp`, `send_notification`) no tienen timeout.
- **Impacto:** Si el parser XML o el ERP se cuelgan, el worker se bloquea indefinidamente.
- **Fix:** Aplicar `with_timeout` genérico en `_call()`:
```python
TIMEOUT_TOOL_DEFAULT = 30

def _call(self, name, tenant_id, **kwargs):
    timeout = TIMEOUT_ERP if "erp" in name else TIMEOUT_TOOL_DEFAULT
    result = with_timeout(call_tool, timeout, name)(name, **kwargs)
```

### AG-03 — Confidence threshold configurable por tenant (BIEN implementado)
- **Archivo:** `b2b_ai/agent/loop.py:200`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** El threshold se lee del config del tenant (`cfg.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)`). Esto es correcto y permite calibrar por cliente.
- **Nota:** Solo documentar que el valor default es 0.7 y cómo configurarlo por tenant.

---

## 2. Tool Registry (`b2b_ai/tools/`)

### TR-01 — Sin validación de parámetros en call_tool
- **Archivo:** `b2b_ai/tools/registry.py:92-97`
- **Severidad:** 🟠 ALTO
- **Descripción:** `call_tool()` invoca `tdef(**kwargs)` directamente sin validar contra el schema registrado. Si se pasa un parámetro incorrecto o falta uno requerido, el error se propaga como un `TypeError` genérico sin contexto de qué tool falló ni qué parámetros se esperaban.
- **Impacto:** Difícil de debuggear en producción; el audit log registra el error pero no los parámetros inválidos.
- **Fix:** Validar parámetros contra `tdef.parameters` antes de la invocación:
```python
def call_tool(name, **kwargs):
    tdef = get_tool(name)
    if tdef is None:
        raise KeyError(f"Tool no registrada: {name}")
    # Validar requeridos
    required = {p["name"] for p in tdef.parameters if p.get("required")}
    missing = required - set(kwargs.keys())
    if missing:
        raise ValueError(f"Tool '{name}': parámetros requeridos faltantes: {missing}")
    return tdef(**kwargs)
```

### TR-02 — 15 tools registradas, coverage completo
- **Archivo:** `b2b_ai/tools/tools.py:34-213`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** Tools registradas: `parse_cfdi`, `validate_cfdi`, `classify_expense`, `register_erp`, `send_notification`, `reconcile_bank`, `generate_report`, `parse_bank_statement`, `reconciliation_report`, `calculate_payroll`, `build_balance`, `send_balance_to_sat`, `detect_anomalies`, `evaluate_approval`. Todas con descripción y schema. Coverage completo para el pipeline de 5 agentes.
- **Nota:** Falta tool `classify_expense` usar el LLM (usa solo reglas). Ver AG-04.

### TR-03 — Router basado en keywords frágil
- **Archivo:** `b2b_ai/tools/router.py:17-46`
- **Severidad:** 🟡 MEDIO
- **Descripción:** El router usa coincidencia de substring (`p in text`). "banco" matcha con "banco de datos" o "banco central". No hay fuzzy matching ni LLM-based routing.
- **Impacto:** Baja probabilidad de uso real del router (el pipeline orquesta directamente), pero si se usa para intents libres, puede enrutar mal.
- **Fix:** Para MVP es aceptable. Documentar que el router es determinístico y no se usa en el pipeline principal (que orquesta directamente).

---

## 3. Confidence Gate

### CG-01 — Gate de confianza bien implementado con override humano
- **Archivo:** `b2b_ai/agent/loop.py:199-225`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** El confidence gate funciona correctamente:
  1. Lee `confidence_threshold` del config del tenant (default 0.7)
  2. Si `confianza < threshold` → `low_confidence = True`
  3. Si `low_confidence` → siempre escala a humano (incluso con `auto_register`)
  4. Crea `review_id` en DB para que un contador lo resuelva
- **Nota:** El umbral 0.7 es conservador. Para producción, considerar 0.75 para servicios profesionales.

### CG-02 — Doble umbral de confianza inconsistente
- **Archivo:** `b2b_ai/agent/loop.py:200` (threshold=0.7) vs `b2b_ai/services/classify.py:119` (threshold=0.70) vs `b2b_ai/features/bookkeeping/auto_classifier.py:327` (CONFIDENCE_MEDIUM=0.60)
- **Severidad:** 🟠 ALTO
- **Descripción:** Hay TRES umbrales de confianza diferentes:
  - AgentLoop: 0.7 (configurable por tenant)
  - classify_cfdi (reglas): 0.70 hardcodeado en `requires`
  - AutoClassifier (ML): CONFIDENCE_MEDIUM = 0.60
- **Impacto:** Un CFDI con confianza 0.65 pasa el gate ML pero es escalado por el agent loop. Los thresholds deben unificarse.
- **Fix:** Centralizar el threshold en una sola constante/config y usarla en los tres lugares.

---

## 4. Classification ML (`b2b_ai/features/bookkeeping/auto_classifier.py`)

### ML-01 — Modelo se entreña con datos sintéticos, no con datos reales
- **Archivo:** `b2b_ai/features/bookkeeping/auto_classifier.py:234-284`
- **Severidad:** 🟠 ALTO
- **Descripción:** `generate_synthetic_dataset()` genera datos artificiales combinando keywords predefinidos. El modelo nunca ve datos reales de CFDIs mexicanos. El train accuracy es engañoso (~99%) porque los datos sintéticos son predecibles.
- **Impacto:** El modelo no generaliza a CFDIs reales con descripciones variadas, typos, o abreviaturas.
- **Fix:**
  1. Implementar pipeline de ingestión de CFDIs reales (los que ya pasan por el sistema)
  2. Usar `human_override.get_suggestions_for_retraining()` como señal de entrenamiento
  3. Ejecutar retraining periódico con datos reales

### ML-02 — Cross-validation deshabilitado
- **Archivo:** `b2b_ai/features/bookkeeping/auto_classifier.py:393-394`
- **Severidad:** 🟡 MEDIO
- **Descripción:** El comment dice "skip cross-validation for speed" y solo calcula `train_accuracy`. Sin CV, no se detecta overfitting.
- **Fix:** Agregar al menos 3-fold CV:
```python
scores = cross_val_score(self._model, X, y, cv=3, scoring='accuracy')
cv_acc = float(scores.mean())
```

### ML-03 — Fallback rule-based funciona correctamente
- **Archivo:** `b2b_ai/features/bookkeeping/auto_classifier.py:454-471`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** `_rule_based_predict()` usa keyword matching contra los mismos `SYNTHETIC_PATTERNS`. Es determinístico y no falla. Correcto como fallback cuando sklearn no está disponible.

### ML-04 — Override por RFC aprende pero no se persiste
- **Archivo:** `b2b_ai/features/bookkeeping/auto_classifier.py:413-415` y `b2b_ai/features/bookkeeping/human_override.py:69-71`
- **Severidad:** 🟡 MEDIO
- **Descripción:** `AutoClassifier.add_override(rfc, category)` guarda en memoria (`self._overrides`). `HumanOverrideManager` también guarda en memoria. Si el proceso se reinicia, se pierde todo el aprendizaje.
- **Fix:** Persistir los overrides en la DB (tabla `classification_overrides` con RFC, categoría, count, last_updated).

---

## 5. Pipeline Orchestration

### PO-01 — ⛔ CRÍTICO: Sin rollback en fallo parcial del pipeline de producción
- **Archivo:** `b2b_ai/services/pipeline.py:50-229`
- **Severidad:** 🔴 CRÍTICO
- **Descripción:** En `process_file()`:
  1. Se registra en DB con `erp_status=pending` (línea 138-139) ✅
  2. Se calcula `erp_res` ANTES de la inserción DB (líneas 122-133) ❌
  3. El bloque `try/except` en líneas 142-147 tiene `pass` — nunca actualiza la DB con el resultado real del ERP
  4. Si el ERP registra OK pero la notificación falla, no hay rollback del ERP
- **Impacto:** Pólizas fantasma en ERP sin registro en DB, o viceversa. Estado inconsistente.
- **Fix:** Reordenar: primero insertar en DB con status `pending`, luego registrar en ERP, luego actualizar DB con resultado. Si ERP falla, marcar DB como `erp_failed`. Si notificación falla, no afecta el estado fiscal.

### PO-02 — Pipeline de bookkeeping: jobs en memoria, no persistidos
- **Archivo:** `b2b_ai/features/bookkeeping/pipeline.py:63`
- **Severidad:** 🟠 ALTO
- **Descripción:** `self._jobs: Dict[str, PipelineJob] = {}` — los jobs viven en memoria. Si el proceso se reinicia, se pierden todos los jobs con su estado.
- **Impacto:** En producción con restarts de pods, los jobs en progreso se pierden.
- **Fix:** Persistir `PipelineJob` en la DB (tabla `pipeline_jobs` con stage, progress, errors, classifications).

### PO-03 — Checkpoint en batch funciona correctamente
- **Archivo:** `b2b_ai/services/pipeline.py:232-264`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** `process_batch()` soporta `checkpoint_file` para reanudar batches interrumpidos. Lee el set de archivos ya procesados y los salva después de cada archivo. Al terminar, borra el checkpoint. Correcto.

### PO-04 — Error en un CFDI no detiene el batch
- **Archivo:** `b2b_ai/services/pipeline.py:257-258`
- **Severidad:** 🟡 MEDIO
- **Descripción:** En `process_batch()`, si un CFDI falla, se registra el error y se continúa con el siguiente. Esto es correcto para resiliencia, pero el error se registra como dict suelto sin intento de retry.
- **Fix:** Agregar retry individual por archivo (usando `with_retry`), y solo después agregar al resultado de error.

---

## 6. LLM Integration (`b2b_ai/services/llm.py`)

### LI-01 — Fallback a reglas funciona correctamente en todas las tareas
- **Archivo:** `b2b_ai/services/llm.py:672-753`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** Todas las tareas (`classify_invoice`, `extract_data`, `summarize`, `detect_anomaly`) tienen try/except con fallback a reglas. El pipeline nunca se cae por culpa del LLM. `last_source` indica si fue 'llm' o 'rules'.
- **Nota:** El patrón `except Exception` es amplio pero aceptable para un fallback.

### LI-02 — Circuit breaker NO integrado con LLM calls
- **Archivo:** `b2b_ai/infrastructure/circuit_breaker.py:404-409` define `llm_calls`, `b2b_ai/services/llm.py:636-658` no lo usa
- **Severidad:** 🟠 ALTO
- **Descripción:** Se definió un circuit breaker para `llm_calls` con config (failure_threshold=8, recovery=20s), pero `LLMService._run()` NO lo usa. Si el proveedor LLM está caído, cada llamada espera el timeout completo (30s) antes de caer a reglas. Con 100 CFDIs = 50 minutos desperdiciados.
- **Fix:** Integrar el circuit breaker en `_run()`:
```python
from b2b_ai.infrastructure.circuit_breaker import get_or_create_breaker
_llm_breaker = get_or_create_breaker("llm_calls", fallback=None)

def _run(self, task, payload):
    with _llm_breaker:
        text = self.client.complete(messages, max_tokens=max_tokens)
    # fallback a reglas si circuit open
```

### LI-03 — HTTP timeout hardcodeado en providers
- **Archivo:** `b2b_ai/services/llm.py:333` (`timeout=15`), `b2b_ai/infrastructure/config.py:206` (`timeout: int = 60`)
- **Severidad:** 🟡 MEDIO
- **Descripción:** `_http_post_json()` usa `timeout=15` por defecto, pero `LLMSettings.timeout` es 60. El timeout de 15s no se configura desde el settings. Además, el timeout de la env `B2B_LLM_TIMEOUT` (config.py:322) tampoco se propaga al HTTP call.
- **Fix:** Propagar `settings.llm.timeout` al constructor de cada provider y usarlo en `_http_post_json()`.

---

## 7. Error Recovery

### ER-01 — ⛔ CRÍTICO: Estado inconsistente en fallo parcial del pipeline principal
- **Archivo:** `b2b_ai/services/pipeline.py:135-147`
- **Severidad:** 🔴 CRÍTICO
- **Descripción:** El flujo es:
  1. Línea 138: `db.insert_invoice()` con `erp=pending_erp` → DB tiene status "pending"
  2. Línea 122-133: `erp_res` ya fue calculado ANTES de la inserción DB
  3. Línea 142-147: `if erp_res.get("ok")` → `pass` (no-op)
- **Resultado:** La DB nunca se actualiza con el resultado real del ERP. Todas las facturas quedan con `erp_status=pending` indefinidamente.
- **Fix:** Después de `db.insert_invoice()`, hacer `db.update_invoice_erp_status(inv_id, erp_res)`.

### ER-02 — Agent loop: escalada correcta en parse fallido
- **Archivo:** `b2b_ai/agent/loop.py:127-138`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** Si el parser falla, se escala a humano con razón `parse_failed` y NO se intenta registrar en ERP. Correcto.

### ER-03 — Fallo en notificación no bloquea el pipeline
- **Archivo:** `b2b_ai/agent/loop.py:94-95` y `b2b_ai/services/pipeline.py:211-212`
- **Severidad:** 🟠 ALTO
- **Descripción:** En ambos pipelines, si la notificación falla, se captura la excepción y se continúa. Esto es correcto para no perder el registro fiscal. Sin embargo, no hay retry ni se marca como "notification_failed" para reintento posterior.
- **Fix:** Persistir notificaciones pendientes en DB (tabla `pending_notifications`) y procesarlas con un worker de reintento.

---

## 8. Human Override (`b2b_ai/features/bookkeeping/human_override.py`)

### HO-01 — Override endpoint implementado correctamente
- **Archivo:** `b2b_ai/features/bookkeeping/human_override.py:40-77`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** `submit_override()` permite corregir clasificaciones con:
  - UUID del CFDI
  - Acción (RECLASSIFY, etc.)
  - Nueva categoría y cuentas contables
  - Auditoría (corrected_by, reason, timestamp)
  - Agregación por RFC para aprendizaje

### HO-02 — Feedback loop existe pero no se conecta al clasificador automáticamente
- **Archivo:** `b2b_ai/features/bookkeeping/human_override.py:141-163` y `b2b_ai/features/bookkeeping/auto_classifier.py:432-434`
- **Severidad:** 🟠 ALTO
- **Descripción:** `get_suggestions_for_retraining()` genera datos de retraining con >50% de concordancia, pero nadie llama a `AutoClassifier.train()` con esos datos. El loop de feedback está roto.
- **Fix:** Implementar un endpoint `/admin/retrain` o un cron job que:
  1. Llame a `override_manager.get_suggestions_for_retraining()`
  2. Mezcle con datos sintéticos
  3. Llame a `classifier.train()` con los datos combinados
  4. Persista el modelo con `classifier.save()`

### HO-03 — Overrides en memoria, no persistidos
- **Archivo:** `b2b_ai/features/bookkeeping/human_override.py:33-34`
- **Severidad:** 🟡 MEDIO
- **Descripción:** `self._overrides: List[OverrideRecord] = []` — todo en memoria. Igual que ML-04.
- **Fix:** Persistir en tabla `classification_overrides`.

---

## 9. Monitoring

### MO-01 — Métricas Prometheus implementadas pero no conectadas al agente
- **Archivo:** `b2b_ai/monitoring/metrics.py:64-251`
- **Severidad:** 🟡 MEDIO
- **Descripción:** El `MetricsRegistry` tiene contadores para `invoices_processed` y `anomalies_detected`, pero ni el `AgentLoop` ni el `services/pipeline.py` los llaman. Las métricas de negocio no se registran automáticamente.
- **Fix:** En `AgentLoop.process()` y `process_file()`, llamar:
```python
from b2b_ai.monitoring.metrics import metrics
metrics.inc_invoices()
if anomalia["nivel"] == "alerta":
    metrics.inc_anomalies()
```

### MO-02 — Alertas implementadas para infraestructura, no para accuracy de clasificación
- **Archivo:** `b2b_ai/monitoring/alerts.py:201-210`
- **Severidad:** 🟢 BAJO
- **Descripción:** Las alertas default son `error_rate > 5%` y `latency_p95 > 2s`. No hay alerta para:
  - Tasa de clasificación "desconocido" > 20%
  - Tasa de override humano > 30% (señal de degradación del modelo)
  - Tasa de fallback a reglas > 50%
- **Fix:** Agregar reglas de alerta específicas para el dominio contable.

---

## 10. Cost Control

### CC-01 — Token budget implementado correctamente
- **Archivo:** `b2b_ai/services/llm.py:107-200`
- **Severidad:** 🟢 BAJO (positivo)
- **Descripción:** `TokenBudget` controla:
  - Max tokens input/output por llamada
  - Max llamadas por sesión
  - Max costo USD por sesión
  - Tracking acumulativo de tokens y costo
  - Configurable via env vars
  - Estimación rough (~4 chars/token)
- **Nota:** La estimación de tokens es imprecisa (±30%). Para producción, usar `tiktoken` o el tokenizer real del modelo.

### CC-02 — Model routing no implementado
- **Archivo:** `b2b_ai/services/llm.py:575-589`
- **Severidad:** 🟡 MEDIO
- **Descripción:** `get_llm()` selecciona UN proveedor basado en la env `B2B_LLM_PROVIDER`. No hay routing inteligente:
  - No selecciona modelo más barato para tareas simples
  - No usa fallback automático entre proveedores
  - No balancea entre proveedores
- **Impacto:** Si OpenAI falla, no se cae automáticamente a DeepSeek o Anthropic.
- **Fix:** Implementar provider chain con fallback:
```python
def get_llm_with_fallback():
    providers = ["openai", "deepseek", "anthropic"]
    for p in providers:
        try:
            return get_llm(p)
        except LLMError:
            continue
    return MockLLM()
```

---

## Anexo: Inventario de Componentes

### Arquitectura del Agente
```
AgentLoop (loop.py)
  ├── parse_cfdi → validate_cfdi → classify(LLM) → detect_anomaly(LLM)
  ├── Confidence gate (configurable por tenant)
  ├── Decision tree: auto_processed | needs_review | parse_failed | invalid
  ├── register_erp (si auto_processed o policy=auto_register)
  ├── send_notification (email/whatsapp)
  └── create_review (HITL)
```

### Pipeline de Producción
```
process_file (services/pipeline.py)
  ├── parse → validate → PII detect → EFOS 69-B → SAT status
  ├── classify (reglas) → detect_anomalies → evaluate_approval
  ├── DB insert (erp=pending) → ERP register → notification
  └── [BUG: DB no se actualiza con resultado ERP]
```

### Pipeline de Bookkeeping
```
PipelineOrchestrator (bookkeeping/pipeline.py)
  ├── AutoClassifier (ML + rules fallback)
  ├── AccountingRulesEngine (NIF mappings)
  ├── JournalEntryGenerator (pólizas)
  ├── ERPRegistrar (idempotent)
  └── HumanOverrideManager (feedback loop)
```

### Tools Registradas (15)
| Tool | Categoría | Usada en Pipeline |
|------|-----------|-------------------|
| parse_cfdi | parse | ✅ Ambos |
| validate_cfdi | validate | ✅ Ambos |
| classify_expense | classify | ✅ services/pipeline |
| register_erp | erp | ✅ Ambos |
| send_notification | notify | ✅ Ambos |
| detect_anomalies | anomaly | ✅ services/pipeline |
| evaluate_approval | approval | ✅ services/pipeline |
| reconcile_bank | reconcile | ✅ Agente 3 |
| parse_bank_statement | reconcile | ✅ Agente 3 |
| reconciliation_report | reconcile | ✅ Agente 3 |
| calculate_payroll | payroll | ✅ Agente 4 |
| build_balance | accounting | ✅ Agente 5 |
| send_balance_to_sat | accounting | ✅ Agente 5 |
| generate_report | report | ✅ Dashboard |

### Infraestructura Disponible
| Componente | Estado | Integrado con Agente |
|------------|--------|---------------------|
| Circuit Breaker | ✅ Implementado | ❌ No usado por LLM |
| Retry + Backoff | ✅ Implementado | ❌ No usado por tools |
| Timeout wrapper | ✅ Implementado | ⚠️ Solo LLM, no tools |
| Idempotency store | ✅ Implementado | ❌ No usado en pipeline |
| Health checks | ✅ Implementado | ✅ Endpoints /health |
| Prometheus metrics | ✅ Implementado | ❌ No conectado al agente |
| Alert manager | ✅ Implementado | ⚠️ Solo métricas HTTP |
| Structured logging | ✅ Implementado | ✅ PII masking activo |
| Graceful shutdown | ✅ Implementado | ✅ Drain timeout |

---

## Prioridad de Corrección

### 🔴 CRÍTICO (antes de producción)
1. **PO-01 / ER-01:** Reordenar pipeline para que DB se actualice con resultado ERP
2. **ER-01:** Implementar `update_invoice_erp_status()` en DB

### 🟠 ALTO (sprint 1)
3. **AG-01:** Agregar retry a tool calls del agent loop
4. **LI-02:** Integrar circuit breaker con LLM calls
5. **CG-02:** Unificar umbrales de confianza
6. **ML-01:** Pipeline de entrenamiento con datos reales
7. **HO-02:** Conectar feedback loop al clasificador
8. **PO-02:** Persistir pipeline jobs en DB
9. **TR-01:** Validar parámetros en call_tool
10. **ER-03:** Persistir notificaciones pendientes

### 🟡 MEDIO (sprint 2)
11. **AG-02:** Timeout a todas las tool calls
12. **TR-03:** Documentar limitaciones del router
13. **ML-02:** Habilitar cross-validation
14. **ML-04 / HO-03:** Persistir overrides en DB
15. **LI-03:** Propagar HTTP timeout desde config
16. **PO-04:** Retry individual en batch
17. **MO-01:** Conectar métricas al agente
18. **CC-02:** Implementar model routing con fallback

### 🟢 BAJO (backlog)
19. Documentar confidence threshold por tenant
20. Alertas de accuracy del modelo
21. Mejorar estimación de tokens con tiktoken
