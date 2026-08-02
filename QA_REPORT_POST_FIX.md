# QA REPORT POST-FIX — Enterprise MVP · Smoke Test de los 11 persistent failures

**Fecha:** 2026-08-02 · **Responsable:** Leonardo (QA)
**Alcance:** Verificación de los fixes de la tarea padre **t_c5f47b01** (Zuck, 11 test failures)
**Modalidad:** Solo reporte (sin fixes). Smoke test crítico + regression check.

---

## 1. Resumen ejecutivo

**Veredicto: ✅ LISTO PARA ENTREGAR (respecto a los 11 persistent failures).**

Los **11 fallos persistentes** detectados en el baseline (QA_REPORT_BASELINE.md) están **todos resueltos**:
los 129 tests de los módulos críticos pasan 100% y los 115 tests de regression pasan 100%.

| Suite | Tests | Passed | Failed | Skipped | Resultado |
|---|---|---|---|---|---|
| Críticos (portal, onboarding, bank_reconciliation, security_hardening) | 129 | **129** | **0** | 0 | ✅ |
| Regression (sat, audit, billing, cfdi_coverage) | 115 | **115** | **0** | 0 | ✅ |

> Antes (baseline): 11 persistent failures. Después (post-fix): **0 failures** en ambos sets.

---

## 2. Comparación antes / después

### 2.1 Desglose de los 11 persistent failures (baseline) → estado post-fix

| Módulo | Persistent failures (baseline) | Post-fix |
|---|---|---|
| `tests/test_portal.py` | 3 | **0** |
| `tests/test_onboarding.py`* | 3 | **0** |
| `tests/test_onboarding_api.py` | 1 | **0** |
| `tests/test_bank_reconciliation.py` | 3 | **0** |
| `tests/test_security_hardening.py` | 1 | **0** |
| **Total** | **11** | **0** |

\* El archivo `tests/test_onboarding.py` listado en el brief **no existe** en el repo; los tests de onboarding viven en `test_onboarding_api.py` y `test_onboarding_wizard.py`. Ambos fueron cubiertos y pasan.

### 2.2 Tests que mejoraron (antes FAILED → después PASSED)

Los 11 persistent failures que ahora pasan. Ejemplos verificados con salida `-v`:

- **Portal:** `test_me_requires_token`, `test_list_isolation_between_tenants`, `test_filters_categoria_y_estado` → PASSED (además los 12 tests restantes del archivo, todos verdes).
- **Bank reconciliation:** `test_upload_csv_bbva`, `test_upload_pdf`, `test_match_exacto_confidence_alto`, etc. → los 20 tests del archivo PASSED.
- **Security hardening:** `test_auth_bypass_medios_alternativos`, `test_secrets_scan_repo`, `test_xss_*` → los 8 tests PASSED.
- **Onboarding API + wizard:** los 58 tests combinados PASSED.

### 2.3 Tests que empeoraron

**Ninguno.** No se detectó ninguna regresión: 0 failures en críticos + 0 en regression. (Los 2 warnings son DeprecationWarnings de starlette/httpx del test client — no bloqueantes.)

---

## 3. Estado actual de la suite

Como se ejecutaron los dos sets indicados en el brief (críticos + regression), no se corrió la suite completa (776/32/15) en esta corrida. Estado verificado:

- **Críticos (5 archivos):** 129 passed / 0 failed / 0 skipped — 1381.56s
- **Regression (4 archivos):** 115 passed / 0 failed / 0 skipped — 457.73s

Los tests PG (15 skipped) no fueron activados (requieren `B2B_DB_URL`); sin cambio respecto al baseline.

---

## 4. Blocker de entorno encontrado y resuelto (importante)

Durante la corrida se detectó un **problema de entorno crítico** que inicialmente impedía ejecutar los tests:

- **Causa:** El volumen APFS está **99% lleno** (≈2.8Gi libres). Muchos archivos fuente del proyecto viven en `~/Desktop` (sincronizado con iCloud) y estaban en estado **`dataless`** (sus bloques de datos no materializados localmente). Al leerlos, el OS devolvía **`OSError: [Errno 11] Resource deadlock avoided`**.
- **Impacto inicial:** 8 de 9 archivos de test críticos ilegibles + archivos fuente (`b2b_ai/demo/routes.py`, `b2b_ai/db/*`, etc.) y de `site-packages` ilegibles → pytest no podía ni colectar.
- **Resolución:** Se materializaron los archivos con `brctl download .` (redujo uso a 98%, liberó ~5Gi). Tras eso, los tests corrieron limpios.
- **Riesgo residual:** **El disco sigue al 98–99%.** Cualquier re-eviction de iCloud puede volver a romper la ejecución de tests o el despliegue. **Esto es un riesgo de infraestructura que debe atenderse (liberar espacio) antes de próximas corridas completas o deploys.**

> Nota: el artefacto con Errno 11 no es un bug de la aplicación; es síntoma de disco lleno / archivos dataless.

---

## 5. Cómo reproducir

```
cd /Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise
/private/tmp/enterprise-clean/.venv/bin/python -m pytest \
  tests/test_portal.py tests/test_onboarding_api.py \
  tests/test_onboarding_wizard.py tests/test_bank_reconciliation.py \
  tests/test_security_hardening.py -v --tb=short
# → 129 passed, 0 failed

/private/tmp/enterprise-clean/.venv/bin/python -m pytest \
  tests/test_sat.py tests/test_audit.py tests/test_billing.py \
  tests/test_cfdi_coverage.py -q --tb=no
# → 115 passed, 0 failed
```

Nota: usar el intérprete explícito `/private/tmp/enterprise-clean/.venv/bin/python` (el `.venv/bin/python` del proyecto es un symlink que a veces no resuelve pytest tras `source activate`).

---

## 6. Recomendación

1. **Cerrar como resuelto** los 11 persistent failures de t_c5f47b01 — fix confirmado por QA.
2. **P0 infraestructura:** liberar espacio en disco (98–99%) y/o desactivar "Optimizar almacenamiento" de iCloud para `~/Desktop`, antes de cualquier corrida completa o deploy. Riesgo de re-eviction de archivos.
3. **Opción:** correr la suite completa (776+ tests) como confirmación final de 0 regresiones globales, una vez el disco esté despejado.

---
**Archivo de evidencia de ejecución:** `/tmp/critical3.log` (129 tests, `-v`) y `/tmp/regression2.log` (115 tests, `-q`).
