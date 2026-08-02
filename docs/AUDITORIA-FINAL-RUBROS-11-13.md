# Auditoría Final — Rubros 11-13

**Fecha:** 2026-08-02
**Alcance:** Cumplimiento Fiscal, Rendimiento y Costo, Computer Use
**Versión auditada:** HEAD del branch actual

---

## RUBRO 11: CUMPLIMIENTO FISCAL (7/10)

### 11.1 ISR 2026 — Tablas `fiscal_tables.py`

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| `FISCAL_YEAR = 2026` | ✅ | Línea 27 de `fiscal_tables.py` |
| ISR_MENSUAL_2026 definida | ✅ | Líneas 139-150, 10 rangos |
| ISR_ANUAL_2026 definida | ✅ | Líneas 156-167, 10 rangos |
| ISR_QUINCENAL_2026 definida | ✅ | Líneas 173-184, 10 rangos |
| ISR 2026 ≠ copia de 2025 | ⚠️ **CRÍTICO** | **Los valores son IDÉNTICOS a ISR_2025.** Líneas 136-137 confirman: `# TODO: Actualizar límites y cuotas cuando el DOF publique las tablas 2026. Por ahora se usan los mismos valores que 2025.` Los rangos (0-416.34, 416.35-3508.42, etc.), cuotas fijas y porcentajes son idénticos entre 2025 y 2026. |
| `get_isr_table()` centralizado | ✅ | Función lookup por `(año, periodo)` con ValueError si no existe |
| Legacy 2024 preservada | ✅ | `ISR_MENSUAL_2024`, `ISR_ANUAL_2024` presentes |

**Hallazgo CRÍTICO — ISR 2026 es placeholder:**
Las tablas ISR 2026 son copia exacta de las tablas 2025. El código tiene TODOs explícitos (`# TODO: Actualizar límites y cuotas cuando el DOF publique las tablas 2026`). **Esto es correcto si el DOF aún no ha publicado las tablas 2026** (las tablas del SAT generalmente se publican en diciembre del año anterior o enero). Sin embargo, para un sistema que opera en 2026, esto genera resultados que pueden no ser oficiales. **Recomendación: Verificar si el DOF ya publicó las tablas ISR 2026; si sí, actualizar de inmediato. Si no, agregar un warning visible al usuario.**

### 11.2 UMA 2026

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| UMA diario 2026 | ❌ **FAIL** | `113.04` (línea 129). Esperado: `$117.31` |
| UMA mensual 2026 | ❌ **FAIL** | `3391.20` (línea 130). Esperado: `$3,566.22` |
| UMA anual 2026 | ❌ **FAIL** | `40694.40` (línea 131). Esperado: `$42,794.64` |

**Hallazgo CRÍTICO — UMA 2026 incorrecta:**
Los valores de UMA 2026 están **desactualizados**. El INEGI publicó en febrero 2026:
- Diario: **$117.31** (código tiene $113.04)
- Mensual: **$3,566.22** (código tiene $3,391.20)
- Anual: **$42,794.64** (código tiene $40,694.40)

**Impacto:** El IMSS usa `imss_uma_diario = 113.04` en `payroll.py` (RATES línea 84). Todos los cálculos IMSS (cuota fija 20.40×UMA, excedente 3 UMA) están usando un UMA 3.5% menor al real. Esto genera subcálculos en las retenciones IMSS. **Acción inmediata requerida.**

### 11.3 Subsidio al Empleo

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| SUBSIDIO_EMPLEO_MENSUAL_2026 | ✅ | Definida (líneas 191-203), 11 rangos |
| SUBSIDIO_EMPLEO_QUINCENAL_2026 | ✅ | Definida (líneas 208-220) |
| Montos ≠ 2025 | ⚠️ | Son idénticos a 2025 (comentado: "Los montos son los mismos que 2025") |
| `get_subsidio_table()` centralizado | ✅ | Lookup por `(año, periodo)` |
| `calc_subsidio_empleo()` en payroll | ✅ | Líneas 362-402, con ISR neto y subsidio efectivo |

