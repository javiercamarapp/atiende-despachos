# QA REPORT BASELINE — Enterprise MVP · Suite Completa Post-Nuevos Módulos

**Fecha:** 2026-07-31 · **Responsable:** Leonardo (QA)
**Alcance:** Reporte de línea base (baseline). No se hicieron fixes.

---

## 1. Resumen ejecutivo

La suite completa corre **776 passed · 32 failed · 15 skipped · 484 warnings** en 44.52s.

Hay una **caída significativa respecto al reporte anterior** (631/0/15): pasamos de 0 fallos a 32. Sin embargo, **21 de esos 32 son fallos por interferencia de orden entre tests** (pasan en aislamiento). Solo **11 fallos son persistentes** y corresponden a bugs reales en los módulos nuevos (bank_reconciliation, portal, onboarding, security_hardening).

**Veredicto: Las capas core (SQLite, API v1/v2, auth RBAC, integraciones, producción) siguen sólidas. Los módulos nuevos introdujeron bugs reales que hay que arreglar antes de entregar. Los 15 tests PG siguen saltados (mismo hallazgo del reporte anterior).**

---

## 2. Conteo comparativo

| Métrica | Anterior (QA_REPORT_CURRENT) | Actual | Diferencia |
|---|---|---|---|
| Total colectados | 646 | 823 | **+177 tests nuevos** |
| **Passed** | **631** | **776** | +145 |
| **Failed** | **0** | **32** | **+32** (nuevos) |
| **Skipped** | **15** | **15** | Sin cambio (tests PG) |
| Errors | 0 | 0 | Sin cambio |
| Warnings | 2 | 484 | +482 (DeprecationWarnings masivos de FastAPI/Pydantic) |
| Tiempo | 27.26s | 44.52s | +17.26s |

### Desglose de fallos por módulo

| Módulo / Archivo | Fallos en suite completa | Fallos persistentes (en aislamiento) |
|---|---|---|
| `test_auth_api.py` | 7 | **0** (pasan solos) |
| `test_bank_reconciliation.py` | 10 | **3** |
| `test_billing.py` | 1 | **0** (pasa solo) |
| `test_onboarding.py` | 7 | **3** |
| `test_onboarding_api.py` | 5 | **1** |
| `test_portal.py` | 3 | **3** |
| `test_security_hardening.py` | 1 | **1** |
| **Total** | **32** | **11** |

---

## 3. Tests NUEVOS (no estaban en el reporte anterior)

Se agregaron **177 tests nuevos** distribuidos en estos archivos:

| Archivo de test | Tests | Status |
|---|---|---|
| `tests/test_auth_api.py` | ~22 | Todos pasan en aislamiento |
| `tests/test_billing.py` | ~24 | Todos pasan en aislamiento |
| `tests/test_onboarding.py` | ~10 | 3 persistentes |
| `tests/test_onboarding_api.py` | ~7 | 1 persistente |
| `tests/test_portal.py` | ~16 | 3 persistentes |
| `tests/test_bank_reconciliation.py` | ~20 | 3 persistentes |
| `tests/test_monitoring.py` | varios | Pasan |
| `tests/test_notifications_api.py` | varios | Pasan |
| `tests/test_notifications_whatsapp.py` | varios | Pasan |
| `tests/test_notifications_scheduler.py` | varios | Pasan |
| `tests/test_erp_real.py` | varios | Pasan |
| `tests/test_sat_api.py` | varios | Pasan |
| `tests/test_sat.py` | varios | Pasan |
| `tests/test_csv_export.py` | varios | Pasan |
| `tests/test_desktop_drivers.py` | varios | Pasan |
| `tests/test_pwa.py` | varios | Pasan |
| `tests/test_webhooks.py` | varios | Pasan |
| `tests/test_security_hardening.py` | varios | 1 persistente |
| `tests/test_security_hardening_2.py` | varios | Pasan |
| Otros (dashboard, collections, e2e) | varios | Pasan |

---

## 4. Top 5 fallos más críticos

### P1 — Portal: /portal/invoices NO es endpoint REST (3 tests)

- **Tests:** `test_me_requires_token`, `test_list_isolation_between_tenants`, `test_filters_categoria_y_estado`
- **Evidencia:** GET /portal/invoices retorna 200 con HTML/SPA (no JSON). Cuando el test espera 401 sin token o JSON con `"count"`, falla.
- **Causa raíz:** El portal es una SPA con ruteo client-side. No hay endpoint REST en `/portal/invoices`. Los tests asumen API REST donde solo hay SPA.
- **Diagnóstico:** Test desactualizado vs implementación actual, o feature faltante (faltaría un backend JSON API para el portal).
- **Severidad:** P1 — bloquea pruebas del portal completamente.

### P1 — Onboarding: wizard falla con ERP válido "CONTPAQi" (4 tests)

