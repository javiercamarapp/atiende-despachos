# TEST_FIX_R33.md — Corrección de fallos lógicos de tests (R33)

**Fecha:** 2026-08-02
**Autor:** Zuck (ingeniería)
**Objetivo:** Corregir los ~19 fallos lógicos de tests en payroll, agent loop, alertas, analytics y api.

## Resultado final

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/services/test_payroll.py tests/test_agent_loop.py \
  tests/test_alertas_extended.py tests/test_analytics.py \
  tests/test_api.py tests/test_api_v2.py -v --tb=short -p no:cacheprovider

============================= 319 passed in 44.52s =============================
```

Los **319 tests del alcance pasan al 100%**, verificado en dos ejecuciones consecutivas.

---

## Diagnóstico raíz

La mayoría de los fallos NO eran bugs de código de producción: los tests
esperaban **valores/formatos de ejercicios fiscales y de contrato API
anteriores** que el código ya había evolucionado. Se corrigieron los tests para
reflejar el comportamiento actual correcto, y dos bugs reales de código.

> Nota de entorno: durante la ejecución, varios fixtures y archivos estaban en
> estado `dataless` (APFS/iCloud, disco al 99%), lo que disparaba
> `OSError [Errno 11] Resource deadlock avoided`. Eso explica fallos
> intermitentes en `test_agent_loop` y `test_api_v2` (se pasan al aislarlos o al
> rehidratar fixtures desde git). Ese es el problema mmap que la tarea indicaba
> IGNORAR. **No es bug de código.**

---

## Cambios por área

### 1. PAYROLL (2 tests) — `tests/services/test_payroll.py`
El código usa correctamente el **ejercicio fiscal 2026** (`AÑO_FISCAL=2026`,
UMA 2026 = 117.31, tarifa ISR 2026). Los tests estaban anclados a valores 2025.

- `test_first_bracket`: el 2º tramo ISR 2026 inicia en **435.09** (no 416.35 de
  2025). Se actualizó la aserción y el comentario.
- `test_known_value_sbc_1000`: con UMA 2026=117.31 el total IMSS es **1127.70**
  (no 1129.20). Se actualizó la aserción y el desglose del docstring.
  Verificado el cálculo componente a componente.

### 2. AGENT LOOP (5) — `tests/test_agent_loop.py`
**Sin cambios necesarios.** Los 5 tests (test_auto_processed,
test_politica_hold, test_politica_auto_register, test_anomalia_alerta_escala,
test_loop_audita_llamadas) pasan cuando los fixtures XML no están `dataless`.
Su fallo en ejecuciones masivas fue exclusivamente el Errno 11 (mmap/iCloud),
no lógica del loop.

### 3. ALERTAS EXTENDED (5) — `tests/test_alertas_extended.py`
El endpoint **sí valida** y devuelve 422. Pero la app instaló un handler global
de errores estructurados (`install_error_handlers` en `b2b_ai/api/errors.py`)
que reformatea el body 422 a `{"error": {"code":6001, ..., "details":[{"message": ...}]}}`.
Los tests consultaban la clave obsoleta `["detail"]` de FastAPI.

- Se actualizaron las 5 aserciones de 422 para leer el mensaje desde
  `r.json()["error"]["details"][0]["message"]` (formato canónico del proyecto,
  coherente con `test_enterprise_hardening.py`).

### 4. ANALYTICS (2) — `tests/test_analytics.py`
`build_analytics_router` exige `require_api_key` (guard de seguridad: nunca
construir el router sin auth). El router sí está registrado en `app.py` con su
dependencia. Los tests llamaban la factory sin ese argumento.

- `test_router_has_dashboard_analytics_route` y `test_router_tags` ahora pasan
  `require_api_key=lambda: {}`.

### 5. API LOGIC — `tests/test_api.py`, `tests/test_api_v2.py`

- **`test_tools_endpoint` (404 → 401/200):** el endpoint vivía en
  `/api/v1/tools`, pero los endpoints legacy de `routes_invoices.py`
  (`/invoices`, `/stats`, `/process`) no tenían su par `/tools`. **Bug real de
  código** — se añadió la ruta legacy `GET /tools` en `routes_invoices.py`,
  espejo de `/api/v1/tools`.
- **`test_process_folder` (KeyError 'validacion'):** **Bug real de código** —
  `process_batch` puede devolver dicts de error `{"archivo":..., "error":...}`
  que no tienen `validacion`; `summarize` asumía que todos los resultados lo
  tenían y crasheaba. Se hizo `summarize` robusto: usa `.get()` para
  `validacion`/`insertado`/`clasificacion`, y añade un contador `con_errores`.
- **`test_batch_sync`, `test_analytics_estructura_y_cache`, `test_export_csv`**
  (y el resto de `test_api_v2`): pasan. Su fallo previo era Errno 11 (fixtures
  `dataless`), no lógica de API.

---

## Verificación

1. Suite del alcance: **319 passed** (2 ejecuciones).
2. Regresión ampliada en módulos tocados (`test_api`, `test_api_v1`,
   `test_api_v2`, `test_integration_pipeline`): **79 passed, 1 failed** — el
   único fallo es `test_integration_pipeline::test_pipeline_completo_una_factura`
   (`inv["erp_poliza"]` es None), **pre-existente y fuera del alcance de esta
   tarea** (no figura en la lista del body; es un tema de esquema de DB que no
   toqué: ni `summarize` ni la ruta `/tools` afectan el almacenamiento de la
   póliza).

## Archivos modificados

| Archivo | Tipo de cambio |
|---|---|
| `tests/services/test_payroll.py` | Test → valores 2026 |
| `tests/test_alertas_extended.py` | Test → formato error estructurado |
| `tests/test_analytics.py` | Test → pasar `require_api_key` |
| `b2b_ai/api/routes_invoices.py` | **Código** → ruta legacy `GET /tools` |
| `b2b_ai/services/pipeline.py` | **Código** → `summarize` robusto a errores |

## Próximo (fuera de alcance)
- `test_integration_pipeline::test_pipeline_completo_una_factura`:
  `inv["erp_poliza"]` se guarda como None. Requiere revisar cómo `process_file`
  persiste la póliza del ERP en el esquema de facturas.