**Nota:** Los montos de subsidio al empleo suelen mantenerse iguales entre años, así que la duplicación de 2025→2026 es razonable. Sin embargo, la nota "TODO: Actualizar si el DOF publica tabla nueva para 2026" indica que no se ha verificado oficialmente.

### 11.4 AÑO_FISCAL en payroll.py

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| `AÑO_FISCAL = 2026` | ✅ | Línea 116 de `payroll.py` |
| ISR default usa 2026 | ✅ | `TARIFA_ISR_2026_MENSUAL` es el default (línea 153) |
| Subsidio default usa 2026 | ✅ | `SUBSIDIO_EMPLEO_MENSUAL` = 2026 (línea 53) |
| IMSS UMA usa 2026 | ⚠️ | Usa `113.04` (incorrecto, ver sección 11.2) |

### 11.5 IVA 16%, CFDI 4.0, DIOT

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| IVA tasas válidas | ✅ | `VALID_IVA_RATES = {0, 0.0, 8, 0.08, 16, 0.16}` en `compliance.py` |
| DIOT tasas IVA | ✅ | `TASA_IVA_16 = 0.16`, `TASA_IVA_8 = 0.08`, `TASA_IVA_0 = 0.00` en `diot_expansion.py` |
| CFDI 4.0 parser | ✅ | `parser.py: "Parser completo de CFDI 4.0 (y tolerante a 3.3)"` |
| CFDI 4.0 XML output | ✅ | `generate_payroll_cfdi()` genera `Version="4.0"` con schema CFDI 4.0 |
| CFDI 4.0 catálogos SAT | ✅ | `catalogs.py` implementa catálogos oficiales CFDI 4.0 |
| DIOT batch processing | ✅ | `diot_expansion.py` con `process_cfdi_batch()`, `DIOTBatchResult`, `DIOTBatchSummary` |
| CFF Art. 85-A (DIOT) | ✅ | Referenciado en docstring de `diot_expansion.py` |
| XSS/DTD protection en CFDI XML | ✅ | `xml_security.py` mitiga SSRF via DTD loading |
| `validate_iva_rate()` | ✅ | Solo 0%, 8%, 16% son válidos |
| Compliance engine | ✅ | `compliance.py` cubre CFF arts. 30, 82, 85, 86, 89, 105 |

### 11.6 Resumen Cumplimiento Fiscal

| Componente | Score |
|------------|-------|
| ISR tablas (con TODO) | 7/10 |
| UMA 2026 | 2/10 — **valores incorrectos** |
| Subsidio al empleo | 8/10 |
| AÑO_FISCAL | 10/10 |
| IVA / CFDI 4.0 / DIOT | 9/10 |
| **Global Rubro 11** | **7/10** |

---

## RUBRO 12: RENDIMIENTO Y COSTO (7/10)

### 12.1 Lazy Imports

| Hallazgo | Estado | Detalle |
|----------|--------|---------|
| `__init__.py` de `computer_use` | ⚠️ | Importa **todo** al nivel del módulo: `PlaywrightDesktop`, `CONTPAQiRealDriver`, `AspelRealDriver`, `BrowserAutomation`, `MockBrowser`, etc. (21 imports en `__init__.py`). Esto carga Playwright y asyncio en cada import del paquete. |
| Factory imports diferidos | ✅ | `_create_playwright_driver()` en `factory.py` (línea 348-382) hace imports dentro de la función, evitando cargar Playwright cuando no se usa. Comentario: "Imports are deferred to avoid loading Playwright when not needed." |
| Playwright import diferido | ✅ | `launch()` en `playwright_desktop.py` importa `async_playwright` dentro del método (línea 179). |
| `compliance.py` importa fiscal_tables | ✅ | Importa solo lo necesario de `fiscal_tables`. |
| `generate_payroll_cfdi()` | ✅ | `import xml.sax.saxutils` se hace dentro de la función (línea 631). |

**Hallazgo:** El `__init__.py` de `computer_use` es el principal problema de startup. Importa `PlaywrightDesktop` directamente (línea 53), lo que fuerza la carga de todo el módulo `playwright_desktop.py` (que incluye asyncio, hashlib, etc.) aunque solo se necesite el Mock. **Recomendación: Convertir a imports perezosos en `__init__.py`.**