- **Tests:** `test_complete_flujo_completo`, `test_complete_flujo_ok`, `test_score_100_flujo_completo`, `test_paso7_valida_plan`
- **Evidencia:** PUT /api/v1/onboarding/step/2 con `{"erp": "CONTPAQi"}` → 400 "ERP inválido". El wizard tiene case-insensitive handling implementado (línea 144 de wizard.py) pero falla en ejecución real.
- **Causa raíz:** Posible stale import o interacción entre fixtures. `ERP_OPTIONS = ["CONTPAQi", "ASPEL", "OTHER"]` y el validador usa `by_key = {opt.upper(): opt ...}` — lógicamente correcto pero falla en contexto de test. Se reproduce en aislamiento.
- **Severidad:** P1 — bloquea el flujo de onboarding completo.

### P2 — Bank Reconciliation: estado compartido entre tests (3 tests)

- **Tests:** `test_match_ai_fallback_tokens`, `test_report_endpoint_sin_movimientos`, `test_report_endpoint_con_movimientos`
- **Evidencia:** `test_report_endpoint_sin_movimientos` espera `"ok": True/False` y recibe tipo booleano. `test_report_endpoint_con_movimientos` espera 3 movimientos y encuentra 12 (datos acumulados de tests anteriores).
- **Causa raíz:** Los tests de bank reconciliation no limpian la DB entre sí (shared state en la DB SQLite en memoria). El fixture `client` se reusa sin reset.
- **Severidad:** P2 — funcionalidad de conciliación existe pero la suite no es fiable.

### P3 — Security Hardening: secreto JWT en source code (1 test)

- **Test:** `test_secrets_scan_repo`
- **Evidencia:** `b2b_ai/auth/middleware.py:42` contiene `_DEV_SECRET = "b2b-ai-dev-jwt-secret-no-usable-en-produccion"`
- **Causa raíz:** El test escanea el repo buscando strings con aspecto de secretos. El dev secret hardcodeado se usa SOLO cuando no hay `B2B_JWT_SECRET` en entorno. Es un placeholder con nombre explícito de desarrollo, pero el escáner no lo distingue.
- **Diagnóstico:** El test es correcto — aunque es un dev secret, tenerlo en texto plano en source es una mala práctica. El fix es moverlo a una variable de entorno o marcarlo como falso positivo en el test.
- **Severidad:** P3 (cosmético para dev, P1 si alguien despliega sin setear B2B_JWT_SECRET).

### P3 — Interferencia de orden entre tests (21 fallos)

- **Tests:** 7 de auth_api, 7 de bank_reconciliation, 1 de billing, 3 de onboarding_type_error, 2 de onboarding_checklist
- **Evidencia:** Todos pasan cuando se ejecuta SÓLO su archivo. Fallan solo cuando corren después de otros tests que modifican la DB compartida.
- **Causa raíz:** La DB en memoria (`:memory:`) se comparte entre todos los tests que usan el fixture `client`. Tests que crean tenants/usuarios contaminan el estado de tests posteriores.
- **Severidad:** P3 (no es bug de funcionalidad, es bug de test suite — pero erosiona la confianza en los resultados).

---

## 5. Tests de integración PG que requieren DB real (15 skipped)

**Sin cambios respecto al reporte anterior.** Siguen saltados por ausencia de `B2B_DB_URL`:

| Archivo | Tests | Condición |
|---|---|---|
| `tests/test_pg_backend.py` | 7 | skipif sin B2B_DB_URL |
| `tests/test_pg_migrations.py` | 2 | skipif sin B2B_DB_URL |
| `tests/test_db_pg_integration.py` | 6 | skipif sin B2B_DB_URL |

El PostgreSQL real sigue disponible (docker, puerto 54329). Los 4-5 bugs del adaptador PG documentados en `QA_REPORT_CURRENT.md` persisten.

---

## 6. Warnings (no bloqueantes)

**484 warnings** en total (vs 2 en el reporte anterior). Crecimiento masivo por:

| Categoría | Frecuencia | Causa |
|---|---|---|
| `DeprecationWarning: on_event is deprecated` | ~360 | FastAPI `@app.on_event("startup")` en `app.py:328` — cada test que carga la app lo dispara |
| `DeprecationWarning: on_event` (FastAPI router) | ~120 | Misma causa, desde `applications.py:4681` |
| `StarletteDeprecationWarning: install httpx2` | ~1 | Starlette testclient deprecado |
| `PydanticDeprecatedSince20: .dict()` | ~1-2 | `body.dict(exclude_none=True)` → `model_dump()` |
| `DeprecationWarning: Use content=<...>` | ~1 | httpx upload API |
| `DeprecationWarning: per-request cookies` | ~1 | Starlette testclient |