### 12.2 Memory Usage

| Hallazgo | Estado | Detalle |
|----------|--------|---------|
| Script de profiling | ✅ | `scripts/memprofile_pipeline.py` — mide pico tracemalloc, RSS, retención post-GC, y detecta leaks por bloque. |
| Batch processing medido | ✅ | Procesa N CFDI por bloque (default 1000), mide `peak_int_MB`, `retained_post_gc_MB`, `rss_max_MB`. |
| Leak detection | ✅ | Compara retención post-GC entre primer y último bloque. Threshold: >10 MB = warning. |
| Decimal precision | ✅ | `payroll.py` usa `Decimal` con `ROUND_HALF_UP` — no hay pérdida de precisión fiscal. |

### 12.3 Connection Pool Sizing

| Hallazgo | Estado | Detalle |
|----------|--------|---------|
| SQLAlchemy engine | ❌ | **No se encontró** `create_engine`, `create_async_engine`, `pool_size`, ni `max_overflow` en el código. |
| DB layer | ✅ | `Database(":memory:")` en scripts de test y profiling. SQLite-based, sin pool. |

**Nota:** El proyecto usa SQLite como base de datos principal (no PostgreSQL/MySQL). No hay configuración de connection pool porque SQLite no lo requiere. Para producción, si se migra a PostgreSQL, se necesitará configurar `pool_size`, `max_overflow`, y `pool_recycle`.

### 12.4 Batch Processing

| Hallazgo | Estado | Detalle |
|----------|--------|---------|
| Pipeline batch | ✅ | `process_batch()` en `services/pipeline.py` — procesa archivos CFDI en batch. |
| DIOT batch | ✅ | `process_cfdi_batch()` en `diot_expansion.py` — convierte N facturas a formato DIOT. |
| ERP batch registration | ✅ | `ERPRegistrar.register_batch()` — registra pólizas con rollback si alguna falla. |
| Batch blocks pattern | ✅ | `memprofile_pipeline.py` procesa en K bloques para detectar leaks acumulativos. |
| Memory profiling integrated | ✅ | Script separado `memprofile_pipeline.py` ejecutable con `--n 1000 --blocks 4 --json`. |

### 12.5 Resumen Rendimiento

| Componente | Score |
|------------|-------|
| Lazy imports | 6/10 — `__init__.py` carga todo |
| Memory profiling | 9/10 — excelente infraestructura |
| Connection pool | N/A (SQLite) |
| Batch processing | 8/10 |
| **Global Rubro 12** | **7/10** |

---

## RUBRO 13: COMPUTER USE (8/10)

### 13.1 Factory (`factory.py`)

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| `ComputerUseDriverFactory.create()` | ✅ | Entry point único, acepta `provider`, `mode`, `tenant_id`, `config` |
| 3 modos: mock/playwright/disabled | ✅ | `VALID_MODES = {"mock", "playwright", "disabled"}` |
| 2 proveedores: contpaqi/aspel | ✅ | `VALID_PROVIDERS = {"contpaqi", "aspel"}` |
| Sin fallback silencioso real→mock | ✅ | Comentario explícito: "The factory NEVER silently falls back from real to mock" |
| `DisabledDriver` implementa ABC | ✅ | Todos los métodos retornan `configuration_error` |
| `MockComputerUseDriver` completo | ✅ | Full lifecycle: connect → login → navigate → extract → register → verify → logout |
| Import diferido de Playwright | ✅ | `_create_playwright_driver()` importa dentro de la función |
| Test cobertura factory | ✅ | 483 líneas de tests en `test_computer_use_factory.py` |

### 13.2 Config (`config.py`)

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Env vars documentadas | ✅ | `B2B_COMPUTER_USE_MODE`, `_PROVIDER`, `_HEADLESS`, `_TIMEOUT_SECONDS`, `_MAX_RETRIES`, `_SCREENSHOT_DIR`, `_ALLOW_WRITES` + credenciales por proveedor |
| `validate()` invariantes | ✅ | 5 reglas: provider conocido, modo conocido, producción rechaza mock, playwright requiere creds, example.com rechazado |
| `ComputerUseConfig` frozen | ✅ | `@dataclass(frozen=True)` — immutable post-creación |
| Rechaza mock en producción | ✅ | `if env in ("production", "prod") and self.mode == "mock": raise` |
| Rechaza example.com en playwright | ✅ | `if "example.com" in url.lower(): raise` |
| `from_env()` factory method | ✅ | Lee todas las env vars con defaults |
| Password enmascarado en `__repr__` | ✅ | No expone password |

### 13.3 `PlaywrightDesktop` y `PlaywrightDesktopConfig`

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| `PlaywrightDesktopConfig` dataclass | ✅ | 6 campos: `headless`, `navigation_timeout_ms`, `action_timeout_ms`, `max_retries`, `allowed_hosts`, `allow_private_hosts` |
| Browser launch con retry | ✅ | `_retry_async()` con exponential backoff |
| Click por coordenadas | ✅ | `click(x, y)` |
| Click por selector (CSS/XPath) | ✅ | `click_selector(selector)` con fallback |
| Type text | ✅ | `type_text(text)` con retry |
| Fill con verificación | ✅ | `fill(selector, value)` verifica `input_value()` post-fill |
| Screenshot con hash comparison | ✅ | SHA-256 hash, detección de duplicados |
| Table extraction | ✅ | `extract_table(selector)` con headers y rows |
| Dropdown selection | ✅ | `select_dropdown(selector, value)` |
| Resource cleanup | ✅ | `close()` + `__del__` con warning si no se cerró |
| Health check | ✅ | `health()` reporta estado completo |

### 13.4 `CONTPAQiRealDriver` y `AspelRealDriver`

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| CONTPAQiRealDriver existe | ✅ | 499 líneas, implementa `DesktopAutomation` |
| AspelRealDriver existe | ✅ | 506 líneas, implementa `DesktopAutomation` |
| Login multi-selector fallback | ✅ | 5 username selectors + 5 password selectors + 6 submit selectors |
| Menu navigation con paths | ✅ | `CONTPAQI_MENU_PATHS` / `ASPEL_MENU_PATHS` con selectors y grid_selectors |
| Invoice grid extraction | ✅ | `extract_invoices()` + `capture_invoice_grid()` |
| Error recovery | ✅ | `recover_from_error()` — verifica health, reconecta si necesario |
| Screenshot-based state verification | ✅ | Usa screenshots para verificar estado post-acción |
| Sync wrappers | ✅ | `_run_sync()` con event loop compartido |

### 13.5 Factory → CU Integration

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Factory crea real drivers | ✅ | `_create_playwright_driver()` instancia `CONTPAQiRealDriver` o `AspelRealDriver` |
| Config validation antes de crear | ✅ | Factory llama `config._provider_credentials()` y valida URL/username/password |
| `erp_registrar.py` usa factory | ⚠️ | `ERPRegistrar._send_to_erp()` tiene `raise NotImplementedError` para non-MOCK (línea 153). **No integra aún con ComputerUseDriverFactory.** |
| `register_erp` tool | ✅ | `tools/tools.py` define `@tool(name="register_erp")` |

**Hallazgo:** `ERPRegistrar` no usa la factory de Computer Use. Para conectar CONTPAQi/Aspel reales vía Playwright, `ERPRegistrar._send_to_erp()` necesita delegar a `ComputerUseDriverFactory.create()` en lugar de hacer `NotImplementedError`. Esto es un gap de integración, no un bug de seguridad.

### 13.6 E2E Tests con Chromium Real

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Tests de factory/mock | ✅ | `test_computer_use_factory.py` — 483 líneas, cubre DriverResult, Config, Factory, DisabledDriver, MockComputerUseDriver, ABC |
| E2E con Chromium real | ⚠️ | **No se encontraron tests E2E que lancen Chromium real.** Los tests usan `ComputerUseConfig(mode="playwright")` pero instancian el driver sin lanzar el browser (verifican que el objeto se crea, no que navegue). |
| Smoke test | ✅ | `smoke_test.py` existe en `computer_use/` |