**Impacto:** Cero. Son todos de FastAPI/Pydantic v2 migration. La app funciona igual. Pero son una señal de ruido alarmante — 484 warnings sepultan warnings reales.

---

## 7. Comparación: qué mejoró vs qué empeoró

### Mejoró

- **Cobertura de tests:** +177 tests nuevos (billing, auth, portal, onboarding, bank reconciliation, SAT, notificaciones, webhooks, ERP, PWA, seguridad avanzada)
- **API v2:** Tests de batch, analytics, webhooks, export CSV/XLSX/PDF, admin, rate limit por tenant — todos pasan
- **Notificaciones:** Tests de WhatsApp, email, scheduler, API — todos pasan
- **SAT/ERP:** Tests de integración SAT y ERP — pasan
- **Seguridad:** Tests de hardening agregados (XSS, mutación, auth bypass, rate limit bypass) — casi todos pasan
- **Webhooks:** Retry, delivery, extracción CFDI de email — pasan
- **PWA:** Tests de service worker, offline, manifest — pasan

### Empeoró

- **Fallos totales:** 0 → 32 (aunque 21 son por interferencia, no bugs reales)
- **Fallos persistentes:** 0 → 11 (nuevos módulos)
- **Warnings:** 2 → 484 (FastAPI deprecation)
- **Tiempo de suite:** 27s → 44s (esperable con 177 tests más)
- **Bank reconciliation:** 0 → 3 fallos persistentes (estado compartido)
- **Portal:** No existía → 3 fallos (SPA vs API desajuste)
- **Onboarding:** No existía → 4 fallos (ERP validation + TypeError)
- **Auth API:** No existía → 7 fallos (interferencia de orden)
- **Secrets scan:** No existía → 1 hallazgo (dev secret en source)

### Sin cambio

- **Tests PG saltados:** 15 (mismo estado)
- **Capas core (db, api, integration, production):** Verdes

---

## 8. Recomendación: qué arreglar primero

### Inmediato (P1 — bloquea features completas)

1. **Portal tests (3 bugs)** — Decidir: ¿el portal debe tener backend JSON API para /portal/invoices, o los tests deben adaptarse a la SPA? Si es backend, Zuck necesita implementar los endpoints. Si es SPA, reescribir tests para status 200 + HTML check. Conversión con el equipo.

2. **Onboarding ERP validation (4 bugs)** — Parece un problema de fixture/import en tests más que de lógica. El validador en wizard.py maneja case-insensitive correctamente. Zuck debe:
   - Verificar que `ERP_OPTIONS` no está siendo sobrescrito en algún fixture/conftest
   - Verificar que la validación en API route no duplica la validación del wizard
   - Arreglar los tests de `test_onboarding.py` para usar `conftest` con estado limpio

### Prioridad alta (P2 — fiabilidad de suite)

3. **Bank reconciliation state leak (3 bugs)** — Agregar limpieza de DB entre tests en el conftest de bank_reconciliation o usar transacciones con rollback. Afecta 10 tests en suite completa pero solo 3 en aislamiento.

4. **Auth API state leak (7 bugs)** — Misma causa que bank reconciliation. Usar fixture de DB con rollback en `test_auth_api.py`. Todos pasan en aislamiento.

### Prioridad media (P3 — hygiene)

5. **Interferencia de orden (21 bugs en total)** — Arreglar de raíz: usar fixtures con `yield` + DB teardown en el conftest principal, o cambiar a DB temporal por test. Es el mayor foco de falsos positivos.

6. **Secrets scan repo (1 bug)** — Mover `_DEV_SECRET` a variable de entorno en conftest, o agregar excepción en el test. El placeholder es explícito para desarrollo pero el escáner no tiene contexto.

7. **Warnings masivos (484)** — Migrar `@app.on_event("startup")` a lifespan events de FastAPI. Esto eliminaría ~480 warnings de un golpe. Cambio de 1-2 líneas en `app.py`.

### Queda pendiente (del reporte anterior)

8. **PG adapter bugs** — Los 4-5 bugs reportados en `QA_REPORT_CURRENT.md` persisten. Requieren DB real para reproducirse.

---

## 9. Cómo reproducir

```bash
# Suite completa (32 failed)
cd /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
# → 776 passed, 32 failed, 15 skipped, 484 warnings

# Sólo fallos persistentes (11 tests)
python -m pytest tests/test_bank_reconciliation.py \
  tests/test_portal.py \
  tests/test_onboarding.py \
  tests/test_onboarding_api.py \
  tests/test_security_hardening.py::test_secrets_scan_repo \
  -v --tb=short
# → 11 failed (esperado)

# Fallos por interferencia se pueden verificar: cada archivo pasa solo
python -m pytest tests/test_auth_api.py -v --tb=short
# → 22 passed
```