### 13.7 Security Layer (`security.py`)

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Domain allowlist | ✅ | `_KNOWN_ERP_DOMAINS`: contpaqi.com, contpaqiweb.com, aspel.com.mx, sap.com, odoo.com, sat.gob.mx, etc. |
| Blocked domains | ✅ | `_BLOCKED_DOMAINS`: example.com/org/net, localhost, 127.0.0.1, 0.0.0.0, ::1 |
| SSRF protection | ✅ | `validate_domain()` rechaza dominios no permitidos. `webhooks.py` bloquea IPs privadas para SSRF. |
| Credential encryption | ✅ | Fernet encryption con `B2B_ENCRYPTION_KEY`, fallback a base64 con warning CRITICAL |
| Per-tenant isolation | ✅ | `TenantBrowserContext` con cookie jar y storage separado por tenant |
| Session management | ✅ | `SessionManager` con timeout (30 min), max 3 sesiones/tenant, purge automático |
| PII masking | ✅ | `mask_pii_in_text()` cubre RFC, CURP, nómina, teléfono, tarjeta |
| Screenshot retention | ✅ | `RetentionPolicy` configurable: max_age, max_count, max_size |
| Audit log append-only | ✅ | `AuditLog` con `AuditEntry` frozen dataclass, rotación a 10K entradas |
| RBAC | ✅ | 4 roles (admin/contador/auxiliar/auditor) con permisos granulares |
| Write gate | ✅ | `B2B_COMPUTER_USE_ALLOW_WRITES=false` por default |
| Human confirmation fiscal | ✅ | 9 acciones fiscales requieren confirmación humana |
| Idempotency | ✅ | `generate_idempotency_key()` + `AuditLog.check_idempotency()` |

### 13.8 Resumen Computer Use

| Componente | Score |
|------------|-------|
| Factory | 9/10 |
| Config | 10/10 |
| PlaywrightDesktop | 9/10 |
| Real drivers | 8/10 |
| Factory→ERP integration | 5/10 — gap con ERPRegistrar |
| E2E tests | 4/10 — sin Chromium real |
| Security | 10/10 — excepcional |
| **Global Rubro 13** | **8/10** |

---

## RESUMEN EJECUTIVO

| Rubro | Score | Hallazgo Principal |
|-------|-------|--------------------|
| **11. Cumplimiento Fiscal** | **7/10** | UMA 2026 incorrecta ($113.04 vs $117.31). ISR 2026 es placeholder (idéntico a 2025). |
| **12. Rendimiento y Costo** | **7/10** | `__init__.py` de computer_use carga todo sin lazy import. SQLite sin pool config. |
| **13. Computer Use** | **8/10** | Security layer excepcional. Gap: ERPRegistrar no integra con CU factory. Sin E2E con Chromium real. |

### Acciones Requeridas (Prioridad)

1. **🔴 URGENTE:** Actualizar UMA 2026 a $117.31 diario / $3,566.22 mensual / $42,794.64 anual en `fiscal_tables.py` y propagar a `RATES["imss_uma_diario"]` en `payroll.py`.
2. **🟡 ALTA:** Verificar publicación DOF de tablas ISR 2026. Si están publicadas, actualizar `ISR_MENSUAL_2026`, `ISR_ANUAL_2026`, `ISR_QUINCENAL_2026`.
3. **🟡 ALTA:** Integrar `ERPRegistrar._send_to_erp()` con `ComputerUseDriverFactory` para habilitar ERP real vía Playwright.
4. **🟢 MEDIA:** Convertir `computer_use/__init__.py` a lazy imports para reducir startup time.
5. **🟢 MEDIA:** Agregar E2E tests con Chromium real (lanzar browser, navegar a página de prueba, verificar flujo).
6. **🔵 BAJA:** Configurar connection pool si se migra a PostgreSQL.

---

*Auditoría generada por Hermes Agent — B2B-AI-MVP Enterprise*
